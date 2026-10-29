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
No quad with 13" props fits the 610 mm launch box. A compact 7" frame (≤ 450 mm with guards) is the competition airframe. This is pending the team's frame measurements.

## D-006 · Survivor grid labels are configurable (2026-10-29)
The organizers have not yet published the grid convention. `navyam_perception.grid.ArenaGrid` takes origin, yaw, cell size and label style as parameters. The default labels columns A, B, C… along the arena x axis and rows 1, 2, 3… along y, counted from the arena corner on the entry side.
