"""Full Navyam mission in simulation: Gazebo maze + ArduPilot SITL iris with 2D LiDAR + Cartographer
+ Nav2 + explore_lite + Navyam mission, velocity bridge and survivor registry.

  ros2 launch navyam_bringup sim.launch.py world:=/abs/path/to/sim/worlds/nidar_s7.sdf

Then start the mission (the only operator input besides abort):
  ros2 service call /navyam/start std_srvs/srv/Trigger

The SITL iris has no camera yet, so the survivor detector is off here (detector:=false).
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

SITL_DEFAULTS = ("copter.parm", "gazebo-iris.parm", "dds_udp.parm", "dds_use_ns.parm")


def _launch(pkg: str, *path: str) -> PythonLaunchDescriptionSource:
    return PythonLaunchDescriptionSource(os.path.join(get_package_share_directory(pkg), *path))


def _setup(context):
    world = os.path.abspath(LaunchConfiguration("world").perform(context))
    if not os.path.isfile(world):
        raise RuntimeError(f"world file not found: {world} (generate one with sim/maze_gen/navyam_maze.py)")
    world_name = os.path.splitext(os.path.basename(world))[0]
    grid_params = LaunchConfiguration("grid_params").perform(context) or os.path.splitext(world)[0] + ".params.yaml"
    if not os.path.isfile(grid_params):
        raise RuntimeError(f"grid params not found: {grid_params}")
    gui = LaunchConfiguration("gui").perform(context).lower() == "true"
    rviz = LaunchConfiguration("rviz").perform(context)
    nav_delay = float(LaunchConfiguration("nav_delay_s").perform(context))
    detector = LaunchConfiguration("detector").perform(context).lower() == "true"

    cfg_dir = os.path.join(get_package_share_directory("navyam_bringup"), "config")
    cfg = lambda name: os.path.join(cfg_dir, name)  # noqa: E731
    sitl_dir = os.path.join(get_package_share_directory("ardupilot_sitl"), "config", "default_params")
    defaults = ",".join([os.path.join(sitl_dir, f) for f in SITL_DEFAULTS] + [cfg("sitl_extnav.parm")])
    sim_time = {"use_sim_time": True}
    tf_remaps = [("/tf", "tf"), ("/tf_static", "tf_static")]

    actions = [
        IncludeLaunchDescription(
            _launch("ros_gz_sim", "launch", "gz_sim.launch.py"),
            launch_arguments={"gz_args": f"-v4 -s -r {world}"}.items(),
        ),
        IncludeLaunchDescription(
            _launch("ardupilot_gz_bringup", "launch", "robots", "iris_lidar.launch.py"),
            launch_arguments={"world_name": world_name, "lidar_dim": "2", "defaults": defaults}.items(),
        ),
        IncludeLaunchDescription(
            _launch("ardupilot_cartographer", "launch", "cartographer.launch.py"),
            launch_arguments={"rviz": rviz, "use_sim_time": "true"}.items(),
        ),
    ]
    if gui:
        actions.append(IncludeLaunchDescription(
            _launch("ros_gz_sim", "launch", "gz_sim.launch.py"),
            launch_arguments={"gz_args": "-v4 -g"}.items(),
        ))

    navyam_params = [cfg("navyam.yaml"), grid_params, sim_time]
    late = [
        IncludeLaunchDescription(
            _launch("nav2_bringup", "launch", "navigation_launch.py"),
            launch_arguments={"params_file": cfg("nav2_sim.yaml"), "use_sim_time": "true", "autostart": "true"}.items(),
        ),
        Node(package="explore_lite", executable="explore", name="explore_node", output="screen",
             parameters=[cfg("explore.yaml"), sim_time], remappings=tf_remaps),
        Node(package="navyam_mission", executable="cmd_vel_bridge", name="cmd_vel_bridge", output="screen",
             parameters=navyam_params),
        Node(package="navyam_mission", executable="mission", name="mission", output="screen",
             parameters=navyam_params),
        Node(package="navyam_perception", executable="survivor_registry", name="survivor_registry", output="screen",
             parameters=navyam_params),
    ]
    if detector:
        late.append(Node(package="navyam_perception", executable="survivor_detector", name="survivor_detector",
                         output="screen", parameters=navyam_params))
    # Give SITL, the DDS agent and Cartographer time to publish TF and /map before Nav2 starts.
    actions.append(TimerAction(period=nav_delay, actions=late))
    return actions


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription([
        DeclareLaunchArgument("world", description="absolute path to a generated .sdf world"),
        DeclareLaunchArgument("grid_params", default_value="", description="defaults to WORLD.params.yaml"),
        DeclareLaunchArgument("gui", default_value="true", description="open the Gazebo GUI"),
        DeclareLaunchArgument("rviz", default_value="true", description="open RViz (Cartographer's config)"),
        DeclareLaunchArgument("nav_delay_s", default_value="15.0", description="delay before Nav2 and Navyam nodes"),
        DeclareLaunchArgument("detector", default_value="false", description="run the YOLO survivor detector"),
        OpaqueFunction(function=_setup),
    ])
