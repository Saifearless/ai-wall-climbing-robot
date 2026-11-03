ESP32 motor controller + HC-SR04 distance test

This is the earlier supplied motor starter sketch, with USE_HCSR04 changed to true.
Motor pin assignments, serial commands, motor duty and the 300 ms timeout are unchanged.
It enables distance testing; it does not add autonomous driving or obstacle stopping.
Reviewed against the original file; not compiled or tested on the physical robot here.

WIRING: make all changes with USB and motor power disconnected.
Use the PRINTED ESP32 labels, not Raspberry Pi physical pin numbers.
Sensor TRIG (yellow wire): D18 / GPIO18.
Sensor ECHO (blue wire): 1k resistor R1, then a junction connected to D19 / GPIO19.
From that junction: 1k R2 in series with 1k R3 to GND (2k total).
Sensor GND (red wire): ESP32 GND. Divider ground joins the same GND.
Sensor VCC (green wire): USB-derived 5V/VIN rail on this DevKit-style board.
Use USB as the ESP32 power input for this test; never connect the 12V motor supply to VIN or the sensor.
Do not also power the ESP32 from the L298N 5V terminal while USB is connected.
Disconnect the old ultrasonic signal connections from the Pi.
Use three confirmed 1k-ohm resistors: brown-black-red-gold for four-band parts.
Do not use the 100-ohm brown-black-brown-gold parts for this divider.
Keep bare joints insulated and clear of the boards and connector shells.

Existing L298N mapping:
ENA=25, IN1=26, IN2=27, IN3=32, IN4=33, ENB=14.
Keep existing motor wires and ENA/ENB jumper configuration as before.

UPLOAD AND TEST:
1. Extract this ZIP. Open esp32_motor_ultrasonic/esp32_motor_ultrasonic.ino in Arduino IDE.
2. Keep motor battery disconnected; connect MOTOR ESP32 to laptop using a USB data cable.
3. Select ESP32 Dev Module, its COM port, and Espressif ESP32 board package 3.x.
4. Upload. If connection stalls, hold BOOT while the upload connects, then release.
5. Open Serial Monitor at 115200 baud. Send s; expect STOP.
6. Place a flat book 20-30 cm ahead of the ultrasonic sensor. Send lowercase d once.
7. Expect DISTANCE cm: followed by a number. Wait at least 0.1 second before sending d again.
8. DISTANCE no valid echo means no usable reading; it does not mean the path is clear.

The d command stops the motors before measuring. Do not send motor movement commands during this sensor test.
To return USB to the Pi, close Serial Monitor first. Power off before changing wiring.

Reference: Espressif Arduino-ESP32 LEDC API
https://docs.espressif.com/projects/arduino-esp32/en/latest/api/ledc.html
