import sys
import os

GATEWAY_FILE = "/opt/hermes/gateway/platforms/telegram.py"
PATCH_MARKER_PUB = "# --- Publish callbacks (pub:) ---"

PATCH_CODE_PUB = '''
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
                    return
                elif action == "preview":
                    await query.answer(text="👀 Sending preview audio...")
                    import asyncio
                    async def do_preview():
                        proc = await asyncio.create_subprocess_exec(
                            "python3", "/opt/data/skills/music/soundcloud/scripts/publish_release.py",
                            "--release", release_name, "--preview")
                        await proc.wait()
                    asyncio.create_task(do_preview())
                    return
                elif action == "edit":
                    await query.answer(text="✏️ Please tell the agent what to edit in chat.")
                    return
                elif action == "go":
                    await query.answer(text=f"🚀 Publishing {release_name} to SoundCloud!")
                    try:
                        await query.edit_message_reply_markup(reply_markup=None)
                    except Exception:
                        pass
                    import asyncio
                    async def do_publish():
                        proc = await asyncio.create_subprocess_exec(
                            "python3", "/opt/data/skills/music/soundcloud/scripts/publish_release.py",
                            "--release", release_name, "--confirm")
                        await proc.wait()
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
        print("[patch] already patched")
        return True

    target = "        # --- Update prompt callbacks ---"
    if target not in content:
        return False

    patched = content.replace(target, PATCH_CODE_PUB + "\n" + target)

    with open(GATEWAY_FILE, "w") as f:
        f.write(patched)
    print("[patch] ✅ applied safely")
    return True

if __name__ == "__main__":
    sys.exit(0 if patch() else 1)
