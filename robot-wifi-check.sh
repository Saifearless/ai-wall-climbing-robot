#!/bin/bash
# One diagnostic boot for Sai's existing Raspberry Pi card.
# No passwords, user files, packages or connection profiles are replaced.
set -u
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C
export SYSTEMD_PAGER=cat
export PAGER=cat
export NO_COLOR=1

BOOT=/boot/firmware
ORIGINAL_SHA=fc981e3f87a0cc4ae1c9e6d774d02bbbaf4c225b8cd3ff7d30194c837ee3517e
REPORT="$BOOT/PI-WIFI-REPORT.txt"

# A different Pi/card must not have its boot command replaced by this package.
if ! grep -qE '(^| )root=PARTUUID=0208f461-02( |$)' /proc/cmdline; then
    exit 2
fi
if ! mountpoint -q "$BOOT"; then
    exit 3
fi
exec >"$REPORT" 2>&1 || exit 4
trap 'printf "\nCHECK INTERRUPTED: the outer timeout may have expired.\n"; sync; exit 124' TERM INT
trap 'sync' EXIT

printf 'RASPBERRY PI WI-FI CHECK\n'
date -Is
printf 'This is a special diagnostic boot, not the normal robot startup.\n'
printf 'Network names and local IP addresses may appear; no stored passwords are requested.\n'

# Restore the exact uploaded command line first, so the next boot is normal.
if ! printf '%s  %s\n' "$ORIGINAL_SHA" "$BOOT/cmdline-original.txt" | sha256sum -c -; then
    printf 'ERROR: Original command-line backup missing or changed.\n'
    printf 'Restore your own saved cmdline.txt before starting the Pi normally.\n'
    exit 5
fi
RESTORE=$(mktemp "$BOOT/.robot-cmdline-restore.XXXXXX") || exit 6
if ! cp "$BOOT/cmdline-original.txt" "$RESTORE" || ! mv -f "$RESTORE" "$BOOT/cmdline.txt"; then
    printf 'ERROR: Could not restore cmdline.txt. Restore your laptop backup manually.\n'
    exit 7
fi
sync
printf 'Original cmdline.txt restored for the next boot.\n'

section() { printf '\n===== %s =====\n' "$1"; }
run() {
    local status
    printf '\n$'; printf ' %q' "$@"; printf '\n'
    timeout --kill-after=2s 12s "$@"
    status=$?
    [ "$status" -eq 0 ] || printf '[command exit %s]\n' "$status"
    return 0
}

section 'Hardware, operating system and storage'
run uname -a
run cat /etc/os-release
run cat /proc/device-tree/model
run df -h / "$BOOT"
run vcgencmd get_throttled
run systemctl --no-pager --plain --failed

section 'Wireless state before enabling Wi-Fi'
run rfkill list
run ip -brief link
run systemctl is-enabled NetworkManager.service
run systemctl is-active NetworkManager.service

section 'Start the existing network service'
run systemctl start NetworkManager.service
run nmcli --colors no radio
run nmcli --colors no networking
run nmcli --colors no -f NAME,TYPE,AUTOCONNECT connection show

section 'Enable networking using the saved settings'
# These are the only persistent network setting changes: networking/radio on.
# No SSID, password, IP address or saved connection profile is changed.
run rfkill unblock wifi
run nmcli networking on
run nmcli radio wifi on
printf '\nWaiting 35 seconds for automatic connection...\n'
sleep 35

section 'Result'
run nmcli --colors no general status
run nmcli --colors no device status
run nmcli --colors no -f GENERAL.DEVICE,GENERAL.STATE,GENERAL.REASON,IP4.ADDRESS device show
run ip -brief address
run ip route
run rfkill list
run vcgencmd get_throttled

section 'Visible access points'
run nmcli --colors no --wait 8 -f IN-USE,SSID,SIGNAL,SECURITY device wifi list --rescan yes

section 'Recent network service messages'
run journalctl -b -u NetworkManager.service --no-pager -n 100 -o short-monotonic

section 'Relevant kernel messages'
timeout --kill-after=2s 8s dmesg --color=never |
    grep -Ei 'brcm|wlan|wifi|wireless|rfkill|voltage|under.?voltage|mmc|ext4|I/O error|firmware.*(error|fail)' |
    tail -n 100

section 'Finished'
printf 'CHECK COMPLETE. Original cmdline.txt has been restored.\n'
printf 'The Pi will now shut down. The red power light may remain on.\n'
printf 'After disconnecting USB power, return the card to Windows and send this report.\n'
sync
exit 0
