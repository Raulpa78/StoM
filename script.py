import os
import sys
import json
import time
from pathlib import Path

OUTPUT = os.getenv("OUTPUT", "salida.m3u")

PORTAL = os.getenv("PORTAL", "")
MAC = os.getenv("MAC", "")
SERIAL_NUMBER = os.getenv("SERIAL_NUMBER", "")
DEVICE_ID = os.getenv("DEVICE_ID", "")
DEVICE_ID2 = os.getenv("DEVICE_ID2", "")

def validate_env():
    required = {
        "PORTAL": PORTAL,
        "MAC": MAC,
        "SERIAL_NUMBER": SERIAL_NUMBER,
        "DEVICE_ID": DEVICE_ID,
        "DEVICE_ID2": DEVICE_ID2,
    }

    missing = [key for key, value in required.items() if not value.strip()]
    if missing:
        raise RuntimeError(
            "Faltan variables de entorno requeridas: " + ", ".join(missing)
        )

def mask(value, visible=4):
    if not value:
        return ""
    if len(value) <= visible:
        return "*" * len(value)
    return value[:visible] + "*" * (len(value) - visible)

def build_payload():
    return {
        "portal": PORTAL,
        "device": {
            "mac": MAC,
            "serial_number": SERIAL_NUMBER,
            "device_id": DEVICE_ID,
            "device_id2": DEVICE_ID2,
        },
        "generated_at": int(time.time())
    }

def generate_demo_m3u():
    lines = [
        "#EXTM3U",
        '#EXTINF:-1 tvg-id="demo" tvg-name="Demo" group-title="Demo",Canal Demo',
        "https://example.com/stream/demo.m3u8"
    ]
    return "\n".join(lines)

def main():
    try:
        validate_env()

        print("[INFO] Variables cargadas correctamente")
        print(f"[INFO] PORTAL: {PORTAL}")
        print(f"[INFO] MAC: {mask(MAC)}")
        print(f"[INFO] SERIAL_NUMBER: {mask(SERIAL_NUMBER)}")
        print(f"[INFO] DEVICE_ID: {mask(DEVICE_ID)}")
        print(f"[INFO] DEVICE_ID2: {mask(DEVICE_ID2)}")

        payload = build_payload()

        Path("debug_payload.json").write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8"
        )

        m3u_content = generate_demo_m3u()
        Path(OUTPUT).write_text(m3u_content, encoding="utf-8")

        print(f"[OK] Archivo generado: {OUTPUT}")
        print("[OK] Archivo auxiliar generado: debug_payload.json")

    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()