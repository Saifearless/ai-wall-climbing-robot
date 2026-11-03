# Crack detector model

The recovered `pi/crack_inspector.py` expects a separately downloaded file named `crack_model.onnx`. The model binary was not retrieved for this collection and is not included. Copying the Python file alone will not make crack detection run.

The following metadata is recorded in the saved script; the upstream download and current publisher metadata were not reverified during repository preparation:

| Field | Recorded value |
| --- | --- |
| Model source | `https://huggingface.co/beaunix/smart-crack-vision` |
| Revision | `9442007ef9c1003880baa5796d253608691b37c4` |
| Model family | YOLOv8n-seg, one crack class |
| SHA-256 | `4b789658646d790079d3e78d9d3ed475030d740a4b8412aff52248189a114cbd` |
| Input shape | `[1, 3, 640, 640]` |
| Expected output shapes | `[1, 37, 8400]` and `[1, 32, 160, 160]` |
| License noted in source | AGPL-3.0 for the separately downloaded model |

Use the model from the working Pi if it matches this checksum, or obtain the exact compatible artifact from its publisher. The script checks the SHA-256 before opening the inference session. Do not bypass this check to use an arbitrary model, because preprocessing and output decoding are model-specific.

The original source also references Ultralytics' documented box/prototype-mask operations. Verify the upstream license and redistribution conditions before publishing weights. Model weights are excluded by `.gitignore` in this source collection.

The web interface marks suspected visible cracks and saves images, masks and scan metadata. A score is not a calibrated safety assessment; the software does not determine structural severity.
