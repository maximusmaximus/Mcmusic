#!/usr/bin/env python3
"""
logger_hub.py — Unified Logging & Failure Journaling Subsystem for SP2

Provides structured telemetry, failure journaling, and audit logging:
  - pipeline_events.jsonl: Real-time event telemetry across all phases.
  - failure_journal.jsonl: Structured failure records for weekly self-evolution.
  - pipeline_audit.log: Human-readable, scrubbed operational log.
"""

import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone

LOGS_DIR = os.environ.get("HERMES_LOGS_DIR", "/opt/data/logs")
EVENTS_FILE = os.path.join(LOGS_DIR, "pipeline_events.jsonl")
FAILURE_FILE = os.path.join(LOGS_DIR, "failure_journal.jsonl")
AUDIT_FILE = os.path.join(LOGS_DIR, "pipeline_audit.log")

os.makedirs(LOGS_DIR, exist_ok=True)

SENSITIVE_PATTERNS = [
    re.compile(r'(api[-_]?key["\']?\s*[:=]\s*["\']?)([^"\'\s]+)', re.IGNORECASE),
    re.compile(r'(bot\d+:[A-Za-z0-9_-]+)', re.IGNORECASE),
    re.compile(r'(Bearer\s+)([A-Za-z0-9_.-]+)', re.IGNORECASE),
]


def scrub_sensitive(text: str) -> str:
    """Scrub tokens, bot credentials, and API keys from logs."""
    if not isinstance(text, str):
        text = str(text)
    for pattern in SENSITIVE_PATTERNS:
        text = pattern.sub(r'\1[REDACTED]', text)
    return text


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_event(event_type: str, details: dict = None, album: str = None, phase: int = None, track_num: int = None):
    """Record an operational event to pipeline_events.jsonl and audit log."""
    entry = {
        "timestamp": _now_iso(),
        "event_type": event_type,
        "album": album or "N/A",
        "phase": phase,
        "track_num": track_num,
        "details": details or {}
    }
    try:
        with open(EVENTS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception as e:
        print(f"[logger_hub] Failed to write event: {e}", file=sys.stderr)

    # Human readable audit line
    track_str = f" [Track {track_num}]" if track_num else ""
    phase_str = f" [Phase {phase}]" if phase else ""
    audit_msg = f"[{_now_iso()}] {event_type}{phase_str}{track_str} ({album or 'GLOBAL'}): {json.dumps(details or {}, default=str)}"
    _append_audit(scrub_sensitive(audit_msg))


def log_failure(error_category: str, error_message: str, traceback_str: str = None,
                context: dict = None, album: str = None, phase: int = None,
                track_num: int = None, action_taken: str = "pending"):
    """
    Record an error or exception to failure_journal.jsonl for self-update analysis.
    Categories: API_TIMEOUT, RATE_LIMIT, DAW_TIMEOUT, CORRUPT_OUTPUT, SYNTAX_ERROR, NETWORK_ERROR, USER_ABORT, UNKNOWN
    """
    clean_msg = scrub_sensitive(str(error_message))
    clean_tb = scrub_sensitive(traceback_str or traceback.format_exc()) if traceback_str or sys.exc_info()[0] else None

    entry = {
        "timestamp": _now_iso(),
        "album": album or "N/A",
        "phase": phase,
        "track_num": track_num,
        "error_category": error_category,
        "error_message": clean_msg,
        "traceback": clean_tb,
        "context": context or {},
        "action_taken": action_taken
    }

    try:
        with open(FAILURE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception as e:
        print(f"[logger_hub] Failed to write failure record: {e}", file=sys.stderr)

    # Audit line
    _append_audit(f"[{_now_iso()}] 🚨 FAILURE [{error_category}] Phase {phase} Track {track_num} ({album}): {clean_msg}")
    if clean_tb:
        _append_audit(f"Traceback:\n{clean_tb}")


def _append_audit(text: str):
    try:
        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass


def get_recent_failures(days: int = 7) -> list:
    """Retrieve failure records logged in the last N days."""
    if not os.path.exists(FAILURE_FILE):
        return []

    cutoff = time.time() - (days * 86400)
    recent = []

    try:
        with open(FAILURE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    ts_str = record.get("timestamp", "")
                    # Parse ISO format
                    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if dt.timestamp() >= cutoff:
                        recent.append(record)
                except Exception:
                    continue
    except Exception as e:
        print(f"[logger_hub] Error reading failure journal: {e}", file=sys.stderr)

    return recent


def update_failure_action(timestamp: str, action_taken: str):
    """Update action_taken for a failure (e.g. user_retried, skipped, auto_healed)."""
    if not os.path.exists(FAILURE_FILE):
        return
    try:
        records = []
        with open(FAILURE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("timestamp") == timestamp:
                        rec["action_taken"] = action_taken
                    records.append(rec)
                except Exception:
                    continue
        with open(FAILURE_FILE, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, default=str) + "\n")
    except Exception as e:
        print(f"[logger_hub] Error updating failure action: {e}", file=sys.stderr)


if __name__ == "__main__":
    # Smoke test
    log_event("LOGGER_INIT", {"status": "ok"}, album="TEST_ALBUM", phase=1)
    print("Logger hub initialized successfully.")
