from setuptools import setup

package_name = "navyam_mission"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Navyam team",
    maintainer_email="offsujal128005@gmail.com",
    description="Mission state machine and Nav2 to ArduPilot velocity bridge for Navyam.",
    license="Proprietary",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "mission = navyam_mission.mission_node:main",
            "cmd_vel_bridge = navyam_mission.cmd_vel_bridge_node:main",
        ],
    },
)
