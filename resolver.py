import json
import re
from pathlib import Path
from urllib.parse import quote

from huggingface_hub import HfApi

from .resolver_cache import get_cached_resolution, set_cached_resolution
from .security import sanitize_filename


KNOWN_MODELS_FILE = Path(__file__).resolve().parent / "known_models.json"

ALLOWED_FILE_EXTENSIONS = {
    ".safetensors",
    ".ckpt",
    ".pt",
    ".pth",
    ".bin",
    ".gguf",
}

AUTO_RESOLVE_SCORE = 95
AMBIGUOUS_MIN_SCORE = 45
MAX_REPOS_TO_CHECK = 8
MAX_CANDIDATES = 8


def debug_log(message: str) -> None:
    print(f"[CMI resolver] {message}")


def normalize_name(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"\.(safetensors|ckpt|pt|pth|bin|gguf)$", "", value)
    value = re.sub(r"[_\-\s]+", "", value)
    value = re.sub(r"[^a-z0-9]", "", value)
    return value


def stem_only(value: str) -> str:
    value = sanitize_filename(value or "")
    if "." in value:
        return value.rsplit(".", 1)[0]
    return value


def load_known_models() -> dict:
    if not KNOWN_MODELS_FILE.exists():
        debug_log("known_models.json not found")
        return {}
    try:
        data = json.loads(KNOWN_MODELS_FILE.read_text(encoding="utf-8"))
        debug_log(f"known_models loaded entries={len(data)}")
        return data
    except Exception as e:
        debug_log(f"known_models load error={e}")
        return {}


def build_hf_resolve_url(repo_id: str, revision: str, rfilename: str) -> str:
    safe_file = "/".join(quote(part) for part in rfilename.split("/"))
    return f"https://huggingface.co/{repo_id}/resolve/{revision}/{safe_file}"


def score_candidate(requested_name: str, requested_directory: str, repo_id: str, filename: str) -> tuple[int, list[str]]:
    requested_raw = sanitize_filename(requested_name or "")
    requested_norm = normalize_name(requested_raw)
    requested_stem = normalize_name(stem_only(requested_raw))

    filename_base = Path(filename).name
    filename_norm = normalize_name(filename_base)
    filename_stem = normalize_name(stem_only(filename_base))
    repo_norm = normalize_name(repo_id)

    score = 0
    reasons = []

    if requested_raw and requested_raw.lower() == filename_base.lower():
        score += 100
        reasons.append("exact filename match")

    if requested_stem and requested_stem == filename_stem:
        score += 95
        reasons.append("exact stem match")

    if requested_norm and requested_norm == filename_norm:
        score += 90
        reasons.append("exact normalized name match")

    if requested_stem and requested_stem in filename_stem:
        score += 55
        reasons.append("requested name inside filename")

    if filename_stem and filename_stem in requested_stem:
        score += 45
        reasons.append("filename inside requested name")

    if requested_stem and requested_stem in repo_norm:
        score += 20
        reasons.append("requested name inside repo id")

    if filename_base.lower().endswith(".safetensors"):
        score += 8
        reasons.append("preferred safetensors format")

    directory_bonus_map = {
        "loras": ["lora", "loras"],
        "vae": ["vae"],
        "checkpoints": ["checkpoint", "ckpt", "model", "pony"],
        "text_encoders": ["text", "encoder", "clip", "t5"],
        "clip": ["clip"],
        "clip_vision": ["clipvision", "clipvisionmodel", "vision"],
        "controlnet": ["controlnet"],
        "diffusion_models": ["diffusion", "transformer", "unet"],
        "unet": ["unet"],
    }

    keywords = directory_bonus_map.get(requested_directory, [])
    filename_repo_norm = normalize_name(filename_base + repo_id)
    if any(normalize_name(k) in filename_repo_norm for k in keywords):
        score += 8
        reasons.append(f"directory hint match ({requested_directory})")

    return score, reasons


def candidate_from_known_entry(entry: dict, asset: dict) -> dict | None:
    repo_id = entry.get("repo_id", "").strip()
    filename = entry.get("filename", "").strip()
    revision = entry.get("revision", "main").strip() or "main"

    if not repo_id or not filename:
        return None

    url = build_hf_resolve_url(repo_id, revision, filename)
    score, reasons = score_candidate(asset["name"], asset["directory"], repo_id, filename)

    return {
        "repo_id": repo_id,
        "filename": filename,
        "revision": revision,
        "url": url,
        "score": max(score, 98),
        "reasons": reasons + ["known catalog match"],
        "source": "known_models",
    }


def find_known_model_match(asset: dict) -> dict | None:
    known = load_known_models()
    if not known:
        return None

    requested_name = sanitize_filename(asset.get("name", ""))
    requested_directory = asset.get("directory", "")
    requested_norm = normalize_name(requested_name)
    requested_stem = normalize_name(stem_only(requested_name))

    for _, entry in known.items():
        aliases = entry.get("aliases", []) or []
        directory = entry.get("directory", "").strip()
        if directory and directory != requested_directory:
            continue

        values = [entry.get("filename", ""), entry.get("repo_id", "")] + aliases
        normalized_values = {normalize_name(v) for v in values if v}

        if requested_norm in normalized_values or requested_stem in normalized_values:
            debug_log(
                f"known_models match asset={requested_name} directory={requested_directory} repo={entry.get('repo_id','')} file={entry.get('filename','')}"
            )
            return candidate_from_known_entry(entry, asset)

    return None


def cached_resolution_to_candidate(asset: dict, cached: dict) -> dict | None:
    repo_id = cached.get("repo_id", "").strip()
    filename = cached.get("filename", "").strip()
    revision = cached.get("revision", "main").strip() or "main"
    url = cached.get("url", "").strip()

    if not repo_id or not filename:
        return None

    if not url:
        url = build_hf_resolve_url(repo_id, revision, filename)

    return {
        "repo_id": repo_id,
        "filename": filename,
        "revision": revision,
        "url": url,
        "score": int(cached.get("confidence", 100)),
        "reasons": ["cached resolution"],
        "source": "cache",
    }


def build_search_queries(requested_name: str) -> list[str]:
    raw = sanitize_filename(requested_name or "").strip()
    stem = stem_only(raw)

    variants = []

    if raw:
        variants.append(raw)

    if stem:
        variants.append(stem)
        variants.append(stem.replace("_", " "))
        variants.append(stem.replace("-", " "))
        variants.append(stem.replace(".", " "))

    simplified = stem
    cleanup_tokens = [
        "_vae", "-vae", " vae",
        "_fp16", "-fp16", " fp16",
        "_fp8", "-fp8", " fp8",
        "_bf16", "-bf16", " bf16",
    ]
    for token in cleanup_tokens:
        simplified = simplified.replace(token, "")
    simplified = simplified.strip(" _-.")

    if simplified:
        variants.append(simplified)
        variants.append(simplified.replace("_", " "))
        variants.append(simplified.replace("-", " "))
        variants.append(simplified.replace(".", " "))

    # versión simplificada: v2.1 -> v2
    version_simplified = re.sub(r"v(\d+)\.\d+", r"v\1", stem, flags=re.IGNORECASE)
    if version_simplified and version_simplified != stem:
        variants.append(version_simplified)
        variants.append(version_simplified.replace("_", " "))
        variants.append(version_simplified.replace(".", " "))

    seen = set()
    out = []
    for v in variants:
        v = v.strip()
        if not v:
            continue
        key = v.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(v)

    return out[:8]


def safe_list_models(api: HfApi, query: str):
    """
    Compatible con distintas versiones de huggingface_hub.
    """
    debug_log(f"HF list_models query={query}")
    attempts = [
        {"search": query, "limit": MAX_REPOS_TO_CHECK, "sort": "downloads", "direction": -1},
        {"search": query, "limit": MAX_REPOS_TO_CHECK, "sort": "downloads"},
        {"search": query, "limit": MAX_REPOS_TO_CHECK},
    ]

    last_error = None
    for params in attempts:
        try:
            result = list(api.list_models(**params))
            debug_log(f"HF list_models query={query} ok params={params} repos={len(result)}")
            return result
        except TypeError as e:
            last_error = e
            debug_log(f"HF list_models query={query} typeerror params={params} error={e}")
            continue
        except Exception as e:
            last_error = e
            debug_log(f"HF list_models query={query} error={e}")
            continue

    debug_log(f"HF list_models query={query} failed last_error={last_error}")
    return []


def list_hf_candidates(asset: dict) -> list[dict]:
    requested_name = sanitize_filename(asset.get("name", ""))
    requested_directory = asset.get("directory", "")
    queries = build_search_queries(requested_name)

    debug_log(
        f"HF search start asset={requested_name} directory={requested_directory} queries={queries}"
    )

    if not queries:
        debug_log("HF search aborted: no queries")
        return []

    api = HfApi()
    candidates = []
    seen_repo = set()
    seen_files = set()
    repos = []

    for query in queries:
        partial = safe_list_models(api, query)
        for repo in partial:
            repo_id = getattr(repo, "id", None) or getattr(repo, "modelId", None)
            if not repo_id:
                continue
            if repo_id.lower() in seen_repo:
                continue
            seen_repo.add(repo_id.lower())
            repos.append(repo)

    debug_log(f"HF repo pool asset={requested_name} unique_repos={len(repos)}")

    for repo in repos:
        repo_id = getattr(repo, "id", None) or getattr(repo, "modelId", None)
        if not repo_id:
            continue

        try:
            info = api.model_info(repo_id)
        except Exception as e:
            debug_log(f"HF model_info repo={repo_id} error={e}")
            continue

        revision = getattr(info, "sha", None) or "main"
        siblings = getattr(info, "siblings", None) or []
        debug_log(f"HF inspect repo={repo_id} files={len(siblings)}")

        for sib in siblings:
            rfilename = getattr(sib, "rfilename", None)
            if not rfilename:
                continue

            filename_base = Path(rfilename).name
            ext = Path(filename_base).suffix.lower()
            if ext not in ALLOWED_FILE_EXTENSIONS:
                continue

            score, reasons = score_candidate(
                requested_name=requested_name,
                requested_directory=requested_directory,
                repo_id=repo_id,
                filename=filename_base,
            )

            if score < AMBIGUOUS_MIN_SCORE:
                continue

            key = f"{repo_id}|{rfilename}".lower()
            if key in seen_files:
                continue
            seen_files.add(key)

            candidate = {
                "repo_id": repo_id,
                "filename": rfilename,
                "revision": revision,
                "url": build_hf_resolve_url(repo_id, revision, rfilename),
                "score": score,
                "reasons": reasons,
                "source": "huggingface_search",
            }
            candidates.append(candidate)

    candidates.sort(key=lambda x: x["score"], reverse=True)

    debug_log(
        f"HF search done asset={requested_name} directory={requested_directory} candidates={len(candidates)}"
    )
    for c in candidates[:5]:
        debug_log(
            f"candidate score={c['score']} repo={c['repo_id']} file={c['filename']} reasons={c.get('reasons', [])}"
        )

    return candidates[:MAX_CANDIDATES]


def choose_best_candidate(candidates: list[dict]) -> tuple[dict | None, bool]:
    if not candidates:
        debug_log("choose_best_candidate: no candidates")
        return None, False

    top = candidates[0]
    if len(candidates) == 1:
        auto = top["score"] >= AUTO_RESOLVE_SCORE
        debug_log(
            f"choose_best_candidate: single candidate score={top['score']} auto={auto} repo={top['repo_id']} file={top['filename']}"
        )
        return top, auto

    second = candidates[1]
    gap = top["score"] - second["score"]
    auto = top["score"] >= AUTO_RESOLVE_SCORE and gap >= 8

    debug_log(
        f"choose_best_candidate: top={top['score']} second={second['score']} gap={gap} auto={auto} repo={top['repo_id']} file={top['filename']}"
    )
    return top, auto


def asset_with_candidate(asset: dict, candidate: dict, resolved: bool, resolver_status: str, candidates: list[dict] | None = None) -> dict:
    updated = {
        **asset,
        "repo_id": candidate.get("repo_id", ""),
        "revision": candidate.get("revision", "main"),
        "url": candidate.get("url", ""),
        "name": sanitize_filename(Path(candidate.get("filename", asset.get("name", ""))).name),
        "resolved": resolved,
        "resolver_status": resolver_status,
        "resolver_score": candidate.get("score", 0),
        "resolver_source": candidate.get("source", ""),
        "resolver_reasons": candidate.get("reasons", []),
    }
    if candidates is not None:
        updated["candidates"] = candidates
        updated["candidate_count"] = len(candidates)
    return updated


def resolve_asset(asset: dict) -> dict:
    debug_log(
        f"resolve_asset start asset={asset.get('name','')} directory={asset.get('directory','')} source={asset.get('source','')}"
    )

    if asset.get("url"):
        debug_log(f"resolve_asset already provided asset={asset.get('name','')}")
        return {
            **asset,
            "resolved": True,
            "resolver_status": "provided",
            "resolver_score": 100,
            "resolver_source": asset.get("source", "provided"),
            "candidate_count": 0,
        }

    cached = get_cached_resolution(asset.get("name", ""), asset.get("directory", ""))
    if cached:
        candidate = cached_resolution_to_candidate(asset, cached)
        if candidate:
            debug_log(
                f"resolve_asset cache hit asset={asset.get('name','')} repo={candidate.get('repo_id','')} file={candidate.get('filename','')}"
            )
            return asset_with_candidate(asset, candidate, True, "resolved_from_cache")

    known_candidate = find_known_model_match(asset)
    if known_candidate:
        debug_log(
            f"resolve_asset known catalog hit asset={asset.get('name','')} repo={known_candidate.get('repo_id','')} file={known_candidate.get('filename','')}"
        )
        set_cached_resolution(
            asset.get("name", ""),
            asset.get("directory", ""),
            {
                "repo_id": known_candidate["repo_id"],
                "filename": known_candidate["filename"],
                "revision": known_candidate["revision"],
                "url": known_candidate["url"],
                "confidence": known_candidate["score"],
            },
        )
        return asset_with_candidate(asset, known_candidate, True, "resolved_from_catalog")

    hf_candidates = list_hf_candidates(asset)
    best, auto = choose_best_candidate(hf_candidates)

    if best and auto:
        debug_log(
            f"resolve_asset auto resolved asset={asset.get('name','')} repo={best.get('repo_id','')} file={best.get('filename','')} score={best.get('score',0)}"
        )
        set_cached_resolution(
            asset.get("name", ""),
            asset.get("directory", ""),
            {
                "repo_id": best["repo_id"],
                "filename": best["filename"],
                "revision": best["revision"],
                "url": best["url"],
                "confidence": best["score"],
            },
        )
        return asset_with_candidate(asset, best, True, "resolved_auto", hf_candidates)

    if best and hf_candidates:
        debug_log(
            f"resolve_asset ambiguous asset={asset.get('name','')} candidates={len(hf_candidates)} top_repo={best.get('repo_id','')} top_file={best.get('filename','')}"
        )
        return {
            **asset,
            "resolved": False,
            "resolver_status": "ambiguous",
            "candidate_count": len(hf_candidates),
            "candidates": hf_candidates,
        }

    debug_log(f"resolve_asset unresolved asset={asset.get('name','')}")
    return {
        **asset,
        "resolved": False,
        "resolver_status": "unresolved",
        "candidate_count": 0,
        "candidates": [],
    }


def resolve_assets(assets: list[dict]) -> list[dict]:
    debug_log(f"resolve_assets start total={len(assets)}")
    resolved = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        resolved.append(resolve_asset(asset))
    debug_log(f"resolve_assets done total={len(resolved)}")
    return resolved


def confirm_candidate(asset: dict, candidate: dict) -> dict:
    debug_log(
        f"confirm_candidate asset={asset.get('name','')} repo={candidate.get('repo_id','')} file={candidate.get('filename','')}"
    )

    resolution = {
        "repo_id": candidate.get("repo_id", "").strip(),
        "filename": candidate.get("filename", "").strip(),
        "revision": candidate.get("revision", "main").strip() or "main",
        "url": candidate.get("url", "").strip(),
        "confidence": int(candidate.get("score", 100)),
    }

    set_cached_resolution(
        asset.get("name", ""),
        asset.get("directory", ""),
        resolution,
    )

    return asset_with_candidate(asset, {
        **candidate,
        "source": "confirmed_manual",
    }, True, "resolved_manual")