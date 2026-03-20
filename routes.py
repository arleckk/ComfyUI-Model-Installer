from aiohttp import web
import traceback
import subprocess
from pathlib import Path

try:
    from server import PromptServer
except Exception:
    PromptServer = None

from .parser import collect_assets
from .resolver import resolve_assets, list_hf_candidates, confirm_candidate
from .installer import install_manager, COMFY_ROOT
from .models_map import ALLOWED_MODEL_DIRS
from .utils import file_exists_and_nonempty
from . import PLUGIN_VERSION

PLUGIN_DIR = Path(__file__).resolve().parent


def _json_request_data(request_data: dict) -> dict:
    return request_data if isinstance(request_data, dict) else {}


def _find_local_target_path(asset: dict) -> Path | None:
    directory = asset.get("directory", "")
    rel_dir = ALLOWED_MODEL_DIRS.get(directory)
    if rel_dir is None:
        return None

    target_dir = COMFY_ROOT / rel_dir
    name = asset.get("name", "")

    exact = target_dir / name
    if file_exists_and_nonempty(exact):
        return exact

    if not target_dir.exists():
        return exact

    expected_stem = Path(name).stem.lower() if "." in name else name.lower()
    for entry in target_dir.iterdir():
        if entry.is_file() and entry.stem.lower() == expected_stem:
            return entry

    return exact


def _annotate_installed_status(assets: list[dict]) -> list[dict]:
    annotated = []
    for asset in assets:
        target_path = _find_local_target_path(asset)
        if target_path is None:
            continue

        status = "installed" if file_exists_and_nonempty(target_path) else "missing"
        annotated.append(
            {
                **asset,
                "status": status if asset.get("status") in (None, "", "missing", "installed", "already_installed") else asset.get("status"),
                "target_path": str(target_path),
            }
        )
    return annotated


def _run_git_command(args: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            args,
            cwd=str(PLUGIN_DIR),
            capture_output=True,
            text=True,
            shell=False,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def _is_git_repo() -> bool:
    return (PLUGIN_DIR / ".git").exists()


def _get_current_commit() -> str:
    code, out, err = _run_git_command(["git", "rev-parse", "HEAD"])
    return out if code == 0 else ""


def _get_remote_commit(branch: str = "main") -> str:
    code, out, err = _run_git_command(["git", "rev-parse", f"origin/{branch}"])
    return out if code == 0 else ""


def _git_fetch() -> tuple[bool, str]:
    code, out, err = _run_git_command(["git", "fetch", "origin"])
    if code != 0:
        return False, err or out
    return True, out or "Fetched successfully"


def _git_pull_main() -> tuple[bool, str]:
    code, out, err = _run_git_command(["git", "pull", "origin", "main"])
    if code != 0:
        return False, err or out
    return True, out or "Updated successfully"


def register_routes():
    if PromptServer is None:
        return

    routes = PromptServer.instance.routes

    @routes.get("/model-installer/ping")
    async def model_installer_ping(request):
        return web.json_response(
            {
                "ok": True,
                "plugin": "ComfyUI Model Installer",
                "version": PLUGIN_VERSION,
            }
        )

    @routes.get("/model-installer/version")
    async def model_installer_version(request):
        try:
            git_repo = _is_git_repo()
            current_commit = _get_current_commit() if git_repo else ""

            return web.json_response(
                {
                    "ok": True,
                    "plugin": "ComfyUI Model Installer",
                    "version": PLUGIN_VERSION,
                    "git_repo": git_repo,
                    "current_commit": current_commit,
                }
            )
        except Exception as e:
            tb = traceback.format_exc()
            print("\n[ComfyUI Model Installer] /model-installer/version ERROR")
            print(tb)
            return web.json_response(
                {
                    "ok": False,
                    "error": str(e),
                    "traceback": tb,
                    "where": "/model-installer/version",
                },
                status=400,
            )

    @routes.get("/model-installer/update/check")
    async def model_installer_update_check(request):
        try:
            if not _is_git_repo():
                return web.json_response(
                    {
                        "ok": True,
                        "git_repo": False,
                        "can_update": False,
                        "message": "Plugin folder is not a git repository.",
                    }
                )

            success, fetch_msg = _git_fetch()
            if not success:
                return web.json_response(
                    {
                        "ok": False,
                        "git_repo": True,
                        "can_update": False,
                        "error": fetch_msg,
                    },
                    status=400,
                )

            current_commit = _get_current_commit()
            remote_commit = _get_remote_commit("main")

            if not current_commit or not remote_commit:
                return web.json_response(
                    {
                        "ok": False,
                        "git_repo": True,
                        "can_update": False,
                        "error": "Could not resolve local or remote commit.",
                    },
                    status=400,
                )

            has_update = current_commit != remote_commit

            return web.json_response(
                {
                    "ok": True,
                    "git_repo": True,
                    "can_update": True,
                    "has_update": has_update,
                    "current_commit": current_commit,
                    "remote_commit": remote_commit,
                }
            )
        except Exception as e:
            tb = traceback.format_exc()
            print("\n[ComfyUI Model Installer] /model-installer/update/check ERROR")
            print(tb)
            return web.json_response(
                {
                    "ok": False,
                    "error": str(e),
                    "traceback": tb,
                    "where": "/model-installer/update/check",
                },
                status=400,
            )

    @routes.post("/model-installer/update/plugin")
    async def model_installer_update_plugin(request):
        try:
            if not _is_git_repo():
                return web.json_response(
                    {
                        "ok": False,
                        "error": "Plugin folder is not a git repository.",
                    },
                    status=400,
                )

            success_fetch, fetch_msg = _git_fetch()
            if not success_fetch:
                return web.json_response(
                    {
                        "ok": False,
                        "error": fetch_msg,
                    },
                    status=400,
                )

            current_commit = _get_current_commit()
            remote_commit = _get_remote_commit("main")

            if current_commit and remote_commit and current_commit == remote_commit:
                return web.json_response(
                    {
                        "ok": True,
                        "updated": False,
                        "message": "Plugin is already up to date.",
                        "current_commit": current_commit,
                        "remote_commit": remote_commit,
                    }
                )

            success_pull, pull_msg = _git_pull_main()
            if not success_pull:
                return web.json_response(
                    {
                        "ok": False,
                        "error": pull_msg,
                    },
                    status=400,
                )

            new_commit = _get_current_commit()

            return web.json_response(
                {
                    "ok": True,
                    "updated": True,
                    "message": pull_msg,
                    "current_commit": new_commit,
                    "remote_commit": remote_commit,
                    "restart_required": True,
                }
            )
        except Exception as e:
            tb = traceback.format_exc()
            print("\n[ComfyUI Model Installer] /model-installer/update/plugin ERROR")
            print(tb)
            return web.json_response(
                {
                    "ok": False,
                    "error": str(e),
                    "traceback": tb,
                    "where": "/model-installer/update/plugin",
                },
                status=400,
            )

    @routes.post("/model-installer/scan")
    async def model_installer_scan(request):
        try:
            data = await request.json()
            data = _json_request_data(data)
            workflow = data.get("workflow", {}) or {}

            assets = collect_assets(workflow, include_inferred=True)
            assets = _annotate_installed_status(assets)

            return web.json_response(
                {
                    "ok": True,
                    "count": len(assets),
                    "assets": assets,
                }
            )
        except Exception as e:
            tb = traceback.format_exc()
            print("\n[ComfyUI Model Installer] /model-installer/scan ERROR")
            print(tb)
            return web.json_response(
                {
                    "ok": False,
                    "error": str(e),
                    "traceback": tb,
                    "where": "/model-installer/scan",
                },
                status=400,
            )

    @routes.post("/model-installer/scan-resolve")
    async def model_installer_scan_resolve(request):
        try:
            data = await request.json()
            data = _json_request_data(data)
            workflow = data.get("workflow", {}) or {}

            assets = collect_assets(workflow, include_inferred=True)
            assets = resolve_assets(assets)
            assets = _annotate_installed_status(assets)

            resolved_count = len([a for a in assets if a.get("resolved")])
            ambiguous_count = len([a for a in assets if a.get("resolver_status") == "ambiguous"])
            unresolved_count = len([a for a in assets if a.get("resolver_status") == "unresolved"])

            return web.json_response(
                {
                    "ok": True,
                    "count": len(assets),
                    "resolved_count": resolved_count,
                    "ambiguous_count": ambiguous_count,
                    "unresolved_count": unresolved_count,
                    "assets": assets,
                }
            )
        except Exception as e:
            tb = traceback.format_exc()
            print("\n[ComfyUI Model Installer] /model-installer/scan-resolve ERROR")
            print(tb)
            return web.json_response(
                {
                    "ok": False,
                    "error": str(e),
                    "traceback": tb,
                    "where": "/model-installer/scan-resolve",
                },
                status=400,
            )

    @routes.post("/model-installer/resolve/candidates")
    async def model_installer_resolve_candidates(request):
        try:
            data = await request.json()
            data = _json_request_data(data)
            asset = data.get("asset", {}) or {}

            candidates = list_hf_candidates(asset)

            return web.json_response(
                {
                    "ok": True,
                    "asset": asset,
                    "candidate_count": len(candidates),
                    "candidates": candidates,
                }
            )
        except Exception as e:
            tb = traceback.format_exc()
            print("\n[ComfyUI Model Installer] /model-installer/resolve/candidates ERROR")
            print(tb)
            return web.json_response(
                {
                    "ok": False,
                    "error": str(e),
                    "traceback": tb,
                    "where": "/model-installer/resolve/candidates",
                },
                status=400,
            )

    @routes.post("/model-installer/resolve/confirm")
    async def model_installer_resolve_confirm(request):
        try:
            data = await request.json()
            data = _json_request_data(data)
            asset = data.get("asset", {}) or {}
            candidate = data.get("candidate", {}) or {}

            resolved_asset = confirm_candidate(asset, candidate)
            annotated = _annotate_installed_status([resolved_asset])

            return web.json_response(
                {
                    "ok": True,
                    "asset": annotated[0] if annotated else resolved_asset,
                }
            )
        except Exception as e:
            tb = traceback.format_exc()
            print("\n[ComfyUI Model Installer] /model-installer/resolve/confirm ERROR")
            print(tb)
            return web.json_response(
                {
                    "ok": False,
                    "error": str(e),
                    "traceback": tb,
                    "where": "/model-installer/resolve/confirm",
                },
                status=400,
            )

    @routes.post("/model-installer/download")
    async def model_installer_download(request):
        try:
            data = await request.json()
            data = _json_request_data(data)
            assets = data.get("assets", []) or []
            overwrite = bool(data.get("overwrite", False))

            normalized_assets = []
            for asset in assets:
                if not isinstance(asset, dict):
                    continue
                if "name" not in asset or "url" not in asset or "directory" not in asset:
                    continue

                normalized_assets.append(
                    {
                        "name": asset["name"],
                        "url": asset["url"],
                        "directory": asset["directory"],
                        "source": asset.get("source", "manual"),
                        "node_id": asset.get("node_id"),
                        "node_type": asset.get("node_type"),
                        "title": asset.get("title", ""),
                    }
                )

            if not normalized_assets:
                return web.json_response(
                    {
                        "ok": False,
                        "error": "No valid assets provided",
                    },
                    status=400,
                )

            job_id = install_manager.create_job(normalized_assets, overwrite=overwrite)
            return web.json_response(
                {
                    "ok": True,
                    "job_id": job_id,
                }
            )
        except Exception as e:
            tb = traceback.format_exc()
            print("\n[ComfyUI Model Installer] /model-installer/download ERROR")
            print(tb)
            return web.json_response(
                {
                    "ok": False,
                    "error": str(e),
                    "traceback": tb,
                    "where": "/model-installer/download",
                },
                status=400,
            )

    @routes.get("/model-installer/status")
    async def model_installer_status(request):
        try:
            job_id = request.query.get("job_id", "").strip()
            if job_id:
                job = install_manager.get_job(job_id)
                if not job:
                    return web.json_response(
                        {
                            "ok": False,
                            "error": "Job not found",
                        },
                        status=404,
                    )
                return web.json_response({"ok": True, "job": job})

            return web.json_response({"ok": True, "jobs": install_manager.get_jobs()})
        except Exception as e:
            tb = traceback.format_exc()
            print("\n[ComfyUI Model Installer] /model-installer/status ERROR")
            print(tb)
            return web.json_response(
                {
                    "ok": False,
                    "error": str(e),
                    "traceback": tb,
                    "where": "/model-installer/status",
                },
                status=400,
            )

    @routes.post("/model-installer/cancel")
    async def model_installer_cancel(request):
        try:
            data = await request.json()
            job_id = (data.get("job_id", "") or "").strip()
            if not job_id:
                return web.json_response(
                    {"ok": False, "error": "Missing job_id"},
                    status=400,
                )

            cancelled = install_manager.cancel_job(job_id)
            if not cancelled:
                return web.json_response(
                    {"ok": False, "error": "Job not found"},
                    status=404,
                )

            return web.json_response({"ok": True, "job_id": job_id})
        except Exception as e:
            tb = traceback.format_exc()
            print("\n[ComfyUI Model Installer] /model-installer/cancel ERROR")
            print(tb)
            return web.json_response(
                {"ok": False, "error": str(e), "traceback": tb, "where": "/model-installer/cancel"},
                status=400,
            )