from __future__ import annotations

import os
import subprocess
from pathlib import Path

import modal

GPU_MODEL = "L4"

from models import models, models_ext
from plugins import comfy_plugins, comfy_plugins_ext

root_dir = Path(__file__).parent

base_dir = Path("/cache/ComfyUI")
input_dir = Path("/cache/ComfyUI/input")
output_dir = Path("/cache/ComfyUI/output")
user_dir = Path("/cache/ComfyUI/user")

COMFYUI_ROOT = Path("/root/comfy/ComfyUI")
COMFY_MODELS_ROOT = Path(COMFYUI_ROOT / "models")

# create persistent storage
vol = modal.Volume.from_name("hf-hub-cache", create_if_missing=True, version=2)

# construct images and install deps/custom nodes
image = (
    modal.Image.debian_slim(python_version="3.13")
    .add_local_python_source("models", "plugins", copy=True)
    .run_commands("apt-get update")
    .apt_install("git", "git-lfs", "libgl1-mesa-dev", "libglib2.0-0", "aria2", "ffmpeg") #rav1e
    .uv_pip_install("pip", "uv", "aiohttp", "fastapi", "websockets", "comfy-cli", "comfyui-manager>=4.1b1", "setuptools~=81.0", "gradio>=4", "kernels~=0.12.0", extra_options="--upgrade")
    .pip_install_from_requirements(str(root_dir / "requirements_comfy.txt")) # uv=True
    # Since nunchaku doesn't have pre-built wheels for pytorch stable v2.11, let's use v2.10
    .uv_pip_install("torch~=2.10.0", "torchao~=0.16.0", "torchvision~=0.25.0", "torchaudio~=2.10.0", "torchcodec", extra_options="--upgrade", index_url="https://download.pytorch.org/whl/cu130") # xformers
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
    global image
    
    # prepare base directory
    print(f"Testing2 Global Image: {image}")
    extra_file_path = Path(__file__).parent / "extra_model_paths.yaml"
    Path(base_dir).mkdir(parents=True, exist_ok=True)
    Path(input_dir).mkdir(parents=True, exist_ok=True)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    Path(str(user_dir / "default/workflows")).mkdir(parents=True, exist_ok=True)
    
    #subprocess.run(['rsync', '-a', '/root/comfy/ComfyUI/', '/cache/ComfyUI/'], volumes={"/cache": vol})
    if extra_file_path.exists():
        image = image.add_local_file(
            extra_file_path, 
            str(COMFYUI_ROOT / "extra_model_paths.yaml"), 
            copy=True
        )
    else:
        print(f"Extra Model Paths file ({extra_file_path}) Not Found!")

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


def install_missing_deps():
    import torch
    full_pytorch_version = torch.__version__
    pytorch_version_number = ".".join(full_pytorch_version.split(" ")[0].split(".")[:2])
    print(f"PyTorch Ver = {pytorch_version_number}")
    
    global image
    print(f"Testing4 Global Image: {image}")
    image = image.uv_pip_install("cupy-cuda13x", "this_should_fail")
    #image = image.run_commands("pip install sageattention==2.2.0 --no-build-isolation --extra-index-url https://comfy-org.github.io/wheels; exit 1")
    #image = image.pip_install("sageattention==2.*", extra_options="--no-build-isolation --extra-index-url https://comfy-org.github.io/wheels") #sageattn3 
    #raise ValueError("Break! Testing purpose.")
    #image = image.uv_pip_install("flash-attn-3", extra_options="--no-build-isolation --extra-index-url https://download.pytorch.org/whl/cu130") #flash-attn-4[cu13]
    #image = image.uv_pip_install(f"https://github.com/nunchaku-tech/nunchaku/releases/download/v1.2.1/nunchaku-1.2.1+cu13.0torch{pytorch_version_number}-cp313-cp313-linux_x86_64.whl")
    
    image = image.run_commands("uv pip show cupy-cuda13x sageattention flash-attn-3 nunchaku; exit 1")
    print("Done install missing dependencies.")


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

# download models
print(f"Testing1 Global Image: {image}")
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
        #download_external_plugin(plugin["url"], plugin["branch"], plugin["install"])
        folder_name = plugin['url'].rstrip('/').rsplit('/', 1)[-1].removesuffix('.git')
        image = image.run_commands(f"cd {nodes_dir} && git clone --recurse-submodules --single-branch --branch {plugin['branch']} {plugin['url']} && cd -", volumes={"/cache": vol}) # ; exit 0 
        #image = image.run_commands(f"cd {nodes_dir}/{folder_name} && git pull && git submodule update --init --recursive && cd -", volumes={"/cache": vol})
        plugin_reqs = plugin.get('requirements') # TODO: allows more than one requirements files (comma/space separated)
        if plugin_reqs and plugin_reqs.strip():
            plugin_reqs = plugin_reqs.strip()
            if plugin_reqs.endswith(".toml"):
                image = image.pip_install_from_pyproject(f"{nodes_dir}/{folder_name}/{plugin_reqs}") # uv_sync
            else:
                image = image.uv_pip_install(f"{nodes_dir}/{folder_name}/{plugin_reqs}", extra_options="-r") #, uv=True # pip_install_from_requirements #, gpu=GPU_MODEL

        plugin_install = plugin.get('install')
        if plugin_install and plugin_install.strip():
            plugin_install = plugin_install.strip()
            if plugin_install.endswith(".py"):
                image = image.run_commands(f"cd {nodes_dir}/{folder_name} && python {plugin_install} && cd -", volumes={"/cache": vol}) #, gpu=GPU_MODEL
            else:
                print(f"Unsupported installation script: {plugin_install}")
        
        plugin_deps = plugin.get('dependencies')
        if plugin_deps and plugin_deps.strip():
            plugin_deps = plugin_deps.strip()
            image = image.uv_pip_install(plugin_deps) #, gpu=GPU_MODEL
 
# install missing dependencies or override with a compatible version
print(f"Testing3 Global Image: {image}")
image = image.run_function(
    install_missing_deps, 
    volumes={"/cache": vol},
    #gpu=GPU_MODEL
)

# Disable ultralytics' Anonymized Google Analytics
image = image.run_commands("yolo settings sync=False")

# copy custom nodes to base_dir
#import shutil
#print("Copying custom_nodes structure...")
#shutil.copytree(COMFYUI_ROOT / "custom_nodes", base_dir / "custom_nodes", symlinks=True, ignore_dangling_symlinks=True, dirs_exist_ok=True)

def wait_for_port(port: int, timeout: int = 60):
    import time
    import socket
    
    """Block until the port is accepting connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return  # port is open — ComfyUI is ready
        except OSError:
            time.sleep(0.5)
    raise TimeoutError(f"ComfyUI never became ready on port {port}")


from fastapi import FastAPI, Request, Response, WebSocket
from fastapi.responses import JSONResponse
import httpx
import websockets

app = modal.App(name="modal-comfyui", image=image)
web_app = FastAPI()
shared_dict = modal.Dict.from_name(app.name, create_if_missing=True)


uiport = 8188
gpuport = uiport + 1

async def get_remote_url(class_name: str) -> str:
    remote_cls = modal.Cls.from_name(app.name, class_name)
    url = await remote_cls().web.get_web_url.aio()
    return url
    
@web_app.get("/prompt")
@web_app.get("/api/prompt")
async def prompt_get():
    url = await get_remote_url("ComfyGPU")
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.get(f"{url}/prompt")
    return JSONResponse(resp.json())
    
@web_app.post("/prompt")
@web_app.post("/api/prompt")
async def prompt_post(request: Request):
    body = await request.json()
    
    url = await get_remote_url("ComfyGPU")

    # Your custom logic — transform, validate, log, route
    # ...

    # Forward to remote ComfyUI
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{url}/prompt",
            json=body,
            timeout=120,
        )
    return JSONResponse(resp.json())

@web_app.get("/queue")
@web_app.get("/api/queue")
async def queue_get():
    url = await get_remote_url("ComfyGPU")
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.get(f"{url}/queue")
    return JSONResponse(resp.json())

@web_app.post("/queue")
@web_app.post("/api/queue")
async def queue_post(request: Request):
    body = await request.json()
    url = await get_remote_url("ComfyGPU")
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{url}/queue",
            json=body,
            timeout=120,
        )
    return JSONResponse(resp.json())
    
@web_app.post("/interrupt")
@web_app.post("/api/interrupt")
async def interrupt(request: Request):
    body = await request.json()
    url = await get_remote_url("ComfyGPU")
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{url}/interrupt",
            json=body,
            timeout=120,
        )
    return JSONResponse(resp.json())

@web_app.websocket("/ws")
async def proxy_websocket(websocket: WebSocket):
    await websocket.accept()

    # Use active GPU instance when available, otherwise use localhost (CPU)
    uri = f"ws://127.0.0.1:{uiport}/ws"
    active_count = await shared_dict.get.aio("active", 0)
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

    print(f"CONNECTing to {uri}")
    async with websockets.connect(
        uri,
        open_timeout=30,        # handshake timeout (seconds)
        close_timeout=10,       # graceful close timeout
        ping_interval=20,       # send pings every N seconds
        ping_timeout=20,        # wait N seconds for pong before closing
    ) as comfy_ws:
        async def client_to_comfy():
            try:
                async for message in websocket.iter_bytes():
                    await comfy_ws.send(message)
            except Exception as e:
                pass
            finally:
                active_count = await shared_dict.get.aio("active", 0)
                if comfy_ws.uri.startswith("ws://127.0.0.1") and active_count>0:
                    await comfy_ws.close()  # ensure cleanup 

        async def comfy_to_client():
            try:
                async for message in comfy_ws:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)
            except Exception as e:
                pass

        async def watch_active():
            while True:
                active_count = await shared_dict.get.aio("active", 0)
                if comfy_ws.uri.startswith("ws://127.0.0.1") and active_count>0:
                    await comfy_ws.close()
                    break
                await asyncio.sleep(1)  # poll every second

        import asyncio
        # Cancel both tasks when either side closes
        tasks = await asyncio.gather(
            client_to_comfy(),
            comfy_to_client(),
            watch_active(),
            return_exceptions=True
        )

# Proxy everything else to local ComfyUI
@web_app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "TRACE"])
async def proxy(path: str, request: Request):
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.request(
            method=request.method,
            url=f"http://127.0.0.1:{uiport}/{path}",
            content=await request.body(),
            headers=dict(request.headers),
        )
    # Return raw bytes with the original content-type
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type"),
    )
    

@app.cls(
    max_containers=1,
    gpu=GPU_MODEL,
    volumes={"/cache": vol},
    scaledown_window=60,  # idle 1 minutes to shutdown
    enable_memory_snapshot=True,
    experimental_options={"enable_gpu_snapshot": True},
)
@modal.concurrent(max_inputs=10)
class ComfyGPU:
    @modal.enter(snap=True)
    def start_checkpoint(self):
        self.proc = subprocess.Popen(
            f"comfy manager enable-legacy-gui && comfy launch --background -- --listen 0.0.0.0 --port {gpuport} --enable-cors-header '*' --user-directory {user_dir} --output-directory {output_dir} --input-directory {input_dir} ", shell=True # --base-directory {base_dir} --extra-model-paths-config {COMFYUI_ROOT}/extra_model_paths.yaml 
        )
        # Block here — snapshot is taken only after this returns
        wait_for_port(gpuport, timeout=120)

    @modal.enter(snap=False)
    def start_restore(self):
        if shared_dict.get("active"):
            shared_dict["active"] += 1
        else:
            shared_dict["active"] = 1
        print("App Restored!")
        # On restore, sockets may need to be rebound
        #self.proc = subprocess.Popen(
        #    f"comfy manager enable-legacy-gui && comfy launch --background -- --listen 0.0.0.0 --port {gpuport} --user-directory {user_dir} --output-directory {output_dir} --input-directory {input_dir} ", shell=True # --base-directory {base_dir} --extra-model-paths-config {COMFYUI_ROOT}/extra_model_paths.yaml 
        #)
        #wait_for_port(gpuport, timeout=120)
    
    @modal.web_server(gpuport, startup_timeout=60)
    def web(self):
        print("App Ready!")
    
    @modal.exit()
    def cleanup(self):
        if shared_dict.get("active") and shared_dict["active"]>0:
            shared_dict["active"] -= 1
        else:
            shared_dict["active"] = 0
        self.proc.terminate()
        print("App CleanUp!")

@app.cls(
    max_containers=1,
    #cpu=2.0, memory=4096,
    volumes={"/cache": vol},
    scaledown_window=60,  # idle 1 minutes to shutdown
    enable_memory_snapshot=True,
    experimental_options={"enable_gpu_snapshot": True},
)
@modal.concurrent(max_inputs=10)
class ComfyCPU:
    @modal.enter(snap=True)
    def start_checkpoint(self):
        self.proc = subprocess.Popen(
            f"comfy manager enable-legacy-gui && comfy launch --background -- --listen 0.0.0.0 --port {uiport} --enable-cors-header '*' --user-directory {user_dir} --output-directory {output_dir} --input-directory {input_dir} --cpu ", shell=True # --base-directory {base_dir} --extra-model-paths-config {COMFYUI_ROOT}/extra_model_paths.yaml
        )
        # Block here — snapshot is taken only after this returns
        wait_for_port(uiport, timeout=120)

    @modal.enter(snap=False)
    def start_restore(self):
        print("App Restored!")
        # On restore, sockets may need to be rebound
        #self.proc = subprocess.Popen(
        #    f"comfy manager enable-legacy-gui && comfy launch --background -- --listen 0.0.0.0 --port {uiport} --user-directory {user_dir} --output-directory {output_dir} --input-directory {input_dir} --cpu ", shell=True # --base-directory {base_dir} --extra-model-paths-config {COMFYUI_ROOT}/extra_model_paths.yaml 
        #)
        #wait_for_port(uiport, timeout=120)
    
    #@modal.web_server(uiport, startup_timeout=60)
    #def web(self):
    #    print("App Ready!")

    @modal.asgi_app()
    def api(self):
        print("App Ready!")
        return web_app
    
    @modal.exit()
    def cleanup(self):
        self.proc.terminate()
        print("App CleanUp!")
