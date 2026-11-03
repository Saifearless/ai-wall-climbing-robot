#!/bin/bash
# One repair boot for the Pi 4 / Raspberry Pi OS card in PI-WIFI-REPORT.txt.
# Normal boot is restored BEFORE any networking changes.
set -eu
export LC_ALL=C
BOOT=/boot/firmware
REPORT="$BOOT/PI-WIFI-FIX.txt"
PROFILE=/etc/NetworkManager/system-connections/robot-wifi-repair.nmconnection
UUID=13cfe16e-7c38-4c23-ab6f-6e2d34a6b6f4
exec >"$REPORT" 2>&1
finish() {
    local result=$?
    trap - EXIT
    echo
    if [ "$result" -ne 0 ]; then
        echo "REPAIR STOPPED before all steps completed (exit $result)."
        echo 'Share this report for the next step. Do not share the settings JSON.'
    fi
    echo 'The Pi will now shut down. A red power light may remain on.'
    sync
}
trap finish EXIT
echo 'RASPBERRY PI WI-FI REPAIR REPORT'
date -Iseconds
echo 'Special repair boot. Passwords are not included in this report.'
cd "$BOOT"
sha256sum -c cmdline-before-wifi-repair.sha256
if grep -Eq '(^|[[:space:]])(systemd\.run[^[:space:]=]*=|systemd\.unit=|init=)' cmdline-before-wifi-repair.txt; then
    echo 'STOP: backup still contains special boot arguments. Restore a normal cmdline.txt manually.'
    exit 1
fi
cp cmdline-before-wifi-repair.txt cmdline.txt
cmp -s cmdline-before-wifi-repair.txt cmdline.txt
sync
echo 'Original cmdline.txt restored for the next boot.'
python3 "$BOOT/install-profile.py"
timeout 30s systemctl start NetworkManager.service
timeout 10s systemctl enable NetworkManager.service
rfkill unblock wifi
timeout 10s nmcli networking on
timeout 10s nmcli radio wifi on
timeout 10s nmcli connection load "$PROFILE"
echo
echo 'Attempting Wi-Fi connection (up to 60 seconds)...'
CONNECTED=no
if timeout 65s nmcli --colors no --wait 60 connection up uuid "$UUID" ifname wlan0; then
    CONNECTED=yes
fi
echo
echo '--- Result ---'
nmcli --colors no -f DEVICE,TYPE,STATE,CONNECTION device status || true
nmcli --colors no -f GENERAL.STATE,GENERAL.REASON,IP4.ADDRESS device show wlan0 || true
ip -brief address show wlan0 || true
vcgencmd get_throttled || true
if [ "$CONNECTED" = yes ]; then
    echo 'SUCCESS: the saved Wi-Fi profile connected during this repair boot.'
    echo 'After shutdown, disconnect and reconnect power for normal robot startup.'
else
    echo 'PROFILE SAVED, BUT CONNECTION WAS NOT CONFIRMED.'
    echo 'Check that the selected Wi-Fi is on and its name/password were entered correctly.'
    echo 'Run START.cmd again to retry with corrected details if necessary.'
    nmcli --colors no --wait 8 -f SSID,SIGNAL,SECURITY device wifi list --rescan yes || true
fi
echo 'REPAIR COMPLETE. The next boot uses the original cmdline.txt.'
