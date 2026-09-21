import os
import sys

GATEWAY_FILE = "/opt/hermes/gateway/platforms/telegram.py"

PIPELINE_HANDLERS = """
            # --- Pipeline Phase Handlers ---
            if choice.startswith("songs:") or choice.startswith("art:") or choice.startswith("final:") or choice.startswith("master:"):
                import os as _os
                _flags_dir = "/tmp/pipeline_flags"
                _os.makedirs(_flags_dir, exist_ok=True)
                
                # Convert 'songs:approve' to 'songs_approved' flag etc.
                _action = choice.replace(":", "_")
                if choice == "songs:approve": _action = "songs_approved"
                if choice == "songs:flac": _action = "songs_flac_requested"
                if choice == "songs:reject": _action = "songs_rejected"
                if choice == "art:approve": _action = "art_approved"
                if choice == "master:approve": _action = "master_approved"
                if choice == "master:wait": _action = "master_wait"
                
                with open(_os.path.join(_flags_dir, _action), "w") as _f:
                    _f.write("trigger")
                
                await query.answer(text="✅ Acknowledged")
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except Exception:
                    pass
                return
"""

def patch():
    if not os.path.exists(GATEWAY_FILE):
        print("Gateway file not found.")
        return
        
    with open(GATEWAY_FILE, "r") as f:
        content = f.read()
        
    if "# --- Pipeline Phase Handlers ---" in content:
        print("Pipeline handlers already patched.")
        return
        
    # Inject right after "if data.startswith('ap:'):" and "choice = data.split(':', 1)[1]"
    target = "            choice = data.split(\":\", 1)[1]"
    
    if target not in content:
        print("Target injection point not found.")
        return
        
    content = content.replace(target, target + "\n" + PIPELINE_HANDLERS)
    
    with open(GATEWAY_FILE, "w") as f:
        f.write(content)
        
    print("Gateway patched with pipeline handlers.")
    
if __name__ == "__main__":
    patch()
