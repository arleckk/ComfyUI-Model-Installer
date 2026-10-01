"""Run with: python -B -m unittest discover -s tests -v"""

import importlib
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


# Import without ComfyUI's route-registration entry point.
ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "_cmi_progress_tests"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package
installer = importlib.import_module(f"{PACKAGE}.installer")


class DownloadProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manager = installer.InstallManager()
        self.asset = {
            "name": "test.safetensors", "directory": "loras",
            "url": "https://huggingface.co/example/model/resolve/main/test.safetensors",
        }
        self.manager._jobs["test"] = {
            "id": "test", "status": "queued", "overwrite": False,
            "cancel_requested": False, "completed_assets": 0, "failed_assets": 0,
            "assets": [{**self.asset, "status": "pending"}],
        }
        self.root_patch = patch.object(installer, "COMFY_ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.clock = [100.0]
        self.clock_patch = patch.object(installer.time, "monotonic", side_effect=lambda: self.clock[0])
        self.clock_patch.start()
        self.addCleanup(self.clock_patch.stop)
        # These tests isolate metrics and fallback behavior. Process cancellation is
        # exercised separately below with real child processes.
        def inline_worker(job_id, index, configuration):
            if configuration["transport"] == "huggingface":
                progress = installer._DownloadProgress(self.manager, job_id, index)
                return installer.hf_hub_download(
                    repo_id=configuration["repo_id"], filename=configuration["filename"],
                    repo_type="model", revision=configuration["revision"], local_dir=None,
                    token=configuration["token"], tqdm_class=installer._make_hf_progress_class(progress),
                )
            result = self.manager._stream_direct(
                job_id, index, configuration["asset"], Path(configuration["target_path"]), False
            )
            return result["path"]
        self.worker_patch = patch.object(self.manager, "_run_download_worker", side_effect=inline_worker)
        self.worker_patch.start()
        self.addCleanup(self.worker_patch.stop)

    def state(self, job_id="test"):
        return dict(self.manager.get_job(job_id)["assets"][0])

    def source(self, size=1024):
        path = self.root / "cached.safetensors"
        path.write_bytes(b"x" * size)
        return str(path)

    def response(self, chunks, size=0):
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Length": str(size)} if size else {}
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.iter_content.side_effect = lambda **kwargs: chunks()
        return response

    def test_hub_reports_progress_before_download_returns(self):
        ready, release, finished = threading.Event(), threading.Event(), threading.Event()
        source = self.source()

        def download(*args, tqdm_class=None, **kwargs):
            try:
                with tqdm_class(total=1024, disable=True) as bar:
                    self.clock[0] += 1
                    bar.update(256)
                    ready.set()
                    if not release.wait(5):
                        raise RuntimeError("Test timed out")
                    self.clock[0] += 1
                    bar.update(768)
                return source
            finally:
                finished.set()

        with patch.object(installer, "hf_hub_download", autospec=True, side_effect=download):
            job_id = self.manager.create_job([self.asset])
            try:
                self.assertTrue(ready.wait(5))
                state = self.state(job_id)
                self.assertFalse(finished.is_set())
                self.assertEqual(state["downloaded_bytes"], 256)
                self.assertEqual(state["total_bytes"], 1024)
                self.assertEqual(state["speed_bytes_per_second"], 256)
                self.assertEqual(state["eta_seconds"], 3)
                self.assertEqual(state["download_phase"], "downloading")
            finally:
                release.set()
                self.assertTrue(finished.wait(5))
            for thread in threading.enumerate():
                if thread.name.startswith("Thread-") and thread is not threading.current_thread():
                    thread.join(5)
            self.assertEqual(self.manager.get_job(job_id)["status"], "completed")
            self.assertEqual(self.state(job_id)["speed_bytes_per_second"], 0)

    def test_resumed_bytes_are_excluded_from_speed(self):
        progress = installer._DownloadProgress(self.manager, "test", 0)
        with installer._make_hf_progress_class(progress)(total=1000, initial=600, disable=True) as bar:
            self.clock[0] += 2
            bar.update(100)
            state = self.state()
            self.assertEqual(state["downloaded_bytes"], 700)
            self.assertEqual(state["speed_bytes_per_second"], 50)
            self.assertEqual(state["eta_seconds"], 6)

    def test_xet_network_speed_and_eta_use_separate_counters(self):
        progress = installer._DownloadProgress(self.manager, "test", 0)
        with installer._make_hf_progress_class(progress)(total=1000) as bar:
            self.clock[0] += 1
            bar.update_transfer(100)
            self.assertEqual(self.state()["speed_bytes_per_second"], 100)
            self.assertEqual(self.state()["transferred_bytes"], 100)
            self.assertIsNone(self.state()["eta_seconds"])
            self.clock[0] += 1
            bar.update(500)
            self.assertEqual(self.state()["speed_bytes_per_second"], 50)
            self.assertEqual(self.state()["eta_seconds"], 2)

    def test_unknown_total_reports_bytes_and_speed_without_eta(self):
        progress = installer._DownloadProgress(self.manager, "test", 0)
        self.clock[0] += 2
        progress.update(512, None)
        state = self.state()
        self.assertEqual(state["downloaded_bytes"], 512)
        self.assertEqual(state["speed_bytes_per_second"], 256)
        self.assertEqual(state["total_bytes"], 0)
        self.assertIsNone(state["eta_seconds"])

    def test_progress_is_throttled_but_final_bytes_are_published(self):
        progress = installer._DownloadProgress(self.manager, "test", 0)
        self.clock[0] += 0.1
        progress.update(10, 100)
        self.assertEqual(self.state()["downloaded_bytes"], 0)
        progress.update(100, 100)
        self.assertEqual(self.state()["downloaded_bytes"], 100)
        self.assertEqual(self.state()["eta_seconds"], 0)

    def test_cached_download_uses_copying_phase(self):
        history = []
        original = self.manager._update_asset

        def record(*args, **kwargs):
            original(*args, **kwargs)
            history.append(self.state())

        with patch.object(self.manager, "_update_asset", side_effect=record), patch.object(
            installer, "hf_hub_download", autospec=True, return_value=self.source()
        ):
            self.manager._run_job("test")
        self.assertTrue(any(s.get("download_phase") == "copying" for s in history))
        self.assertEqual(self.state()["downloaded_bytes"], 1024)
        self.assertEqual(self.state()["status"], "installed")
        self.assertEqual((self.root / "models/loras/test.safetensors").read_bytes(), b"x" * 1024)

    def test_cancelled_hub_does_not_fall_back_or_damage_existing_model(self):
        target = self.root / "models/loras/test.safetensors"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"existing model")
        self.manager._jobs["test"]["overwrite"] = True

        def download(*args, tqdm_class=None, **kwargs):
            with tqdm_class(total=1024) as bar:
                self.manager.cancel_job("test")
                try:
                    bar.update(100)
                except installer._DownloadCancelled as error:
                    raise RuntimeError("Native callback failed") from error

        with patch.object(installer, "hf_hub_download", autospec=True, side_effect=download), patch.object(
            installer.requests, "get"
        ) as direct:
            self.manager._run_job("test")
            direct.assert_not_called()
        self.assertEqual(self.manager.get_job("test")["status"], "cancelled")
        self.assertEqual(self.manager.get_job("test")["failed_assets"], 0)
        self.assertEqual(self.state()["status"], "cancelled")
        self.assertEqual(target.read_bytes(), b"existing model")

    def test_direct_stream_reports_live_metrics(self):
        def chunks():
            self.clock[0] += 1
            yield b"x" * 512
            state = self.state()
            self.assertEqual(state["downloaded_bytes"], 512)
            self.assertEqual(state["speed_bytes_per_second"], 512)
            self.assertEqual(state["eta_seconds"], 1)
            self.clock[0] += 1
            yield b"x" * 512

        with patch.object(installer.requests, "get", return_value=self.response(chunks, 1024)):
            self.manager._download_direct("test", 0, self.asset, self.root / "direct.safetensors", False)
        self.assertEqual(self.state()["status"], "installed")

    def test_failed_hub_falls_back_with_fresh_metrics(self):
        def chunks():
            self.clock[0] += 1
            yield b"x" * 1024

        with patch.object(installer, "hf_hub_download", autospec=True, side_effect=RuntimeError("Network error")), patch.object(
            installer.requests, "get", return_value=self.response(chunks, 1024)
        ) as direct:
            self.manager._run_job("test")
            direct.assert_called_once()
        self.assertEqual(self.manager.get_job("test")["status"], "completed")

    def test_older_hub_without_callback_streams_directly(self):
        def old_hub(repo_id, filename, token=None):
            self.fail("Old Hub client should not be called without progress support")

        def chunks():
            self.clock[0] += 1
            yield b"x" * 1024

        with patch.object(installer, "hf_hub_download", old_hub), patch.object(
            installer.requests, "get", return_value=self.response(chunks, 1024)
        ):
            self.manager._run_job("test")
        self.assertEqual(self.state()["status"], "installed")

    def test_auth_error_is_not_retried_as_direct_download(self):
        with patch.object(installer, "hf_hub_download", autospec=True, side_effect=RuntimeError("401 Unauthorized")), patch.object(
            installer.requests, "get"
        ) as direct:
            self.manager._run_job("test")
            direct.assert_not_called()
        self.assertEqual(self.manager.get_job("test")["status"], "completed_with_errors")
        self.assertIn("HF_TOKEN", self.state()["error"])

    def test_callbacks_are_independent_between_downloads(self):
        other = installer.InstallManager()
        other._jobs["other"] = {"assets": [{}], "cancel_requested": False}
        first = installer._make_hf_progress_class(installer._DownloadProgress(self.manager, "test", 0))
        second = installer._make_hf_progress_class(installer._DownloadProgress(other, "other", 0))
        with first(total=1000) as one, second(total=1000) as two:
            self.clock[0] += 1
            one.update(100)
            two.update(200)
        self.assertEqual(self.state()["downloaded_bytes"], 100)
        self.assertEqual(other.get_job("other")["assets"][0]["downloaded_bytes"], 200)


class CancellationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manager = installer.InstallManager()
        self.processes = []
        self.asset = {
            "name": "test.safetensors", "directory": "loras",
            "url": "https://huggingface.co/example/model/resolve/main/test.safetensors",
        }
        # Reports once then hangs, reproducing a native transfer that has stopped
        # making callbacks. Direct mode also leaves an owned partial file behind.
        self.worker = self.root / "blocked_worker.py"
        self.worker.write_text(
            'import json, pathlib, sys, time\n'
            'config = json.load(sys.stdin)\n'
            'if config["transport"] == "direct":\n'
            '    pathlib.Path(config["target_path"] + ".part").write_bytes(b"partial")\n'
            'print("CMI_DOWNLOAD_EVENT " + json.dumps({"type":"progress", "data":'
            '{"downloaded_bytes":123,"total_bytes":1000}}), flush=True)\n'
            'time.sleep(60)\n', encoding="utf-8"
        )
        self.patches = [
            patch.object(installer, "COMFY_ROOT", self.root),
            patch.object(installer, "DOWNLOAD_WORKER_PATH", self.worker),
        ]
        original_popen = installer.subprocess.Popen

        def start_process(*args, **kwargs):
            process = original_popen(*args, **kwargs)
            self.processes.append(process)
            return process

        self.patches.append(patch.object(installer.subprocess, "Popen", side_effect=start_process))
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.addCleanup(self.stop_remaining_jobs)

    def wait_for(self, predicate, timeout=5):
        deadline = installer.time.perf_counter() + timeout
        while installer.time.perf_counter() < deadline:
            if predicate():
                return
            installer.time.sleep(0.01)
        self.fail("Timed out waiting for download state")

    def stop_remaining_jobs(self):
        for job in self.manager.get_jobs():
            if job["status"] in {"queued", "running", "cancelling"}:
                self.manager.cancel_job(job["id"])
        for process in self.processes:
            if process.poll() is None:
                process.wait(timeout=5)

    def start_job(self, assets=None, overwrite=False):
        job_id = self.manager.create_job(assets or [self.asset], overwrite=overwrite)
        self.wait_for(lambda: self.manager.get_job(job_id)["assets"][0].get("downloaded_bytes") == 123)
        return job_id

    def test_cancel_stops_a_worker_with_no_further_callbacks(self):
        job_id = self.start_job()
        started = installer.time.perf_counter()
        self.assertTrue(self.manager.cancel_job(job_id))
        self.assertEqual(self.manager.get_job(job_id)["status"], "cancelling")
        self.wait_for(lambda: self.manager.get_job(job_id)["status"] == "cancelled", timeout=2)
        self.assertLess(installer.time.perf_counter() - started, 2)
        self.assertIsNotNone(self.processes[0].poll())
        self.assertFalse((self.root / "models/loras/test.safetensors").exists())
        self.assertEqual(self.manager.get_job(job_id)["failed_assets"], 0)

    def test_cancel_one_job_does_not_stop_another_worker(self):
        first = self.start_job()
        second_asset = {**self.asset, "name": "other.safetensors",
                        "url": self.asset["url"].replace("test.safetensors", "other.safetensors")}
        second = self.start_job([second_asset])
        self.manager.cancel_job(first)
        self.wait_for(lambda: self.manager.get_job(first)["status"] == "cancelled")
        self.assertEqual(self.manager.get_job(second)["status"], "running")
        self.assertIsNone(self.processes[1].poll())
        self.manager.cancel_job(second)
        self.wait_for(lambda: self.manager.get_job(second)["status"] == "cancelled")

    def test_cancel_marks_queued_assets_cancelled_without_starting_them(self):
        job_id = self.start_job([self.asset, {**self.asset, "name": "queued.safetensors"}])
        self.manager.cancel_job(job_id)
        self.wait_for(lambda: self.manager.get_job(job_id)["status"] == "cancelled")
        self.assertEqual(len(self.processes), 1)
        self.assertEqual([a["status"] for a in self.manager.get_job(job_id)["assets"]], ["cancelled", "cancelled"])

    def test_cancel_preserves_existing_model_when_overwriting(self):
        target = self.root / "models/loras/test.safetensors"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"existing model")
        job_id = self.start_job(overwrite=True)
        self.manager.cancel_job(job_id)
        self.wait_for(lambda: self.manager.get_job(job_id)["status"] == "cancelled")
        self.assertEqual(target.read_bytes(), b"existing model")

    def test_cancel_direct_worker_removes_only_its_partial_file(self):
        asset = {**self.asset, "url": "https://civitai.com/api/download/models/123"}
        job_id = self.start_job([asset])
        self.assertTrue(list((self.root / "models/loras").glob("*.part")))
        unrelated = self.root / "models/loras/another-job.part"
        unrelated.write_bytes(b"other download")
        self.manager.cancel_job(job_id)
        self.wait_for(lambda: self.manager.get_job(job_id)["status"] == "cancelled")
        self.assertEqual(list((self.root / "models/loras").glob("*.part")), [unrelated])
        self.assertEqual(unrelated.read_bytes(), b"other download")

    def test_cancel_finished_job_is_an_idempotent_noop(self):
        self.manager._jobs["finished"] = {"id": "finished", "status": "completed", "cancel_requested": False}
        self.assertTrue(self.manager.cancel_job("finished"))
        self.assertEqual(self.manager.get_job("finished")["status"], "completed")
        self.assertFalse(self.manager.get_job("finished")["cancel_requested"])


if __name__ == "__main__":
    unittest.main()
