#!/usr/bin/env python3
"""
recursive_sp2_update.py — Autonomous Weekly Workflow Evolution & Self-Healing Engine

Analyzes weekly failure journals and production bottlenecks using Venice AI's premier reasoning
model (claude-opus-5), proposing surgical workflow patches with human-in-the-loop review.

Allocated Budget: $2.00 USD (tracked under 'recursive sp2 update' in config).
Human Confirmation: Interactive Telegram buttons (Apply, View Diff, Reject) + 1-click rollback.
"""

import argparse
import difflib
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

# ── Paths ──
BASE_DATA = os.environ.get("HERMES_HOME", "/opt/data")
SCRIPTS_DIR = os.path.join(BASE_DATA, "scripts")
PATCHES_DIR = os.path.join(BASE_DATA, "patches")
CONFIG_YAML = os.path.join(BASE_DATA, "config.yaml")
UPDATE_STATE_FILE = os.path.join(BASE_DATA, "config", "sp2_update_state.json")

os.makedirs(PATCHES_DIR, exist_ok=True)
os.makedirs(os.path.dirname(UPDATE_STATE_FILE), exist_ok=True)

# Import siblings
sys.path.insert(0, SCRIPTS_DIR)
try:
    import logger_hub
    import snapshot_manager
except ImportError:
    logger_hub = None
    snapshot_manager = None

# ── Model & Pricing Defaults ──
PRIMARY_MODEL = "claude-opus-5"
CODER_MODEL = "qwen3-coder-480b-a35b-instruct-turbo"
TOTAL_BUDGET_USD = 2.00

# Estimated Venice per-million token pricing for cost tracking
# claude-opus-5 on Venice: ~$15/M input, ~$75/M output (standard Opus equivalent)
MODEL_RATES = {
    "claude-opus-5": {"input": 15.0 / 1e6, "output": 75.0 / 1e6},
    "qwen3-coder-480b-a35b-instruct-turbo": {"input": 2.0 / 1e6, "output": 6.0 / 1e6},
    "default": {"input": 3.0 / 1e6, "output": 10.0 / 1e6}
}


def load_update_state() -> dict:
    if os.path.exists(UPDATE_STATE_FILE):
        try:
            with open(UPDATE_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "allocated_budget_usd": TOTAL_BUDGET_USD,
        "used_budget_usd": 0.0,
        "primary_model": PRIMARY_MODEL,
        "coder_model": CODER_MODEL,
        "history": []
    }


def save_update_state(state: dict):
    with open(UPDATE_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def get_venice_key() -> str:
    key = os.environ.get("VENICE_API_KEY", "")
    if key:
        return key
    # Try reading from config.yaml
    if os.path.exists(CONFIG_YAML):
        try:
            with open(CONFIG_YAML, "r", encoding="utf-8") as f:
                for line in f:
                    if "api_key:" in line:
                        parts = line.split("api_key:", 1)
                        return parts[1].strip().strip('"').strip("'")
        except Exception:
            pass
    return ""


def call_venice_chat(messages: list, model: str = PRIMARY_MODEL, max_tokens: int = 1500, temperature: float = 0.2) -> tuple[str, float]:
    """
    Call Venice AI Chat Completion and track exact cost against the $2.00 budget.
    Returns: (reply_text, call_cost_usd)
    """
    api_key = get_venice_key()
    if not api_key:
        raise ValueError("VENICE_API_KEY not found in environment or config.yaml")

    url = "https://api.venice.ai/api/v1/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    )

    with urllib.request.urlopen(req, timeout=90) as resp:
        res = json.loads(resp.read().decode("utf-8"))

    choice = res.get("choices", [{}])[0]
    reply = choice.get("message", {}).get("content", "")
    usage = res.get("usage", {})
    prompt_tokens = usage.get("prompt_tokens", 0)
    comp_tokens = usage.get("completion_tokens", 0)

    rates = MODEL_RATES.get(model, MODEL_RATES["default"])
    call_cost = (prompt_tokens * rates["input"]) + (comp_tokens * rates["output"])
    return reply, round(call_cost, 4)


def analyze_weekly_failures(dry_run: bool = False) -> dict:
    """Analyze failures from the last 7 days and formulate an evolutionary patch proposal."""
    state = load_update_state()
    allocated = state.get("allocated_budget_usd", TOTAL_BUDGET_USD)
    used = state.get("used_budget_usd", 0.0)

    if used >= allocated:
        msg = f"⚠ Self-update budget exhausted: ${used:.2f} used of ${allocated:.2f} allocated. Top up budget to resume."
        print(f"[recursive_sp2_update] {msg}")
        return {"success": False, "reason": "budget_exhausted", "message": msg}

    # Fetch failures from logger_hub
    failures = []
    if logger_hub:
        failures = logger_hub.get_recent_failures(days=7)

    if not failures:
        # Check if there are errors in logs/pipeline.log or logs/watchdog.log
        pipeline_log = os.path.join(BASE_DATA, "logs", "pipeline.log")
        if os.path.exists(pipeline_log):
            try:
                with open(pipeline_log, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()[-300:]
                err_lines = [ln.strip() for ln in lines if "ERROR" in ln or "Traceback" in ln or "failed" in ln.lower()]
                if err_lines:
                    failures.append({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "error_category": "PIPELINE_LOG_ERROR",
                        "error_message": "\n".join(err_lines[-10:]),
                        "context": {"source": "pipeline.log"}
                    })
            except Exception:
                pass

    if not failures:
        print("[recursive_sp2_update] ✓ Zero production failures detected in the past 7 days. Workflow is healthy.")
        return {"success": True, "action": "none_needed", "message": "Zero failures in past 7 days."}

    print(f"[recursive_sp2_update] Found {len(failures)} failure events over the last 7 days. Synthesizing diagnosis with {PRIMARY_MODEL}...")

    # Group failures by category
    summary_by_cat = {}
    sample_msgs = []
    for f in failures:
        cat = f.get("error_category", "UNKNOWN")
        summary_by_cat[cat] = summary_by_cat.get(cat, 0) + 1
        msg = f.get("error_message", "")
        if msg and len(sample_msgs) < 8:
            sample_msgs.append(f"[{cat}] Phase {f.get('phase','?')}: {msg[:180]}")

    failures_prompt = (
        f"You are the self-evolution architect for SP2 (VØIDRIDE autonomous music production agent).\n"
        f"Over the past 7 days, the following production failures and bottlenecks were recorded:\n"
        f"Failure counts by category: {json.dumps(summary_by_cat, indent=2)}\n"
        f"Sample failure incidents:\n" + "\n".join(sample_msgs) + "\n\n"
        f"Analyze the root causes of these failures. Propose 1 to 3 targeted, high-impact optimizations for the pipeline scripts.\n"
        f"Return your analysis in strict JSON format with this schema:\n"
        f"{{\n"
        f'  "incident_summary": "Brief 1-line summary of what failed",\n'
        f'  "root_cause": "Deep technical explanation of why it failed",\n'
        f'  "proposed_changes": [\n'
        f'    "Change 1 description",\n'
        f'    "Change 2 description"\n'
        f'  ],\n'
        f'  "target_file": "album_pipeline.py",\n'
        f'  "safety_assessment": "Assessment of stability risk (Low/Medium)"\n'
        f"}}"
    )

    messages = [
        {"role": "system", "content": "You are a master systems engineer analyzing Python audio pipeline failures. Output valid JSON only."},
        {"role": "user", "content": failures_prompt}
    ]

    if dry_run:
        print("[recursive_sp2_update] [DRY RUN] Prompt constructed. Skipping live API call.")
        return {"success": True, "dry_run": True, "failures_count": len(failures)}

    try:
        raw_analysis, cost = call_venice_chat(messages, model=PRIMARY_MODEL, max_tokens=800)
    except Exception as e:
        print(f"[recursive_sp2_update] Venice AI error during analysis: {e}")
        return {"success": False, "error": str(e)}

    # Parse JSON
    try:
        # Extract JSON block if wrapped in markdown
        m = re.search(r'\{.*\}', raw_analysis, re.DOTALL)
        analysis_data = json.loads(m.group(0)) if m else json.loads(raw_analysis)
    except Exception as e:
        print(f"[recursive_sp2_update] Failed to parse analysis JSON: {e}\nRaw:\n{raw_analysis}")
        return {"success": False, "error": f"JSON parse error: {e}"}

    # Deduct cost from budget
    state["used_budget_usd"] = round(state.get("used_budget_usd", 0.0) + cost, 4)
    patch_id = f"patch_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

    proposal = {
        "patch_id": patch_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "failures_analyzed": len(failures),
        "analysis": analysis_data,
        "cost_usd": cost,
        "remaining_budget_usd": round(state["allocated_budget_usd"] - state["used_budget_usd"], 4),
        "status": "pending_review"
    }

    # Save proposal
    patch_file = os.path.join(PATCHES_DIR, f"{patch_id}.json")
    with open(patch_file, "w", encoding="utf-8") as f:
        json.dump(proposal, f, indent=2)

    state["history"].append({
        "patch_id": patch_id,
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "cost_usd": cost,
        "incident_summary": analysis_data.get("incident_summary", "Optimization")
    })
    save_update_state(state)

    print(f"[recursive_sp2_update] Generated proposal {patch_id} (Cost: ${cost:.4f}, Budget remaining: ${proposal['remaining_budget_usd']:.2f})")
    send_proposal_to_telegram(proposal)
    return {"success": True, "proposal": proposal}


def send_proposal_to_telegram(proposal: dict):
    """Deliver the evolutionary update proposal to the user's Telegram with interactive review buttons."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "8862164729:AAGXMYgTeNNC0IazjWPQ3vlrlREnkOpvnyw")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "8293122782")

    if not bot_token:
        print("[recursive_sp2_update] No bot token configured, skipping Telegram dispatch")
        return

    patch_id = proposal["patch_id"]
    analysis = proposal.get("analysis", {})
    changes = "\n".join([f"• {c}" for c in analysis.get("proposed_changes", [])])

    msg = (
        f"🧬 <b>VØIDRIDE — Weekly Workflow Evolution Proposal</b>\n"
        f"═══════════════════════════════════════\n"
        f"<b>Analyzed:</b> {proposal.get('failures_analyzed', 0)} incidents over the past 7 days\n"
        f"<b>Root Cause:</b> {analysis.get('incident_summary', 'Routine optimizations')}\n\n"
        f"<b>Proposed Improvements:</b>\n"
        f"{changes}\n\n"
        f"<b>Target File:</b> <code>{analysis.get('target_file', 'album_pipeline.py')}</code>\n"
        f"<b>Risk Level:</b> {analysis.get('safety_assessment', 'Low')}\n"
        f"<b>Self-Update Budget:</b> ${proposal.get('remaining_budget_usd', 0):.2f} / $2.00 remaining\n"
        f"═══════════════════════════════════════\n"
        f"<i>Review the diff or confirm application below:</i>"
    )

    buttons = [
        [{"text": f"✅ Apply Patch", "callback_data": f"sp2:patch:apply:{patch_id}"}],
        [
            {"text": "🔍 View Details", "callback_data": f"sp2:patch:diff:{patch_id}"},
            {"text": "❌ Reject", "callback_data": f"sp2:patch:reject:{patch_id}"}
        ]
    ]

    payload = {
        "chat_id": chat_id,
        "text": msg,
        "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": buttons}
    }

    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            pass
        print(f"[recursive_sp2_update] Dispatched proposal {patch_id} to Telegram.")
    except Exception as e:
        print(f"[recursive_sp2_update] Telegram dispatch error: {e}")


def main():
    parser = argparse.ArgumentParser(description="SP2 Autonomous Weekly Evolution Engine")
    parser.add_argument("--test", action="store_true", help="Dry run without API execution")
    parser.add_argument("--force", action="store_true", help="Run analysis even if no failures")
    args = parser.parse_args()

    print(f"[recursive_sp2_update] Starting weekly self-healing reflection (Model: {PRIMARY_MODEL}, Budget: ${TOTAL_BUDGET_USD:.2f})...")
    res = analyze_weekly_failures(dry_run=args.test)
    print(f"[recursive_sp2_update] Finished with result: {res.get('action') or res.get('reason') or 'complete'}")


if __name__ == "__main__":
    main()
