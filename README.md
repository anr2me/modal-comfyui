# modal-comfyui

Run ComfyUI on Modal.com with auto-scaling, GPU snapshots, and easy model management.

Good for testing wan2.2 or other video generation models.

## Prerequisites

- A [Modal](https://modal.com/) account
- Python installed
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) installed

## Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/anr2me/modal-comfyui.git
   cd modal-comfyui
   ```
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
- Hugging Face models(`models`) using `repo_id` and `filename`. Set your `HF_TOKEN` in `huggingface-secret` Secrets for a faster download speed and gated models.
- External models(`models_ext`, e.g. civitai) using a direct `url`. You can also set your `CIVITAI_TOKEN` in `custom-secret` Secrets to download gated models.

Models are downloaded to persistent volumes and symlinked to the specified `model_dir`.

`model_dir` accepts two styles:
- **Relative path** (recommended for standard ComfyUI folders): resolved under `/root/comfy/ComfyUI/models/`. e.g. `"checkpoints"` → `/root/comfy/ComfyUI/models/checkpoints`.
- **Absolute path**: used as-is. Use this when the target lives outside `ComfyUI/models/` (e.g. a custom node's own model directory).

See `models.example.py` for reference.

### Plugins and Custom Nodes

Copy `plugins.example.py` to `plugins.py` and edit it to add custom node IDs or titles to be installed via `comfy-cli`.
- **Workflow Dependencies**: If you have a `workflow_api.json` in the root directory, the setup will automatically install the necessary custom nodes for that workflow.

### In case of Insufficient Custom Node

Open ComfyUI manager on comfyui and click "Used in Workflow" to see which custom nodes are used in the workflow.  
_*Note: We are using Legacy ComfyUI Manager._

- Add these custom nodes to `comfy_plugins` in `plugins.py`(be careful of node id). You can find the node id at https://registry.comfy.org/
- You can also install custom nodes repository using `git` url. Add the url, branch, and their dependencies to `comfy_plugins_ext` in `plugins.py` (be careful of dependency conflicts).

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
Or rebuild the image and deploy (ie. after removing models at persistent volume to redownload them):
```bash
MODAL_FORCE_BUILD=1 modal deploy comfyui.py
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
```bash
COMFY_VER="nightly"
COMFYGPU_ARGS="--use-flash-attention --preview-method auto --front-end-version Comfy-Org/ComfyUI_frontend@1.45.21"
COMFYMIX_ARGS="--preview-method auto --front-end-version Comfy-Org/ComfyUI_frontend@1.45.21"
JOBS_CUTOFFTIME=172800
MODAL_MAXTIME=3600
MODAL_IDLETIME=38
MODAL_WAITTIME=20
MODAL_MAXSTARTTIME=300
```
You can access ComfyUI from the provided persistent URL when successfully deployed.

## Modal Commands

Reference for the Modal CLI commands you'll use most with this project. The app is registered as `modal-comfyui` and its Modal Volume is `hf-hub-cache`.

### Apps

```bash
modal app list                           # list all your apps and their state
modal app history modal-comfyui          # show deployment history (each `modal deploy` is a version)
modal app rollback modal-comfyui <N>     # roll back to version N — creates a new deployment entry
modal app stop modal-comfyui -y          # permanently stop the app and its containers
modal app logs modal-comfyui             # tail live logs from all containers
```

Rollback only touches the app definition + image. It does **not** revert files on the Modal Volume (models, workflows saved via the UI, generated outputs).

### Volumes (models, workflows, outputs)

Everything persistent lives on the `hf-hub-cache` volume:
- `ComfyUI/output/` — generated images and videos
- `ComfyUI/user/` — workflows and settings you save in the browser UI
- `hf-hub/`, `civitai/`, etc. — downloaded model weights (symlinked into ComfyUI at container start)

```bash
modal volume list                                          # show all volumes
modal volume ls hf-hub-cache                               # list top-level contents
modal volume ls hf-hub-cache ComfyUI/output                # browse generated outputs
modal volume get hf-hub-cache ComfyUI/output ./outputs     # download all outputs to your laptop
modal volume get hf-hub-cache ComfyUI/output/vid.mp4 .     # download a single file
modal volume put hf-hub-cache ./input.png ComfyUI/input/   # upload an input image
modal volume rm -r hf-hub-cache ComfyUI/output             # delete a directory on the volume
modal volume delete hf-hub-cache -y                        # wipe the entire volume (forces full re-download on next deploy)
```

### Deploying and rebuilding

```bash
modal serve comfyui.py                                     # dev mode — hot-reload while running, dies on Ctrl-C
modal deploy comfyui.py                                    # production — persistent URL, versioned
MODAL_FORCE_BUILD=1 modal deploy comfyui.py                # force a full image rebuild, ignoring layer cache
python comfyui.py                                          # deploy and clear the in-memory `shared_dict` (use after a hung app)
```

### Account and environment

```bash
modal setup                                                # log in / configure credentials (first-time only)
modal profile current                                      # show which workspace/environment you're using
modal profile list                                         # list configured profiles
```

The Modal dashboard at [modal.com/apps](https://modal.com/apps) mirrors most of these commands with a GUI and also shows real-time GPU/CPU usage, cost, and logs.

## Running MiniMax-H3 (I2V / T2V / R2V)

`models.example.py` includes the five files needed for the three MiniMax-H3 video workflows from [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3).

1. **Use a Blackwell GPU.** The workflows load the NVFP4 text encoder (`qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors`), which only runs on Blackwell — deploy with `MODAL_GPU=RTX-PRO-6000` (or `B200`).
2. **Copy `models.example.py` to `models.py`** and deploy:
   ```bash
   MODAL_GPU=RTX-PRO-6000 modal deploy comfyui.py
   ```
3. **Open the ComfyUI URL, then load a template**: Workflow menu → Browse Templates → search "MiniMax H3" → pick I2V, T2V, or R2V.
4. If nodes render red (missing `MiniMaxH3ImageToVideo` / `MiniMaxH3ReferenceToVideo`), the stable ComfyUI is behind. Redeploy with `COMFY_VER=nightly MODAL_GPU=RTX-PRO-6000 modal deploy comfyui.py`, or use ComfyUI Manager's "Install Missing Custom Nodes" from within the UI.

## Features

- **Auto-scaling**: Scales down to zero when not in use to save costs (modal's serverless can also auto-scales vertically, where CPU cores and RAM size can grow automatically as needed, so you don't need to overprovision them).
- **GPU Snapshots**: Fast startup times using Modal's GPU snapshots (cold-start can be under 3 seconds).
- **Model Caching**: Uses Modal Volumes to cache models across runs (modal's persistent volume is free for the first 1 TiB).
- **Custom Node Management**: Integrated with `comfy-cli` for easy plugin installation.
- **Mixed CPU and GPU instance**: Works on your workflows using CPU-only instance for cheaper rates, but runs workflows on GPU instance seamlessly. Also have persistent completed jobs across sessions with their output assets accessible from Media Assets panel.
- **Pre-installed Wheels**:
  - PyTorch+CUDA 13.0
  - FlashAttention 2.x, 3, and 4
  - SageAttention 2.x and 3
  - llama-cpp-python
  - nunchaku

## Contributing

Please feel free to contribute to make this project better.
Performance improvements/optimizations are very welcome.
