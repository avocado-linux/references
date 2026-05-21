---
language: Java
targets:
  - "*"
topics:
  - openjdk
icon: icon.png
---

# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Java Hello World

A reference runtime that demonstrates how to compile and run a Java application as an Avocado OS extension. The app is compiled with `javac` and packaged as an executable JAR inside the SDK container using OpenJDK 17.

- Compile Java source files and package as a JAR inside the SDK container
- Install OpenJDK 17 via native SDK packages (`nativesdk-openjdk-17-jdk`)
- Generate a wrapper script for easy command-line execution on the target
- Run on any supported target with the JVM
