#!/usr/bin/env python3
"""One-boot Wi-Fi repair for the existing robot card; credentials stay local."""
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import uuid

BOOT = Path('/boot/firmware')
PROC_CMDLINE = Path('/proc/cmdline')
ORIGINAL_SHA = 'fc981e3f87a0cc4ae1c9e6d774d02bbbaf4c225b8cd3ff7d30194c837ee3517e'
SECRET_NAME = 'robot-wifi-settings.json'
PASSWORD = ''
LOG = None
ENV = dict(os.environ, PATH='/usr/sbin:/usr/bin:/sbin:/bin', LC_ALL='C',
           NO_COLOR='1', SYSTEMD_PAGER='cat', PAGER='cat')


class RepairError(Exception):
    pass


def log(text):
    text = str(text)
    if PASSWORD:
        text = text.replace(PASSWORD, '[password removed]')
    if LOG:
        LOG.write(text + '\n')
        LOG.flush()


def run(label, args, timeout=20, required=True, show=True):
    # Never print argv: the connection command contains the password.
    log('\n' + label)
    try:
        result = subprocess.run(args, env=ENV, text=True, encoding='utf-8',
                                errors='replace', stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RepairError(label + ': timed out') from None
    except OSError:
        raise RepairError(label + ': could not start command') from None
    if show:
        log(result.stdout.rstrip())
    if result.returncode:
        log('Command exit: ' + str(result.returncode))
        if required:
            raise RepairError(label + ': failed; see messages above')
    return result.stdout.strip()


def restore_original():
    original = (BOOT / 'cmdline-original.txt').read_bytes()
    if hashlib.sha256(original).hexdigest() != ORIGINAL_SHA:
        raise RepairError('Original cmdline backup does not match. Restore your laptop backup.')
    fd, name = tempfile.mkstemp(prefix='.robot-cmdline-', dir=BOOT)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(original)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, BOOT / 'cmdline.txt')
        os.sync()
    finally:
        Path(name).unlink(missing_ok=True)
    log('Original cmdline.txt restored. The next boot will be normal.')


def validate_settings(settings):
    if not isinstance(settings, dict):
        raise RepairError('Settings must be a JSON object. Run the laptop setup again.')
    ssid, password = settings.get('ssid'), settings.get('password')
    if not isinstance(ssid, str) or not 1 <= len(ssid.encode('utf-8')) <= 32:
        raise RepairError('Hotspot name must be 1-32 UTF-8 bytes.')
    if not isinstance(password, str):
        raise RepairError('Missing hotspot password. Run the laptop setup again.')
    if any(c in ssid + password for c in '\x00\r\n'):
        raise RepairError('Hotspot name/password contains an invalid line break.')
    if not (8 <= len(password.encode('utf-8')) <= 63 or re.fullmatch(r'[0-9a-fA-F]{64}', password)):
        raise RepairError('WPA2 password must be 8-63 bytes, or a 64-character hexadecimal key.')
    return ssid, password


def interrupted(signum, frame):
    raise RepairError('The repair exceeded its time limit or was interrupted.')


def main():
    global PASSWORD, LOG
    if not re.search(r'(^|\s)root=PARTUUID=0208f461-02(\s|$)', PROC_CMDLINE.read_text()):
        return 2
    if not os.path.ismount(BOOT):
        return 3
    secret = BOOT / SECRET_NAME
    try:
        LOG = (BOOT / 'PI-WIFI-RECONNECT.txt').open('w', encoding='utf-8')
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        log('ROBOT WI-FI RECONNECTION')
        log(time.strftime('%Y-%m-%d %H:%M:%S %z'))
        restore_original()
        ssid, PASSWORD = validate_settings(json.loads(secret.read_text(encoding='utf-8-sig')))
        # Remove the temporary FAT-partition credential file after reading it.
        # NetworkManager will save the connection through its normal settings backend.
        secret.unlink()
        os.sync()
        log('Requested hotspot: ' + ssid)

        run('Enable networking and SSH for normal startups',
            ['systemctl', 'enable', 'NetworkManager.service', 'ssh.service'])
        run('Start NetworkManager for this repair', ['systemctl', 'start', 'NetworkManager.service'])
        run('Unblock Wi-Fi', ['rfkill', 'unblock', 'wifi'])
        run('Enable networking', ['nmcli', 'networking', 'on'])
        run('Enable Wi-Fi radio', ['nmcli', 'radio', 'wifi', 'on'])
        time.sleep(3)
        run('Refresh Wi-Fi scan', ['nmcli', '--wait', '10', 'device', 'wifi', 'list',
                                 'ifname', 'wlan0', '--rescan', 'yes'], show=False)
        run('Connect using the password entered on your laptop',
            ['nmcli', '--colors', 'no', '--wait', '60', 'device', 'wifi', 'connect',
             ssid, 'password', PASSWORD, 'ifname', 'wlan0',
             'name', 'robot-hotspot-recovery', 'private', 'no'], timeout=70)

        active = run('Read active connection identifier',
                     ['nmcli', '-g', 'GENERAL.CON-UUID', 'device', 'show', 'wlan0'])
        try:
            active = str(uuid.UUID(active))
        except ValueError:
            raise RepairError('No active Wi-Fi connection identifier was returned.') from None
        run('Save automatic reconnection', ['nmcli', 'connection', 'modify', 'uuid', active,
                                           'connection.autoconnect', 'yes',
                                           'connection.autoconnect-priority', '100'])
        addresses = run('Wi-Fi IPv4 address', ['nmcli', '-g', 'IP4.ADDRESS', 'device', 'show', 'wlan0'])
        if not addresses:
            raise RepairError('Wi-Fi connected but no IPv4 address was assigned.')
        run('Connection status', ['nmcli', '--colors', 'no', 'device', 'status'])
        run('Power status during repair', ['vcgencmd', 'get_throttled'], required=False)
        log('\nREPAIR COMPLETE. A Wi-Fi connection is active and autoconnect is saved.')
        log('The Pi will restart ONCE into its original normal boot configuration.')
        log('After the restart, check the hotspot device list for robot and its current IP.')
        return 0
    except RepairError as exc:
        log('\nREPAIR FAILED: ' + str(exc))
    except Exception as exc:
        # Do not print exception repr/traceback or JSON contents (may contain credentials).
        log('\nREPAIR FAILED: ' + type(exc).__name__ + '. Send this report for review.')
    finally:
        try:
            secret.unlink(missing_ok=True)
        except OSError:
            log('Could not remove temporary settings file. Remove robot-wifi-settings.json on the laptop.')
        if LOG:
            LOG.flush()
            os.fsync(LOG.fileno())
        os.sync()
    log('The Pi will shut down after this failed attempt. Return the card to the reader.')
    if LOG:
        LOG.flush()
        os.fsync(LOG.fileno())
    os.sync()
    return 1


if __name__ == '__main__':
    sys.exit(main())
