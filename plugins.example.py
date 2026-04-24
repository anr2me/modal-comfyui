comfy_plugins = [
    # put comfyui custom node id here
    # IMPORTANT: node id from comfyui registry (Not node name)
    "comfyui-kjnodes",
    "ComfyUI-WanVideoWrapper",
]

comfy_plugins_ext = [
    # External downloads (via git).
    # {
    #     "url": "URL",
    #     "branch": "BRANCH",
    #     "install": "requirements.txt", # or "install.py"
    # },
    {
        "url": "https://github.com/Comfy-Org/ComfyUI-Manager.git", 
        "branch": "main",
        "install": "requirements.txt",
    },
    {
        "url": "https://github.com/Lightricks/ComfyUI-LTXVideo.git", 
        "branch": "master",
        "install": "requirements.txt",
    },
]
