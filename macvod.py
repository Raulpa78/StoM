import requests
import json
import os
import sys
import re
import base64
from urllib.parse import urlparse
from typing import Dict, Optional, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
#  UTILIDADES DE COLOR
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
    print(f"{COLORS.get(color, '')}{text}\033[m")


def input_colored(prompt: str, color: str) -> str:
    return input(f"{COLORS.get(color, '')}{prompt}\033[m")


# ============================================================
#  VALIDACIÓN DE ENTRADAS
# ============================================================

def get_base_url() -> str:
    base_url_input = os.getenv("IPTV_URL", "").strip()

    if not base_url_input:
        if not sys.stdin.isatty():
            raise ValueError("Falta IPTV_URL y no hay entrada interactiva disponible.")
        base_url_input = input_colored("Enter IPTV link: ", "cyan").strip()

    parsed = urlparse(base_url_input)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError("URL inválida. Ejemplo: http://dominio:puerto")

    return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}" if parsed.port else f"{parsed.scheme}://{parsed.hostname}"


def get_env_or_input(env_name: str, prompt: str, optional: bool = True) -> str:
    value = os.getenv(env_name, "").strip()
    if value:
        return value

    if not sys.stdin.isatty():
        return "" if optional else ValueError(f"Falta {env_name}")

    try:
        return input_colored(prompt, "cyan").strip()
    except EOFError:
        return ""


def get_mac_address() -> str:
    mac = get_env_or_input("MAC_ADDRESS", "Input MAC address: ", optional=False)
    return mac.upper()


# ============================================================
#  PETICIONES AL SERVIDOR
# ============================================================

def get_token(session, base_url, mac, serial="", device_id="", device_id_2="", timeout=10):
    url = f"{base_url}/portal.php?action=handshake&type=stb&token=&JsHttpRequest=1-xml"
    headers = {"Authorization": f"MAC {mac}"}

    payload = {k: v for k, v in {
        "serial": serial,
        "device_id": device_id,
        "device_id_2": device_id_2
    }.items() if v}

    try:
        res = session.post(url, headers=headers, json=payload, timeout=timeout) if payload \
            else session.get(url, headers=headers, timeout=timeout)

        res.raise_for_status()
        return res.json().get("js", {}).get("token")

    except Exception as e:
        print_colored(f"Error fetching token: {e}", "red")
        return None


def get_vod_categories(session, base_url, token):
    url = f"{base_url}/portal.php?type=vod&action=get_categories&JsHttpRequest=1-xml"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        res = session.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        return res.json().get("js")
    except Exception as e:
        print_colored(f"Error fetching VOD categories: {e}", "red")
        return None


def get_vod_list(session, base_url, token, category_id, page=1):
    url = (
        f"{base_url}/portal.php?type=vod&action=get_ordered_list"
        f"&category={category_id}&p={page}&JsHttpRequest=1-xml"
    )
    headers = {"Authorization": f"Bearer {token}"}

    try:
        res = session.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        return res.json().get("js", {}).get("data")
    except:
        return None


# ============================================================
#  RESOLVER URL REAL DEL VOD (INDIVIDUAL)
# ============================================================

def resolve_vod_url(session, base_url, token, cmd_value):
    try:
        decoded = base64.b64decode(cmd_value).decode("utf-8")
        print_colored(f"CMD decodificado: {decoded}", "yellow")
        payload = json.loads(decoded)
    except Exception as e:
        print_colored(f"Error decodificando cmd: {e}", "red")
        return None

    # Si ya viene una URL en el JSON, úsala directamente
    if isinstance(payload, dict) and "cmd" in payload and payload["cmd"].startswith("http"):
        print_colored("Usando URL directa desde cmd (sin create_link)", "cyan")
        return payload["cmd"]

    # Normalizar campos para create_link
    if "stream_id" in payload:
        payload["id"] = payload["stream_id"]

    if "target_container" in payload and isinstance(payload["target_container"], list):
        payload["type"] = payload["target_container"][0]

    url = f"{base_url}/portal.php?type=vod&action=create_link&JsHttpRequest=1-xml"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        res = session.post(url, headers=headers, json=payload, timeout=10)
        print_colored(f"Respuesta create_link: {res.text}", "magenta")
        res.raise_for_status()
        data = res.json().get("js", {})
        real_url = data.get("cmd")
        return real_url
    except Exception as e:
        print_colored(f"Error en create_link: {e}", "red")
        return None

# ============================================================
#  RESOLVER URLs EN PARALELO (TURBO MODE)
# ============================================================

def resolve_urls_parallel(session, base_url, token, vod_items, max_workers=30):
    print_colored("Resolviendo URLs reales en paralelo...", "yellow")

    resolved = {}

    def task(vod):
        cmd_value = vod.get("cmd", "")
        if not cmd_value:
            return vod["name"], None

        if cmd_value.startswith("ey"):
            url = resolve_vod_url(session, base_url, token, cmd_value)
            return vod["name"], url
        else:
            return vod["name"], cmd_value

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(task, vod): vod for vod in vod_items}

        for future in as_completed(futures):
            title, url = future.result()
            resolved[title] = url

    print_colored("Resolución de URLs completada.", "green")
    return resolved


# ============================================================
#  EXPORTACIÓN A M3U POR CATEGORÍA
# ============================================================

def sanitize_filename(name: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_\-\.]', '_', name)


def export_m3u_by_category(category_title, resolved_urls):
    safe_title = sanitize_filename(category_title)
    filename = f"tar_nex_vod_{safe_title}.m3u"

    with open(filename, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")

        for title, url in resolved_urls.items():
            if not url:
                continue

            f.write(f'#EXTINF:-1,{title}\n')
            f.write(f'{url}\n')

    print_colored(f"M3U generado: {filename}", "green")


# ============================================================
#  DESCARGA DE CARÁTULAS MULTIHILO
# ============================================================

def download_poster(url, save_path):
    try:
        res = requests.get(url, timeout=10, stream=True)
        res.raise_for_status()

        with open(save_path, "wb") as f:
            for chunk in res.iter_content(1024):
                f.write(chunk)

        return True
    except:
        return False


def download_posters_for_category(vod_items, category_title, max_workers=20):
    folder = f"posters_{sanitize_filename(category_title)}"
    os.makedirs(folder, exist_ok=True)

    print_colored(f"Descargando carátulas (multihilo) para: {category_title}", "yellow")

    tasks = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:

        for vod in vod_items:
            title = vod.get("name", "Sin título")
            poster_url = (
                vod.get("poster") or vod.get("cover") or
                vod.get("screenshot") or vod.get("icon")
            )

            if not poster_url:
                continue

            filename = sanitize_filename(title) + ".jpg"
            save_path = os.path.join(folder, filename)

            tasks.append(executor.submit(download_poster, poster_url, save_path))

        completed = 0
        for _ in as_completed(tasks):
            completed += 1
            print_colored(f"Carátulas descargadas: {completed}/{len(tasks)}", "cyan")


# ============================================================
#  PROCESAR SOLO CATEGORÍAS FILTRADAS
# ============================================================

def fetch_all_vods_by_category(session, base_url, token, categories):
    result = {}

    for cat in categories:
        cat_id = cat.get("id")
        cat_title = cat.get("title", "Sin título")

        print_colored(f"Procesando categoría: {cat_title}", "cyan")

        page = 1
        vods = []

        while True:
            vod_list = get_vod_list(session, base_url, token, cat_id, page)
            if not vod_list:
                break

            vods.extend(vod_list)
            page += 1

        result[cat_title] = vods

    return result


# ============================================================
#  MAIN
# ============================================================

def main():
    try:
        base_url = get_base_url()
        mac = get_mac_address()
        serial = get_env_or_input("SERIAL_NUMBER", "Input serial number (optional): ")
        device_id = get_env_or_input("DEVICE_ID", "Input device ID (optional): ")
        device_id_2 = get_env_or_input("DEVICE_ID_2", "Input secondary device ID (optional): ")

        session = requests.Session()
        session.cookies.update({"mac": mac})
        session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Referer": f"{base_url}/c/",
            "Accept": "application/json, text/javascript, */*; q=.01",
            "X-Requested-With": "XMLHttpRequest",
        })

        token = get_token(session, base_url, mac, serial, device_id, device_id_2)
        if not token:
            print_colored("No se pudo obtener el token.", "red")
            sys.exit(1)

        print_colored(f"Token obtenido: {token}", "green")

        vod_categories = get_vod_categories(session, base_url, token)
        if not vod_categories:
            print_colored("No se pudieron obtener categorías VOD.", "red")
            sys.exit(1)

        # FILTRO CORRECTO (solo ES y HINDI reales)
        filtered_categories = []
        for c in vod_categories:
            title = c.get("title", "").lower()

            if "┃es┃" in title or title.startswith("┃es┃"):
                filtered_categories.append(c)
                continue

            if "hindi" in title:
                filtered_categories.append(c)
                continue

        print_colored(f"Categorías filtradas: {len(filtered_categories)}", "yellow")
        for c in filtered_categories:
            print_colored(f"- {c.get('title')}", "cyan")

        # SOLO procesar categorías filtradas
        vod_by_category = fetch_all_vods_by_category(session, base_url, token, filtered_categories)

        total_vods = sum(len(v) for v in vod_by_category.values())
        print_colored(f"Total VODs encontrados: {total_vods}", "green")

        for category_title, vod_items in vod_by_category.items():

            # 🔥 RESOLVER URLs EN PARALELO (TURBO)
            resolved_urls = resolve_urls_parallel(session, base_url, token, vod_items)

            # Generar M3U
            export_m3u_by_category(category_title, resolved_urls)

            # Descargar carátulas
            download_posters_for_category(vod_items, category_title)

    except Exception as e:
        print_colored(f"Error inesperado: {e}", "red")
        sys.exit(1)


if __name__ == "__main__":
    main()
