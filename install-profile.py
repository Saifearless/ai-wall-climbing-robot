#!/usr/bin/env python3
"""Install this repair's own WPA2 profile. Never print input credentials."""
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

PROFILE_UUID = '13cfe16e-7c38-4c23-ab6f-6e2d34a6b6f4'


def make_profile(settings):
    ssid = settings.get('ssid')
    password = settings.get('password')
    if not isinstance(ssid, str) or not isinstance(password, str):
        raise ValueError('Invalid settings')
    ssid_bytes = ssid.encode('utf-8')
    if not 1 <= len(ssid_bytes) <= 32 or any(ord(c) < 32 or ord(c) == 127 for c in ssid):
        raise ValueError('Invalid SSID')
    if re.fullmatch(r'[0-9a-fA-F]{64}', password):
        psk = password.lower()
    elif re.fullmatch(r'[\x20-\x7e]{8,63}', password):
        psk = hashlib.pbkdf2_hmac('sha1', password.encode('ascii'), ssid_bytes, 4096, 32).hex()
    else:
        raise ValueError('Invalid WPA2 password')
    # Decimal bytes are supported by the Pi's NetworkManager keyfile reader.
    encoded_ssid = ''.join(str(b) + ';' for b in ssid_bytes)
    return (
        '[connection]\n'
        'id=robot-wifi-repair\n'
        f'uuid={PROFILE_UUID}\n'
        'type=wifi\n'
        'interface-name=wlan0\n'
        'autoconnect=true\n'
        '\n[wifi]\n'
        'mode=infrastructure\n'
        f'ssid={encoded_ssid}\n'
        '\n[wifi-security]\n'
        'key-mgmt=wpa-psk\n'
        'proto=rsn;\n'
        f'psk={psk}\n'
        'psk-flags=0\n'
        '\n[ipv4]\n'
        'method=auto\n'
        '\n[ipv6]\n'
        'method=auto\n'
    )


def install(settings_path, profile_path):
    settings = json.loads(settings_path.read_text(encoding='utf-8-sig'))
    profile = make_profile(settings)
    if profile_path.exists():
        old = profile_path.read_text(encoding='utf-8')
        if not re.search(r'^uuid=' + re.escape(PROFILE_UUID) + r'$', old, re.MULTILINE):
            raise ValueError('An unrelated profile occupies the repair filename')
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix='.robot-wifi-', dir=profile_path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(profile)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, profile_path)
    finally:
        Path(temp_name).unlink(missing_ok=True)
    settings_path.unlink()
    print('Saved a persistent WPA2 Wi-Fi profile and removed the temporary password file.')


if __name__ == '__main__':
    try:
        install(
            Path('/boot/firmware/robot-wifi-settings.json'),
            Path('/etc/NetworkManager/system-connections/robot-wifi-repair.nmconnection'),
        )
    except Exception:
        print('Profile installation failed. Check the settings using START.cmd, then retry.')
        print('Credentials have not been printed. Do not upload robot-wifi-settings.json.')
        sys.exit(1)
