#!/usr/bin/env python3
import liblo
import time
import sys
import json

class ArdourOSCClient:
    def __init__(self, port=3819):
        try:
            self.target = liblo.Address(port)
        except liblo.AddressError as err:
            sys.stderr.write(f"OSC address error: {err}\n")
            sys.exit(1)
            
        try:
            self.server = liblo.Server()
        except liblo.ServerError as err:
            sys.stderr.write(f"OSC server error: {err}\n")
            sys.exit(1)
            
        self.responses = []
        self.server.add_method(None, None, self._callback)
        
    def _callback(self, path, args, types, src):
        self.responses.append({"path": path, "args": args})
        
    def send(self, path, *args):
        liblo.send(self.target, path, *args)
        
    def wait_for_response(self, timeout=1.0):
        start = time.time()
        while time.time() - start < timeout:
            self.server.recv(10)
            if self.responses:
                res = self.responses.copy()
                self.responses.clear()
                return res
        return []

    def transport_play(self):
        self.send("/transport_play")

    def transport_stop(self):
        self.send("/transport_stop")

    def locate(self, sample_pos):
        self.send("/locate", sample_pos)
        
    def record_enable(self):
        self.send("/rec_enable_toggle")
        
    def set_fader(self, strip_id, value):
        # value 0.0 to 1.0
        self.send(f"/strip/fader", strip_id, float(value))
        
    def set_pan(self, strip_id, value):
        # value 0.0 (left) to 1.0 (right)
        self.send(f"/strip/pan_stereo_position", strip_id, float(value))
        
    def set_mute(self, strip_id, state):
        self.send(f"/strip/mute", strip_id, 1 if state else 0)
        
    def set_solo(self, strip_id, state):
        self.send(f"/strip/solo", strip_id, 1 if state else 0)

    def select_strip(self, strip_id):
        self.send("/strip/select", strip_id, 1)

    def set_plugin_param(self, strip_id, plugin_id, param_id, value):
        self.send(f"/strip/plugin/parameter", strip_id, plugin_id, param_id, float(value))

    def get_strip_name(self, strip_id):
        self.send("/strip/name", strip_id)
        res = self.wait_for_response(0.5)
        for r in res:
            if r['path'].endswith('/name'):
                return r['args'][0]
        return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"success": False, "error": "Missing command"}))
        sys.exit(1)
        
    cmd = sys.argv[1]
    client = ArdourOSCClient()
    
    try:
        if cmd == "play":
            client.transport_play()
        elif cmd == "stop":
            client.transport_stop()
        elif cmd == "locate":
            client.locate(int(sys.argv[2]))
        elif cmd == "fader":
            client.set_fader(int(sys.argv[2]), float(sys.argv[3]))
        elif cmd == "pan":
            client.set_pan(int(sys.argv[2]), float(sys.argv[3]))
        elif cmd == "mute":
            client.set_mute(int(sys.argv[2]), sys.argv[3].lower() == 'true')
        else:
            print(json.dumps({"success": False, "error": f"Unknown command {cmd}"}))
            sys.exit(1)
            
        print(json.dumps({"success": True, "command": cmd}))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))
