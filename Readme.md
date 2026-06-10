# Level-1 Autonomous Drone Mission
## Takeoff → Altitude Hold → Land (No GPS, Outdoor)
### Hardware: Jetson Orin Nano + RealSense D435i + Pixhawk Cube Orange

---

## Overview of what we're building

```
D435i (facing down)
    ↓  depth image (ROS 2 topic)
Jetson: rangefinder_bridge node
    ↓  sensor_msgs/Range → MAVROS
MAVROS
    ↓  MAVLink DISTANCE_SENSOR message
Pixhawk Cube Orange
    ↓  EKF uses rangefinder as altitude source
    ↓  GUIDED mode accepts velocity setpoints
Jetson: mission_node
    ↓  cmd_vel setpoints (takeoff / hold / land)
Pixhawk → ESCs → Motors
```

---

## STEP 1 — Physical Setup

### 1.1 Mount the RealSense D435i
- Mount **pointing straight down** on the drone body
- Ensure it has a clear view of the ground (no propellers in frame)
- Use a vibration-dampening mount (silicone grommets) — vibration kills depth accuracy
- Outdoors: add a small sun shield (cardboard visor) to reduce IR interference

### 1.2 Wire Jetson ↔ Pixhawk
```
Pixhawk Cube Orange  TELEM2 port  →  Jetson UART
   Pin 2 (TX)    →   Jetson RX (via 3.3V logic level — Cube Orange is 3.3V safe)
   Pin 3 (RX)    →   Jetson TX
   Pin 1 (VCC)   →   DO NOT connect (use separate 5V for Jetson)
   Pin 6 (GND)   →   Jetson GND

OR use USB: Pixhawk USB ↔ Jetson USB-A
   (easier for testing, use UART for final build — more reliable)
```

### 1.3 Connect RealSense to Jetson
- Use the **USB 3.0 port** (blue) on Jetson — USB 2 is too slow for depth
- Keep cable under 1m for reliability

---

## STEP 2 — Install Software on Jetson Orin Nano

### 2.1 JetPack
Flash **JetPack 6.0** using SDK Manager on a host PC.
Verify after boot:
```bash
cat /etc/nv_tegra_release    # should show R36 (JetPack 6.x)
```

### 2.2 ROS 2 Humble
```bash
# Add ROS 2 apt repo
sudo apt install software-properties-common curl -y
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
     -o /usr/share/keyrings/ros-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) \
     signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] \
     http://packages.ros.org/ros2/ubuntu jammy main" \
     | sudo tee /etc/apt/sources.list.d/ros2.list

sudo apt update
sudo apt install ros-humble-desktop python3-colcon-common-extensions -y

# Add to bashrc
echo "source /opt/ros/humble/setup.bash" >> ~/.bashrc
source ~/.bashrc
```

### 2.3 Intel RealSense SDK + ROS 2 wrapper
```bash
# RealSense SDK (librealsense2)
sudo apt-key adv --keyserver keys.gnupg.net \
     --recv-key F6E65AC044F831AC80A06380C8B3A55A6F3EFCDE
sudo add-apt-repository \
     "deb https://librealsense.intel.com/Debian/apt-repo jammy main"
sudo apt update
sudo apt install librealsense2-dkms librealsense2-utils \
                 librealsense2-dev librealsense2-dbg -y

# Test D435i is working
realsense-viewer    # should show depth stream

# ROS 2 wrapper
sudo apt install ros-humble-realsense2-camera -y
```

### 2.4 MAVROS
```bash
sudo apt install ros-humble-mavros ros-humble-mavros-extras -y

# Install GeographicLib datasets (required by MAVROS)
sudo /opt/ros/humble/lib/mavros/install_geographiclib_datasets.sh
```

### 2.5 Build this package
```bash
# Create workspace
mkdir -p ~/ros2_ws/src
cd ~/ros2_ws/src

# Copy the drone_l1 package folder here
cp -r /path/to/drone_l1 .

# Create resource marker file (required by ROS 2)
mkdir -p drone_l1/resource
touch drone_l1/resource/drone_l1

# Build
cd ~/ros2_ws
colcon build --packages-select drone_l1
source install/setup.bash
```

---

## STEP 3 — Configure Pixhawk Cube Orange (ArduCopter)

### 3.1 Flash ArduCopter firmware
- Use **Mission Planner** (Windows) or **QGroundControl** (any OS)
- Install ArduCopter **4.4.x** or later
- Cube Orange → select "CubeOrange" target

### 3.2 Load parameters
In Mission Planner: **Config → Full Parameter List → Load from file**
Load: `config/ardupilot_params.param`
Click **Write Params**, then **Reboot**

### 3.3 Mandatory calibrations (do these in order)
```
1. Accelerometer calibration   → Initial Setup → Mandatory Hardware → Accel Calibration
2. Compass calibration         → Initial Setup → Mandatory Hardware → Compass
3. Radio calibration           → Initial Setup → Mandatory Hardware → Radio Calibration
4. ESC calibration             → do per your ESC type (BLHeli / standard PWM)
5. Motor test                  → Optional Hardware → Motor Test → verify rotation direction
```

### 3.4 Verify rangefinder is working
1. Connect Jetson → run `ros2 launch drone_l1 mission_l1.launch.py` (without arming)
2. In Mission Planner: **Ctrl+F → Proximity** or check `sonarrange` in Status tab
3. Move drone up/down by hand — value should track distance to floor
4. Confirm it reads **correctly at 0.5 m, 1.0 m, 2.0 m**

---

## STEP 4 — Pre-flight Checks (do every flight)

```bash
# On Jetson:
# 1. Check D435i is detected
rs-enumerate-devices | grep D435

# 2. Check Pixhawk serial port
ls /dev/ttyUSB*   # or /dev/ttyACM0

# 3. Check ROS topics come up
ros2 launch drone_l1 mission_l1.launch.py &
sleep 10
ros2 topic list   # should see /mavros/state, /camera/depth/image_rect_raw, etc.
ros2 topic echo /mavros/state --once   # check connected:true, armed:false

# 4. Check rangefinder is publishing
ros2 topic echo /mavros/rangefinder/rangefinder --once
# Should show range: ~0.x (distance to ground while sitting)
```

Physical checks:
- [ ] Props tight, correct rotation direction
- [ ] Battery fully charged
- [ ] Area clear of people — minimum 10m radius
- [ ] RC transmitter on, switch in STABILIZE position
- [ ] Wind < 4 m/s (calm conditions only for first flights)

---

## STEP 5 — Test Flight Sequence

### Test 1: Manual ALTHOLD (before any autonomous flight)
1. Switch RC to ALTHOLD mode
2. Arm and take off manually
3. Verify drone holds altitude when you let go of throttle at ~1.5m
4. Land manually
5. If ALTHOLD is not stable → tune `PSC_VELZ_P` in Mission Planner

### Test 2: Short autonomous mission
```bash
# Edit mission_node.py: set TARGET_ALTITUDE = 1.5, HOLD_DURATION = 5.0
# Then launch:
ros2 launch drone_l1 mission_l1.launch.py target_altitude:=1.5 hold_duration:=5.0
```
- Stand by with RC transmitter
- If anything looks wrong → flip to STABILIZE immediately

### Test 3: Full mission at 3m
```bash
ros2 launch drone_l1 mission_l1.launch.py target_altitude:=3.0 hold_duration:=15.0
```

---

## STEP 6 — Monitoring During Flight

```bash
# Terminal 1: Watch mission state
ros2 topic echo /rosout | grep mission_node

# Terminal 2: Watch altitude in real-time
ros2 topic echo /mavros/rangefinder/rangefinder

# Terminal 3: Watch Pixhawk state
ros2 topic echo /mavros/state

# Terminal 4: Watch local position (EKF estimate)
ros2 topic echo /mavros/local_position/pose
```

---

## Troubleshooting

| Problem | Likely cause | Fix |
|---|---|---|
| Rangefinder reads 0 or -inf | D435i not streaming depth | Check USB 3.0, run `realsense-viewer` |
| Drone climbs past target | rangefinder not reaching Pixhawk | Verify RNGFND1_TYPE=10, check MAVROS plugin_allowlist |
| Drone drifts horizontally | No GPS (expected at L1) | Stay in calm wind, supervise manually |
| Mission node stuck in ARMING | No FCU heartbeat | Check serial port, baud rate, SERIAL2_PROTOCOL=2 |
| Drone won't arm | Arming checks failing | Check `ARMING_CHECK` param, pre-arm messages in Mission Planner |
| Oscillating altitude | PSC_VELZ_P too high | Reduce by 0.5 steps |
| D435i unreliable outdoors | Sunlight interference | Add sun shield, reduce ambient IR |

---

## File Structure
```
drone_l1/
├── src/drone_l1/
│   ├── mission_node.py          ← main mission controller
│   └── rangefinder_bridge.py   ← D435i depth → Range msg
├── launch/
│   └── mission_l1.launch.py    ← launches everything
├── config/
│   └── ardupilot_params.param  ← Pixhawk parameters
├── setup.py
└── package.xml
```
