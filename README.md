# AI-Based Wall-Climbing Robot for Structural Inspection and Defect Detection

Saved project software for a Raspberry Pi 4, motor ESP32, L298N driver, ESP32-CAM, and ultrasonic sensor. The collection includes manual web control, a distance display, camera snapshots, crack inspection, an experimental supervised inspection cycle, and the Wi-Fi troubleshooting tools used during setup.

Prepared on 3 November 2026 from nine saved project files/packages. The 24 recovered files, including 14 code files, are preserved byte-for-byte. This is a collection of saved versions; it is not a fresh backup of the programs currently on the physical robot. Configuration changes made later on the Pi may differ.

## Code and purpose

| Location | Purpose |
| --- | --- |
| `pi/robot_web_distance.py` | Manual phone/browser control, camera snapshots, and Pi ultrasonic distance display; port 5000. |
| `pi/crack_inspector.py` | Separate crack-inspection web service; port 5001; requires the specific external ONNX model. |
| `pi/robot_autonomy.py` | Experimental stationary scan or one supervised floor approach followed by a scan; port 5002. |
| `pi/robot_web.py` | Earlier manual web controller without the distance display; port 5000. |
| `pi/robot_control.py` | Original terminal-based motor and snapshot test. |
| `firmware/esp32_camera/` | AI Thinker ESP32-CAM snapshot server with `/capture`. |
| `firmware/esp32_motor_test/` | ESP32 motor test firmware with a 300 ms movement timeout. |
| `firmware/esp32_motor_ultrasonic/` | Alternative motor firmware with an ESP32-connected HC-SR04 test enabled. |
| `support/pi-wifi-check/` | Original SD-card-specific Wi-Fi diagnostic scripts. |
| `support/pi-wifi-reconnect/` | Original SD-card-specific Wi-Fi reconnection tool. |
| `support/pi-wifi-repair/` | Windows/SD-card-assisted Wi-Fi profile repair tools. |
| `docs/original/` | Original starter and autonomy instructions. |

The browser HTML, CSS and JavaScript are embedded in the Python applications and camera sketch. There is no separate frontend project.

## Configuration and running

Use the existing working Pi environment where possible. `requirements.txt` lists Python imports needed for the Pi applications; it is not a version-locked, freshly hardware-tested environment. Arduino sketches target the Espressif Arduino-ESP32 3.x APIs specified by their source comments.

1. Keep the motor ESP32 and ESP32-CAM sketches separate: they run on different boards. Open the appropriate `.ino` file in Arduino IDE. Set the camera sketch's `YOUR_WIFI_NAME` and `YOUR_WIFI_PASSWORD` locally; do not commit real credentials.
2. Choose one motor firmware. The `esp32_motor_test` version has its optional ESP32 ultrasonic test disabled. The alternative `esp32_motor_ultrasonic` version connects the sensor to ESP32 GPIO18/19. The Pi distance application instead expects Pi BCM23/24; these are different wiring configurations.
3. Before starting manual control, edit the `CAMERA` constant in the selected Python manual controller to the camera's current base URL, such as `http://192.168.1.50`. The saved `10.x.x.x` addresses and startup messages are historical local-network values.
4. Run only one motor controller at a time. The two manual web apps, terminal controller, and autonomy app share the same motor USB device.

From this repository's root on the Pi, using the Python environment that has the required packages:

```bash
# Manual controller with distance display
ROBOT_PORT=/dev/ttyUSB0 python3 pi/robot_web_distance.py
```

Open `http://PI_IP:5000` from a phone or laptop on the same network, replacing `PI_IP` with the Pi's current address.

Run the independent inspection service in another terminal after obtaining the exact model described in [MODEL_NOTES.md](docs/MODEL_NOTES.md):

```bash
python3 pi/crack_inspector.py --model /path/to/crack_model.onnx --camera http://192.168.1.50/capture
```

Open `http://PI_IP:5001`. Replace the example camera IP and model path with the actual values. A separate virtual environment may be needed for ONNX Runtime, OpenCV and NumPy; use the interpreter from the robot's existing working environment when available.

For the experimental stationary inspection test, first stop the manual controller. Keep the crack service running on its default port 5001:

```bash
python3 pi/robot_autonomy.py --control-script "$PWD/pi/robot_web_distance.py" --camera http://192.168.1.50 --motor-port /dev/ttyUSB0
```

Open `http://PI_IP:5002`. The default sends no forward commands. It still opens the motor serial device, checks its STOP reply, and requires the sensor and camera. Read [the original autonomy guide](docs/original/autonomy-START_HERE.txt) before considering `--drive`. Its historical copy paths and IP addresses must be adapted to the current setup.

## Scope and hardware limits

The motor sketches retain their 300 ms timeout. Manual distance readings are informational, without automatic obstacle stopping. The camera sketch serves repeated JPEG snapshots, not an MJPEG stream. The autonomy program implements a limited floor approach, not autonomous wall navigation. These files do not control the vacuum pump or verify adhesion.

The interfaces are local-network prototype services; their request tokens do not provide user login or make them suitable for direct internet exposure. Verify wiring and motor stopping on the actual hardware before operation. The ultrasonic wiring requirements depend on the exact sensor and voltage levels.

The Wi-Fi tools contain boot configuration and recovery checks tied to the original SD card. Preserve those checks; do not copy their `cmdline.txt` onto an unrelated Pi. They are retained as project history, not part of normal robot startup. Do not commit the credential settings or diagnostic logs they generate.

Crack detections are suspected visible defects; they do not measure physical crack width or certify structural safety.

## Files, provenance and verification

- [Source manifest](docs/source-manifest.json): original package names and SHA-256 checksums of recovered files.
- [Validation notes](docs/VALIDATION.md): checks performed while assembling this collection.
- [Model notes](docs/MODEL_NOTES.md): model metadata recorded by the saved crack script.

No project-wide license has been assigned as part of this upload preparation. Preserve any third-party terms and attribution when distributing model files or modifying this collection.
