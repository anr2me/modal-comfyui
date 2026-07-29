# Models to download during image build.
#
# `model_dir` accepts two styles:
#
#   1. Relative path (recommended for standard ComfyUI model folders):
#        "checkpoints"       -> /root/comfy/ComfyUI/models/checkpoints
#        "loras/wan22"       -> /root/comfy/ComfyUI/models/loras/wan22
#
#   2. Absolute path (use when the target is outside ComfyUI/models/,
#      e.g. a custom node's own model directory):
#        "/root/comfy/ComfyUI/custom_nodes/ComfyUI-ReActor/models/insightface"
#
# Common subdirectories under ComfyUI/models/:
#   checkpoints, diffusion_models, vae, loras, text_encoders,
#   clip_vision, controlnet, upscale_models, embeddings.

models = [
    # Hugging Face downloads (via huggingface_hub).
    # {
    #     "repo_id": "HF_REPO_ID",
    #     "filename": "FILENAME",
    #     "model_dir": "checkpoints",
    # },
    {
        "repo_id": "Comfy-Org/ace_step_1.5_ComfyUI_files",
        "filename": "split_files/diffusion_models/acestep_v1.5_xl_turbo_bf16.safetensors",
        "model_dir": "diffusion_models",
    },
    {
        "repo_id": "Comfy-Org/ace_step_1.5_ComfyUI_files",
        "filename": "split_files/text_encoders/qwen_4b_ace15.safetensors",
        "model_dir": "text_encoders",
    },
    {
        "repo_id": "Comfy-Org/ace_step_1.5_ComfyUI_files",
        "filename": "split_files/text_encoders/qwen_0.6b_ace15.safetensors",
        "model_dir": "text_encoders",
    },
    {
        "repo_id": "Comfy-Org/ace_step_1.5_ComfyUI_files",
        "filename": "split_files/vae/ace_1.5_vae.safetensors",
        "model_dir": "vae",
    },
    
    {
        "repo_id": "Comfy-Org/ERNIE-Image",
        "filename": "diffusion_models/ernie-image-turbo.safetensors",
        "model_dir": "diffusion_models",
    },
    {
        "repo_id": "Comfy-Org/ERNIE-Image",
        "filename": "text_encoders/ministral-3-3b.safetensors",
        "model_dir": "text_encoders",
    },
    {
        "repo_id": "Comfy-Org/ERNIE-Image",
        "filename": "text_encoders/ernie-image-prompt-enhancer.safetensors",
        "model_dir": "text_encoders",
    },
    {
        "repo_id": "Comfy-Org/ERNIE-Image",
        "filename": "vae/flux2-vae.safetensors",
        "model_dir": "vae",
    },

    {
        "repo_id": "Comfy-Org/Bernini-R",
        "filename": "diffusion_models/wan2.1_bernini_1.3B_fp16.safetensors", 
        "model_dir": "diffusion_models",
    },
    {
        "repo_id": "Comfy-Org/Wan_2.1_ComfyUI_repackaged",
        "filename": "split_files/diffusion_models/wan2.1_vace_1.3B_fp16.safetensors",
        "model_dir": "diffusion_models",
    },
    {
        "repo_id": "Comfy-Org/Wan_2.1_ComfyUI_repackaged",
        "filename": "split_files/clip_vision/clip_vision_h.safetensors",
        "model_dir": "clip_vision",
    },
    {
        "repo_id": "Comfy-Org/Wan_2.1_ComfyUI_repackaged",
        "filename": "split_files/text_encoders/umt5_xxl_fp16.safetensors",
        "model_dir": "text_encoders",
    },
    {
        "repo_id": "Comfy-Org/Wan_2.1_ComfyUI_repackaged",
        "filename": "split_files/vae/wan_2.1_vae.safetensors",
        "model_dir": "vae",
    },
]

models_ext = [
    # External downloads (
]

models_ext = [
    # External downloads (via aria2c). Use for civitai, direct URLs, etc.
    # {
    #     "url": "URL",
    #     "filename": "FILENAME",
    #     "model_dir": "loras",
    # },
]
