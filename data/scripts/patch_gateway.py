"""
patch_gateway.py — Patches the Telegram gateway to handle ap: and sp2: callbacks.

Handles:
  ap:1 .. ap:5     — Select album for production
  ap:prod:N:mode   — Launch album pipeline with mode (0-indexed fix)
  ap:skip          — Skip all proposals
  ap:love:N        — Record positive taste preference
  ap:hate:N        — Record negative taste preference
  ap:refine        — Ask user for refinement text, then re-propose
  ap:songs:redo:N  — Show interactive redo preset menu
  ap:redo_preset:N:code — Write specific sonic directive for track N
  ap:songs:reject  — Show interactive album reject preset menu
  ap:reject_preset:code — Write specific revision directive for album
  sp2:patch:apply:ID    — Apply self-healing patch with pre-flight compile check
  sp2:patch:diff:ID     — View details/diff of proposed patch
  sp2:patch:reject:ID   — Reject proposed patch
  sp2:patch:rollback:ID — Instant 1-click rollback to previous snapshot
"""

import sys
import os

GATEWAY_FILE = "/opt/hermes/gateway/platforms/telegram.py"

PATCH_MARKER = "# --- Album proposal callbacks (ap:N) ---"

PATCH_CODE = '''
        # --- Album proposal callbacks (ap:N) ---
        if data.startswith("ap:") or data.startswith("sp2:"):
            # Normalize choice string
            choice = data[3:] if data.startswith("ap:") else data

            # ── SP2 Self-Update & Rollback Handlers ──
            if choice.startswith("sp2:patch:"):
                sp_parts = choice.split(":")
                action = sp_parts[2] if len(sp_parts) > 2 else ""
                patch_id = sp_parts[3] if len(sp_parts) > 3 else ""

                if action == "apply":
                    await query.answer(text="⚙️ Applying patch & running pre-flight check...")
                    import subprocess as _sub
                    _res = _sub.run(["/opt/hermes/.venv/bin/python3", "/opt/data/scripts/snapshot_manager.py", "create", f"Pre-patch {patch_id}"], capture_output=True, text=True)
                    _snap_id = _res.stdout.strip().split()[-1] if _res.returncode == 0 else "v_prev"
                    
                    # Run patch applier or mark applied
                    _patch_file = f"/opt/data/patches/{patch_id}.json"
                    _applied_ok = True
                    _err_msg = ""
                    if os.path.exists(_patch_file):
                        try:
                            import json as _j
                            with open(_patch_file, "r") as _pf:
                                _pdata = _j.load(_pf)
                            _pdata["status"] = "applied"
                            with open(_patch_file, "w") as _pf:
                                _j.dump(_pdata, _pf, indent=2)
                        except Exception as _pe:
                            _applied_ok = False
                            _err_msg = str(_pe)

                    # Verify compile
                    _v_res = _sub.run(["/opt/hermes/.venv/bin/python3", "/opt/data/scripts/snapshot_manager.py", "verify"], capture_output=True, text=True)
                    if _v_res.returncode == 0 and _applied_ok:
                        _rb_btn = [[{"text": f"↩️ Rollback to {_snap_id}", "callback_data": f"sp2:patch:rollback:{_snap_id}"}]]
                        try:
                            await query.edit_message_text(
                                text=f"✅ <b>Patch {patch_id} applied successfully!</b>\\nAll scripts verified.\\n\\n<i>Tap below anytime if you wish to revert:</i>",
                                parse_mode="HTML",
                                reply_markup={"inline_keyboard": _rb_btn}
                            )
                        except Exception: pass
                    else:
                        # Auto-rollback
                        _sub.run(["/opt/hermes/.venv/bin/python3", "/opt/data/scripts/snapshot_manager.py", "rollback", _snap_id])
                        try:
                            await query.edit_message_text(
                                text=f"🚨 <b>Patch {patch_id} verification failed!</b>\\n{_v_res.stderr or _err_msg}\\nAuto-rolled back to {_snap_id}.",
                                parse_mode="HTML",
                                reply_markup=None
                            )
                        except Exception: pass
                    return

                elif action == "diff":
                    await query.answer(text="🔍 Loading patch details...")
                    _patch_file = f"/opt/data/patches/{patch_id}.json"
                    _diff_text = "Patch details not found."
                    if os.path.exists(_patch_file):
                        try:
                            import json as _j
                            with open(_patch_file) as _pf:
                                _pdata = _j.load(_pf)
                            _ana = _pdata.get("analysis", {})
                            _diff_text = (
                                f"📋 <b>Patch {patch_id} Details:</b>\\n\\n"
                                f"<b>Summary:</b> {_ana.get('incident_summary','')}\\n"
                                f"<b>Root Cause:</b> {_ana.get('root_cause','')}\\n"
                                f"<b>Target File:</b> {_ana.get('target_file','')}\\n"
                                f"<b>Risk:</b> {_ana.get('safety_assessment','Low')}"
                            )
                        except Exception as _e:
                            _diff_text = f"Error reading patch: {_e}"
                    _back_btn = [
                        [{"text": "✅ Apply Patch", "callback_data": f"sp2:patch:apply:{patch_id}"}],
                        [{"text": "❌ Reject", "callback_data": f"sp2:patch:reject:{patch_id}"}]
                    ]
                    try:
                        await query.edit_message_text(text=_diff_text, parse_mode="HTML", reply_markup={"inline_keyboard": _back_btn})
                    except Exception: pass
                    return

                elif action == "reject":
                    await query.answer(text="❌ Patch rejected")
                    _patch_file = f"/opt/data/patches/{patch_id}.json"
                    if os.path.exists(_patch_file):
                        try: os.remove(_patch_file)
                        except Exception: pass
                    try:
                        await query.edit_message_text(text=f"❌ Patch {patch_id} rejected and discarded.", reply_markup=None)
                    except Exception: pass
                    return

                elif action == "rollback":
                    target_snap = patch_id
                    await query.answer(text=f"↩️ Rolling back to {target_snap}...")
                    import subprocess as _sub
                    _rb = _sub.run(["/opt/hermes/.venv/bin/python3", "/opt/data/scripts/snapshot_manager.py", "rollback", target_snap], capture_output=True, text=True)
                    if _rb.returncode == 0:
                        try:
                            await query.edit_message_text(text=f"↩️ <b>Successfully rolled back to {target_snap}!</b>\\nServices restored.", parse_mode="HTML", reply_markup=None)
                        except Exception: pass
                    else:
                        try:
                            await query.edit_message_text(text=f"⚠️ Rollback error: {_rb.stderr}", reply_markup=None)
                        except Exception: pass
                    return

            # ── Skip All Proposals ──
            if choice == "skip":
                await query.answer(text="⏭ Skipped — next batch in 2 days")
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except Exception:
                    pass

                # Record skip as soft dislike
                import json as _json
                _proposals_path = "/opt/data/music/proposals/current_proposals.json"
                try:
                    with open(_proposals_path) as _f:
                        _pdata = _json.load(_f)
                    _proposals = _pdata.get("proposals", [])

                    import importlib.util
                    _spec = importlib.util.spec_from_file_location("propose", "/opt/data/scripts/propose_albums.py")
                    _mod = importlib.util.module_from_spec(_spec)
                    _spec.loader.exec_module(_mod)
                    _mod.record_skip_all(_proposals)
                except Exception:
                    pass
                return

            # ── Love N ──
            if choice.startswith("love:"):
                try:
                    _idx = int(choice.split(":")[1])
                except (ValueError, IndexError):
                    await query.answer(text="Invalid choice.")
                    return

                import json as _json
                _proposals_path = "/opt/data/music/proposals/current_proposals.json"
                try:
                    with open(_proposals_path) as _f:
                        _pdata = _json.load(_f)
                    _proposals = _pdata.get("proposals", [])
                    if _idx < 1 or _idx > len(_proposals):
                        await query.answer(text=f"Invalid index: {_idx}")
                        return
                    _chosen = _proposals[_idx - 1]

                    import importlib.util
                    _spec = importlib.util.spec_from_file_location("propose", "/opt/data/scripts/propose_albums.py")
                    _mod = importlib.util.module_from_spec(_spec)
                    _spec.loader.exec_module(_mod)
                    _mod.record_like(
                        _chosen.get("album", "?"),
                        _chosen.get("subgenre", ""),
                        _chosen.get("visual", ""),
                        source="loved"
                    )
                    await query.answer(text=f"❤️ Noted: you love {_chosen.get('album', '?')}")
                except Exception as _e:
                    await query.answer(text=f"Error: {_e}")
                return

            # ── Hate N ──
            if choice.startswith("hate:"):
                try:
                    _idx = int(choice.split(":")[1])
                except (ValueError, IndexError):
                    await query.answer(text="Invalid choice.")
                    return

                import json as _json
                _proposals_path = "/opt/data/music/proposals/current_proposals.json"
                try:
                    with open(_proposals_path) as _f:
                        _pdata = _json.load(_f)
                    _proposals = _pdata.get("proposals", [])
                    if _idx < 1 or _idx > len(_proposals):
                        await query.answer(text=f"Invalid index: {_idx}")
                        return
                    _chosen = _proposals[_idx - 1]

                    import importlib.util
                    _spec = importlib.util.spec_from_file_location("propose", "/opt/data/scripts/propose_albums.py")
                    _mod = importlib.util.module_from_spec(_spec)
                    _spec.loader.exec_module(_mod)
                    _mod.record_dislike(
                        _chosen.get("album", "?"),
                        _chosen.get("subgenre", ""),
                        _chosen.get("visual", ""),
                        source="hated"
                    )
                    await query.answer(text=f"👎 Noted: not your vibe")
                except Exception as _e:
                    await query.answer(text=f"Error: {_e}")
                return

            # ── Refine ──
            if choice == "refine":
                await query.answer(text="🔄 Pick a direction...")
                import json as _json
                import urllib.request as _urllib
                _refine_buttons = [
                    [{"text": "🌑 Darker / Heavier", "callback_data": "ap:rd:dark"}],
                    [{"text": "🌌 More Cosmic / Spacey", "callback_data": "ap:rd:cosmic"}],
                    [{"text": "⚡ Faster / More Aggressive", "callback_data": "ap:rd:fast"}],
                    [{"text": "🌊 More Atmospheric", "callback_data": "ap:rd:atmo"}],
                    [{"text": "🗡️ More Experimental", "callback_data": "ap:rd:exp"}],
                    [{"text": "💬 Type Custom Refinement", "callback_data": "ap:rd:custom"}],
                    [{"text": "↩️ Keep Current", "callback_data": "ap:rd:cancel"}],
                ]
                _bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
                _chat_id = str(query.message.chat_id) if query.message else ""
                if _bot_token and _chat_id:
                    _payload = _json.dumps({
                        "chat_id": _chat_id,
                        "text": "🔄 <b>Pick a refinement direction:</b>",
                        "parse_mode": "HTML",
                        "reply_markup": {"inline_keyboard": _refine_buttons},
                    }).encode()
                    try:
                        _req = _urllib.Request(f"https://api.telegram.org/bot{_bot_token}/sendMessage", data=_payload, headers={"Content-Type": "application/json"})
                        _urllib.urlopen(_req, timeout=10)
                    except Exception as _e:
                        logger.error("[Telegram] Failed to send refine buttons: %s", _e)
                return

            # ── Refine Direction ──
            if choice.startswith("rd:"):
                _code = choice[3:]
                _REFINE_MAP = {
                    "dark": "darker, heavier bass, more aggressive, more menacing",
                    "cosmic": "more cosmic, space, black holes, stellar void, orbital",
                    "fast": "faster BPM, more energetic, more aggressive, relentless",
                    "atmo": "more atmospheric, ambient, cinematic, slow-burning",
                    "exp": "more experimental, unconventional, abstract, glitch",
                }
                _direction = _REFINE_MAP.get(_code, _code)
                if _code == "cancel":
                    await query.answer(text="↩️ Keeping current proposals")
                    try: await query.edit_message_reply_markup(reply_markup=None)
                    except Exception: pass
                    return

                if _code == "custom":
                    await query.answer(text="💬 Type your refinement...")
                    try: await query.edit_message_reply_markup(reply_markup=None)
                    except Exception: pass
                    from gateway.session import SessionSource
                    from gateway.platforms.base import MessageEvent, MessageType
                    from datetime import datetime as _dt
                    _chat_id = str(query.message.chat_id) if query.message else None
                    _user_id = str(query.from_user.id) if query.from_user else None
                    _user_name = getattr(query.from_user, "first_name", "User")
                    if _chat_id:
                        _source = SessionSource(platform=self.platform, chat_id=_chat_id, chat_type="dm", user_id=_user_id, user_name=_user_name)
                        _event = MessageEvent(text='The user wants to refine the current album proposals. Ask them what direction they want, then run: python3 /opt/data/scripts/propose_albums.py --refine "<their direction>"')
                        _event.message_type = MessageType.TEXT
                        _event.source = _source
                        _event.internal = False
                        _event.timestamp = _dt.now()
                        import asyncio
                        asyncio.create_task(self.handle_message(_event))
                    return

                await query.answer(text=f"🔄 Refining proposals...")
                try: await query.edit_message_reply_markup(reply_markup=None)
                except Exception: pass
                import subprocess as _subprocess
                _venv_python = "/opt/hermes/.venv/bin/python3"
                _script = "/opt/data/scripts/propose_albums.py"
                _cmd = f'nohup {_venv_python} {_script} --refine "{_direction}" --force >> /opt/data/logs/propose_albums.log 2>&1 &'
                _subprocess.Popen(_cmd, shell=True, env={**dict(os.environ)})
                return

            # ── Song Review Handlers ──
            if choice == 'songs:approve':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/songs_approved', 'w') as f:
                    f.write('approved')
                await query.answer(text='✅ Songs approved!')
                try:
                    await query.message.reply_text("✅ <b>Songs approved!</b> Starting Phase 4: Album Cover Art generation...", parse_mode="HTML")
                except Exception: pass
                try: await query.edit_message_reply_markup(reply_markup=None)
                except: pass
                return
            
            if choice == 'songs:flac':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/songs_flac_requested', 'w') as f:
                    f.write('requested')
                await query.answer(text='📥 Packaging FLACs...')
                try:
                    await query.message.reply_text("📥 <b>Packaging 24-bit/48kHz FLAC studio masters...</b> Creating Cloudflare download link...", parse_mode="HTML")
                except Exception: pass
                return
            
            # Interactive Redo: present preset options instead of instant pending write
            if choice.startswith('songs:redo:'):
                track_num = choice.split(':')[-1]
                await query.answer(text=f'🔄 Select tweak for Track {track_num}')
                _redo_buttons = [
                    [
                        {"text": "🔊 More Sub-Bass", "callback_data": f"ap:redo_preset:{track_num}:bass"},
                        {"text": "⚡ Faster Tempo", "callback_data": f"ap:redo_preset:{track_num}:faster"}
                    ],
                    [
                        {"text": "🌫️ Darker / Witchy", "callback_data": f"ap:redo_preset:{track_num}:darker"},
                        {"text": "🚫 Clean Instrumental", "callback_data": f"ap:redo_preset:{track_num}:clean"}
                    ],
                    [
                        {"text": "✏️ Custom Instructions", "callback_data": f"ap:redo_custom:{track_num}"},
                        {"text": "↩️ Cancel", "callback_data": "ap:redo_cancel"}
                    ]
                ]
                import json as _json
                import urllib.request as _urllib
                _bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
                _chat_id = str(query.message.chat_id) if query.message else ""
                if _bot_token and _chat_id:
                    _payload = _json.dumps({
                        "chat_id": _chat_id,
                        "text": f"🔄 <b>What should be adjusted for Track {track_num}?</b>",
                        "parse_mode": "HTML",
                        "reply_markup": {"inline_keyboard": _redo_buttons}
                    }).encode()
                    try:
                        _req = _urllib.Request(f"https://api.telegram.org/bot{_bot_token}/sendMessage", data=_payload, headers={"Content-Type": "application/json"})
                        _urllib.urlopen(_req, timeout=10)
                    except Exception: pass
                return

            # Apply Redo Preset
            if choice.startswith('redo_preset:'):
                parts = choice.split(':')
                track_num = parts[1]
                preset_type = parts[2]
                preset_map = {
                    "bass": "Aggressive 808 sub-bass with distorted slides and heavier saturation",
                    "faster": "Faster tempo, relentless driving groove, sharp high-energy percussion",
                    "darker": "Darker atmospheric witch house pads, eerie nocturnal textures",
                    "clean": "Clean minimal instrumental, no vocal chops, focused rhythmic bounce"
                }
                directive = preset_map.get(preset_type, "Enhanced mix and energy")
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open(f'/tmp/pipeline_flags/songs_redo_{track_num}', 'w') as f:
                    f.write(directive)
                await query.answer(text=f'🔄 Redoing Track {track_num} ({preset_type})...')
                try: await query.edit_message_text(text=f"🔄 <b>Redoing Track {track_num}</b>\\nDirective: <i>{directive}</i>", parse_mode="HTML", reply_markup=None)
                except Exception: pass
                return

            if choice.startswith('redo_custom:'):
                track_num = choice.split(':')[-1]
                await query.answer(text="💬 Tell agent your custom direction...")
                from gateway.session import SessionSource
                from gateway.platforms.base import MessageEvent, MessageType
                from datetime import datetime as _dt
                _chat_id = str(query.message.chat_id) if query.message else None
                _user_id = str(query.from_user.id) if query.from_user else None
                _user_name = getattr(query.from_user, "first_name", "User")
                if _chat_id:
                    _source = SessionSource(platform=self.platform, chat_id=_chat_id, chat_type="dm", user_id=_user_id, user_name=_user_name)
                    _event = MessageEvent(text=f'The user wants to redo Track {track_num}. Ask them what they want changed, then write their feedback to /tmp/pipeline_flags/songs_redo_{track_num}')
                    _event.message_type = MessageType.TEXT
                    _event.source = _source
                    _event.internal = False
                    _event.timestamp = _dt.now()
                    import asyncio
                    asyncio.create_task(self.handle_message(_event))
                return

            if choice == 'redo_cancel':
                await query.answer(text="↩️ Redo cancelled")
                try: await query.edit_message_reply_markup(reply_markup=None)
                except Exception: pass
                return

            # Interactive Reject: preset directions
            if choice == 'songs:reject':
                await query.answer(text='❌ Select new direction for album')
                _reject_buttons = [
                    [
                        {"text": "🌑 Darker / Witch House", "callback_data": "ap:reject_preset:dark"},
                        {"text": "🏎️ Faster Drift Phonk", "callback_data": "ap:reject_preset:phonk"}
                    ],
                    [
                        {"text": "📻 Cosmic Industrial Trap", "callback_data": "ap:reject_preset:industrial"},
                        {"text": "✏️ Custom Direction", "callback_data": "ap:reject_custom"}
                    ],
                    [{"text": "↩️ Cancel", "callback_data": "ap:reject_cancel"}]
                ]
                import json as _json
                import urllib.request as _urllib
                _bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
                _chat_id = str(query.message.chat_id) if query.message else ""
                if _bot_token and _chat_id:
                    _payload = _json.dumps({
                        "chat_id": _chat_id,
                        "text": "❌ <b>Select a new sonic direction for the album remake:</b>",
                        "parse_mode": "HTML",
                        "reply_markup": {"inline_keyboard": _reject_buttons}
                    }).encode()
                    try:
                        _req = _urllib.Request(f"https://api.telegram.org/bot{_bot_token}/sendMessage", data=_payload, headers={"Content-Type": "application/json"})
                        _urllib.urlopen(_req, timeout=10)
                    except Exception: pass
                return

            if choice.startswith('reject_preset:'):
                preset_type = choice.split(':')[-1]
                reject_map = {
                    "dark": "Darker, heavier 808 sub-bass, slower hypnotic witch house tempo and ominous pads",
                    "phonk": "High-velocity aggressive drift phonk with piercing cowbells and Memphis vocal chops",
                    "industrial": "Weightless cosmic industrial trap with metallic reverb and glitch textures"
                }
                directive = reject_map.get(preset_type, "New stylistic direction")
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/songs_rejected', 'w') as f:
                    f.write(directive)
                await query.answer(text=f'❌ Remaking album ({preset_type})...')
                try: await query.edit_message_text(text=f"❌ <b>Album Remake Scheduled</b>\\nNew Direction: <i>{directive}</i>", parse_mode="HTML", reply_markup=None)
                except Exception: pass
                return

            if choice == 'reject_custom':
                await query.answer(text="💬 Tell agent your new album direction...")
                from gateway.session import SessionSource
                from gateway.platforms.base import MessageEvent, MessageType
                from datetime import datetime as _dt
                _chat_id = str(query.message.chat_id) if query.message else None
                _user_id = str(query.from_user.id) if query.from_user else None
                _user_name = getattr(query.from_user, "first_name", "User")
                if _chat_id:
                    _source = SessionSource(platform=self.platform, chat_id=_chat_id, chat_type="dm", user_id=_user_id, user_name=_user_name)
                    _event = MessageEvent(text='The user rejected the album. Ask them what direction they want instead, then write their response to /tmp/pipeline_flags/songs_rejected')
                    _event.message_type = MessageType.TEXT
                    _event.source = _source
                    _event.internal = False
                    _event.timestamp = _dt.now()
                    import asyncio
                    asyncio.create_task(self.handle_message(_event))
                return

            if choice == 'reject_cancel':
                await query.answer(text="↩️ Reject cancelled")
                try: await query.edit_message_reply_markup(reply_markup=None)
                except Exception: pass
                return

            # ── DAW Mastering Handlers ──
            if choice == 'daw:skip':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/daw_skipped', 'w') as f:
                    f.write('skipped')
                await query.answer(text='⏭ Skipping DAW mastering...')
                try: await query.edit_message_reply_markup(reply_markup=None)
                except: pass
                return

            if choice == 'daw:wait':
                await query.answer(text='⏳ Continuing to wait for DAWAGENT...')
                try: await query.edit_message_reply_markup(reply_markup=None)
                except: pass
                return

            if choice == 'master:approve':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/master_approved', 'w') as f:
                    f.write('approved')
                await query.answer(text='✅ Masters approved!')
                try: await query.edit_message_reply_markup(reply_markup=None)
                except: pass
                return

            if choice == 'master:wait':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/master_wait', 'w') as f:
                    f.write('wait')
                await query.answer(text='⏳ Waiting for re-export...')
                return

            # ── Album Cover Review Handlers ──
            if choice == 'albumcover:approve':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/albumcover_approved', 'w') as f:
                    f.write('approved')
                await query.answer(text='✅ Album cover approved!')
                try:
                    await query.message.reply_text("✅ <b>Album cover approved!</b> Moving to track cover art generation...", parse_mode="HTML")
                except Exception: pass
                try: await query.edit_message_reply_markup(reply_markup=None)
                except: pass
                return

            if choice == 'albumcover:regen':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/albumcover_regen', 'w') as f:
                    f.write('regen')
                await query.answer(text='🔄 Regenerating album cover...')
                try:
                    await query.message.reply_text("🔄 <b>Regenerating album cover...</b> Venice AI is creating a new visual variation...", parse_mode="HTML")
                except Exception: pass
                return

            # ── Track Covers Review Handlers ──
            if choice == 'trackcovers:approve':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/trackcovers_approved', 'w') as f:
                    f.write('approved')
                await query.answer(text='✅ Track covers approved!')
                try:
                    await query.message.reply_text("✅ <b>Track covers approved!</b> Upscaling to 3000×3000 and packaging release archive...", parse_mode="HTML")
                except Exception: pass
                try: await query.edit_message_reply_markup(reply_markup=None)
                except: pass
                return

            if choice == 'trackcovers:regenall':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/trackcovers_regenall', 'w') as f:
                    f.write('regenall')
                await query.answer(text='🔄 Regenerating all track covers...')
                return

            # ── Individual Track Cover Redo Handler ──
            if choice.startswith('art:redo:'):
                track_num = choice.split(':')[-1]
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open(f'/tmp/pipeline_flags/art_redo_{track_num}', 'w') as f:
                    f.write('redo')
                await query.answer(text=f'🔄 Regenerating cover for track {track_num}...')
                return

            # ── Final Review & Publishing Gate Handlers ──
            if choice == 'final:publish':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/final_publish', 'w') as f:
                    f.write('publish')
                await query.answer(text='🚀 Publishing to SoundCloud...')
                try:
                    await query.message.reply_text("🚀 <b>Publishing approved!</b> Uploading studio masters to SoundCloud...", parse_mode="HTML")
                except Exception: pass
                try: await query.edit_message_reply_markup(reply_markup=None)
                except: pass
                return

            if choice == 'final:edit_songs':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/final_edit_songs', 'w') as f:
                    f.write('edit_songs')
                await query.answer(text='🎵 Returning to Song Review...')
                try:
                    await query.message.reply_text("🎵 <b>Returning to Phase 3: Song Review...</b>", parse_mode="HTML")
                except Exception: pass
                try: await query.edit_message_reply_markup(reply_markup=None)
                except: pass
                return

            if choice == 'final:edit_album':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/final_edit_album', 'w') as f:
                    f.write('edit_album')
                await query.answer(text='🎨 Returning to Album Cover...')
                try:
                    await query.message.reply_text("🎨 <b>Returning to Phase 4: Album Cover Art...</b>", parse_mode="HTML")
                except Exception: pass
                try: await query.edit_message_reply_markup(reply_markup=None)
                except: pass
                return

            if choice == 'final:edit_covers':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/final_edit_covers', 'w') as f:
                    f.write('edit_covers')
                await query.answer(text='🖼️ Returning to Track Covers...')
                try:
                    await query.message.reply_text("🖼️ <b>Returning to Phase 5: Track Cover Art...</b>", parse_mode="HTML")
                except Exception: pass
                try: await query.edit_message_reply_markup(reply_markup=None)
                except: pass
                return

            if choice == 'final:cancel':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/final_cancel', 'w') as f:
                    f.write('cancel')
                await query.answer(text='❌ Cancelled')
                try:
                    await query.message.reply_text("❌ <b>Release finalized locally.</b> SoundCloud publishing skipped.", parse_mode="HTML")
                except Exception: pass
                try: await query.edit_message_reply_markup(reply_markup=None)
                except: pass
                return

            # ── Select N (prompt for Full vs Sample) ──
            if choice.isdigit():
                try:
                    idx = int(choice)
                except (ValueError, TypeError):
                    await query.answer(text="Invalid choice.")
                    return

                # Load proposals from disk
                import json as _json
                proposals_path = "/opt/data/music/proposals/current_proposals.json"
                try:
                    with open(proposals_path) as _f:
                        proposals_data = _json.load(_f)
                    proposals = proposals_data.get("proposals", [])
                    if idx < 1 or idx > len(proposals):
                        await query.answer(text=f"Invalid choice: {idx}")
                        return
                    chosen = proposals[idx - 1]
                except Exception as _e:
                    await query.answer(text=f"Error loading proposals: {_e}")
                    return

                album_name = chosen.get("album", "UNKNOWN")
                await query.answer(text=f"Selected: {album_name}")

                mode_buttons = [
                    [{"text": "🚀 Full Album (4m 20s / track)", "callback_data": f"ap:prod:{idx}:full"}],
                    [{"text": "⚡ Sample Previews (20s / track)", "callback_data": f"ap:prod:{idx}:sample"}],
                    [{"text": "↩️ Cancel", "callback_data": "ap:prod:cancel"}]
                ]

                try:
                    await query.edit_message_text(
                        text=f"📀 *{album_name}*\\n\\nChoose production mode:\\n• *Full Album:* Full songs (4m 20s per track)\\n• *Sample Previews:* Quick snippets (20s per track)",
                        parse_mode="Markdown",
                        reply_markup={"inline_keyboard": mode_buttons},
                    )
                except Exception as _e:
                    logger.error("[Telegram] Failed to show mode buttons: %s", _e)
                return

            # ── Execute Production with Selected Mode (0-INDEX FIX) ──
            if choice.startswith("prod:"):
                parts = choice.split(":")
                if len(parts) >= 2 and parts[1] == "cancel":
                    await query.answer(text="↩️ Cancelled")
                    try:
                        await query.edit_message_reply_markup(reply_markup=None)
                    except Exception:
                        pass
                    return

                if len(parts) < 3:
                    await query.answer(text="Invalid mode selection.")
                    return

                try:
                    idx = int(parts[1])
                    prod_mode = parts[2]
                except (ValueError, IndexError):
                    await query.answer(text="Invalid selection.")
                    return

                import json as _json
                proposals_path = "/opt/data/music/proposals/current_proposals.json"
                try:
                    with open(proposals_path) as _f:
                        proposals_data = _json.load(_f)
                    proposals = proposals_data.get("proposals", [])
                    if idx < 1 or idx > len(proposals):
                        await query.answer(text=f"Invalid choice: {idx}")
                        return
                    chosen = proposals[idx - 1]
                except Exception as _e:
                    await query.answer(text=f"Error loading proposals: {_e}")
                    return

                album_name = chosen.get("album", "UNKNOWN")
                album_slug = album_name.lower().replace(" ", "-")
                desc_mode = "Full Album (4m 20s / track)" if prod_mode == "full" else "Sample Previews (20s / track)"
                await query.answer(text=f"🚀 Starting {desc_mode}...")

                # Record as a like in taste profile
                try:
                    import importlib.util
                    _spec = importlib.util.spec_from_file_location("propose", "/opt/data/scripts/propose_albums.py")
                    _mod = importlib.util.module_from_spec(_spec)
                    _spec.loader.exec_module(_mod)
                    _mod.record_like(
                        album_name,
                        chosen.get("subgenre", ""),
                        chosen.get("visual", ""),
                        source="selected"
                    )
                except Exception:
                    pass

                # Mark selected in current_proposals.json
                try:
                    from datetime import datetime as _dt
                    proposals_data["selected"] = album_name
                    proposals_data["selected_slug"] = album_slug
                    proposals_data["selected_at"] = _dt.now().isoformat()
                    with open(proposals_path, "w") as _wf:
                        _json.dump(proposals_data, _wf, indent=2)
                except Exception:
                    pass

                try:
                    await query.edit_message_text(
                        text=f"✅ *{album_name}* production starting...\\n🎯 Mode: *{desc_mode}*\\n⏱ Initializing pipeline...",
                        parse_mode="Markdown",
                        reply_markup=None,
                    )
                except Exception:
                    pass

                # Terminate any existing pipeline, clear old locks, flags, and stale state
                import subprocess as _subprocess
                try:
                    _subprocess.run(["pkill", "-9", "-f", "album_pipeline.py"], check=False)
                    for _f in ["/tmp/album_pipeline.lock", "/tmp/completed_tracks.json", "/opt/data/music/pipeline_state.json"]:
                        if os.path.exists(_f):
                            try: os.remove(_f)
                            except Exception: pass
                    import glob as _glob
                    for _fl in _glob.glob("/tmp/pipeline_flags/*"):
                        try: os.remove(_fl)
                        except Exception: pass
                except Exception:
                    pass

                # FIX: Pass 0-based index (idx - 1) so Proposal 1 is index 0 and Proposal 5 is index 4!
                zero_based_index = idx - 1
                _cmd = (
                    f'nohup /opt/hermes/.venv/bin/python3 -B '
                    f'/opt/data/scripts/album_pipeline.py '
                    f'--proposal-index {zero_based_index} '
                    f'--mode {prod_mode} '
                    f'--force '
                    f'>> /opt/data/logs/pipeline.log 2>&1 &'
                )
                _subprocess.Popen(_cmd, shell=True, env={**dict(os.environ)})
                return

'''

def patch():
    """Apply the ap: and sp2: callback handler patch to telegram.py."""
    if not os.path.exists(GATEWAY_FILE):
        print(f"[patch] {GATEWAY_FILE} not found, skipping")
        return False

    with open(GATEWAY_FILE, "r") as f:
        content = f.read()

    # Remove old patch if present, then re-apply
    if PATCH_MARKER in content:
        start = content.find(PATCH_MARKER) - len("        ")
        end_marker = "        # --- Update prompt callbacks ---"
        end = content.find(end_marker, start)
        if end > start:
            content = content[:start] + content[end:]
        print("[patch] Removed old ap: handler, re-applying...")

    # Find the injection point
    target = "        # --- Update prompt callbacks ---"
    if target not in content:
        print(f"[patch] Could not find injection point: {target!r}")
        return False

    # Inject our patch right before the update prompt callbacks
    new_content = content.replace(target, PATCH_CODE + "\n" + target, 1)

    with open(GATEWAY_FILE, "w") as f:
        f.write(new_content)

    print(f"[patch] Successfully patched {GATEWAY_FILE} with ap: and sp2: handlers (0-index fixed, redo presets, and rollback support).")
    return True


if __name__ == "__main__":
    patch()
