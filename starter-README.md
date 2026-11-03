# Raspberry Pi 4 inspection robot: bench-test starter

This package controls motors and captures photos. It does NOT contain a trained crack detector, autonomous obstacle avoidance, suction control, or validated wall-climbing behavior. Keep wheels lifted for initial tests. Code has not been tested on your hardware.

## Hardware assumptions: check before connecting power

- Standard ESP32-WROOM-32 DevKit and an L298N module (not an unidentified "L289N").
- Two motor channels. If multiple motors share an output, their combined stall current must fit the driver and power system. L298N voltage drop and heating can limit climbing torque.
- AI Thinker ESP32-CAM with OV2640 and compatible ESP32-CAM-MB adapter.
- Arduino IDE with Espressif ESP32 board package **3.x** (motor code uses its LEDC API).
- Motor battery voltage, motor rating and L298N regulator-jumper configuration still need verification. No battery-to-driver instructions are assumed in this package.
- Pi powered through its own 5.1V 3A USB-C supply. Do not use L298N 5V output for the Pi.
- ESP32 initially USB-powered. Do not also connect L298N 5V to ESP32 USB/5V supply.

## 1. Motor wiring, all supplies disconnected

| ESP32 GPIO | L298N |
|---|---|
|26|IN1|
|27|IN2|
|32|IN3|
|33|IN4|
|25|ENA|
|14|ENB|
|GND|GND|

Remove ONLY ENA/ENB jumper caps before wiring the enable pins. Do not confuse them with 5V-EN. Add a 10k ohm resistor from ENA to GND and another from ENB to GND to disable motors during boot. Connect left motor to OUT1/OUT2 and right motor to OUT3/OUT4. GPIO numbers are printed pin labels, not physical header positions. Driver ground and ESP32 ground must be common. Battery connection and 5V-EN setting await verification of your actual parts.

## 2. Upload motor firmware

1. Install Arduino IDE and `esp32 by Espressif Systems` 3.x through Boards Manager. Official instructions: https://docs.espressif.com/projects/arduino-esp32/en/latest/installing.html
2. Open `esp32_motor_test/esp32_motor_test.ino`.
3. Connect ESP32 to laptop with a USB DATA cable. Select ESP32 Dev Module only for the stated WROOM DevKit. Select its serial port.
4. Upload with motor battery disconnected. If needed, hold BOOT while upload starts, then release.
5. Open Serial Monitor at 115200 baud. Send `s`; expect STOP. Disconnect/reconnect USB if you missed READY.
6. Only after motor supply compatibility is verified, lift wheels and apply motor power. Send `a`, then `b` separately. Each runs for 300ms at duty 120/255 and automatically stops. Send `f` only after both wheel directions are correct.
7. If direction is wrong, power off before swapping that motor's output wires. Do not increase duty to overcome a jam. Stop if the motor cannot turn or driver overheats.

Commands: `a` motor A, `b` motor B, `f` forward, `v` reverse, `l` left, `r` right, `s` stop, `d` distance test. Turning assumes A is left and B is right. This is intentionally short-pulse bench firmware. The timeout is not a safety-rated emergency stop; maintain a physical motor-power disconnect.

## 3. Camera upload

1. With power off, fit camera board to MB adapter using matching pin labels/orientation. Check camera ribbon is seated.
2. Open `esp32_camera/esp32_camera.ino`. Replace YOUR_WIFI_NAME and YOUR_WIFI_PASSWORD with your own 2.4GHz network credentials; keep them private.
3. Select AI Thinker ESP32-CAM, the MB USB serial port, and upload through a USB DATA cable. If your MB does not automatically enter download mode, use its documented IO0/BOOT and reset procedure; release IO0 from ground and reset for normal running.
4. Open Serial Monitor at 115200 and reset. Copy the printed `http://...` address.
5. Open it from a device on the same LAN. The page refreshes snapshots; it is not an MJPEG video stream. `/capture` returns one JPEG.
6. Do not expose this unauthenticated camera server to the internet. It is for your local test network.

## 4. Run on Raspberry Pi 4

Boot Raspberry Pi OS with a working microSD card, join the same Wi-Fi, and copy/extract this whole folder to your home folder. The following commands assume it is at `~/robot_starter`:

```bash
sudo apt update
sudo apt install python3-serial
cd ~/robot_starter/pi
python3 -m serial.tools.list_ports
```

Connect the MOTOR ESP32 to Pi with a USB DATA cable; select its listed port (often `/dev/ttyUSB0` or `/dev/ttyACM0`). Close other serial monitors before running:

```bash
python3 robot_control.py --port /dev/ttyUSB0 --camera http://192.168.1.50
```

Replace port and camera address with the actual values. Enter one command and press Enter. `c` saves a photo inside `inspection_photos` in the current directory. `q` exits. The ESP32 stops movement after 300ms even when no further commands arrive. Ctrl+C also requests a stop. If serial permission is denied, add your user to the dialout group with `sudo usermod -aG dialout "$USER"`, then log out and back in.

## 5. Optional HC-SR04 distance test

DISABLED by default. First confirm that your sensor is HC-SR04; other sensors may need different wiring. For a confirmed standard 5V HC-SR04: VCC to regulated 5V; GND to ESP32 ground; TRIG to GPIO18; ECHO through a voltage divider (ECHO -> 1k resistor -> GPIO19 node, node -> 2k resistor -> GND). Never connect 5V Echo directly to ESP32. Verify output levels and trigger compatibility for your particular module; some variants need a trigger level shifter. Set USE_HCSR04=true and upload again. `d` stops motors before reading distance. No echo is reported as invalid, never as a clear path. No automatic obstacle-stop behavior is implemented.

## 6. Next stage

After bench tests, confirm battery/motor specs, driver identity and sensor model. Add a suitable crack-trained model with known preprocessing before calling the image processing AI defect detection. Test adhesion separately with a tether before any climbing. An ultrasonic reading cannot confirm suction or structural safety.
