"""Local robot controls plus an HC-SR04 distance display.

Pi 4: TRIG = BCM23 / physical 16; divided ECHO = BCM24 / physical 18.
Keep the existing ECHO voltage divider. Distance is informational only:
it does not change motor commands or implement automatic obstacle stopping.
Run with /usr/bin/python3 robot_web_distance.py after stopping the old app.
"""
import os
import secrets
import threading
import time
from queue import Queue, Empty, Full
import serial
from flask import Flask, request, render_template_string, jsonify


class DistanceReader:
    """One GPIO owner and worker; HTTP requests only read its latest result."""

    TRIG = 23
    ECHO = 24
    TIMEOUT = 0.1
    INTERVAL = 0.5
    STALE_AFTER = 2.0

    def __init__(self):
        self._state_lock = threading.Lock()
        self._stop = threading.Event()
        self._overflow = threading.Event()
        self._events = Queue(maxsize=64)
        self._thread = None
        self._state = (None, 'Starting sensor...', None)

    def _publish(self, distance, message):
        with self._state_lock:
            self._state = (distance, message, time.monotonic())

    def snapshot(self):
        with self._state_lock:
            distance, message, updated = self._state
        age = None if updated is None else time.monotonic() - updated
        if distance is not None and age > self.STALE_AFTER:
            distance, message = None, 'Sensor reading expired. Restart the app.'
        return {
            'ok': distance is not None,
            'distance_cm': distance,
            'message': message,
            'age_ms': None if age is None else round(age * 1000),
        }

    def start(self):
        if self._thread is not None:
            raise RuntimeError('Distance reader already started.')
        self._thread = threading.Thread(
            target=self._run, name='distance-reader', daemon=True)
        self._thread.start()

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._publish(None, 'Sensor stopped.')

    def _edge(self, chip, gpio, level, tick):
        if level in (0, 1) and not self._stop.is_set():
            try:
                self._events.put_nowait((level, tick))
            except Full:
                self._overflow.set()

    def _measure(self, gpio, handle):
        gpio.gpio_write(handle, self.TRIG, 0)
        time.sleep(0.002)
        if gpio.gpio_read(handle, self.ECHO):
            return None, 'ECHO high before trigger. Check sensor wiring.'
        while True:
            try:
                self._events.get_nowait()
            except Empty:
                break
        self._overflow.clear()

        # Linux GPIO event ticks and monotonic_ns use CLOCK_MONOTONIC.
        # Exclude callbacks from an older trigger that arrived late.
        trigger_tick = time.monotonic_ns()
        gpio.gpio_write(handle, self.TRIG, 1)
        try:
            time.sleep(0.00001)
        finally:
            gpio.gpio_write(handle, self.TRIG, 0)

        rising_tick = None
        deadline = time.monotonic() + self.TIMEOUT
        while not self._stop.is_set():
            if self._overflow.is_set():
                return None, 'Too many ECHO edges. Check connections.'
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                level, tick = self._events.get(timeout=remaining)
            except Empty:
                break
            if tick < trigger_tick:
                continue
            if level == 1 and rising_tick is None:
                rising_tick = tick
            elif level == 0 and rising_tick is not None:
                if self._overflow.is_set():
                    return None, 'Too many ECHO edges. Check connections.'
                distance = (tick - rising_tick) / 1_000_000_000 * 17150
                if not 2 <= distance <= 400:
                    return None, 'Echo outside the 2-400 cm range.'
                return round(distance, 1), 'Live distance'
        if rising_tick is None:
            return None, 'No echo. Check target, power and wiring.'
        return None, 'ECHO timeout. Check target and wiring.'

    def _run(self):
        gpio = None
        handle = None
        callback = None
        trig_ready = False
        try:
            import lgpio as gpio
            handle = gpio.gpiochip_open(0)  # Raspberry Pi 4
            gpio.gpio_claim_output(handle, self.TRIG)
            trig_ready = True
            gpio.gpio_write(handle, self.TRIG, 0)
            gpio.gpio_claim_alert(
                handle, self.ECHO, gpio.BOTH_EDGES, gpio.SET_PULL_DOWN)
            callback = gpio.callback(handle, self.ECHO, gpio.BOTH_EDGES, self._edge)
            if self._stop.wait(1):
                return
            while not self._stop.is_set():
                self._publish(*self._measure(gpio, handle))
                if self._stop.wait(self.INTERVAL):
                    break
        except Exception as error:
            print(f'Distance sensor error: {error}', flush=True)
            self._publish(None, 'Sensor unavailable. Check the Pi terminal.')
        finally:
            # Attempt each cleanup even if another cleanup operation fails.
            cleanup = []
            if trig_ready:
                cleanup.append(lambda: gpio.gpio_write(handle, self.TRIG, 0))
            if callback is not None:
                cleanup.append(callback.cancel)
            if handle is not None:
                cleanup.append(lambda: gpio.gpiochip_close(handle))
            for action in cleanup:
                try:
                    action()
                except Exception as error:
                    print(f'Sensor cleanup: {error}', flush=True)

CAMERA = 'http://10.211.43.58'
PORT = os.environ.get('ROBOT_PORT', '/dev/ttyUSB0')
app = Flask(__name__)
token = secrets.token_urlsafe(32)
lock = threading.Lock()
motor = None
last_sequence = {}
distance_reader = DistanceReader()
PAGE = '''<!doctype html><html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Robot control</title><style>
body{font-family:Arial;text-align:center;background:#eef2f6;margin:20px}
main{max-width:640px;margin:auto}img{width:100%;min-height:180px;background:#ddd}
.controls{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:20px 0}
button{padding:22px 5px;font-size:18px;border:0;border-radius:12px;background:#1260b5;color:white;touch-action:none;user-select:none;-webkit-user-select:none}
.stop{background:#b71c1c}p{line-height:1.5}
.distance{background:white;border-radius:12px;padding:16px;margin:18px 0}
.distance h2{font-size:18px;margin:0 0 8px}.distance output{font-size:36px;font-weight:bold;color:#1260b5}
.distance p{margin:8px 0 0}.distance small{display:block;margin-top:8px;color:#555}
</style></head><body><main><h1>Robot control</h1>
<img id="camera" alt="Camera snapshots"><p id="cameraStatus">Connecting to camera...</p>
<section class="distance" aria-labelledby="distanceTitle">
<h2 id="distanceTitle">Front distance</h2>
<output id="distanceValue">-- cm</output>
<p id="distanceStatus" role="status">Connecting to sensor...</p>
<small>Distance display only. Stop the robot manually.</small></section>
<div class="controls"><span></span><button data-direction="f">Forward</button><span></span>
<button data-direction="l">Left</button><button class="stop" onclick="stopMotion()">STOP</button><button data-direction="r">Right</button>
<span></span><button data-direction="v">Backward</button><span></span></div>
<p>Hold a direction to move. Release to stop.</p><p id="status">Ready</p>
<a href="{{camera}}" target="_blank" rel="noopener">Open camera page</a>
<script>
const key={{token|tojson}}, cameraURL={{camera|tojson}};
const picture=document.getElementById('camera'), cs=document.getElementById('cameraStatus');
function refresh(){picture.src=cameraURL+'/capture?t='+Date.now()}
picture.onload=()=>{cs.textContent='Camera connected';setTimeout(refresh,500)};
picture.onerror=()=>{cs.textContent='Camera unavailable: check its power and Wi-Fi';setTimeout(refresh,2000)};
refresh();
const client={{client|tojson}};
let sequence=0, held=null, generation=0, timer=null;
const status=document.getElementById('status');
async function transmit(command){
 const response=await fetch('/move/'+command,{method:'POST',
 headers:{'X-Robot-Key':key,'Content-Type':'application/json'},
 body:JSON.stringify({client,sequence:++sequence}),
 signal:AbortSignal.timeout(800),keepalive:command==='s'});
 if(!response.ok)throw new Error(await response.text());
}
function stopMotion(message='Stopped'){
 held=null;generation++;clearTimeout(timer);
 status.textContent=message;
 transmit('s').catch(()=>{status.textContent='Connection lost. Automatic motor timeout remains active.'});
}
async function heartbeat(myGeneration){
 if(!held || generation!==myGeneration)return;
 try{await transmit(held.command)}
 catch(error){if(generation===myGeneration)stopMotion('Connection lost — release and try again.');return}
 if(held && generation===myGeneration)timer=setTimeout(()=>heartbeat(myGeneration),80);
}
for(const button of document.querySelectorAll('[data-direction]')){
 button.addEventListener('contextmenu',e=>e.preventDefault());
 button.addEventListener('pointerdown',e=>{
  if(held || (e.pointerType==='mouse' && e.button!==0))return;
  e.preventDefault();button.setPointerCapture(e.pointerId);
  held={command:button.dataset.direction,pointer:e.pointerId};
  status.textContent='Moving — release to stop';heartbeat(++generation);
 });
 for(const event of ['pointerup','pointercancel','lostpointercapture'])
  button.addEventListener(event,e=>{if(held && held.pointer===e.pointerId)stopMotion()});
}
window.addEventListener('blur',()=>{if(held)stopMotion()});
window.addEventListener('pagehide',()=>stopMotion());
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopMotion()});
document.addEventListener('keydown',e=>{if(e.code==='Space'||e.code==='Escape'){e.preventDefault();stopMotion()}});

const distanceValue=document.getElementById('distanceValue');
const distanceStatus=document.getElementById('distanceStatus');
let distanceFreshUntil=0;
function clearDistance(message){
 distanceFreshUntil=0;
 distanceValue.textContent='-- cm';
 distanceStatus.textContent=message;
}
async function updateDistance(){
 if(document.hidden){setTimeout(updateDistance,500);return}
 const started=performance.now();
 try{
  const response=await fetch('/distance',{cache:'no-store',signal:AbortSignal.timeout(1200)});
  if(!response.ok)throw new Error('Distance request failed');
  const data=await response.json();
  const now=performance.now();
  const remaining=2000-data.age_ms-(now-started);
  if(document.hidden){clearDistance('Refreshing distance...')}
  else if(data.ok && Number.isFinite(data.distance_cm) && Number.isFinite(data.age_ms) && remaining>0){
   distanceFreshUntil=now+remaining;
   distanceValue.textContent=data.distance_cm.toFixed(1)+' cm';
   distanceStatus.textContent='Live distance';
  }else{
   clearDistance(data.ok ? 'Reading expired. Waiting for sensor...' : data.message || 'No sensor reading.');
  }
 }catch(error){clearDistance('Distance unavailable. Check the Pi connection.')}
 finally{setTimeout(updateDistance,500)}
}
setInterval(()=>{
 if(distanceFreshUntil && performance.now()>=distanceFreshUntil)
  clearDistance('Reading expired. Waiting for sensor...');
},250);
document.addEventListener('visibilitychange',()=>clearDistance('Refreshing distance...'));
updateDistance();
</script></main></body></html>'''

@app.get('/')
def home():
    client = secrets.token_urlsafe(16)
    with lock:
        if len(last_sequence) >= 100:
            return 'Restart the app to open more control sessions.', 503
        last_sequence[client] = 0
    return render_template_string(PAGE, camera=CAMERA, token=token, client=client), 200, {'Cache-Control':'no-store'}

@app.get('/distance')
def distance():
    return jsonify(distance_reader.snapshot()), 200, {'Cache-Control': 'no-store'}

@app.post('/move/<command>')
def move(command):
    if not secrets.compare_digest(request.headers.get('X-Robot-Key', ''), token):
        return 'Reload the control page.', 403
    if command not in ('f', 'v', 'l', 'r', 's'):
        return 'Unknown command.', 400
    data = request.get_json(silent=True) or {}
    client, sequence = data.get('client'), data.get('sequence')
    if not isinstance(client, str) or type(sequence) is not int:
        return 'Invalid control request.', 400
    with lock:
        if client not in last_sequence:
            return 'Reload the page.', 403
        if sequence <= last_sequence[client]:
            return 'Older command ignored.', 200
        last_sequence[client] = sequence
        try:
            motor.reset_input_buffer()
            motor.write(command.encode('ascii'))
        except (serial.SerialException, OSError):
            return 'Motor USB disconnected. Stop the app and reconnect it.', 503
    return 'Stop command sent.' if command == 's' else 'Movement heartbeat sent.'

def main():
    global motor
    motor = serial.Serial(baudrate=115200, timeout=0.2, write_timeout=0.5, exclusive=True)
    motor.dtr = False
    motor.rts = False
    motor.port = PORT
    try:
        motor.open()
        time.sleep(2)
        motor.reset_input_buffer()
        motor.write(b's')
        deadline = time.monotonic() + 3
        found = False
        while time.monotonic() < deadline:
            if motor.readline().strip() == b'STOP':
                found = True
                break
        if not found:
            raise RuntimeError('Motor firmware did not reply STOP. Check the motor ESP32 USB port and close miniterm.')
        distance_reader.start()
        print('Motor connected. Open http://10.211.43.45:5000 on the same Wi-Fi.', flush=True)
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False, threaded=True)
    finally:
        try:
            with lock:
                if motor.is_open:
                    try:
                        motor.write(b's')
                    except (serial.SerialException, OSError):
                        pass
                    motor.close()
        finally:
            distance_reader.close()

if __name__ == '__main__':
    main()
