import inspect
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests
from huggingface_hub import hf_hub_download
from tqdm.auto import tqdm

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
PROGRESS_UPDATE_INTERVAL = 0.25
DOWNLOAD_WORKER_PATH = Path(__file__).with_name("download_worker.py")
WORKER_EVENT_PREFIX = "CMI_DOWNLOAD_EVENT "


def debug_log(message: str) -> None:
    print(f"[CMI installer] {message}")


def get_hf_token() -> str:
    return (os.getenv("HF_TOKEN", "") or "").strip()


class _DownloadCancelled(RuntimeError):
    pass


class _DownloadProgress:
    """Publish transfer metrics without counting resumed bytes as new traffic."""

    def __init__(self, manager, job_id, asset_index, phase="downloading"):
        self.manager = manager
        self.job_id = job_id
        self.asset_index = asset_index
        self.phase = phase
        self._lock = threading.RLock()
        self.reset()

    def reset(self, initial=0, total=None):
        with self._lock:
            self.started_at = time.monotonic()
            self.last_update = self.started_at
            self.initial = max(0, int(initial or 0))
            self.downloaded = self.initial
            self.total = max(0, int(total or 0))
            self.transferred = 0
            self.has_transfer_updates = False
            self._publish(force=True)

    def update(self, downloaded, total=None, force=False):
        self.manager._check_cancel(self.job_id)
        with self._lock:
            self.downloaded = max(0, int(downloaded or 0))
            self.total = max(0, int(total or 0))
            self._publish(force=force or (self.total > 0 and self.downloaded >= self.total))

    def update_transfer(self, increment):
        self.manager._check_cancel(self.job_id)
        with self._lock:
            self.has_transfer_updates = True
            self.transferred += max(0, int(increment or 0))
            self._publish()

    def _publish(self, force=False):
        now = time.monotonic()
        if not force and now - self.last_update < PROGRESS_UPDATE_INTERVAL:
            return
        elapsed = now - self.started_at
        completed = max(0, self.downloaded - self.initial)
        file_rate = completed / elapsed if elapsed > 0 else 0
        speed = self.transferred / elapsed if self.has_transfer_updates and elapsed > 0 else file_rate
        # Xet can compress/deduplicate traffic, so estimate remaining time from file
        # completion, while displaying network throughput when it is available.
        eta = max(0, self.total - self.downloaded) / file_rate if self.total > 0 and file_rate > 0 else None
        self.manager._update_asset(
            self.job_id,
            self.asset_index,
            download_phase=self.phase,
            downloaded_bytes=self.downloaded,
            transferred_bytes=self.transferred if self.has_transfer_updates else None,
            total_bytes=self.total,
            speed_bytes_per_second=speed,
            eta_seconds=eta,
        )
        self.last_update = now


def _make_hf_progress_class(progress):
    """A per-download callback; never replaces Hugging Face's global progress bar."""

    class DownloadTqdm(tqdm):
        def __init__(self, *args, **kwargs):
            kwargs.pop("name", None)
            # Console bars can be disabled, but the web UI still needs byte counts.
            kwargs["disable"] = False
            super().__init__(*args, **kwargs)
            progress.reset(self.n, self.total)

        def display(self, *args, **kwargs):
            return False

        def update(self, n=1):
            result = super().update(n)
            progress.update(self.n, self.total)
            return result

        def reset(self, total=None):
            super().reset(total)
            progress.reset(self.n, self.total)

        def update_transfer(self, n):
            # Newer Hub/Xet versions provide network and file completion separately.
            progress.update_transfer(n)

        def set_transfer_postfix_str(self, *args, **kwargs):
            pass

    return DownloadTqdm


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
            if job["status"] not in {"queued", "running", "cancelling"}:
                return True
            job["cancel_requested"] = True
            job["status"] = "cancelling"
            job["updated_at"] = time.time()
            for asset in job["assets"]:
                if asset.get("status") == "downloading":
                    asset.update(status="cancelling", speed_bytes_per_second=0, eta_seconds=None)
            return True

    def _mark_job_cancelled(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            for asset in job["assets"]:
                if asset.get("status") in {"pending", "downloading", "cancelling"}:
                    asset.update(status="cancelled", download_phase="", speed_bytes_per_second=0, eta_seconds=None)
            job.update(status="cancelled", updated_at=time.time())

    def _run_download_worker(self, job_id: str, asset_index: int, configuration: dict) -> str:
        """Keep cancellation independent of network reads and native callbacks."""
        self._check_cancel(job_id)
        events = queue.Queue()
        with tempfile.TemporaryFile() as error_output:
            process = subprocess.Popen(
                [sys.executable, "-s", "-u", str(DOWNLOAD_WORKER_PATH)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=error_output,
                text=True,
                encoding="utf-8",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

            def read_events():
                try:
                    for line in process.stdout:
                        if line.startswith(WORKER_EVENT_PREFIX):
                            try:
                                events.put(json.loads(line[len(WORKER_EVENT_PREFIX):]))
                            except (ValueError, TypeError):
                                continue
                finally:
                    events.put(None)

            reader = threading.Thread(target=read_events, daemon=True)
            result = None
            reader.start()
            try:
                # Credentials go through stdin, never through command-line arguments.
                process.stdin.write(json.dumps(configuration))
                process.stdin.close()
                while True:
                    self._check_cancel(job_id)
                    try:
                        event = events.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if event is None:
                        raise RuntimeError(f"Download worker exited unexpectedly (code {process.poll()})")
                    if event.get("type") == "progress":
                        self._update_asset(job_id, asset_index, **event["data"])
                    elif event.get("type") == "done":
                        self._check_cancel(job_id)
                        result = event["path"]
                        return result
                    elif event.get("type") == "error":
                        raise RuntimeError(event["message"])
            finally:
                # A native transfer can ignore callback exceptions or hang on exit.
                # Terminate only this job's worker, and reap it before reporting done.
                if result is not None:
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
                reader.join(timeout=1)
                if not process.stdin.closed:
                    process.stdin.close()
                process.stdout.close()

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
                    "transferred_bytes": None,
                    "download_phase": "",
                    "speed_bytes_per_second": 0,
                    "eta_seconds": None,
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
                self._mark_job_cancelled(job_id)
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
                if isinstance(e, _DownloadCancelled) or job.get("cancel_requested"):
                    self._mark_job_cancelled(job_id)
                    return
                debug_log(f"job={job_id} asset={asset.get('name','')} error={e}")
                self._update_asset(job_id, index, status="error", error=str(e), download_phase="", speed_bytes_per_second=0, eta_seconds=None)
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

        domain = urlparse(url).netloc.lower()
        if "huggingface.co" in domain:
            return self._download_huggingface(job_id, asset_index, asset, target_path, overwrite)

        return self._download_direct(job_id, asset_index, asset, target_path, overwrite)

    def _extract_hf_repo_parts(self, url: str) -> tuple[str, str, str] | None:
        """
        Supports URLs like:
        https://huggingface.co/<repo_id>/resolve/main/<path/to/file>
        https://huggingface.co/<repo_id>/blob/main/<path/to/file>

        Returns:
            (repo_id, revision, filename_in_repo)
        """
        parsed = urlparse(url)
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) < 5:
            return None

        repo_id = "/".join(parts[:2])
        mode = parts[2]
        revision = parts[3]

        if mode not in {"resolve", "blob"}:
            return None

        filename = "/".join(parts[4:]) if len(parts) >= 5 else ""
        if not filename:
            return None

        return repo_id, revision, filename

    def _download_huggingface(self, job_id: str, asset_index: int, asset: dict, target_path: Path, overwrite: bool) -> dict:
        url = asset["url"]
        token = get_hf_token()
        self._update_asset(job_id, asset_index, status="downloading")
        _DownloadProgress(self, job_id, asset_index)
        temp_path = target_path.with_name(f"{target_path.name}.{job_id}.part")

        debug_log(
            f"HF download start asset={asset.get('name','')} token={'yes' if token else 'no'} url={url}"
        )

        repo_parts = self._extract_hf_repo_parts(url)
        # Older Hub clients have no per-download callback. Direct streaming keeps
        # live progress working without monkey-patching a shared library.
        if repo_parts and "tqdm_class" in inspect.signature(hf_hub_download).parameters:
            repo_id, revision, filename_in_repo = repo_parts
            debug_log(
                f"HF parsed repo_id={repo_id} revision={revision} filename={filename_in_repo}"
            )

            try:
                downloaded = self._run_download_worker(job_id, asset_index, {
                    "transport": "huggingface",
                    "repo_id": repo_id,
                    "filename": filename_in_repo,
                    "revision": revision,
                    "token": token if token else None,
                })
                self._check_cancel(job_id)
                source_path = Path(downloaded)

                if temp_path.exists():
                    temp_path.unlink()

                total_bytes = source_path.stat().st_size if source_path.exists() else 0
                progress = _DownloadProgress(self, job_id, asset_index, phase="copying")
                progress.update(0, total_bytes, force=True)

                with source_path.open("rb") as src, temp_path.open("wb") as dst:
                    copied = 0
                    while True:
                        chunk = src.read(DOWNLOAD_CHUNK_SIZE)
                        if not chunk:
                            break
                        self._check_cancel(job_id)
                        dst.write(chunk)
                        copied += len(chunk)
                        progress.update(copied, total_bytes)

                self._check_cancel(job_id)
                move_atomic(temp_path, target_path)
                self._update_asset(job_id, asset_index, status="installed", download_phase="", speed_bytes_per_second=0, eta_seconds=None)
                debug_log(f"HF download installed asset={asset.get('name','')} path={target_path}")
                return {"status": "installed", "path": str(target_path)}

            except Exception as e:
                # Native transports may wrap exceptions raised by the callback.
                # Cancellation must never trigger another download via the fallback.
                if isinstance(e, _DownloadCancelled):
                    temp_path.unlink(missing_ok=True)
                    raise
                self._check_cancel(job_id)
                message = str(e)
                lower_message = message.lower()

                if "401" in lower_message or "unauthorized" in lower_message or "gated" in lower_message:
                    raise RuntimeError(
                        "Hugging Face authentication required or access not granted for this model. "
                        "Set HF_TOKEN or login with 'hf auth login', and make sure your account has access."
                    )

                debug_log(f"HF hub download failed asset={asset.get('name','')} error={message}")
                # fallback to direct stream below

        debug_log(f"HF fallback to direct streaming asset={asset.get('name','')}")
        return self._download_direct(job_id, asset_index, asset, target_path, overwrite)

    def _build_request_headers(self, url: str) -> dict:
        headers = {}
        token = get_hf_token()
        domain = urlparse(url).netloc.lower()

        if token and "huggingface.co" in domain:
            headers["Authorization"] = f"Bearer {token}"

        return headers

    def _download_direct(self, job_id: str, asset_index: int, asset: dict, target_path: Path, overwrite: bool) -> dict:
        temp_path = target_path.with_name(f"{target_path.name}.{job_id}.part")
        self._update_asset(job_id, asset_index, status="downloading")
        _DownloadProgress(self, job_id, asset_index)
        try:
            downloaded = self._run_download_worker(job_id, asset_index, {
                "transport": "direct",
                "asset": asset,
                "target_path": str(temp_path),
                "token": get_hf_token() or None,
            })
            self._check_cancel(job_id)
            move_atomic(Path(downloaded), target_path)
            self._update_asset(job_id, asset_index, status="installed", download_phase="", speed_bytes_per_second=0, eta_seconds=None)
            return {"status": "installed", "path": str(target_path)}
        finally:
            # These temporary files belong to this job, including the worker's stream.
            temp_path.unlink(missing_ok=True)
            temp_path.with_suffix(temp_path.suffix + ".part").unlink(missing_ok=True)

    def _stream_direct(self, job_id: str, asset_index: int, asset: dict, target_path: Path, overwrite: bool) -> dict:
        url = asset["url"]
        temp_path = target_path.with_suffix(target_path.suffix + ".part")
        headers = self._build_request_headers(url)

        if temp_path.exists():
            temp_path.unlink()

        self._update_asset(job_id, asset_index, status="downloading")
        progress = _DownloadProgress(self, job_id, asset_index)

        debug_log(
            f"direct download start asset={asset.get('name','')} domain={urlparse(url).netloc.lower()} token_auth={'yes' if 'Authorization' in headers else 'no'}"
        )

        try:
            with requests.get(
                url,
                stream=True,
                timeout=DOWNLOAD_TIMEOUT,
                allow_redirects=True,
                headers=headers,
            ) as response:
                if response.status_code == 401 and "huggingface.co" in urlparse(url).netloc.lower():
                    raise RuntimeError(
                        "Hugging Face authentication required or access not granted for this model. "
                        "Set HF_TOKEN or login with 'hf auth login', and make sure your account has access."
                    )

                response.raise_for_status()

                total_bytes = int(response.headers.get("Content-Length", "0") or "0")
                progress.update(0, total_bytes, force=True)

                with temp_path.open("wb") as f:
                    downloaded = 0
                    for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                        self._check_cancel(job_id)
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        progress.update(downloaded, total_bytes)
                    progress.update(downloaded, total_bytes, force=True)

        except requests.HTTPError as e:
            if "huggingface.co" in urlparse(url).netloc.lower():
                status_code = getattr(getattr(e, "response", None), "status_code", None)
                if status_code == 401:
                    raise RuntimeError(
                        "Hugging Face authentication required or access not granted for this model. "
                        "Set HF_TOKEN or login with 'hf auth login', and make sure your account has access."
                    )
            raise
        except requests.RequestException as e:
            raise RuntimeError(f"Download request failed: {e}") from e

        if not file_exists_and_nonempty(temp_path):
            raise RuntimeError("Downloaded file is empty or incomplete")

        self._check_cancel(job_id)
        move_atomic(temp_path, target_path)
        self._update_asset(job_id, asset_index, status="installed", download_phase="", speed_bytes_per_second=0, eta_seconds=None)
        debug_log(f"direct download installed asset={asset.get('name','')} path={target_path}")
        return {"status": "installed", "path": str(target_path)}

    def _check_cancel(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if job and job.get("cancel_requested"):
            raise _DownloadCancelled("Download cancelled")


install_manager = InstallManager()
