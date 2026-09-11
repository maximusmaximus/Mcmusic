#!/usr/bin/env python3
import os
import xml.etree.ElementTree as ET
import uuid
import shutil

class SessionManager:
    def __init__(self, sessions_dir="/opt/dawagent/sessions"):
        self.sessions_dir = sessions_dir
        os.makedirs(self.sessions_dir, exist_ok=True)

    def _get_session_path(self, name):
        return os.path.join(self.sessions_dir, name, f"{name}.ardour")

    def create_session(self, name, sr=48000, bpm=120):
        # Creates a basic Ardour session XML structure
        session_dir = os.path.join(self.sessions_dir, name)
        if os.path.exists(session_dir):
            raise Exception(f"Session {name} already exists.")
        
        os.makedirs(session_dir)
        xml_path = os.path.join(session_dir, f"{name}.ardour")
        
        root = ET.Element("Session", {
            "version": "7001",
            "name": name,
            "sample-rate": str(sr),
            "id-counter": "100"
        })
        
        config = ET.SubElement(root, "Config")
        ET.SubElement(config, "Option", {"name": "tempo-beats-per-minute", "value": str(bpm)})
        
        routes = ET.SubElement(root, "Routes")
        # Master bus
        ET.SubElement(routes, "Route", {
            "id": "1",
            "name": "Master",
            "default-type": "audio",
            "flags": "MasterOut",
            "active": "yes",
            "phase-invert": "00"
        })
        
        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ", level=0)
        tree.write(xml_path, encoding="utf-8", xml_declaration=True)
        return xml_path

    def list_sessions(self):
        sessions = []
        if os.path.exists(self.sessions_dir):
            for d in os.listdir(self.sessions_dir):
                if os.path.isdir(os.path.join(self.sessions_dir, d)):
                    sessions.append(d)
        return sessions

    def add_track_offline(self, session_name, track_name, track_type):
        path = self._get_session_path(session_name)
        if not os.path.exists(path):
            raise Exception(f"Session {session_name} not found at {path}")
            
        tree = ET.parse(path)
        root = tree.getroot()
        
        counter = int(root.attrib.get("id-counter", "100"))
        track_id = str(counter + 1)
        root.attrib["id-counter"] = str(counter + 10)
        
        routes = root.find("Routes")
        if routes is None:
            routes = ET.SubElement(root, "Routes")
            
        ET.SubElement(routes, "Route", {
            "id": track_id,
            "name": track_name,
            "default-type": track_type,
            "active": "yes",
            "phase-invert": "00",
            "denormal-protection": "no",
            "meter-point": "MeterPostFader",
            "order-keys": "editor=1,mixer=1"
        })
        
        tree.write(path, encoding="utf-8", xml_declaration=True)
        return track_id

    def list_tracks(self, session_name):
        path = self._get_session_path(session_name)
        if not os.path.exists(path):
            return []
            
        tree = ET.parse(path)
        root = tree.getroot()
        tracks = []
        
        routes = root.find("Routes")
        if routes is not None:
            for route in routes.findall("Route"):
                tracks.append({
                    "id": route.attrib.get("id"),
                    "name": route.attrib.get("name"),
                    "type": route.attrib.get("default-type"),
                    "is_master": "MasterOut" in route.attrib.get("flags", "")
                })
        return tracks

if __name__ == "__main__":
    sm = SessionManager()
    print("SessionManager module ready.")
