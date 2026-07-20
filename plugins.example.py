comfy_plugins = [
    # put comfyui custom node id here
    # IMPORTANT: node id from comfyui registry (Not node name)
    "comfyui-kjnodes",
    "ComfyUI-WanVideoWrapper",
    "rgthree-comfy",
    "comfyui-easy-use",
    "comfyui-videohelpersuite",
    "comfyui-impact-pack",
    "comfyui-impact-subpack",
    "ComfyUI-Crystools",
    "raylight",
]

comfy_plugins_ext = [
    # External custom nodes installed directly from git.
    # {
    #     "url": "https://github.com/owner/repo.git",
    #     "branch": "main",  # optional; omit to use the repo's default branch
    #     "requirements": ["requirements.txt", "pyproject.toml"],  # optional req files
    #     "install": "install.py",  # optional install script (.py)
    #     "ext_deps": ["numpy<2", "setuptools<=81"],  # optional extra pip packages
    # },
    {
        "url": "https://github.com/Echoflare/ComfyUI-Reverse-Proxy-Fix.git", 
    },
    {
        "url": "https://github.com/Comfy-Org/ComfyUI-Manager.git", 
        "branch": "main",
        "requirements": ["pyproject.toml", "requirements.txt"],
    },
    {
        "url": "https://github.com/Lightricks/ComfyUI-LTXVideo.git", 
        "branch": "master",
        "requirements": ["requirements.txt"],
        "ext_deps": ["kornia~=0.6.12"],
    },
]
