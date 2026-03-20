from pathlib import PurePath
from urllib.parse import urlparse, unquote

ALLOWED_DOMAINS = {
    "huggingface.co",
    "hf.co",
    "civitai.com",
    "github.com",
    "objects.githubusercontent.com",
    "cdn-lfs.huggingface.co",
}

ALLOWED_EXTENSIONS = {
    ".safetensors",
    ".ckpt",
    ".pt",
    ".pth",
    ".bin",
    ".json",
    ".gguf",
}

INVALID_FILENAME_CHARS = '<>:"/\\|?*'


def is_allowed_domain(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
        return any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS)
    except Exception:
        return False


def sanitize_filename(filename: str) -> str:
    clean = filename.strip().replace("\x00", "")
    clean = unquote(clean)
    for ch in INVALID_FILENAME_CHARS:
        clean = clean.replace(ch, "_")
    clean = PurePath(clean).name
    clean = clean.strip(" .")
    return clean


def is_allowed_extension(filename: str) -> bool:
    lower = filename.lower()
    return any(lower.endswith(ext) for ext in ALLOWED_EXTENSIONS)


def safe_rel_model_dir(directory: str) -> str:
    """
    Basic sanitizer for folder key names, not filesystem paths.
    """
    if not directory:
        return ""
    directory = directory.strip().replace("\\", "/").strip("/")
    directory = directory.replace("../", "").replace("..\\", "")
    return directory