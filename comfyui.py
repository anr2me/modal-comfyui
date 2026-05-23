from __future__ import annotations

import os
import subprocess
from pathlib import Path

import modal

GPU_MODEL = os.getenv("MODAL_GPU", "L4")

from models import models, models_ext
from plugins import comfy_plugins, comfy_plugins_ext

root_dir = Path(__file__).parent

base_dir = Path("/cache/ComfyUI")
input_dir = Path("/cache/ComfyUI/input")
output_dir = Path("/cache/ComfyUI/output")
user_dir = Path("/cache/ComfyUI/user")
models_dir = Path("/cache/ComfyUI/models")
cusnodes_dir = Path("/cache/ComfyUI/custom_nodes")

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
    .uv_pip_install(["pip", "uv", "aiohttp", "fastapi", "websockets", "httpx", "comfy-cli", "comfyui-manager>=4.1b1", "setuptools~=81.0", "gradio>=4", "kernels~=0.12.0"], extra_options="--upgrade")
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


def _hf_secrets() -> list[modal.Secret]:
    """Prefer Modal Secret 'huggingface-secret'; fall back to local HF_TOKEN
    env. Public models work even when both are absent (warned)."""
    try:
        s = modal.Secret.from_name("huggingface-secret")
        s.hydrate()  # from_name is lazy, force the existence check here
        return [s]
    except modal.exception.NotFoundError:
        token = os.environ.get("HF_TOKEN", "")
        if not token:
            print(
                "Warning: no Modal Secret 'huggingface-secret' and no HF_TOKEN env. "
                "Public models will download with throttled bandwidth; "
                "gated models will fail."
            )
        return [modal.Secret.from_dict({"HF_TOKEN": token})]


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
).run_function(download_all, volumes={"/cache": vol}, secrets=_hf_secrets())

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
    url = f"https://github.com/nunchaku-tech/nunchaku/releases/download/v1.2.1/nunchaku-1.2.1+cu13.0torch{ver}-cp312-cp312-linux_x86_64.whl"
    subprocess.check_call([sys.executable, "-m", "uv", "pip", "install", "--no-deps", url])
    # flash-attn
    url = f"https://github.com/mjun0812/flash-attention-prebuild-wheels/releases/download/v0.9.0/flash_attn-2.8.3+cu130torch{ver}-cp312-cp312-linux_x86_64.whl"
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
print("Done install missing dependencies.")

# Disable ultralytics' Anonymized Google Analytics
image = image.run_commands("yolo settings sync=False")

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
    from fastapi import Request, Response, WebSocket
    from fastapi.responses import JSONResponse
    import httpx
    import websockets

from fastapi import FastAPI
web_app = FastAPI() 

app = modal.App(name="modal-comfyui", image=image)
shared_dict = modal.Dict.from_name(app.name, create_if_missing=True)
# Reset the contents when redeployed
shared_dict.clear()


uiport = 8188
gpuport = uiport + 1
cpuport = uiport + 2

async def get_remote_url(class_name: str) -> str:
    remote_cls = modal.Cls.from_name(app.name, class_name)
    url = await remote_cls().web.get_web_url.aio()
    return url

async def forward_httpx(url: str, request: Request, timeout: int = 120) -> Response:
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
    headers["accept-encoding"] = "gzip, br, deflate" #"identity;q=1, *;q=0" 

    # Forward to remote ComfyUI
    body = await request.body()
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.request(
            method=request.method,
            url=f"{url}{request.url.path}",
            params=request.query_params,
            headers=headers,
            content=body,
            #extensions={"decode_content": False}, 
        )
    # Return raw bytes with the original content-type
    new_resp = Response(
        content=resp.content,
        status_code=resp.status_code,
        #media_type=resp.headers.get("content-type"),
        headers=resp.headers,
    )
    try:
        # NOTE: resp.content might be zstd compressed (depends on resp.headers["content-encoding"]), thus resp.json() might failed without explicitly decompressing the content first
        #import zstandard as zstd
        #dctx = zstd.ZstdDecompressor()
        #decompressed = dctx.decompress(resp.content)
        
        #new_resp = JSONResponse(resp.json())
        print(f"[{request.method}:{request.url.path}?{request.query_params}({len(resp.content)})]: {body} ==> {resp.content} <==")
    except Exception as e:
        print(f"[{request.method}:{request.url.path}({len(resp.content)})]: {e!r} => {resp.headers} ==> {resp}")

    return new_resp
    

@web_app.post("/prompt")
@web_app.post("/api/prompt")
@web_app.post("/queue")
@web_app.post("/api/queue")
async def proxy_prompt(request: Request):
    url = await get_remote_url("ComfyGPU")

    pending_prompt = await shared_dict.get.aio("pending_prompt", 0)
    await shared_dict.put.aio("pending_prompt", pending_prompt + 1)

    # spin-up GPU instance
    active_count = await shared_dict.get.aio("active", 0)
    if active_count == 0:
        print("Spinning Up GPU instance...")
        async with httpx.AsyncClient(timeout=300) as client:
            await client.get(url)
    
    # wait until websocket is connected to GPU instance
    print("Waiting for GPU websocket to be Ready...")
    import time
    import asyncio
    deadline = time.time() + 300
    while time.time() < deadline:
        try:
            #shared_dict.hydrate()
            if (await shared_dict.get.aio("ws_ready", False)) and not (await shared_dict.get.aio("ws_host", "")).startswith("127.0."):
                print("GPU websocket is Ready!")
                break  # websocket is connected to GPU instance
        except OSError:
            await asyncio.sleep(0.1) # time.sleep(0.1)
        
    # Forward request
    print(f"Forwarding {request.method}:{request.url.path} to GPU instance...")
    new_resp = await forward_httpx(url, request)
    
    pending_prompt = await shared_dict.get.aio("pending_prompt", 0)
    if pending_prompt > 0:
        await shared_dict.put.aio("pending_prompt", pending_prompt - 1)
    return new_resp

@web_app.get("/prompt")
@web_app.get("/api/prompt")
@web_app.get("/queue")
@web_app.get("/api/queue")
async def proxy_queue(request: Request):
    url = f"http://127.0.0.1:{uiport}"
    active_count = await shared_dict.get.aio("active", 0)
    if active_count > 0:
        url = await get_remote_url("ComfyGPU")

    # Forward request
    new_resp = await forward_httpx(url, request)
 
    return new_resp
    
@web_app.post("/interrupt")
@web_app.post("/api/interrupt")
async def proxy_interrupt(request: Request):
    url = f"http://127.0.0.1:{uiport}"
    active_count = await shared_dict.get.aio("active", 0)
    if active_count > 0:
        url = await get_remote_url("ComfyGPU")

    # Forward request
    new_resp = await forward_httpx(url, request)
 
    return new_resp

#@web_app.get("/api/view")
@web_app.get("/api/jobs")
async def proxy_jobs(request: Request):
    url = f"http://127.0.0.1:{uiport}"
    active_count = await shared_dict.get.aio("active", 0)
    if active_count > 0:
        url = await get_remote_url("ComfyGPU")

    # Forward request
    new_resp = await forward_httpx(url, request)
 
    return new_resp

# Proxy other API routes
@web_app.get("/internal/logs{path:path}")
@web_app.patch("/internal/logs{path:path}")
#@web_app.get("/api/{path:path}")
async def proxy_api(request: Request, path: str):
    url = f"http://127.0.0.1:{uiport}"
    active_count = await shared_dict.get.aio("active", 0)
    if active_count > 0:
        url = await get_remote_url("ComfyGPU")

    # Forward request
    new_resp = await forward_httpx(url, request)
 
    return new_resp

# Proxy websocket
@web_app.websocket("/ws")
async def proxy_websocket(websocket: WebSocket):
    await websocket.accept()

    import asyncio
    from starlette.websockets import WebSocketState
    from websockets.connection import State
    from websockets.exceptions import ConnectionClosedError
    # We should only exit the function when connection to client lost
    while True:
        # Use active GPU instance when available, otherwise use localhost (CPU)
        uri = f"ws://127.0.0.1:{uiport}/ws"
        active_count = await shared_dict.get.aio("active", 0)
        inqueue_count = await shared_dict.get.aio("inqueue", 0)
        print(f"Active = {active_count}, InQueue = {inqueue_count}")
        if active_count > 0:
            url = await get_remote_url("ComfyGPU")
            from urllib.parse import urlparse, urlunparse
            scheme_map = {"http": "ws", "https": "wss"}
            parsed = urlparse(url)
            if parsed.scheme in scheme_map:
                # Create a new URL object with the updated scheme
                new_parsed = parsed._replace(scheme=scheme_map[parsed.scheme])
                url = urlunparse(new_parsed)
            uri = f"{url}/ws"

        try:
            print(f"CONNECTing to {uri}")
            async with websockets.connect(
                uri,
                open_timeout=300,        # handshake timeout (seconds)
                close_timeout=10,       # graceful close timeout
                ping_interval=15,       # send pings every N seconds
                ping_timeout=20,        # wait N seconds for pong before closing
            ) as comfy_ws:
                async def client_to_comfy():
                    import json
                    try:
                        async for message in websocket.iter_bytes():
                            #if isinstance(message, str) and message.startswith("{"):
                            #    msgobj = json.loads(message)
                            print(f"client_to_comfy: {message}")
                            if message is not None:
                                await comfy_ws.send(message)
                    except Exception as e:
                        print("client_to_comfy Throw: " + repr(e))
                    finally:
                        # Close internal connection when there are no more messages
                        #await comfy_ws.close()
                        #await shared_dict.put.aio("ws_ready", False)
                        #print("Internal websocket is Not Ready!")
                        pass
                        
                async def comfy_to_client():
                    import json
                    try:
                        async for message in comfy_ws:
                            if isinstance(message, bytes):
                                print(f"comfy_to_client(b): {message}")
                                await websocket.send_bytes(message)
                                ws_ready = await shared_dict.get.aio("ws_ready", False)
                                if not ws_ready:
                                    await shared_dict.put.aio("ws_ready", True)
                                    print("Internal websocket is Ready!")
                            elif message is not None:
                                print_msg = True
                                status_updated = False
                                inqueue_count = 0
                                if message.startswith("{"):
                                    msgobj = json.loads(message)
                                    # Ignore messages for crystools.monitor
                                    if msgobj.get("type", "").startswith("crystools.monitor"):
                                        print_msg = False
                                    # Update number of inqueue when connected to GPU instance
                                    if msgobj.get("type", "").startswith("status") and not comfy_ws.request.headers.get("Host", "").startswith("127.0."):
                                        inqueue_count = int(msgobj["data"]["status"]["exec_info"]["queue_remaining"])
                                        await shared_dict.put.aio("inqueue", inqueue_count)
                                        status_updated = True
                                if print_msg:
                                    print(f"comfy_to_client: {message}")
                                await websocket.send_text(message)
                                ws_ready = await shared_dict.get.aio("ws_ready", False)
                                if not ws_ready:
                                    await shared_dict.put.aio("ws_ready", True)
                                    print("Internal websocket is Ready!")
                                # Disconnect from GPU instance when there are no running inference anymore
                                if status_updated:
                                    active_count = await shared_dict.get.aio("active", 0)
                                    pending_prompt = await shared_dict.get.aio("pending_prompt", 0)
                                    if active_count>0 and inqueue_count==0 and pending_prompt==0 and not comfy_ws.request.headers.get("Host", "").startswith("127.0."):
                                        print(f"{inqueue_count} Queue remaining in GPU instance, disconnecting from GPU instance.")
                                        await comfy_ws.close()
                                        await shared_dict.put.aio("ws_ready", False)
                                        print("Internal websocket is Not Ready!")
                    except Exception as e:
                        print("comfy_to_client Throw: " + repr(e))
                    finally:
                        # Close internal connection when there are no more messages
                        #await comfy_ws.close()
                        #await shared_dict.put.aio("ws_ready", False)
                        #print("Internal websocket is Not Ready!")
                        pass
                        
                async def watch_active():
                    try:
                        while True:
                            active_count = await shared_dict.get.aio("active", 0)
                            #print(f"watch_active: Active = {active_count}, Request = {comfy_ws.request}, Response = {comfy_ws.response}")
                            if websocket.client_state == WebSocketState.DISCONNECTED:
                                print(f"Disconnected EndUser Websocket State = {websocket.client_state}")
                                # Disconnect internal websocket too
                                if comfy_ws.state != State.CLOSED:
                                    await comfy_ws.close()
                                    await shared_dict.put.aio("ws_ready", False)
                                    print("Internal websocket is Not Ready!")
                                break
                            if active_count>0 and comfy_ws.request.headers.get("Host", "").startswith("127.0."):
                                print(f"{active_count} Active GPU instance detected, disconnecting from CPU instance.")
                                if comfy_ws.state != State.CLOSED:
                                    await comfy_ws.close()
                                    await shared_dict.put.aio("ws_ready", False)
                                    print("Internal websocket is Not Ready!")
                                break
                            if comfy_ws.state == State.CLOSED:
                                print("Closed Internal Websocket!")
                                break 
                            await asyncio.sleep(1)  # poll every second
                    except Exception as e:
                        print("watch_active Throw: " + repr(e))

                ws_host = comfy_ws.request.headers.get("Host", "")
                await shared_dict.put.aio("ws_host", ws_host)
                # cancel both tasks when either side closes their internal connection
                tasks = await asyncio.gather(
                    client_to_comfy(),
                    comfy_to_client(),
                    watch_active(),
                    return_exceptions=True
                )
                #print("Internal websocket connection was closed!")
        except ConnectionClosedError as e:
            # Handles errors during active connection (e.g., ping timeout)
            print(f"Connection closed unexpectedly: {e!r}")
        except (OSError, Exception) as e:
            # Handles connection refused, DNS issues, or handshake failures
            print(f"Failed to connect: {e!r}")
            
        # Exit when EndUser connection is lost
        if websocket.client_state == WebSocketState.DISCONNECTED:
            break
        await asyncio.sleep(1)  # poll every second

# Proxy everything else to local ComfyUI
@web_app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "TRACE"])
async def proxy(request: Request, path: str):
    url = f"http://127.0.0.1:{uiport}"
    
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
    headers["accept-encoding"] = "gzip, br, deflate" #"identity;q=1, *;q=0" 

    body = await request.body()
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.request(
            method=request.method,
            url=f"{url}/{path}",
            params=request.query_params,
            headers=headers,
            content=body,
            #extensions={"decode_content": False},
        )
    # Return raw bytes with the original content-type
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        #media_type=resp.headers.get("content-type"),
        headers=resp.headers,
    )
    

@app.cls(
    max_containers=1,
    gpu=GPU_MODEL,
    volumes={"/cache": vol},
    scaledown_window=60,  # idle 1 minutes to shutdown
    enable_memory_snapshot=True,
    experimental_options={"enable_gpu_snapshot": True},
    startup_timeout=300, # container's startup timeout
    timeout=3600, # execution timeout, this will also be websocket timeout
)
@modal.concurrent(max_inputs=10)
class ComfyGPU:
    @modal.enter(snap=True)
    def start_checkpoint(self):
        self.proc = subprocess.Popen(
            f"comfy manager enable-legacy-gui && comfy launch --background -- --listen 0.0.0.0 --port {gpuport} --enable-cors-header '*' --user-directory {user_dir} --output-directory {output_dir} --input-directory {input_dir} ", shell=True # --base-directory {base_dir} --extra-model-paths-config {COMFYUI_ROOT}/extra_model_paths.yaml 
        )
        # Block here — snapshot is taken only after this returns
        wait_for_port(gpuport, timeout=300)

    @modal.enter(snap=False)
    def start_restore(self):
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
    
    @modal.exit()
    def cleanup(self):
        if shared_dict.get("active", 0) > 0:
            shared_dict["active"] -= 1
        else:
            shared_dict["active"] = 0
        # There won't be any inference running when ComfyUI is shutting down
        shared_dict["inqueue"] = 0
        
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
    scaledown_window=60,  # idle 1 minutes to shutdown
    enable_memory_snapshot=True,
    experimental_options={"enable_gpu_snapshot": True},
    startup_timeout=300, # container's startup timeout
    timeout=3600, # execution timeout, this will also be websocket timeout
)
@modal.concurrent(max_inputs=10)
class ComfyCPU:
    @modal.enter(snap=True)
    def start_checkpoint(self):
        self.proc = subprocess.Popen(
            f"comfy manager enable-legacy-gui && comfy launch --background -- --listen 0.0.0.0 --port {cpuport} --enable-cors-header '*' --user-directory {user_dir} --output-directory {output_dir} --input-directory {input_dir} --cpu ", shell=True # --base-directory {base_dir} --extra-model-paths-config {COMFYUI_ROOT}/extra_model_paths.yaml
        )
        # Block here — snapshot is taken only after this returns
        wait_for_port(cpuport, timeout=300)

    @modal.enter(snap=False)
    def start_restore(self):
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
    scaledown_window=60,  # idle 1 minutes to shutdown
    enable_memory_snapshot=True,
    experimental_options={"enable_gpu_snapshot": True},
    startup_timeout=300, # container's startup timeout
    timeout=3600, # execution timeout, this will also be websocket timeout
)
@modal.concurrent(max_inputs=10)
class ComfyMix:
    @modal.enter(snap=True)
    def start_checkpoint(self):
        self.proc = subprocess.Popen(
            f"comfy manager enable-legacy-gui && comfy launch --background -- --listen 0.0.0.0 --port {uiport} --enable-cors-header '*' --user-directory {user_dir} --output-directory {output_dir} --input-directory {input_dir} --cpu ", shell=True # --base-directory {base_dir} --extra-model-paths-config {COMFYUI_ROOT}/extra_model_paths.yaml
        )
        # Block here — snapshot is taken only after this returns
        wait_for_port(uiport, timeout=300)

    @modal.enter(snap=False)
    def start_restore(self):
        print("App Restored!")
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
        proc = getattr(self, "proc", None)
        if proc is not None:
            try:
                proc.terminate()
                proc.wait()
            except (ProcessLookupError, OSError):
                pass
        print("App CleanUp!")
