from pathlib import Path

ALLOWED_MODEL_DIRS = {
    "checkpoints": Path("models/checkpoints"),
    "diffusion_models": Path("models/diffusion_models"),
    "unet": Path("models/unet"),
    "loras": Path("models/loras"),
    "vae": Path("models/vae"),
    "text_encoders": Path("models/text_encoders"),
    "clip": Path("models/clip"),
    "clip_vision": Path("models/clip_vision"),
    "controlnet": Path("models/controlnet"),
    "embeddings": Path("models/embeddings"),
    "upscale_models": Path("models/upscale_models"),
    "style_models": Path("models/style_models"),
    "audio_encoders": Path("models/audio_encoders"),
    "diffusers": Path("models/diffusers"),
    "LLM": Path("models/LLM"),
}