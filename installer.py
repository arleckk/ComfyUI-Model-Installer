import os
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests
from huggingface_hub import hf_hub_download

from .models_map import ALLOWED_MODEL_DIRS
from .security import (
    is_allowed_domain,
    is_allowed_extension,
    sanitize_filename,
)
from .utils import ensure_dir, move_atomic, file_exists_and_nonempty


COMFY_ROOT = Path(__file__).resolve().parents[2]
DOWNLOAD_TIMEOUT = 30
DOWNLOAD_CHUNK_SIZE = 1024 * 1024


class InstallManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}

    def get_jobs(self) -> list[dict]:
        with self._lock:
            return list(self._jobs.values())

    def get_job(self, job_id: str) -> dict | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel_job(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            job["cancel_requested"] = True
            return True

    def create_job(self, assets: list[dict], overwrite: bool = False) -> str:
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        job = {
            "id": job_id,
            "status": "queued",
            "created_at": time.time(),
            "updated_at": time.time(),
            "overwrite": overwrite,
            "total_assets": len(assets),
            "completed_assets": 0,
            "failed_assets": 0,
            "cancel_requested": False,
            "current_asset": None,
            "assets": [
                {
                    **asset,
                    "status": "pending",
                    "error": "",
                    "downloaded_bytes": 0,
                    "total_bytes": 0,
                    "target_path": "",
                }
                for asset in assets
            ],
        }
        with self._lock:
            self._jobs[job_id] = job

        thread = threading.Thread(target=self._run_job, args=(job_id,), daemon=True)
        thread.start()
        return job_id

    def _update_job(self, job_id: str, **kwargs) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.update(kwargs)
            job["updated_at"] = time.time()

    def _update_asset(self, job_id: str, index: int, **kwargs) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            if index < 0 or index >= len(job["assets"]):
                return
            job["assets"][index].update(kwargs)
            job["updated_at"] = time.time()

    def _run_job(self, job_id: str) -> None:
        self._update_job(job_id, status="running")

        job = self.get_job(job_id)
        if not job:
            return

        for index, asset in enumerate(job["assets"]):
            job = self.get_job(job_id)
            if not job:
                return

            if job["cancel_requested"]:
                self._update_job(job_id, status="cancelled")
                return

            self._update_job(job_id, current_asset=asset["name"])

            try:
                result = self._install_single_asset(
                    job_id=job_id,
                    asset_index=index,
                    asset=asset,
                    overwrite=job["overwrite"],
                )
                if result["status"] in ("installed", "already_installed"):
                    with self._lock:
                        self._jobs[job_id]["completed_assets"] += 1
                else:
                    with self._lock:
                        self._jobs[job_id]["failed_assets"] += 1
            except Exception as e:
                self._update_asset(job_id, index, status="error", error=str(e))
                with self._lock:
                    self._jobs[job_id]["failed_assets"] += 1

        final_job = self.get_job(job_id)
        if not final_job:
            return

        if final_job["failed_assets"] > 0:
            self._update_job(job_id, status="completed_with_errors")
        else:
            self._update_job(job_id, status="completed")

    def _target_path_for_asset(self, asset: dict) -> Path:
        directory = asset["directory"]
        rel_dir = ALLOWED_MODEL_DIRS[directory]
        filename = sanitize_filename(asset["name"])
        return COMFY_ROOT / rel_dir / filename

    def _install_single_asset(self, job_id: str, asset_index: int, asset: dict, overwrite: bool) -> dict:
        directory = asset.get("directory", "")
        url = (asset.get("url", "") or "").strip()
        name = sanitize_filename(asset.get("name", "") or "")

        if not directory or directory not in ALLOWED_MODEL_DIRS:
            raise ValueError(f"Unsupported directory: {directory}")

        if not url:
            raise ValueError("Missing asset URL")

        if not is_allowed_domain(url):
            raise ValueError(f"Domain not allowed: {urlparse(url).netloc}")

        if not name:
            raise ValueError("Missing asset filename")

        if not is_allowed_extension(name):
            raise ValueError(f"Unsupported file extension: {name}")

        target_path = self._target_path_for_asset(asset)
        ensure_dir(target_path.parent)
        self._update_asset(job_id, asset_index, target_path=str(target_path))

        if file_exists_and_nonempty(target_path) and not overwrite:
            self._update_asset(job_id, asset_index, status="already_installed")
            return {"status": "already_installed", "path": str(target_path)}

        if "huggingface.co" in urlparse(url).netloc.lower():
            return self._download_huggingface(job_id, asset_index, asset, target_path, overwrite)

        return self._download_direct(job_id, asset_index, asset, target_path, overwrite)

    def _extract_hf_repo_parts(self, url: str) -> tuple[str, str] | None:
        """
        Supports URLs like:
        https://huggingface.co/<repo_id>/resolve/main/<path/to/file>
        https://huggingface.co/<repo_id>/blob/main/<path/to/file>
        """
        parsed = urlparse(url)
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) < 4:
            return None

        # repo can be org/repo
        repo_id = "/".join(parts[:2])
        mode = parts[2]
        if mode not in {"resolve", "blob"}:
            return None

        filename = "/".join(parts[4:]) if len(parts) >= 5 else ""
        if not filename:
            return None

        return repo_id, filename

    def _download_huggingface(self, job_id: str, asset_index: int, asset: dict, target_path: Path, overwrite: bool) -> dict:
        url = asset["url"]
        self._update_asset(job_id, asset_index, status="downloading")

        repo_parts = self._extract_hf_repo_parts(url)
        if repo_parts:
            repo_id, filename_in_repo = repo_parts
            downloaded = hf_hub_download(
                repo_id=repo_id,
                filename=filename_in_repo,
                repo_type="model",
                local_dir=None,
                local_dir_use_symlinks=False,
            )
            source_path = Path(downloaded)
            temp_path = target_path.with_suffix(target_path.suffix + ".part")
            if temp_path.exists():
                temp_path.unlink()
            # copy from HF cache into temp, then atomic move
            with source_path.open("rb") as src, temp_path.open("wb") as dst:
                while True:
                    chunk = src.read(DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    dst.write(chunk)
                    self._check_cancel(job_id)
            move_atomic(temp_path, target_path)
            self._update_asset(job_id, asset_index, status="installed")
            return {"status": "installed", "path": str(target_path)}

        # fallback to direct streaming for HF if parsing fails
        return self._download_direct(job_id, asset_index, asset, target_path, overwrite)

    def _download_direct(self, job_id: str, asset_index: int, asset: dict, target_path: Path, overwrite: bool) -> dict:
        url = asset["url"]
        temp_path = target_path.with_suffix(target_path.suffix + ".part")

        if temp_path.exists():
            temp_path.unlink()

        self._update_asset(job_id, asset_index, status="downloading", downloaded_bytes=0, total_bytes=0)

        with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT, allow_redirects=True) as response:
            response.raise_for_status()

            total_bytes = int(response.headers.get("Content-Length", "0") or "0")
            self._update_asset(job_id, asset_index, total_bytes=total_bytes)

            with temp_path.open("wb") as f:
                downloaded = 0
                for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                    self._check_cancel(job_id)
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    self._update_asset(
                        job_id,
                        asset_index,
                        downloaded_bytes=downloaded,
                        total_bytes=total_bytes,
                    )

        if not file_exists_and_nonempty(temp_path):
            raise RuntimeError("Downloaded file is empty or incomplete")

        move_atomic(temp_path, target_path)
        self._update_asset(job_id, asset_index, status="installed")
        return {"status": "installed", "path": str(target_path)}

    def _check_cancel(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if job and job.get("cancel_requested"):
            raise RuntimeError("Download cancelled")


install_manager = InstallManager()