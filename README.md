# modal-comfyui

Run ComfyUI on Modal.com with auto-scaling, GPU snapshots, and easy model management.

Good for testing wan2.2 or other video generation models.

## Prerequisites

- A Modal account
- Python installed
- `uv` installed

## Installation

1. Clone this repository.
2. Install the Modal client:
   ```bash
   uv sync
   ```
3. Set up your modal account (if not done already):
   ```bash
   modal setup
   ```

## Configuration

### Models

Copy `models.example.py` to `models.py` and edit it to manage your models. You can specify:
- Hugging Face models(`models`) using `repo_id` and `filename`. Set your `HF_TOKEN` in `Secrets` for a faster download speed.
- External models(`models_ext`, e.g. civitai) using a direct `url`.

Models are downloaded to volumes and symlinked to the specified `model_dir`.

`model_dir` accepts two styles:
- **Relative path** (recommended for standard ComfyUI folders): resolved under `/root/comfy/ComfyUI/models/`. e.g. `"checkpoints"` → `/root/comfy/ComfyUI/models/checkpoints`.
- **Absolute path**: used as-is. Use this when the target lives outside `ComfyUI/models/` (e.g. a custom node's own model directory).

See `models.example.py` for reference.

### Plugins and Custom Nodes

Copy `plugins.example.py` to `plugins.py` and edit it to add custom node IDs or titles to be installed via `comfy-cli`.
- **Workflow Dependencies**: If you have a `workflow_api.json` in the root directory, the setup will automatically install the necessary custom nodes for that workflow.

### In case of Insufficient Custom Node

Open ComfyUI manager on comfyui and click "Used in Workflow" to see which custom nodes are used in the workflow.

Add these custom nodes to `plugins.py`(be careful of node id). You can find the node id at https://registry.comfy.org/

## Usage

### Serve (Development)

Run the following command to start ComfyUI in development mode:
```bash
modal serve comfyui.py
```
This will provide a temporary URL where you can access the ComfyUI interface.

### Deploy (Production)

To deploy ComfyUI as a persistent app using the default L4 GPU:
```bash
modal deploy comfyui.py
```
Or deploy with cleared `shared_dict` (ie. when the App forcefully stopped):
```bash
python comfyui.py
```
Or change the GPU with:
```bash
MODAL_GPU=RTX-PRO-6000 modal deploy comfyui.py
```
You can find the GPU types available on modal.com at https://modal.com/docs/guide/gpu

Other Environment Variables you can use are:
```
MODAL_MAXTIME=3600
MODAL_IDLETIME=60
MODAL_WAITTIME=20
MODAL_MAXSTARTTIME=300
MODAL_JOBSCUTOFFTIME=86400
```
You can access ComfyUI from the provided URL when successfully deployed.

## Features

- **Auto-scaling**: Scales down to zero when not in use to save costs (modal's serverless can also auto-scales vertically, where CPU cores and RAM size can grow automatically as needed).
- **GPU Snapshots**: Fast startup times using Modal's GPU snapshots (cold-start can be under 3 seconds).
- **Model Caching**: Uses Modal Volumes to cache models across runs (modal's persistent volume is free for the first 1 TiB).
- **Custom Node Management**: Integrated with `comfy-cli` for easy plugin installation.
- **Mixed CPU and GPU instance**: Works on your workflows using CPU-only instance for cheaper rates, but runs workflows on GPU instance seamlessly. Also have persistent completed jobs across sessions with their output assets accessible from Media Assets panel.

## Contributing

Please feel free to contribute to make this project better.
Performance improvements/optimizations are very welcome.
