"""Local robot controls for the existing 300 ms ESP32 motor firmware."""
import os
import secrets
import threading
import time
import serial
from flask import Flask, request, render_template_string

CAMERA = 'http://10.211.43.58'
PORT = os.environ.get('ROBOT_PORT', '/dev/ttyUSB0')
app = Flask(__name__)
token = secrets.token_urlsafe(32)
lock = threading.Lock()
motor = None
last_sequence = {}
PAGE = '''<!doctype html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Robot control</title><style>
body{font-family:Arial;text-align:center;background:#eef2f6;margin:20px}
main{max-width:640px;margin:auto}img{width:100%;min-height:180px;background:#ddd}
.controls{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:20px 0}
button{padding:22px 5px;font-size:18px;border:0;border-radius:12px;background:#1260b5;color:white;touch-action:none;user-select:none;-webkit-user-select:none}
.stop{background:#b71c1c}p{line-height:1.5}
</style></head><body><main><h1>Robot control</h1>
<img id="camera" alt="Camera snapshots"><p id="cameraStatus">Connecting to camera...</p>
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
</script></main></body></html>'''

@app.get('/')
def home():
    client = secrets.token_urlsafe(16)
    with lock:
        if len(last_sequence) >= 100:
            return 'Restart the app to open more control sessions.', 503
        last_sequence[client] = 0
    return render_template_string(PAGE, camera=CAMERA, token=token, client=client), 200, {'Cache-Control':'no-store'}

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
        print('Motor connected. Open http://10.211.43.45:5000 on the same Wi-Fi.', flush=True)
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False, threaded=True)
    finally:
        if motor.is_open:
            try:
                motor.write(b's')
            except (serial.SerialException, OSError):
                pass
            motor.close()

if __name__ == '__main__':
    main()
