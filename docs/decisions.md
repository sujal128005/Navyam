# Decisions log

Short records of choices that shape the system. Newest at the bottom. Change a decision by adding a new entry that supersedes the old one.

## D-001 · ArduPilot Copter, not PX4 (2026-10-29)
The brief names Mission Planner, which is ArduPilot's GCS. ArduPilot has EKF3 ExternalNav, SmartRTL for the "recall" failsafe, and an official ROS 2 maze simulation with a 2D LiDAR and Cartographer.

## D-002 · 2D LiDAR SLAM is the primary position source (2026-10-29)
The LDROBOT D500 (360°, 12 m, 10 Hz) feeds SLAM, and the SLAM pose goes to EKF3 as ExternalNav (position and yaw). Maze walls are likely plain panels with few visual features, and the scenario mentions low visibility. Visual SLAM on the D435i stays a later option as a second EKF source.

## D-003 · ArduPilot DDS interface, MAVROS as fallback (2026-10-29)
We use ArduPilot's native ROS 2 DDS interface (`/ap/cmd_vel`, `/ap/pose/filtered`, `/ap/arm_motors`, `/ap/mode_switch`, `/ap/experimental/takeoff`), the same path ArduPilot's own SLAM simulation uses. If the serial DDS link proves unreliable on the Cube, or the Cube firmware build lacks DDS, we switch to MAVROS.

## D-004 · Fly as a holonomic 2D robot (2026-10-29)
ArduPilot holds altitude (rangefinder) and attitude. Above that, everything is the standard ROS 2 2D navigation stack: Nav2 with a holonomic DWB controller and frontier exploration. Our `cmd_vel_bridge` adds altitude correction and a watchdog, and only forwards commands while the mission enables navigation.

## D-005 · Current 13" airframe is the development mule (2026-10-29)
No quad with 13" props fits the 610 mm launch box. A compact 7" frame (≤ 450 mm with guards) is the competition airframe. Confirmed by the team's measurement (2026-10-29): 105 cm prop tip to prop tip and 83 cm frame end to end, both diagonal. The box's own diagonal is 86 cm, so the mule fits in no orientation, and it would leave only 5–8 cm a side in a 1 m corridor.

## D-006 · Survivor grid labels are configurable (2026-10-29)
The organizers have not yet published the grid convention. `navyam_perception.grid.ArenaGrid` takes origin, yaw, cell size and label style as parameters. The default labels columns A, B, C… along the arena x axis and rows 1, 2, 3… along y, counted from the arena corner on the entry side.

## D-007 · RC link: FlySky now, ELRS for the competition (2026-10-29)
The mule flies a FlySky transmitter with an FS-iA6B receiver on RCIN. That's fine for development once its throttle failsafe is configured (see `firmware/ardupilot/navyam_base.param`). The competition frame gets an ELRS receiver for the TX16S already in the BOM: a clean no-signal failsafe and enough channels for kill, mode and abort switches.

## D-008 · Team computers (2026-10-29)
- **Dell RTX gaming laptop:** dual-boot Ubuntu 22.04. Used for simulation (Gazebo + SITL) and YOLO training.
- **Samsung Galaxy Book Pro 360:** stays on Windows as the GCS laptop, running Mission Planner and the Navyam GCS page in a browser.
- **Jetson:** the only computer on the drone.
