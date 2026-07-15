---
language: Python
targets:
  - raspberrypi4
  - raspberrypi5
  - jetson-orin-nano-devkit
  - jetson-agx-orin-devkit
  - imx8mp-evk
  - imx91-frdm
  - imx93-evk
  - imx93-frdm
topics:
  - camera
  - vision
icon: icon.png
---

# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Intel RealSense Web Visualizer

A reference project demonstrating how to build a real-time Intel RealSense depth camera visualizer as an Avocado OS system extension.

Features:
- Stream three live views: Color, Depth Colormap, and Infrared
- Toggle individual panels on/off from the toolbar
- Click any feed to measure distance at that pixel (returns distance in meters and 3D coordinates)
- Live device info bar (camera model, serial, firmware, USB type, depth scale)
- Responsive single-page dashboard served on port 5000
- Bundled pip packages (Flask, pyrealsense2) deployed as a system extension
- systemd-managed service that starts on boot

Supported hardware:
- Raspberry Pi 4 and 5
- NVIDIA Jetson Orin Nano and AGX Orin
- NXP i.MX8M Plus, i.MX91, and i.MX93

Requires an Intel RealSense D400-series (D415, D435, D435i, D455) or L500-series camera connected via USB.
