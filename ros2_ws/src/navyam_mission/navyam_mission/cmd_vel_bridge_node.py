"""Nav2 -> ArduPilot velocity bridge.

* Forwards Nav2's /cmd_vel (geometry_msgs/Twist, body frame) to ArduPilot's /ap/cmd_vel
  (TwistStamped, frame "base_link"), capped to indoor speeds, with altitude hold on top.
* Forwards nothing unless the mission has enabled navigation (/navyam/nav_enabled), so it
  never fights ArduPilot's own takeoff or landing.
* While enabled, a stale /cmd_vel (watchdog) becomes "hover here".
* Republishes the EKF velocity as /odom (body-frame twist), which Nav2's controller needs.
"""
import rclpy
from geometry_msgs.msg import PoseStamped, Twist, TwistStamped
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from std_msgs.msg import Bool

from navyam_mission.velocity import VelocityLimits, body_command, earth_to_body, yaw_from_quaternion

LATCHED = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE)


class CmdVelBridge(Node):
    def __init__(self) -> None:
        super().__init__("cmd_vel_bridge")
        p = self.declare_parameter
        self.z_target = p("takeoff_alt_m", 1.1).value
        self.lim = VelocityLimits(
            max_xy=p("max_xy", 0.6).value,
            max_yaw_rate=p("max_yaw_rate", 0.8).value,
            max_vz=p("max_vz", 0.3).value,
            kz=p("kz", 0.8).value,
        )
        self.timeout_ns = int(p("cmd_timeout_s", 0.5).value * 1e9)
        rate_hz = p("rate_hz", 20.0).value

        self.enabled = False
        self.cmd: Twist | None = None
        self.cmd_time = None
        self.pose: PoseStamped | None = None
        self.yaw: float | None = None

        self.create_subscription(Twist, "/cmd_vel", self.on_cmd, 10)
        self.create_subscription(Bool, "/navyam/nav_enabled", self.on_enabled, LATCHED)
        self.create_subscription(PoseStamped, "/ap/pose/filtered", self.on_pose, qos_profile_sensor_data)
        self.create_subscription(TwistStamped, "/ap/twist/filtered", self.on_twist, qos_profile_sensor_data)
        self.pub = self.create_publisher(TwistStamped, "/ap/cmd_vel", 10)
        self.odom_pub = self.create_publisher(Odometry, "/odom", 10)
        self.create_timer(1.0 / rate_hz, self.tick)

    def on_cmd(self, msg: Twist) -> None:
        self.cmd, self.cmd_time = msg, self.get_clock().now()

    def on_enabled(self, msg: Bool) -> None:
        if msg.data != self.enabled:
            self.get_logger().info(f"navigation {'enabled' if msg.data else 'disabled'}")
        self.enabled = msg.data

    def on_pose(self, msg: PoseStamped) -> None:
        self.pose = msg
        q = msg.pose.orientation
        self.yaw = yaw_from_quaternion(q.x, q.y, q.z, q.w)

    def on_twist(self, msg: TwistStamped) -> None:
        lin = msg.twist.linear
        if msg.header.frame_id == "base_link":
            vx, vy = lin.x, lin.y
        elif self.yaw is not None:
            vx, vy = earth_to_body(lin.x, lin.y, self.yaw)
        else:
            return
        odom = Odometry()
        odom.header.stamp = msg.header.stamp
        odom.header.frame_id = "odom"
        odom.child_frame_id = "base_link"
        if self.pose is not None:
            odom.pose.pose = self.pose.pose
        odom.twist.twist.linear.x, odom.twist.twist.linear.y = vx, vy
        odom.twist.twist.linear.z = lin.z
        odom.twist.twist.angular = msg.twist.angular
        self.odom_pub.publish(odom)

    def tick(self) -> None:
        if not self.enabled:
            return
        now = self.get_clock().now()
        fresh = self.cmd is not None and (now - self.cmd_time).nanoseconds <= self.timeout_ns
        vx, vy, wz = (self.cmd.linear.x, self.cmd.linear.y, self.cmd.angular.z) if fresh else (0.0, 0.0, 0.0)
        z = self.pose.pose.position.z if self.pose is not None else None
        vx, vy, vz, wz = body_command(vx, vy, wz, z, self.z_target, self.lim)

        out = TwistStamped()
        out.header.stamp = now.to_msg()
        out.header.frame_id = "base_link"
        out.twist.linear.x, out.twist.linear.y, out.twist.linear.z = vx, vy, vz
        out.twist.angular.z = wz
        self.pub.publish(out)


def main() -> None:
    rclpy.init()
    node = CmdVelBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
