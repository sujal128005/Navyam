"""Mission node: runs the state machine and executes its actions over ArduPilot DDS and Nav2.

Operator interface (the only allowed inputs during a NIDAR run):
  ros2 service call /navyam/start std_srvs/srv/Trigger
  ros2 service call /navyam/abort std_srvs/srv/Trigger
"""
import math
from collections import deque
from dataclasses import fields

import rclpy
from action_msgs.msg import GoalStatus
from ardupilot_msgs.msg import Status
from ardupilot_msgs.srv import ArmMotors, ModeSwitch, Takeoff as TakeoffSrv
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import OccupancyGrid
from navyam_msgs.msg import MissionStatus, SurvivorArray
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import BatteryState
from std_msgs.msg import Bool
from std_srvs.srv import Trigger
from tf2_ros import Buffer, TransformException, TransformListener

from navyam_mission.state_machine import (
    COPTER_MODE_LAND, Arm, CancelNav, Explore, Inputs, Mission, MissionConfig, NavEnable, NavigateHome,
    Phase, SetMode, Takeoff,
)

LATCHED = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE)
SERVICE_WAIT_S = 3.0
LAND_RETRIES = 5


class MissionNode(Node):
    def __init__(self) -> None:
        super().__init__("mission")
        defaults = MissionConfig()
        cfg = MissionConfig(**{
            f.name: self.declare_parameter(f.name, getattr(defaults, f.name)).value for f in fields(MissionConfig)
        })
        self.home = (self.declare_parameter("home_x", 0.0).value, self.declare_parameter("home_y", 0.0).value)
        self.mission = Mission(cfg)

        # Latest world state
        self.armed = False
        self.altitude: float | None = None
        self.battery_pct: float | None = None
        self.survivors = 0
        self.known_cells = 0
        self.map_resolution = 0.05
        self.start_requested = False
        self.abort_reason: str | None = None
        self.nav_failed = False

        # Action execution
        self.queue: deque = deque()
        self.busy = False
        self.waiting_since = None
        self.land_attempts = 0
        self.goal_handle = None
        self.nav_cancelled = False

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.create_subscription(Status, "/ap/status", self.on_status, qos_profile_sensor_data)
        self.create_subscription(BatteryState, "/ap/battery", self.on_battery, qos_profile_sensor_data)
        self.create_subscription(PoseStamped, "/ap/pose/filtered", self.on_pose, qos_profile_sensor_data)
        self.create_subscription(OccupancyGrid, "/map", self.on_map, QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE))
        self.create_subscription(SurvivorArray, "/navyam/survivors", self.on_survivors, LATCHED)

        self.status_pub = self.create_publisher(MissionStatus, "/navyam/status", 10)
        self.explore_pub = self.create_publisher(Bool, "/explore/resume", 10)
        self.nav_enabled_pub = self.create_publisher(Bool, "/navyam/nav_enabled", LATCHED)
        self.nav_enabled_pub.publish(Bool(data=False))

        self.mode_cli = self.create_client(ModeSwitch, "/ap/mode_switch")
        self.arm_cli = self.create_client(ArmMotors, "/ap/arm_motors")
        self.takeoff_cli = self.create_client(TakeoffSrv, "/ap/experimental/takeoff")
        self.prearm_cli = self.create_client(Trigger, "/ap/prearm_check")
        self.nav_client = ActionClient(self, NavigateToPose, "navigate_to_pose")

        self.create_service(Trigger, "/navyam/start", self.on_start)
        self.create_service(Trigger, "/navyam/abort", self.on_abort)

        self.create_timer(0.2, self.tick)
        self.create_timer(0.5, self.publish_status)
        self.create_timer(1.0, self.hold_explorer)
        self.get_logger().info("mission ready: call /navyam/start to begin")

    # ---------- inputs ----------
    def on_status(self, msg: Status) -> None:
        self.armed = msg.armed

    def on_battery(self, msg: BatteryState) -> None:
        self.battery_pct = None if math.isnan(msg.percentage) else msg.percentage * 100.0

    def on_pose(self, msg: PoseStamped) -> None:
        self.altitude = msg.pose.position.z

    def on_map(self, msg: OccupancyGrid) -> None:
        self.known_cells = len(msg.data) - msg.data.count(-1)
        self.map_resolution = msg.info.resolution

    def on_survivors(self, msg: SurvivorArray) -> None:
        self.survivors = len(msg.survivors)

    def on_start(self, _req, res):
        if self.mission.phase is not Phase.IDLE:
            res.success, res.message = False, f"mission already in {self.mission.phase.value}"
            return res
        if not self.prearm_cli.service_is_ready():
            res.success, res.message = False, "ArduPilot /ap/prearm_check not available"
            return res
        self.prearm_cli.call_async(Trigger.Request()).add_done_callback(self.on_prearm)
        res.success, res.message = True, "pre-arm check running; mission starts if it passes"
        return res

    def on_prearm(self, fut) -> None:
        result = fut.result()
        if result is not None and result.success:
            self.start_requested = True
        else:
            self.get_logger().error(f"pre-arm check failed, not starting: {getattr(result, 'message', 'no reply')}")

    def on_abort(self, _req, res):
        self.abort_reason = "operator abort"
        res.success, res.message = True, "aborting: LAND"
        return res

    def dist_home(self) -> float | None:
        try:
            tf = self.tf_buffer.lookup_transform("map", "base_link", Time())
        except TransformException:
            return None
        t = tf.transform.translation
        return math.hypot(t.x - self.home[0], t.y - self.home[1])

    # ---------- main loop ----------
    def tick(self) -> None:
        now = self.get_clock().now().nanoseconds * 1e-9
        actions = self.mission.step(Inputs(
            now=now, start=self.start_requested, abort=self.abort_reason is not None,
            abort_reason=self.abort_reason or "", armed=self.armed, altitude_m=self.altitude,
            battery_pct=self.battery_pct, survivors=self.survivors, known_cells=self.known_cells,
            dist_home_m=self.dist_home(), nav_failed=self.nav_failed,
        ))
        self.start_requested = False
        self.abort_reason = None
        self.nav_failed = False
        if self.mission.phase is Phase.ABORTED and actions:
            self.queue.clear()  # an abort replaces anything still pending
        for a in actions:
            self.get_logger().info(f"[{self.mission.phase.value}] {self.mission.reason} -> {a}")
            self.queue.append(a)
        self.run_queue(now)

    def run_queue(self, now: float) -> None:
        while self.queue and not self.busy:
            action = self.queue[0]
            if isinstance(action, Explore):
                self.explore_pub.publish(Bool(data=action.enable))
            elif isinstance(action, NavEnable):
                self.nav_enabled_pub.publish(Bool(data=action.enable))
            elif isinstance(action, NavigateHome):
                self.navigate_home()
            elif isinstance(action, CancelNav):
                self.cancel_nav()
            else:
                client, request = self.service_for(action)
                if not client.service_is_ready():
                    self.waiting_since = self.waiting_since or now
                    if now - self.waiting_since > SERVICE_WAIT_S and not self.is_land(action):
                        self.queue.popleft()
                        self.waiting_since = None
                        self.abort_reason = f"ArduPilot service {client.srv_name} unavailable"
                    return
                self.waiting_since = None
                self.busy = True
                client.call_async(request).add_done_callback(lambda fut, a=action: self.on_service_done(a, fut))
            self.queue.popleft()

    def service_for(self, action):
        if isinstance(action, SetMode):
            return self.mode_cli, ModeSwitch.Request(mode=action.mode)
        if isinstance(action, Arm):
            return self.arm_cli, ArmMotors.Request(arm=action.arm)
        if isinstance(action, Takeoff):
            return self.takeoff_cli, TakeoffSrv.Request(alt=float(action.alt_m))
        raise TypeError(f"unknown action {action}")

    @staticmethod
    def is_land(action) -> bool:
        return isinstance(action, SetMode) and action.mode == COPTER_MODE_LAND

    def on_service_done(self, action, fut) -> None:
        self.busy = False
        res = fut.result()
        ok = res is not None and bool(getattr(res, "status", getattr(res, "result", False)))
        if ok:
            return
        self.get_logger().error(f"{action} failed")
        if self.is_land(action) and self.land_attempts < LAND_RETRIES:
            self.land_attempts += 1
            self.queue.appendleft(action)
        elif not self.is_land(action) and self.mission.phase not in (Phase.ABORTED, Phase.LAND, Phase.DONE):
            self.abort_reason = f"{type(action).__name__} rejected by ArduPilot"

    # ---------- Nav2 ----------
    def navigate_home(self) -> None:
        if not self.nav_client.server_is_ready():
            self.get_logger().error("Nav2 navigate_to_pose not available")
            self.nav_failed = True
            return
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = "map"
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x, goal.pose.pose.position.y = self.home
        goal.pose.pose.orientation.w = 1.0
        self.nav_cancelled = False
        self.nav_client.send_goal_async(goal).add_done_callback(self.on_goal_response)

    def on_goal_response(self, fut) -> None:
        handle = fut.result()
        if handle is None or not handle.accepted:
            self.get_logger().error("Nav2 rejected the return-to-exit goal")
            self.nav_failed = True
            return
        self.goal_handle = handle
        handle.get_result_async().add_done_callback(self.on_nav_result)

    def on_nav_result(self, fut) -> None:
        self.goal_handle = None
        status = fut.result().status
        if status != GoalStatus.STATUS_SUCCEEDED and not self.nav_cancelled:
            self.get_logger().warn(f"return-to-exit ended with status {status}")
            self.nav_failed = True

    def cancel_nav(self) -> None:
        if self.goal_handle is not None:
            self.nav_cancelled = True
            self.goal_handle.cancel_goal_async()

    # ---------- outputs ----------
    def hold_explorer(self) -> None:
        # explore_lite starts exploring as soon as it launches; keep it paused outside EXPLORE.
        if self.mission.phase is not Phase.EXPLORE:
            self.explore_pub.publish(Bool(data=False))

    def publish_status(self) -> None:
        now = self.get_clock().now()
        msg = MissionStatus()
        msg.header.stamp = now.to_msg()
        msg.phase = self.mission.phase.value
        msg.reason = self.mission.reason
        msg.elapsed_s = float(self.mission.elapsed(now.nanoseconds * 1e-9))
        msg.battery_pct = float("nan") if self.battery_pct is None else float(self.battery_pct)
        msg.survivors_confirmed = min(self.survivors, 255)
        msg.survivors_expected = min(self.mission.cfg.expected_survivors, 255)
        msg.explored_area_m2 = float(self.known_cells * self.map_resolution ** 2)
        self.status_pub.publish(msg)


def main() -> None:
    rclpy.init()
    node = MissionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
