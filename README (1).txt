RESTORE THE ROBOT HOTSPOT CONNECTION
For the existing Raspberry Pi 4 card, bootfs drive D: on your Windows laptop.

Your diagnostic reached Linux, scanned the Saikiran WPA2 hotspot at signal
100, and recorded throttled=0x0 during that test. NetworkManager had no
loaded Wi-Fi connection profile in the diagnostic boot. This does not tell
us why a profile was absent or prove that all normal startup services work.
The repair saves a connection through NetworkManager and tests association.

WINDOWS LAPTOP
1. Keep the Pi disconnected from power and insert its card in the reader.
2. Extract this ZIP into a folder on the laptop.
3. Copy robot-wifi-reconnect.py into the TOP LEVEL of bootfs (D:), beside
   config.txt. Copy the actual file, not its folder. Leave other files alone.
4. Open SETUP-IN-POWERSHELL.txt from the extracted laptop folder in Notepad.
   Press Ctrl+A, then Ctrl+C. Open Windows PowerShell (PS C:\Users\manda>),
   paste the entire block, and press Enter if needed.
5. At the hotspot-name prompt, press Enter for Saikiran, or type the exact
   current name (capital letters matter). At the password prompt, type your
   CURRENT phone-hotspot password and press Enter. Characters are hidden.
   Do not send your password to ChatGPT.
6. Continue only after the green READY message. An error means stop and send
   its text/screenshot. Do not change the checked hashes or ignore errors.

PI STARTUP
7. Safely eject the reader. Insert the card in the Pi while power is off.
   Keep ESP32 boards and motors disconnected, and keep the hotspot on.
8. Power the Pi. Allow FIVE minutes for this repair and one normal restart.
   On success it restarts once and should appear as robot in the hotspot
   connected-device list. It should then remain powered and connected.
9. Read robot's CURRENT IP address in that list. The previous IP may change.
   Connect your laptop to the same hotspot, then use Windows PowerShell:
       ssh sai@CURRENT_PI_IP
   Replace CURRENT_PI_IP with the actual address; do not type that placeholder.
10. If robot does not appear after five minutes, disconnect the Pi's USB-C
    power before removing the card. Put it back in the laptop reader and send
    PI-WIFI-RECONNECT.txt from bootfs. A failed attempt shuts down deliberately;
    the red power light may remain on. If there is no report, tell ChatGPT.

CHANGES
- Validates the original boot-file backup and the repair script before setup.
- Temporarily writes robot-wifi-settings.json on the card with credentials
  entered locally; the Pi removes that temporary file after reading it.
- Restores the original cmdline.txt before attempting the repair.
- Enables NetworkManager and the existing SSH service for normal boot.
- Turns Wi-Fi/networking on, connects to the requested hotspot using nmcli,
  and saves automatic reconnection with priority 100 for the active profile.
- Does not format, reinstall, install packages, delete other profiles,
  replace robot programs/models, reset login passwords or control GPIO/motors.
- Creates PI-WIFI-RECONNECT.txt; it does not intentionally record the password.
  Do not upload robot-wifi-settings.json if it remains on the card.
- Success restarts once. Failure shuts down. Commands have timeouts and an
  outer limit of 210 seconds once the repair script starts.

UNDO THE TEMPORARY BOOT (IF NEEDED)
With Pi power disconnected and the card in the reader, copy your original
laptop backup of cmdline.txt onto bootfs as cmdline.txt, replacing the
repair version. The existing cmdline-original.txt is also the exact backup.
Remove robot-wifi-settings.json if it remains. Other files can be left alone.
The repair normally restores the boot command itself. This undo does not
remove a successfully saved Wi-Fi profile or disable SSH.

TESTING LIMITS
Original-file restoration, mocked successful/failed connections, local
credential deletion/redaction, input validation and generated boot-command
handling were tested. The repair has not been run on your physical Pi.
Neither successful association in this repair nor a zero power-warning
reading proves long-term power stability or normal robot app startup.

REFERENCE
https://networkmanager.dev/docs/api/latest/nmcli.html
https://manpages.debian.org/trixie/systemd/systemd-run-generator.8.en.html
