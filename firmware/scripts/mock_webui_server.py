"""Host mock server for developing and smoke-testing firmware/data/ Web UI."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

STATE = {
    "config": {
        "device_name": "Front Gate",
        "wifi": {"ssid": "HomeNet", "password_set": True, "hostname": "wiegand-gate-controller", "antenna": "auto"},
        "mqtt": {
            "enabled": True,
            "host": "192.168.1.10",
            "port": 1883,
            "username": "mqtt",
            "password_set": True,
            "base_topic": "wiegand-gate-controller",
            "discovery_prefix": "homeassistant",
            "ha_discovery": True,
        },
        "relay": {
            "mode": "gate_dual",
            "relay1_pulse_ms": 600,
            "relay2_pulse_ms": 600,
            "relay1_inverted": False,
            "relay2_inverted": False,
            "relay1_hold_open": False,
            "travel_time_ms": 15000,
        },
        "sensor": {
            "mode": "roger_b70",
            "in1_inverted": False,
            "in2_inverted": False,
            "in3_inverted": False,
            "in3_enabled": True,
            "in3_pedestrian": False,
            "cor_indicates_open": True,
            "sc_blink_timeout_ms": 2200,
        },
        "reader": {
            "wiegand_bits": 0,
            "pin_min_len": 4,
            "pin_max_len": 8,
            "pin_timeout_ms": 5000,
            "keypad_enabled": True,
            "led_active_low": True,
            "beep_active_low": True,
            "granted_beep_ms": 150,
            "granted_led_ms": 2500,
            "denied_beeps": 3,
            "card_action": "toggle",
            "card_cooldown_ms": 0,
        },
    },
    "gate_state": "closed",
    "users": [
        {"id": 1, "name": "Valentinas Ring", "card": "2764857", "pin": "1234", "enabled": True, "target": "primary", "hits": 12},
        {"id": 2, "name": "Courier UHF", "card": "3AABBCCDDEEFF11", "pin": "", "enabled": True, "target": "pedestrian", "hits": 3},
    ],
    "next_id": 3,
    "last_unknown": {"code": "8844112", "bits": 26, "at_ms": 42000},
    "events": [
        {"ts": 42000, "type": "denied", "source": "wiegand", "user": "-", "code": "8844112"},
        {"ts": 31000, "type": "granted", "source": "wiegand", "user": "Valentinas Ring", "code": "2764857"},
    ],
}


def deep_merge(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            deep_merge(dst[k], v)
        elif k != "password" or v:
            dst[k] = v


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, mime: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: object, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(n).decode()) if n > 0 else {}

    def do_GET(self) -> None:
        u = urlparse(self.path)
        if u.path == "/":
            self._send(200, (DATA / "index.html").read_bytes(), "text/html")
        elif u.path == "/app.css":
            self._send(200, (DATA / "app.css").read_bytes(), "text/css")
        elif u.path == "/app.js":
            self._send(200, (DATA / "app.js").read_bytes(), "application/javascript")
        elif u.path == "/api/status":
            cfg = STATE["config"]
            self._json({
                "device_name": cfg["device_name"],
                "fw_version": "sim-1.0",
                "uptime_s": 120,
                "vin_v": 24.15,
                "simulated": True,
                "network": {"wifi_connected": True, "ap_mode": False, "ip": "192.168.1.55", "mac": "AABBCCDDEEFF", "rssi": -54, "mqtt_connected": True, "antenna": "external" if cfg["wifi"].get("antenna") == "external" else "internal"},
                "gate": {"state": STATE["gate_state"], "mode": cfg["relay"]["mode"], "sensor_mode": cfg["sensor"]["mode"], "hold_open": False, "relay1": False, "relay2": False, "in1": STATE["gate_state"] != "closed", "in2": STATE["gate_state"] == "open", "in3": False},
                "last_unknown": STATE["last_unknown"],
                "users_count": len(STATE["users"]),
            })
        elif u.path == "/api/config":
            self._json(STATE["config"])
        elif u.path == "/api/users":
            self._json({"users": STATE["users"]})
        elif u.path == "/api/events":
            self._json({"events": STATE["events"]})
        else:
            self._send(404, b"Not found", "text/plain")

    def do_POST(self) -> None:
        u = urlparse(self.path)
        if u.path == "/api/config":
            deep_merge(STATE["config"], self._body())
            self._json({"ok": True})
        elif u.path == "/api/users":
            b = self._body()
            uid = int(b.get("id") or 0)
            if uid == 0:
                uid = STATE["next_id"]
                STATE["next_id"] += 1
                STATE["users"].append({"id": uid, "name": b["name"], "card": b.get("card", ""), "pin": b.get("pin", ""), "enabled": bool(b.get("enabled", True)), "target": b.get("target", "primary"), "hits": 0})
            else:
                for usr in STATE["users"]:
                    if usr["id"] == uid:
                        usr.update({"name": b["name"], "card": b.get("card", ""), "pin": b.get("pin", ""), "enabled": bool(b.get("enabled", True)), "target": b.get("target", "primary")})
            STATE["last_unknown"] = {"code": "", "bits": 0, "at_ms": 0}
            self._json({"ok": True})
        elif u.path == "/api/action":
            act = self._body().get("action", "")
            if act in ("open", "unlock"):
                STATE["gate_state"] = "open"
            elif act in ("close", "lock"):
                STATE["gate_state"] = "closed"
            elif act == "clear_unknown":
                STATE["last_unknown"] = {"code": "", "bits": 0, "at_ms": 0}
            self._json({"ok": True})
        else:
            self._json({"ok": False}, 404)

    def do_DELETE(self) -> None:
        u = urlparse(self.path)
        if u.path == "/api/users":
            uid = int(parse_qs(u.query).get("id", ["0"])[0])
            STATE["users"] = [x for x in STATE["users"] if x["id"] != uid]
            self._json({"ok": True})
        else:
            self._json({"ok": False}, 404)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
