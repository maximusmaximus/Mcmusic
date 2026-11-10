#!/usr/bin/env python3
"""
model_registry.py — Single-Source-of-Truth Venice AI Model Registry Loader & Validator

Provides zero-dependency lookup of active Venice AI models, ordered fallbacks,
Venice-specific request parameters (e.g. disable_thinking on hybrid Qwen models),
and cohesive VØIDRIDE album budget constants across all pipeline scripts.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REQUIRED_ROLES = {
    "music.main_instrumental",
    "music.dark_texture",
    "music.main_vocal",
    "music.foley_sfx",
    "llm.proposals",
    "llm.showrunner",
    "llm.creative_director",
    "llm.image_prompt",
    "image.cover_primary",
    "image.edit",
}

VALID_MODALITIES = {"music", "text", "image", "inpaint", "asr", "upscale"}

HYBRID_THINKING_PREFIXES = ("qwen-3-7", "qwen-3-6", "qwen-3-8", "qwen3-235b-a22b-thinking", "kimi-k3")

DEFAULT_REGISTRY: Dict[str, Any] = {
    "schema_version": "1.0",
    "budget_policy": {
        "weekly_canary_cap_usd": 1.50,
        "voidride_durations": {"tracks": [220, 224, 218, 216], "closer": 236},
        "estimated_costs_usd": {
            "single_track": 3.16,
            "closer_track": 3.16,
            "tracks_total": 15.80,
            "covers_total": 0.52,
            "album_total": 16.32,
            "avg_track": 3.16,
        },
    },
    "roles": {
        "music.main_instrumental": {
            "primary": "elevenlabs-music",
            "fallbacks": ["elevenlabs-music-v2", "elevenlabs-music-v2-5"],
            "modality": "music",
            "params": {"max_prompt_chars": 2000, "supports_duration": True, "supports_instrumental": True},
        },
        "music.dark_texture": {
            "primary": "stable-audio-25",
            "fallbacks": ["mmaudio-v2-text-to-audio"],
            "modality": "music",
            "params": {"max_prompt_chars": 500, "supports_duration": True, "supports_instrumental": False},
        },
        "music.main_vocal": {
            "primary": "ace-step-15",
            "fallbacks": ["minimax-music-v26", "minimax-music-v2"],
            "modality": "music",
            "params": {"max_prompt_chars": 2000, "supports_duration": True, "supports_lyrics": True},
        },
        "music.foley_sfx": {
            "primary": "elevenlabs-sound-effects-v2",
            "fallbacks": ["mmaudio-v2-text-to-audio"],
            "modality": "music",
            "params": {"max_prompt_chars": 500, "supports_duration": False},
        },
        "llm.proposals": {
            "primary": "qwen-3-7-plus",
            "fallbacks": ["deepseek-v4-flash", "qwen-3-8-flash"],
            "modality": "text",
            "params": {
                "temperature": 0.9,
                "max_tokens": 4800,
                "venice_parameters": {
                    "include_venice_system_prompt": False,
                    "strip_thinking_response": True,
                    "disable_thinking": True,
                },
            },
        },
        "llm.showrunner": {
            "primary": "deepseek-v4-flash",
            "fallbacks": ["qwen-3-7-plus", "qwen-3-8-flash"],
            "modality": "text",
            "params": {"temperature": 0.6, "max_tokens": 5500, "venice_parameters": {"strip_thinking_response": True}},
        },
        "llm.creative_director": {
            "primary": "deepseek-v4-flash",
            "fallbacks": ["qwen-3-7-plus", "qwen-3-8-flash"],
            "modality": "text",
            "params": {"temperature": 0.55, "max_tokens": 3500, "venice_parameters": {"strip_thinking_response": True}},
        },
        "llm.image_prompt": {
            "primary": "deepseek-v4-flash",
            "fallbacks": ["qwen-3-7-plus", "qwen-3-8-flash"],
            "modality": "text",
            "params": {"temperature": 0.7, "max_tokens": 900, "venice_parameters": {"strip_thinking_response": True}},
        },
        "image.cover_primary": {
            "primary": "qwen-image-3-pro",
            "fallbacks": ["grok-imagine-image-2-0", "grok-imagine-image", "flux-2-max"],
            "modality": "image",
            "params": {"resolution": "1024x1024", "upscale_scale": 4, "upscale_creativity": 0.01},
        },
        "image.edit": {
            "primary": "qwen-image-3-edit",
            "fallbacks": ["qwen-image-3-pro-edit", "seedream-v5-5-edit"],
            "modality": "inpaint",
            "params": {"enhance_prompt": True},
        },
    },
    "music_model_specs": {},
    "rejected_candidates": {},
}


def resolve_registry_path(custom_path: Optional[str] = None) -> Path:
    if custom_path:
        return Path(custom_path)
    env_override = os.environ.get("VENICE_MODEL_REGISTRY_PATH")
    if env_override and os.path.exists(env_override):
        return Path(env_override)

    here = Path(__file__).resolve()
    # Relative to data/scripts/model_registry.py -> data/config/model_registry.json
    rel_candidate = here.parent.parent / "config" / "model_registry.json"
    if rel_candidate.exists():
        return rel_candidate

    for candidate in [
        Path("/opt/data/config/model_registry.json"),
        Path(r"D:\hermes-music\data\config\model_registry.json"),
        Path(r"D:\sp2\data\config\model_registry.json"),
    ]:
        if candidate.exists():
            return candidate
    return rel_candidate


def load_registry(custom_path: Optional[str] = None) -> Dict[str, Any]:
    path = resolve_registry_path(custom_path)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            ok, _ = validate_registry_schema(data)
            if ok:
                return data
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULT_REGISTRY))


def validate_registry_schema(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    if not isinstance(data, dict):
        return False, ["Registry root must be a JSON object"]
    if str(data.get("schema_version", "")) != "1.0":
        errors.append(f"Unsupported schema_version: {data.get('schema_version')!r}")

    roles = data.get("roles")
    if not isinstance(roles, dict):
        errors.append("'roles' must be a dict")
        return False, errors

    missing = sorted(REQUIRED_ROLES - set(roles.keys()))
    if missing:
        errors.append(f"Missing required roles: {', '.join(missing)}")

    for role_name, spec in roles.items():
        if not isinstance(spec, dict):
            errors.append(f"Role '{role_name}' must be an object")
            continue
        primary = str(spec.get("primary", "")).strip()
        if not primary:
            errors.append(f"Role '{role_name}' has empty primary model")
        fallbacks = spec.get("fallbacks", [])
        if not isinstance(fallbacks, list) or any(not str(m).strip() for m in fallbacks):
            errors.append(f"Role '{role_name}' fallbacks must be a list of non-empty strings")
        modality = spec.get("modality", "")
        if modality not in VALID_MODALITIES:
            errors.append(f"Role '{role_name}' has invalid modality '{modality}'")

    bp = data.get("budget_policy", {})
    if not isinstance(bp, dict) or float(bp.get("weekly_canary_cap_usd", 0)) <= 0:
        errors.append("budget_policy.weekly_canary_cap_usd must be > 0")

    return len(errors) == 0, errors


def get_primary_model(role: str, default: str = "", custom_path: Optional[str] = None) -> str:
    reg = load_registry(custom_path)
    role_spec = reg.get("roles", {}).get(role, {})
    return str(role_spec.get("primary") or default).strip()


def get_role_chain(role: str, default_chain: Optional[List[str]] = None, custom_path: Optional[str] = None) -> List[str]:
    """Return deduplicated [primary, *fallbacks] list for a given role."""
    reg = load_registry(custom_path)
    role_spec = reg.get("roles", {}).get(role, {})
    raw = []
    if role_spec.get("primary"):
        raw.append(str(role_spec["primary"]).strip())
    for fb in role_spec.get("fallbacks", []):
        if fb and str(fb).strip() not in raw:
            raw.append(str(fb).strip())
    if not raw and default_chain:
        return list(default_chain)
    return raw


def build_venice_parameters(model_id: str, role: Optional[str] = None, extra: Optional[Dict[str, Any]] = None, custom_path: Optional[str] = None) -> Dict[str, Any]:
    """Return safe venice_parameters for a text model, automatically disabling thinking token starvation on hybrid models."""
    reg = load_registry(custom_path)
    params: Dict[str, Any] = {"strip_thinking_response": True}
    if role:
        role_vp = reg.get("roles", {}).get(role, {}).get("params", {}).get("venice_parameters", {})
        if isinstance(role_vp, dict):
            params.update(role_vp)
    if any(model_id.startswith(pfx) for pfx in HYBRID_THINKING_PREFIXES) or "qwen" in model_id.lower():
        if "kimi-k3" not in model_id.lower():
            params["disable_thinking"] = True
    if extra:
        params.update(extra)
    return params


def get_music_model_specs(custom_path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    reg = load_registry(custom_path)
    specs = reg.get("music_model_specs", {})
    return dict(specs) if isinstance(specs, dict) else {}


def get_budget_policy(custom_path: Optional[str] = None) -> Dict[str, Any]:
    reg = load_registry(custom_path)
    return dict(reg.get("budget_policy", DEFAULT_REGISTRY["budget_policy"]))


if __name__ == "__main__":
    reg = load_registry()
    ok, errs = validate_registry_schema(reg)
    if not ok:
        raise SystemExit("Registry validation failed: " + "; ".join(errs))
    print(f"[model_registry] Validated {len(reg['roles'])} roles from {resolve_registry_path()}")
    for r_name, r_spec in reg["roles"].items():
        print(f"  {r_name:26s} -> {r_spec['primary']} (fallbacks: {', '.join(r_spec.get('fallbacks', []))})")
