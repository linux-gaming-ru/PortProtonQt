"""Steam shortcuts management for PortProtonQt."""

import base64
import os
import random
import re
import shlex
import shutil
import zlib
from functools import partial
from pathlib import Path
from urllib.parse import urlsplit

import orjson
import requests
import vdf
import websocket

from portprotonqt.config.portproton import get_custom_icon_path
from portprotonqt.logger import get_logger
from portprotonqt.downloader import Downloader
from portprotonqt.icon_extractor import generate_thumbnail
from portprotonqt.config import (
    extract_exec_target_path,
    game_config,
    get_portproton_location,
    get_portproton_start_command,
    ui_config,
)
from portprotonqt.steam_api.utils import (
    safe_vdf_load,
    get_steam_home,
    get_last_steam_user,
    get_steam_users,
    convert_steam_id,
)
from portprotonqt.steam_api.api import (
    get_steam_game_info_async,
    fetch_sgdb_cover_async,
)

logger = get_logger(__name__)
downloader = Downloader()


def enable_steam_cef() -> tuple[bool, str]:
    """
    Check and enable Steam CEF remote debugging if necessary.

    Creates a .cef-enable-remote-debugging file in the Steam directory.
    Steam must be restarted after the file is first created.

    Returns:
        (True, "already_enabled") if already enabled.
        (True, "restart_needed") if just enabled and Steam restart is needed.
        (False, "steam_not_found") if Steam directory is not found.
    """
    steam_home = get_steam_home()
    if not steam_home:
        return (False, "steam_not_found")

    cef_flag_file = steam_home / ".cef-enable-remote-debugging"
    logger.info(f"Checking CEF flag: {cef_flag_file}")

    if cef_flag_file.exists():
        logger.info("CEF Remote Debugging is already enabled")
        return (True, "already_enabled")
    else:
        try:
            os.makedirs(cef_flag_file.parent, exist_ok=True)
            cef_flag_file.touch()
            logger.info("Enabled CEF Remote Debugging. Steam restart required")
            return (True, "restart_needed")
        except Exception as e:
            logger.error(f"Failed to create CEF flag {cef_flag_file}: {e}")
            return (False, str(e))


def call_steam_api(js_cmd: str, *args) -> dict | None:
    """
    Execute a JavaScript function in the Steam context via CEF Remote Debugging.

    Args:
        js_cmd: Name of the JS function to call (e.g., 'createShortcut').
        *args: Arguments to pass to the JS function.

    Returns:
        Dictionary with the result or None if an error occurs.
    """
    status, message = enable_steam_cef()
    if not (status is True and message == "already_enabled"):
        if message == "restart_needed":
            logger.warning("Steam CEF API is available but requires Steam restart for full activation")
        elif message == "steam_not_found":
            logger.error("Could not find Steam directory to check CEF API")
        else:
            logger.error(f"Steam CEF API is unavailable or not ready: {message}")
        return None

    steam_debug_url = "http://localhost:8080/json"

    try:
        response = requests.get(steam_debug_url, timeout=2)
        response.raise_for_status()
        contexts = response.json()
        ws_url = next(
            (ctx['webSocketDebuggerUrl'] for ctx in contexts if ctx['title'] == 'SharedJSContext'),
            None
        )
        if not ws_url:
            logger.warning("SharedJSContext not found. Is Steam running with -cef-enable-remote-debugging?")
            return None
    except Exception as e:
        logger.warning(f"Failed to connect to Steam CEF API at {steam_debug_url}. Is Steam running? {e}")
        return None

    js_code = """
        async function createShortcut(name, exe, dir, icon, args) {
            const id = await SteamClient.Apps.AddShortcut(name, exe, dir, args);
            console.log("Shortcut created with ID:", id);
            await SteamClient.Apps.SetShortcutName(id, name);
            if (icon)
                await SteamClient.Apps.SetShortcutIcon(id, icon);
            if (args)
                await SteamClient.Apps.SetAppLaunchOptions(id, args);
            return { id };
        };

        async function setGrid(id, i, ext, image) {
            await SteamClient.Apps.SetCustomArtworkForApp(id, image, ext, i);
            return true;
        };

        async function removeShortcut(id) {
            await SteamClient.Apps.RemoveShortcut(+id);
            return true;
        };
    """
    try:
        ws = websocket.create_connection(ws_url, timeout=5)
        js_args = ", ".join(orjson.dumps(arg).decode('utf-8') for arg in args)
        expression = f"{js_code} {js_cmd}({js_args});"
        payload = {
            "id": random.randint(0, 32767),
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True
            }
        }

        ws.send(orjson.dumps(payload))
        response_str = ws.recv()
        ws.close()

        response_data = orjson.loads(response_str)
        if "error" in response_data:
            logger.error(f"JavaScript execution error in Steam: {response_data['error']['message']}")
            return None
        result = response_data.get('result', {}).get('result', {})
        if result.get('type') == 'object' and result.get('subtype') == 'error':
            logger.error(f"JavaScript execution error in Steam: {result.get('description')}")
            return None
        return result.get('value')
    except Exception as e:
        logger.error(f"WebSocket interaction error with Steam: {e}")
        return None


def _parse_exec_line(exec_line: str) -> tuple[str | None, str]:
    """Parse exec_line to extract executable path."""
    try:
        exe_path = extract_exec_target_path(exec_line)
        if not exe_path:
            logger.error("Failed to parse exec_line: %s", exec_line)
            return None, "Failed to parse executable command: no target path"
        return exe_path, ""
    except Exception as e:
        logger.error(f"Failed to parse exec_line: {exec_line}, error: {e}")
        return None, f"Failed to parse executable command: {e}"


def _create_launch_script(
    game_name: str,
    exe_path: str,
    portproton_dir: str,
    start_sh: list[str]
) -> tuple[str, str]:
    """Create launch script for the game."""
    steam_scripts_dir = os.path.join(portproton_dir, "steam_scripts")
    os.makedirs(steam_scripts_dir, exist_ok=True)

    safe_game_name = re.sub(r'[<>:"/\\|?*]', '_', game_name.strip())
    script_path = os.path.join(steam_scripts_dir, f"{safe_game_name}.sh")
    appimage_path = os.getenv("APPIMAGE", "").strip()
    flatpak_id = os.getenv("FLATPAK_ID", "").strip()
    if flatpak_id:
        launch_command = shlex.join(["flatpak", "run", flatpak_id, "--silent", exe_path])
    elif appimage_path and os.path.isfile(appimage_path):
        launch_command = shlex.join([appimage_path, "--silent", exe_path])
    else:
        launch_command = shlex.join(["portprotonqt", "--silent", exe_path])

    script_content = f"""#!/usr/bin/env bash
export LD_PRELOAD=
{launch_command} "$@"
"""
    try:
        if os.path.exists(script_path):
            with open(script_path, encoding="utf-8") as f:
                if f.read() == script_content:
                    logger.info(f"Launch script already exists: {script_path}")
                    return script_path, ""

        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script_content)
        os.chmod(script_path, 0o755)
        logger.info(f"Created launch script: {script_path}")
    except Exception as e:
        logger.error(f"Failed to create launch script {script_path}: {e}")
        return "", f"Failed to create launch script: {e}"

    return script_path, ""


def _generate_icon(exe_path: str, portproton_dir: str) -> str:
    """Generate thumbnail icon for the game."""
    safe_game_name = re.sub(r'[<>:"/\\|?*]', '_', os.path.basename(exe_path))
    generated_icon_path = os.path.join(portproton_dir, "data", "img", f"{safe_game_name}.png")

    try:
        img_dir = os.path.join(portproton_dir, "data", "img")
        os.makedirs(img_dir, exist_ok=True)

        if os.path.exists(generated_icon_path):
            logger.info(f"Reusing existing thumbnail: {generated_icon_path}")
        else:
            success = generate_thumbnail(exe_path, generated_icon_path, size=128, force_resize=True)
            if not success or not os.path.exists(generated_icon_path):
                logger.warning(f"Failed to generate thumbnail for {exe_path}")
                return ""
            else:
                logger.info(f"Generated thumbnail: {generated_icon_path}")
        return generated_icon_path
    except Exception as e:
        logger.error(f"Failed to generate thumbnail for {exe_path}: {e}")
        return ""


def _add_shortcut_via_vdf(
    game_name: str,
    script_path: str,
    icon_path: str,
    steam_shortcuts_path: Path,
    user_dir: Path
) -> tuple[int | None, str]:
    """Add shortcut via shortcuts.vdf (fallback method)."""
    backup_path = f"{steam_shortcuts_path}.backup"
    if os.path.exists(steam_shortcuts_path):
        try:
            shutil.copy2(steam_shortcuts_path, backup_path)
            logger.info(f"Created backup of shortcuts.vdf at {backup_path}")
        except Exception as e:
            logger.error(f"Failed to create backup of shortcuts.vdf: {e}")
            return None, f"Failed to create backup of shortcuts.vdf: {e}"

    unique_string = f"{script_path}{game_name}"
    baseid = zlib.crc32(unique_string.encode('utf-8')) & 0xffffffff
    appid = baseid | 0x80000000
    if appid > 0x7FFFFFFF:
        aidvdf = appid - 0x100000000
    else:
        aidvdf = appid

    shortcut = {
        "appid": aidvdf,
        "AppName": game_name,
        "Exe": f'"{script_path}"',
        "StartDir": f'"{os.path.dirname(script_path)}"',
        "icon": icon_path,
        "LaunchOptions": "",
        "IsHidden": 0,
        "AllowDesktopConfig": 1,
        "AllowOverlay": 1,
        "openvr": 0,
        "Devkit": 0,
        "DevkitGameID": "",
        "LastPlayTime": 0,
        "tags": {'0': 'PortProton'}
    }
    logger.info(f"Shortcut entry to be written: {shortcut}")

    try:
        if not os.path.exists(steam_shortcuts_path):
            os.makedirs(os.path.dirname(steam_shortcuts_path), exist_ok=True)
            open(steam_shortcuts_path, 'wb').close()

        try:
            if os.path.getsize(steam_shortcuts_path) > 0:
                with open(steam_shortcuts_path, 'rb') as f:
                    shortcuts_data = vdf.binary_load(f)
            else:
                shortcuts_data = {"shortcuts": {}}
        except Exception as load_err:
            logger.warning(f"Failed to load existing shortcuts.vdf, starting fresh: {load_err}")
            shortcuts_data = {"shortcuts": {}}

        shortcuts = shortcuts_data.get("shortcuts", {})
        for _key, entry in shortcuts.items():
            if entry.get("AppName") == game_name and entry.get("Exe") == f'"{script_path}"':
                logger.info(f"Game '{game_name}' already exists in Steam shortcuts")
                return None, f"Game '{game_name}' already exists in Steam"

        new_index = str(len(shortcuts))
        shortcuts[new_index] = shortcut

        with open(steam_shortcuts_path, 'wb') as f:
            vdf.binary_dump({"shortcuts": shortcuts}, f)
        logger.info(f"Game '{game_name}' successfully added to Steam with covers")
        return appid, ""
    except Exception as e:
        logger.error(f"Failed to update shortcuts.vdf: {e}")
        if os.path.exists(backup_path):
            try:
                shutil.copy2(backup_path, steam_shortcuts_path)
                logger.info("Restored shortcuts.vdf from backup due to update failure")
            except Exception as restore_err:
                logger.error(f"Failed to restore shortcuts.vdf from backup: {restore_err}")
        return None, f"Failed to update shortcuts.vdf: {e}"


def _download_covers(
    appid: int,
    steam_appid: tuple[int | None, str],
    grid_dir: str,
    was_api_used: bool
) -> None:
    """Download cover images for the game."""
    source_appid, game_name = steam_appid
    cover_types = [
        ("p.jpg", "library_600x900_2x.jpg"),
        ("_hero.jpg", "library_hero.jpg"),
        ("_logo.png", "logo.png"),
        (".jpg", "header.jpg")
    ]

    def on_cover_download(result_path: str | None, steam_name: str, index: int) -> None:
        try:
            if result_path and os.path.exists(result_path):
                logger.info(f"Downloaded cover {steam_name} to {result_path}")
                if was_api_used:
                    try:
                        with open(result_path, 'rb') as f:
                            img_b64 = base64.b64encode(f.read()).decode('utf-8')
                        logger.info(f"Applying cover type '{steam_name}' via API for AppID {appid}")
                        ext = Path(result_path).suffix.lstrip('.')
                        call_steam_api("setGrid", appid, index, ext, img_b64)
                    except Exception as e:
                        logger.error(f"Failed to apply cover '{steam_name}' via API: {e}")
            else:
                logger.warning(f"Failed to download cover {steam_name} for appid {steam_appid}")
        except Exception as e:
            logger.error(f"Failed to process cover {steam_name} for appid {steam_appid}: {e}")

    def download_sgdb(index: int, cover_file: str, steam_name: str) -> None:
        image_type = ("grids", "heroes", "logos", "hgrids")[index]

        def on_url(url: str) -> None:
            if not url.startswith("https://cdn2.steamgriddb.com/"):
                on_cover_download(None, steam_name, index)
                return
            extension = Path(urlsplit(url).path).suffix.lower()
            if extension not in (".png", ".jpg", ".jpeg"):
                logger.warning("Unsupported SGDB artwork format: %s", extension)
                on_cover_download(None, steam_name, index)
                return
            destination = str(Path(cover_file).with_suffix(extension))
            downloader.download_async(
                url, destination, timeout=5,
                callback=partial(on_cover_download, steam_name=steam_name, index=index),
            )

        fetch_sgdb_cover_async(game_name, on_url, image_type)

    def on_steam_download(
        index: int, steam_name: str, cover_file: str, result: str | None
    ) -> None:
        if result:
            on_cover_download(result, steam_name, index)
        else:
            download_sgdb(index, cover_file, steam_name)

    for i, (suffix, steam_name) in enumerate(cover_types):
        cover_file = os.path.join(grid_dir, f"{appid}{suffix}")
        if not source_appid:
            download_sgdb(i, cover_file, steam_name)
            continue
        cover_url = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{source_appid}/{steam_name}"
        downloader.download_async(
            cover_url,
            cover_file,
            timeout=5,
            callback=partial(on_steam_download, i, steam_name, cover_file)
        )


def add_to_steam(
    game_name: str, exec_line: str, cover_path: str, icon_source: str | None = None
) -> tuple[bool, str]:
    """
    Add a non-Steam game to Steam via shortcuts.vdf with PortProton tag,
    and download Steam Grid covers with correct sizes and names.
    """
    if not exec_line or not exec_line.strip():
        logger.error("Invalid exec_line: empty or whitespace")
        return (False, "Executable command is empty or invalid")

    exe_path, error = _parse_exec_line(exec_line)
    if not exe_path:
        return (False, error)

    is_store_uri = exe_path.startswith(("gog://launch/", "egs://launch/"))
    if not is_store_uri and not os.path.exists(exe_path):
        logger.error(f"Executable not found: {exe_path}")
        return (False, f"Executable file not found: {exe_path}")

    portproton_dir = get_portproton_location()
    start_sh = get_portproton_start_command()
    if not portproton_dir or not start_sh:
        logger.error("PortProton directory not found")
        return (False, "PortProton directory not found")

    script_path, error = _create_launch_script(game_name, exe_path, portproton_dir, start_sh)
    if error:
        return (False, error)

    icon_source = get_custom_icon_path(exe_path) or icon_source or (None if is_store_uri else exe_path)
    icon_path = _generate_icon(icon_source, portproton_dir) if icon_source else ""

    steam_home = get_steam_home()
    if not steam_home:
        logger.error("Steam home directory not found")
        return (False, "Steam directory not found")

    userdata_dir = steam_home / "userdata"
    selected_account = game_config.get_steam_account_id()
    if selected_account == "all":
        steam_users = get_steam_users(steam_home)
        user_dirs = [
            userdata_dir / str(convert_steam_id(int(user_id)))
            for user_id in steam_users
        ]
        if not user_dirs:
            logger.error("Failed to retrieve Steam user IDs")
            return (False, "Failed to get Steam user IDs")
    else:
        last_user = get_last_steam_user(steam_home)
        if not last_user or 'SteamID' not in last_user:
            logger.error("Failed to retrieve Steam user ID")
            return (False, "Failed to get Steam user ID")
        unsigned_id = convert_steam_id(last_user['SteamID'])
        user_dirs = [userdata_dir / str(unsigned_id)]

    user_dir = user_dirs[0]
    steam_shortcuts_path = user_dir / "config" / "shortcuts.vdf"
    grid_dir = user_dir / "config" / "grid"
    os.makedirs(grid_dir, exist_ok=True)

    appid = None
    was_api_used = False

    api_response = None
    if selected_account != "all":
        logger.info("Attempting to add shortcut via Steam CEF API")
        api_response = call_steam_api(
            "createShortcut",
            game_name,
            script_path,
            str(Path(script_path).parent),
            icon_path,
            ""
        )

    if api_response and isinstance(api_response, dict) and 'id' in api_response:
        appid = api_response['id']
        was_api_used = True
        logger.info(f"Shortcut successfully added via API. AppID: {appid}")
    else:
        logger.warning("Failed to add shortcut via API. Falling back to shortcuts.vdf")
        for user_dir in user_dirs:
            steam_shortcuts_path = user_dir / "config" / "shortcuts.vdf"
            appid, error = _add_shortcut_via_vdf(
                game_name, script_path, icon_path, steam_shortcuts_path, user_dir
            )
            if error:
                return (False, error)

    if not appid:
        return (False, "Failed to create shortcut using any method")

    if ui_config.get_economy_mode():
        logger.info("Economy mode enabled: skipping cover download for shortcut %s", game_name)
        if was_api_used:
            return (True, "Game added to Steam via CEF API")
        return (True, "Game added to Steam. Please restart Steam for changes to take effect.")

    steam_appid = None

    def on_game_info(game_info: dict) -> None:
        nonlocal steam_appid
        steam_appid = game_info.get("appid")
        if not steam_appid or not isinstance(steam_appid, int):
            _download_covers(appid, (None, game_name), str(grid_dir), was_api_used)
            return
        logger.info(f"Found Steam AppID {steam_appid} for cover download")
        _download_covers(appid, (steam_appid, game_name), str(grid_dir), was_api_used)

    get_steam_game_info_async(game_name, exec_line, on_game_info)

    if was_api_used:
        return (True, "Game added to Steam via CEF API")
    else:
        return (True, "Game added to Steam. Please restart Steam for changes to take effect.")


def _delete_cover_files(grid_dir: str, appid: int) -> None:
    """Delete cover files for a game."""
    cover_files = [
        os.path.join(grid_dir, f"{appid}{suffix}{extension}")
        for suffix in ("", "p", "_hero", "_logo")
        for extension in (".jpg", ".png", ".jpeg")
    ]
    for cover_file in cover_files:
        if os.path.exists(cover_file):
            try:
                os.remove(cover_file)
                logger.info(f"Deleted cover file: {cover_file}")
            except Exception as e:
                logger.error(f"Failed to delete cover file {cover_file}: {e}")
        else:
            logger.info(f"Cover file not found: {cover_file}")


def remove_from_steam(game_name: str, exec_line: str) -> tuple[bool, str]:
    """Remove a non-Steam game from Steam by deleting its entry from shortcuts.vdf."""
    if not game_name or not game_name.strip():
        logger.error("Invalid game_name: empty or whitespace")
        return (False, "Game name is empty or invalid")
    if not exec_line or not exec_line.strip():
        logger.error("Invalid exec_line: empty or whitespace")
        return (False, "Executable command is empty or invalid")

    portproton_dir = get_portproton_location()
    if not portproton_dir:
        logger.error("PortProton directory not found")
        return (False, "PortProton directory not found")

    safe_game_name = re.sub(r'[<>:"/\\|?*]', '_', game_name.strip())
    script_path = os.path.join(portproton_dir, "steam_scripts", f"{safe_game_name}.sh")

    steam_home = get_steam_home()
    if not steam_home:
        logger.error("Steam home directory not found")
        return (False, "Steam directory not found")

    last_user = get_last_steam_user(steam_home)
    if not last_user or 'SteamID' not in last_user:
        logger.error("Failed to retrieve Steam user ID")
        return (False, "Failed to get Steam user ID")

    userdata_dir = steam_home / "userdata"
    user_id = last_user['SteamID']
    unsigned_id = convert_steam_id(user_id)
    user_dir = userdata_dir / str(unsigned_id)

    steam_shortcuts_path = os.path.join(user_dir, "config", "shortcuts.vdf")
    grid_dir = os.path.join(user_dir, "config", "grid")

    if not os.path.exists(steam_shortcuts_path):
        logger.info(f"shortcuts.vdf not found at {steam_shortcuts_path}")
        return (False, f"Game '{game_name}' not found in Steam")

    appid = None

    try:
        if os.path.getsize(steam_shortcuts_path) > 0:
            with open(steam_shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
        else:
            shortcuts_data = {"shortcuts": {}}
    except Exception as load_err:
        logger.error(f"Failed to load shortcuts.vdf: {load_err}")
        return (False, f"Failed to load shortcuts.vdf: {load_err}")

    shortcuts = shortcuts_data.get("shortcuts", {})
    new_shortcuts = {}
    index = 0

    for _key, entry in shortcuts.items():
        if entry.get("AppName") == game_name and entry.get("Exe") == f'"{script_path}"':
            appid = convert_steam_id(int(entry.get("appid")))
            logger.info(f"Found matching shortcut for '{game_name}' to remove")
            continue
        new_shortcuts[str(index)] = entry
        index += 1

    if not appid:
        logger.info(f"Game '{game_name}' not found in Steam shortcuts")
        return (False, f"Game '{game_name}' not found in Steam")

    api_response = call_steam_api("removeShortcut", appid)
    was_api_used = api_response is not None

    if was_api_used:
        logger.info(f"Shortcut for AppID {appid} successfully removed via API")
    else:
        logger.warning("Failed to remove shortcut via API. Falling back to editing shortcuts.vdf")

        backup_path = f"{steam_shortcuts_path}.backup"
        try:
            shutil.copy2(steam_shortcuts_path, backup_path)
            logger.info(f"Created backup of shortcuts.vdf at {backup_path}")
        except Exception as e:
            logger.error(f"Failed to create backup of shortcuts.vdf: {e}")
            return (False, f"Failed to create backup of shortcuts.vdf: {e}")

        try:
            with open(steam_shortcuts_path, 'wb') as f:
                vdf.binary_dump({"shortcuts": new_shortcuts}, f)
            logger.info(f"Successfully updated shortcuts.vdf, removed '{game_name}'")
        except Exception as e:
            logger.error(f"Failed to update shortcuts.vdf: {e}")
            if os.path.exists(backup_path):
                try:
                    shutil.copy2(backup_path, steam_shortcuts_path)
                    logger.info("Restored shortcuts.vdf from backup due to update failure")
                except Exception as restore_err:
                    logger.error(f"Failed to restore shortcuts.vdf from backup: {restore_err}")
            return (False, f"Failed to update shortcuts.vdf: {e}")

    _delete_cover_files(grid_dir, appid)

    if os.path.exists(script_path):
        try:
            os.remove(script_path)
            logger.info(f"Deleted steam script: {script_path}")
        except Exception as e:
            logger.error(f"Failed to delete steam script {script_path}: {e}")
    else:
        logger.info(f"Steam script not found: {script_path}")

    logger.info(f"Game '{game_name}' successfully removed from Steam")
    if was_api_used:
        return (True, f"Game '{game_name}' removed from Steam")
    else:
        return (True, f"Game '{game_name}' removed from Steam. Please restart Steam for changes to take effect.")


def is_game_in_steam(game_name: str) -> bool:
    """Check if a game is already in Steam shortcuts."""
    steam_home = get_steam_home()
    if steam_home is None:
        logger.warning("Steam home directory not found")
        return False

    try:
        last_user = get_last_steam_user(steam_home)
        if not last_user or 'SteamID' not in last_user:
            logger.warning("No valid Steam user found")
            return False

        user_id = last_user['SteamID']
        unsigned_id = convert_steam_id(user_id)
        steam_shortcuts_path = os.path.join(
            str(steam_home), "userdata", str(unsigned_id), "config", "shortcuts.vdf"
        )
        if not os.path.exists(steam_shortcuts_path):
            logger.warning(f"Shortcuts file not found at {steam_shortcuts_path}")
            return False

        shortcuts_data = safe_vdf_load(steam_shortcuts_path)
        shortcuts = shortcuts_data.get("shortcuts", {})
        for _key, entry in shortcuts.items():
            if entry.get("AppName") == game_name:
                return True
    except Exception as e:
        logger.error(f"Failed to check if game {game_name} is in Steam: {e}")
    return False
