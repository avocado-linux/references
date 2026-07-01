import os
from glob import glob

from setuptools import setup

package_name = "ros2_lite6"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        # Web UI assets — installed to share/ros2_lite6/static/ inside the
        # container so the ament_index lookup in http_api.py can find them.
        (
            os.path.join("share", package_name, "static"),
            glob(os.path.join(package_name, "static", "*")),
        ),
        # Launch files.
        (
            os.path.join("share", package_name, "launch"),
            glob("launch/*.launch.py"),
        ),
        # URDF.
        (
            os.path.join("share", package_name, "urdf"),
            glob("urdf/*.urdf"),
        ),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Avocado Reference",
    maintainer_email="dev@example.com",
    description="ROS 2 driver + HTTP API + web UI for UFactory Lite 6 on Avocado OS",
    license="MIT",
    entry_points={
        "console_scripts": [
            "node = ros2_lite6.node:main",
        ],
    },
)
