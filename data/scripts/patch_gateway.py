"""
patch_gateway.py — Patches the Telegram gateway to handle ap: (album proposal) callbacks.

Handles:
  ap:1 .. ap:5     — Select album for production
  ap:skip          — Skip all proposals
  ap:love:N        — Record a positive taste preference
  ap:hate:N        — Record a negative taste preference
  ap:refine        — Ask user for refinement text, then re-propose
"""

import sys
import os

GATEWAY_FILE = "/opt/hermes/gateway/platforms/telegram.py"

PATCH_MARKER = "# --- Album proposal callbacks (ap:N) ---"

PATCH_CODE = '''
        # --- Album proposal callbacks (ap:N) ---
        if data.startswith("ap:"):
            choice = data.split(":", 1)[1]

            # ── Skip All ──
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

                    # Import taste functions
                    import importlib.util
                    _spec = importlib.util.spec_from_file_location("propose", "/opt/data/scripts/propose_albums.py")
                    _mod = importlib.util.module_from_spec(_spec)
                    _spec.loader.exec_module(_mod)
                    _mod.record_skip_all(_proposals)
                except Exception:
                    pass  # non-fatal

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

                # Send direction buttons as a NEW message (editing the proposals message is unreliable)
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
                        _req = _urllib.Request(
                            f"https://api.telegram.org/bot{_bot_token}/sendMessage",
                            data=_payload,
                            headers={"Content-Type": "application/json"},
                        )
                        _urllib.urlopen(_req, timeout=10)
                    except Exception as _e:
                        logger.error("[Telegram] Failed to send refine buttons: %s", _e)
                return

            # ── Refine Direction (preset or custom) ──
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
                    try:
                        await query.edit_message_reply_markup(reply_markup=None)
                    except Exception:
                        pass
                    return

                if _code == "custom":
                    await query.answer(text="💬 Type your refinement...")
                    # Remove buttons and inject a synthetic message telling agent to ask for refinement
                    try:
                        await query.edit_message_reply_markup(reply_markup=None)
                    except Exception:
                        pass

                    # Inject synthetic message to agent
                    from gateway.session import SessionSource
                    from gateway.platforms.base import MessageEvent, MessageType
                    from datetime import datetime as _dt

                    _chat_id = str(query.message.chat_id) if query.message else None
                    _user_id = str(query.from_user.id) if query.from_user else None
                    _user_name = getattr(query.from_user, "first_name", "User")

                    if _chat_id:
                        _source = SessionSource(
                            platform=self.platform,
                            chat_id=_chat_id,
                            chat_type="dm",
                            user_id=_user_id,
                            user_name=_user_name,
                        )
                        _event = MessageEvent(text='The user wants to refine the current album proposals. Ask them what direction they want, then run: python3 /opt/data/scripts/propose_albums.py --refine "<their direction>"')
                        _event.message_type = MessageType.TEXT
                        _event.source = _source
                        _event.internal = False
                        _event.timestamp = _dt.now()

                        import asyncio
                        asyncio.create_task(self.handle_message(_event))
                    return

                # Preset direction — run refine directly via subprocess
                await query.answer(text=f"🔄 Refining proposals...")
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except Exception:
                    pass

                # Run the refine script in background
                import subprocess as _subprocess
                _venv_python = "/opt/hermes/.venv/bin/python3"
                _script = "/opt/data/scripts/propose_albums.py"
                try:
                    _proc = _subprocess.Popen(
                        [_venv_python, _script, "--refine", _direction],
                        stdout=_subprocess.PIPE, stderr=_subprocess.PIPE,
                        env={**dict(os.environ)},
                    )
                    # Don't block the event loop — fire and forget
                    import asyncio

                    async def _wait_refine():
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(None, _proc.wait)

                    asyncio.create_task(_wait_refine())
                except Exception as _e:
                    import urllib.request as _urllib
                    _bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
                    _chat_id = str(query.message.chat_id) if query.message else ""
                    if _bot_token and _chat_id:
                        import json as _json2
                        _payload = _json2.dumps({"chat_id": _chat_id, "text": f"⚠️ Refine failed: {_e}", "parse_mode": "Markdown"}).encode()
                        try:
                            _req = _urllib.Request(f"https://api.telegram.org/bot{_bot_token}/sendMessage", data=_payload, headers={"Content-Type": "application/json"})
                            _urllib.urlopen(_req, timeout=10)
                        except Exception:
                            pass
                return

            # ── Song Review Handlers ──
            if choice == 'songs:approve':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/songs_approved', 'w') as f:
                    f.write('approved')
                await query.answer(text='✅ Songs approved!')
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except: pass
                return
            
            if choice == 'songs:flac':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/songs_flac_requested', 'w') as f:
                    f.write('requested')
                await query.answer(text='📥 Packaging FLACs...')
                return
            
            if choice.startswith('songs:redo:'):
                track_num = choice.split(':')[-1]
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open(f'/tmp/pipeline_flags/songs_redo_{track_num}', 'w') as f:
                    f.write('pending')
                await query.answer(text=f'🔄 What to change about track {track_num}?')
                return
            
            if choice == 'songs:reject':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/songs_rejected', 'w') as f:
                    f.write('pending')
                await query.answer(text='❌ What direction instead?')
                return

            # ── DAW Mastering Handlers ──
            if choice == 'daw:skip':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/daw_skipped', 'w') as f:
                    f.write('skipped')
                await query.answer(text='⏭ Skipping DAW mastering...')
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except: pass
                return

            if choice == 'daw:wait':
                await query.answer(text='⏳ Continuing to wait for DAWAGENT...')
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except: pass
                return

            if choice == 'master:approve':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/master_approved', 'w') as f:
                    f.write('approved')
                await query.answer(text='✅ Masters approved!')
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
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
                    await query.edit_message_reply_markup(reply_markup=None)
                except: pass
                return

            if choice == 'albumcover:regen':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/albumcover_regen', 'w') as f:
                    f.write('regen')
                await query.answer(text='🔄 Regenerating album cover...')
                return

            # ── Track Covers Review Handlers ──
            if choice == 'trackcovers:approve':
                os.makedirs('/tmp/pipeline_flags', exist_ok=True)
                with open('/tmp/pipeline_flags/trackcovers_approved', 'w') as f:
                    f.write('approved')
                await query.answer(text='✅ Track covers approved!')
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
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

            # ── Select N (produce album) ──
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
            album_slug = album_name.lower().replace(" ", "-")
            await query.answer(text=f"🚀 Producing: {album_name}")

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
                pass  # non-fatal

            # Mark as selected in proposals file
            try:
                from datetime import datetime as _sel_dt
                proposals_data["selected"] = album_name
                proposals_data["selected_slug"] = album_slug
                proposals_data["selected_at"] = _sel_dt.now().isoformat()
                proposals_data["selected_index"] = idx
                with open(proposals_path, "w") as _wf:
                    _json.dump(proposals_data, _wf, indent=2)
            except Exception:
                pass  # non-fatal

            # Edit message to show selection, remove buttons
            try:
                await query.edit_message_text(
                    text=f"✅ Selected: *{album_name}* — production starting\\.\\.\\.",
                    parse_mode="MarkdownV2",
                    reply_markup=None,
                )
            except Exception:
                pass

            import subprocess as _subprocess
            _venv_python = '/opt/hermes/.venv/bin/python3'
            _script = '/opt/data/scripts/album_pipeline.py'
            _proc = _subprocess.Popen(
                [_venv_python, _script, '--proposal-index', str(idx)],
                stdout=_subprocess.PIPE, stderr=_subprocess.PIPE,
                env={**dict(os.environ)},
            )
            import asyncio
            async def _wait_pipeline():
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, _proc.wait)
            asyncio.create_task(_wait_pipeline())

            return

'''

def patch():
    """Apply the ap: callback handler patch to telegram.py."""
    if not os.path.exists(GATEWAY_FILE):
        print(f"[patch] {GATEWAY_FILE} not found, skipping")
        return False

    with open(GATEWAY_FILE, "r") as f:
        content = f.read()

    # Remove old patch if present, then re-apply
    if PATCH_MARKER in content:
        # Find and remove old patch block
        start = content.find(PATCH_MARKER) - len("        ")  # account for indent
        # Find the next handler block or end of our patch
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

    # Inject our handler before update_prompt
    patched = content.replace(target, PATCH_CODE + "\n" + target)

    with open(GATEWAY_FILE, "w") as f:
        f.write(patched)

    print("[patch] ✅ ap: callback handler injected into telegram.py (with love/hate/refine)")
    return True


if __name__ == "__main__":
    sys.exit(0 if patch() else 1)
