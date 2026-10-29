# Getting started: simulation laptop (Dell RTX)

This guide is for the teammate setting up the Dell RTX laptop. That laptop runs the **Navyam simulation**: a virtual maze, a virtual drone with a LiDAR, and our autonomy software. We can then test everything before risking the real drone. Later it will also train the survivor-detection model on its GPU.

You don't need any drone hardware for this. Plan on **one to two days** for steps 1–4. Most of that is downloads and compiling.

Background reading:
- **What we're building:** [README.md](../README.md). In short, a drone that flies into the NIDAR maze on its own, maps it, finds up to six survivors and tags them on a grid map, then flies back out.
- **Decisions already made, and why:** [decisions.md](decisions.md).

---

## Step 1 · Install Ubuntu 22.04 next to Windows (dual boot)

ROS 2 Humble and Gazebo need **Ubuntu 22.04 LTS** (not 24.04). Windows stays; you choose the OS at boot.

1. **Back up** anything important on the laptop first.
2. In Windows, **suspend BitLocker** if it's on (Control Panel → BitLocker → Suspend protection). Otherwise Windows may ask for a recovery key after Ubuntu is installed.
3. **Free up disk space:** Disk Management → right-click the C: partition → *Shrink Volume*. Leave **at least 120 GB** unallocated (150 GB+ is better).
4. **Make a boot USB** (8 GB or larger):
   - Download the *Ubuntu 22.04.x LTS Desktop* ISO from ubuntu.com/download/alternative-downloads.
   - Write it to the USB stick with Rufus or balenaEtcher.
5. **Dell BIOS check (press F2 at power-on):** look at *Storage → SATA/NVMe Operation*.
   - If it says **AHCI**, nothing to do.
   - If it says **RAID On**, the Ubuntu installer may not see the disk. Don't switch it blindly: Windows won't boot if you change it without preparing first. Search "switch RAID to AHCI without reinstalling Windows" (it's a safe-mode trick), or ask on the team chat first.
6. **Boot the USB:** press **F12** at power-on and pick the USB stick. Choose *Install Ubuntu*, then:
   - Tick **"Install third-party software for graphics and Wi-Fi hardware"**.
   - Choose **"Install Ubuntu alongside Windows Boot Manager"**.
   - If it asks for a Secure Boot password, pick one and remember it. You'll type it once on a blue "MOK management" screen after the reboot (choose *Enroll MOK*).

## Step 2 · NVIDIA driver

In Ubuntu, open a terminal:

```bash
sudo apt update && sudo apt upgrade -y
sudo ubuntu-drivers install
sudo reboot
```

After the reboot, `nvidia-smi` should list the RTX GPU. If it doesn't, stop here and ask. Gazebo will crawl without the GPU.

## Step 3 · Get the code

1. Accept the GitHub invitation to the **navyam** repository. It arrives by email, or under github.com → notifications.
2. Install git and clone the repo into your home folder:

```bash
sudo apt install -y git python3-pip
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
cd ~
git clone https://github.com/sujal128005/Navyam.git navyam
cd navyam
```

When git asks for a password, use a **GitHub personal access token**, not your GitHub password. Create one at github.com → Settings → Developer settings → Personal access tokens. Alternatively, set up an SSH key.

3. Quick check that Python works (no ROS needed yet):

```bash
python3 -m unittest discover -s sim/maze_gen
python3 sim/maze_gen/navyam_maze.py --seed 7 --out /tmp/test_maze --ascii
```

You should see `OK` and a maze drawn in text.

## Step 4 · ROS 2, ArduPilot simulator and Gazebo

Follow **[sim-setup.md](sim-setup.md)**. It links ArduPilot's own install guides in the right order.

**The milestone:** ArduPilot's own maze demo runs (section 1 of sim-setup.md). The drone sits in a maze in Gazebo, and the map appears in RViz.

Take a **screenshot of Gazebo and RViz** at that point and send it to the team chat.

Common snags:
- *`microxrcedds_gen` not found:* the Micro-XRCE-DDS-Gen folder isn't on your `PATH`. Add the export line from ArduPilot's ROS 2 guide to `~/.bashrc`, then open a new terminal.
- *Gazebo packages not found:* run `export GZ_VERSION=harmonic` **before** `rosdep install` and `colcon build`. Put it in `~/.bashrc` too.
- *Build runs out of memory:* add `--parallel-workers 2` to `colcon build`.
- *Anything else:* copy the **first** error line (not the last) into the team chat.

## Step 5 · Run the Navyam mission in simulation

Continue with sections 2–4 of [sim-setup.md](sim-setup.md): build our packages, generate a maze, launch, and start the mission with `ros2 service call /navyam/start std_srvs/srv/Trigger`.

Go through the **"What to check on the first run"** table in sim-setup.md. For each row, note pass or fail plus what you saw. That table is the most useful thing to send back.

This is the first time this code has run anywhere, so expect problems. Every error you report is progress.

## How we share work

- Don't commit straight to `main`. Make a branch per task:
  ```bash
  git checkout -b sim/first-run
  git add -A
  git commit -m "Short description"
  git push -u origin sim/first-run
  ```
  Then open a Pull Request on GitHub.
- Put logs and screenshots in the PR description or the team chat. Don't commit them to the repo.
- Big files (rosbags, datasets, model weights) go on the Samsung T7 SSD, not GitHub.

## What comes after (not yet)

- A simulated drone with a depth camera, so the survivor detector can run in simulation.
- Training the YOLO survivor detector on this laptop's GPU.
- The ground-station web page (map, survivors, video, abort).
