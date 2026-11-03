#!/usr/bin/env python3
"""Camera crack-inspection demo for Sai's Raspberry Pi.

Run: ~/robot-ai/bin/python ~/crack_inspector.py
Open: http://<Pi IP>:5001
Requires: OpenCV, numpy, Flask and onnxruntime; no motor/serial access.

Model: beaunix/smart-crack-vision (YOLOv8n-seg, single crack class)
https://huggingface.co/beaunix/smart-crack-vision
Revision: 9442007ef9c1003880baa5796d253608691b37c4
The separately downloaded model is licensed AGPL-3.0 by its publisher.
Output decoding follows YOLOv8's documented box/prototype-mask format.
https://docs.ultralytics.com/reference/utils/ops/

This demo marks suspected visible cracks. It does not measure crack width,
classify structural severity, or certify a surface as safe.
"""
import os

# Limit CPU contention with the existing motor-control web application.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "2")

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
import uuid

import cv2
import numpy as np
import onnxruntime as ort
from flask import Flask, jsonify, render_template_string, request, send_file

MODEL_SHA256 = "4b789658646d790079d3e78d9d3ed475030d740a4b8412aff52248189a114cbd"
MODEL_SOURCE = "https://huggingface.co/beaunix/smart-crack-vision"
cv2.setNumThreads(1)


class CrackDetector:
    def __init__(self, model_path):
        path = Path(model_path).expanduser()
        if not path.is_file():
            raise RuntimeError("Model missing: " + str(path))
        if hashlib.sha256(path.read_bytes()).hexdigest() != MODEL_SHA256:
            raise RuntimeError("Model file differs from the checked download. Download crack_model.onnx again.")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.session = ort.InferenceSession(str(path), sess_options=options,
                                            providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        if self.session.get_inputs()[0].shape != [1, 3, 640, 640]:
            raise RuntimeError("Unexpected model input shape.")

    @staticmethod
    def preprocess(image):
        height, width = image.shape[:2]
        ratio = min(640 / width, 640 / height)
        rw, rh = round(width * ratio), round(height * ratio)
        left, top = (640 - rw) // 2, (640 - rh) // 2
        canvas = np.full((640, 640, 3), 114, dtype=np.uint8)
        canvas[top:top + rh, left:left + rw] = cv2.resize(image, (rw, rh))
        rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
        tensor = np.ascontiguousarray(rgb.transpose(2, 0, 1)[None], dtype=np.float32) / 255.0
        return tensor, (ratio, left, top, rw, rh)

    @staticmethod
    def decode(outputs, image, transform, threshold):
        """Decode class scores, suppress duplicate boxes and reconstruct masks."""
        predictions = next((x for x in outputs if x.shape == (1, 37, 8400)), None)
        prototypes = next((x for x in outputs if x.shape == (1, 32, 160, 160)), None)
        if predictions is None or prototypes is None:
            raise RuntimeError("Unexpected model output shapes: " + str([x.shape for x in outputs]))
        if not all(np.isfinite(x).all() for x in outputs):
            raise RuntimeError("The model returned invalid numbers.")
        height, width = image.shape[:2]
        ratio, left, top, rw, rh = transform
        rows = predictions[0].T
        rows = rows[(rows[:, 4] >= threshold) & (rows[:, 2] > 0) & (rows[:, 3] > 0)]
        # Bound work on noisy images; this is not a physical crack count.
        rows = rows[np.argsort(-rows[:, 4])[:300]]
        marked = image.copy()
        if not len(rows):
            return marked, [], np.zeros((height, width), dtype=np.uint8)
        nms_boxes = np.column_stack((rows[:, 0] - rows[:, 2] / 2,
                                     rows[:, 1] - rows[:, 3] / 2, rows[:, 2:4]))
        indices = cv2.dnn.NMSBoxes(nms_boxes.tolist(), rows[:, 4].tolist(),
                                    threshold, 0.45)
        indices = np.asarray(indices, dtype=int).reshape(-1)[:20]
        detections = []
        combined = np.zeros((height, width), dtype=bool)
        proto = prototypes[0].reshape(32, -1)
        for index in indices:
            row = rows[index]
            x1 = float(np.clip((row[0] - row[2] / 2 - left) / ratio, 0, width))
            y1 = float(np.clip((row[1] - row[3] / 2 - top) / ratio, 0, height))
            x2 = float(np.clip((row[0] + row[2] / 2 - left) / ratio, 0, width))
            y2 = float(np.clip((row[1] + row[3] / 2 - top) / ratio, 0, height))
            if x2 <= x1 or y2 <= y1:
                continue
            logits = (row[5:] @ proto).reshape(160, 160)
            # Undo the exact padding used above before resizing to the camera frame.
            mask_canvas = cv2.resize(logits, (640, 640), interpolation=cv2.INTER_LINEAR)
            logits_image = cv2.resize(mask_canvas[top:top + rh, left:left + rw],
                                      (width, height), interpolation=cv2.INTER_LINEAR)
            mask = logits_image > 0  # sigmoid(logit) > 0.5
            yy, xx = np.ogrid[:height, :width]
            mask &= (xx >= x1) & (xx < x2) & (yy >= y1) & (yy < y2)
            combined |= mask
            detections.append({"box_xyxy_pixels": [round(v, 1) for v in (x1, y1, x2, y2)],
                               "model_score": round(float(row[4]), 4),
                               "mask_pixels": int(mask.sum())})
        marked[combined] = (0.55 * marked[combined] + 0.45 * np.array([0, 0, 255])).astype(np.uint8)
        for number, detection in enumerate(detections, 1):
            x1, y1, x2, y2 = [int(v) for v in detection["box_xyxy_pixels"]]
            cv2.rectangle(marked, (x1, y1), (min(x2, width - 1), min(y2, height - 1)), (0, 200, 255), 2)
            label = "Suspected crack %d | score %.2f" % (number, detection["model_score"])
            cv2.putText(marked, label, (max(0, x1), max(18, y1 - 7)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(marked, label, (max(0, x1), max(18, y1 - 7)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 220, 255), 1, cv2.LINE_AA)
        return marked, detections, combined.astype(np.uint8) * 255

    def analyse(self, image, threshold=0.35):
        tensor, transform = self.preprocess(image)
        started = time.perf_counter()
        outputs = self.session.run(None, {self.input_name: tensor})
        marked, detections, mask = self.decode(outputs, image, transform, threshold)
        return marked, detections, mask, round(time.perf_counter() - started, 2)


def fetch_camera(url):
    separator = "&" if "?" in url else "?"
    req = Request(url + separator + "t=" + str(time.time_ns()), headers={"Cache-Control": "no-cache"})
    with urlopen(req, timeout=12) as response:
        data = response.read(5_000_001)
    if len(data) > 5_000_000:
        raise RuntimeError("Camera image was unexpectedly large.")
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("The camera returned no readable image. Check its /capture address.")
    if max(image.shape[:2]) > 4096:
        raise RuntimeError("Camera resolution is too large for this demo.")
    return image


PAGE = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Robot crack inspection</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#eef3f7;color:#182c3d;font:17px system-ui,sans-serif}
main{max-width:1100px;margin:auto;padding:24px}h1{font-size:30px;margin-bottom:8px}
.card{background:white;padding:22px;border-radius:16px;margin:20px 0;box-shadow:0 3px 16px #193a5010}
button{background:#125fa9;color:white;border:0;border-radius:10px;padding:16px 24px;font:inherit;font-weight:650;cursor:pointer}
button:disabled{opacity:.6;cursor:wait}select{font:inherit;padding:10px;margin:10px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.grid img{width:100%;height:auto;border-radius:9px}
figure{margin:0}figcaption{font-weight:650;margin:10px 0}a{color:#125fa9}small{display:block;line-height:1.6;color:#4c6171}
#status{min-height:28px;font-weight:600;white-space:pre-wrap}.links{display:flex;gap:22px;flex-wrap:wrap;margin-top:18px}
[hidden]{display:none!important}@media(max-width:700px){.grid{grid-template-columns:1fr}main{padding:14px}h1{font-size:26px}}
</style><main>
<h1>Robot crack inspection</h1>
<p>Keep the robot still and point the camera at a well-lit wall. Each scan takes one new photograph.</p>
<div class="card"><label for="threshold">Detection threshold</label>
<select id="threshold"><option value="0.25">0.25 — more candidates</option><option value="0.35" selected>0.35 — starting setting</option><option value="0.50">0.50 — fewer candidates</option></select>
<p><button id="scan">Capture &amp; analyse</button></p><p id="status" role="status" aria-live="polite">Ready for a camera test.</p>
<small>Yellow boxes mark suspected crack regions; red shading marks predicted crack pixels. Model scores are not calibrated probabilities. Shadows, joints and markings can be mistaken for cracks.</small></div>
<section id="result" class="card" hidden><p id="details"></p><div class="grid">
<figure><figcaption>Original photograph</figcaption><img id="original" alt="Original camera photograph"></figure>
<figure><figcaption>Model result</figcaption><img id="marked" alt="Camera photograph with suspected cracks marked"></figure>
</div><div class="links"><a id="download" download>Download marked image</a><a id="report" download>Download scan data</a></div></section>
<small>Demonstration only. A missed detection does not establish that a surface is safe. Confirm findings visually; structural assessment requires qualified inspection.</small>
<p><a id="controls">Open robot controls</a> · <a href="https://huggingface.co/beaunix/smart-crack-vision" target="_blank" rel="noopener">Model and attribution</a> · <a href="/source">Script source</a></p>
<script>
const token={{ token|tojson }};
const button=document.getElementById('scan'), status=document.getElementById('status'), result=document.getElementById('result');
const controls=new URL(location.href);controls.port='5000';controls.pathname='/';controls.search='';document.getElementById('controls').href=controls.href;
button.addEventListener('click',async()=>{
 button.disabled=true;result.hidden=true;status.textContent='Capturing and analysing. Please keep the camera still…';
 const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),90000);
 try{
  const response=await fetch('/scan',{method:'POST',headers:{'Content-Type':'application/json','X-Scan-Key':token},
   body:JSON.stringify({threshold:Number(document.getElementById('threshold').value)}),signal:controller.signal});
  const data=await response.json();if(!response.ok)throw new Error(data.error||'Scan failed.');
  status.textContent=data.count ? data.count+' suspected crack region(s). Please check the marked image.' : 'No crack detected above the selected threshold. Review the original image too.';
  document.getElementById('details').textContent='Captured '+new Date(data.captured_at).toLocaleString()+' · analysis '+data.seconds+' s · threshold '+data.threshold;
  document.getElementById('original').src=data.original;document.getElementById('marked').src=data.marked;
  document.getElementById('download').href=data.marked+'?download=1';document.getElementById('report').href=data.report+'?download=1';
  result.hidden=false;
 }catch(error){status.textContent=error.name==='AbortError'?'Scan timed out. Check the Pi terminal before trying again.':'Scan failed: '+error.message;}
 finally{clearTimeout(timeout);button.disabled=false;}
});
</script></main></html>"""


def create_app(detector, camera, output_dir, fetcher=fetch_camera):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 1024
    directory = Path(output_dir).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(24)
    scan_lock = threading.Lock()

    @app.after_request
    def no_cache(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        return response

    @app.get('/')
    def index():
        return render_template_string(PAGE, token=key)

    @app.post('/scan')
    def scan():
        if not secrets.compare_digest(request.headers.get('X-Scan-Key', ''), key):
            return jsonify(error='Reload this page and try again.'), 403
        data = request.get_json(silent=True)
        try:
            threshold = float(data.get('threshold', 0.35)) if isinstance(data, dict) else 0.35
        except (TypeError, ValueError):
            return jsonify(error='Invalid threshold.'), 400
        if not np.isfinite(threshold) or not 0.15 <= threshold <= 0.85:
            return jsonify(error='Threshold must be between 0.15 and 0.85.'), 400
        if not scan_lock.acquire(blocking=False):
            return jsonify(error='A scan is already running. Wait for it to finish.'), 409
        try:
            image = fetcher(camera)
            captured_at = datetime.now(timezone.utc).isoformat()
            marked, detections, mask, seconds = detector.analyse(image, threshold)
            scan_id = uuid.uuid4().hex
            folder = directory / scan_id
            folder.mkdir()
            for name, pixels in [('original.jpg', image), ('marked.jpg', marked), ('mask.png', mask)]:
                if not cv2.imwrite(str(folder / name), pixels):
                    raise OSError('Could not save scan image.')
            report = {'captured_at': captured_at, 'image_size_wh': list(image.shape[1::-1]),
                      'threshold': threshold, 'seconds': seconds, 'regions': detections,
                      'model_source': MODEL_SOURCE, 'model_sha256': MODEL_SHA256,
                      'note': 'Suspected visible cracks only. Scores are not calibrated probabilities; no structural safety assessment.'}
            (folder / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            return jsonify(count=len(detections), captured_at=captured_at, seconds=seconds, threshold=threshold,
                           original='/results/' + scan_id + '/original.jpg',
                           marked='/results/' + scan_id + '/marked.jpg', report='/results/' + scan_id + '/report.json')
        except (URLError, TimeoutError, ConnectionError):
            return jsonify(error='Camera unreachable. Check power, Wi-Fi and the camera address: ' + camera), 502
        except Exception as error:
            app.logger.exception('Scan failed')
            return jsonify(error=str(error)[:240] or 'Scan failed; check the Pi terminal.'), 500
        finally:
            scan_lock.release()

    @app.get('/results/<scan_id>/<filename>')
    def result_file(scan_id, filename):
        if not re.fullmatch(r'[0-9a-f]{32}', scan_id) or filename not in {'original.jpg', 'marked.jpg', 'mask.png', 'report.json'}:
            return jsonify(error='Result not found.'), 404
        path = directory / scan_id / filename
        if not path.is_file():
            return jsonify(error='Result not found.'), 404
        return send_file(path, as_attachment=request.args.get('download') == '1', download_name=scan_id + '_' + filename)

    @app.get('/source')
    def source():
        return send_file(Path(__file__).resolve(), as_attachment=True, download_name='crack_inspector.py')

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default=str(Path.home() / 'crack_model.onnx'))
    parser.add_argument('--camera', default='http://10.211.43.58/capture')
    parser.add_argument('--port', type=int, default=5001)
    parser.add_argument('--output', default=str(Path.home() / 'crack_results'))
    args = parser.parse_args()
    print('Loading the crack model...', flush=True)
    detector = CrackDetector(args.model)
    app = create_app(detector, args.camera, args.output)
    print('READY — open http://<Pi IP>:' + str(args.port), flush=True)
    print('Scans are saved in ' + str(Path(args.output).expanduser()), flush=True)
    app.run(host='0.0.0.0', port=args.port, debug=False, use_reloader=False, threaded=True)


if __name__ == '__main__':
    main()
