from __future__ import annotations

import os
import subprocess
from pathlib import Path

import modal

# This runs on both locally and on container
GPU_MODEL = os.getenv("MODAL_GPU", "L4")
GPU_NAME = GPU_MODEL.split(':')[0]
GPU_COUNT = int(GPU_MODEL.split(":")[1]) if ":" in GPU_MODEL else 1
COMFYGPUARGS = os.getenv("MODAL_COMFYGPUARGS", "") # additional ComfyUI arguments on GPU instance
MAXTIME = int(os.getenv("MODAL_MAXTIME", "3600")) # stream & websocket max lifetime before forcefully terminated, will also affects startup time when lower than MAXSTARTTIME.
IDLETIME = int(os.getenv("MODAL_IDLETIME", "60")) # spin down on idle timeout
WAITTIME = int(os.getenv("MODAL_WAITTIME", "20")) # wait time to finished progressbar animation when inference is done (ie. VHS save video node)
MAXSTARTTIME = int(os.getenv("MODAL_MAXSTARTTIME", "300")) # ComfyUI & it's custom nodes initialization/startup timeout
JOBSCUTOFFTIME = int(os.getenv("MODAL_JOBSCUTOFFTIME", "86400")) # completed jobs history cutoff (ie. only shows jobs from the last 24 hours)

def update_vars_from_env():
    global GPU_MODEL
    global GPU_NAME
    global GPU_COUNT
    global COMFYGPUARGS
    global MAXTIME
    global IDLETIME
    global WAITTIME
    global MAXSTARTTIME
    global JOBSCUTOFFTIME
    # Reassigned using Secrets Env vars on container
    GPU_MODEL = os.getenv("MODAL_GPU", "L4")
    GPU_NAME = GPU_MODEL.split(':')[0]
    GPU_COUNT = int(GPU_MODEL.split(":")[1]) if ":" in GPU_MODEL else 1
    COMFYGPUARGS = os.getenv("MODAL_COMFYGPUARGS", "")
    MAXTIME = int(os.getenv("MODAL_MAXTIME", "3600"))
    IDLETIME = int(os.getenv("MODAL_IDLETIME", "60"))
    WAITTIME = int(os.getenv("MODAL_WAITTIME", "20"))
    MAXSTARTTIME = int(os.getenv("MODAL_MAXSTARTTIME", "300"))
    JOBSCUTOFFTIME = int(os.getenv("MODAL_JOBSCUTOFFTIME", "86400"))

from models import models, models_ext
from plugins import comfy_plugins, comfy_plugins_ext

root_dir = Path(__file__).parent

base_dir = Path("/cache/ComfyUI")
input_dir = Path("/cache/ComfyUI/input")
output_dir = Path("/cache/ComfyUI/output")
user_dir = Path("/cache/ComfyUI/user")
models_dir = Path("/cache/ComfyUI/models")
cusnodes_dir = Path("/cache/ComfyUI/custom_nodes")
temp_dir = Path("/cache/ComfyUI/temp")

COMFYUI_ROOT = Path("/root/comfy/ComfyUI")
COMFY_MODELS_ROOT = Path(COMFYUI_ROOT / "models")

# create persistent storage
vol = modal.Volume.from_name("hf-hub-cache", create_if_missing=True, version=2)

# construct images and install deps/custom nodes
image = (
    modal.Image.debian_slim(python_version="3.12")
    .add_local_python_source("models", "plugins", copy=True)
    .run_commands("apt-get update")
    .apt_install("git", "git-lfs", "libgl1-mesa-dev", "libglib2.0-0", "aria2", "ffmpeg") #rav1e
    .uv_pip_install(["pip", "uv", "aiohttp", "fastapi", "websockets", "httpx", "brotli", "zstandard", "starlette", "starlette-compress", "comfy-cli", "comfyui-manager>=4.1b1", "setuptools~=81.0", "gradio>=4", "kernels~=0.12.0"], extra_options="--upgrade")
    .pip_install_from_requirements(str(root_dir / "requirements_comfy.txt")) # uv=True
    # Since nunchaku doesn't have pre-built wheels for pytorch stable v2.11, let's use v2.10
    .uv_pip_install(["torch~=2.10.0", "torchao~=0.16.0", "torchvision~=0.25.0", "torchaudio~=2.10.0", "torchcodec~=0.10.0"], extra_options="--upgrade", index_url="https://download.pytorch.org/whl/cu130") # xformers
    .uv_pip_install("cupy-cuda13x")
    .run_commands("comfy --skip-prompt --no-enable-telemetry tracking disable")
    #.run_commands("git config --global core.fileMode false")
    #.run_commands("git config --global pull.rebase") 
    .run_commands("comfy --skip-prompt install --restore --nvidia --cuda-version 13.0", volumes={"/cache": vol}) # --workspace /cache/ComfyUI
    #  || cd /cache/ComfyUI && comfy --here install --restore && cd - 
    #.run_commands(f"comfy --skip-prompt --workspace /cache/ComfyUI set-default {base_dir}", volumes={"/cache": vol})
    #.run_commands(f"comfy --skip-prompt set-default {COMFYUI_ROOT} --launch-extras='--network-mode personal_cloud --security-level normal'") # Allow installing custom nodes from Manager
    .run_commands("git lfs install") # --skip-smudge
)


def get_comfyui_path() -> Path:
    global COMFYUI_ROOT, COMFY_MODELS_ROOT
    comfyui_path = COMFYUI_ROOT
    #return COMFYUI_ROOT
    try:
        result = subprocess.check_output(["comfy", "which"], text=True)
        if ":" in result:
            comfyui_path = Path(result.split(":", 1)[1].strip())
            COMFYUI_ROOT = comfyui_path
            COMFY_MODELS_ROOT = Path(COMFYUI_ROOT / "models")
            print(f"ComfyUI Path: {comfyui_path}")
        else:
            print("Path not found in output")
    except FileNotFoundError:
        if not modal.is_local():
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
        # Use CivitAI token when available
        uri = url
        if url.startswith("https://civitai.com/") or url.startswith("https://civitai.red/"):
            token = os.environ.get("CIVITAI_TOKEN")
            uri = f"{url}{'&' if '?' in url else '?'}token={token}"
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
                uri,
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
                "--single-branch", 
                "--branch",
                branch,
                url,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
    )
    # TODO (git pull, install dependencies)


def download_all():
    # prepare base directory
    Path(base_dir).mkdir(parents=True, exist_ok=True)
    Path(input_dir).mkdir(parents=True, exist_ok=True)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    Path(cusnodes_dir).mkdir(parents=True, exist_ok=True)
    Path(models_dir).mkdir(parents=True, exist_ok=True)
    Path(str(user_dir / "default/workflows")).mkdir(parents=True, exist_ok=True)
    #subprocess.run(['rsync', '-a', '/root/comfy/ComfyUI/', '/cache/ComfyUI/'], volumes={"/cache": vol})

    for model in models:
        hf_download(model["repo_id"], model["filename"], model["model_dir"])

    for model in models_ext:
        download_external_model(model["url"], model["filename"], model["model_dir"])

    # copy models to base_dir (skip existing files)
    import shutil
    def copy_if_not_exists(src, dst):
        dst_path = Path(dst)
        if dst_path.is_symlink():
            dst_path.unlink() 
        if not os.path.exists(dst):
            src_path = Path(src)
            if src_path.is_symlink():
                # Replicate the symlink itself
                link_to = os.readlink(src_path)
                os.symlink(link_to, dst_path)
            else:
                shutil.copy2(src, dst, follow_symlinks=False)
    
    #print("Copying models structure...")
    #shutil.copytree(COMFYUI_ROOT / "models", base_dir / "models", copy_function=copy_if_not_exists, symlinks=False, ignore_dangling_symlinks=True, dirs_exist_ok=True)


def get_secrets() -> list[modal.Secret]:
    """Prefer Modal Secret 'huggingface-secret' or 'custom-secret'; fall back to local HF_TOKEN and CIVITAI_TOKEN 
    env. Public models work even when both are absent (warned)."""
    secrets = []
    # Try with 'custom-secret'
    try:
        s = modal.Secret.from_name("custom-secret")
        s.hydrate()  # from_name is lazy, force the existence check here
        secrets.append(s)
    except modal.exception.NotFoundError:
        token = os.environ.get("CIVITAI_TOKEN", "")
        if not token:
            print(
                "Warning: no Modal Secret 'custom-secret' and no CIVITAI_TOKEN env. "
                "Gated models will fail."
            )
        secrets.append(modal.Secret.from_dict({"CIVITAI_TOKEN": token}))
    # Try with 'huggingface-secret'
    try:
        s = modal.Secret.from_name("huggingface-secret")
        s.hydrate()  # from_name is lazy, force the existence check here
        secrets.append(s)
    except modal.exception.NotFoundError:
        token = os.environ.get("HF_TOKEN", "")
        if not token:
            print(
                "Warning: no Modal Secret 'huggingface-secret' and no HF_TOKEN env. "
                "Public models will download with throttled bandwidth; "
                "gated models will fail."
            )
        secrets.append(modal.Secret.from_dict({"HF_TOKEN": token}))
    return secrets


# use extra model paths when available
extra_file_path = Path(__file__).parent / "extra_model_paths.yaml"
if extra_file_path.exists():
    image = image.add_local_file(
        extra_file_path, 
        str(COMFYUI_ROOT / "extra_model_paths.yaml"), 
        copy=True
    )
else:
    print(f"Extra Model Paths file ({extra_file_path}) Not Found!")

# download models
image = image.env(
    {"HF_HUB_ENABLE_HF_TRANSFER": "1", "HF_XET_HIGH_PERFORMANCE": "1"}
).run_function(download_all, volumes={"/cache": vol}, secrets=get_secrets())

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
    image = image.run_commands("comfy node install " + " ".join(comfy_plugins), volumes={"/cache": vol}) #, gpu=GPU_MODEL

if comfy_plugins_ext:
    nodes_dir = str(get_comfyui_path() / "custom_nodes")
    Path(nodes_dir).mkdir(parents=True, exist_ok=True)
    for plugin in comfy_plugins_ext:
        folder_name = plugin['url'].rstrip('/').rsplit('/', 1)[-1].removesuffix('.git')
        # clone the repository, including it's submodules
        image = image.run_commands(f"cd {nodes_dir} && git clone --recurse-submodules --single-branch --branch {plugin['branch']} {plugin['url']}")
        # install dependencies from one or more requirements files (usually .txt or .toml files, but can support any extension)
        plugin_reqs = plugin.get("requirements", "").strip()
        if plugin_reqs:
            formatted_reqs = " ".join(f"-r {file}" for file in plugin_reqs.split())
            image = image.run_commands(f"cd {nodes_dir}/{folder_name} && uv pip install --no-deps --python $(command -v python) --compile-bytecode {formatted_reqs}")

        # run installation script (usually install.py or setup.py)
        plugin_install = plugin.get("install", "").strip()
        if plugin_install:
            if plugin_install.endswith(".py"):
                image = image.run_commands(f"cd {nodes_dir}/{folder_name} && python {plugin_install}")
            else:
                print(f"Unsupported installation script: {plugin_install}")

        # install optional packages or packages that got dependency issue with other custom nodes due to pinned to an incompatible version
        plugin_deps = plugin.get("dependencies", "").strip()
        if plugin_deps:
            image = image.uv_pip_install(plugin_deps.split(), extra_options="--no-deps") #, gpu=GPU_MODEL

# install missing dependencies or override with a compatible version
def install_wheels():
    import torch, subprocess, sys
    ver = ".".join(torch.__version__.split(".")[:2])
    # nunchaku
    url = f"https://github.com/nunchaku-tech/nunchaku/releases/download/v1.2.1/nunchaku-1.2.1+cu13.0torch{ver}-cp{sys.version_info.major}{sys.version_info.minor}-cp{sys.version_info.major}{sys.version_info.minor}-linux_x86_64.whl"
    subprocess.check_call([sys.executable, "-m", "uv", "pip", "install", "--no-deps", url])
    # flash-attn
    url = f"https://github.com/mjun0812/flash-attention-prebuild-wheels/releases/download/v0.9.0/flash_attn-2.8.3+cu130torch{ver}-cp{sys.version_info.major}{sys.version_info.minor}-cp{sys.version_info.major}{sys.version_info.minor}-linux_x86_64.whl"
    subprocess.check_call([sys.executable, "-m", "uv", "pip", "install", "--no-deps", url])
    
image = (
    image
    .uv_pip_install("sageattention~=2.2.0", extra_options="--no-build-isolation --extra-index-url https://comfy-org.github.io/wheels")
    .uv_pip_install("sageattn3", extra_options="--no-build-isolation --extra-index-url https://comfy-org.github.io/wheels")
    #.uv_pip_install("flash-attn", extra_options="--no-build-isolation") # need to build with nvcc
    .uv_pip_install("flash-attn-3", extra_options="--no-build-isolation --extra-index-url https://download.pytorch.org/whl/cu130")
    .uv_pip_install("flash-attn-4[cu13]", extra_options="--no-build-isolation", pre=True) # use dependencies
    # Detect pytorch version and install wheels inside the container
    .run_function(install_wheels)
    #.uv_pip_install("tokenizers~=0.19.1", extra_options="--only-binary=tokenizers --no-deps", pre=True) # needed for transformers<4.43
    #.uv_pip_install("transformers~=4.42.4") # extra_options="--no-deps --no-build-isolation" # Fix KeyError: 'default' issue on bytedance Lance
    #.uv_pip_install("peft~=0.10.0") # compatible peft version for transformers 4.40–4.42
)
#print("Done install missing dependencies.")

# Disable ultralytics' Anonymized Google Analytics
image = image.run_commands("yolo settings sync=False")

# Testing for vulnerability on custom nodes
nodes_dir = str(get_comfyui_path() / "custom_nodes")
image = image.run_commands(
    f"python -m venv /tmp/temp_venv && "
    f"/tmp/temp_venv/bin/pip install bandit[toml] && "
    f"/tmp/temp_venv/bin/bandit -r {nodes_dir} -n 3 --severity-level=high || true " # only shows 3 lines of high-severity issue # " -f json "
    f"; rm -rf /tmp/temp_venv || true" # Cleanup ensures venv is not in the final layer, and making sure the image building doesn't failed here.
,volumes={"/cache": vol})

# copy custom nodes to base_dir
#import shutil
#print("Copying custom_nodes structure...")
#shutil.copytree(COMFYUI_ROOT / "custom_nodes", base_dir / "custom_nodes", symlinks=True, ignore_dangling_symlinks=True, dirs_exist_ok=True)

def wait_for_port(port: int, timeout: int = 60):
    """Block until the port is accepting connections."""
    import time
    import socket
    
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return  # port is open — ComfyUI is ready
        except OSError:
            time.sleep(0.5)
    raise TimeoutError(f"ComfyUI never became ready on port {port}")


with image.imports():
    from fastapi.responses import StreamingResponse, JSONResponse, Response
    from fastapi import Request, WebSocket, HTTPException, status
    #from fastapi.middleware.gzip import GZipMiddleware
    from starlette_compress import CompressMiddleware
    import httpx
    import websockets

from fastapi import FastAPI

web_app = FastAPI()
try:
    from starlette_compress import CompressMiddleware  # safe: only runs inside container
    
    # Enable automatic compression
    web_app.add_middleware(
        #GZipMiddleware, 
        #compresslevel=5,     # Balance between speed (1) and size reduction (9)
        CompressMiddleware, # All-in-One compression middleware (Zstd, Brotli, and Gzip)
        zstd_level=10,        # Standard Zstd compression level (1-19)
        brotli_quality=6,   # Brotli: 0 to 11
        gzip_level=5,        # Gzip: 1 to 9
        minimum_size=1000,  # Bytes: skip small payloads to protect CPU overhead
    )
except ImportError:
    pass  # starlette_compress not installed locally; middleware skipped


app = modal.App(
    name="modal-comfyui", 
    image=image, 
    secrets=[
        modal.Secret.from_dict(
            {
                "MODAL_GPU": str(GPU_MODEL),
                "MODAL_COMFYGPUARGS": str(COMFYGPUARGS),
                "MODAL_MAXTIME": str(MAXTIME),
                "MODAL_IDLETIME": str(IDLETIME),
                "MODAL_WAITTIME": str(WAITTIME),
                "MODAL_MAXSTARTTIME": str(MAXSTARTTIME),
                "MODAL_JOBSCUTOFFTIME": str(JOBSCUTOFFTIME),
            }
        ),
    ]
)
shared_dict = modal.Dict.from_name(app.name, create_if_missing=True)
jobs_dict = modal.Dict.from_name(app.name+"_jobs", create_if_missing=True)
# Reset the contents when redeployed, but doing it here will cleared it during spin up!
#shared_dict.clear()
num_prompts = 0


uiport = 8188
gpuport = uiport + 1
cpuport = uiport + 2

from enum import IntEnum, auto

class LogsType(IntEnum):
    ERROR = auto()  # Starts at 1 by default
    WARNING = auto()  # 2
    INFO = auto()  # 3
    DEBUG = auto()   # 4
    VERBOSE = auto()   # 5
    
async def send_logs_msg(websocket: WebSocket, msg: str, logs_type: LogsType = 0):
    import json
    from datetime import datetime
    from starlette.websockets import WebSocketState
    
    if websocket.client_state != WebSocketState.DISCONNECTED:
        prefixtype = ""
        match logs_type:
            case LogsType.ERROR:
                prefixtype = "\u001b[1m\u001b[31m[ERROR]\u001b[0m "
            case LogsType.WARNING:
                prefixtype = "\u001b[1m\u001b[33m[WARNING]\u001b[0m "
            case LogsType.INFO:
                prefixtype = "\033[32m[INFO]\033[0m "
                
        msg = f"\n{prefixtype}{msg}"
        data = {"type": "logs","data": {"entries": [{"t": datetime.utcnow().isoformat(),"m": msg}],"size": None}}
        await websocket.send_text(json.dumps(data))

async def fix_gpu_active_count():
    # Fix active count, in the case where the GPU container got SIGKILLed (which couldn't reached @modal.exit stage)
    GpuClass = modal.Cls.from_name(app.name, "ComfyGPU")
    stats = await GpuClass().web.get_current_stats.aio()
    active_count = stats.num_total_runners
    await shared_dict.put.aio("active", active_count)
    print(f"Detected Active GPU instance(s): {active_count}")
    # if there is no active GPU instance, inqueue should be 0 too
    if active_count == 0:
        await shared_dict.put.aio("inqueue", 0)
    
async def get_remote_url(class_name: str) -> str:
    remote_cls = modal.Cls.from_name(app.name, class_name)
    url = await remote_cls().web.get_web_url.aio()
    return url

async def do_vol_commit(class_name: str):
    # Dynamically look up the class from the other deployed app
    TargetCls = modal.Cls.from_name(app.name, class_name)

    active_count = await shared_dict.get.aio("active", 0)
    if active_count > 0:
        try:
            print(f"Commiting Volume changes on {class_name} instance.")
            # Instantiate and await the method remotely (.remote.aio())
            remote_instance = TargetCls()
            await remote_instance.vol_commit.remote.aio()
        except Exception as e:
            print(f"do_vol_commit Throw: {e!r}")

async def wait_websocket_ready():
    import time
    import asyncio
    print("Waiting for Internal websocket to be Ready...")
    deadline = time.time() + MAXSTARTTIME
    while time.time() < deadline:
        try:
            ws_ready = await shared_dict.get.aio("ws_ready", False)
            if ws_ready:
                #print(f"Internal websocket is Ready!")
                break # websocket is connected to GPU instance
            #print(f"Wait: Time = {time.time()}, (active:{active_count}, ready:{ws_ready}, host: {ws_host})")
        except Exception as e:
            print(f"Waiting websocket Throw: {e!r}")
        
        await asyncio.sleep(0.1)
    else:
        print("Internal Websocket Timeout!") # raise TimeoutError("Internal Websocket Timeout!")

async def forward_httpx(url: str, request: Request, try_json: bool = False, timeout: int = 120, new_body: bytes = b'', show_logs: bool = False):
    # Strip Host from headers to prevent loopback
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in (
            "host",
            "content-length",
            "x-forwarded-proto",
            "x-forwarded-for",
            "x-forwarded-host",
            "x-forwarded-port",
        )
    }
    # Enforce using only encoding that will be automatically decoded (ie. gzip/deflate/br) by request
    #headers["accept-encoding"] = "gzip, deflate" # , br # "identity;q=1, *;q=0" 
    # Use original range header (for partial streaming) if exist
    #if range_header := request.headers.get("range"):
    #    headers["Range"] = range_header
        
    # Load the full content into memory instead of streaming in chunk with request.stream()
    try:
        body = await request.body()
    except Exception as e:
        print(f"Request Body Throw: {e!r}")
        
    if new_body:
        body = new_body
    
    # Forward to remote ComfyUI
    async def make_stream():
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    method=request.method,
                    url=f"{url}{request.url.path}",
                    params=request.query_params,
                    headers=headers,
                    content=body,
                    #stream=True,
                    #extensions={"decode_content": False}, 
                ) as resp:
                    # Yield metadata as first item, then chunks
                    yield resp
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        #if show_logs:
                        #    print(f"[{request.method}:{request.url.path}?{request.query_params}({len(chunk)})]: >..> {chunk} <..<")
                        yield chunk
        except httpx.TimeoutException:
            # Return 504 when the upstream server fails to reply within the timeout period
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="The upstream server took too long to respond."
            )
        except httpx.HTTPStatusError as exc:
            # Handle other forwarding status errors
            raise HTTPException(
                status_code=exc.response.status_code,
                detail="Upstream server error occurred."
            )

    gen = make_stream()

    # First yield is the response object with headers/status
    resp = await anext(gen) # await gen.__anext__()
    
    # Filter hop-by-hop headers that must not be forwarded
    HOP_BY_HOP = {
        "transfer-encoding", "connection", "keep-alive",
        "proxy-authenticate", "proxy-authorization",
        "te", "trailers", "upgrade",
        "content-encoding",  # httpx already decoded it
        # CORS — let your proxy set its own
        #"access-control-allow-origin",
        #"access-control-allow-credentials", # FIXME: credentials need to be False when origin='*'?
        #"access-control-allow-headers",
        #"access-control-allow-methods",
        #"access-control-expose-headers",
        # vendor-specific
        #"alt-svc",               # HTTP/3 hint, irrelevant for proxied response
        "modal-function-call-id", # upstream vendor header, not for client (can cause image not to shows up)
    }
    filtered_headers = {
        k: v for k, v in resp.headers.items()
        if k.lower() not in HOP_BY_HOP
    }

    is_chunked = resp.headers.get("transfer-encoding", "").lower() == "chunked"
    is_json = "application/json" in resp.headers.get("content-type", "")
    is_empty = int(resp.headers.get("content-length", "-1")) == 0

    # Stream only non-JSON chunked responses (SSE, binary, etc.)
    if is_chunked and not is_json and not try_json and not is_empty: # or (resp.status_code==206 and not resp.headers.get("content-length", "")):
        if show_logs:
            print(f"[{request.method}:{request.url.path}?{request.query_params}]: {request.headers} >> {body} ==> [[{resp.status_code}]] =>> {resp.headers} >>>> ")
        # Remaining yields are byte chunks — client/stream stays open
        new_resp = StreamingResponse(
            gen,  # continues from where we left off
            status_code=resp.status_code,
            headers=filtered_headers,
            media_type=resp.headers.get("content-type"),
        )
    else:
        # Safe to buffer small/complete responses
        content = await resp.aread()
        # Close the generator cleanly
        await gen.aclose()
        if show_logs:
            print(f"[{request.method}:{request.url.path}?{request.query_params}({len(content)})]: {request.headers} >> {body} ==> [[{resp.status_code}]] =>> {resp.headers} >>> {content} <<<")
        new_resp = Response(
            content=content,
            status_code=resp.status_code,
            headers=filtered_headers,
            media_type=resp.headers.get("content-type"),
        )
        if try_json:
            import json
            if content:
                try:
                    # NOTE: resp.content might be zstd compressed (depends on resp.headers["content-encoding"]), thus resp.json() might failed without explicitly decompressing the content first
                    #import zstandard as zstd
                    #dctx = zstd.ZstdDecompressor()
                    #decompressed = dctx.decompress(resp.content)

                    new_resp = JSONResponse(content=json.loads(content), status_code=resp.status_code) # JSONResponse(json.loads(new_resp.body), status_code=new_resp.status_code)
                except Exception as e: # (json.JSONDecodeError, UnicodeDecodeError):
                    print(f"[{request.method}:{request.url.path}({len(content)})] Throw: {e!r} => {resp.headers} ==> {resp}")
            #else:
            #    new_resp = JSONResponse(content={}, status_code=resp.status_code)
        
    return new_resp
    

@web_app.post("/prompt")
@web_app.post("/api/prompt")
async def proxy_prompt(request: Request):
    global num_prompts
    url = await get_remote_url("ComfyGPU")

    pending_prompt = await shared_dict.get.aio("pending_prompt", 0)
    await shared_dict.put.aio("pending_prompt", pending_prompt + 1)
    num_prompts += 1
    #print(f"Increasing Pending Prompt to: {pending_prompt + 1}")

    # spin-up GPU instance
    active_count = await shared_dict.get.aio("active", 0)
    if active_count == 0:
        print("Spinning Up GPU instance...")
        async with httpx.AsyncClient(timeout=MAXSTARTTIME) as client:
            await client.get(url)
            # Testing for pending_prompt value as spinning up GPU instance could reset the shared_dict
            #pending_prompt = await shared_dict.get.aio("pending_prompt", 0)
            #print(f"Rechecked pending_prompt: {pending_prompt}")

    # TODO: ws_host, ws_ready, inqueue, pending_prompt, and internal sid should be created per EndUser's sid/clientId/client_id (ie. ws_ready[client_id])
    # wait until websocket is connected to GPU instance
    print("Waiting for GPU websocket to be Ready...")
    import time
    import asyncio
    sid = ""
    deadline = time.time() + MAXSTARTTIME
    while time.time() < deadline:
        try:
            #shared_dict.hydrate()
            active_count = await shared_dict.get.aio("active", 0)
            sid = await shared_dict.get.aio("sid", "")
            ws_ready = await shared_dict.get.aio("ws_ready", False)
            ws_host  = await shared_dict.get.aio("ws_host", "127.0.")
            if active_count>0 and sid and ws_ready and not ws_host.startswith("127.0."):
                print(f"GPU websocket is Ready! (Active:{active_count}, Ready:{ws_ready}, Host: {ws_host})")
                break # websocket is connected to GPU instance
            #print(f"Wait: Time = {time.time()}, (active:{active_count}, ready:{ws_ready}, host: {ws_host})")
        except Exception as e:
            print(f"Waiting GPU Throw: {e!r}")
        
        await asyncio.sleep(0.1)
    else:
        print("GPU instance Timeout!")

    # Replace client_id content with the new sid, because sometimes the progressbar didn't shows up
    body = await request.body()
    import json
    try:
        bodyobj = json.loads(body)
        oldid = bodyobj.get("client_id", "")
        if oldid and sid:
            print(f"Replacing client_id: {oldid} ==> {sid}")
            bodyobj["client_id"] = sid
        body = json.dumps(bodyobj).encode('utf-8')
    except Exception as e:
        print(f"[{request.method}:{request.url.path}] Body JSON Throw: {e!r}")
        
    # Forward request
    try:
        print(f"Forwarding {request.method}:{request.url.path} to GPU instance...")
        new_resp = await forward_httpx(url, request, True, new_body=body)
    except Exception as e:
        print(f"[{request.method}:{request.url.path}?{request.query_params}] Throw: {e!r}")

    # NOTE: If the input got preempted/interrupted midway, pending_prompt might not get decreased!
    pending_prompt = await shared_dict.get.aio("pending_prompt", 0)
    if pending_prompt > 0:
        await shared_dict.put.aio("pending_prompt", pending_prompt - 1)
        #print(f"Decreasing Pending Prompt to: {pending_prompt - 1}")
    num_prompts -= 1
    
    return new_resp

@web_app.get("/prompt")
@web_app.get("/api/prompt")
@web_app.get("/queue")
@web_app.get("/api/queue")
@web_app.post("/queue")
@web_app.post("/api/queue")
async def proxy_queue(request: Request):
    url = f"http://127.0.0.1:{uiport}"
    active_count = await shared_dict.get.aio("active", 0)
    if active_count > 0:
        url = await get_remote_url("ComfyGPU")

    # wait until internal websocket is connected and ready
    await wait_websocket_ready()
    
    # Forward request
    new_resp = await forward_httpx(url, request, True, show_logs=True)
 
    return new_resp

@web_app.get("/system_stats")
@web_app.get("/api/system_stats")
@web_app.post("/free")
@web_app.post("/interrupt")
@web_app.post("/api/interrupt")
async def proxy_interrupt(request: Request):
    url = f"http://127.0.0.1:{uiport}"
    active_count = await shared_dict.get.aio("active", 0)
    if active_count > 0:
        url = await get_remote_url("ComfyGPU")

    # wait until internal websocket is connected and ready
    await wait_websocket_ready()
    
    # Forward request
    new_resp = await forward_httpx(url, request, True, show_logs=True)
 
    return new_resp

# Proxy history API routes
@web_app.get("/object_info{path:path}")
@web_app.get("/api/object_info{path:path}")
@web_app.get("/history{path:path}")
@web_app.post("/history{path:path}")
@web_app.get("/api/history{path:path}")
@web_app.post("/api/history{path:path}")
async def proxy_history(request: Request, path: str):
    url = f"http://127.0.0.1:{uiport}"
    active_count = await shared_dict.get.aio("active", 0)
    if active_count > 0:
        url = await get_remote_url("ComfyGPU")

    body = await request.body()
    bodyobj = {}
    import json
    try:
        bodyobj = json.loads(body)
    except Exception as e:
        print(f"[{request.method}:{request.url.path}] Body JSON Throw: {e!r}")

    # Forward request
    new_resp = await forward_httpx(url, request, True, new_body=body, show_logs=True)

    # TODO: get all history (similar to /api/jobs ?)
    max_items = int(request.query_params.get("max_items", 200))
    offset = int(request.query_params.get("offset", -1))

    # get the job from cache if not found
    if (new_resp.status_code == 404 or not new_resp.body) and request.method=="GET" and path.startswith("/") and len(path)>1:
        job_id = path[1:]
        job = await jobs_dict.get.aio(str(job_id), None)
        if job:
            new_resp = JSONResponse(content=job)
            
    # Clear/delete cached history too
    elif new_resp.status_code == 200 and request.method=="POST":
        if bodyobj.get("clear", False):
            print("Clearing All completed jobs!")
            await jobs_dict.clear.aio()
        if "delete" in bodyobj:
            to_delete = bodyobj["delete"]
            for id_to_delete in to_delete:
                await jobs_dict.pop.aio(str(id_to_delete), None)
    
    return new_resp

@web_app.get("/api/jobs{path:path}")
async def proxy_jobs(request: Request, path: str):
    import json
    import asyncio
    import time
    
    url = f"http://127.0.0.1:{uiport}"
    active_count = await shared_dict.get.aio("active", 0)
    if active_count > 0:
        url = await get_remote_url("ComfyGPU")

    # wait until internal websocket is connected and ready
    await wait_websocket_ready()
    
    # Forward request
    new_resp = await forward_httpx(url, request, True)

    # get the job from cache if not found
    if new_resp.status_code == 404 and path.startswith("/") and len(path)>1:
        job_id = path[1:]
        job = await jobs_dict.get.aio(str(job_id), None)
        if job:
            new_resp = JSONResponse(content=job)
    else:
        # cache completed jobs to be persistent across sessions
        params = request.query_params.get("status", "")
        sort_by = request.query_params.get('sort_by', 'created_at').lower()
        sort_order = request.query_params.get('sort_order', 'desc').lower()

        if params and "completed" in params:
            try:
                respobj = json.loads(new_resp.body)
                # update jobs_dict with new jobs
                jobs = respobj.get("jobs", [])
                pagination = respobj.get("pagination", {})
                if jobs:
                    await asyncio.gather(*[
                        jobs_dict.put.aio(str(item["id"]), item)  # skip_if_exists=True
                        for item in jobs
                    ])
                # current time in milliseconds (create_time is in ms)
                cutoff = time.time() * 1000 - (JOBSCUTOFFTIME * 1000)
                # retrieve the full jobs (filter out old jobs when needed)
                jobs = [v async for _, v in jobs_dict.items.aio() if JOBSCUTOFFTIME < 0 or v.get("create_time", 0) >= cutoff]
    
                # update pagination
                if pagination:
                    jobs_count = len(jobs)
                    page_offset = int(pagination.get("offset", 0))
                    page_limit = int(pagination.get("limit", 200)) # limit is optional, but we should cap it.
                    pagination["has_more"] = (page_offset+page_limit < jobs_count)
                    if jobs_count > page_limit:
                        jobs_count = page_limit
                    pagination["total"] = jobs_count
                    # sort jobs by sort_by(ie. create_time) in sort_order(ie. desc) order
                    jobs.sort(key=lambda x: x.get(sort_by, 0), reverse=(sort_order=="desc"))
                    # only retrieve jobs up to limit from offset
                    jobs = jobs[page_offset:page_offset + page_limit]
                    # update response's pagination
                    pagination["limit"] = page_limit
                    respobj["pagination"] = pagination
                
                # update response' jobs
                respobj["jobs"] = jobs
    
                # construct new response
                new_body = json.dumps(respobj).encode("utf-8")
            
                # update headers with correct content-length
                headers = dict(new_resp.headers)
                headers["content-length"] = str(len(new_body))
            
                new_resp = Response(
                    content=new_body,
                    status_code=new_resp.status_code,
                    headers=headers,
                    media_type=new_resp.media_type,
                )
            except Exception as e:
                print(f"[{request.method}:{request.url.path}] Body JSON Throw: {e!r}")

    return new_resp

@web_app.get("/view")
@web_app.get("/viewvideo")
@web_app.get("/api/view")
@web_app.get("/api/viewvideo")
async def proxy_view(request: Request):
    url = f"http://127.0.0.1:{uiport}"
    active_count = await shared_dict.get.aio("active", 0)
    if active_count > 0:
        url = await get_remote_url("ComfyGPU")

    # wait until internal websocket is connected and ready
    await wait_websocket_ready()
    
    # Forward request
    new_resp = await forward_httpx(url, request, False) #stream=True 

    # Making sure the content is downloadable
    #headers = {} # dict(new_resp.headers)
    ##headers.pop("transfer-encoding", None)  # avoid conflict with content-length
    #for key in ("content-disposition", "content-range", "accept-ranges", "content-length", "etag", "cache-control", "last-modified", "transfer-encoding"):
    #    if val := new_resp.headers.get(key):
    #        headers[key] = val
    #    
    #new_resp = Response(
    #        content=new_resp.body,
    #        media_type=new_resp.media_type,
    #        status_code=new_resp.status_code,
    #        headers=headers,
    #)
    return new_resp

# Proxy Logs API routes
@web_app.patch("/internal/logs{path:path}")
@web_app.get("/internal/logs{path:path}")
async def proxy_logs(request: Request, path: str):
    url = f"http://127.0.0.1:{uiport}"
    active_count = await shared_dict.get.aio("active", 0)
    if active_count > 0:
        url = await get_remote_url("ComfyGPU")

    # wait until internal websocket is connected and ready
    await wait_websocket_ready()

    # store logs subscribe enabled state
    body = await request.body()
    import json
    if path == "/subscribe" and request.method == "PATCH":
        try:
            bodyobj = json.loads(body)
            value = bodyobj.get("enabled", "false")
            logs_enabled = value if isinstance(value, bool) else value.lower() == "true"
            await shared_dict.put.aio("logs_enabled", logs_enabled)
        except Exception as e:
            print(f"[{request.method}:{request.url.path}] Body JSON Throw: {e!r}")

    # Forward request
    new_resp = await forward_httpx(url, request, True, new_body=body)
 
    return new_resp

# Proxy Crystools API routes
@web_app.patch("/api/crystools{path:path}")
@web_app.get("/api/crystools{path:path}")
async def proxy_crystools(request: Request, path: str):
    url = f"http://127.0.0.1:{uiport}"
    active_count = await shared_dict.get.aio("active", 0)
    if active_count > 0:
        url = await get_remote_url("ComfyGPU")

    # wait until internal websocket is connected and ready
    await wait_websocket_ready()

    # Forward request
    new_resp = await forward_httpx(url, request, True, show_logs=True)

    # Check and tamper GPU info with fake GPUs
    # NOTE: Trying to access faked GPU will get status_code=400 (ie. PATCH /api/crystools/monitor/GPU/0 -> 400 Bad Request)
    try:
        # NOTE: StreamingResponse doesn't have body and can throw exception here!
        body = new_resp.body
    except Exception as e:
        print(f"NoBody Throw: {e!r}")
        
    import json
    if path == "/monitor/GPU" and request.method == "GET":
        #await shared_dict.put.aio("crystools_enabled", True)
        #fakeGPUs = b'[{"index": 0, "name": "NVIDIA L4"}]'
        #gpus = json.loads(fakeGPUs)
        #duplicated = [{"index": i, "name": gpus[0]["name"]} for i in range(GPU_COUNT)]
        duplicated = [{"index": i, "name": f"NVIDIA {GPU_NAME}"} for i in range(GPU_COUNT)]
        fakeGPUs = json.dumps(duplicated).encode('utf-8')
        try:
            bodyobj = json.loads(body)
            # If no GPU detected
            if not bodyobj or not bodyobj[0]:
                print(f"Faking to have {GPU_COUNT}x NVIDIA {GPU_NAME} GPU!")
                body = fakeGPUs
        except Exception as e:
            print(f"[{request.method}:{request.url.path}] Body JSON Throw: {e!r}")
            if not body:
                print(f"Faking (e) to have {GPU_COUNT}x NVIDIA {GPU_NAME} GPU!")
                body = fakeGPUs

    headers = dict(new_resp.headers)
    headers.pop("transfer-encoding", None)  # avoid conflict with content-length

    new_resp = Response(
            content=body, # content-length will be set if "transfer-encoding: chunked" is not present.
            media_type=new_resp.media_type,
            status_code=new_resp.status_code,
            headers=headers,
    )
    return new_resp 

# Proxy other API routes
@web_app.get("/api/{path:path}")
@web_app.get("/internal/{path:path}")
async def proxy_api(request: Request, path: str):
    url = f"http://127.0.0.1:{uiport}"
    active_count = await shared_dict.get.aio("active", 0)
    if active_count > 0:
        url = await get_remote_url("ComfyGPU")

    # Forward request
    new_resp = await forward_httpx(url, request, True)
 
    return new_resp

# Proxy websocket
@web_app.websocket("/ws")
async def proxy_websocket(websocket: WebSocket): # (websocket: WebSocket, request: Request)
    await websocket.accept()

    import asyncio
    import json
    import time
    from starlette.websockets import WebSocketState
    from websockets.connection import State
    from websockets.exceptions import ConnectionClosedError
    
    # Strip Host from headers to prevent loopback
    headers = {
        k: v for k, v in websocket.headers.items()
        if k.lower() not in (
            "host",
            "content-length",
            "accept-encoding",   # not applicable to websockets
            "x-forwarded-proto",
            "x-forwarded-for",
            "x-forwarded-host",
            "x-forwarded-port",
        )
    }
    # Enforce using only encoding that will be automatically decoded (ie. gzip/deflate/br) by request
    #headers["accept-encoding"] = "deflate" #gzip, br, # "identity;q=1, *;q=0"

    # Get query parameters as an ImmutableMultiDict
    query_params = dict(websocket.query_params)
    params = ""
    if query_params:
        params = f"?{'&'.join([f'{k}={v}' for k, v in query_params.items()])}"

    # Use existing clientId (including from CPU instance) when available
    sid = await shared_dict.get.aio("sid", "")
    if sid and not params: 
        params = f"?clientId={sid}"
        
    # We should only exit the function when connection to client lost
    while True:
        # Use active GPU instance when available, otherwise use localhost (CPU)
        uri = f"ws://127.0.0.1:{uiport}/ws"
        #shared_dict.hydrate()
        active_count = await shared_dict.get.aio("active", 0)
        inqueue_count = await shared_dict.get.aio("inqueue", 0)
        pending_prompt = await shared_dict.get.aio("pending_prompt", 0)
        print(f"Active = {active_count}, InQueue = {inqueue_count}, PendingPrompt = {pending_prompt}")
        if active_count > 0 and (inqueue_count>0 or pending_prompt>0):
            url = await get_remote_url("ComfyGPU")
            from urllib.parse import urlparse, urlunparse
            scheme_map = {"http": "ws", "https": "wss"}
            parsed = urlparse(url)
            if parsed.scheme in scheme_map:
                # Create a new URL object with the updated scheme
                new_parsed = parsed._replace(scheme=scheme_map[parsed.scheme])
                url = urlunparse(new_parsed)
            uri = f"{url}/ws"
        uri = f"{uri}{params}"

        # Send a message to Enduser's websocket
        await send_logs_msg(websocket, f"Connecting to {uri} ...\n", LogsType.INFO)

        try:
            print(f"CONNECTing to {uri}")
            print(f"Headers: {headers}")
            async with websockets.connect(
                uri,
                additional_headers=headers, 
                #compression="deflate",  # this is the only valid option (and it's the default)
                open_timeout=MAXSTARTTIME,  # handshake timeout (seconds)
                close_timeout=10,           # graceful close timeout
                ping_interval=15,           # send pings every N seconds
                ping_timeout=20,            # wait N seconds for pong before closing
            ) as comfy_ws:
                dc_time = 0
                
                async def client_to_comfy():
                    try:
                        async for message in websocket.iter_bytes():
                            #if isinstance(message, str) and message.startswith("{"):
                            #    msgobj = json.loads(message)
                            print(f"client_to_comfy: {message}")
                            if message is not None:
                                await comfy_ws.send(message)
                    except Exception as e:
                        print(f"client_to_comfy Throw: {e!r}")
                        # Update "active" with the actual number
                        await fix_gpu_active_count()
                    finally:
                        # Close internal connection when there are no more messages
                        #print("Internal websocket is Not Ready!")
                        #await shared_dict.put.aio("ws_ready", False)
                        #await comfy_ws.close()
                        pass
                        
                async def comfy_to_client():
                    nonlocal dc_time
                    try:
                        async for message in comfy_ws:
                            if isinstance(message, bytes):
                                print(f"comfy_to_client(b): {message}")
                                await websocket.send_bytes(message)
                                #ws_ready = await shared_dict.get.aio("ws_ready", False)
                                #if not ws_ready and comfy_ws.state != State.CLOSED:
                                #    await shared_dict.put.aio("ws_ready", True)
                                #    print(f"Internal websocket is Ready[b]!({comfy_ws.request.headers.get("Host", "")})")
                            elif message is not None:
                                print_msg = True
                                status_updated = False
                                inqueue_count = 0
                                sid = ""
                                if message.startswith("{"):
                                    try:
                                        msgobj = json.loads(message)
                                        # Don't logs messages for crystools.monitor, since it can flood the logs
                                        if msgobj.get("type", "").startswith("crystools.monitor"):
                                            print_msg = False
                                        # Check sid existence when receiving status message
                                        if msgobj.get("type", "").startswith("status"):
                                            sid = (msgobj["data"]).get("sid", "")
                                            # Update sid
                                            if sid:
                                                await shared_dict.put.aio("sid", sid)
                                            # Update number of inqueue when connected to GPU instance
                                            if not comfy_ws.request.headers.get("Host", "").startswith("127.0."):
                                                inqueue_count = int(msgobj["data"]["status"]["exec_info"]["queue_remaining"])
                                                await shared_dict.put.aio("inqueue", inqueue_count)
                                                status_updated = True
                                                # Update sid if it's from GPU instance
                                                #if sid:
                                                #    await shared_dict.put.aio("sid", sid)
                                                #    ws_ready = await shared_dict.get.aio("ws_ready", False)
                                                #    if not ws_ready and comfy_ws.state != State.CLOSED:
                                                #        await shared_dict.put.aio("ws_ready", True)
                                                #        print(f"Internal websocket is Ready!({comfy_ws.request.headers.get("Host", "")})")
                                    except Exception as e:
                                        print(f"message JSON Throw: {e!r}")
                                        
                                if print_msg:
                                    print(f"comfy_to_client: {message}")
                                
                                await websocket.send_text(message)
                                active_count = await shared_dict.get.aio("active", 0)
                                # Update ws_ready after receiving status message with sid
                                ws_ready = await shared_dict.get.aio("ws_ready", False)
                                if not ws_ready and sid and comfy_ws.state != State.CLOSED:
                                    await shared_dict.put.aio("ws_ready", True)
                                    print(f"Internal websocket is Ready!({comfy_ws.request.headers.get("Host", "")})")
                                    if active_count > 0:
                                        await send_logs_msg(websocket, f"{active_count} Active GPU instance(s) detected.\n", LogsType.INFO)
                                    # Re-subscribe the Logs on GPU instance
                                    logs_enabled = await shared_dict.get.aio("logs_enabled", False)
                                    if logs_enabled and not comfy_ws.request.headers.get("Host", "").startswith("127.0."):
                                        print(f"Re-subscribing Logs({logs_enabled})...")
                                        logs_url = f"http://127.0.0.1:{uiport}"
                                        if active_count > 0:
                                            logs_url = await get_remote_url("ComfyGPU")
                                        logs_url += "/internal/logs/subscribe"
                                        logs_body = json.dumps({"enabled": logs_enabled, "clientId": sid}).encode("utf-8") 
                                        async with httpx.AsyncClient(timeout=120) as logs_client:
                                            await logs_client.patch(logs_url, content=logs_body)
                                    # Re-Patch Crystools monitor on GPU instance
                                    #crystools_enabled = await shared_dict.get.aio("crystools_enabled", False)
                                    #if crystools_enabled and not comfy_ws.request.headers.get("Host", "").startswith("127.0."):
                                    #    print(f"Re-patching Crystools Monitor ({gpu_enabled})...")
                                    #    crystools_url = f"http://127.0.0.1:{uiport}"
                                    #    if active_count > 0:
                                    #        crystools_url = await get_remote_url("ComfyGPU")
                                    #        crystools_url += "/api/crystools/monitor/GPU"
                                    #        async with httpx.AsyncClient(timeout=120) as crystools_client:
                                    #            crystools_resp = await crystools_client.get(crystools_url)
                                    #        crystools_body = json.dumps({"temperature": True, "utilization": True, "vram": True}).encode("utf-8") 
                                    #        async with httpx.AsyncClient(timeout=120) as crystools_client:
                                    #            await crystools_client.patch(crystools_url+"/0", content=crystools_body)
                                    
                                # Disconnect from GPU instance when there are no running inference anymore
                                if status_updated:
                                    pending_prompt = await shared_dict.get.aio("pending_prompt", 0)
                                    inqueue_count = await shared_dict.get.aio("inqueue", 0)
                                    if active_count>0 and inqueue_count==0 and pending_prompt==0 and not comfy_ws.request.headers.get("Host", "").startswith("127.0."):
                                        countdown = WAITTIME
                                        dc_time = time.time() + countdown
                                        print(f"{inqueue_count}(+{pending_prompt}) Queue remaining in GPU instance. Disconnecting from GPU instance in {countdown} seconds.")
                                        # Send to logs too
                                        await send_logs_msg(websocket, f"No queued prompt left. Disconnecting from GPU instance in {countdown} seconds.\n", LogsType.INFO)
                                        # Force remote instance to commit changes on volume
                                        await do_vol_commit("ComfyGPU")
                                        # Commit the volume locally too
                                        await vol.commit.aio()
                                        #print("Internal websocket is Not Ready anymore!")
                                        #await shared_dict.put.aio("ws_ready", False)
                                        #await comfy_ws.close()
                    except Exception as e:
                        print(f"comfy_to_client Throw: {e!r}")
                        # NOTE: ConnectionClosedError(None, Close(code=<CloseCode.PROTOCOL_ERROR: 1002> could mean the remote ComfyUI (GPU instance) got SIGKILLed/crashed! (and didn't reached App CleanUp stage!)
                        # Update "active" with the actual number
                        await fix_gpu_active_count()
                    finally:
                        # Close internal connection when there are no more messages
                        #print("Internal websocket is Not Ready!")
                        #await shared_dict.put.aio("ws_ready", False)
                        #await comfy_ws.close()
                        pass
                        
                async def watch_active():
                    nonlocal dc_time
                    prev_pending = 0
                    try:
                        while True:
                            #shared_dict.hydrate()
                            active_count = await shared_dict.get.aio("active", 0)
                            inqueue_count = await shared_dict.get.aio("inqueue", 0)
                            pending_prompt = await shared_dict.get.aio("pending_prompt", 0)
                            #print(f"watch_active: Active = {active_count}, Request = {comfy_ws.request}, Response = {comfy_ws.response}")
                            # Fake a queue while spinning up  GPU instance
                            if active_count == 0 and prev_pending != pending_prompt and websocket.client_state != WebSocketState.DISCONNECTED:
                                print(f"Pending prompt changed! Faking queue_remaining ({pending_prompt})")
                                fakedata = {"type": "status", "data": {"status": {"exec_info": {"queue_remaining": pending_prompt+inqueue_count}}}}
                                await websocket.send_text(json.dumps(fakedata))
                                # Send to logs too
                                await send_logs_msg(websocket, f"Starting GPU instance...\n", LogsType.INFO)
                            prev_pending = pending_prompt
                            
                            # Reset countdown timer when there are pending jobs
                            if active_count > 0 and (pending_prompt > 0 or inqueue_count > 0) and not comfy_ws.request.headers.get("Host", "").startswith("127.0."):
                                dc_time = 0

                            if dc_time != 0 and dc_time <= time.time():
                                print("Internal websocket is Not Ready anymore!")
                                await shared_dict.put.aio("ws_ready", False)
                                await comfy_ws.close()
                                break
                            if websocket.client_state == WebSocketState.DISCONNECTED:
                                print(f"Disconnected EndUser Websocket State = {websocket.client_state}")
                                # Disconnect internal websocket too
                                if comfy_ws.state != State.CLOSED:
                                    print("Internal websocket is Not Ready!")
                                    await shared_dict.put.aio("ws_ready", False)
                                    await comfy_ws.close()
                                break
                            if active_count>0 and (inqueue_count>0 or pending_prompt>0) and comfy_ws.request.headers.get("Host", "").startswith("127.0."):
                                print(f"{active_count} Active GPU instance detected. Disconnecting from CPU instance.")
                                if comfy_ws.state != State.CLOSED:
                                    print("Internal websocket is Not Ready!")
                                    await shared_dict.put.aio("ws_ready", False)
                                    await comfy_ws.close()
                                break
                            if comfy_ws.state == State.CLOSED:
                                print("Closed Internal Websocket!")
                                break
                            #import time
                            #print(f"Watch: Time = {time.time()}, (Active:{active_count}, InQueue:{inqueue_count}, PendingPrompt:{pending_prompt}, Host: {comfy_ws.request.headers.get("Host", "")})")
                            await asyncio.sleep(0.1)  # poll interval
                    except Exception as e:
                        print(f"watch_active Throw: {e!r}")

                ws_host = comfy_ws.request.headers.get("Host", "127.0.0.")
                #if ws_host == "127.0.0.":
                #    print("WARNING: Host not found in request!")
                print(f"Connected Internal WebSocket Host: {ws_host}")
                await shared_dict.put.aio("ws_host", ws_host)
                try:
                    # cancel both tasks when either side closes their internal connection
                    # Create named tasks so we can cancel them
                    client_task = asyncio.create_task(client_to_comfy())
                    server_task = asyncio.create_task(comfy_to_client())
                    watch_task  = asyncio.create_task(watch_active())
    
                    all_tasks = {client_task, server_task, watch_task}
    
                    # Return as soon as ANY task finishes (e.g. watch_active breaks)
                    done, pending = await asyncio.wait(all_tasks, return_when=asyncio.FIRST_COMPLETED)
    
                    # Cancel the remaining tasks
                    for task in pending:
                        task.cancel()
    
                    # Wait for cancellations to complete cleanly
                    await asyncio.gather(*pending, return_exceptions=True)
                except Exception as e:
                    print(f"comfy_ws Throw: {e!r}")
                finally:
                    # Make sure we close internal websocket to avoid double websocket when reconnected (ie. refreshing the tab)
                    if comfy_ws.state != State.CLOSED:
                        print("Internal websocket is Not Ready!")
                        await shared_dict.put.aio("ws_ready", False)
                        await comfy_ws.close()
                print("Internal websocket connection was Closed!")
        except ConnectionClosedError as e:
            # Handles errors during active connection (e.g., ping timeout)
            print(f"Connection closed unexpectedly: {e!r}")
        except (OSError, Exception) as e:
            # Handles connection refused, DNS issues, or handshake failures
            print(f"Failed to connect: {e!r}")
            # NOTE: Responde status_code = 204, the GPU instance might be crashed!
            # Send an error message to EndUser's websocket
            await send_logs_msg(websocket, f"Failed to connect to GPU instance: {e!r}.\n", LogsType.ERROR)
            
        # Exit when EndUser connection is lost
        if websocket.client_state == WebSocketState.DISCONNECTED:
            break
        await asyncio.sleep(1)  # poll every second

# Proxy everything else to local ComfyUI
@web_app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "TRACE"])
async def proxy(request: Request, path: str):
    url = f"http://127.0.0.1:{uiport}"
    
    # Forward request
    new_resp = await forward_httpx(url, request, False)
    
    return new_resp
    

@app.cls(
    max_containers=1,
    gpu=GPU_MODEL,
    memory=(128, 262144), # (request, limit) in MiB, set hard limit to avoid high cost when memory leaks occurred
    volumes={"/cache": vol},
    scaledown_window=IDLETIME,  # idle 1 minutes to shutdown
    enable_memory_snapshot=True,
    experimental_options={"enable_gpu_snapshot": True},
    startup_timeout=MAXSTARTTIME, # container's startup timeout
    timeout=MAXTIME, # execution timeout, this will also be websocket timeout
)
@modal.concurrent(max_inputs=20)
class ComfyGPU:
    @modal.enter(snap=True)
    def start_checkpoint(self):
        try:
            update_vars_from_env()
            print(f"Additional ComfyUI Arguments: {COMFYGPUARGS}")
            self.proc = subprocess.Popen(
                f"comfy manager enable-legacy-gui && comfy launch --background -- {COMFYGPUARGS} --listen 0.0.0.0 --port {gpuport} --enable-cors-header '*' --user-directory {user_dir} --output-directory {output_dir} --input-directory {input_dir} --temp-directory {temp_dir} ", shell=True # --base-directory {base_dir} --extra-model-paths-config {COMFYUI_ROOT}/extra_model_paths.yaml 
            )
            # Block here — snapshot is taken only after this returns
            wait_for_port(gpuport, timeout=MAXSTARTTIME)
        except Exception as e:
            print(f"ComfyGPU Throw: {e!r}")

    @modal.enter(snap=False)
    def start_restore(self):
        update_vars_from_env()
        active_count = shared_dict.get("active", 0)
        shared_dict["active"] = active_count + 1
    
        # On restore, sockets may need to be rebound
        #self.proc = subprocess.Popen(
        #    f"comfy manager enable-legacy-gui && comfy launch --background -- --listen 0.0.0.0 --port {gpuport} --user-directory {user_dir} --output-directory {output_dir} --input-directory {input_dir} ", shell=True # --base-directory {base_dir} --extra-model-paths-config {COMFYUI_ROOT}/extra_model_paths.yaml 
        #)
        wait_for_port(gpuport, timeout=30)
        print("App Restored!")
    
    @modal.web_server(gpuport, startup_timeout=30)
    def web(self):
        print("App Ready!")

    @modal.method()
    def vol_commit(self):
        print("Forcing volume commits!")
        # Force the volume to commit changes 
        vol.commit()
    
    @modal.exit()
    def cleanup(self):
        if shared_dict.get("active", 0) > 0:
            shared_dict["active"] -= 1
        else:
            shared_dict["active"] = 0
        # There won't be any inference running when ComfyUI is shutting down
        shared_dict["inqueue"] = 0
        # Force the volume to commit changes 
        vol.commit()
        
        proc = getattr(self, "proc", None)
        if proc is not None:
            try:
                proc.terminate()
                proc.wait()
            except (ProcessLookupError, OSError):
                pass
        print("App CleanUp!")

@app.cls(
    max_containers=1,
    #cpu=2.0, memory=4096,
    volumes={"/cache": vol},
    scaledown_window=IDLETIME,  # idle 1 minutes to shutdown
    enable_memory_snapshot=True,
    experimental_options={"enable_gpu_snapshot": True},
    startup_timeout=MAXSTARTTIME, # container's startup timeout
    timeout=MAXTIME, # execution timeout, this will also be websocket timeout
)
@modal.concurrent(max_inputs=20)
class ComfyCPU:
    @modal.enter(snap=True)
    def start_checkpoint(self):
        try:
            update_vars_from_env()
            self.proc = subprocess.Popen(
                f"comfy manager enable-legacy-gui && comfy launch --background -- --listen 0.0.0.0 --port {cpuport} --enable-cors-header '*' --user-directory {user_dir} --output-directory {output_dir} --input-directory {input_dir} --temp-directory {temp_dir} --cpu ", shell=True # --base-directory {base_dir} --extra-model-paths-config {COMFYUI_ROOT}/extra_model_paths.yaml
            )
            # Block here — snapshot is taken only after this returns
            wait_for_port(cpuport, timeout=MAXSTARTTIME)
        except Exception as e:
            print(f"ComfyCPU Throw: {e!r}")

    @modal.enter(snap=False)
    def start_restore(self):
        update_vars_from_env()
        # On restore, sockets may need to be rebound
        #self.proc = subprocess.Popen(
        #    f"comfy manager enable-legacy-gui && comfy launch --background -- --listen 0.0.0.0 --port {uiport} --user-directory {user_dir} --output-directory {output_dir} --input-directory {input_dir} --cpu ", shell=True # --base-directory {base_dir} --extra-model-paths-config {COMFYUI_ROOT}/extra_model_paths.yaml 
        #)
        wait_for_port(cpuport, timeout=30)
        print("App Restored!")
    
    @modal.web_server(cpuport, startup_timeout=30)
    def web(self):
        print("App Ready!")

    @modal.exit()
    def cleanup(self):
        # Force the volume to commit changes 
        vol.commit()
        
        proc = getattr(self, "proc", None)
        if proc is not None:
            try:
                proc.terminate()
                proc.wait()
            except (ProcessLookupError, OSError):
                pass
        print("App CleanUp!")

@app.cls(
    max_containers=1,
    #cpu=2.0, memory=4096,
    volumes={"/cache": vol},
    scaledown_window=60, # IDLETIME # idle 1 minutes to shutdown
    enable_memory_snapshot=True,
    experimental_options={"enable_gpu_snapshot": True},
    startup_timeout=MAXSTARTTIME, # container's startup timeout
    timeout=MAXTIME, # execution timeout, this will also be websocket timeout
)
@modal.concurrent(max_inputs=20)
class ComfyMix:
    @modal.enter(snap=True)
    def start_checkpoint(self):
        update_vars_from_env()
        global num_prompts
        num_prompts = 0
        try:
            self.proc = subprocess.Popen(
                f"comfy manager enable-legacy-gui && comfy launch --background -- --listen 0.0.0.0 --port {uiport} --enable-cors-header '*' --user-directory {user_dir} --output-directory {output_dir} --input-directory {input_dir} --temp-directory {temp_dir} --cpu ", shell=True # --base-directory {base_dir} --extra-model-paths-config {COMFYUI_ROOT}/extra_model_paths.yaml
            )
            # Block here — snapshot is taken only after this returns
            wait_for_port(uiport, timeout=MAXSTARTTIME)
        except Exception as e:
            print(f"ComfyMix Throw: {e!r}")

    @modal.enter(snap=False)
    def start_restore(self):
        update_vars_from_env()
        print("App Restored!")
        global num_prompts
        num_prompts = 0
        # On restore, sockets may need to be rebound
        #self.proc = subprocess.Popen(
        #    f"comfy manager enable-legacy-gui && comfy launch --background -- --listen 0.0.0.0 --port {uiport} --user-directory {user_dir} --output-directory {output_dir} --input-directory {input_dir} --cpu ", shell=True # --base-directory {base_dir} --extra-model-paths-config {COMFYUI_ROOT}/extra_model_paths.yaml 
        #)
        wait_for_port(uiport, timeout=30)
    
    @modal.asgi_app()
    def api(self):
        print("App Ready!")
        return web_app
    
    @modal.exit()
    def cleanup(self):
        global num_prompts
        # Force the volume to commit changes 
        vol.commit()
        # Detects preemptive interruption to fix pending_prompt
        if num_prompts > 0:
            pending_prompt = int(shared_dict.get("pending_prompt", 0))
            shared_dict["pending_prompt"] = max(0, pending_prompt - num_prompts)
            print(f"Preemptive/Interruption detected during Prompting! ({pending_prompt} - {num_prompts})")
            num_prompts = 0
        
        proc = getattr(self, "proc", None)
        if proc is not None:
            try:
                proc.terminate()
                proc.wait()
            except (ProcessLookupError, OSError):
                pass
        print("App CleanUp!")

# This will get executed by: python comfyui.py
if __name__ == "__main__":
    with modal.enable_output():
        # Clear the dict before deploying new logic
        with app.run():
            print("Clearing shared_dict ...")
            shared_dict.clear() # Removes all items

        # Alternative to: modal deploy comfyui.py
        print(f"Deploying App({app.name}) ...")
        app.deploy()
