#!/usr/bin/env python3
"""Bench control: 300ms wheel pulses and camera snapshots. No AI inference."""
import argparse
from datetime import datetime
from pathlib import Path
import time
import urllib.request
import urllib.error
import serial

def read_replies(board, duration=0.65):
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        line = board.readline().decode('utf-8', errors='replace').strip()
        if line:
            print('ESP32:', line)

def save_photo(camera, directory):
    url = camera.rstrip('/') + '/capture'
    with urllib.request.urlopen(url, timeout=5) as response:
        data = response.read(5_000_001)
        if len(data) > 5_000_000 or not data.startswith(b'\xff\xd8'):
            raise ValueError('Camera did not return a valid-size JPEG')
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.jpg')
    path.write_bytes(data)
    print('Saved:', path.resolve())

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True, help='ESP32 USB serial device, e.g. /dev/ttyUSB0')
    parser.add_argument('--camera', help='ESP32-CAM URL, e.g. http://192.168.1.50')
    parser.add_argument('--photos', type=Path, default=Path('inspection_photos'))
    args = parser.parse_args()
    if args.camera and not args.camera.startswith('http://'):
        parser.error('--camera must begin with http://')
    board = None
    try:
        board = serial.Serial(args.port,115200,timeout=0.1,write_timeout=0.5)
        time.sleep(2)  # USB opening may reset the ESP32.
        board.write(b's'); board.flush(); read_replies(board)
        print('Wheels lifted. Each movement lasts only 300ms.')
        print('a = motor A | b = motor B | f = forward | v = reverse')
        print('l/r = turn | s = stop | d = sensor test | c = photo | q = quit')
        while True:
            command = input('Command: ').strip().lower()
            if command == 'q':
                break
            if command == 'c':
                board.write(b's'); board.flush(); read_replies(board,0.15)
                if not args.camera:
                    print('Add --camera http://CAMERA_IP when launching.')
                    continue
                try:
                    save_photo(args.camera,args.photos)
                except (OSError,ValueError,urllib.error.URLError) as exc:
                    print('Photo failed:',exc)
            elif command in ('a','b','f','v','l','r','s','d'):
                board.write(command.encode('ascii')); board.flush()
                read_replies(board)
            else:
                board.write(b's'); board.flush()
                print('Unknown command; STOP sent.')
    except (KeyboardInterrupt,EOFError):
        print('\nStopping.')
    except (serial.SerialException,OSError) as exc:
        print('Connection error:',exc)
    finally:
        if board is not None:
            try:
                if board.is_open:
                    board.write(b's'); board.flush()
            except (serial.SerialException,OSError):
                pass
            board.close()

if __name__ == '__main__':
    main()
