# Getting Started with ROS 2 Lite 6

Build a Docker image carrying a ROS 2 Humble + xArm SDK app locally, `docker save` it to a tarball, bake it into the application sysext via `avocado build`, and load it on the device on sysext merge. The container reaches the arm over Ethernet on a shared LAN.

The container runs a full ROS 2 graph: `robot_state_publisher` broadcasts TF transforms and the URDF, `lite6_node` publishes `/joint_states` at 30 Hz, and `foxglove_bridge` exposes all topics over WebSocket for browser-based visualization. Any machine on the LAN can visualize the arm live — no ROS 2 install required, just a browser.

## Prerequisites

- macOS 10.12+ or Linux (Ubuntu 22.04+, Fedora 39+)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) or a working local Docker daemon
- The latest [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview)
- A supported target — see `supported_targets` in `avocado.yaml` for the full list. All are arm64; this guide's commands use any NXP i.MX or `raspberrypi5`, and the rest follow the same flow.
- A UFactory Lite 6 robot arm with its control box powered on and on Ethernet
- A switch (or any router with a built-in switch) for the device, arm, and your laptop to share

## Topology

```
                       ┌── [your laptop] (DHCP)
[switch / router] ─────┤
                       ├── [Avocado device] (DHCP on eth0)
                       └── [Lite 6]
```

The device, the arm, and your laptop all sit on one shared LAN. **The arm's IP must be reachable from the device.** Two paths:

### Path 1 — Reconfigure the arm to your LAN (recommended)

The arm ships with a factory IP in the `192.168.1.x` range (printed on the control box sticker). To get it onto your LAN:

1. Power the arm on with **a temporary direct cable** between the arm and a laptop set to `192.168.1.50/24`.
2. In a browser, open `http://<arm-ip>:18333` to reach UFactory Studio.
3. Settings → Network → change the IP to one on your LAN, e.g. `10.0.0.42`. Save and power-cycle the arm.
4. Move the cable to your switch. The arm is now a normal host on your LAN.

### Path 2 — Run a dedicated 192.168.1.x switch

Plug the arm and the Avocado device into a small unmanaged switch, leave the arm at its factory IP, and configure the device with a static `192.168.1.10/24` (replace `overlay/network/etc/systemd/network/10-eth0-dhcp.network` with a static-address version — see Customize).

---

## Phase 1 — Build, deploy, wave the arm

### Initialize

```bash
avocado init --reference ros2-ufactory-lite6 ros2-lite6
cd ros2-lite6
```

For a non-default target:

```bash
avocado init --reference ros2-ufactory-lite6 --target imx8mp-evk ros2-lite6
cd ros2-lite6
```

### Install

```bash
avocado install -f
```

Pulls the SDK image and the runtime feed packages: `docker` + the kernel modules.

### Set the arm IP

Edit `overlay/app/etc/container-app/container-app.env`:

```ini
LITE6_IP=192.168.1.125           # whatever you set in Path 1 above
LITE6_AUTOSTART_SEQUENCE=false
ROS_DOMAIN_ID=42
```

Don't have an arm yet? Use `LITE6_IP=mock` — the container publishes synthetic data so you can exercise the rest of the stack.

### Build the container image

The Docker image is built on your development machine (not inside the Avocado SDK). You must run this step **every time you change application code** — anything under `app/` (Python source, Dockerfile, launch files, URDF, entrypoint). Avocado doesn't know how to build Docker images; it just packages whatever tarball is at `overlay/app/usr/lib/container-app/lite6.tar` into the sysext. If you skip this step after changing code, the device will run the old image.

```bash
TARGET_PLATFORM=linux/arm64 sh build-image.sh
```

This cross-builds the image for arm64 via Docker buildx, then `docker save`s it to the tarball. First build takes ~5 minutes (downloads `ros:humble-ros-base`, installs xArm SDK + `robot_state_publisher` + `tf2_ros` + `foxglove_bridge`, builds the ROS 2 package via colcon). Subsequent builds are fast thanks to Docker layer caching.

### Build the runtime

```bash
avocado build
```

### Deploy

```bash
# Raspberry Pi 5
avocado provision -r dev --profile sd

# i.MX 8MP EVK
avocado provision -r dev --profile sd

# i.MX 9x boards via UUU / eMMC
avocado provision -r dev --profile uuu-emmc
```

Insert the SD card (or trigger the relevant flash mode), apply power.

### Find the device IP

The serial console always works:

```bash
ip addr show eth0 | grep 'inet '
```

### Verify

SSH in (empty root password):

```bash
ssh root@<device-ip>

systemctl status docker.service container-app.service
# both: Active: active (running)

docker images
# lite6-ros2    latest    ...

# Live arm status via HTTP
curl http://<device-ip>:8080/status | jq
# {"connected": true, "mock": false, "ip": "10.0.0.42",
#  "joints_deg": [0.0, 0.0, ...], ...}

# Make the arm wave (~10 seconds)
curl -X POST http://<device-ip>:8080/wave

# ROS 2 topics (inside the container)
docker exec ros2-lite6 bash -lc \
  'source /ws/install/setup.bash && ros2 topic list'
# /joint_states
# /robot_description
# /tf
# /tf_static

# Live joint state stream
docker exec ros2-lite6 bash -lc \
  'source /ws/install/setup.bash && ros2 topic echo /joint_states'
```

If `connected: false`, check that `LITE6_IP` is correct and the device can `ping` the arm:

```bash
ping -c 3 10.0.0.42
```

### ROS 2 on your laptop

The container publishes a full ROS 2 graph over DDS. Any machine on the same network with matching `ROS_DOMAIN_ID` can see and interact with the arm's topics and TF tree.

Install ROS 2 Humble locally, then:

```bash
export ROS_DOMAIN_ID=42
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

# Verify topics are visible
ros2 topic list
# /joint_states        — 30 Hz joint angles (sensor_msgs/JointState)
# /robot_description   — URDF (latched, std_msgs/String)
# /tf                  — live joint transforms from robot_state_publisher
# /tf_static           — fixed transforms (world → base_link)

# Stream live joint state
ros2 topic echo /joint_states

# Inspect the TF tree
ros2 run tf2_tools view_frames
# Generates frames.pdf showing: world → base_link → link1 → ... → link6
```

### RViz visualization

The shipped RViz config is at `overlay/app/usr/share/ros2-lite6/rviz/lite6.rviz`. Copy it to your laptop and launch:

```bash
export ROS_DOMAIN_ID=42
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
rviz2 -d lite6.rviz
```

You should see:

- The Lite 6 arm rendered as a 3D robot model (from the URDF)
- Joint frames (TF axes) at each link, updating in real time
- A grid on the XY plane for spatial reference

Move the arm via the web UI at `http://<device-ip>:8080` or the HTTP API — the RViz model follows in real time.

### Foxglove Studio (browser-based visualization)

The container runs [Foxglove Bridge](https://docs.foxglove.dev/docs/visualization/connecting/live/ros-foxglove-bridge) on port 8765, exposing all ROS 2 topics over WebSocket. No ROS 2 install needed on your laptop — just a browser.

1. Open [https://app.foxglove.dev](https://app.foxglove.dev) in your browser (free, no account required)
2. Click **Open connection**
3. Select **Foxglove WebSocket** and enter: `ws://<device-ip>:8765`
4. Click **Open**

You now have live access to every ROS 2 topic. Recommended panels to add:

- **3D** — renders the robot model from `/robot_description` with live TF. You'll see the arm move in real time as you jog it from the web UI.
- **Raw Messages** on `/joint_states` — live stream of joint angles, updated at 30 Hz.
- **Plot** on `/joint_states.position[0]` through `[5]` — real-time chart of each joint angle over time.
- **Topic Graph** — shows the full node/topic graph (`lite6_node` → `/joint_states` → `robot_state_publisher` → `/tf`).
- **Diagnostics** — summary of all active topics with message rates and types.

The web control UI (`http://<device-ip>:8080`) and Foxglove (`ws://<device-ip>:8765`) work simultaneously — control the arm from one, observe it from the other.

✅ **Phase 1 complete.** Container is running. Arm responds to HTTP. ROS 2 topics publish. TF tree and robot model are live. Foxglove visualizes everything in the browser.

---

## Phase 2 — Edit motion code, push the update

### Add a new sequence

Edit `app/ros2_lite6/ros2_lite6/sequences.py`:

```python
def shake(arm: ArmController, oscillations: int = 6) -> None:
    """Quick joint-2 nod."""
    arm.go_home()
    for i in range(oscillations):
        sign = 1.0 if i % 2 == 0 else -1.0
        angles = list(HOME_JOINTS_DEG)
        angles[1] = sign * 15.0
        arm.set_servo_angle(angles, speed_deg_s=80.0)
    arm.go_home()
```

Add a route in `app/ros2_lite6/ros2_lite6/http_api.py`:

```python
@app.post("/shake")
def shake() -> dict:
    threading.Thread(target=sequences.shake, args=(arm,), daemon=True).start()
    return {"accepted": "shake"}
```

### Rebuild and push

Any change to application code (Python, Dockerfile, launch files, URDF) requires rebuilding the Docker image first. `avocado build` and `avocado deploy` alone will not pick up code changes — they only package and push the tarball that `build-image.sh` produces.

```bash
# 1. Rebuild the Docker image (required after any code change)
TARGET_PLATFORM=linux/arm64 sh build-image.sh

# 2. Rebuild the Avocado runtime (packages the new tarball into the sysext)
avocado build

# 3. Deploy to the device
avocado runtime deploy dev --device root@<device-ip>
```

`avocado runtime deploy` streams the changed sysext bytes, fires `systemd-sysext refresh` on the device, the `app` extension's `on_merge` restarts the container (which loads the updated image on start).

### Verify the update

```bash
curl -X POST http://<device-ip>:8080/shake
# Arm performs the new sequence.
```

✅ **Phase 2 complete.** New behavior on the arm without re-flashing.

---

## ROS 2 architecture

The container runs three ROS 2 nodes via a single launch file (`lite6.launch.py`):

```
┌──────────────────────────────────────────────────────────────────────┐
│  Docker container (lite6-ros2:latest)                                │
│                                                                      │
│  ┌───────────────────┐  ┌────────────────────┐  ┌────────────────┐  │
│  │  lite6_node        │  │  robot_state_pub    │  │ foxglove_bridge│  │
│  │                   │  │                    │  │                │  │
│  │  xArm SDK ←─────────→ Lite 6 arm (TCP)   │  │  WebSocket     │  │
│  │  FastAPI/Uvicorn  │  │  URDF → TF         │  │  :8765         │  │
│  │  :8080            │  │                    │  │                │  │
│  │                   │  │  subscribes:       │  │  exposes all   │  │
│  │  publishes:       │  │   /joint_states    │  │  ROS 2 topics  │  │
│  │   /joint_states ──│─→│                    │  │  to browsers   │  │
│  │                   │  │  publishes:        │  │                │  │
│  │                   │  │   /tf, /tf_static  │  │                │  │
│  │                   │  │   /robot_desc      │  │                │  │
│  └───────────────────┘  └────────────────────┘  └────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

**Ports:**

| Port | Protocol | Purpose |
|------|----------|---------|
| 8080 | HTTP | Web UI + REST API for arm control |
| 8765 | WebSocket | Foxglove Bridge — connect from [app.foxglove.dev](https://app.foxglove.dev) |

**Topics published over DDS (visible to any ROS 2 machine on the network):**

| Topic | Type | Rate | Description |
|-------|------|------|-------------|
| `/joint_states` | `sensor_msgs/JointState` | 30 Hz | Joint angles for all 6 joints (radians) |
| `/tf` | `tf2_msgs/TFMessage` | 30 Hz | Live transforms for every joint frame |
| `/tf_static` | `tf2_msgs/TFMessage` | Latched | Fixed transform: `world` → `base_link` |
| `/robot_description` | `std_msgs/String` | Latched | Full URDF of the Lite 6 |

**HTTP API (port 8080):**

The web UI and REST endpoints (`/status`, `/move/joint`, `/move/line`, `/pick_and_place`, `/wave`, `/estop`, etc.) remain available for non-ROS clients. Both interfaces control the same arm — they share a single thread-safe `ArmController`.

**Foxglove Bridge (port 8765):**

All ROS 2 topics are exposed over WebSocket for browser-based visualization via [Foxglove Studio](https://app.foxglove.dev). No ROS 2 install needed on the observing machine — any browser on the LAN can connect.

---

## Customize

### Enable autostart-on-boot

By default the arm sits idle waiting for HTTP commands. To run a sequence as soon as the container comes up, edit `overlay/app/etc/container-app/container-app.env`:

```ini
LITE6_AUTOSTART_SEQUENCE=true
```

Rebuild and redeploy. **Make sure the arm's workspace is clear of obstacles before enabling this** — the arm will move at boot, every boot, automatically.

### Switch to a dedicated 192.168.1.x arm subnet

Replace `overlay/network/etc/systemd/network/10-eth0-dhcp.network` with:

```ini
[Match]
Name=eth0 end0 enP*

[Network]
Address=192.168.1.10/24
```

Then leave the arm at its factory `192.168.1.x` IP, plug both into the same switch, set your laptop to a `192.168.1.x` static. The device's HTTP API is reachable at `http://192.168.1.10:8080`.

### Use a different UFactory arm

The xArm Python SDK supports xArm 5/6/7, 850, and Lite 6 with the same API. To switch:

1. Edit `app/ros2_lite6/ros2_lite6/arm.py` — `HOME_JOINTS_DEG` may need a length change for 7-DoF arms.
2. Replace `app/ros2_lite6/urdf/lite6.urdf` with a URDF matching the new arm's kinematics (joint count, link lengths, joint axes). The URDF is used by `robot_state_publisher` to broadcast TF and render the model in RViz.
3. Rebuild and redeploy.

### Switch to full `xarm_ros2` + MoveIt 2

The default reference uses a thin custom ROS 2 node + the xArm Python SDK to keep the image under ~500 MB. To use the full `xarm_ros2` stack with MoveIt 2 planning, swap the `Dockerfile` for one based on `moveit/moveit2:humble-source` and `colcon build` `xarm_ros2`. Expect:

- ~2 GB compressed image
- 15+ minute first build
- Bump `stone/<target>/stone-<target>.json` `var.size` to **8192 MB**

### Adjust the var partition size

For other targets or when the image grows, edit `stone/<target>/stone-<target>.json`:

```json
{ "name": "var", "image": "var", "size": 8192, "size_unit": "mebibytes", "expand": "true" }
```

---

## Debugging

### Container won't start

```bash
journalctl -u container-app.service -b --no-pager | tail -50
docker logs ros2-lite6
```

Common causes:

- Architecture mismatch (built for amd64, ran on arm64) → re-run `sh build-image.sh` with `TARGET_PLATFORM=linux/arm64`.
- Image not loaded → check `docker images` shows `lite6-ros2:latest`. If missing, `docker load` in the service's `ExecStartPre` may have failed; check `journalctl -u container-app.service`.

### `/status` returns `connected: false`

The container started but couldn't reach the arm at `LITE6_IP`. Check:

- `ping <arm-ip>` from the device — if that fails, the device and arm aren't on the same LAN.
- Arm powered on and not in error state (UFactory Studio web UI is the easiest check).
- `LITE6_IP` correctly set in `container-app.env`.

After fixing, `systemctl restart container-app`.

### ROS 2 topics not showing up on the laptop

- `ROS_DOMAIN_ID` must match on both sides (default `42`).
- `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` recommended on both sides for cleaner Docker / multi-host discovery.
- Firewall on your laptop or LAN may block UDP multicast — check.
- Verify inside the container first: `docker exec ros2-lite6 bash -lc 'source /ws/install/setup.bash && ros2 topic list'` should show `/joint_states`, `/robot_description`, `/tf`, and `/tf_static`.

### Foxglove won't connect

- Confirm the container is running: `docker logs ros2-lite6 2>&1 | grep foxglove` — you should see `foxglove_bridge` log its WebSocket address.
- Check that port 8765 is listening: `cat /proc/net/tcp` on the device and look for `2241` (hex for 8765) in the local address column.
- Foxglove Studio at `app.foxglove.dev` is served over HTTPS. Some browsers block mixed content (HTTPS page connecting to `ws://` non-TLS WebSocket). If the connection silently fails, try the [Foxglove Desktop app](https://foxglove.dev/download) instead, or use Chrome which is more permissive with localhost/LAN WebSocket connections.

### TF tree looks wrong in RViz

- `ros2 run tf2_tools view_frames` on your laptop generates a PDF of the TF tree. Confirm the chain runs from `world` → `base_link` → `link1` → ... → `link6`.
- If the robot model shows but doesn't move, check that `/joint_states` is being received: `ros2 topic hz /joint_states` should report ~30 Hz.

---

## Safety

A robot arm moves. Real-world considerations:

- **Clear the workspace** before powering on the arm and before triggering any motion.
- **`/estop`** is the emergency stop endpoint. `curl -X POST http://<device-ip>:8080/estop` — disables motion immediately.
- Default `LITE6_AUTOSTART_SEQUENCE=false` means nothing moves unless you ask. Keep it that way during development.
