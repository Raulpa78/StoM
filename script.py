import os
import requests
import re
import time
import sys

# ========= CONFIG =========
PORTAL = os.getenv("PORTAL", "")
MAC = os.getenv("MAC", "")
SERIAL_NUMBER = os.getenv("SERIAL_NUMBER", "")
DEVICE_ID = os.getenv("DEVICE_ID", "")
DEVICE_ID2 = os.getenv("DEVICE_ID2", "")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "")
OUTPUT = os.getenv("OUTPUT", "canales.m3u")
# ==========================

session = requests.Session()

USER_AGENT = os.getenv("USER_AGENT", "MAG270")
COMMON_HEADERS = {
    "User-Agent": USER_AGENT,
    "X-User-Agent": "Model: MAG270; Link: Ethernet",
    "Referer": PORTAL.replace("/server/load.php", "/c/") if PORTAL else "",
    "Cookie": f"mac={MAC}; stb_lang=es; timezone=Europe/Madrid;",
}

def validate_config():
    """Validate that all required environment variables are configured."""
    required_vars = {
        "PORTAL": PORTAL,
        "MAC": MAC,
        "SERIAL_NUMBER": SERIAL_NUMBER,
        "DEVICE_ID": DEVICE_ID,
        "DEVICE_ID2": DEVICE_ID2,
        "AUTH_TOKEN": AUTH_TOKEN,
    }
    
    missing_vars = [var for var, value in required_vars.items() if not value]
    
    if missing_vars:
        print("[ERROR] Missing required environment variables:")
        for var in missing_vars:
            print(f"  - {var}")
        raise Exception(f"Missing required configuration: {', '.join(missing_vars)}")
    
    print("[+] Configuration validated successfully")

def call_api(params, token=None):
    """Make API call with error handling and diagnostics."""
    headers = COMMON_HEADERS.copy()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    try:
        print(f"[DEBUG] Making request to: {PORTAL}")
        print(f"[DEBUG] Params: {params}")
        
        r = session.get(PORTAL, headers=headers, params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    
    except requests.exceptions.HTTPError as e:
        print(f"[ERROR] HTTP {e.response.status_code}: {e.response.reason}")
        print(f"[ERROR] Response text: {e.response.text[:500]}")  # First 500 chars
        print(f"[DEBUG] Request URL: {e.response.url}")
        print(f"[DEBUG] Request headers: {dict(headers)}")
        raise
    
    except requests.exceptions.ConnectionError as e:
        print(f"[ERROR] Connection error: {e}")
        raise
    
    except requests.exceptions.Timeout as e:
        print(f"[ERROR] Request timeout: {e}")
        raise
    
    except Exception as e:
        print(f"[ERROR] Unexpected error: {type(e).__name__}: {e}")
        raise

def handshake():
    """Perform initial handshake using the AUTH_TOKEN from environment."""
    params = {
        "type": "stb",
        "action": "handshake",
        "token": AUTH_TOKEN,
        "JsHttpRequest": "1-xml"
    }
    
    try:
        print("[*] Attempting handshake...")
        data = call_api(params)
        token = data.get("js", {}).get("token")
        
        if not token:
            print(f"[DEBUG] Handshake response: {data}")
            raise Exception("No se pudo obtener el token en el handshake")
        
        print(f"[+] Token obtenido: {token}")
        return token
    
    except Exception as e:
        print(f"[ERROR] Handshake failed: {e}")
        raise

def get_profile(token):
    """Get user profile and channels list."""
    params = {
        "type": "stb",
        "action": "get_profile",
        "hd": "1",
        "ver": "ImageDescription: .2.18-r23-270; ImageDate: Thu Sep 13 11:31:16 EEST 2018; PORTAL version: 5.5.; API Version: JS API version: 343; STB API version: 146; Player Engine version: x58[...]",
        "num_banks": "2",
        "sn": SERIAL_NUMBER,
        "stb_type": "MAG270",
        "client_type": "STB",
        "image_version": "218",
        "video_out": "hdmi",
        "device_id": DEVICE_ID,
        "device_id2": DEVICE_ID2,
        "signature": "",
        "auth_second_step": "1",
        "hw_version": "1.7-BD-00",
        "not_valid_token": "",
        "metrics": '{{"mac":"{}","sn":"{}","model":"MAG270","type":"STB","uid":"","random":"{}"}}'.format(
            MAC, SERIAL_NUMBER, int(time.time())
        ),
        "hw_version_2": "",
        "timestamp": str(int(time.time())),
        "api_signature": "262",
        "prehash": "",
        "JsHttpRequest": "1-xml"
    }
    
    try:
        print("[*] Fetching profile...")
        data = call_api(params, token=token)
        channels = data.get("js", {}).get("data", [])
        print(f"[+] Canales encontrados: {len(channels)}")
        return channels
    
    except Exception as e:
        print(f"[ERROR] Failed to get profile: {e}")
        raise

def get_create_link(token, cmd):
    """Create streaming link for a channel."""
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
    
    try:
        data = call_api(params, token=token)
        link = data.get("js", {}).get("cmd", "")
        
        # A veces responde algo como: ffmpeg http://...
        match = re.search(r'(https?://\S+)', link)
        return match.group(1) if match else link
    
    except Exception as e:
        print(f"[DEBUG] Error creating link for cmd {cmd}: {e}")
        raise

def generate_m3u(channels, token):
    """Generate M3U playlist from channels."""
    lines = ["#EXTM3U"]
    success_count = 0
    error_count = 0
    
    for idx, ch in enumerate(channels, 1):
        name = ch.get("name", "Sin nombre")
        tvg_id = ch.get("xmltv_id", "")
        logo = ch.get("logo", "")
        group = ch.get("tv_genre_id", "")
        cmd = ch.get("cmd")
        
        if not cmd:
            print(f"[SKIP] {name}: No cmd found")
            continue
        
        try:
            print(f"[{idx}/{len(channels)}] Processing: {name}")
            url = get_create_link(token, cmd)
            
            if not url:
                print(f"[SKIP] {name}: Empty URL returned")
                error_count += 1
                continue
            
            extinf = f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{name}" tvg-logo="{logo}" group-title="{group}",{name}'
            lines.append(extinf)
            lines.append(url)
            print(f"[OK] {name}")
            success_count += 1
        
        except Exception as e:
            print(f"[ERROR] {name}: {e}")
            error_count += 1
            continue
    
    print(f"\n[SUMMARY] Successful: {success_count}, Failed: {error_count}, Total: {len(channels)}")
    return "\n".join(lines)

def main():
    """Main execution function."""
    try:
        print("=" * 60)
        print("Script: Generador de M3U para Portal IPTV")
        print("=" * 60)
        
        # Validate configuration
        validate_config()
        print()
        
        # Handshake
        print("[*] Handshake...")
        token = handshake()
        print()
        
        # Get profile
        print("[*] Obteniendo perfil...")
        channels = get_profile(token)
        print()
        
        if not channels:
            print("[WARNING] No channels found!")
            sys.exit(1)
        
        # Generate M3U
        print("[*] Generando M3U...")
        m3u_content = generate_m3u(channels, token)
        print()
        
        # Save to file
        with open(OUTPUT, "w", encoding="utf-8") as f:
            f.write(m3u_content)
        
        print(f"[+] Archivo guardado en: {OUTPUT}")
        print("=" * 60)
        print("[SUCCESS] Script executed successfully!")
        print("=" * 60)
    
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Script interrupted by user")
        sys.exit(130)
    
    except Exception as e:
        print(f"\n[CRITICAL] Script failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
