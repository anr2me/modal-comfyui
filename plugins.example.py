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
    # External downloads (via git).
    # {
    #     "url": "URL",
    #     "branch": "BRANCH",
    #     "requirements": "requirements.txt", # or "pyproject.toml"
    #     "install": "install.py", 
    # },
    {
        "url": "https://github.com/Comfy-Org/ComfyUI-Manager.git", 
        "branch": "main",
        "requirements": "requirements.txt",
        "install": "",
    },
    {
        "url": "https://github.com/Lightricks/ComfyUI-LTXVideo.git", 
        "branch": "master",
        "requirements": "requirements.txt",
        "install": "",
    },
]
