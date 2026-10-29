"""Survivor detector: YOLO person detection on the D435i colour image, localized with aligned depth.

Input  : colour image + depth aligned to colour + its camera_info (realsense-ros topics by default)
Output : /navyam/detections (navyam_msgs/DetectionArray, map frame)
         /navyam/detector/image (annotated colour image, used for the GCS video)

Model: an Ultralytics YOLO file. Use a TensorRT engine on the Jetson for speed:
  yolo export model=best.pt format=engine half=True imgsz=640
"""
import time

import rclpy
import tf2_geometry_msgs  # noqa: F401  (registers PointStamped with tf2)
from cv_bridge import CvBridge
from geometry_msgs.msg import PointStamped
from message_filters import ApproximateTimeSynchronizer, Subscriber
from navyam_msgs.msg import Detection, DetectionArray
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo, Image
from tf2_ros import Buffer, TransformException, TransformListener

from navyam_perception.projection import box_depth_m, pixel_to_point

PERSON_CLASS = 0  # COCO "person"


class DetectorNode(Node):
    def __init__(self) -> None:
        super().__init__("survivor_detector")
        p = self.declare_parameter
        self.model_path = p("model", "yolo11n.pt").value
        self.conf = p("confidence", 0.5).value
        self.imgsz = p("imgsz", 640).value
        self.classes = list(p("classes", [PERSON_CLASS]).value)
        self.target_frame = p("target_frame", "map").value
        self.min_depth = p("min_depth_m", 0.3).value
        self.max_depth = p("max_depth_m", 6.0).value
        self.min_period = 1.0 / p("max_rate_hz", 10.0).value
        self.publish_image = p("publish_image", True).value
        color_topic = p("color_topic", "/camera/camera/color/image_raw").value
        depth_topic = p("depth_topic", "/camera/camera/aligned_depth_to_color/image_raw").value
        info_topic = p("info_topic", "/camera/camera/aligned_depth_to_color/camera_info").value

        from ultralytics import YOLO  # imported here so the rest of the package works without it
        self.model = YOLO(self.model_path)
        self.get_logger().info(f"loaded detector model {self.model_path}")

        self.bridge = CvBridge()
        self.K = None
        self.last_run = 0.0
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.create_subscription(CameraInfo, info_topic, self.on_info, qos_profile_sensor_data)
        color = Subscriber(self, Image, color_topic, qos_profile=qos_profile_sensor_data)
        depth = Subscriber(self, Image, depth_topic, qos_profile=qos_profile_sensor_data)
        self.sync = ApproximateTimeSynchronizer([color, depth], queue_size=5, slop=0.05)
        self.sync.registerCallback(self.on_frames)
        self.det_pub = self.create_publisher(DetectionArray, "/navyam/detections", 10)
        self.img_pub = self.create_publisher(Image, "/navyam/detector/image", qos_profile_sensor_data)

    def on_info(self, msg: CameraInfo) -> None:
        k = msg.k
        self.K = (k[0], k[4], k[2], k[5])  # fx, fy, cx, cy

    def on_frames(self, color: Image, depth: Image) -> None:
        now = time.monotonic()
        if self.K is None or now - self.last_run < self.min_period:
            return
        self.last_run = now

        try:
            tf = self.tf_buffer.lookup_transform(
                self.target_frame, depth.header.frame_id, Time.from_msg(depth.header.stamp),
                timeout=Duration(seconds=0.05),
            )
        except TransformException as exc:
            self.get_logger().warn(f"no transform to {self.target_frame}: {exc}", throttle_duration_sec=5.0)
            return

        img = self.bridge.imgmsg_to_cv2(color, desired_encoding="bgr8")
        dimg = self.bridge.imgmsg_to_cv2(depth, desired_encoding="passthrough")
        scale = 0.001 if dimg.dtype.kind == "u" else 1.0  # 16UC1 is millimetres, 32FC1 metres
        result = self.model.predict(img, conf=self.conf, classes=self.classes, imgsz=self.imgsz, verbose=False)[0]

        out = DetectionArray()
        out.header.stamp, out.header.frame_id = depth.header.stamp, self.target_frame
        fx, fy, cx, cy = self.K
        for xyxy, conf in zip(result.boxes.xyxy.tolist(), result.boxes.conf.tolist()):
            d = box_depth_m(dimg, tuple(xyxy), scale, min_m=self.min_depth, max_m=self.max_depth)
            if d is None:
                continue
            u, v = (xyxy[0] + xyxy[2]) / 2, (xyxy[1] + xyxy[3]) / 2
            pt = PointStamped()
            pt.header = depth.header
            pt.point.x, pt.point.y, pt.point.z = pixel_to_point(u, v, d, fx, fy, cx, cy)
            p_map = tf2_geometry_msgs.do_transform_point(pt, tf)
            det = Detection()
            det.position = p_map.point
            det.confidence = float(conf)
            out.detections.append(det)
        self.det_pub.publish(out)

        if self.publish_image:
            annotated = self.bridge.cv2_to_imgmsg(result.plot(), encoding="bgr8")
            annotated.header = color.header
            self.img_pub.publish(annotated)


def main() -> None:
    rclpy.init()
    node = DetectorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
