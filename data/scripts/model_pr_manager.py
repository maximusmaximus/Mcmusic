#!/usr/bin/env python3
"""
model_pr_manager.py — Automated Git Worktree, GitHub PR, CI Gate, Merge & Dual-Mount Deployer

Implements best-practice GitOps for weekly Venice AI model upgrades on maximusmaximus/Mcmusic:
  1. Creates a clean temporary git worktree off origin/main (never touches dirty runtime state).
  2. Commits updated model_registry.json, venice_catalog_snapshot.json, and benchmark report.
  3. Pushes branch `chore/venice-models-YYYY-WW` and opens a Pull Request via `gh` CLI or GitHub REST API.
  4. Verifies GitHub Actions CI check-runs are 100% green before allowing `merge`.
  5. Squash-merges PR, deletes remote branch, fast-forwards host/container checkouts, snapshots, and verifies live!
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_SLUG = os.environ.get("MCMUSIC_REPO", "maximusmaximus/Mcmusic")
GITHUB_API = "https://api.github.com"


def _load_dotenv() -> None:
    for env_path in ["/opt/data/.env", "/opt/hermes/.env", r"D:\sp2\.env", r"D:\hermes-music\.env"]:
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip('"').strip("'")
                            if k and k not in os.environ:
                                os.environ[k] = v
            except Exception:
                pass


_load_dotenv()


def get_github_token() -> str:
    for var in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(var):
            return os.environ[var].strip()
    if shutil.which("gh"):
        try:
            proc = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except Exception:
            pass
    return ""


def resolve_repo_root() -> Path:
    env_root = os.environ.get("MCMUSIC_REPO_ROOT")
    if env_root and os.path.isdir(os.path.join(env_root, ".git")):
        return Path(env_root)
    here = Path(__file__).resolve()
    # data/scripts/model_pr_manager.py -> repo root is 2 parents up
    candidate = here.parent.parent.parent
    if (candidate / ".git").exists():
        return candidate
    for p in [Path(r"D:\hermes-music"), Path("/mnt/d/hermes-music"), Path(r"D:\sp2"), Path("/mnt/d/sp2")]:
        if (p / ".git").exists():
            return p
    return candidate


def _github_api_request(method: str, endpoint: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    token = get_github_token()
    if not token:
        raise RuntimeError("Missing GH_TOKEN / GITHUB_TOKEN and `gh auth token` unavailable")
    url = f"{GITHUB_API}{endpoint}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "VOIDRIDE-ModelScout/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw.strip() else {}


def _run_git(args: List[str], cwd: Path, token: str = "") -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    cmd = ["git"]
    if token:
        import base64
        basic = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
        cmd.extend(["-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {basic}"])
    cmd.extend(args)
    return subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True, timeout=120)


def check_pr_ci_status(pr_number: int) -> Tuple[bool, str, Dict[str, Any]]:
    """Verify PR exists, is open/mergeable, and all GitHub Actions check-runs on head SHA passed."""
    pr = _github_api_request("GET", f"/repos/{REPO_SLUG}/pulls/{pr_number}")
    state = pr.get("state", "")
    if state != "open":
        return False, f"PR #{pr_number} is '{state}' (not open)", pr

    head_sha = pr.get("head", {}).get("sha", "")
    if not head_sha:
        return False, f"PR #{pr_number} missing head SHA", pr

    checks = _github_api_request("GET", f"/repos/{REPO_SLUG}/commits/{head_sha}/check-runs")
    runs = checks.get("check_runs", [])
    if not runs:
        return False, f"No CI check-runs reported yet for commit {head_sha[:7]} — wait for GitHub Actions CI", pr

    pending = [r["name"] for r in runs if r.get("status") != "completed"]
    if pending:
        return False, f"CI checks still running: {', '.join(pending)}", pr

    failed = [
        f"{r['name']} ({r.get('conclusion')})"
        for r in runs
        if r.get("conclusion") not in ("success", "skipped", "neutral")
    ]
    if failed:
        return False, f"CI checks failed: {', '.join(failed)}", pr

    return True, f"All {len(runs)} CI check-run(s) passed on {head_sha[:7]}", pr


def _create_upgrade_pr_via_github_api(
    branch_name: str,
    title: str,
    body_markdown: str,
    files_to_write: Dict[str, bytes],
) -> Dict[str, Any]:
    """Container-native PR creation via GitHub Git Data REST API (works inside sp2 without a .git mount)."""
    import base64

    # Pre-validate model_registry.json schema if included
    if "data/config/model_registry.json" in files_to_write:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import model_registry
        reg_obj = json.loads(files_to_write["data/config/model_registry.json"].decode("utf-8"))
        ok, errs = model_registry.validate_registry_schema(reg_obj)
        if not ok:
            raise RuntimeError(f"Registry validation failed before PR creation: {errs}")

    main_ref = _github_api_request("GET", f"/repos/{REPO_SLUG}/git/ref/heads/main")
    base_sha = main_ref["object"]["sha"]
    base_commit = _github_api_request("GET", f"/repos/{REPO_SLUG}/git/commits/{base_sha}")
    base_tree_sha = base_commit["tree"]["sha"]

    tree_entries = []
    for rel_path, content_bytes in files_to_write.items():
        clean_rel = rel_path.replace("\\", "/").lstrip("/")
        lf_bytes = content_bytes.replace(b"\r\n", b"\n")
        blob = _github_api_request(
            "POST",
            f"/repos/{REPO_SLUG}/git/blobs",
            {"content": base64.b64encode(lf_bytes).decode("ascii"), "encoding": "base64"},
        )
        tree_entries.append({
            "path": clean_rel,
            "mode": "100644",
            "type": "blob",
            "sha": blob["sha"],
        })

    new_tree = _github_api_request(
        "POST",
        f"/repos/{REPO_SLUG}/git/trees",
        {"base_tree": base_tree_sha, "tree": tree_entries},
    )
    if new_tree["sha"] == base_tree_sha:
        return {"created": False, "reason": "no_diff"}

    new_commit = _github_api_request(
        "POST",
        f"/repos/{REPO_SLUG}/git/commits",
        {"message": title, "tree": new_tree["sha"], "parents": [base_sha]},
    )
    commit_sha = new_commit["sha"]

    try:
        _github_api_request(
            "POST",
            f"/repos/{REPO_SLUG}/git/refs",
            {"ref": f"refs/heads/{branch_name}", "sha": commit_sha},
        )
    except urllib.error.HTTPError as e:
        if e.code == 422:
            _github_api_request(
                "PATCH",
                f"/repos/{REPO_SLUG}/git/refs/heads/{branch_name}",
                {"sha": commit_sha, "force": True},
            )
        else:
            raise

    existing = _github_api_request("GET", f"/repos/{REPO_SLUG}/pulls?state=open&head=maximusmaximus:{branch_name}")
    if isinstance(existing, list) and existing:
        pr_obj = _github_api_request(
            "PATCH",
            f"/repos/{REPO_SLUG}/pulls/{existing[0]['number']}",
            {"title": title, "body": body_markdown},
        )
    else:
        pr_obj = _github_api_request(
            "POST",
            f"/repos/{REPO_SLUG}/pulls",
            {"title": title, "head": branch_name, "base": "main", "body": body_markdown},
        )

    return {
        "created": True,
        "pr_number": pr_obj["number"],
        "pr_url": pr_obj["html_url"],
        "branch": branch_name,
        "head_sha": pr_obj.get("head", {}).get("sha", commit_sha),
    }


def create_upgrade_pr(
    branch_name: str,
    title: str,
    body_markdown: str,
    files_to_write: Dict[str, bytes],
    run_local_tests: bool = True,
) -> Dict[str, Any]:
    """Cut an isolated git worktree from origin/main (or use GitHub Git Data API inside sp2), push, and open PR."""
    repo_root = resolve_repo_root()
    token = get_github_token()
    if not (repo_root / ".git").exists():
        return _create_upgrade_pr_via_github_api(branch_name, title, body_markdown, files_to_write)

    fetch_res = _run_git(["fetch", "origin", "main"], cwd=repo_root, token=token)
    if fetch_res.returncode != 0:
        raise RuntimeError(f"git fetch origin main failed: {fetch_res.stderr}")

    tmp_wt = Path(tempfile.mkdtemp(prefix="mcmusic_pr_wt_"))
    try:
        wt_add = _run_git(["worktree", "add", "-B", branch_name, str(tmp_wt), "origin/main"], cwd=repo_root, token=token)
        if wt_add.returncode != 0:
            raise RuntimeError(f"git worktree add failed: {wt_add.stderr}")

        rel_paths: List[str] = []
        for rel_path, content_bytes in files_to_write.items():
            clean_rel = rel_path.replace("\\", "/").lstrip("/")
            dest = tmp_wt / clean_rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            lf_bytes = content_bytes.replace(b"\r\n", b"\n")
            with open(dest, "wb") as f:
                f.write(lf_bytes)
            rel_paths.append(clean_rel)

        if run_local_tests and (tmp_wt / "tests" / "test_static_and_contracts.py").exists():
            py_bin = "/opt/hermes/.venv/bin/python3" if os.path.exists("/opt/hermes/.venv/bin/python3") else sys.executable
            test_proc = subprocess.run(
                [py_bin, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
                cwd=str(tmp_wt),
                capture_output=True,
                text=True,
                timeout=180,
            )
            if test_proc.returncode != 0:
                raise RuntimeError(f"Pre-PR test suite failed:\n{test_proc.stdout}\n{test_proc.stderr}")

        _run_git(["config", "user.name", "VØIDRIDE Model Scout"], cwd=tmp_wt)
        _run_git(["config", "user.email", "voidride-bot@users.noreply.github.com"], cwd=tmp_wt)
        add_res = _run_git(["add", "--"] + rel_paths, cwd=tmp_wt)
        if add_res.returncode != 0:
            raise RuntimeError(f"git add failed: {add_res.stderr}")

        diff_check = _run_git(["diff", "--cached", "--quiet"], cwd=tmp_wt)
        if diff_check.returncode == 0:
            return {"created": False, "reason": "no_diff"}

        commit_res = _run_git(["commit", "-m", title], cwd=tmp_wt)
        if commit_res.returncode != 0:
            raise RuntimeError(f"git commit failed: {commit_res.stderr}")

        push_res = _run_git(["push", "-u", "origin", f"{branch_name}:{branch_name}", "--force-with-lease"], cwd=tmp_wt, token=token)
        if push_res.returncode != 0:
            # Retry regular force push if branch is brand new / lease stale
            push_res = _run_git(["push", "-u", "origin", f"{branch_name}:{branch_name}", "--force"], cwd=tmp_wt, token=token)
            if push_res.returncode != 0:
                raise RuntimeError(f"git push failed: {push_res.stderr}")

        # Check if an open PR already exists for this branch
        existing = _github_api_request("GET", f"/repos/{REPO_SLUG}/pulls?state=open&head=maximusmaximus:{branch_name}")
        if isinstance(existing, list) and existing:
            pr_obj = _github_api_request(
                "PATCH",
                f"/repos/{REPO_SLUG}/pulls/{existing[0]['number']}",
                {"title": title, "body": body_markdown},
            )
        else:
            pr_obj = _github_api_request(
                "POST",
                f"/repos/{REPO_SLUG}/pulls",
                {"title": title, "head": branch_name, "base": "main", "body": body_markdown},
            )

        return {
            "created": True,
            "pr_number": pr_obj["number"],
            "pr_url": pr_obj["html_url"],
            "branch": branch_name,
            "head_sha": pr_obj.get("head", {}).get("sha", ""),
        }
    finally:
        _run_git(["worktree", "remove", "--force", str(tmp_wt)], cwd=repo_root)
        shutil.rmtree(tmp_wt, ignore_errors=True)


def merge_upgrade_pr(pr_number: int, force_bypass_ci: bool = False) -> Dict[str, Any]:
    """Verify CI checks passed, squash-merge PR on GitHub, delete branch, sync mounts, snapshot & verify."""
    if os.path.exists("/tmp/album_pipeline.lock"):
        return {"merged": False, "error": "Active album production in progress (/tmp/album_pipeline.lock). Retry after completion."}

    ci_ok, ci_msg, pr_obj = check_pr_ci_status(pr_number)
    if not ci_ok and not force_bypass_ci:
        return {"merged": False, "error": ci_msg, "pr_url": pr_obj.get("html_url", "")}

    # Take atomic pre-merge snapshot
    snap_id = None
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import snapshot_manager
        snap_id = snapshot_manager.create_snapshot(f"Pre-merge PR #{pr_number}")
    except Exception:
        pass

    merge_resp = _github_api_request(
        "PUT",
        f"/repos/{REPO_SLUG}/pulls/{pr_number}/merge",
        {
            "commit_title": f"{pr_obj.get('title', f'Merge PR #{pr_number}')} (#{pr_number})",
            "merge_method": "squash",
        },
    )
    if not merge_resp.get("merged"):
        return {"merged": False, "error": f"GitHub merge refused: {merge_resp}"}

    branch_name = pr_obj.get("head", {}).get("ref", "")
    if branch_name and branch_name != "main":
        try:
            _github_api_request("DELETE", f"/repos/{REPO_SLUG}/git/refs/heads/{branch_name}")
        except Exception:
            pass

    # Sync local checkouts (D:\hermes-music and D:\sp2 if reachable) + /opt/data/config/model_registry.json
    token = get_github_token()
    synced_roots: List[str] = []
    for root_cand in [Path(r"D:\hermes-music"), Path("/mnt/d/hermes-music"), Path(r"D:\sp2"), Path("/mnt/d/sp2")]:
        if (root_cand / ".git").exists():
            _run_git(["fetch", "origin", "main"], cwd=root_cand, token=token)
            pull_res = _run_git(["pull", "--ff-only", "origin", "main"], cwd=root_cand, token=token)
            if pull_res.returncode == 0:
                synced_roots.append(str(root_cand))

    # If running inside container sp2 (/opt/data without .git), fetch updated model_registry.json directly from main
    if os.path.exists("/opt/data") and not os.path.exists("/opt/data/.git"):
        try:
            import base64
            reg_blob = _github_api_request("GET", f"/repos/{REPO_SLUG}/contents/data/config/model_registry.json?ref=main")
            if reg_blob.get("content"):
                raw_bytes = base64.b64decode(reg_blob["content"]).replace(b"\r\n", b"\n")
                os.makedirs("/opt/data/config", exist_ok=True)
                with open("/opt/data/config/model_registry.json", "wb") as f:
                    f.write(raw_bytes)
                synced_roots.append("/opt/data/config/model_registry.json")
        except Exception:
            pass

    # Sync live D:\music\profiles\vidride\profile.json main_model if updated
    try:
        import model_registry
        new_main = model_registry.get_primary_model("music.main_instrumental", "elevenlabs-music-v2-5")
        for prof_path in ["/opt/data/music/profiles/vidride/profile.json", r"D:\music\profiles\vidride\profile.json"]:
            if os.path.exists(prof_path):
                with open(prof_path, "r", encoding="utf-8") as pf:
                    pdata = json.load(pf)
                if pdata.get("defaults", {}).get("main_model") != new_main:
                    pdata.setdefault("defaults", {})["main_model"] = new_main
                    pdata.setdefault("sonic_dna", {}).setdefault("preferred_models", {})["main"] = new_main
                    content_out = (json.dumps(pdata, indent=2, ensure_ascii=True) + "\n").encode("utf-8")
                    with open(prof_path, "wb") as pf:
                        pf.write(content_out)
    except Exception:
        pass

    # Verify live environment
    verify_ok = True
    verify_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify_pipeline_environment.py")
    if os.path.exists(verify_script):
        py_bin = "/opt/hermes/.venv/bin/python3" if os.path.exists("/opt/hermes/.venv/bin/python3") else sys.executable
        vp = subprocess.run([py_bin, verify_script], capture_output=True, text=True, timeout=30)
        verify_ok = vp.returncode == 0

    return {
        "merged": True,
        "pr_number": pr_number,
        "sha": merge_resp.get("sha", ""),
        "snapshot_id": snap_id,
        "synced_roots": synced_roots,
        "verify_ok": verify_ok,
        "ci_summary": ci_msg,
    }


def close_upgrade_pr(pr_number: int, record_rejected_models: Optional[List[str]] = None) -> Dict[str, Any]:
    """Close an unwanted model upgrade PR and record rejected candidate IDs so next week skips them."""
    pr_obj = _github_api_request("PATCH", f"/repos/{REPO_SLUG}/pulls/{pr_number}", {"state": "closed"})
    branch_name = pr_obj.get("head", {}).get("ref", "")
    if branch_name and branch_name != "main":
        try:
            _github_api_request("DELETE", f"/repos/{REPO_SLUG}/git/refs/heads/{branch_name}")
        except Exception:
            pass

    if record_rejected_models:
        try:
            import model_registry
            reg_path = model_registry.resolve_registry_path()
            reg = model_registry.load_registry(str(reg_path))
            rej = reg.setdefault("rejected_candidates", {})
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            for mid in record_rejected_models:
                rej[mid] = {"rejected_at": now_iso, "pr_number": pr_number}
            with open(reg_path, "wb") as f:
                f.write((json.dumps(reg, indent=2) + "\n").encode("utf-8"))
        except Exception:
            pass

    return {"closed": True, "pr_number": pr_number}


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage weekly Venice model upgrade PRs on GitHub")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", help="Check PR CI check-runs")
    p_status.add_argument("pr_number", type=int)

    p_merge = sub.add_parser("merge", help="CI-gated squash merge & live deploy")
    p_merge.add_argument("pr_number", type=int)
    p_merge.add_argument("--force-bypass-ci", action="store_true")

    p_close = sub.add_parser("close", help="Close PR and mark candidate rejected")
    p_close.add_argument("pr_number", type=int)
    p_close.add_argument("--reject-models", default="", help="Comma-separated model IDs to ignore in future runs")

    args = parser.parse_args()
    if args.cmd == "status":
        ok, msg, _ = check_pr_ci_status(args.pr_number)
        print(json.dumps({"ok": ok, "message": msg}))
        sys.exit(0 if ok else 1)
    elif args.cmd == "merge":
        res = merge_upgrade_pr(args.pr_number, force_bypass_ci=args.force_bypass_ci)
        print(json.dumps(res, indent=2))
        sys.exit(0 if res.get("merged") else 1)
    elif args.cmd == "close":
        rej = [m.strip() for m in args.reject_models.split(",") if m.strip()]
        res = close_upgrade_pr(args.pr_number, record_rejected_models=rej)
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
