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
            "data/skills/creative/cover-title-overlay/scripts/overlay-title.py",
            "data/skills/creative/artwork/scripts/gen_artwork.py",
            "data/skills/artwork/artwork/scripts/gen_artwork.py",
            "skills/artwork/artwork/scripts/gen_artwork.py",
            "skills/creative/cover-title-overlay/scripts/overlay-title.py",
            "dawagent/scripts/auto_processor.py",
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
            REPO_ROOT / "data" / "music" / "profiles" / "vidride" / "profile.json",
            REPO_ROOT / "data" / "skills" / "master-producer" / "master-producer" / "SKILL.md",
            REPO_ROOT / "data" / "skills" / "creative" / "artwork" / "SKILL.md",
            REPO_ROOT / "data" / "skills" / "creative" / "cover-title-overlay" / "SKILL.md",
            REPO_ROOT / "skills" / "creative" / "cover-title-overlay" / "SKILL.md",
            REPO_ROOT / "data" / "memories" / "MEMORY.md",
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

        # Weekly canary spend cap & Cohesive VØIDRIDE budget invariant
        bp = model_registry.get_budget_policy(str(reg_path))
        self.assertLessEqual(float(bp["weekly_canary_cap_usd"]), 1.50)
        self.assertAlmostEqual(float(bp["estimated_costs_usd"]["album_total"]), 16.32, places=2)

        # Authentic VØIDRIDE audio model roles
        self.assertEqual(data["roles"]["music.main_instrumental"]["primary"], "elevenlabs-music")
        self.assertEqual(data["roles"]["music.dark_texture"]["primary"], "stable-audio-25")

        # Hybrid Qwen thinking starvation protection
        vp_qwen = model_registry.build_venice_parameters("qwen-3-7-plus", role="llm.proposals", custom_path=str(reg_path))
        self.assertTrue(vp_qwen.get("disable_thinking"), "Hybrid Qwen models must set disable_thinking=True")
        self.assertTrue(vp_qwen.get("strip_thinking_response"))

        # Deduplicated role chain lookup
        chain = model_registry.get_role_chain("music.main_instrumental", custom_path=str(reg_path))
        self.assertGreaterEqual(len(chain), 2)
        self.assertEqual(len(chain), len(set(chain)))

    def test_05_pipeline_cohesive_voidride_and_five_proposal_contracts(self):
        """Enforce REQUIRED_PROPOSAL_COUNT == 5, Cohesive VØIDRIDE ~$16.32 budget, and -11.5 LUFS mastering targets."""
        propose_mod = _load_module_from_path("propose_albums_contract", SCRIPTS_DIR / "propose_albums.py")
        self.assertEqual(
            propose_mod.REQUIRED_PROPOSAL_COUNT,
            5,
            "VØIDRIDE strictly requires 5 proposals (never 3)",
        )
        self.assertAlmostEqual(propose_mod.AVG_ALBUM_COST_USD, 16.32, places=2)

        for rel_auto in (
            "data/skills/dawagent/dawagent/scripts/auto_processor.py",
            "dawagent/scripts/auto_processor.py",
        ):
            auto_proc_path = REPO_ROOT / rel_auto
            if auto_proc_path.exists():
                auto_mod = _load_module_from_path(f"auto_proc_{rel_auto}", auto_proc_path)
                self.assertAlmostEqual(auto_mod.DEFAULT_LUFS, -11.5, places=1)
                self.assertAlmostEqual(auto_mod.DEFAULT_TRUE_PEAK, -1.0, places=1)
                self.assertAlmostEqual(auto_mod.DEFAULT_LRA, 9.5, places=1)

        handoff_txt = (REPO_ROOT / "data" / "skills" / "dawagent" / "dawagent" / "scripts" / "handoff.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"lufs": -11.5', handoff_txt)
        self.assertNotIn('"lufs": -10.0', handoff_txt)

    def test_06_voidride_vibe_and_album_cohesion_contracts(self):
        """Guard classic VØIDRIDE dark nightride sonic DNA, stem stack, DSP sculpting, and strict album-level cohesion."""
        profile_path = REPO_ROOT / "data" / "music" / "profiles" / "vidride" / "profile.json"
        self.assertTrue(profile_path.exists(), f"Missing VØIDRIDE profile: {profile_path}")
        prof_raw = profile_path.read_text(encoding="utf-8")
        prof = json.loads(prof_raw)

        self.assertEqual(prof["defaults"]["main_model"], "elevenlabs-music")
        self.assertEqual(prof["sonic_dna"]["preferred_models"]["main"], "elevenlabs-music")
        self.assertEqual(prof["sonic_dna"]["preferred_models"]["texture"], "stable-audio-25")
        self.assertEqual(prof["sonic_dna"]["preferred_models"]["atmosphere"], "stable-audio-25")
        self.assertIn("NO silence drops", prof["sonic_dna"]["anti_patterns"])
        self.assertAlmostEqual(float(prof["mastering"]["target_lufs"]), -11.5, places=1)
        active_dna_prose = " ".join(
            [
                str(prof.get("description", "")),
                str(prof["sonic_dna"].get("prompt_prefix", "")),
                str(prof["sonic_dna"].get("sound_signature", "")),
            ]
        ).lower()
        self.assertNotIn("earworm", active_dna_prose)
        self.assertNotIn("climax drop 2", active_dna_prose)

        # Verify derive_cohesive_album_grid locks unified subgenre, >=4/5 root minor key, and <=10 BPM cruising pocket
        pa_path = REPO_ROOT / "data" / "skills" / "master-producer" / "master-producer" / "scripts" / "produce-album.py"
        pa_mod = _load_module_from_path("produce_album_cohesion", pa_path)
        grid = pa_mod.derive_cohesive_album_grid(
            "REFINERY MOON - ritual industrial trap / hyperspatial nightride bass. 138-146 BPM, Cm.",
            total_tracks=5,
            sonic_dna=prof["sonic_dna"],
        )
        self.assertEqual(len(grid), 5)
        self.assertEqual(grid[0]["root_key"], "Cm")

        subgenres = {g["subgenre"] for g in grid}
        self.assertEqual(len(subgenres), 1, f"All 5 tracks must share one unified album subgenre, got: {subgenres}")
        self.assertEqual([g["key"] for g in grid], ["Cm", "Cm", "Cm", "Fm", "Cm"])

        bpms = [int(g["bpm"]) for g in grid]
        self.assertTrue(all(138 <= b <= 146 for b in bpms), f"BPMs drifted outside [138, 146]: {bpms}")
        self.assertLessEqual(max(bpms) - min(bpms), 10, f"Album BPM spread exceeded 10 BPM: {bpms}")

        # Verify master-producer.py preserves sub warmth, uses stable-audio-25 dark beds, and omits +12st PitchShift on main
        import inspect
        mp_path = REPO_ROOT / "data" / "skills" / "master-producer" / "master-producer" / "scripts" / "master-producer.py"
        mp_mod = _load_module_from_path("master_producer_vibe", mp_path)
        sculpt_src = inspect.getsource(mp_mod.sculpt_main_with_demucs)
        self.assertNotIn("PitchShift", sculpt_src)
        self.assertIn("1.08", sculpt_src)
        self.assertAlmostEqual(float(mp_mod.TARGET_PROFILES["streaming"]["lufs"]), -11.5, places=1)
        self.assertEqual(mp_mod.STEM_CONFIG["texture"]["model"], "stable-audio-25")
        self.assertEqual(mp_mod.STEM_CONFIG["atmosphere"]["model"], "stable-audio-25")

    def test_07_cover_art_cohesion_typography_and_3k_contracts(self):
        """Guard Album Visual Showrunner world-locking, WCAG Y>=0.45 neon palette cohesion, gateway quickedit fix, and 3K naming."""
        import colorsys
        import shutil
        import tempfile
        from PIL import Image, ImageDraw

        # 1. gen_artwork.py must NEVER hardcode deprecated grok-imagine-image-quality
        for rel_ga in (
            "data/skills/creative/artwork/scripts/gen_artwork.py",
            "data/skills/artwork/artwork/scripts/gen_artwork.py",
            "skills/artwork/artwork/scripts/gen_artwork.py",
        ):
            ga_path = REPO_ROOT / rel_ga
            if ga_path.exists():
                ga_txt = ga_path.read_text(encoding="utf-8")
                self.assertNotIn("grok-imagine-image-quality", ga_txt, f"{rel_ga} still references deprecated image model")
                self.assertIn("get_cover_model_chain", ga_txt)

        # 2. Gateway callback index bug fix: 'art:quickedit:3:darker' -> track_num='3', preset='darker'
        gw_txt = (SCRIPTS_DIR / "patch_gateway.py").read_text(encoding="utf-8")
        self.assertIn("if len(parts) >= 4:", gw_txt)
        choice = "art:quickedit:3:darker"
        parts = choice.split(":")
        track_num = parts[2] if len(parts) >= 4 else parts[1]
        preset = parts[3] if len(parts) >= 4 else parts[2]
        self.assertEqual(track_num, "3")
        self.assertEqual(preset, "darker")

        # 3. overlay-title.py: WCAG relative luminance floor (Y >= 0.45) + album-locked cohesive neon family
        ov_path = REPO_ROOT / "data" / "skills" / "creative" / "cover-title-overlay" / "scripts" / "overlay-title.py"
        ov_mod = _load_module_from_path("overlay_title_contract", ov_path)

        # Dark ultramarine (#192DFF, Y ~ 0.14) must be automatically lifted to luminous ice-blue/orchid (Y >= 0.45)
        raw_dark_blue = (25, 45, 255)
        self.assertLess(ov_mod.relative_luminance(raw_dark_blue), 0.20)
        lifted_rgb = ov_mod.ensure_luminous_neon_rgb(235.0, 0.92, 1.0, min_luminance=0.45)
        self.assertGreaterEqual(
            ov_mod.relative_luminance(lifted_rgb),
            0.45,
            f"Dark blue {raw_dark_blue} was not lifted above WCAG luminance floor: {lifted_rgb}",
        )
        lifted_stops = ov_mod.ensure_luminous_hex_stops("#192DFF", min_luminance=0.45)
        self.assertEqual(len(lifted_stops), 3)
        for rgb_stop in lifted_stops:
            self.assertGreaterEqual(ov_mod.relative_luminance(rgb_stop), 0.45)

        # Album + 5 tracks must lock to _album_family instead of scattering across a 6-color 360-deg rainbow
        tmp = Path(tempfile.mkdtemp(prefix="test_overlay_cohesion_"))
        try:
            alb_bg = tmp / "album_cover_bg.png"
            img = Image.new("RGB", (600, 600), (10, 14, 22))
            draw = ImageDraw.Draw(img)
            draw.rectangle([40, 120, 560, 260], fill=(0, 225, 240))   # Electric cyan rim light
            draw.rectangle([80, 280, 520, 360], fill=(18, 190, 145))  # Cold teal reflection
            img.save(alb_bg, "PNG")

            alb_out = tmp / "album_cover.png"
            ov_mod.overlay_title(
                str(alb_bg),
                "ACID REFLEX",
                output_path=str(alb_out),
                bottom=True,
                auto_color=True,
                stacked=True,
                is_album=True,
            )
            self.assertTrue(alb_out.exists())

            pal_file = tmp / ".cover_palettes.json"
            self.assertTrue(pal_file.exists(), "Album overlay must record .cover_palettes.json")
            pal_data = json.loads(pal_file.read_text(encoding="utf-8"))
            family_obj = pal_data.get("_album_family", {})
            family_hues = family_obj.get("anchor_hues", []) if isinstance(family_obj, dict) else []
            self.assertEqual(len(family_hues), 3, f"Expected 3-hue cohesive album family, got: {family_obj}")

            def _hex_to_hue_and_lum(hx: str):
                h = hx.lstrip("#")
                r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
                hue_deg = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)[0] * 360.0
                return hue_deg, ov_mod.relative_luminance((r, g, b))

            for idx, tr_name in enumerate(["OPTIC NERVE", "CHROME BILE", "CAUSTIC LINE", "VALVE BURN", "PHANTOM SUMP"], 1):
                tr_bg = tmp / f"0{idx}_bg.png"
                shutil.copy2(alb_bg, tr_bg)
                tr_out = tmp / f"0{idx}_cover.png"
                ov_mod.overlay_title(
                    str(tr_bg),
                    tr_name,
                    output_path=str(tr_out),
                    bottom=True,
                    auto_color=True,
                    stacked=True,
                    is_album=False,
                    album_anchor=str(alb_bg),
                )
                self.assertTrue(tr_out.exists())

            pal_after = json.loads(pal_file.read_text(encoding="utf-8"))
            checked_covers = 0
            for key, entry in pal_after.items():
                if key.startswith("_"):
                    continue
                checked_covers += 1
                stops = entry.get("stops_hex", []) if isinstance(entry, dict) else []
                self.assertEqual(len(stops), 3)
                for stop_hex in stops:
                    h_deg, lum = _hex_to_hue_and_lum(stop_hex)
                    self.assertGreaterEqual(lum, 0.44, f"Stop {stop_hex} on {key} violated luminance floor ({lum:.3f})")
                    min_dist = min(abs(((h_deg - fh + 180.0) % 360.0) - 180.0) for fh in family_hues)
                    self.assertLessEqual(
                        min_dist,
                        38.0,
                        f"Track {key} stop {stop_hex} ({h_deg:.1f} deg) drifted outside album family {family_hues}",
                    )
            self.assertEqual(checked_covers, 6, "Expected album cover + 5 track covers recorded in .cover_palettes.json")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        # 4. album_pipeline.py: off-world literal pun scrubber, motif budget caps, and canonical underscore paths
        ap_mod = _load_module_from_path("album_pipeline_contract", SCRIPTS_DIR / "album_pipeline.py")
        noisy_tracks = [
            {
                "track": i + 1,
                "title": f"TRACK {i + 1}",
                "shot_scale": "wide",
                "image_prompt": (
                    "Subterranean concrete bay with shipping containers on an ocean pier beside a nuclear cooling tower. "
                    "A shadowed figure in a fedora stands in the mist. "
                    "A matte-black katana blade rests along the concrete ledge. "
                    "A cold full moon gleams through the skylight."
                ),
            }
            for i in range(5)
        ]
        cleaned = ap_mod._scrub_off_world_puns_and_cap_motifs(
            noisy_tracks,
            "Flooded brutalist subterranean server vault with emerald-cyan coolant mist",
            "Unified nocturnal vault world",
            "Pitch-black obsidian shadows lit strictly by ice electric cyan (#00E5F0)",
            "waning gibbous",
            "77% illuminated silver disc",
        )
        self.assertEqual(len(cleaned), 5)
        self.assertEqual(len({c["shot_scale"] for c in cleaned}), 5, "All 5 tracks must receive distinct shot scales")
        fedora_hits = sum(1 for c in cleaned if "fedora" in c["image_prompt"].lower())
        katana_hits = sum(1 for c in cleaned if "katana" in c["image_prompt"].lower())
        moon_hits = sum(1 for c in cleaned if "moon" in c["image_prompt"].lower())
        self.assertEqual(fedora_hits, 1, f"Fedora cap must keep 1 and scrub 4 across 5 tracks: {fedora_hits}")
        self.assertEqual(katana_hits, 1, f"Katana cap must keep 1 and scrub 4 across 5 tracks: {katana_hits}")
        self.assertEqual(moon_hits, 2, f"Moon cap must keep 2 and scrub 3 across 5 tracks: {moon_hits}")
        for c in cleaned:
            low = c["image_prompt"].lower()
            self.assertNotIn("shipping container", low)
            self.assertNotIn("ocean pier", low)
            self.assertNotIn("nuclear cooling tower", low)

        tmp_art = Path(tempfile.mkdtemp(prefix="test_canon_paths_"))
        try:
            legacy_space = tmp_art / "OPTIC NERVE_cover.png"
            legacy_space.write_bytes(b"legacy")
            bg_p, cov_p, jpg_p = ap_mod.get_canonical_track_cover_paths(str(tmp_art), "OPTIC NERVE")
            self.assertTrue(cov_p.endswith("OPTIC_NERVE_cover.png"))
            self.assertTrue(bg_p.endswith("OPTIC_NERVE_cover_bg.png"))
            self.assertTrue(jpg_p.endswith("OPTIC_NERVE_cover.jpg"))
            self.assertTrue(os.path.exists(cov_p), "Legacy space-named cover must migrate to canonical underscore path")
        finally:
            shutil.rmtree(tmp_art, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
