# BG Spotter

AI-driven AAF guide-track generator for post-production sound. Ingests a picture-locked film and outputs an AAF containing guide tracks (Backgrounds and Footsteps) for sound effects work.

## Setup on a new machine

1. **SSH access**: generate/add an SSH key for the new machine to GitHub, then clone:
   ```
   git clone git@github.com:rxbxt/bg-spotter.git
   ```

2. **Python 3.11+**, then from the repo root:
   ```
   pip install -e ".[dev]"
   ```
   This installs pyaaf2, scenedetect, ultralytics, PySide6, the ollama client, and pytest.

3. **YOLO model**: `yolo11n-pose.pt` is committed to the repo, so nothing extra needed.

4. **Ollama**: install the Ollama app/CLI separately (it's not a pip package) and make sure it's running on `localhost:11434` (configured in `src/bg_spotter/config.py`).

5. **VLM model**: the GUI's "VLM model" dropdown lists whatever vision-capable models are installed via `ollama list`. If you use the VLM walker-counting step, `ollama pull` a vision model (e.g. `llava` or `qwen2.5vl`).

6. **Test video**: source video files are not committed to the repo (too large for GitHub). Copy any test footage over separately.

## Running

```
bg-spotter
```

## Tests

```
pytest
```
