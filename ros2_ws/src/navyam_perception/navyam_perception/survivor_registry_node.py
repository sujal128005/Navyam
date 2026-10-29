"""Survivor registry node: detections (map frame) -> confirmed survivors with grid labels.

Publishes /navyam/survivors (latched) for the mission and the GCS, and /navyam/survivor_markers for RViz.
"""
import rclpy
from builtin_interfaces.msg import Time as TimeMsg
from navyam_msgs.msg import DetectionArray, Survivor, SurvivorArray
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from visualization_msgs.msg import Marker, MarkerArray

from navyam_perception.grid import ArenaGrid
from navyam_perception.registry import SurvivorRegistry

LATCHED = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE)


class SurvivorRegistryNode(Node):
    def __init__(self) -> None:
        super().__init__("survivor_registry")
        p = self.declare_parameter
        self.grid = ArenaGrid(
            origin_x=p("grid_origin_x", 0.0).value,
            origin_y=p("grid_origin_y", 0.0).value,
            cell_m=p("grid_cell_m", 1.0).value,
            cols=p("grid_cols", 15).value,
            rows=p("grid_rows", 15).value,
            yaw=p("grid_yaw", 0.0).value,
        )
        self.registry = SurvivorRegistry(
            merge_radius_m=p("merge_radius_m", 0.7).value,
            confirm_hits=p("confirm_hits", 5).value,
            confirm_window_s=p("confirm_window_s", 1.5).value,
            stale_s=p("stale_s", 5.0).value,
            min_confidence=p("min_confidence", 0.4).value,
        )
        self.frame = p("map_frame", "map").value
        self.create_subscription(DetectionArray, "/navyam/detections", self.on_detections, 10)
        self.pub = self.create_publisher(SurvivorArray, "/navyam/survivors", LATCHED)
        self.marker_pub = self.create_publisher(MarkerArray, "/navyam/survivor_markers", LATCHED)
        self.create_timer(1.0, self.on_timer)
        self.get_logger().info(
            f"grid {self.grid.cols}x{self.grid.rows} cells of {self.grid.cell_m} m, "
            f"origin ({self.grid.origin_x:.2f}, {self.grid.origin_y:.2f})"
        )
        self.publish()

    def on_detections(self, msg: DetectionArray) -> None:
        if msg.header.frame_id != self.frame:
            self.get_logger().warn(
                f"ignoring detections in frame '{msg.header.frame_id}', expected '{self.frame}'",
                throttle_duration_sec=5.0,
            )
            return
        t = Time.from_msg(msg.header.stamp).nanoseconds * 1e-9
        changed = False
        for d in msg.detections:
            track = self.registry.add(d.position.x, d.position.y, d.confidence, t)
            if track is not None:
                changed = True
                label = self.grid.label_of(track.x, track.y) or "outside grid"
                self.get_logger().info(
                    f"survivor {track.id} confirmed at ({track.x:.2f}, {track.y:.2f}) -> {label}"
                )
        if changed:
            self.publish()

    def on_timer(self) -> None:
        self.registry.prune(self.get_clock().now().nanoseconds * 1e-9)
        self.publish()

    def publish(self) -> None:
        stamp = self.get_clock().now().to_msg()
        out = SurvivorArray()
        out.header.stamp, out.header.frame_id = stamp, self.frame
        markers = MarkerArray()
        for tr in self.registry.confirmed:
            s = Survivor()
            s.id = tr.id
            s.position.x, s.position.y = tr.x, tr.y
            cell = self.grid.cell_of(tr.x, tr.y)
            s.grid_col, s.grid_row = cell if cell else (-1, -1)
            s.grid_label = self.grid.label(*cell) if cell else ""
            s.confidence = float(tr.best_confidence)
            s.hits = tr.hits
            s.confirmed_at = _to_time_msg(tr.confirmed_at)
            out.survivors.append(s)
            markers.markers += self._markers(tr.id, tr.x, tr.y, s.grid_label or "?", stamp)
        self.pub.publish(out)
        self.marker_pub.publish(markers)

    def _markers(self, ident: int, x: float, y: float, label: str, stamp) -> list:
        dot = Marker()
        dot.header.frame_id, dot.header.stamp = self.frame, stamp
        dot.ns, dot.id, dot.type, dot.action = "survivors", ident, Marker.CYLINDER, Marker.ADD
        dot.pose.position.x, dot.pose.position.y, dot.pose.position.z = x, y, 0.1
        dot.pose.orientation.w = 1.0
        dot.scale.x = dot.scale.y = 0.4
        dot.scale.z = 0.2
        dot.color.r, dot.color.g, dot.color.b, dot.color.a = 0.95, 0.3, 0.05, 0.9
        text = Marker()
        text.header = dot.header
        text.ns, text.id, text.type, text.action = "survivor_labels", ident, Marker.TEXT_VIEW_FACING, Marker.ADD
        text.pose.position.x, text.pose.position.y, text.pose.position.z = x, y, 0.6
        text.pose.orientation.w = 1.0
        text.scale.z = 0.3
        text.color.r = text.color.g = text.color.b = text.color.a = 1.0
        text.text = f"S{ident} {label}"
        return [dot, text]


def _to_time_msg(seconds: float | None) -> TimeMsg:
    msg = TimeMsg()
    if seconds is not None:
        msg.sec = int(seconds)
        msg.nanosec = int((seconds - int(seconds)) * 1e9)
    return msg


def main() -> None:
    rclpy.init()
    node = SurvivorRegistryNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
