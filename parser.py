import re
from urllib.parse import urlparse, unquote
from .security import sanitize_filename, safe_rel_model_dir
from .models_map import ALLOWED_MODEL_DIRS


MODEL_LINKS_TITLE_HINTS = {
    "model links",
    "models",
    "required models",
    "required assets",
}


DIRECTORY_ALIASES = {
    "checkpoint": "checkpoints",
    "checkpoints": "checkpoints",
    "ckpt": "checkpoints",
    "unet": "unet",
    "diffusion_model": "diffusion_models",
    "diffusion_models": "diffusion_models",
    "diffusion model": "diffusion_models",
    "lora": "loras",
    "loras": "loras",
    "vae": "vae",
    "text_encoder": "text_encoders",
    "text encoders": "text_encoders",
    "text_encoders": "text_encoders",
    "clip": "clip",
    "clip_vision": "clip_vision",
    "controlnet": "controlnet",
    "embedding": "embeddings",
    "embeddings": "embeddings",
    "upscaler": "upscale_models",
    "upscale_models": "upscale_models",
    "style_models": "style_models",
    "audio_encoders": "audio_encoders",
    "diffusers": "diffusers",
    "llm": "LLM",
}


INFERRED_LOADER_MAP = {
    "CheckpointLoaderSimple": "checkpoints",
    "CheckpointLoader": "checkpoints",
    "LoraLoader": "loras",
    "LoraLoaderModelOnly": "loras",
    "VAELoader": "vae",
    "CLIPLoader": "text_encoders",
    "DualCLIPLoader": "text_encoders",
    "TripleCLIPLoader": "text_encoders",
    "UNETLoader": "diffusion_models",
    "DiffusionModelLoader": "diffusion_models",
    "ControlNetLoader": "controlnet",
    "UpscaleModelLoader": "upscale_models",
    "StyleModelLoader": "style_models",
    "CLIPVisionLoader": "clip_vision",
}


def normalize_directory(directory: str) -> str:
    if not directory:
        return ""
    directory = safe_rel_model_dir(str(directory))
    directory = directory.replace("models/", "").replace("models\\", "")
    directory = directory.strip("/").strip()
    directory_lower = directory.lower()
    normalized = DIRECTORY_ALIASES.get(directory_lower, directory)
    return normalized if normalized in ALLOWED_MODEL_DIRS else ""


def filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    name = unquote(parsed.path.split("/")[-1]) if parsed.path else ""
    return sanitize_filename(name)


def asset_key(directory: str, name: str) -> str:
    return f"{directory}/{name}".lower()


def asset_priority(asset: dict) -> int:
    source = asset.get("source", "")
    if source == "properties.models":
        return 100
    if source == "markdown":
        return 80
    if source == "inferred_loader":
        return 10
    return 0


def parse_properties_models(workflow: dict) -> list[dict]:
    assets = []
    nodes = workflow.get("nodes", []) or []

    for node in nodes:
        if not isinstance(node, dict):
            continue

        props = node.get("properties", {}) or {}
        if not isinstance(props, dict):
            continue

        models = props.get("models", []) or []
        if not isinstance(models, list):
            continue

        for model in models:
            if not isinstance(model, dict):
                continue

            name = sanitize_filename(model.get("name", "") or "")
            url = (model.get("url", "") or "").strip()
            directory = normalize_directory(model.get("directory", "") or "")

            if not url or not directory:
                continue

            if not name:
                name = filename_from_url(url)

            if not name:
                continue

            assets.append(
                {
                    "name": name,
                    "url": url,
                    "directory": directory,
                    "source": "properties.models",
                    "node_id": node.get("id"),
                    "node_type": node.get("type"),
                    "title": node.get("title", ""),
                }
            )

    return assets


def looks_like_model_links_note(node: dict) -> bool:
    if not isinstance(node, dict):
        return False

    if str(node.get("type", "")).lower() != "markdownnote":
        return False

    title = str(node.get("title", "") or "").strip().lower()
    if title in MODEL_LINKS_TITLE_HINTS:
        return True

    widgets_values = node.get("widgets_values", [])
    if not isinstance(widgets_values, list) or not widgets_values:
        return False

    text = "\n".join(str(x) for x in widgets_values if x is not None).lower()
    return "huggingface.co" in text or "civitai.com" in text or "models/" in text


def detect_directory_from_line(line_lower: str, current_pending: str = "") -> str:
    pending_directory = current_pending or ""

    for folder in ALLOWED_MODEL_DIRS.keys():
        if folder.lower() in line_lower:
            pending_directory = folder
            break

    if "models/" in line_lower:
        parts = line_lower.split("models/", 1)
        if len(parts) > 1:
            after = parts[1].strip()
            if after:
                token_parts = after.split()
                if token_parts:
                    token = token_parts[0]
                    token = token.split(":")[0].split(")")[0].split(",")[0].strip("/ ")
                    normalized = normalize_directory(token)
                    if normalized:
                        pending_directory = normalized

    return normalize_directory(pending_directory)


def parse_markdown_assets(workflow: dict) -> list[dict]:
    assets = []
    nodes = workflow.get("nodes", []) or []

    url_regex = re.compile(r"https?://[^\s)>\]]+")
    markdown_link_regex = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")

    pending_directory = ""

    for node in nodes:
        if not looks_like_model_links_note(node):
            continue

        widgets_values = node.get("widgets_values", [])
        if not isinstance(widgets_values, list):
            continue

        text = "\n".join(str(x) for x in widgets_values if x is not None)
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        for line in lines:
            line_lower = line.lower()
            pending_directory = detect_directory_from_line(line_lower, pending_directory)

            for match in markdown_link_regex.finditer(line):
                name = sanitize_filename(match.group(1) or "")
                url = (match.group(2) or "").strip()
                directory = pending_directory or ""

                if not name:
                    name = filename_from_url(url)

                if name and url and directory:
                    assets.append(
                        {
                            "name": name,
                            "url": url,
                            "directory": directory,
                            "source": "markdown",
                            "node_id": node.get("id"),
                            "node_type": node.get("type"),
                            "title": node.get("title", ""),
                        }
                    )

            for url in url_regex.findall(line):
                name = filename_from_url(url)
                directory = detect_directory_from_line(line_lower, pending_directory)

                if name and url and directory:
                    assets.append(
                        {
                            "name": name,
                            "url": url,
                            "directory": directory,
                            "source": "markdown",
                            "node_id": node.get("id"),
                            "node_type": node.get("type"),
                            "title": node.get("title", ""),
                        }
                    )

    return assets


def parse_loader_inferred_assets(workflow: dict) -> list[dict]:
    assets = []
    nodes = workflow.get("nodes", []) or []

    for node in nodes:
        if not isinstance(node, dict):
            continue

        node_type = str(node.get("type", "") or "")
        directory = INFERRED_LOADER_MAP.get(node_type, "")
        if not directory:
            continue

        widgets_values = node.get("widgets_values", [])
        if not isinstance(widgets_values, list) or not widgets_values:
            continue

        raw_value = widgets_values[0]
        if not isinstance(raw_value, str):
            continue

        name = sanitize_filename(raw_value.strip())
        if not name:
            continue

        assets.append(
            {
                "name": name,
                "url": "",
                "directory": directory,
                "source": "inferred_loader",
                "node_id": node.get("id"),
                "node_type": node_type,
                "title": node.get("title", ""),
                "resolved": False,
                "resolver_status": "needs_resolution",
            }
        )

    return assets


def dedupe_assets(assets: list[dict]) -> list[dict]:
    deduped = {}
    for asset in assets:
        if not isinstance(asset, dict):
            continue

        directory = asset.get("directory", "")
        name = asset.get("name", "")
        if not directory or not name:
            continue

        key = asset_key(directory, name)
        if key not in deduped:
            deduped[key] = asset
            continue

        if asset_priority(asset) > asset_priority(deduped[key]):
            deduped[key] = asset

    return list(deduped.values())


def collect_assets(workflow: dict, include_inferred: bool = True) -> list[dict]:
    if not isinstance(workflow, dict):
        return []

    primary = parse_properties_models(workflow)
    fallback = parse_markdown_assets(workflow)
    inferred = parse_loader_inferred_assets(workflow) if include_inferred else []

    merged = dedupe_assets(primary + fallback + inferred)
    merged.sort(key=lambda x: (x.get("directory", ""), x.get("name", "").lower()))
    return merged