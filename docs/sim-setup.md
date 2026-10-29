# Simulation setup (phase P2)

Runs the whole mission loop on a laptop: Gazebo maze, ArduPilot SITL quad with a 2D LiDAR, Cartographer SLAM feeding the EKF, Nav2, frontier exploration, and the Navyam mission nodes.

**You need Ubuntu 22.04 on real hardware** (dual boot is fine). WSL2 can run it, but Gazebo is much slower there. An NVIDIA GPU helps.

## 1. ROS 2 Humble + Gazebo Harmonic + ArduPilot ROS 2 workspace

Follow ArduPilot's own guides, in this order. They are kept up to date with the exact package versions:

1. ROS 2 Humble desktop: https://docs.ros.org/en/humble/Installation/Ubuntu-Install-Debians.html
2. ArduPilot "ROS 2": https://ardupilot.org/dev/docs/ros2.html (workspace `~/ardu_ws`, Micro-XRCE-DDS-Gen, `ardupilot` + `ardupilot_msgs`)
3. ArduPilot "ROS 2 with SITL": https://ardupilot.org/dev/docs/ros2-sitl.html
4. ArduPilot "ROS 2 with Gazebo": https://ardupilot.org/dev/docs/ros2-gazebo.html (Gazebo Harmonic, `ardupilot_gz`, `GZ_VERSION=harmonic`)
5. ArduPilot "Cartographer SLAM with ROS 2 in SITL": https://ardupilot.org/dev/docs/ros2-cartographer-slam.html (`ardupilot_ros`)

**Gate before going further:** ArduPilot's own demo must work.

```bash
source ~/ardu_ws/install/setup.bash
ros2 launch ardupilot_gz_bringup iris_maze.launch.py lidar_dim:=2      # terminal 1
ros2 launch ardupilot_cartographer cartographer.launch.py              # terminal 2
```

You should see the map grow in RViz.

## 2. Add Nav2, explore_lite and Navyam

```bash
sudo apt install -y ros-humble-navigation2 ros-humble-nav2-bringup
cd ~/ardu_ws/src
git clone https://github.com/robo-friends/m-explore-ros2.git
ln -s ~/navyam/ros2_ws/src/navyam_msgs .
ln -s ~/navyam/ros2_ws/src/navyam_mission .
ln -s ~/navyam/ros2_ws/src/navyam_perception .
ln -s ~/navyam/ros2_ws/src/navyam_bringup .
cd ~/ardu_ws
rosdep install --from-paths src --ignore-src -r -y --skip-keys gazebo-ros-pkgs
colcon build --symlink-install --packages-up-to navyam_bringup explore_lite
source install/setup.bash
```

(`~/navyam` is this repository cloned on the Ubuntu machine.)

## 3. Generate a maze and fly the mission

```bash
cd ~/navyam
python3 sim/maze_gen/navyam_maze.py --seed 7 --out sim/worlds/nidar_s7 --ascii
ros2 launch navyam_bringup sim.launch.py world:=$HOME/navyam/sim/worlds/nidar_s7.sdf
```

Wait until RViz shows the map and the terminal prints `mission ready`, about 15 s after launch. Then start the mission in another terminal:

```bash
ros2 service call /navyam/start std_srvs/srv/Trigger
ros2 topic echo /navyam/status          # phase, reason, elapsed time, survivors
ros2 service call /navyam/abort std_srvs/srv/Trigger   # LAND now
```

Survivors use the Gazebo Fuel model "Rescue Randy", which downloads on the first run (internet needed once, then cached). Offline, add `--offline` to the generator for simple box mannequins.

Useful generator options: `--cell 1.0` (corridor width, default 1 m, the brief's minimum), `--rooms 6`, `--survivors 6`, `--braid 0.15` (loops), `--seed N`.

## 4. What to check on the first run

| Check | Command | Expected |
|---|---|---|
| LiDAR | `ros2 topic hz /scan` | ~10 Hz |
| SLAM into the EKF | `ros2 topic echo /ap/pose/filtered --once` | position near (0, 0) before takeoff, follows the drone |
| Map | RViz `/map` | walls appear as the drone moves |
| Mission start | `/navyam/status` | IDLE → TAKEOFF → EXPLORE |
| Navigation | `ros2 topic echo /ap/cmd_vel` | only during EXPLORE / RETURN |
| Exit | `/navyam/status` | RETURN → LAND → DONE near the launch box |

## Known gaps (next steps)

- **No camera on the SITL iris yet.** The survivor detector needs an RGB-D camera in simulation. Next step: a Navyam SITL model (iris + 2D LiDAR + depth camera). Until then `detector:=false`, and the registry, mission and GCS can be tested by publishing fake `/navyam/detections`.
- **ExternalNav path:** `sitl_extnav.parm` follows ArduPilot's Cartographer guide. Confirm on the first run that the EKF really uses the SLAM pose (MAVProxy `status` / EKF flags), not GPS.
- **1 m corridors with the iris** (radius ~0.35 m) are tight. If Nav2 can't find paths, try `--cell 1.5` first to separate tuning problems from geometry problems.
- **Web GCS** (map + survivors + video + abort) is not built yet.
- **Scoring script** to compare `/navyam/survivors` against `sim/worlds/NAME.yaml` ground truth is not built yet.
