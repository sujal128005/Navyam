# Navyam

Autonomous GPS-denied indoor drone for **NIDAR Track 1, "AirMouse"**. The drone enters a covered maze from the entry point, maps it, tags up to six survivors on a live 2D grid map, and flies back out without GPS or any external network.

- Technical plan (hardware audit, architecture, roadmap): https://claude.ai/artifact/CnLirskgnm34gcxoTpN89Y
- Decisions log: [docs/decisions.md](docs/decisions.md)
- Simulation setup: [docs/sim-setup.md](docs/sim-setup.md)

## Stack

| Layer | Choice |
|---|---|
| Flight controller | Cube Orange(+) running ArduPilot Copter 4.5/4.6 |
| Companion | Jetson Orin Nano Super (8 GB), JetPack 6.2, Ubuntu 22.04, ROS 2 Humble |
| Localization | LDROBOT D500 2D LiDAR → SLAM (Cartographer in sim) → EKF3 ExternalNav |
| ROS ↔ ArduPilot | ArduPilot DDS (`/ap/*` topics and services) over Micro XRCE-DDS |
| Navigation | Nav2 (holonomic DWB) + `explore_lite` frontier exploration |
| Survivors | RealSense D435i + YOLO (TensorRT) → depth projection → registry → grid cell |
| GCS | Mission Planner (telemetry, video, abort) + Navyam web GCS page (to come) |

## Repository layout

```
docs/                     plan notes, decisions, setup guides
firmware/ardupilot/       parameter files for the Cube
sim/maze_gen/             NIDAR-style maze world generator (pure Python, no ROS needed)
sim/worlds/               generated Gazebo worlds + their ground-truth/grid YAML
ros2_ws/src/
  navyam_msgs/            Detection, Survivor, SurvivorArray, MissionStatus
  navyam_perception/      grid maths, survivor registry, YOLO detector node
  navyam_mission/         mission state machine, cmd_vel → ArduPilot bridge
  navyam_bringup/         launch files and configs (sim first)
tools/                    helper scripts
```

## Quick checks (any OS with Python 3.10+)

The pure-Python parts (maze generator, grid maths, survivor registry, mission state machine) have unit tests that run without ROS:

```bash
python -m unittest discover -s sim/maze_gen -v
(cd ros2_ws/src/navyam_perception && python -m unittest discover -s test -v)   # needs numpy
(cd ros2_ws/src/navyam_mission && python -m unittest discover -s test -v)
```

## Generate a maze world

```bash
python sim/maze_gen/navyam_maze.py --seed 7 --out sim/worlds/nidar_s7 --ascii
```

This writes `nidar_s7.sdf` (Gazebo world) and `nidar_s7.yaml` (grid parameters and survivor ground truth).

## Status

Phase P2 (simulation) scaffolding. Nothing here has flown. See the roadmap in the plan.
