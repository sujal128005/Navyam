from setuptools import setup

package_name = "navyam_perception"

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
    description="Survivor detection, registry and grid labels for Navyam.",
    license="Proprietary",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "survivor_registry = navyam_perception.survivor_registry_node:main",
            "survivor_detector = navyam_perception.detector_node:main",
        ],
    },
)
