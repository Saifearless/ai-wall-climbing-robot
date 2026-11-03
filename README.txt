ONE-BOOT RASPBERRY PI WI-FI CHECK
Prepared for the existing card with root PARTUUID 0208f461-02.

The uploaded config.txt does not disable Wi-Fi, and cmdline.txt specifies
wireless country IN. These files cannot confirm a successful boot, power
quality or the current saved Wi-Fi credentials.

INSTALL
1. Keep a copy of your original cmdline.txt on the Windows laptop.
2. With Pi power disconnected, put its card in your laptop's reader.
3. Extract this ZIP into a folder on the laptop.
4. Copy these THREE files to the top level of the card's bootfs drive,
   beside config.txt: cmdline.txt, cmdline-original.txt, robot-wifi-check.sh.
   Replace cmdline.txt when Windows asks. Do not change config.txt.
   Copy the actual files, not the enclosing folder or the ZIP itself.
5. Safely eject the reader. Put the card in the Pi.
6. Keep your usual hotspot on with the same name and password. Keep the
   ESP32 boards and motors disconnected. Power the Pi and wait FIVE minutes.
7. This test intentionally shuts the Pi down after collecting the report.
   The red light may remain on. A temporary hotspot connection can disappear
   when it shuts down; this is expected during this diagnostic test.
8. After five minutes, disconnect USB-C power, put the card back in the
   reader, and send PI-WIFI-REPORT.txt from bootfs to ChatGPT.

WHAT IT DOES
- Runs a bounded, temporary diagnostic instead of the normal robot startup.
- Restores the exact original cmdline.txt at the start of the check.
- Starts the existing NetworkManager service for this boot, unblocks Wi-Fi,
  and turns networking and Wi-Fi on using the saved connection settings.
- Collects OS, disk, radio, power-warning, network and relevant kernel status.
- Does not replace passwords, connection profiles, Python files or models.
- Does not format the card, install packages or control GPIO/motors.
- The report can contain network names and local IP/MAC addresses. It does
  not request secret fields or copy Wi-Fi credential files.
- Shuts down when complete (or when the outer 150-second timeout fires).
  The five-minute allowance includes time before the diagnostic starts.

IF THERE IS NO REPORT
This does NOT prove that the card or Pi is broken. The diagnostic may not
have been reached, the files may be in the wrong location, or boot/power/
mounting may have failed. Send a screenshot of the bootfs file list.
Restore your saved original cmdline.txt before a normal startup.

UNDO / NORMAL STARTUP
With the Pi disconnected from power and the card in the reader:
- Copy cmdline-original.txt to cmdline.txt, replacing the diagnostic version.
  Or restore the original cmdline.txt you saved on your laptop.
- Keep all other existing card files. Safely eject before powering the Pi.
- The check normally restores cmdline.txt automatically; this manual step
  also works if the diagnostic never started.
The diagnostic turns Wi-Fi/networking on; it otherwise leaves network
settings intact. It does not set up automatic startup of robot programs.

VALIDATION AND LIMITS
Shell syntax, original-file restoration, refusal on a wrong card or altered
backup, timeout command generation and report creation were checked locally.
This has NOT been run on your physical Pi, so successful boot or reconnection
is not guaranteed. config.txt and cmdline.txt alone cannot prove card health.

SOURCES
https://manpages.debian.org/trixie/systemd/systemd-run-generator.8.en.html
https://networkmanager.dev/docs/api/latest/nmcli.html
https://www.raspberrypi.com/documentation/computers/configuration.html
