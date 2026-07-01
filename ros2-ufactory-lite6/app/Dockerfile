FROM ros:humble-ros-base

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3-pip python3-colcon-common-extensions \
      ros-humble-rmw-cyclonedds-cpp \
      ros-humble-robot-state-publisher \
      ros-humble-tf2-ros \
      ros-humble-launch-ros \
      ros-humble-foxglove-bridge \
    && rm -rf /var/lib/apt/lists/*

# Python deps: xArm SDK + the HTTP control surface.
# xarm-python-sdk is pinned to a recent known-good release.
RUN pip3 install --no-cache-dir \
      xarm-python-sdk==1.17.3 \
      fastapi==0.115.0 \
      "uvicorn[standard]==0.30.6"

WORKDIR /ws/src
COPY ros2_lite6 ./ros2_lite6

WORKDIR /ws
RUN . /opt/ros/humble/setup.sh \
    && colcon build --merge-install

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Defaults — every var is overridable from the systemd unit's --env flags.
ENV LITE6_IP=192.168.1.117 \
    LITE6_AUTOSTART_SEQUENCE=false \
    ROS_DOMAIN_ID=42 \
    RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

EXPOSE 8080 8765
ENTRYPOINT ["/entrypoint.sh"]
