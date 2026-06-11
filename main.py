import requests
import json
import os
import re
import sys
from datetime import datetime
from urllib.parse import urlparse
from typing import Dict, List, Optional, Tuple


# ============================================================
#  UTILIDADES DE CONSOLA
# ============================================================

COLORS = {
    "green": "\033[92m",
    "red": "\033[91m",
    "blue": "\033[94m",
    "yellow": "\033[93m",
    "cyan": "\033[96m",
    "magenta": "\033[95m",
}


def print_colored(text: str, color: str) -> None:
    print(f"{COLORS.get(color, '')}{text}\033[0m")


def input_colored(prompt: str, color: str) -> str:
    return input(f"{COLORS.get(color, '')}{prompt}\033[0m")


# ============================================================
#  ENTRADA DE DATOS
# ============================================================

def get_env_or_input(env_name: str, prompt: str, uppercase: bool = False) -> str:
    value = os.getenv(env_name)
    if value:
        return value.upper() if uppercase else value
    user_value = input_colored(prompt, "cyan")
    return user_value.upper() if uppercase else user_value


def get_base_url() -> str:
    base_url_input = os.getenv("IPTV_URL") or input_colored("Enter IPTV link: ", "cyan")
    parsed = urlparse(base_url_input)
    scheme = parsed.scheme or "http"
    host = parsed.hostname
    port = parsed.port or 80
    return f"{scheme}://{host}:{port}"


# ============================================================
#  PETICIONES AL SERVIDOR
# ============================================================

def get_token(
    session: requests.Session,
    base_url: str,
    mac: str,
    serial: str,
    device_id: str,
    device_id_2: str,
    timeout: int = 10,
) -> Optional[str]:

    url = f"{base_url}/portal.php?action=handshake&type=stb&token=&JsHttpRequest=1-xml"
    headers = {"Authorization": f"MAC {mac}"}

    payload = {
        k: v for k, v in {
            "serial": serial,
            "device_id": device_id,
            "device_id_2": device_id_2,
        }.items() if v
    }

    try:
        res = session.post(url, headers=headers, json=payload, timeout=timeout) if payload else session.get(url, headers=headers, timeout=timeout)
        res.raise_for_status()
        return res.json()["js"]["token"]

    except Exception as e:
        print_colored(f"Error fetching token: {e}", "red")
        return None


def get_subscription(session: requests.Session, base_url: str, token: str) -> bool:
    url = f"{base_url}/portal.php?type=account_info&action=get_main_info&JsHttpRequest=1-xml"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        res = session.get(url, headers=headers)
        res.raise_for_status()
        data = res.json()["js"]

        print_colored(
            f"MAC = {data.get('mac')}\n"
            f"Serial = {data.get('serial', 'N/A')}\n"
            f"Device ID = {data.get('device_id', 'N/A')}\n"
            f"Device ID 2 = {data.get('device_id_2', 'N/A')}\n"
            f"Expiry = {data.get('phone', 'N/A')}",
            "green",
        )
        return True

    except Exception as e:
        print_colored(f"Error fetching subscription info: {e}", "red")
        return False


def get_channel_list(
    session: requests.Session, base_url: str, token: str
) -> Tuple[Optional[List[Dict]], Optional[Dict]]:

    headers = {"Authorization": f"Bearer {token}"}

    try:
        # Géneros
        res_genre = session.get(
            f"{base_url}/server/load.php?type=itv&action=get_genres&JsHttpRequest=1-xml",
            headers=headers,
        )
        res_genre.raise_for_status()
        group_info = {g["id"]: g["title"] for g in res_genre.json()["js"]}

        # Canales
        res_channels = session.get(
            f"{base_url}/portal.php?type=itv&action=get_all_channels&JsHttpRequest=1-xml",
            headers=headers,
        )
        res_channels.raise_for_status()
        channels = res_channels.json()["js"]["data"]

        return channels, group_info

    except Exception as e:
        print_colored(f"Error fetching channel list: {e}", "red")
        return None, None


# ============================================================
#  GENERACIÓN DE ARCHIVO M3U
# ============================================================

def save_channel_list(
    base_url: str,
    channels: List[Dict],
    groups: Dict,
    mac: str,
    serial: str,
    device_id: str,
) -> None:

    # Carpeta fija
    output_dir = "output"
    filename = os.path.join(output_dir, "vivo.m3u")

    # Crear carpeta si no existe
    os.makedirs(output_dir, exist_ok=True)

    count = 0

    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")

            for ch in channels:
                name = ch.get("name", "Unknown")
                logo = ch.get("logo", "")
                group = groups.get(ch.get("tv_genre_id", "0"), "General")

                raw_url = ch.get("cmds", [{}])[0].get("url", "").replace("ffmpeg ", "")
                if not raw_url:
                    continue

                if "localhost" in raw_url:
                    match = re.search(r"/ch/(\\d+)", raw_url)
                    if match:
                        ch_id = match.group(1)
                        raw_url = f"{base_url}/play/live.php?mac={mac}&stream={ch_id}&extension=ts"
                        if serial:
                            raw_url += f"&serial={serial}"
                        if device_id:
                            raw_url += f"&device_id={device_id}"

                f.write(f'#EXTINF:-1 tvg-logo="{logo}" group-title="{group}",{name}\n')
                f.write(f"{raw_url}\n")
                count += 1

        print_colored(f"Total channels: {count}", "green")
        print_colored(f"Saved to: {filename}", "blue")

    except Exception as e:
        print_colored(f"Error saving file: {e}", "red")


# ============================================================
#  MAIN
# ============================================================

def main():
    try:
        base_url = get_base_url()
        mac = get_env_or_input("MAC_ADDRESS", "Input MAC: ", uppercase=True)
        serial = get_env_or_input("SERIAL_NUMBER", "Input serial (optional): ")
        device_id = get_env_or_input("DEVICE_ID", "Input device ID (optional): ")
        device_id_2 = get_env_or_input("DEVICE_ID_2", "Input device ID 2 (optional): ")

        session = requests.Session()
        session.cookies.update({"mac": mac})
        session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Referer": f"{base_url}/c/",
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        })

        token = get_token(session, base_url, mac, serial, device_id, device_id_2)
        if not token:
            return

        print_colored("Token acquired.", "green")

        if not get_subscription(session, base_url, token):
            return

        channels, groups = get_channel_list(session, base_url, token)
        if channels and groups:
            save_channel_list(base_url, channels, groups, mac, serial, device_id)

    except KeyboardInterrupt:
        print_colored("Exiting...", "yellow")
        sys.exit(0)


if __name__ == "__main__":
    main()