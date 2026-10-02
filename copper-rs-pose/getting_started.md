# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Getting Started with Copper Human Pose

This guide shows how to build the Copper human pose reference, put it on a device, and watch the poses on your laptop. The app is one Rust binary. It reads a USB camera, finds poses with YOLOv8n-pose on the CPU, and serves the results over Rerun on port 9876.

## Prerequisites

- macOS or Linux. On macOS, the Avocado CLI starts its own helper VM (avocado-vm) for the SDK. On Linux, Docker must be installed and running.
- The latest version of the [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview)
- One of the supported devices: `raspberrypi5`, `imx8mp-evk` or `jetson-orin-nano`
- The media and cables to provision your device (SD card, USB cable, serial console adapter). See the [Support Matrix](https://docs.peridio.com/hardware/support-matrix).
- A USB (UVC) webcam. Most webcams that give YUYV video work.
- A network connection between the device and your laptop. Ethernet is better than Wi-Fi, because the device sends raw camera frames to the viewer.
- The Rerun viewer, version 0.34.1, on your laptop. Install it with one of these commands:

  ```bash
  pip install rerun-sdk==0.34.1
  cargo install rerun-cli@0.34.1 --locked
  ```

  The viewer version must be the same as the version in the app. A different version does not connect.

## Initialize

Initialize a new project from the reference:

```bash
avocado init --reference copper-rs-pose copper-pose
cd copper-pose
```

To use a target other than the default (`raspberrypi5`), add `--target`:

```bash
avocado init --reference copper-rs-pose --target imx8mp-evk copper-pose
cd copper-pose
```

## Install

Install the Rust toolchain and the packages for the device:

```bash
avocado install -f
```

## Build

Compile the app and build the runtime image:

```bash
avocado build
```

The first build compiles about 700 Rust crates and takes some minutes. Later builds take less than 1 minute. For the details, see [How the build works](#how-the-build-works).

## Deploy

### Raspberry Pi 5 and NXP i.MX 8MP EVK

Insert your SD card and provision:

```bash
avocado provision -r dev --profile sd
```

Put the SD card into the device, connect the webcam and the network, and apply power.

### NVIDIA Jetson Orin Nano

```bash
avocado provision -r dev --profile tegraflash
```

Obey the USB disconnect and reconnect prompts during the flash process. Then connect the webcam and the network.

### Update a device that you provisioned before

When you change the code, you do not have to provision again. Build, then deploy to the running device:

```bash
avocado build
avocado deploy -r dev -d <device-ip>
```

## Verify

Log in as `root` with an empty password. The service starts automatically at boot.

1. Make sure that the device found the webcam:

   ```bash
   ls -l /dev/copper-camera
   ```

   This is a link to the video node of the USB camera, for example `/dev/copper-camera -> video1`. Connect only one USB camera. With two cameras, the link can go to either one. If the link is not there, see [Troubleshooting](#troubleshooting).

2. Make sure that the service runs:

   ```bash
   systemctl status copper-rs-pose
   journalctl -u copper-rs-pose
   ```

   The status is `active (running)`. The journal has this line, which shows that the Rerun server is ready. You use this command in step 5.

   ```
   copper-rs-pose: Rerun server ready. On your laptop run: rerun --connect rerun+http://<device-ip>:9876/proxy
   ```

3. Make sure that the Copper log is written:

   ```bash
   ls -lh /var/lib/copper-rs-pose/
   ```

   The directory has `human-pose_0.copper`. When a log file is full (256 MB), Copper starts `human-pose_1.copper`, then `human-pose_2.copper`, and more. Copper does not delete old files. Delete them when you need disk space.

4. Get the IP address of the device:

   ```bash
   ip a
   ```

5. On your laptop, connect the viewer. Use the IP address from step 4:

   ```bash
   rerun --version
   rerun --connect rerun+http://<device-ip>:9876/proxy
   ```

   `rerun --version` must show 0.34.1. The viewer shows the `camera/image` view with the live camera image. When a person is in the camera image, the viewer shows a box, the keypoints and the skeleton lines on the person.

Inference runs on the CPU. The frame rate is low, and it is lowest on the i.MX 8MP, which has Cortex-A53 cores.

### See the Copper TUI

The Copper console monitor shows the task graph and the timing of each task. It starts only when you run the app in a terminal. The service uses the camera and port 9876, so the command stops the service first. On your laptop, run:

```bash
ssh -t root@<device-ip> 'systemctl stop copper-rs-pose; copper-rs-pose'
```

Push `q` to stop the app. The app prints `copper-rs-pose: Exiting...` when it stops. Then start the service again:

```bash
ssh root@<device-ip> systemctl start copper-rs-pose
```

## Customize

All app files are in `app/`. After a change, build and deploy again (see [Update a device that you provisioned before](#update-a-device-that-you-provisioned-before)).

### Change the detection sensitivity

In `app/copperconfig.ron`, change the `yolo` task:

- `conf_threshold`: the minimum score for a person. Make it lower to find more people.
- `iou_threshold`: the overlap limit when two boxes are on the same person.

### Change the camera resolution

The width and height are in three places in `app/copperconfig.ron`. The three values must be the same:

- The `pipeline` string of the `camera` task
- The `caps` string of the `camera` task
- The `width` and `height` of the `gst_to_image` task

### Use a different camera

The udev rule `overlay/usr/lib/udev/rules.d/70-copper-camera.rules` makes `/dev/copper-camera` for a USB camera. To use a different camera, change the rule, or change `device=` in the `pipeline` string.

### Add a task to the graph

A Copper app is a graph of tasks. Each task is a Rust type, and `copperconfig.ron` connects the tasks. To add a task:

1. Write the task in `app/src/tasks/`, and export it from `app/src/tasks/mod.rs`. Use `rerun_viz.rs` as an example of a sink task.
2. Add the task to `tasks` in `app/copperconfig.ron`.
3. Add a line to `cnx` for each message that the task receives.

For example, write a sink `PoseCounter` in `app/src/tasks/pose_counter.rs` with `type Input<'m> = input_msg!(CuPoses);`, and export it from `mod.rs`. Then add the task and its connection:

```ron
(id: "counter", type: "tasks::PoseCounter"),
```

```ron
(src: "yolo", dst: "counter", msg: "payloads::CuPoses"),
```

The build examines the graph. If a message type does not agree with a task, the build fails.

## How the build works

The Install step installs the Rust cross-compilation toolchain (`nativesdk-rust`, `nativesdk-cargo`, `packagegroup-rust-cross-canadian-avocado-<target>`). It also installs the GStreamer headers that the app links against (`gstreamer1.0-dev`, `gstreamer1.0-plugins-base-dev`) and the GStreamer plugins for the device.

The build runs `copper-compile.sh` in the SDK container. The script does these steps:

1. Finds the Rust target from `RUST_TARGET_PATH`.
2. Puts the cargo cache and the build output in `$AVOCADO_BUILD_DIR`. This directory is in the SDK volume, which is much faster than the project directory.
3. Downloads the YOLOv8n-pose weights (6.6 MB) from Hugging Face, pinned to one commit, and examines the sha256. If the file is already there, it does not download it again.
4. Writes `app/.cargo/config.toml` with the sysroot flags.
5. Runs `cargo build --release --locked --ignore-rust-version`.

Copper declares Rust 1.95, and the SDK has Rust 1.94.1. The code builds with 1.94.1, so the script uses `--ignore-rust-version`. `Cargo.toml` pins the Copper crates to `=1.2.1`, and `Cargo.lock` pins all other crates.

At build time, `build.rs` and the `#[copper_runtime]` macro read `app/copperconfig.ron` and make the task graph into Rust code. Thus a change to `copperconfig.ron` needs a new build.

Then `copper-install.sh` copies the binary to `/usr/bin/copper-rs-pose` and the weights to `/usr/share/copper-rs-pose/` in the extension.

## Troubleshooting

- **The service restarts every 5 seconds.** The app cannot open the camera. Make sure that `/dev/copper-camera` is there. If a camera is connected later, the service starts it automatically.
- **`/dev/copper-camera` is not there.** Find your camera with `v4l2-ctl --list-devices`. If it is not a USB (UVC) camera, change `device=` in the `pipeline` string.
- **No image in the viewer.** Make sure that `rerun --version` on the laptop shows 0.34.1, and that the laptop can connect to port 9876 on the device.
- **No skeletons.** Stand back so that the camera sees all of your body, or make `conf_threshold` lower.
- **The camera is disconnected while the app runs.** The app does not find this, and it stops sending frames. Restart the service.

## Security

The Rerun server has no authentication. All computers on the same network can connect to port 9876 and see the camera image. Use this reference only on a network that you trust.
