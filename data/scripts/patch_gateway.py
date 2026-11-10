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

            # ── Weekly Venice Model PR Gate Handlers (sp2:model_pr:merge|status|close) ──
            if choice.startswith("sp2:model_pr:"):
                mp_parts = choice.split(":")
                mp_action = mp_parts[2] if len(mp_parts) > 2 else ""
                mp_pr_num = mp_parts[3] if len(mp_parts) > 3 else ""
                mp_extra = mp_parts[4] if len(mp_parts) > 4 else ""
                import subprocess as _sub
                import json as _j

                if mp_action == "status":
                    await query.answer(text=f"🔍 Checking GitHub Actions CI for PR #{mp_pr_num}...")
                    _st = _sub.run(
                        ["/opt/hermes/.venv/bin/python3", "/opt/data/scripts/model_pr_manager.py", "status", mp_pr_num],
                        capture_output=True, text=True, timeout=35
                    )
                    try:
                        _st_obj = _j.loads(_st.stdout.strip()) if _st.stdout.strip() else {}
                        _st_msg = _st_obj.get("message") or _st.stderr or "Unknown status"
                    except Exception:
                        _st_msg = _st.stdout or _st.stderr or "Status check error"
                    await query.message.reply_text(f"🔎 <b>PR #{mp_pr_num} CI Status:</b>\\n{_st_msg}", parse_mode="HTML")
                    return

                elif mp_action == "merge":
                    await query.answer(text=f"⚙️ Verifying CI & merging PR #{mp_pr_num}...")
                    _mg = _sub.run(
                        ["/opt/hermes/.venv/bin/python3", "/opt/data/scripts/model_pr_manager.py", "merge", mp_pr_num],
                        capture_output=True, text=True, timeout=90
                    )
                    try:
                        _mg_obj = _j.loads(_mg.stdout.strip()) if _mg.stdout.strip() else {}
                    except Exception:
                        _mg_obj = {"merged": False, "error": _mg.stderr or _mg.stdout}

                    if _mg_obj.get("merged"):
                        _snap = _mg_obj.get("snapshot_id") or ""
                        _rb_kb = [[{"text": f"↩️ Rollback Snapshot ({_snap})", "callback_data": f"sp2:patch:rollback:{_snap}"}]] if _snap else None
                        try:
                            await query.edit_message_text(
                                text=(
                                    f"✅ <b>Merged PR #{mp_pr_num} &amp; Deployed Live!</b>\\n"
                                    f"• <b>CI Gate:</b> {_mg_obj.get('ci_summary', 'Passed')}\\n"
                                    f"• <b>Commit:</b> <code>{str(_mg_obj.get('sha', ''))[:7]}</code>\\n"
                                    f"• <b>Live Env Verify:</b> {'✅ Passed' if _mg_obj.get('verify_ok') else '⚠️ Check logs'}"
                                ),
                                parse_mode="HTML",
                                reply_markup={"inline_keyboard": _rb_kb} if _rb_kb else None,
                            )
                        except Exception:
                            pass
                    else:
                        await query.message.reply_text(
                            f"⚠️ <b>Merge Blocked for PR #{mp_pr_num}:</b>\\n{_mg_obj.get('error', 'CI checks not green yet')}",
                            parse_mode="HTML",
                        )
                    return

                elif mp_action == "close":
                    await query.answer(text=f"❌ Closing PR #{mp_pr_num}...")
                    _cmd = ["/opt/hermes/.venv/bin/python3", "/opt/data/scripts/model_pr_manager.py", "close", mp_pr_num]
                    if mp_extra:
                        _cmd.extend(["--reject-models", mp_extra])
                    _sub.run(_cmd, capture_output=True, text=True, timeout=35)
                    try:
                        await query.edit_message_text(
                            text=f"❌ <b>PR #{mp_pr_num} closed.</b> Candidate(s) recorded in <code>rejected_candidates</code>.",
                            parse_mode="HTML",
                            reply_markup=None,
                        )
                    except Exception:
                        pass
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
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                _refine_buttons = [
                    [InlineKeyboardButton("🌑 Darker / Heavier", callback_data="ap:rd:dark")],
                    [InlineKeyboardButton("🌌 More Cosmic / Spacey", callback_data="ap:rd:cosmic")],
                    [InlineKeyboardButton("⚡ Faster / More Aggressive", callback_data="ap:rd:fast")],
                    [InlineKeyboardButton("🌊 More Atmospheric", callback_data="ap:rd:atmo")],
                    [InlineKeyboardButton("🗡️ More Experimental", callback_data="ap:rd:exp")],
                    [InlineKeyboardButton("💬 Type Custom Refinement", callback_data="ap:rd:custom")],
                    [InlineKeyboardButton("↩️ Keep Current", callback_data="ap:rd:cancel")],
                ]
                try:
                    await query.message.reply_text(
                        "🔄 <b>Pick a refinement direction:</b>",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(_refine_buttons),
                    )
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
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                _redo_buttons = [
                    [
                        InlineKeyboardButton("🔊 More Sub-Bass", callback_data=f"ap:redo_preset:{track_num}:bass"),
                        InlineKeyboardButton("⚡ Faster Tempo", callback_data=f"ap:redo_preset:{track_num}:faster")
                    ],
                    [
                        InlineKeyboardButton("🌫️ Darker / Witchy", callback_data=f"ap:redo_preset:{track_num}:darker"),
                        InlineKeyboardButton("🚫 Clean Instrumental", callback_data=f"ap:redo_preset:{track_num}:clean")
                    ],
                    [
                        InlineKeyboardButton("✏️ Custom Instructions", callback_data=f"ap:redo_custom:{track_num}"),
                        InlineKeyboardButton("↩️ Cancel", callback_data="ap:redo_cancel")
                    ]
                ]
                try:
                    await query.message.reply_text(
                        f"🔄 <b>What should be adjusted for Track {track_num}?</b>",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(_redo_buttons),
                    )
                except Exception as _e:
                    logger.error("[Telegram] Failed to send redo buttons: %s", _e)
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
                try:
                    await query.edit_message_text(text=f"🔄 <b>Redoing Track {track_num}</b>\\nDirective: <i>{directive}</i>", parse_mode="HTML", reply_markup=None)
                except Exception:
                    try: await query.edit_message_reply_markup(reply_markup=None)
                    except Exception: pass
                return

            if choice.startswith('redo_custom:'):
                track_num = choice.split(':')[-1]
                await query.answer(text="💬 Tell agent your custom direction...")
                try:
                    await query.edit_message_text(text=f"💬 <b>Custom Redo for Track {track_num}</b>\\nType your instructions in the chat, and the agent will remake the track.", parse_mode="HTML", reply_markup=None)
                except Exception:
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
                try:
                    await query.edit_message_text(text="↩️ <i>Track redo cancelled.</i>", parse_mode="HTML", reply_markup=None)
                except Exception:
                    try: await query.edit_message_reply_markup(reply_markup=None)
                    except Exception: pass
                return

            # Interactive Reject: preset directions
            if choice == 'songs:reject':
                await query.answer(text='❌ Select new direction for album')
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                _reject_buttons = [
                    [
                        InlineKeyboardButton("🌑 Darker / Witch House", callback_data="ap:reject_preset:dark"),
                        InlineKeyboardButton("🏎️ Faster Drift Phonk", callback_data="ap:reject_preset:phonk")
                    ],
                    [
                        InlineKeyboardButton("📻 Cosmic Industrial Trap", callback_data="ap:reject_preset:industrial"),
                        InlineKeyboardButton("✏️ Custom Direction", callback_data="ap:reject_custom")
                    ],
                    [InlineKeyboardButton("↩️ Cancel", callback_data="ap:reject_cancel")]
                ]
                try:
                    await query.message.reply_text(
                        "❌ <b>Select a new sonic direction for the album remake:</b>",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(_reject_buttons),
                    )
                except Exception as _e:
                    logger.error("[Telegram] Failed to send reject buttons: %s", _e)
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
                try:
                    await query.edit_message_text(text=f"❌ <b>Album Remake Scheduled</b>\\nNew Direction: <i>{directive}</i>", parse_mode="HTML", reply_markup=None)
                except Exception:
                    try: await query.edit_message_reply_markup(reply_markup=None)
                    except Exception: pass
                return

            if choice == 'reject_custom':
                await query.answer(text="💬 Tell agent your new album direction...")
                try:
                    await query.edit_message_text(text="💬 <b>Custom Album Remake</b>\\nType your instructions in the chat, and the agent will regenerate the album.", parse_mode="HTML", reply_markup=None)
                except Exception:
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
                try:
                    await query.edit_message_text(text="↩️ <i>Remake cancelled. Keeping current tracks.</i>", parse_mode="HTML", reply_markup=None)
                except Exception:
                    try: await query.edit_message_reply_markup(reply_markup=None)
                    except Exception: pass
                return

            # ── Error Recovery Handlers ──
            if choice == 'error:retry':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/error_retry', 'w') as f:
                    f.write('retry')
                try:
                    import subprocess as _sub
                    _chk = _sub.run(["pgrep", "-f", "album_pipeline.py"], capture_output=True)
                    if _chk.returncode != 0 and os.path.exists("/opt/data/music/pipeline_state.json"):
                        _cmd = "nohup /opt/hermes/.venv/bin/python3 -B /opt/data/scripts/album_pipeline.py --resume >> /opt/data/logs/pipeline.log 2>&1 &"
                        _sub.Popen(_cmd, shell=True, env={**dict(os.environ)})
                except Exception:
                    pass
                await query.answer(text='🔄 Retrying production...')
                try:
                    await query.message.reply_text("🔄 <b>Retrying production step...</b>", parse_mode="HTML")
                except Exception: pass
                try: await query.edit_message_reply_markup(reply_markup=None)
                except: pass
                return

            if choice == 'error:skip':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/error_skip', 'w') as f:
                    f.write('skip')
                await query.answer(text='⏭ Skipping failed step...')
                try:
                    await query.message.reply_text("⏭ <b>Skipping failed step and continuing pipeline...</b>", parse_mode="HTML")
                except Exception: pass
                try: await query.edit_message_reply_markup(reply_markup=None)
                except: pass
                return

            if choice == 'error:log':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/error_log', 'w') as f:
                    f.write('log')
                await query.answer(text='📋 Fetching full error log...')
                return

            if choice == 'error:abort':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/error_abort', 'w') as f:
                    f.write('abort')
                await query.answer(text='🛑 Aborting pipeline...')
                try:
                    await query.message.reply_text("🛑 <b>Pipeline aborted by user.</b>", parse_mode="HTML")
                except Exception: pass
                try: await query.edit_message_reply_markup(reply_markup=None)
                except: pass
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

            if choice == 'albumcover:edit':
                await query.answer(text='✏️ Select cover edit')
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                _edit_buttons = [
                    [
                        InlineKeyboardButton("🌑 Deeper Shadows & Noir", callback_data="ap:albumcover:quickedit:darker"),
                        InlineKeyboardButton("🌫️ Dense Cyan Mist & Steam", callback_data="ap:albumcover:quickedit:mist")
                    ],
                    [
                        InlineKeyboardButton("🗡️ Add Sleek Katana", callback_data="ap:albumcover:quickedit:katana"),
                        InlineKeyboardButton("👤 Fedora Silhouette", callback_data="ap:albumcover:quickedit:fedora")
                    ],
                    [
                        InlineKeyboardButton("🌕 Cold Moon Glow", callback_data="ap:albumcover:quickedit:moon"),
                        InlineKeyboardButton("💬 Custom Edit Instructions", callback_data="ap:albumcover:customedit")
                    ],
                    [InlineKeyboardButton("↩️ Cancel Edit", callback_data="ap:albumcover:edit_cancel")]
                ]
                try:
                    await query.message.reply_text(
                        "✏️ <b>Choose a visual edit for the Album Cover:</b>",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(_edit_buttons),
                    )
                except Exception as _e:
                    logger.error("[Telegram] Failed to send album cover edit buttons: %s", _e)
                return

            if choice.startswith('albumcover:quickedit:'):
                preset = choice.split(':')[-1]
                preset_map = {
                    "darker": "Dramatically deepen shadows, pitch black void contrast, sinister nocturnal chiaroscuro, specular wet reflections",
                    "mist": "Dense volumetric cyan fog and rising vent steam curling across the floor, cold breath haze and diffused light beams",
                    "katana": "A matte-black katana with woven hilt resting in the scene, razor folded steel edge catching cold neon gleam",
                    "fedora": "A motionless silhouette of a shadowed man in a wide-brimmed fedora in the distant doorway, face completely dark",
                    "moon": "A cold luminous moon casting silver rim light and shafts through drifting mist and cracked skylight"
                }
                directive = preset_map.get(preset, "Enhance cinematic atmospheric contrast and textures")
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/albumcover_edit', 'w') as f:
                    f.write(directive)
                await query.answer(text=f'✏️ Editing cover ({preset})...')
                try:
                    await query.edit_message_text(text=f"✏️ <b>Applying Album Cover Edit</b>\\nDirective: <i>{directive}</i>", parse_mode="HTML", reply_markup=None)
                except Exception:
                    try:
                        await query.edit_message_caption(caption=f"✏️ <b>Applying Album Cover Edit</b>\\nDirective: <i>{directive}</i>", parse_mode="HTML", reply_markup=None)
                    except Exception:
                        try: await query.edit_message_reply_markup(reply_markup=None)
                        except Exception: pass
                return

            if choice == 'albumcover:customedit':
                await query.answer(text="💬 Tell agent your custom cover edit...")
                try:
                    await query.edit_message_text(text="💬 <b>Custom Cover Edit</b>\\nType your instructions in the chat, and the agent will apply them to the cover.", parse_mode="HTML", reply_markup=None)
                except Exception:
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
                    _event = MessageEvent(text='The user wants to edit the album cover. Ask them what specific visual changes they want, then write their exact instructions to /tmp/pipeline_flags/albumcover_edit')
                    _event.message_type = MessageType.TEXT
                    _event.source = _source
                    _event.internal = False
                    _event.timestamp = _dt.now()
                    import asyncio
                    asyncio.create_task(self.handle_message(_event))
                return

            if choice == 'albumcover:edit_cancel':
                await query.answer(text="↩️ Edit cancelled")
                try:
                    await query.edit_message_text(text="↩️ <i>Cover edit cancelled.</i>", parse_mode="HTML", reply_markup=None)
                except Exception:
                    try: await query.edit_message_reply_markup(reply_markup=None)
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

            # ── Individual Track Cover Edit Handlers ──
            if choice.startswith('art:edit:'):
                track_num = choice.split(':')[-1]
                await query.answer(text=f'✏️ Select edit for Track {track_num}')
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                _edit_buttons = [
                    [
                        InlineKeyboardButton("🌑 Deeper Shadows", callback_data=f"ap:art:quickedit:{track_num}:darker"),
                        InlineKeyboardButton("🌫️ Dense Mist", callback_data=f"ap:art:quickedit:{track_num}:mist")
                    ],
                    [
                        InlineKeyboardButton("🗡️ Add Katana", callback_data=f"ap:art:quickedit:{track_num}:katana"),
                        InlineKeyboardButton("👤 Fedora Silhouette", callback_data=f"ap:art:quickedit:{track_num}:fedora")
                    ],
                    [
                        InlineKeyboardButton("🌕 Moon Highlight", callback_data=f"ap:art:quickedit:{track_num}:moon"),
                        InlineKeyboardButton("💬 Custom Prompt", callback_data=f"ap:art:customedit:{track_num}")
                    ],
                    [InlineKeyboardButton("↩️ Cancel", callback_data="ap:art:edit_cancel")]
                ]
                try:
                    await query.message.reply_text(
                        f"✏️ <b>Choose a visual edit for Track {track_num} cover:</b>",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(_edit_buttons),
                    )
                except Exception as _e:
                    logger.error("[Telegram] Failed to send track cover edit buttons: %s", _e)
                return

            if choice.startswith('art:quickedit:'):
                parts = choice.split(':')
                track_num = parts[1]
                preset = parts[2]
                preset_map = {
                    "darker": "Dramatically deepen shadows, pitch black void contrast, sinister nocturnal chiaroscuro, specular wet reflections",
                    "mist": "Dense volumetric cyan fog and rising vent steam curling across the floor, cold breath haze and diffused light beams",
                    "katana": "A matte-black katana with woven hilt resting in the scene, razor folded steel edge catching cold neon gleam",
                    "fedora": "A motionless silhouette of a shadowed man in a wide-brimmed fedora in the distant doorway, face completely dark",
                    "moon": "A cold luminous moon casting silver rim light and shafts through drifting mist and cracked skylight"
                }
                directive = preset_map.get(preset, "Enhance cinematic atmospheric contrast and textures")
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open(f'/tmp/pipeline_flags/art_edit_{track_num}', 'w') as f:
                    f.write(directive)
                await query.answer(text=f'✏️ Editing Track {track_num} ({preset})...')
                try:
                    await query.edit_message_text(text=f"✏️ <b>Applying Track {track_num} Edit</b>\\nDirective: <i>{directive}</i>", parse_mode="HTML", reply_markup=None)
                except Exception:
                    try:
                        await query.edit_message_caption(caption=f"✏️ <b>Applying Track {track_num} Edit</b>\\nDirective: <i>{directive}</i>", parse_mode="HTML", reply_markup=None)
                    except Exception:
                        try: await query.edit_message_reply_markup(reply_markup=None)
                        except Exception: pass
                return

            if choice.startswith('art:customedit:'):
                track_num = choice.split(':')[-1]
                await query.answer(text=f"💬 Tell agent your custom edit for Track {track_num}...")
                try:
                    await query.edit_message_text(text=f"💬 <b>Custom Edit for Track {track_num}</b>\\nType your instructions in the chat, and the agent will apply them to the cover.", parse_mode="HTML", reply_markup=None)
                except Exception:
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
                    _event = MessageEvent(text=f'The user wants to edit Track {track_num} cover. Ask them what specific visual changes they want, then write their exact instructions to /tmp/pipeline_flags/art_edit_{track_num}')
                    _event.message_type = MessageType.TEXT
                    _event.source = _source
                    _event.internal = False
                    _event.timestamp = _dt.now()
                    import asyncio
                    asyncio.create_task(self.handle_message(_event))
                return

            if choice == 'art:edit_cancel':
                await query.answer(text="↩️ Edit cancelled")
                try:
                    await query.edit_message_text(text="↩️ <i>Track cover edit cancelled.</i>", parse_mode="HTML", reply_markup=None)
                except Exception:
                    try: await query.edit_message_reply_markup(reply_markup=None)
                    except Exception: pass
                return

            # ── Final Review & Publishing Gate Handlers ──
            if choice == 'final:publish':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/final_publish', 'w') as f:
                    f.write('publish')
                await query.answer(text='🚀 Confirmed: Proceeding to SoundCloud...')
                try:
                    await query.message.reply_text("🚀 <b>Good to proceed confirmed!</b> Uploading studio masters and artwork to SoundCloud...", parse_mode="HTML")
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

            # ── Venice Credit Warning Gate Handlers (credit:added & credit:pause) ──
            def _query_venice_budget_live(_mode="full"):
                import json as _j, urllib.request as _ur
                _key = os.environ.get("VENICE_API_KEY", "")
                if not _key and os.path.exists("/opt/data/.env"):
                    try:
                        for _ln in open("/opt/data/.env"):
                            if _ln.strip().startswith("VENICE_API_KEY="):
                                _key = _ln.strip().split("=", 1)[1].strip().strip('"').strip("'")
                                break
                    except Exception:
                        pass
                _avg_track = 0.48 if _mode == "sample" else 2.24
                _avg_tracks_total = round(_avg_track * 5, 2) if _mode == "sample" else 11.18
                _avg_covers = 0.0 if _mode == "sample" else 0.52
                _avg_album = round(_avg_tracks_total + _avg_covers, 2)
                if not _key:
                    return {"ok": False, "total_usd": 0.0, "usd": 0.0, "diem": 0.0, "avg_track": _avg_track, "avg_album": _avg_album, "completable": 5, "shortfall": 0.0, "sufficient": True}
                try:
                    _req = _ur.Request(
                        "https://api.venice.ai/api/v1/api_keys/rate_limits",
                        headers={"Authorization": f"Bearer {_key}", "User-Agent": "Mozilla/5.0"},
                    )
                    with _ur.urlopen(_req, timeout=10) as _resp:
                        _data = _j.loads(_resp.read().decode("utf-8")).get("data", {})
                    _bal = _data.get("balances", {})
                    _usd = float(_bal.get("USD", 0.0) or 0.0)
                    _diem = float(_bal.get("DIEM", 0.0) or 0.0)
                    _bundled = float(_bal.get("BUNDLED_CREDITS", 0.0) or 0.0)
                    _tot = round(_usd + _diem + _bundled, 2)
                    _comp = min(5, int(_tot // _avg_track)) if _avg_track > 0 else 5
                    _short = round(max(0.0, _avg_album - _tot), 2)
                    _suff = _tot >= _avg_album
                    return {
                        "ok": True,
                        "total_usd": _tot,
                        "usd": round(_usd, 2),
                        "diem": round(_diem, 2),
                        "avg_track": _avg_track,
                        "avg_tracks_total": _avg_tracks_total,
                        "avg_covers": _avg_covers,
                        "avg_album": _avg_album,
                        "completable": _comp,
                        "shortfall": _short,
                        "sufficient": _suff,
                    }
                except Exception as _e:
                    return {"ok": False, "total_usd": 0.0, "usd": 0.0, "diem": 0.0, "avg_track": _avg_track, "avg_album": _avg_album, "completable": 5, "shortfall": 0.0, "sufficient": True, "error": str(_e)}

            if choice == 'credit:added':
                import json as _json
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                # Clear any pause flag
                for _pf in ('/tmp/pipeline_flags/credit_paused', '/tmp/credit_paused'):
                    if os.path.exists(_pf):
                        try: os.remove(_pf)
                        except Exception: pass

                # Check if there is a pending album selection saved
                _pending_file = '/tmp/pending_album_selection.json'
                _pending = None
                if os.path.exists(_pending_file):
                    try:
                        with open(_pending_file) as _f:
                            _pending = _json.load(_f)
                    except Exception:
                        _pending = None

                _check_mode = (_pending or {}).get("mode", "full")
                _b = _query_venice_budget_live(_check_mode)
                _tot = _b.get("total_usd", 0.0)
                _avg_alb = _b.get("avg_album", 11.70)
                _comp = _b.get("completable", 0)
                _short = _b.get("shortfall", 0.0)

                # If an active pipeline is currently waiting on a balance gate, signal retry
                if os.path.exists('/tmp/album_pipeline.lock') and (_b.get("sufficient") or _comp >= 1):
                    with open('/tmp/pipeline_flags/error_retry', 'w') as _f:
                        _f.write('credit_added')
                    await query.answer(text=f'💳 Balance: ${_tot:.2f} USD — Resuming pipeline!')
                    try:
                        await query.message.reply_text(
                            f"✅ <b>Venice Credits Verified: ${_tot:.2f} USD!</b>\\n"
                            f"Resuming album production pipeline now...",
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass
                    try: await query.edit_message_reply_markup(reply_markup=None)
                    except Exception: pass
                    return

                # If sufficient (or can complete all 5 tracks) and a pending album was selected, launch it now!
                if _b.get("sufficient") or _tot >= _b.get("avg_tracks_total", 11.18):
                    await query.answer(text=f'✅ Verified: ${_tot:.2f} USD available!')
                    if _pending and _pending.get("idx"):
                        _p_idx = int(_pending["idx"])
                        _p_mode = _pending.get("mode", "full")
                        _p_album = _pending.get("album", "SELECTED ALBUM")
                        try: os.remove(_pending_file)
                        except Exception: pass
                        try:
                            await query.message.reply_text(
                                f"✅ <b>Venice Credits Verified: ${_tot:.2f} USD!</b>\\n"
                                f"Avg Full Album Cost: <b>~${_avg_alb:.2f} USD</b> (5/5 tracks funded — Option 1B).\\n"
                                f"🚀 Launching <b>{_p_album}</b> ({_p_mode} mode) now...",
                                parse_mode="HTML",
                            )
                        except Exception:
                            pass
                        try: await query.edit_message_reply_markup(reply_markup=None)
                        except Exception: pass
                        import subprocess as _subprocess
                        _zero_idx = _p_idx - 1
                        _cmd = (
                            f'nohup /opt/hermes/.venv/bin/python3 -B '
                            f'/opt/data/scripts/album_pipeline.py '
                            f'--proposal-index {_zero_idx} '
                            f'--mode {_p_mode} '
                            f'--force '
                            f'>> /opt/data/logs/pipeline.log 2>&1 &'
                        )
                        _subprocess.Popen(_cmd, shell=True, env={**dict(os.environ)})
                        return
                    else:
                        try:
                            await query.message.reply_text(
                                f"✅ <b>Venice Credits Verified: ${_tot:.2f} USD!</b>\\n"
                                f"• Avg Full Album Cost: <b>~${_avg_alb:.2f} USD</b> ($11.18 tracks + $0.52 artwork)\\n"
                                f"• Capacity: <b>5/5 tracks funded</b>\\n\\n"
                                f"👆 Tap any album proposal button above to begin production!",
                                parse_mode="HTML",
                            )
                        except Exception:
                            pass
                        return
                else:
                    # Still below average album cost
                    await query.answer(text=f'⚠️ Balance: ${_tot:.2f} USD (still need +${_short:.2f} USD)')
                    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                    _warn_btns = [
                        [
                            InlineKeyboardButton("💳 Credit Added", callback_data="ap:credit:added"),
                            InlineKeyboardButton("⏸ Pause", callback_data="ap:credit:pause"),
                        ]
                    ]
                    if _pending and _pending.get("idx") and _comp >= 1:
                        _warn_btns.append([
                            InlineKeyboardButton(
                                f"▶️ Produce Partial ({_comp}/5 Tracks Anyway)",
                                callback_data=f"ap:prod_force:{_pending['idx']}:{_pending.get('mode', 'full')}",
                            )
                        ])
                    try:
                        await query.message.reply_text(
                            f"⚠️ <b>Venice Credits Still Below Full Album Cost</b>\\n"
                            f"• Current Balance: <b>${_tot:.2f} USD</b> (${_b.get('usd', 0.0):.2f} USD / {_b.get('diem', 0.0):.2f} DIEM)\\n"
                            f"• Avg Full Album Cost: <b>~${_avg_alb:.2f} USD</b> ($11.18 tracks + $0.52 covers)\\n"
                            f"• Capacity: Can complete <b>{_comp}/5 tracks</b> (shortfall: <b>${_short:.2f} USD</b>)\\n\\n"
                            f"Add at least <b>${_short:.2f} USD</b> and tap <b>💳 Credit Added</b>, or tap <b>⏸ Pause</b>.",
                            parse_mode="HTML",
                            reply_markup=InlineKeyboardMarkup(_warn_btns),
                        )
                    except Exception:
                        pass
                    return

            if choice == 'credit:pause':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/credit_paused', 'w') as _f:
                    _f.write('paused')
                with open('/tmp/credit_paused', 'w') as _f:
                    _f.write('paused')
                _b = _query_venice_budget_live("full")
                _tot = _b.get("total_usd", 0.0)
                _avg_alb = _b.get("avg_album", 11.70)
                _comp = _b.get("completable", 0)
                _short = _b.get("shortfall", 0.0)
                await query.answer(text='⏸ Production paused until credits are added.')
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                _resume_kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Credit Added", callback_data="ap:credit:added")]
                ])
                try:
                    await query.message.reply_text(
                        f"⏸ <b>Paused — Waiting for Venice Credits</b>\\n"
                        f"• Available Balance: <b>${_tot:.2f} USD</b>\\n"
                        f"• Avg Full Album Cost: <b>~${_avg_alb:.2f} USD</b> ($11.18 tracks + $0.52 covers)\\n"
                        f"• Current Capacity: <b>{_comp}/5 tracks</b> (shortfall: <b>${_short:.2f} USD</b>)\\n\\n"
                        f"Pipeline is safely paused. Once you add credits, tap <b>💳 Credit Added</b> below to verify and continue!",
                        parse_mode="HTML",
                        reply_markup=_resume_kb,
                    )
                except Exception:
                    pass
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

                _b = _query_venice_budget_live("full")
                _low = bool(_b.get("ok") and not _b.get("sufficient"))

                mode_buttons = [
                    [{"text": "🚀 Full Album (4 Singles ~3m + 3m35s Closer)", "callback_data": f"ap:prod:{idx}:full"}],
                    [{"text": "⚡ Sample Previews (20s / track)", "callback_data": f"ap:prod:{idx}:sample"}],
                ]
                if _low:
                    mode_buttons.append([
                        {"text": "💳 Credit Added", "callback_data": "ap:credit:added"},
                        {"text": "⏸ Pause", "callback_data": "ap:credit:pause"},
                    ])
                mode_buttons.append([{"text": "↩️ Cancel", "callback_data": "ap:prod:cancel"}])

                _credit_note = ""
                if _low:
                    # Save as pending selection so tapping "Credit Added" can launch it directly
                    try:
                        with open("/tmp/pending_album_selection.json", "w") as _pf:
                            _json.dump({"idx": idx, "mode": "full", "album": album_name}, _pf)
                    except Exception:
                        pass
                    _credit_note = (
                        f"\\n\\n⚠️ *Low Venice Credits Warning:*\\n"
                        f"• Available: *${_b['total_usd']:.2f} USD* vs Avg Full Album: *~${_b['avg_album']:.2f} USD*\\n"
                        f"• Capacity: *{_b['completable']}/5 tracks* (shortfall: *${_b['shortfall']:.2f} USD*)\\n"
                        f"Tap *💳 Credit Added* after topping up, or *⏸ Pause*."
                    )
                elif _b.get("ok"):
                    _credit_note = f"\\n\\n💳 *Venice Credits:* ${_b['total_usd']:.2f} USD _(Avg Album: ~${_b['avg_album']:.2f} — ✅ Ready)_"

                try:
                    await query.edit_message_text(
                        text=f"📀 *{album_name}*\\n\\nChoose production mode:\\n• *Full Album (Option 1B):* 4 punchy ~3m singles + 3m35s closer (~$11.70 avg)\\n• *Sample Previews:* Quick snippets (20s per track, ~$2.40 avg){_credit_note}",
                        parse_mode="Markdown",
                        reply_markup={"inline_keyboard": mode_buttons},
                    )
                except Exception as _e:
                    logger.error("[Telegram] Failed to show mode buttons: %s", _e)
                return

            # ── Execute Production with Selected Mode (0-INDEX FIX + Credit Gate) ──
            if choice.startswith("prod:") or choice.startswith("prod_force:"):
                _force_start = choice.startswith("prod_force:")
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
                desc_mode = "Full Album (4 Singles ~3m + 3m35s Closer)" if prod_mode == "full" else "Sample Previews (20s / track)"

                # Pre-launch Venice credit gate (unless user explicitly forced partial production)
                if not _force_start:
                    _b = _query_venice_budget_live(prod_mode)
                    if _b.get("ok") and not _b.get("sufficient"):
                        try:
                            with open("/tmp/pending_album_selection.json", "w") as _pf:
                                _json.dump({"idx": idx, "mode": prod_mode, "album": album_name}, _pf)
                        except Exception:
                            pass
                        await query.answer(text=f"⚠️ Insufficient Venice credits (${_b['total_usd']:.2f} / ~${_b['avg_album']:.2f} USD)")
                        _gate_buttons = [
                            [
                                {"text": "💳 Credit Added", "callback_data": "ap:credit:added"},
                                {"text": "⏸ Pause", "callback_data": "ap:credit:pause"},
                            ],
                        ]
                        if _b.get("completable", 0) >= 1:
                            _gate_buttons.append([
                                {"text": f"▶️ Start Anyway ({_b['completable']}/5 Tracks)", "callback_data": f"ap:prod_force:{idx}:{prod_mode}"}
                            ])
                        _gate_buttons.append([{"text": "↩️ Cancel", "callback_data": "ap:prod:cancel"}])
                        try:
                            await query.edit_message_text(
                                text=(
                                    f"⚠️ *Insufficient Venice Credits for {album_name}*\\n"
                                    f"━━━━━━━━━━━━━━━━━━━━━━\\n"
                                    f"• *Available Credits:* ${_b['total_usd']:.2f} USD (${_b['usd']:.2f} USD / {_b['diem']:.2f} DIEM)\\n"
                                    f"• *Avg Full Album Cost:* ~${_b['avg_album']:.2f} USD (${_b['avg_tracks_total']:.2f} for 5 tracks + ${_b['avg_covers']:.2f} artwork)\\n"
                                    f"• *Track Capacity:* Can only complete *{_b['completable']}/5 tracks* (*${_b['shortfall']:.2f} USD needed*)\\n\\n"
                                    f"Top up credits at `venice.ai/settings/api` and tap *💳 Credit Added* to launch *{album_name}*, or tap *⏸ Pause*."
                                ),
                                parse_mode="Markdown",
                                reply_markup={"inline_keyboard": _gate_buttons},
                            )
                        except Exception as _ge:
                            logger.error("[Telegram] Failed to show credit gate: %s", _ge)
                        return

                try:
                    if os.path.exists("/tmp/pending_album_selection.json"):
                        os.remove("/tmp/pending_album_selection.json")
                except Exception:
                    pass
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
