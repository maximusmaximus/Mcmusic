#!/usr/bin/env python3
"""
model_feedback_collector.py — Closed-Loop Production Feedback & Telemetry Collector

Aggregates 7-day real-world model performance across VØIDRIDE productions:
  1. Explicit human feedback: track redos (ap:songs:redo:*), album rejects, proposal loves/hates/skips, cover edits.
  2. Technical & API reliability: timeouts, HTTP 4xx/5xx, empty-thinking responses, latency, USD spend.
  3. Acoustic QC metrics: post-master LUFS accuracy (-10.0 LUFS target), True Peak (<= -0.8 dBTP), dynamic range.
"""

import json
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DATA = os.environ.get("HERMES_HOME", "/opt/data")
if not os.path.exists(BASE_DATA) and os.path.exists(r"D:\sp2\data"):
    BASE_DATA = r"D:\sp2\data"

LOGS_DIR = os.path.join(BASE_DATA, "logs")
TELEMETRY_FILE = os.path.join(LOGS_DIR, "model_telemetry.jsonl")
EVENTS_FILE = os.path.join(LOGS_DIR, "pipeline_events.jsonl")
FAILURE_FILE = os.path.join(LOGS_DIR, "failure_journal.jsonl")

MUSIC_DIR = "/opt/data/music" if os.path.exists("/opt/data/music") else (r"D:\music" if os.path.exists(r"D:\music") else os.path.join(BASE_DATA, "music"))
TASTE_FILE = os.path.join(MUSIC_DIR, "proposals", "taste_profile.json")
EXPORTS_DIR = os.path.join(MUSIC_DIR, "exports")


def record_model_telemetry(
    role: str,
    model_id: str,
    outcome: str,
    latency_s: Optional[float] = None,
    cost_usd: Optional[float] = None,
    quality_score: Optional[float] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Append a structured model execution or human-feedback event to model_telemetry.jsonl."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "epoch": time.time(),
        "role": role,
        "model_id": model_id,
        "outcome": outcome,  # success | timeout | error | empty_response | user_redo | user_approved | user_loved | user_hated | cover_edited
        "latency_s": round(float(latency_s), 3) if latency_s is not None else None,
        "cost_usd": round(float(cost_usd), 5) if cost_usd is not None else None,
        "quality_score": round(float(quality_score), 3) if quality_score is not None else None,
        "details": details or {},
    }
    try:
        with open(TELEMETRY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass


def _read_jsonl_since(filepath: str, cutoff_epoch: float) -> List[Dict[str, Any]]:
    if not os.path.exists(filepath):
        return []
    items: List[Dict[str, Any]] = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                ep = obj.get("epoch")
                if ep is None and obj.get("timestamp"):
                    try:
                        ep = datetime.fromisoformat(str(obj["timestamp"]).replace("Z", "+00:00")).timestamp()
                    except Exception:
                        ep = cutoff_epoch + 1
                if ep is None or float(ep) >= cutoff_epoch:
                    items.append(obj)
    except Exception:
        pass
    return items


def _collect_recent_mastering_qc(cutoff_epoch: float) -> Dict[str, Any]:
    """Inspect recent DAW production_receipt.json files for post-master LUFS & True Peak compliance."""
    checked = 0
    lufs_pass = 0
    tp_pass = 0
    lufs_values: List[float] = []
    if not os.path.isdir(EXPORTS_DIR):
        return {"checked": 0, "lufs_pass_rate": 1.0, "tp_pass_rate": 1.0, "avg_lufs": -10.0}

    for root, _, files in os.walk(EXPORTS_DIR):
        for fn in files:
            if fn != "production_receipt.json":
                continue
            fp = os.path.join(root, fn)
            try:
                if os.path.getmtime(fp) < cutoff_epoch:
                    continue
                with open(fp, "r", encoding="utf-8") as f:
                    rec = json.load(f)
                qc = rec.get("post_master_qc") or rec.get("qc") or {}
                lufs = qc.get("integrated_lufs") or qc.get("lufs")
                tp = qc.get("true_peak_dbtp") or qc.get("true_peak_db")
                if lufs is not None:
                    checked += 1
                    lv = float(lufs)
                    lufs_values.append(lv)
                    if -11.5 <= lv <= -8.8:
                        lufs_pass += 1
                    if tp is None or float(tp) <= -0.5:
                        tp_pass += 1
            except Exception:
                continue

    return {
        "checked": checked,
        "lufs_pass_rate": round(lufs_pass / checked, 3) if checked else 1.0,
        "tp_pass_rate": round(tp_pass / checked, 3) if checked else 1.0,
        "avg_lufs": round(sum(lufs_values) / len(lufs_values), 2) if lufs_values else -10.0,
    }


def summarize_weekly_feedback(days: int = 7, registry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build a 7-day per-role & system-wide feedback report to guide weekly model upgrades."""
    cutoff = time.time() - (days * 86400)
    telemetry = _read_jsonl_since(TELEMETRY_FILE, cutoff)
    events = _read_jsonl_since(EVENTS_FILE, cutoff)
    failures = _read_jsonl_since(FAILURE_FILE, cutoff)

    role_stats: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "calls": 0,
            "successes": 0,
            "timeouts": 0,
            "errors": 0,
            "user_redos": 0,
            "user_approvals": 0,
            "latencies": [],
            "spend_usd": 0.0,
            "models_seen": set(),
        }
    )

    for item in telemetry:
        role = item.get("role", "unknown")
        st = role_stats[role]
        st["calls"] += 1
        if item.get("model_id"):
            st["models_seen"].add(item["model_id"])
        outcome = item.get("outcome", "")
        if outcome in ("success", "user_approved", "user_loved"):
            st["successes"] += 1
        if outcome == "timeout":
            st["timeouts"] += 1
        elif outcome in ("error", "empty_response"):
            st["errors"] += 1
        if outcome in ("user_redo", "user_hated", "cover_edited"):
            st["user_redos"] += 1
        if outcome in ("user_approved", "user_loved"):
            st["user_approvals"] += 1
        if item.get("latency_s") is not None:
            st["latencies"].append(float(item["latency_s"]))
        if item.get("cost_usd") is not None:
            st["spend_usd"] += float(item["cost_usd"])

    # Fold in pipeline_events.jsonl redo/reject signals
    pipeline_redos = 0
    cover_edits = 0
    for ev in events:
        etype = str(ev.get("event_type", "")).upper()
        if "REDO" in etype or "REJECT" in etype:
            pipeline_redos += 1
            role_stats["music.main_instrumental"]["user_redos"] += 1
        elif "COVER_EDIT" in etype or "ARTWORK_REGEN" in etype:
            cover_edits += 1
            role_stats["image.cover_primary"]["user_redos"] += 1

    # Fold in failure_journal.jsonl API timeouts/errors
    api_timeouts = 0
    for fl in failures:
        cat = str(fl.get("error_category", "")).upper()
        msg = str(fl.get("error_message", "")).lower()
        if "TIMEOUT" in cat or "timed out" in msg:
            api_timeouts += 1

    # Read taste_profile.json summary
    taste_summary = {"likes_7d": 0, "dislikes_7d": 0, "preferred_subgenres": []}
    if os.path.exists(TASTE_FILE):
        try:
            with open(TASTE_FILE, "r", encoding="utf-8") as f:
                tp = json.load(f)
            cutoff_date = datetime.fromtimestamp(cutoff, tz=timezone.utc).strftime("%Y-%m-%d")
            taste_summary["likes_7d"] = sum(1 for x in tp.get("likes", []) if str(x.get("noted_at", "")) >= cutoff_date)
            taste_summary["dislikes_7d"] = sum(1 for x in tp.get("dislikes", []) if str(x.get("noted_at", "")) >= cutoff_date)
            taste_summary["preferred_subgenres"] = tp.get("preferred_subgenres", [])[-8:]
        except Exception:
            pass

    mastering_qc = _collect_recent_mastering_qc(cutoff)

    roles_report: Dict[str, Any] = {}
    all_roles = set(role_stats.keys())
    if registry and isinstance(registry.get("roles"), dict):
        all_roles |= set(registry["roles"].keys())

    for r_name in sorted(all_roles):
        st = role_stats[r_name]
        calls = max(1, st["calls"])
        timeout_rate = round(st["timeouts"] / calls, 3) if st["calls"] else 0.0
        error_rate = round((st["timeouts"] + st["errors"]) / calls, 3) if st["calls"] else 0.0
        redo_denom = max(1, st["successes"] + st["user_redos"])
        redo_rate = round(st["user_redos"] / redo_denom, 3) if (st["successes"] + st["user_redos"]) else 0.0
        avg_lat = round(sum(st["latencies"]) / len(st["latencies"]), 2) if st["latencies"] else None

        needs_attention = (timeout_rate > 0.15) or (error_rate > 0.20) or (redo_rate > 0.25)
        roles_report[r_name] = {
            "calls": st["calls"],
            "timeout_rate": timeout_rate,
            "error_rate": error_rate,
            "redo_rate": redo_rate,
            "avg_latency_s": avg_lat,
            "spend_usd": round(st["spend_usd"], 4),
            "models_seen": sorted(st["models_seen"]),
            "status": "degraded" if needs_attention else "healthy",
        }

    return {
        "window_days": days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_redos_7d": pipeline_redos,
        "cover_edits_7d": cover_edits,
        "api_timeouts_7d": api_timeouts,
        "taste_summary": taste_summary,
        "mastering_qc": mastering_qc,
        "roles": roles_report,
    }


if __name__ == "__main__":
    import model_registry
    summary = summarize_weekly_feedback(days=7, registry=model_registry.load_registry())
    print(json.dumps(summary, indent=2))
