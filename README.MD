# ComfyUI Model Installer

A ComfyUI plugin that scans the current workflow, detects required model assets, shows which ones are missing, and installs them automatically into the correct `models/` folder.

It is designed to work like a lightweight workflow-aware asset manager for **Windows, Linux, and macOS**.

---

## Features

- Scan the current workflow
- Detect required assets from:
  - `properties.models`
  - `MarkdownNote` fallback (`Model Links`)
- Show installed vs missing assets
- Install missing models automatically
- Place files into the correct ComfyUI model folders
- Show download progress
- Show total size when available
- Display plugin version
- Check for plugin updates
- Update plugin from `origin/main` when installed as a git repo

---

## Supported asset folders

The plugin currently supports these ComfyUI model directories:

- `models/checkpoints`
- `models/diffusion_models`
- `models/unet`
- `models/loras`
- `models/vae`
- `models/text_encoders`
- `models/clip`
- `models/clip_vision`
- `models/controlnet`
- `models/embeddings`
- `models/upscale_models`
- `models/style_models`
- `models/audio_encoders`
- `models/diffusers`
- `models/LLM`

---

## How it works

The plugin scans the currently loaded workflow and tries to find model metadata.

### Priority order

1. `node.properties.models`
2. `MarkdownNote` fallback, such as notes named:
   - `Model Links`
   - `Required Models`
   - `Required Assets`

### Expected metadata format

The preferred format is:

```json
{
  "properties": {
    "models": [
      {
        "name": "wan_2.1_vae.safetensors",
        "url": "https://huggingface.co/...",
        "directory": "vae"
      }
    ]
  }
}