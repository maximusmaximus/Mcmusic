#!/usr/bin/env python3
"""
Producer Profiles — Create, manage, and use reusable producer identities.

Each profile stores: style preferences, default models, mastering settings,
prompt prefix, and a catalog of linked productions.

Usage:
    python3 profiles.py ACTION [OPTIONS]

Actions:
    create    Create a new producer profile
    list      List all profiles
    show      Show profile details
    select    Set a profile as active
    active    Show the currently active profile
    update    Modify profile settings
    link      Add a production to a profile's catalog
    catalog   View a profile's production catalog
    delete    Delete a profile
    export    Export profile JSON to stdout
    produce   Run master-producer with active profile defaults
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

PROFILES_DIR = "/opt/data/music/profiles"
ACTIVE_FILE = os.path.join(PROFILES_DIR, ".active")
MASTER_PRODUCER = "/opt/data/skills/master-producer/master-producer/scripts/master-producer.py"


def log(msg):
    print(f"[profiles] {msg}", file=sys.stderr, flush=True)


def slugify(text, max_len=40):
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    text = text.strip('-')
    if len(text) > max_len:
        text = text[:max_len].rsplit('-', 1)[0]
    return text or 'untitled'


def profile_path(slug):
    return os.path.join(PROFILES_DIR, slug, "profile.json")


def load_profile(slug):
    path = profile_path(slug)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def save_profile(profile):
    slug = profile["slug"]
    dirpath = os.path.join(PROFILES_DIR, slug)
    os.makedirs(dirpath, exist_ok=True)
    with open(profile_path(slug), "w") as f:
        json.dump(profile, f, indent=2)


def find_profile_slug(name):
    """Find profile slug by name (case-insensitive) or slug."""
    slug = slugify(name)
    if os.path.exists(profile_path(slug)):
        return slug
    # Search by name
    for entry in os.listdir(PROFILES_DIR):
        path = os.path.join(PROFILES_DIR, entry, "profile.json")
        if os.path.isfile(path):
            with open(path) as f:
                p = json.load(f)
                if p.get("name", "").lower() == name.lower():
                    return p["slug"]
    return None


def get_active_slug():
    if os.path.exists(ACTIVE_FILE):
        with open(ACTIVE_FILE) as f:
            return f.read().strip()
    return None


def set_active_slug(slug):
    os.makedirs(PROFILES_DIR, exist_ok=True)
    with open(ACTIVE_FILE, "w") as f:
        f.write(slug)


def list_profiles():
    os.makedirs(PROFILES_DIR, exist_ok=True)
    active_slug = get_active_slug()
    profiles = []
    for entry in sorted(os.listdir(PROFILES_DIR)):
        path = os.path.join(PROFILES_DIR, entry, "profile.json")
        if os.path.isfile(path):
            with open(path) as f:
                p = json.load(f)
                p["_active"] = (entry == active_slug)
                profiles.append(p)
    return profiles


# ── Actions ──────────────────────────────────────────────


def cmd_create(args):
    name = args.name
    slug = slugify(name)

    if os.path.exists(profile_path(slug)):
        print(json.dumps({"success": False, "error": f"Profile '{name}' already exists"}))
        return

    genres = [g.strip() for g in args.genres.split(",")] if args.genres else []

    profile = {
        "name": name,
        "slug": slug,
        "created_at": datetime.now(tz=__import__("datetime").timezone.utc).isoformat() + "Z",
        "updated_at": datetime.now(tz=__import__("datetime").timezone.utc).isoformat() + "Z",
        "description": args.description or "",
        "style": {
            "genres": genres,
            "mood": args.mood or "",
            "instruments": args.instruments or "",
            "influences": args.influences or "",
            "era": args.era or "",
        },
        "defaults": {
            "main_model": args.main_model or "minimax-music-v2",
            "quality": args.quality or "standard",
            "duration": args.duration or 60,
            "instrumental": args.instrumental or False,
        },
        "mastering": {
            "target_lufs": args.target_lufs or -14,
            "bass_boost_db": args.bass_boost or 1.0,
            "presence_boost_db": args.presence_boost or 2.0,
            "air_boost_db": args.air_boost or 1.5,
            "compression_ratio": args.compression_ratio or 4,
        },
        "prompt_prefix": args.prompt_prefix or "",
        "catalog": [],
    }

    # Auto-generate prompt_prefix if not provided
    if not profile["prompt_prefix"] and (genres or args.mood or args.instruments):
        parts = []
        if genres:
            parts.append(", ".join(genres))
        if args.mood:
            parts.append(args.mood)
        if args.instruments:
            parts.append(args.instruments)
        if args.influences:
            parts.append(f"inspired by {args.influences}")
        profile["prompt_prefix"] = ", ".join(parts)

    save_profile(profile)

    # Auto-select if first profile
    if len(list_profiles()) == 1:
        set_active_slug(slug)
        log(f"Auto-selected '{name}' as active profile (first profile)")

    result = {
        "success": True,
        "action": "created",
        "profile": profile,
    }
    print(json.dumps(result, indent=2))


def cmd_list(args):
    profiles = list_profiles()
    if not profiles:
        print(json.dumps({"success": True, "profiles": [], "message": "No profiles yet. Create one!"}))
        return

    summary = []
    for p in profiles:
        marker = " ★ ACTIVE" if p.get("_active") else ""
        summary.append({
            "name": p["name"],
            "slug": p["slug"],
            "description": p.get("description", "")[:80],
            "genres": p.get("style", {}).get("genres", []),
            "productions": len(p.get("catalog", [])),
            "active": p.get("_active", False),
        })

    print(json.dumps({"success": True, "profiles": summary}, indent=2))


def cmd_show(args):
    slug = find_profile_slug(args.name)
    if not slug:
        print(json.dumps({"success": False, "error": f"Profile '{args.name}' not found"}))
        return

    profile = load_profile(slug)
    profile["_active"] = (slug == get_active_slug())
    print(json.dumps({"success": True, "profile": profile}, indent=2))


def cmd_select(args):
    slug = find_profile_slug(args.name)
    if not slug:
        print(json.dumps({"success": False, "error": f"Profile '{args.name}' not found"}))
        return

    set_active_slug(slug)
    profile = load_profile(slug)
    print(json.dumps({
        "success": True,
        "action": "selected",
        "active_profile": profile["name"],
        "prompt_prefix": profile.get("prompt_prefix", ""),
        "defaults": profile.get("defaults", {}),
    }, indent=2))


def cmd_active(args):
    slug = get_active_slug()
    if not slug:
        print(json.dumps({"success": True, "active": None, "message": "No active profile. Use 'select' to set one."}))
        return

    profile = load_profile(slug)
    if not profile:
        print(json.dumps({"success": False, "error": f"Active profile '{slug}' not found on disk"}))
        return

    if getattr(args, 'json_output', False):
        # Machine-readable output for piping
        print(json.dumps(profile))
    else:
        print(json.dumps({"success": True, "active": profile}, indent=2))


def cmd_update(args):
    slug = find_profile_slug(args.name)
    if not slug:
        print(json.dumps({"success": False, "error": f"Profile '{args.name}' not found"}))
        return

    profile = load_profile(slug)
    changed = []

    # Update style fields
    if args.description:
        profile["description"] = args.description
        changed.append("description")
    if args.genres:
        profile["style"]["genres"] = [g.strip() for g in args.genres.split(",")]
        changed.append("genres")
    if args.mood:
        profile["style"]["mood"] = args.mood
        changed.append("mood")
    if args.instruments:
        profile["style"]["instruments"] = args.instruments
        changed.append("instruments")
    if args.influences:
        profile["style"]["influences"] = args.influences
        changed.append("influences")
    if args.era:
        profile["style"]["era"] = args.era
        changed.append("era")
    if args.prompt_prefix:
        profile["prompt_prefix"] = args.prompt_prefix
        changed.append("prompt_prefix")

    # Update defaults
    if args.main_model:
        profile["defaults"]["main_model"] = args.main_model
        changed.append("main_model")
    if args.quality:
        profile["defaults"]["quality"] = args.quality
        changed.append("quality")
    if args.duration:
        profile["defaults"]["duration"] = args.duration
        changed.append("duration")
    if args.instrumental is not None:
        profile["defaults"]["instrumental"] = args.instrumental
        changed.append("instrumental")

    # Update mastering
    if args.target_lufs:
        profile["mastering"]["target_lufs"] = args.target_lufs
        changed.append("target_lufs")
    if args.bass_boost:
        profile["mastering"]["bass_boost_db"] = args.bass_boost
        changed.append("bass_boost")
    if args.presence_boost:
        profile["mastering"]["presence_boost_db"] = args.presence_boost
        changed.append("presence_boost")
    if args.air_boost:
        profile["mastering"]["air_boost_db"] = args.air_boost
        changed.append("air_boost")

    profile["updated_at"] = datetime.now(tz=__import__("datetime").timezone.utc).isoformat() + "Z"
    save_profile(profile)

    print(json.dumps({
        "success": True,
        "action": "updated",
        "profile": profile["name"],
        "changed": changed,
    }, indent=2))


def cmd_link(args):
    slug = find_profile_slug(args.name)
    if not slug:
        print(json.dumps({"success": False, "error": f"Profile '{args.name}' not found"}))
        return

    profile = load_profile(slug)

    entry = {
        "title": args.title or os.path.basename(args.file),
        "file": args.file,
        "linked_at": datetime.now(tz=__import__("datetime").timezone.utc).isoformat() + "Z",
        "notes": args.notes or "",
    }

    # Check if file exists
    if not os.path.exists(args.file):
        log(f"Warning: File '{args.file}' not found — linking anyway")

    profile["catalog"].append(entry)
    profile["updated_at"] = datetime.now(tz=__import__("datetime").timezone.utc).isoformat() + "Z"
    save_profile(profile)

    print(json.dumps({
        "success": True,
        "action": "linked",
        "profile": profile["name"],
        "entry": entry,
        "catalog_size": len(profile["catalog"]),
    }, indent=2))


def cmd_purge(args):
    """Remove catalog entries that aren't published on SoundCloud."""
    slug = find_profile_slug(args.name)
    if not slug:
        print(json.dumps({"success": False, "error": f"Profile '{args.name}' not found"}))
        return

    profile = load_profile(slug)
    catalog = profile.get("catalog", [])
    old_count = len(catalog)

    # Keep only entries with a soundcloud_url
    published = [c for c in catalog if c.get("soundcloud_url")]
    purged_count = old_count - len(published)

    profile["catalog"] = published
    profile["updated_at"] = datetime.now(tz=__import__("datetime").timezone.utc).isoformat() + "Z"

    # Reset sonic_dna if catalog is empty
    if not published:
        profile.pop("sonic_dna", None)

    save_profile(profile)

    print(json.dumps({
        "success": True,
        "action": "purged",
        "profile": profile["name"],
        "purged": purged_count,
        "kept": len(published),
        "total_was": old_count,
    }, indent=2))


def cmd_publish(args):
    """Mark a catalog entry as published on SoundCloud."""
    slug = find_profile_slug(args.name)
    if not slug:
        print(json.dumps({"success": False, "error": f"Profile '{args.name}' not found"}))
        return

    profile = load_profile(slug)
    catalog = profile.get("catalog", [])

    # Find matching entry by title (most recent match)
    matched = None
    for entry in reversed(catalog):
        if entry.get("title", "").lower() == args.title.lower():
            matched = entry
            break

    if not matched:
        # Try partial match
        for entry in reversed(catalog):
            if args.title.lower() in entry.get("title", "").lower():
                matched = entry
                break

    if not matched:
        print(json.dumps({"success": False, "error": f"Track '{args.title}' not found in catalog"}))
        return

    matched["soundcloud_url"] = args.url
    matched["published_at"] = datetime.now(tz=__import__("datetime").timezone.utc).isoformat() + "Z"
    profile["updated_at"] = datetime.now(tz=__import__("datetime").timezone.utc).isoformat() + "Z"
    save_profile(profile)

    print(json.dumps({
        "success": True,
        "action": "published",
        "profile": profile["name"],
        "title": matched["title"],
        "soundcloud_url": args.url,
    }, indent=2))


def cmd_catalog(args):
    slug = find_profile_slug(args.name)
    if not slug:
        print(json.dumps({"success": False, "error": f"Profile '{args.name}' not found"}))
        return

    profile = load_profile(slug)
    catalog = profile.get("catalog", [])

    # Check which files still exist
    for entry in catalog:
        entry["exists"] = os.path.exists(entry.get("file", ""))

    print(json.dumps({
        "success": True,
        "profile": profile["name"],
        "catalog": catalog,
        "total": len(catalog),
    }, indent=2))


def cmd_delete(args):
    slug = find_profile_slug(args.name)
    if not slug:
        print(json.dumps({"success": False, "error": f"Profile '{args.name}' not found"}))
        return

    profile = load_profile(slug)
    profile_dir = os.path.join(PROFILES_DIR, slug)

    # Remove profile.json
    os.remove(profile_path(slug))
    # Remove directory if empty
    try:
        os.rmdir(profile_dir)
    except OSError:
        pass

    # Clear active if this was the active profile
    if get_active_slug() == slug:
        if os.path.exists(ACTIVE_FILE):
            os.remove(ACTIVE_FILE)

    print(json.dumps({
        "success": True,
        "action": "deleted",
        "profile": profile["name"],
    }, indent=2))


def cmd_export(args):
    slug = find_profile_slug(args.name)
    if not slug:
        print(json.dumps({"success": False, "error": f"Profile '{args.name}' not found"}))
        return

    profile = load_profile(slug)
    print(json.dumps(profile, indent=2))


def cmd_produce(args):
    """Run master-producer using the active profile's defaults."""
    slug = get_active_slug()
    if not slug:
        print(json.dumps({"success": False, "error": "No active profile. Use 'select' first."}))
        return

    profile = load_profile(slug)
    if not profile:
        print(json.dumps({"success": False, "error": f"Active profile '{slug}' not found on disk"}))
        return

    defaults = profile.get("defaults", {})
    prefix = profile.get("prompt_prefix", "")

    # Merge prompt: profile prefix + user prompt
    user_prompt = args.prompt or ""
    if prefix and user_prompt:
        full_prompt = f"{prefix}, {user_prompt}"
    elif prefix:
        full_prompt = prefix
    elif user_prompt:
        full_prompt = user_prompt
    else:
        print(json.dumps({"success": False, "error": "No prompt provided and profile has no prompt_prefix"}))
        return

    # Build master-producer command
    cmd = [
        sys.executable, MASTER_PRODUCER,
        "--prompt", full_prompt,
        "--quality", args.quality or defaults.get("quality", "standard"),
        "--duration", str(args.duration or defaults.get("duration", 60)),
        "--output", "/opt/data/music",
    ]

    if args.main_model or defaults.get("main_model"):
        cmd.extend(["--main-model", args.main_model or defaults["main_model"]])

    if args.lyrics:
        cmd.extend(["--lyrics", args.lyrics])
    elif defaults.get("instrumental"):
        # Note: instrumental flag is handled by model selection in master-producer
        pass

    log(f"")
    log(f"╔══════════════════════════════════════════════════════════╗")
    log(f"║  🎵 Producing as: {profile['name']:<38} ║")
    log(f"╚══════════════════════════════════════════════════════════╝")
    log(f"  Profile:  {profile['name']}")
    log(f"  Genres:   {', '.join(profile.get('style', {}).get('genres', []))}")
    log(f"  Mood:     {profile.get('style', {}).get('mood', 'N/A')}")
    log(f"  Model:    {defaults.get('main_model', 'auto')}")
    log(f"  Quality:  {args.quality or defaults.get('quality', 'standard')}")
    log(f"  Prompt:   {full_prompt[:100]}...")
    log(f"")

    # Run master-producer
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=900,
        env={**os.environ},
    )

    # Forward stderr (progress logs)
    if result.stderr:
        for line in result.stderr.strip().split("\n"):
            log(line)

    if result.returncode != 0:
        print(json.dumps({"success": False, "error": f"Master producer failed (exit {result.returncode})"}))
        return

    # Parse master-producer output
    try:
        prod_result = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(json.dumps({"success": False, "error": "Could not parse master-producer output"}))
        return

    # Auto-link to catalog
    if prod_result.get("success") and prod_result.get("file"):
        title_slug = slugify(user_prompt or "production", max_len=50)
        entry = {
            "title": title_slug.replace("-", " ").title(),
            "file": prod_result["file"],
            "linked_at": datetime.now(tz=__import__("datetime").timezone.utc).isoformat() + "Z",
            "notes": f"Auto-linked from produce command. Quality: {prod_result.get('quality', 'unknown')}",
        }
        profile["catalog"].append(entry)
        profile["updated_at"] = datetime.now(tz=__import__("datetime").timezone.utc).isoformat() + "Z"
        save_profile(profile)
        prod_result["linked_to_profile"] = profile["name"]
        prod_result["catalog_entry"] = entry

    print(json.dumps(prod_result, indent=2))


# ── CLI Parser ───────────────────────────────────────────


def build_parser():
    parser = argparse.ArgumentParser(description="Producer Profiles Manager")
    sub = parser.add_subparsers(dest="action", help="Action to perform")

    # -- create --
    p_create = sub.add_parser("create", help="Create a new profile")
    p_create.add_argument("--name", required=True)
    p_create.add_argument("--description", default="")
    p_create.add_argument("--genres", default="")
    p_create.add_argument("--mood", default="")
    p_create.add_argument("--instruments", default="")
    p_create.add_argument("--influences", default="")
    p_create.add_argument("--era", default="")
    p_create.add_argument("--prompt-prefix", default="")
    p_create.add_argument("--main-model", default="minimax-music-v2")
    p_create.add_argument("--quality", default="standard", choices=["quick", "standard", "premium"])
    p_create.add_argument("--duration", type=int, default=60)
    p_create.add_argument("--instrumental", action="store_true")
    p_create.add_argument("--target-lufs", type=float, default=-14)
    p_create.add_argument("--bass-boost", type=float, default=1.0)
    p_create.add_argument("--presence-boost", type=float, default=2.0)
    p_create.add_argument("--air-boost", type=float, default=1.5)
    p_create.add_argument("--compression-ratio", type=float, default=4)

    # -- list --
    sub.add_parser("list", help="List all profiles")

    # -- show --
    p_show = sub.add_parser("show", help="Show profile details")
    p_show.add_argument("--name", required=True)

    # -- select --
    p_select = sub.add_parser("select", help="Set active profile")
    p_select.add_argument("--name", required=True)

    # -- active --
    p_active = sub.add_parser("active", help="Show active profile")
    p_active.add_argument("--json", dest="json_output", action="store_true", help="Machine-readable output")

    # -- update --
    p_update = sub.add_parser("update", help="Update profile")
    p_update.add_argument("--name", required=True)
    p_update.add_argument("--description", default=None)
    p_update.add_argument("--genres", default=None)
    p_update.add_argument("--mood", default=None)
    p_update.add_argument("--instruments", default=None)
    p_update.add_argument("--influences", default=None)
    p_update.add_argument("--era", default=None)
    p_update.add_argument("--prompt-prefix", default=None)
    p_update.add_argument("--main-model", default=None)
    p_update.add_argument("--quality", default=None, choices=["quick", "standard", "premium"])
    p_update.add_argument("--duration", type=int, default=None)
    p_update.add_argument("--instrumental", action="store_true", default=None)
    p_update.add_argument("--target-lufs", type=float, default=None)
    p_update.add_argument("--bass-boost", type=float, default=None)
    p_update.add_argument("--presence-boost", type=float, default=None)
    p_update.add_argument("--air-boost", type=float, default=None)

    # -- link --
    p_link = sub.add_parser("link", help="Link production to profile")
    p_link.add_argument("--name", required=True)
    p_link.add_argument("--file", required=True)
    p_link.add_argument("--title", default=None)
    p_link.add_argument("--notes", default=None)

    # -- catalog --
    p_catalog = sub.add_parser("catalog", help="View profile catalog")
    p_catalog.add_argument("--name", required=True)

    # -- delete --
    p_delete = sub.add_parser("delete", help="Delete profile")
    p_delete.add_argument("--name", required=True)

    # -- export --
    p_export = sub.add_parser("export", help="Export profile JSON")
    p_export.add_argument("--name", required=True)

    # -- purge --
    p_purge = sub.add_parser("purge", help="Remove unpublished tracks from catalog")
    p_purge.add_argument("--name", required=True)

    # -- publish --
    p_publish = sub.add_parser("publish", help="Mark a track as published on SoundCloud")
    p_publish.add_argument("--name", required=True)
    p_publish.add_argument("--title", required=True, help="Track title to mark as published")
    p_publish.add_argument("--url", required=True, help="SoundCloud URL")

    # -- produce --
    p_produce = sub.add_parser("produce", help="Produce with active profile")
    p_produce.add_argument("--prompt", default=None)
    p_produce.add_argument("--lyrics", default=None)
    p_produce.add_argument("--quality", default=None)
    p_produce.add_argument("--duration", type=int, default=None)
    p_produce.add_argument("--main-model", default=None)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.action:
        parser.print_help()
        sys.exit(1)

    actions = {
        "create": cmd_create,
        "list": cmd_list,
        "show": cmd_show,
        "select": cmd_select,
        "active": cmd_active,
        "update": cmd_update,
        "link": cmd_link,
        "catalog": cmd_catalog,
        "purge": cmd_purge,
        "publish": cmd_publish,
        "delete": cmd_delete,
        "export": cmd_export,
        "produce": cmd_produce,
    }

    fn = actions.get(args.action)
    if fn:
        fn(args)
    else:
        print(json.dumps({"success": False, "error": f"Unknown action: {args.action}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
