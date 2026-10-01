"""Standalone transfer worker. The parent owns cancellation and model installation."""

import importlib
import json
import os
import sys
import types
from pathlib import Path


EVENT_PREFIX = "CMI_DOWNLOAD_EVENT "


def send_event(event_type, **data):
    print(EVENT_PREFIX + json.dumps({"type": event_type, **data}), flush=True)


def main():
    configuration = json.load(sys.stdin)
    # Import download helpers without running ComfyUI's extension entry point.
    package_name = "_cmi_download_worker"
    package = types.ModuleType(package_name)
    package.__path__ = [str(Path(__file__).resolve().parent)]
    sys.modules[package_name] = package
    installer = importlib.import_module(f"{package_name}.installer")

    class WorkerManager(installer.InstallManager):
        def _check_cancel(self, job_id):
            # Raising inside a Rust/Xet callback can deadlock the native downloader.
            # The parent stops this process independently instead.
            pass

        def _update_asset(self, job_id, index, **kwargs):
            super()._update_asset(job_id, index, **kwargs)
            if "downloaded_bytes" in kwargs:
                send_event("progress", data=kwargs)

    manager = WorkerManager()
    manager._jobs["worker"] = {"cancel_requested": False, "assets": [{}]}
    if configuration["transport"] == "huggingface":
        progress = installer._DownloadProgress(manager, "worker", 0)
        path = installer.hf_hub_download(
            repo_id=configuration["repo_id"],
            filename=configuration["filename"],
            repo_type="model",
            revision=configuration["revision"],
            token=configuration.get("token"),
            tqdm_class=installer._make_hf_progress_class(progress),
            **({"cache_dir": configuration["cache_dir"]} if configuration.get("cache_dir") else {}),
        )
    else:
        if configuration.get("token"):
            os.environ["HF_TOKEN"] = configuration["token"]
        result = manager._stream_direct(
            "worker", 0, configuration["asset"], Path(configuration["target_path"]), False
        )
        path = result["path"]
    send_event("done", path=str(path))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        send_event("error", message=str(error))
        sys.exit(1)
