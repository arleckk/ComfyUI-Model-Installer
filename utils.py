from pathlib import Path
import shutil
import hashlib


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def move_atomic(src: Path, dst: Path) -> None:
    ensure_dir(dst.parent)
    if dst.exists():
        dst.unlink()
    shutil.move(str(src), str(dst))


def file_exists_and_nonempty(path: Path) -> bool:
    return path.exists() and path.is_file() and path.stat().st_size > 0


def sha256_of_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()