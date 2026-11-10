#!/usr/bin/env python3
"""
Tier 2 Hermetic E2E Pipeline & Model-Scout Suite ($0.00 API Spend).

Spins up a contract-strict local Mock Venice AI HTTP server and exercises:
  1. Strict 5-proposal generation, deduplication, and low-credit gate in propose_albums.py.
  2. Weekly Venice Model Scout catalog diffing, deprecated-fallback auto-healing, and canary promotion.
  3. Closed-loop 7-day telemetry & LUFS QC aggregation in model_feedback_collector.py.
  4. Full 2-pass -10.0 LUFS / -0.8 dBTP studio audio stem premix + mastering via auto_processor.py & ffmpeg.
"""

import base64
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "data" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


def _load_module(mod_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(mod_name, str(file_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {file_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOCK_PROPOSALS_BATCH = [
    # 1. Duplicate/exhausted word ("BASEMENT") -> must be rejected by validate_proposal!
    {
        "album": "BASEMENT ECHO",
        "tracks": ["NIGHT ONE", "NIGHT TWO", "NIGHT THREE", "NIGHT FOUR", "NIGHT FIVE"],
        "bpm": "136",
        "key": "Dm",
        "subgenre": "california bass",
        "visual": "A dark coastal cliff highway overlooking churning Pacific surf under fog",
        "brief": "Heavy gliding 808 sub-bass and detuned analog brass hooks.",
    },
    # 5 distinct valid 2-word ALL CAPS concepts -> must all be accepted to reach 5/5!
    {
        "album": "CLIFF SURGE",
        "tracks": ["FOG TIDE", "PACIFIC GLIDE", "SALT DRIFT", "BREAKWATER SUB", "HEADLAND PULSE"],
        "bpm": "138",
        "key": "Dm",
        "subgenre": "california bass / nightride trap",
        "visual": "Midnight coastal cliff highway above crashing Pacific surf with wet guardrails",
        "brief": "Detuned brass earworm hook within 8s dropping into gliding West Coast 808s.",
    },
    {
        "album": "SOLAR MIRAGE",
        "tracks": ["MIRROR FIELD", "DESERT ARC", "THERMAL DROP", "DUNE STATIC", "ALKALI CROWN"],
        "bpm": "142",
        "key": "Fm",
        "subgenre": "west coast bass / witch house",
        "visual": "Concentric solar mirror heliostat array in Mojave desert under cold moonlight",
        "brief": "Haunted vocal-chop motif over sub-rattling portamento 808 slides.",
    },
    {
        "album": "HARBOR OBSIDIAN",
        "tracks": ["KEEL WAKE", "MARINA SHADOW", "BILGE HUM", "ANCHOR CHAIN", "JETTY CROWN"],
        "bpm": "132",
        "key": "Cm",
        "subgenre": "melodic nightride trap",
        "visual": "Stealth black hull docked in an empty industrial marina with oil-slick water",
        "brief": "Plucked glass bell hook opening into cavernous half-time nightride bass.",
    },
    {
        "album": "HANGAR VORTEX",
        "tracks": ["FUSELAGE SHELL", "TURBINE SIGH", "TARMAC FROST", "AILERON DRIFT", "RUNWAY ZERO"],
        "bpm": "146",
        "key": "Gm",
        "subgenre": "hyperspatial nightride bass",
        "visual": "Vast derelict aerospace hangar with rain blowing across polished hangar floor",
        "brief": "Aggressive Reese bass switch-ups paired with crisp snap snares.",
    },
    {
        "album": "CANYON TURBINE",
        "tracks": ["SPILLWAY MIST", "PENSTOCK ROAR", "INTAKE GATE", "WEIR SHADOW", "RESERVOIR DEEP"],
        "bpm": "128",
        "key": "Ebm",
        "subgenre": "dark west coast phonk",
        "visual": "Brutalist concrete dam intake towers rising out of black mountain reservoir",
        "brief": "Hypnotic metallic bell lead and thunderous linear-loudness 808 drops.",
    },
]


class _StrictVeniceMockHandler(BaseHTTPRequestHandler):
    """Contract-strict Mock Venice AI API enforcing real Venice parameter rules."""

    server_state = {
        "balance_usd": 6.00,  # Intentionally < $11.70 to test low-credit shortfall gate!
        "catalog": {},
    }

    def log_message(self, fmt, *args):
        pass  # Keep test output clean

    def _send_json(self, code: int, payload: dict):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.startswith("/api/v1/models"):
            items = []
            for mid, spec in self.server_state["catalog"].items():
                items.append({
                    "id": mid,
                    "type": spec.get("type", "text"),
                    "model_spec": {
                        "pricing": spec.get("pricing", {}),
                        "capabilities": spec.get("capabilities", {}),
                        "constraints": spec.get("constraints", {}),
                    },
                })
            self._send_json(200, {"data": items})
            return

        if self.path.startswith("/api/v1/api_keys/rate_limits"):
            self._send_json(
                200,
                {
                    "data": {
                        "balances": {
                            "USD": self.server_state["balance_usd"],
                            "DIEM": 0.0,
                            "BUNDLED_CREDITS": 0.0,
                        }
                    }
                },
            )
            return

        self._send_json(404, {"error": f"Unknown GET {self.path}"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

        if self.path == "/api/v1/chat/completions":
            model = str(body.get("model", ""))
            vp = body.get("venice_parameters") or {}
            # Contract check 1: Hybrid Qwen models MUST set disable_thinking=True
            if "qwen" in model.lower() and not vp.get("disable_thinking"):
                self._send_json(400, {"error": f"Model {model} starved without disable_thinking=True"})
                return

            user_msg = str((body.get("messages") or [{}])[-1].get("content", ""))
            if "Executive Showrunner" in user_msg:
                # Canary benchmark call from venice_model_scout.benchmark_text_model
                if model == "deepseek-v5-turbo":
                    tracks = [
                        {
                            "track_number": 1,
                            "title": "NIGHT GLIDE",
                            "bpm": 138,
                            "key": "Dm",
                            "hook_motif": "Detuned analog brass hook",
                            "main_prompt": "Dynamic hit-arranged California bass at 138 BPM in Dm with [0:00-0:15 Intro] and [0:15-0:55 Drop 1] gliding 808 sub-bass.",
                        },
                        {
                            "track_number": 2,
                            "title": "COASTAL SUB",
                            "bpm": 144,
                            "key": "Fm",
                            "hook_motif": "Plucked glass lead motif",
                            "main_prompt": "West Coast nightride trap at 144 BPM in Fm with [0:00-0:12 Hook Tease] and [0:12-0:50 Drop 1] crisp snap snares.",
                        },
                    ]
                else:
                    # Incumbent scores slightly lower (same BPM on both -> 90 vs 100)
                    tracks = [
                        {
                            "track_number": 1,
                            "title": "IRON TIDE",
                            "bpm": 138,
                            "key": "Dm",
                            "hook_motif": "Brass lead",
                            "main_prompt": "Dynamic hit-arranged California bass at 138 BPM in Dm with [0:00-0:15 Intro] and [0:15-0:55 Drop 1] gliding 808 sub-bass.",
                        },
                        {
                            "track_number": 2,
                            "title": "COLD PIER",
                            "bpm": 138,
                            "key": "Fm",
                            "hook_motif": "Synth pluck",
                            "main_prompt": "West Coast nightride trap at 138 BPM in Fm with [0:00-0:12 Hook Tease] and [0:12-0:50 Drop 1] crisp snap snares.",
                        },
                    ]
                content = json.dumps({"tracks": tracks})
            else:
                content = json.dumps(MOCK_PROPOSALS_BATCH)

            self._send_json(
                200,
                {
                    "choices": [{"message": {"content": content}}],
                    "usage": {"prompt_tokens": 220, "completion_tokens": 310},
                },
            )
            return

        if self.path == "/api/v1/images/generations":
            # Contract check 2: Venice /images/generations rejects OpenAI "n" field and >1024 dims
            if "n" in body:
                self._send_json(400, {"error": "Venice /images/generations rejects 'n' parameter"})
                return
            if int(body.get("width", 1024)) > 1024 or int(body.get("height", 1024)) > 1024:
                self._send_json(400, {"error": "Dimensions >1024x1024 rejected"})
                return
            fake_png = b"\x89PNG\r\n\x1a\n" + (b"\x10" * 12000)
            self._send_json(200, {"data": [{"b64_json": base64.b64encode(fake_png).decode("ascii")}]})
            return

        self._send_json(404, {"error": f"Unknown POST {self.path}"})


class TestHermeticE2EPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reg_data = json.loads((REPO_ROOT / "data" / "config" / "model_registry.json").read_text(encoding="utf-8"))
        catalog = {}
        for _, spec in reg_data["roles"].items():
            mtype = spec["modality"]
            for mid in [spec["primary"], *spec.get("fallbacks", [])]:
                catalog[mid] = {
                    "type": mtype,
                    "pricing": {"input": {"usd": 0.15}, "output": {"usd": 0.30}},
                }
        _StrictVeniceMockHandler.server_state["catalog"] = catalog

        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _StrictVeniceMockHandler)
        cls.port = cls.httpd.server_address[1]
        cls.api_base = f"http://127.0.0.1:{cls.port}/api/v1"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_01_propose_albums_strict_five_and_low_credit_gate(self):
        """E2E: propose_albums filters exhausted concepts, enforces strictly 5 proposals, and flags credit shortfall."""
        tmp = Path(tempfile.mkdtemp(prefix="e2e_propose_"))
        try:
            old_env = {k: os.environ.get(k) for k in ("VENICE_API_BASE", "VENICE_API_KEY")}
            os.environ["VENICE_API_BASE"] = self.api_base
            os.environ["VENICE_API_KEY"] = "test-mock-key"

            propose = _load_module("propose_albums_e2e", SCRIPTS_DIR / "propose_albums.py")
            propose.VENICE_API_BASE = self.api_base
            propose.VENICE_API_KEY = "test-mock-key"
            propose.MUSIC_ROOT = tmp
            propose.RELEASES_DIR = tmp / "releases"
            propose.ALBUMS_DIR = tmp / "albums"
            propose.EXPORTS_DIR = tmp / "exports"
            propose.ARTWORK_DIR = tmp / "artwork" / "covers"
            propose.PROPOSALS_DIR = tmp / "proposals"
            propose.TASTE_FILE = propose.PROPOSALS_DIR / "taste_profile.json"
            propose.HISTORY_FILE = propose.PROPOSALS_DIR / "proposal_history.json"

            proposals = propose.query_venice([], [])
            self.assertIsNotNone(proposals)
            self.assertEqual(len(proposals), 5, "query_venice must return strictly 5 validated proposals")
            titles = [p["album"] for p in proposals]
            self.assertNotIn("BASEMENT ECHO", titles, "Exhausted word BASEMENT must be rejected")

            # Refuses incomplete batch of 3
            self.assertFalse(propose.send_proposals(proposals[:3], dry_run=True))

            # Accepts full batch of 5 and records low-credit shortfall ($6.00 vs $11.70)
            self.assertTrue(propose.send_proposals(proposals, dry_run=True))
            saved = json.loads((propose.PROPOSALS_DIR / "current_proposals.json").read_text(encoding="utf-8"))
            self.assertEqual(len(saved["proposals"]), 5)
            self.assertFalse(saved["venice_budget"]["sufficient"])
            self.assertAlmostEqual(saved["venice_budget"]["shortfall"], 5.70, places=2)
        finally:
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            shutil.rmtree(tmp, ignore_errors=True)

    def test_02_weekly_model_scout_deprecation_heal_and_canary_upgrade(self):
        """E2E: venice_model_scout heals deprecated fallbacks and promotes higher-scoring new Venice models."""
        tmp = Path(tempfile.mkdtemp(prefix="e2e_scout_"))
        try:
            cfg_dir = tmp / "data" / "config"
            cfg_dir.mkdir(parents=True, exist_ok=True)

            base_reg = json.loads((REPO_ROOT / "data" / "config" / "model_registry.json").read_text(encoding="utf-8"))
            # Inject a deprecated fallback to verify auto-healing
            base_reg["roles"]["image.cover_primary"]["fallbacks"].append("deprecated-flux-beta-0")
            reg_file = cfg_dir / "model_registry.json"
            reg_file.write_text(json.dumps(base_reg, indent=2), encoding="utf-8")

            # Previous week's snapshot (before deepseek-v5-turbo existed)
            prev_models = dict(_StrictVeniceMockHandler.server_state["catalog"])
            snap_file = cfg_dir / "venice_catalog_snapshot.json"
            snap_file.write_text(json.dumps({"models": prev_models}, indent=2), encoding="utf-8")

            # Live catalog adds brand-new text model deepseek-v5-turbo
            live_with_new = dict(prev_models)
            live_with_new["deepseek-v5-turbo"] = {
                "type": "text",
                "pricing": {"input": {"usd": 0.12}, "output": {"usd": 0.25}},
            }
            _StrictVeniceMockHandler.server_state["catalog"] = live_with_new

            old_env = {
                k: os.environ.get(k)
                for k in ("VENICE_API_BASE", "VENICE_API_KEY", "VENICE_MODEL_REGISTRY_PATH")
            }
            os.environ["VENICE_API_BASE"] = self.api_base
            os.environ["VENICE_API_KEY"] = "test-mock-key"
            os.environ["VENICE_MODEL_REGISTRY_PATH"] = str(reg_file)

            scout = _load_module("venice_model_scout_e2e", SCRIPTS_DIR / "venice_model_scout.py")
            scout.VENICE_API_BASE = self.api_base

            result = scout.run_weekly_scout(
                init_baseline_only=False,
                dry_run=False,
                open_pr=False,
                notify_telegram=False,
            )
            self.assertEqual(result["status"], "upgrades_ready_dry_run")
            self.assertLessEqual(result["canary_spend_usd"], 1.50)

            upgraded_roles = {u["role"]: u for u in result["upgrades"]}
            self.assertIn("image.cover_primary", upgraded_roles, "Deprecated fallback must be auto-healed")
            self.assertIn("llm.showrunner", upgraded_roles, "New top-scoring text model must win canary")
            self.assertEqual(upgraded_roles["llm.showrunner"]["new_model"], "deepseek-v5-turbo")
        finally:
            _StrictVeniceMockHandler.server_state["catalog"] = prev_models
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            shutil.rmtree(tmp, ignore_errors=True)

    def test_03_feedback_collector_telemetry_and_mastering_qc(self):
        """E2E: model_feedback_collector aggregates 7d redos, timeouts, and LUFS/TP receipts."""
        tmp = Path(tempfile.mkdtemp(prefix="e2e_feedback_"))
        try:
            logs_dir = tmp / "logs"
            exports_dir = tmp / "exports" / "test_album"
            logs_dir.mkdir(parents=True)
            exports_dir.mkdir(parents=True)

            fb = _load_module("feedback_e2e", SCRIPTS_DIR / "model_feedback_collector.py")
            fb.LOGS_DIR = str(logs_dir)
            fb.TELEMETRY_FILE = str(logs_dir / "model_telemetry.jsonl")
            fb.EVENTS_FILE = str(logs_dir / "pipeline_events.jsonl")
            fb.FAILURE_FILE = str(logs_dir / "failure_journal.jsonl")
            fb.EXPORTS_DIR = str(tmp / "exports")
            fb.TASTE_FILE = str(tmp / "taste_profile.json")

            fb.record_model_telemetry("llm.showrunner", "deepseek-v4-flash", "success", latency_s=4.2, cost_usd=0.002)
            fb.record_model_telemetry("music.foley_sfx", "elevenlabs-sound-effects-v2", "timeout", latency_s=30.0)
            fb.record_model_telemetry("music.foley_sfx", "elevenlabs-sound-effects-v2", "timeout", latency_s=30.0)

            (exports_dir / "production_receipt.json").write_text(
                json.dumps({"post_master_qc": {"integrated_lufs": -10.1, "true_peak_dbtp": -0.82}}),
                encoding="utf-8",
            )

            summary = fb.summarize_weekly_feedback(days=7)
            self.assertEqual(summary["mastering_qc"]["checked"], 1)
            self.assertEqual(summary["mastering_qc"]["lufs_pass_rate"], 1.0)
            self.assertEqual(summary["roles"]["llm.showrunner"]["status"], "healthy")
            self.assertEqual(summary["roles"]["music.foley_sfx"]["status"], "degraded")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(shutil.which("ffmpeg") is not None, "ffmpeg not installed on PATH")
    def test_04_studio_two_pass_mastering_chain_e2e(self):
        """E2E Audio: synthesize 48kHz stereo stems, build sidechain premix, run 2-pass -10 LUFS FLAC master, and QC."""
        tmp = Path(tempfile.mkdtemp(prefix="e2e_daw_"))
        try:
            auto_proc_path = REPO_ROOT / "data" / "skills" / "dawagent" / "dawagent" / "scripts" / "auto_processor.py"
            auto_mod = _load_module("auto_proc_e2e", auto_proc_path)
            auto_mod.LOG_FILE = tmp / "auto_processor.log"

            interchange = tmp / "interchange"
            interchange.mkdir(parents=True)
            stem_main = interchange / "01_main.wav"
            stem_tex = interchange / "02_texture.wav"

            # Generate 6s synthetic 48kHz stereo core stem (55Hz 808 sub + 220Hz lead) and texture pad (330Hz)
            subprocess.run(
                [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "sine=frequency=55:duration=6:sample_rate=48000",
                    "-f", "lavfi", "-i", "sine=frequency=220:duration=6:sample_rate=48000",
                    "-filter_complex", "[0:a][1:a]amix=inputs=2:weights=0.9 0.6,aformat=channel_layouts=stereo,volume=0.35",
                    "-ar", "48000", "-ac", "2", str(stem_main),
                ],
                check=True,
                timeout=30,
            )
            subprocess.run(
                [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "sine=frequency=330:duration=6:sample_rate=48000",
                    "-af", "aformat=channel_layouts=stereo,volume=0.18",
                    "-ar", "48000", "-ac", "2", str(stem_tex),
                ],
                check=True,
                timeout=30,
            )

            manifest = {
                "mastering_profile": {"lufs": -10.0, "true_peak": -0.8, "lra": 9.0},
                "processing_plan": {"notes": "808 sub glide + spatial stereo shimmer"},
            }
            stems = auto_mod.find_stems(tmp)
            self.assertEqual(len(stems), 2)

            premix_wav = tmp / "premix.wav"
            premix_cmd = auto_mod.build_premix_from_stems(stems, manifest, premix_wav, use_sidechain=True)
            premix_res = subprocess.run(premix_cmd, capture_output=True, text=True, timeout=60)
            self.assertEqual(premix_res.returncode, 0, premix_res.stderr)
            self.assertTrue(premix_wav.exists() and premix_wav.stat().st_size > 50_000)

            master_flac = tmp / "01_TEST_TRACK_MASTER.flac"
            master_res = auto_mod.master_two_pass(premix_wav, manifest, master_flac)
            self.assertEqual(master_res.returncode, 0, master_res.stderr)
            self.assertTrue(master_flac.exists() and master_flac.stat().st_size > 20_000)

            qc = auto_mod.measure_loudness(master_flac)
            measured_i = float(qc["input_i"])
            measured_tp = float(qc["input_tp"])
            self.assertGreaterEqual(measured_i, -11.8, f"Mastered LUFS too quiet: {measured_i}")
            self.assertLessEqual(measured_i, -8.2, f"Mastered LUFS too hot: {measured_i}")
            self.assertLessEqual(measured_tp, -0.4, f"True Peak ceiling exceeded: {measured_tp} dBTP")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
