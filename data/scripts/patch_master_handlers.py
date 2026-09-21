#!/usr/bin/env python3
"""Inject master:approve and master:wait handlers into the gateway."""
import os

GATEWAY_FILE = "/opt/hermes/gateway/platforms/telegram.py"

MASTER_HANDLERS = """
            # ── Master Review Handlers ──
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
                await query.answer(text='🔄 Waiting for re-export...')
                return
"""

def patch():
    if not os.path.exists(GATEWAY_FILE):
        print("Gateway file not found.")
        return False

    with open(GATEWAY_FILE, "r") as f:
        content = f.read()

    if "master:approve" in content:
        print("master: handlers already present.")
        return True

    # Inject before "# ── Select N (produce album) ──"
    target = "            # ── Select N (produce album) ──"
    if target not in content:
        print(f"Injection point not found: {target!r}")
        return False

    content = content.replace(target, MASTER_HANDLERS + "\n" + target)

    with open(GATEWAY_FILE, "w") as f:
        f.write(content)

    print("✅ Injected master:approve and master:wait handlers.")
    return True

if __name__ == "__main__":
    import sys
    sys.exit(0 if patch() else 1)
