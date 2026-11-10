#!/usr/bin/env python3
"""
Tier 3 Live Venice API Catalog & Structured-JSON Smoke Test.

Automatically skipped when VENICE_API_KEY is absent (e.g. unauthenticated fork PRs).
When VENICE_API_KEY is set, verifies 100% of models in model_registry.json exist in
Venice's live production catalog and runs a ~$0.0002 structured-JSON canary check.
"""

import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "data" / "scripts"
CONFIG_DIR = REPO_ROOT / "data" / "config"
sys.path.insert(0, str(SCRIPTS_DIR))

import model_registry  # noqa: E402
import venice_model_scout  # noqa: E402


@unittest.skipUnless(bool(os.environ.get("VENICE_API_KEY")), "VENICE_API_KEY not set — skipping live Venice smoke tier")
class TestLiveVeniceSmoke(unittest.TestCase):
    def test_01_all_registered_models_exist_in_live_venice_catalog(self):
        """Every primary and fallback model in model_registry.json must exist in live GET /api/v1/models?type=all."""
        api_key = os.environ["VENICE_API_KEY"]
        catalog = venice_model_scout.fetch_venice_catalog(api_key)
        self.assertGreater(len(catalog), 20, "Live Venice catalog unexpectedly small")

        reg = model_registry.load_registry(str(CONFIG_DIR / "model_registry.json"))
        missing = []
        for role_name, spec in reg["roles"].items():
            for slot_model in [spec["primary"], *spec.get("fallbacks", [])]:
                if slot_model not in catalog:
                    missing.append(f"{role_name}: '{slot_model}'")
        self.assertEqual(
            missing,
            [],
            f"Registered model(s) missing/deprecated in live Venice catalog: {missing}",
        )

    def test_02_live_showrunner_structured_json_smoke(self):
        """Primary llm.showrunner model must pass live VØIDRIDE structured-JSON benchmark."""
        api_key = os.environ["VENICE_API_KEY"]
        reg = model_registry.load_registry(str(CONFIG_DIR / "model_registry.json"))
        primary_llm = reg["roles"]["llm.showrunner"]["primary"]
        res = venice_model_scout.benchmark_text_model(api_key, primary_llm, {})
        self.assertTrue(res.get("ok"), f"Live showrunner smoke failed: {res}")
        self.assertGreaterEqual(res.get("score", 0), 75)


if __name__ == "__main__":
    unittest.main()
