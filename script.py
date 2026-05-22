import requests
import re
import time

# ========= CONFIG =========
PORTAL = os.getenv("PORTAL", "")
MAC = os.getenv("MAC", "")
SERIAL_NUMBER = os.getenv("SERIAL_NUMBER", "")
DEVICE_ID = os.getenv("DEVICE_ID", "")
DEVICE_ID2 = os.getenv("DEVICE_ID2", "")
OUTPUT = os.getenv("OUTPUT", "canales.m3u")
# ==========================

session = requests.Session()

COMMON_HEADERS = {
    "User-Agent": USER_AGENT,
    "X-User-Agent": "Model: MAG250; Link: Ethernet",
    "Referer": PORTAL.replace("/server/load.php", "/c/"),
    "Cookie": f"mac={MAC}; stb_lang=es; timezone=Europe/Madrid;",
}

def call_api(params, token=None):
    headers = COMMON_HEADERS.copy()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    r = session.get(PORTAL, headers=headers, params=params, timeout=15)
    r.raise_for_status()
    return r.json()

def handshake():
    params = {
        "type": "stb",
        "action": "handshake",
        "token": "",
        "JsHttpRequest": "1-xml"
    }
    data = call_api(params)
    token = data.get("js", {}).get("token")
    if not token:
        raise Exception("No se pudo obtener el token en el handshake")
    return token

def get_profile(token):
    params = {
        "type": "stb",
        "action": "get_profile",
        "hd": "1",
        "ver": "ImageDescription: .2.18-r23-250; ImageDate: Thu Sep 13 11:31:16 EEST 2018; PORTAL version: 5.5.; API Version: JS API version: 343; STB API version: 146; Player Engine version: x58c",
        "num_banks": "2",
        "sn": SERIAL_NUMBER,
        "stb_type": "MAG250",
        "client_type": "STB",
        "image_version": "218",
        "video_out": "hdmi",
        "device_id": DEVICE_ID,
        "device_id2": DEVICE_ID2,
        "signature": "",
        "auth_second_step": "1",
        "hw_version": "1.7-BD-00",
        "not_valid_token": "",
        "metrics": '{{"mac":"{}","sn":"{}","model":"MAG250","type":"STB","uid":"","random":"{}"}}'.format(
            MAC, SERIAL_NUMBER, int(time.time())
        ),
        "hw_version_2": "",
        "timestamp": str(int(time.time())),
        "api_signature": "262",
        "prehash": "",
        "JsHttpRequest": "1-xml"
    }
    return call_api(params, token=token)
    channels = data.get("js", {}).get("data", [])
    return channels

def get_create_link(token, cmd):
    params = {
        "type": "itv",
        "action": "create_link",
        "cmd": cmd,
        "series": "",
        "forced_storage": "undefined",
        "disable_ad": "",
        "download": "",
        "force_ch_link_check": "",
        "JsHttpRequest": "1-xml"
    }
    data = call_api(params, token=token)
    link = data.get("js", {}).get("cmd", "")

    # A veces responde algo como: ffmpeg http://...
    match = re.search(r'(https?://\S+)', link)
    return match.group(1) if match else link

def generate_m3u(channels, token):
    lines = ["#EXTM3U"]

    for ch in channels:
        name = ch.get("name", "Sin nombre")
        tvg_id = ch.get("xmltv_id", "")
        logo = ch.get("logo", "")
        group = ch.get("tv_genre_id", "")
        cmd = ch.get("cmd")

        if not cmd:
            continue

        try:
            url = get_create_link(token, cmd)
            if not url:
                continue

            extinf = f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{name}" tvg-logo="{logo}" group-title="{group}",{name}'
            lines.append(extinf)
            lines.append(url)
            print(f"[OK] {name}")
        except Exception as e:
            print(f"[ERROR] {name}: {e}")

    return "\n".join(lines)

def main():
    print("[*] Handshake...")
    token = handshake()
    print(f"[+] Token obtenido: {token}")

    print("[*] Perfil...")
    get_profile(token)

    print("[*] Obteniendo canales...")
    channels = get_channels(token)
    print(f"[+] Canales encontrados: {len(channels)}")

    print("[*] Generando M3U...")
    m3u_content = generate_m3u(channels, token)

    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(m3u_content)

    print(f"[+] Archivo guardado en: {OUTPUT}")

if __name__ == "__main__":
    main()
