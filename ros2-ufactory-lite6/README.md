---
language: Python
targets:
  - imx95-frdm
  - imx8mp-evk
  - imx91-frdm
  - imx93-evk
  - imx93-frdm
  - raspberrypi5
  - rzv2n-sr-som
  - stm32mp257f-dk
  - rubikpi3
  - grinn-astra-1680-sbc
topics:
  - container
  - docker
  - ros2
  - robotics
---

# ROS 2 Lite 6 — Robotic Arm Controller

A reference runtime that drives a [UFactory Lite 6](https://www.ufactory.cc/lite-6/) robotic arm from a ROS 2 Humble stack running entirely inside a Docker container on Avocado OS. The container is built locally, saved with `docker save`, and shipped into the device's app extension at `avocado build` time. From `avocado provision` to a moving arm takes one boot. Edits to the motion code push to the device with `avocado runtime deploy` in seconds.

- Built on the `docker-save` reference's shipping pattern — no registry, fully air-gappable
- ROS 2 Humble lives entirely in the container — the Avocado host has no ROS 2 installed
- Drives the Lite 6 over Ethernet via the official xArm Python SDK
- HTTP control surface (FastAPI) on port 8080 — `curl` an endpoint to move the arm; no ROS 2 install required on the dev laptop
- ROS 2 messaging output (`/joint_states` at 30 Hz) for RViz / external nodes on the same LAN
- Foxglove Bridge on port 8765 — visualize the live robot model and topics from a browser, no ROS 2 install required
- Mock mode (`LITE6_IP=mock`) lets you evaluate everything without owning the arm
