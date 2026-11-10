#!/usr/bin/env python3
"""
Tier 1 CI Suite — Static Analysis, AST Symbol-Table (NameError) Checks,
Secret-Leak Guard, LF Line-Ending Guard, and Model Registry Contracts.

Zero network calls, zero API spend, <2s runtime.
"""

import importlib.util
import json
import os
import py_compile
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "data" / "scripts"
CONFIG_DIR = REPO_ROOT / "data" / "config"

sys.path.insert(0, str(SCRIPTS_DIR))
import model_registry  # noqa: E402
import snapshot_manager  # noqa: E402


def _load_module_from_path(mod_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(mod_name, str(file_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load spec for {file_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestStaticAndContracts(unittest.TestCase):
    def _critical_python_files(self):
        files = sorted(SCRIPTS_DIR.glob("*.py"))
        extra_rel = [
            "data/skills/venice-music/venice-music/scripts/venice-music.py",
            "data/skills/master-producer/master-producer/scripts/master-producer.py",
            "data/skills/master-producer/master-producer/scripts/produce-album.py",
            "data/skills/dawagent/dawagent/scripts/handoff.py",
            "data/skills/dawagent/dawagent/scripts/auto_processor.py",
        ]
        for rel in extra_rel:
            p = REPO_ROOT / rel
            if p.exists():
                files.append(p)
        files.extend(sorted((REPO_ROOT / "tests").glob("*.py")))
        return files

    def test_01_syntax_and_ast_undefined_names(self):
        """Every pipeline & skill Python script must compile cleanly and have zero undefined symbols (NameError)."""
        py_files = self._critical_python_files()
        self.assertGreaterEqual(len(py_files), 10)
        failures = []
        for path in py_files:
            try:
                py_compile.compile(str(path), doraise=True)
            except Exception as e:
                failures.append(f"Syntax error in {path.relative_to(REPO_ROOT)}: {e}")
                continue
            undef = snapshot_manager._check_undefined_names(str(path))
            if undef:
                scope, lineno, var_name = undef[0]
                failures.append(
                    f"Undefined symbol '{var_name}' in {path.relative_to(REPO_ROOT)}:{lineno} (scope '{scope}')"
                )
        self.assertEqual(failures, [], "\n".join(failures))

    def test_02_lf_line_endings_enforced(self):
        """Critical scripts, configs, tests, and GitHub workflows must use LF (\\n), never CRLF (\\r\\n)."""
        targets = list(self._critical_python_files())
        for extra in [
            CONFIG_DIR / "model_registry.json",
            REPO_ROOT / ".github" / "workflows" / "ci.yml",
        ]:
            if extra.exists():
                targets.append(extra)

        crlf_files = []
        for p in targets:
            raw = p.read_bytes()
            if b"\r\n" in raw:
                crlf_files.append(str(p.relative_to(REPO_ROOT)))
        self.assertEqual(crlf_files, [], f"CRLF line endings detected in: {crlf_files}")

    def test_03_no_hardcoded_secrets_in_tracked_files(self):
        """Ensure zero API keys, GitHub OAuth tokens, or Telegram bot tokens exist in tracked source files."""
        secret_patterns = [
            ("GitHub Token", re.compile(r"\bgh[opsu]_[A-Za-z0-9]{25,}\b")),
            ("Venice Inference Key", re.compile(r"VENICE-INFERENCE-KEY-[A-Za-z0-9_-]{16,}")),
            ("Telegram Bot Token", re.compile(r"\b\d{8,11}:AA[A-Za-z0-9_-]{31,}\b")),
        ]

        candidates = []
        if (REPO_ROOT / ".git").exists():
            proc = subprocess.run(
                ["git", "ls-files"],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=15,
            )
            if proc.returncode == 0:
                for rel in proc.stdout.splitlines():
                    fp = REPO_ROOT / rel.strip()
                    if fp.is_file() and fp.suffix in {".py", ".json", ".yml", ".yaml", ".md", ".sh"}:
                        candidates.append(fp)

        if not candidates:
            candidates = list(self._critical_python_files()) + list(CONFIG_DIR.glob("*.json"))

        leaks = []
        for fp in candidates:
            try:
                text = fp.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for label, pat in secret_patterns:
                if pat.search(text):
                    leaks.append(f"{label} matched in {fp.relative_to(REPO_ROOT)}")
        self.assertEqual(leaks, [], f"Potential secret leak(s): {leaks}")

    def test_04_model_registry_schema_and_invariants(self):
        """Validate data/config/model_registry.json schema, roles, budget cap, and hybrid-thinking protections."""
        reg_path = CONFIG_DIR / "model_registry.json"
        self.assertTrue(reg_path.exists(), f"Missing {reg_path}")
        data = json.loads(reg_path.read_text(encoding="utf-8"))
        ok, errs = model_registry.validate_registry_schema(data)
        self.assertTrue(ok, f"Registry schema invalid: {errs}")

        # Deprecated model ID must never reappear
        raw_json = json.dumps(data)
        self.assertNotIn("grok-imagine-image-quality", raw_json)

        # Weekly canary spend cap invariant
        bp = model_registry.get_budget_policy(str(reg_path))
        self.assertLessEqual(float(bp["weekly_canary_cap_usd"]), 1.50)
        self.assertAlmostEqual(float(bp["estimated_costs_usd"]["album_total"]), 11.70, places=2)

        # Hybrid Qwen thinking starvation protection
        vp_qwen = model_registry.build_venice_parameters("qwen-3-7-plus", role="llm.proposals", custom_path=str(reg_path))
        self.assertTrue(vp_qwen.get("disable_thinking"), "Hybrid Qwen models must set disable_thinking=True")
        self.assertTrue(vp_qwen.get("strip_thinking_response"))

        # Deduplicated role chain lookup
        chain = model_registry.get_role_chain("music.main_instrumental", custom_path=str(reg_path))
        self.assertGreaterEqual(len(chain), 2)
        self.assertEqual(len(chain), len(set(chain)))

    def test_05_pipeline_option_1b_and_five_proposal_contracts(self):
        """Enforce REQUIRED_PROPOSAL_COUNT == 5, Option 1B ~$11.70 budget, and -10.0 LUFS mastering targets."""
        propose_mod = _load_module_from_path("propose_albums_contract", SCRIPTS_DIR / "propose_albums.py")
        self.assertEqual(
            propose_mod.REQUIRED_PROPOSAL_COUNT,
            5,
            "VØIDRIDE strictly requires 5 proposals (never 3)",
        )
        self.assertAlmostEqual(propose_mod.AVG_ALBUM_COST_USD, 11.70, places=2)

        auto_proc_path = REPO_ROOT / "data" / "skills" / "dawagent" / "dawagent" / "scripts" / "auto_processor.py"
        auto_mod = _load_module_from_path("auto_processor_contract", auto_proc_path)
        self.assertAlmostEqual(auto_mod.DEFAULT_LUFS, -10.0, places=1)
        self.assertAlmostEqual(auto_mod.DEFAULT_TRUE_PEAK, -0.8, places=1)


if __name__ == "__main__":
    unittest.main()
