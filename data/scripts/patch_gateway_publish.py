import sys
import os

GATEWAY_FILE = "/opt/hermes/gateway/platforms/telegram.py"
PATCH_MARKER_PUB = "# --- Publish callbacks (pub:) ---"

PATCH_CODE_PUB = r'''
        # --- Publish callbacks (pub:) ---
        if data.startswith("pub:"):
            parts = data.split(":")
            if len(parts) >= 3:
                release_name = parts[1]
                action = parts[2]
                
                if action == "cancel":
                    await query.answer(text="❌ Publishing cancelled.")
                    try:
                        await query.edit_message_reply_markup(reply_markup=None)
                    except Exception:
                        pass
                    try:
                        await query.message.reply_text(
                            f"❌ <b>Publishing cancelled for {release_name}.</b> Master audio files remain preserved locally.",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
                    return
                elif action == "preview":
                    await query.answer(text="👀 Sending preview audio...")
                    try:
                        await query.message.reply_text(
                            f"👀 <b>Sending preview audio for {release_name}...</b> Uploading track previews to chat.",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
                    import asyncio
                    async def do_preview():
                        proc = await asyncio.create_subprocess_exec(
                            "/opt/hermes/.venv/bin/python3", "/opt/data/skills/music/soundcloud/scripts/publish_release.py",
                            "--release", release_name, "--preview")
                        await proc.wait()
                    asyncio.create_task(do_preview())
                    return
                elif action == "edit":
                    await query.answer(text="✏️ Please tell the agent what to edit in chat.")
                    try:
                        await query.message.reply_text(
                            f"✏️ <b>Edit requested for {release_name}.</b> Reply in chat with any adjustments to metadata, track titles, or tags.",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
                    return
                elif action == "go":
                    await query.answer(text=f"🚀 Publishing {release_name} to SoundCloud!")
                    try:
                        await query.edit_message_reply_markup(reply_markup=None)
                    except Exception:
                        pass
                    try:
                        msg = (
                            f"🚀 <b>Publishing approved!</b> Studio FLAC masters for <b>{release_name}</b> are being uploaded to SoundCloud...\n"
                            "<i>Live progress updates will follow as each track is uploaded and transcoded.</i>"
                        )
                        await query.message.reply_text(msg, parse_mode="HTML")
                    except Exception:
                        pass
                    import asyncio
                    async def do_publish():
                        proc = await asyncio.create_subprocess_exec(
                            "/opt/hermes/.venv/bin/python3", "/opt/data/skills/music/soundcloud/scripts/publish_release.py",
                            "--release", release_name, "--confirm", "--force")
                        rc = await proc.wait()
                        if rc != 0:
                            try:
                                await query.message.reply_text(
                                    f"❌ <b>Publishing failed</b> (Exit code {rc}). Check server logs for details.",
                                    parse_mode="HTML"
                                )
                            except Exception:
                                pass
                    asyncio.create_task(do_publish())
                    return
            await query.answer(text="Unknown action")
            return
'''

def patch():
    if not os.path.exists(GATEWAY_FILE):
        return False
    with open(GATEWAY_FILE, "r") as f:
        content = f.read()

    if PATCH_MARKER_PUB in content:
        print("[patch] Removing existing pub: handler to apply latest version...")
        start = content.find(PATCH_MARKER_PUB)
        end_marker = "        # --- Update prompt callbacks ---"
        end = content.find(end_marker, start)
        if end > start:
            content = content[:start] + content[end:]
        else:
            print("[patch] Could not cleanly find end marker for existing patch")

    target = "        # --- Update prompt callbacks ---"
    if target not in content:
        print(f"[patch] Target not found: {target}")
        return False

    patched = content.replace(target, PATCH_CODE_PUB + "\n" + target, 1)

    with open(GATEWAY_FILE, "w") as f:
        f.write(patched)
    print("[patch] ✅ applied safely with immediate chat confirmations")
    return True

if __name__ == "__main__":
    sys.exit(0 if patch() else 1)
