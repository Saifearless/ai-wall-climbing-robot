#!/usr/bin/env python3
"""One supervised floor approach and stationary crack scan.

Run with /usr/bin/python3 alongside the existing crack_inspector.py service.
The old robot_web_distance.py server MUST be stopped: USB/GPIO have one owner.
Default: stationary test only. --drive permits bounded forward steps.
Uses the existing Pi GPIO23/24 DistanceReader and ESP32 f/s, 300 ms timeout.
This is not wall climbing, wall following, route planning, or full wall coverage.
"""
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import secrets
import signal
import threading
import time
from urllib.request import Request, build_opener, ProxyHandler

from flask import Flask, jsonify, render_template_string, request
import serial


@dataclass(frozen=True)
class Settings:
    drive: bool = False
    stop_cm: float = 40.0
    too_close_cm: float = 25.0
    max_start_cm: float = 120.0
    step_seconds: float = 0.06
    settle_seconds: float = 0.35
    max_steps: int = 20
    motion_seconds: float = 25.0
    lease_seconds: float = 1.2
    max_age: float = 0.45
    sensor_timeout: float = 2.0


class Halt(Exception):
    pass


class Motor:
    def __init__(self, port):
        self.io = threading.Lock()
        self.device = serial.Serial(baudrate=115200, timeout=0.05,
                                    write_timeout=0.1, exclusive=True)
        self.device.dtr = False
        self.device.rts = False
        self.device.port = port

    def open(self):
        self.device.open()
        time.sleep(2)
        self.stop(confirm=True, timeout=3)

    def _write(self, command):
        if self.device.write(command) != 1:
            raise OSError('Incomplete motor USB write.')

    def forward(self):
        with self.io:
            self._write(b'f')

    def stop(self, confirm=False, timeout=0.35):
        with self.io:
            if confirm:
                self.device.reset_input_buffer()
            self._write(b's')
            if confirm:
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    if self.device.readline().strip() == b'STOP':
                        return
                raise OSError('No STOP reply from the motor ESP32. Keep motor power off and check its firmware/USB port.')

    def close(self):
        with self.io:
            if self.device.is_open:
                try:
                    self._write(b's')
                finally:
                    self.device.close()


def make_reader(control_script):
    path = Path(control_script).expanduser().resolve()
    if not path.is_file():
        raise RuntimeError('Missing existing control script: ' + str(path))
    spec = importlib.util.spec_from_file_location('existing_robot_controls', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # Imports definitions; does not call main().
    base = getattr(module, 'DistanceReader', None)
    if base is None or (base.TRIG, base.ECHO) != (23, 24):
        raise RuntimeError('This add-on expects the working Pi GPIO23/24 distance reader. Do not rewire to match it.')

    class Reader(base):
        INTERVAL = 0.12
        STALE_AFTER = 0.45

        def __init__(self):
            super().__init__()
            self.sequence = 0

        def _publish(self, distance, message):
            with self._state_lock:
                self.sequence += 1
                self._state = distance, message, time.monotonic()

        def snapshot(self):
            with self._state_lock:
                value, message, updated = self._state
                sequence = self.sequence
            return dict(distance_cm=value, message=message, updated=updated,
                        sequence=sequence)
    return Reader()


class Inspector:
    """Adapter for the existing, locally running crack_inspector.py API."""
    def __init__(self, camera, service='http://127.0.0.1:5001'):
        self.camera = camera.rstrip('/') + '/capture'
        self.service = service.rstrip('/')
        self.http = build_opener(ProxyHandler({}))
        self.key = None

    def _read(self, url, *, data=None, headers=None, timeout=3, limit=200000):
        req = Request(url, data=data, headers=headers or {})
        with self.http.open(req, timeout=timeout) as response:
            payload = response.read(limit + 1)
        if len(payload) > limit:
            raise RuntimeError('Unexpectedly large camera or inspection response.')
        return payload

    def prepare(self):
        page = self._read(self.service + '/').decode('utf-8')
        match = re.search(r'\bconst\s+token\s*=\s*"([0-9a-f]{48})"\s*;', page)
        if not match:
            raise RuntimeError('Crack service API differs from the saved version. Send the current crack_inspector.py.')
        self.key = match.group(1)
        picture = self._read(self.camera + '?t=' + str(time.time_ns()), limit=5000000)
        if not picture.startswith(b'\xff\xd8'):
            raise RuntimeError('Camera did not return a JPEG. Check camera IP and /capture.')

    def scan(self):
        data = self._read(self.service + '/scan', data=b'{"threshold":0.35}',
                          headers={'Content-Type': 'application/json', 'X-Scan-Key': self.key},
                          timeout=90)
        result = json.loads(data)
        if not isinstance(result, dict) or type(result.get('count')) is not int or result['count'] < 0:
            raise RuntimeError('Unexpected crack scan response.')
        for field, filename in [('original','original.jpg'), ('marked','marked.jpg'), ('report','report.json')]:
            if not re.fullmatch(r'/results/[0-9a-f]{32}/' + re.escape(filename), result.get(field, '')):
                raise RuntimeError('Unexpected scan result address.')
        return result


class Controller:
    def __init__(self, motor, reader, inspector, settings=None, output=None):
        self.motor, self.reader, self.inspector = motor, reader, inspector
        self.cfg = settings or Settings()
        self.output = Path(output).expanduser() if output else None
        self.lock = threading.RLock()
        self.motion_lock = threading.Lock()
        self.closed = threading.Event()
        self.job = None
        self.epoch = 0
        self.phase, self.message = 'Ready', 'Stationary test ready. No movement is enabled.'
        if self.cfg.drive:
            self.message = 'Drive mode enabled. Place the robot on the floor facing the wall, then press Start.'
        self.steps, self.result = 0, None
        self.monitor = threading.Thread(target=self._watch, daemon=True)
        self.monitor.start()

    def state(self):
        snap = self.reader.snapshot()
        value = snap.get('distance_cm')
        updated = snap.get('updated')
        valid = self._valid(snap)
        with self.lock:
            alive = bool(self.job and self.job['thread'].is_alive())
            return dict(phase=self.phase, message=self.message, busy=alive,
                        active=alive and not self.job['cancel'].is_set(), epoch=self.epoch,
                        drive=self.cfg.drive, steps=self.steps, result=self.result,
                        distance_cm=value if valid else None,
                        sensor_message=snap.get('message') if not valid else 'Fresh distance',
                        age_ms=None if updated is None else round(1000*(time.monotonic()-updated)))

    def _valid(self, snap):
        value, updated = snap.get('distance_cm'), snap.get('updated')
        return (type(value) in (int,float) and math.isfinite(value) and 2 <= value <= 400
                and type(updated) in (int,float) and math.isfinite(updated)
                and 0 <= time.monotonic()-updated <= self.cfg.max_age)

    def start(self, owner, epoch):
        with self.lock:
            if self.closed.is_set():
                raise Halt('App is shutting down.')
            if epoch != self.epoch:
                raise Halt('State changed. Refresh the page before starting again.')
            if self.job and self.job['thread'].is_alive():
                raise Halt('A cycle is still finishing. Wait; do not restart it.')
            self.epoch += 1
            self.steps, self.result = 0, None
            job = dict(owner=owner, id=secrets.token_hex(16), cancel=threading.Event(),
                       lease=time.monotonic()+self.cfg.lease_seconds,
                       started=datetime.now(timezone.utc).isoformat())
            self.phase, self.message = 'Checking', 'Checking distance, camera and crack service. Motors stopped.'
            job['thread'] = threading.Thread(target=self._run, args=(job,), daemon=True)
            self.job = job
            job['thread'].start()
            return job['id']

    def heartbeat(self, owner, job_id):
        with self.lock:
            job = self.job
            if not job or job['owner'] != owner or job['id'] != job_id or job['cancel'].is_set():
                raise Halt('Cycle is no longer active.')
            if time.monotonic() >= job['lease']:
                self.stop('Control connection expired. Start again when ready.')
                raise Halt('Control connection expired.')
            job['lease'] = time.monotonic() + self.cfg.lease_seconds

    def stop(self, message='Stopped by operator.'):
        with self.lock:
            if self.job:
                self.job['cancel'].set()
            self.epoch += 1
            self.phase, self.message = 'Stopped', message
        try:
            with self.motion_lock:
                self.motor.stop()
        except Exception as error:
            with self.lock:
                self.message += ' STOP delivery failed: ' + str(error)[:150]

    def _watch(self):
        while not self.closed.wait(0.05):
            with self.lock:
                expired = (self.job and self.job['thread'].is_alive()
                           and not self.job['cancel'].is_set()
                           and time.monotonic() >= self.job['lease'])
            if expired:
                self.stop('Control connection lost. Cycle stopped; it will not resume automatically.')

    def _guard(self, job):
        if self.closed.is_set() or job['cancel'].is_set():
            raise Halt('Cycle cancelled.')
        if time.monotonic() >= job['lease']:
            raise Halt('Control connection lost.')

    def _wait(self, job, seconds):
        end = time.monotonic()+seconds
        while time.monotonic() < end:
            self._guard(job)
            job['cancel'].wait(min(0.01, max(0, end-time.monotonic())))
        self._guard(job)

    def _phase(self, job, name, message):
        with self.lock:
            self._guard(job)
            self.phase, self.message = name, message

    def _distance(self, job, after):
        deadline = time.monotonic()+self.cfg.sensor_timeout
        readings, last = [], None
        while time.monotonic() < deadline:
            self._guard(job)
            snap = self.reader.snapshot()
            if snap.get('updated') is not None and snap['updated'] >= after:
                if not self._valid(snap):
                    raise Halt('Distance missing, invalid or stale. ' + str(snap.get('message', '')))
                if snap.get('sequence') != last:
                    readings.append(snap['distance_cm'])
                    last = snap.get('sequence')
                    if len(readings) == 2:
                        if abs(readings[0]-readings[1]) > 6:
                            raise Halt('Distance readings are unstable. Keep robot and target still.')
                        return min(readings)
            self._wait(job, 0.02)
        raise Halt('No two fresh sensor readings. Check sensor and wall alignment.')

    def _step(self, job):
        with self.motion_lock:
            self._guard(job)
            snap = self.reader.snapshot()
            if not self._valid(snap) or snap['distance_cm'] <= self.cfg.stop_cm:
                raise Halt('Distance changed before moving. Cycle stopped.')
            self.motor.forward()
        try:
            end = time.monotonic()+self.cfg.step_seconds
            while time.monotonic() < end:
                self._guard(job)
                snap = self.reader.snapshot()
                if not self._valid(snap):
                    raise Halt('Sensor fault during movement.')
                if snap['distance_cm'] <= self.cfg.stop_cm:
                    break
                self._wait(job, 0.005)
        finally:
            with self.motion_lock:
                self.motor.stop(confirm=True)

    def _run(self, job):
        try:
            with self.motion_lock:
                self.motor.stop(confirm=True)
            self.inspector.prepare()
            self._guard(job)
            distance = self._distance(job, time.monotonic())
            deadline = time.monotonic()+self.cfg.motion_seconds
            if self.cfg.drive:
                while True:
                    self._guard(job)
                    if distance < self.cfg.too_close_cm:
                        raise Halt('Too close to the wall. Reposition manually; no automatic reversing.')
                    if distance > self.cfg.max_start_cm:
                        raise Halt('Wall too far away or echo lost. Position the robot 40–60 cm from a broad wall.')
                    if distance <= self.cfg.stop_cm:
                        break
                    if self.steps >= self.cfg.max_steps or time.monotonic() >= deadline:
                        raise Halt('Approach limit reached. Stopped without scanning; reposition manually.')
                    self._phase(job, 'Approaching', 'Taking one short forward step, then checking distance.')
                    self._step(job)
                    with self.lock:
                        self.steps += 1
                    self._wait(job, self.cfg.settle_seconds)
                    distance = self._distance(job, time.monotonic())
            with self.motion_lock:
                self.motor.stop(confirm=True)
            self._phase(job, 'Scanning', 'Motors stopped. Capturing and analysing one wall photograph…')
            self._wait(job, self.cfg.settle_seconds)
            result = self.inspector.scan()
            self._guard(job)
            with self.lock:
                self._guard(job)
                self.result = result
                self.phase = 'Complete'
                self.message = ('Stationary test complete. No movement commanded. ' if not self.cfg.drive else 'Inspection cycle complete. Robot remains stopped. ') + str(result['count']) + ' suspected crack region(s). Review the image.'
        except Exception as error:
            with self.lock:
                if not job['cancel'].is_set():
                    self.phase, self.message = 'Stopped', str(error)[:300]
                job['cancel'].set()
        finally:
            try:
                with self.motion_lock:
                    self.motor.stop()
            except Exception as error:
                with self.lock:
                    self.phase, self.message = 'Stopped', 'Motor connection failed: '+str(error)[:200]
            if self.output:
                try:
                    self.output.mkdir(parents=True, exist_ok=True)
                    record = self.state()
                    record.update(started=job['started'], id=job['id'], busy=False, active=False)
                    (self.output/(job['id']+'.json')).write_text(json.dumps(record, indent=2), encoding='utf-8')
                except Exception as error:
                    print('Could not save cycle log:', error, flush=True)

    def close(self):
        self.closed.set()
        self.stop('Application shutting down.')
        self.monitor.join(timeout=1)
        if self.job:
            self.job['thread'].join(timeout=1)


PAGE = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Automatic inspection</title>
<style>body{font:17px system-ui;background:#eef3f8;color:#16304a;margin:0}main{max-width:700px;margin:auto;padding:22px}.card{background:white;border-radius:16px;padding:20px;margin:18px 0}h1{font-size:28px}button{font:700 19px system-ui;padding:20px;border:0;border-radius:12px;color:white;background:#1467ad;width:100%;margin:8px 0;touch-action:manipulation}button:disabled{opacity:.45}#stop{background:#b82424}#distance{font-size:40px;font-weight:bold}img{width:100%;border-radius:10px}a{color:#125c99}small{line-height:1.6;display:block}#message{min-height:70px;line-height:1.5}</style>
<main><h1>Automatic wall inspection</h1><p>{{ 'DRIVE MODE — short forward steps' if drive else 'STATIONARY TEST — movement disabled' }}</p>
<div class="card"><small>Front distance</small><div id="distance">— cm</div><p id="phase">Connecting…</p><p id="message"></p>
{% if drive %}<label><input id="ready" type="checkbox"> Robot is supported for a supervised floor test, facing a broad wall; wheels and path are clear.</label>{% endif %}
<button id="start" disabled>{{ 'Start one inspection' if drive else 'Test sensor + camera + crack detection' }}</button>
<button id="stop">STOP</button><small>Keep this page open and visible. Leaving it stops the cycle. No automatic turning, reversing or restarting.</small></div>
<section class="card" id="result" hidden><h2>Scan result</h2><img id="marked" alt="Marked wall photograph"><p><a id="original" target="_blank" rel="noopener">Original photograph</a> · <a id="report" target="_blank" rel="noopener">Scan data</a></p><small>Model output marks suspected visible cracks. Review the image; this is not a structural safety assessment.</small></section>
<small>This version approaches one wall and scans once. It does not climb, follow a wall or inspect an entire room. The existing motor firmware has no speed command: steps use its normal forward power.</small>
<script>
const key={{key|tojson}},owner={{owner|tojson}};let run=null,epoch={{epoch|tojson}},starting=false;
const start=document.getElementById('start'),message=document.getElementById('message'),result=document.getElementById('result');
async function action(path,data={}){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Auto-Key':key},body:JSON.stringify({owner,...data}),signal:AbortSignal.timeout(800)});const j=await r.json();if(!r.ok)throw Error(j.error||'Request failed');return j}
function stop(){run=null;starting=false;fetch('/stop',{method:'POST',headers:{'Content-Type':'application/json','X-Auto-Key':key},body:JSON.stringify({owner}),keepalive:true}).catch(()=>{});message.textContent='Stopping…';}
document.getElementById('stop').onclick=stop;
start.onclick=async()=>{const ready=document.getElementById('ready');if(starting||(ready&&!ready.checked))return;starting=true;start.disabled=true;result.hidden=true;try{const j=await action('/start',{epoch,ready:!!(ready&&ready.checked)});run=j.run;epoch=j.epoch;if(document.hidden)stop()}catch(e){message.textContent=e.message;stop()}finally{starting=false}};
async function poll(){try{if(run)await action('/heartbeat',{run});const r=await fetch('/state',{cache:'no-store',signal:AbortSignal.timeout(800)});if(!r.ok)throw Error('Status unavailable');const s=await r.json();epoch=s.epoch;
 document.getElementById('phase').textContent=s.phase+' · '+s.steps+' step(s)';message.textContent=s.message;document.getElementById('distance').textContent=s.distance_cm===null?'— cm':s.distance_cm.toFixed(1)+' cm';
 const check=document.getElementById('ready');start.disabled=s.busy||starting||!!(check&&!check.checked);if(!s.busy)run=null;
 if(s.result){const base=new URL(location.href);base.port='5001';document.getElementById('marked').src=new URL(s.result.marked,base);document.getElementById('original').href=new URL(s.result.original,base);document.getElementById('report').href=new URL(s.result.report,base);result.hidden=false;}
 }catch(e){if(run||starting)stop();start.disabled=true;message.textContent='Connection lost. The cycle stops automatically; reconnect and start again.'}finally{setTimeout(poll,300)}}
window.addEventListener('pagehide',()=>{if(run||starting)stop()});window.addEventListener('blur',()=>{if(run||starting)stop()});document.addEventListener('visibilitychange',()=>{if(document.hidden&&(run||starting))stop()});document.addEventListener('keydown',e=>{if(e.code==='Escape'||e.code==='Space'){e.preventDefault();stop()}});poll();
</script></main></html>'''


def create_app(controller):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 2048
    key = secrets.token_urlsafe(32)
    owners = set()
    owner_lock = threading.Lock()

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Frame-Options'] = 'DENY'
        return response

    @app.before_request
    def auth():
        if request.method == 'POST':
            data = request.get_json(silent=True)
            if not secrets.compare_digest(request.headers.get('X-Auto-Key',''), key):
                return jsonify(error='Reload the page.'), 403
            if not isinstance(data, dict) or not isinstance(data.get('owner'), str):
                return jsonify(error='Invalid request.'), 400
            with owner_lock:
                if data['owner'] not in owners:
                    return jsonify(error='Reload the page.'), 403

    @app.get('/')
    def home():
        owner = secrets.token_hex(16)
        with owner_lock:
            if len(owners) >= 100:
                return 'Restart this app to open more sessions.', 503
            owners.add(owner)
        return render_template_string(PAGE, key=key, owner=owner,
                                      drive=controller.cfg.drive, epoch=controller.state()['epoch'])

    @app.get('/state')
    def state():
        return jsonify(controller.state())

    @app.post('/start')
    def start():
        data = request.get_json()
        if type(data.get('epoch')) is not int:
            return jsonify(error='Refresh the page.'), 400
        if controller.cfg.drive and data.get('ready') is not True:
            return jsonify(error='Confirm the floor setup before starting.'), 400
        try:
            run = controller.start(data['owner'], data['epoch'])
            return jsonify(run=run, epoch=controller.state()['epoch'])
        except Halt as error:
            return jsonify(error=str(error)), 409

    @app.post('/heartbeat')
    def heartbeat():
        data = request.get_json()
        try:
            controller.heartbeat(data['owner'], data.get('run'))
            return jsonify(ok=True)
        except Halt as error:
            return jsonify(error=str(error)), 409

    @app.post('/stop')
    def stop():
        controller.stop()
        return jsonify(ok=True, epoch=controller.state()['epoch'])
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--drive', action='store_true', help='Enable bounded physical forward steps (default: no movement).')
    parser.add_argument('--camera', default='http://10.143.244.58')
    parser.add_argument('--control-script', default=str(Path.home()/'robot_web_distance.py'))
    parser.add_argument('--motor-port', default=os.environ.get('ROBOT_PORT','/dev/ttyUSB0'))
    parser.add_argument('--port', type=int, default=5002)
    args = parser.parse_args()
    if not re.fullmatch(r'http://(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?', args.camera):
        parser.error('--camera must be the camera HTTP IP address, without /capture.')
    reader = make_reader(args.control_script)
    motor, controller = Motor(args.motor_port), None
    def terminate(signum, frame):
        raise SystemExit('Shutdown requested.')
    signal.signal(signal.SIGTERM, terminate)
    try:
        motor.open()
        reader.start()
        controller = Controller(motor, reader, Inspector(args.camera), Settings(drive=args.drive),
                                output=Path.home()/'robot_auto_runs')
        app = create_app(controller)
        print('Open http://<current Pi IP>:'+str(args.port), flush=True)
        print('DRIVE MODE: one supervised floor cycle.' if args.drive else 'STATIONARY TEST: no forward commands will be sent.', flush=True)
        app.run(host='0.0.0.0', port=args.port, debug=False, use_reloader=False, threaded=True)
    finally:
        if controller:
            controller.close()
        try:
            motor.close()
        finally:
            reader.close()


if __name__ == '__main__':
    main()
