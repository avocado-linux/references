# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Getting Started with Java Hello World

This guide walks you through building and running the Java reference on Avocado OS. The app compiles a simple Java program into an executable JAR using OpenJDK 17 inside the SDK container.

## Prerequisites

- macOS 10.12+ or Linux (Ubuntu 22.04+, Fedora 39+)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- The latest version of the [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview)

For hardware targets, you will also need:

- Your target device and any required accessories (SD card, USB cable, serial console adapter)
- See the [Support Matrix](https://docs.peridio.com/hardware/support-matrix) for your target's requirements

## Initialize

Clone the reference or initialize a new project from it:

```bash
avocado init --reference java-hello java-hello
cd java-hello
```

To target specific hardware instead of the default, pass `--target`:

```bash
avocado init --reference java-hello --target raspberrypi5 java-hello
cd java-hello
```

## Install

Install the SDK toolchain, extension dependencies, and runtime packages:

```bash
avocado install -f
```

This pulls the SDK container image and installs `nativesdk-openjdk-17-jdk` for compiling Java source files.

## Build

Build the extensions and assemble the runtime image:

```bash
avocado build
```

The build step runs `java-compile.sh` inside the SDK container, which:

1. Compiles Java source files with `javac`
2. Creates a manifest with the main class entry point
3. Packages everything into `ref-java/build/jar/hello-world.jar`

Then `java-install.sh` copies the JAR to `/usr/lib/ref-java/` and creates a wrapper script at `/usr/bin/hello-java`.

## Deploy

### QEMU

For QEMU targets, provision and boot the VM:

```bash
avocado provision -r dev
avocado sdk run -iE vm dev
```

### SD card targets (Raspberry Pi, Seeed reTerminal, NXP, STMicroelectronics)

Insert your SD card and provision:

```bash
avocado provision -r dev --profile sd
```

Insert the SD card into the device and apply power.

### USB flash targets (OnLogic)

```bash
avocado provision -r dev --profile usb
```

### NVIDIA Jetson

```bash
avocado provision -r dev --profile tegraflash
```

Follow the USB disconnect/reconnect prompts during the flash process.

## Verify

Log in as `root` with an empty password. Run the application:

```bash
hello-java
```

You should see output like:

```
Hello from Avocado Linux!
Java version: 17.0.13
Java vendor: N/A
OS: Linux aarch64
```

## Customize

### Modify the application

Edit `ref-java/src/main/java/com/avocado/hello/HelloWorld.java`:

```java
package com.avocado.hello;

public class HelloWorld {
    public static void main(String[] args) {
        System.out.println("My custom Java app on Avocado OS!");
    }
}
```

### Add more Java source files

Add new `.java` files under `ref-java/src/main/java/` and include them in the `javac` command in `java-compile.sh`:

```bash
javac -d build/classes \
    src/main/java/com/avocado/hello/HelloWorld.java \
    src/main/java/com/avocado/hello/MyNewClass.java
```

### Add external JAR dependencies

Place JARs in a `ref-java/lib/` directory and add them to the classpath:

```bash
javac -cp "lib/*" -d build/classes src/main/java/com/avocado/hello/*.java
```

### Rebuild after changes

After any change, rebuild and reprovision:

```bash
avocado build
avocado provision -r dev
```
