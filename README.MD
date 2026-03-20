# ComfyUI Model Installer

A ComfyUI custom plugin that scans workflows, detects required models, resolves missing metadata, and installs missing assets directly into the correct ComfyUI model folders.

It is designed to behave like a lightweight model-aware installer for shared workflows, with automatic detection, optional manual candidate resolution, download progress tracking, and plugin self-update support.

---

## Features

- Scan the current ComfyUI workflow for required assets
- Detect assets from:
  - `properties.models`
  - `MarkdownNote` / `Model Links`
  - inferred loader nodes such as:
    - `CheckpointLoaderSimple`
    - `LoraLoader`
    - `VAELoader`
    - `CLIPLoader`
    - `UNETLoader`
    - `ControlNetLoader`
    - `UpscaleModelLoader`
    - and more
- Resolve missing metadata using:
  - local resolver cache
  - optional `known_models.json`
  - Hugging Face search fallback
- Show candidate matches for ambiguous assets
- Manually choose a candidate from the UI
- Install:
  - selected models
  - all resolved missing models
- Live per-row download progress:
  - total size
  - downloaded bytes
  - progress bar
- Job log with current file progress:
  - example: `Downloading 3 GB of 30 GB (10%)`
- Cancel the current job
- Check for plugin updates
- Update plugin via `git pull origin main`

---

## Current Status

This plugin currently supports:

- automatic workflow scanning
- model metadata extraction
- Hugging Face-based asset resolution
- direct asset installation into the correct ComfyUI folders
- progress monitoring and cancellation
- manual candidate selection for unresolved or ambiguous assets

At the moment, the resolver is focused on **Hugging Face** plus local cache/catalog matching.

---

## Installation

Clone this repository into your ComfyUI `custom_nodes` folder:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/YOUR_USERNAME/ComfyUI-Model-Installer.git
```

Then restart ComfyUI.

---

## Requirements

This plugin expects a working ComfyUI installation and Python environment.

Python dependencies used by the backend include:

- `requests`
- `huggingface_hub`

If needed, install them manually in your ComfyUI Python environment:

```bash
pip install requests huggingface_hub
```

---

## Supported Asset Sources

### 1. `properties.models`

If a workflow node includes structured model metadata, the plugin will use that directly.

Example:

```json
{
  "properties": {
    "models": [
      {
        "name": "example_model.safetensors",
        "url": "https://huggingface.co/org/repo/resolve/main/example_model.safetensors",
        "directory": "checkpoints"
      }
    ]
  }
}
```

### 2. `MarkdownNote` / Model Links

If the workflow includes a note listing model URLs, the plugin can parse links and infer target directories.

### 3. Inferred Loader Nodes

If the workflow does not include full metadata, the plugin can infer missing assets from loader nodes.

Examples:

- `CheckpointLoaderSimple` → `checkpoints`
- `LoraLoader` → `loras`
- `VAELoader` → `vae`
- `CLIPLoader` → `text_encoders`
- `UNETLoader` → `diffusion_models`

These inferred assets are then sent through the resolver pipeline.

---

## Resolver Pipeline

When an asset is missing its URL, the plugin tries to resolve it using this order:

1. local resolver cache
2. `known_models.json` (optional curated catalog)
3. Hugging Face search
4. manual candidate confirmation if needed

### Resolver statuses

Assets can appear as:

- `resolved`
- `ambiguous`
- `unresolved`
- `needs resolution`
- `provided`
- `resolved_from_cache`
- `resolved_from_catalog`
- `resolved_auto`
- `resolved_manual`

---

## UI Overview

The plugin adds a **Model Installer** button to the ComfyUI top bar when possible, with fallback to the classic left menu.

### Main actions

- **Scan Workflow**  
  Scan the current graph and detect required assets

- **Install Selected**  
  Install only the selected resolved missing assets

- **Install Missing**  
  Install all resolved missing assets currently detected

- **Select All Missing**  
  Automatically select all installable missing assets

- **Refresh**  
  Refresh plugin version info and rescan

- **Check Plugin Update**  
  Check whether a newer git version is available

- **Cancel Current Job**  
  Request cancellation of the current installation job

- **Only Missing**  
  Filter the table to show only missing/downloading assets

---

## Resolve Candidates Modal

If an asset is ambiguous or unresolved, the UI shows a **Resolve** button.

Clicking it opens a modal that can:

- show cached candidates
- refresh candidates from the backend
- let you manually confirm one candidate

Once confirmed, the resolution is stored locally in the resolver cache and the asset becomes installable.

---

## Download Progress

During installation, the plugin tracks progress both:

### In the table

Each row shows:

- size
- downloaded bytes
- percentage
- progress bar

### In the log

The log shows the current job progress, for example:

```text
Job running | Progress: 0/1 | Current: ponyRealism_v21MainVAE.safetensors | Downloading 3 GB of 30 GB (10%)
```

---

## Plugin Update Support

The plugin can check whether the git repository is outdated and update itself.

### Supported actions

- check local vs remote commit
- `git fetch origin`
- `git pull origin main`

### Notes

- This only works if the plugin folder is a valid git repository
- After update, you must restart ComfyUI

---

## File Structure

Typical structure:

```text
ComfyUI-Model-Installer/
├── __init__.py
├── routes.py
├── parser.py
├── resolver.py
├── resolver_cache.py
├── installer.py
├── security.py
├── utils.py
├── models_map.py
├── known_models.json          # optional
├── resolver_cache.json        # auto-generated
├── js/
│   └── model_installer.js
├── README.md
└── .gitignore
```

---

## Important Backend Files

### `parser.py`

Responsible for extracting asset requirements from the workflow.

Includes support for:

- structured model metadata
- markdown notes
- inferred loader-based assets

### `resolver.py`

Responsible for resolving assets that do not have full metadata.

Includes:

- cache lookup
- catalog lookup
- Hugging Face search
- candidate scoring
- auto-resolution and manual confirmation support

### `resolver_cache.py`

Stores confirmed or auto-resolved matches locally for future scans.

### `installer.py`

Handles the actual download job lifecycle:

- queue creation
- status updates
- progress tracking
- cancellation
- final installation into the correct model folder

### `routes.py`

Exposes backend API endpoints to the frontend.

---

## API Endpoints

### Health / Version

- `GET /model-installer/ping`
- `GET /model-installer/version`

### Workflow scan

- `POST /model-installer/scan`
- `POST /model-installer/scan-resolve`

### Candidate resolution

- `POST /model-installer/resolve/candidates`
- `POST /model-installer/resolve/confirm`

### Download / status

- `POST /model-installer/download`
- `GET /model-installer/status`
- `POST /model-installer/cancel`

### Plugin update

- `GET /model-installer/update/check`
- `POST /model-installer/update/plugin`

---

## Supported Model Directories

The plugin maps workflow assets into known ComfyUI folders, such as:

- `checkpoints`
- `loras`
- `vae`
- `text_encoders`
- `clip`
- `clip_vision`
- `controlnet`
- `diffusion_models`
- `unet`
- `upscale_models`
- `style_models`
- `embeddings`
- `audio_encoders`
- `diffusers`
- `LLM`

The exact mapping is controlled by `models_map.py`.

---

## Resolver Cache

Confirmed and auto-resolved candidates are stored locally in:

```text
resolver_cache.json
```

This helps future scans resolve faster and avoids repeating manual choices.

Example entry:

```json
{
  "ponyrealism_v2.1_vae|checkpoints": {
    "repo_id": "some-author/some-repo",
    "filename": "ponyRealism_v21MainVAE.safetensors",
    "revision": "main",
    "url": "https://huggingface.co/some-author/some-repo/resolve/main/ponyRealism_v21MainVAE.safetensors",
    "confidence": 97
  }
}
```

---

## Optional `known_models.json`

You can provide a curated catalog of known models to improve resolution quality.

Example:

```json
{
  "pony_realism_main_vae": {
    "repo_id": "author/repo",
    "filename": "ponyRealism_v21MainVAE.safetensors",
    "revision": "main",
    "directory": "checkpoints",
    "aliases": [
      "PonyRealism_v2.1_VAE",
      "pony realism v2",
      "ponyrealism"
    ]
  }
}
```

This file is optional. If it does not exist, the plugin will continue using cache + Hugging Face search.

---

## Debugging

The resolver includes debug logs in the backend console.

Examples:

```text
[CMI resolver] resolve_assets start total=2
[CMI resolver] HF search start asset=PonyRealism_v2.1_VAE directory=checkpoints queries=[...]
[CMI resolver] candidate score=72 repo=author/repo file=model.safetensors reasons=[...]
```

These logs help diagnose:

- failed Hugging Face search
- incompatible `huggingface_hub` versions
- low-score candidate filtering
- missing catalog entries

---

## Compatibility Notes

### Hugging Face API compatibility

Different versions of `huggingface_hub` may expose different `HfApi.list_models(...)` signatures.

The resolver includes compatibility fallbacks so it can work with different installed versions.

### Git update support

If the plugin folder is not a git repository, self-update features are disabled.

### Workflow compatibility

The plugin works best when workflows include either:

- structured `properties.models`
- readable model links
- standard ComfyUI loader nodes

Highly customized or obfuscated workflows may require manual resolution.

---

## Security Notes

The plugin sanitizes filenames and restricts installation to allowed ComfyUI model directories.

This helps prevent:

- invalid relative paths
- unsafe filenames
- writing outside expected model folders

---

## Troubleshooting

### No candidates found

Possible reasons:

- model name is too ambiguous
- the model is not available on Hugging Face
- your installed `huggingface_hub` version behaves differently
- the asset needs a curated `known_models.json` entry

### Plugin does not show in top bar

If the modern ComfyUI top bar API is unavailable, the plugin falls back to the left-side menu button.

---

## License

```text
MIT License
```

---

## Credits

Built for ComfyUI workflow portability and model-aware installation workflows.
