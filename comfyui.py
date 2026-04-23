from __future__ import annotations

import subprocess
from pathlib import Path

import modal

from models import models, models_ext
from plugins import comfy_plugins, comfy_plugins_ext

root_dir = Path(__file__).parent

COMFYUI_ROOT = Path("/root/comfy/ComfyUI")
COMFY_MODELS_ROOT = Path("/root/comfy/ComfyUI/models")


def get_comfyui_path() -> Path:
    comfyui_path = COMFYUI_ROOT
    try:
        result = subprocess.check_output(["comfy", "which"], text=True)
    
        # 2. Extract path after ":"
        # Example output: "Current workspace: /home/user/comfy/ComfyUI"
        if ":" in result:
            comfyui_path = Path(result.split(":", 1)[1].strip())
            print(f"Extracted Path: {comfyui_path}")
        else:
            print("Path not found in output")
    except FileNotFoundError:
        print("comfy-cli is not installed or not in PATH")
    
    return comfyui_path

def resolve_model_dir(model_dir: str) -> Path:
    """Resolve model_dir: absolute paths are used as-is, relative paths are
    placed under /root/comfy/ComfyUI/models/ (e.g. "checkpoints")."""
    p = Path(model_dir)
    return p if p.is_absolute() else COMFY_MODELS_ROOT / p


def hf_download(
    repo_id: str,
    filename: str,
    model_dir: str = "checkpoints",
):
    import os
    import subprocess

    # Download model from Hugging Face
    from huggingface_hub import hf_hub_download

    model = hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        cache_dir="/cache",
        token=os.environ.get("HF_TOKEN"),
    )

    target_dir = resolve_model_dir(model_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    local_filename = Path(filename).name
    target_path = target_dir / local_filename
    if target_path.exists() or target_path.is_symlink():
        target_path.unlink()
    _ = subprocess.run(
        f"ln -s {model} {target_path}",
        shell=True,
        check=True,
    )
    print(f"Downloaded {repo_id}/{filename} to {target_path}")


def download_external_model(url: str, filename: str, model_dir: str):
    import subprocess

    cache_dir = "/cache"
    Path(cache_dir).mkdir(parents=True, exist_ok=True)

    cached_path = Path(cache_dir) / filename
    if not cached_path.exists():
        print(f"Downloading {filename} from {url}...")
        _ = subprocess.run(
            [
                "aria2c",
                "--console-log-level=error",
                "--summary-interval=0",
                "-x",
                "16",
                "-s",
                "16",
                "-o",
                filename,
                "-d",
                cache_dir,
                url,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    target_dir = resolve_model_dir(model_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename

    # Remove existing file/link if it exists to ensure fresh link
    if target_path.exists() or target_path.is_symlink():
        target_path.unlink()

    # Create symlink
    target_path.symlink_to(cached_path)
    print(f"Linked {filename} to {target_path}")

def download_external_plugin(url: str, branch: str, install: str):
    import subprocess

    _ = subprocess.run(
            [
                "git",
                "clone",
                "--recurse-submodules",
                "--single-branch --branch",
                branch,
                url,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
    )
    # TODO

def download_all():
    for model in models:
        hf_download(model["repo_id"], model["filename"], model["model_dir"])

    for model in models_ext:
        download_external_model(model["url"], model["filename"], model["model_dir"])


vol = modal.Volume.from_name("hf-hub-cache", create_if_missing=True, version=2)

# construct images and install deps/custom nodes
image = (
    modal.Image.debian_slim(python_version="3.13")
    .add_local_python_source("models", "plugins", copy=True)
    .apt_install("git", "git-lfs", "libgl1-mesa-dev", "libglib2.0-0", "aria2")
    .uv_pip_install("pip", "uv")
    .pip_install_from_requirements(str(root_dir / "requirements_comfy.txt"), uv=True)
    .run_commands("comfy set-default /cache/ComfyUI", volumes={"/cache": vol})
    .run_commands("comfy --skip-prompt install --nvidia --cuda-version 13.0", volumes={"/cache": vol})
    .run_commands("git lfs install")
)

# setup base directory
base_dir = "/cache/ComfyUI"
Path(base_dir).mkdir(parents=True, exist_ok=True)
#subprocess.run(['rsync', '-a', '/root/comfy/ComfyUI/', '/cache/ComfyUI/'], volumes={"/cache": vol})
image = image.add_local_file(
        str(Path(__file__).parent / "extra_model_paths.yaml"), 
        "/root/comfy/ComfyUI/extra_model_paths.yaml", 
        copy=True
)
#.run_commands("comfy set-default /cache/ComfyUI", volumes={"/cache": vol})
#.run_commands("comfy --skip-prompt install --nvidia --cuda-version 13.0", volumes={"/cache": vol})
#.run_commands("git lfs install")

# download models
image = image.env({"HF_HUB_ENABLE_HF_TRANSFER": "1"}).run_function(
    download_all, volumes={"/cache": vol}
)


# setup custom nodes
workflow_file_path = Path(__file__).parent / "workflow_api.json"
if workflow_file_path.exists():
    image = image.add_local_file(
        workflow_file_path, "/root/workflow_api.json", copy=True
    ).run_commands("comfy node install-deps --workflow=/root/workflow_api.json", volumes={"/cache": vol})
else:
    print(
        f"Warning: {workflow_file_path} not found. API endpoint might not work without a workflow."
    )

if comfy_plugins:
    image = image.run_commands("comfy node install " + " ".join(comfy_plugins), volumes={"/cache": vol})

if comfy_plugins_ext:
    nodes_dir = str(get_comfyui_path() / "custom_nodes")
    for plugin in comfy_plugins_ext:
        #download_external_plugin(plugin["url"], plugin["branch"], plugin["install"])
        image = image.run_commands(f"pushd {nodes_dir} && git clone --recurse-submodules --single-branch --branch {plugin['branch']} plugin['url'] && popd", volumes={"/cache": vol})
        plugin_install = plugin['install']
        if plugin_install and plugin_install.strip():
            plugin_install = plugin_install.strip()
            # Strips trailing slashes, splits by slash, takes the last part, and removes '.git'
            folder_name = plugin['url'].rstrip('/').rsplit('/', 1)[-1].removesuffix('.git')
            image = image.run_commands(f"pushd {nodes_dir}/{folder_name} && git pull && popd", volumes={"/cache": vol})
            if plugin_install.endswith(".py"):
                image = image.run_commands(f"pushd {nodes_dir}/{folder_name} && python {plugin_install} && popd", volumes={"/cache": vol})
            elif plugin_install.endswith(".toml"):
                image = image.uv_sync(f"{nodes_dir}/{folder_name}/{plugin_install}", volumes={"/cache": vol}) # pip_install_from_pyproject
            else:
                image = image.pip_install_from_requirements(f"{nodes_dir}/{folder_name}/{plugin_install}", volumes={"/cache": vol}, uv=True)
                
# install missing dependencies 
image = image.uv_pip_install("matrix-nio","git+https://github.com/nunchaku-tech/nunchaku")

app = modal.App(name="modal-comfyui", image=image)

uiport = 8188
@app.function(
    max_containers=1,
    gpu="L4",
    volumes={"/cache": vol},
    scaledown_window=60,  # idle 1 minutes to shutdown
    enable_memory_snapshot=True,
    experimental_options={"enable_gpu_snapshot": True},
)
@modal.concurrent(max_inputs=10)
@modal.web_server(uiport, startup_timeout=60)
def comfyui():
    _ = subprocess.Popen(
        f"comfy launch --background -- --listen 0.0.0.0 --port {uiport} --base-directory {base_dir}", shell=True
    )
