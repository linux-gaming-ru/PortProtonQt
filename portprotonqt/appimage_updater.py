"""AppImage self-update support."""
import errno
import os
import platform
import pty
import re
import select
import shutil
import subprocess
import time
from pathlib import Path

import requests
from PySide6.QtCore import QThread, Signal

from portprotonqt.downloader import get_requests_session
from portprotonqt.config import ui_config
from portprotonqt.config.base import XDG_DATA_HOME
from portprotonqt.logger import get_logger

logger = get_logger(__name__)

APPIMAGEUPDATETOOL_URL = (
    "https://github.com/pkgforge-dev/AppImageUpdate/releases/latest/download/"
    "appimageupdate-{arch}-linux"
)
APPIMAGEUPDATETOOL_TIMEOUT = 60
APPIMAGE_UPDATE_CHECK_TIMEOUT = 120
APPIMAGE_UPDATE_TIMEOUT = 900
APPIMAGE_UPDATE_START_DELAY_MS = 5000
EXECUTABLE_MODE = 0o755
GITHUB_UPDATE_INFO = (
    "gh-releases-zsync|linux-gaming-ru|PortProtonQt|latest|*x86_64.AppImage.zsync"
)
CHANGELOG_URL = (
    "https://git.linux-gaming.ru/Linux-Gaming/PortProtonQt/raw/branch/main/"
    "CHANGELOG.md"
)
CHANGELOG_GITHUB_URL = (
    "https://raw.githubusercontent.com/linux-gaming-ru/PortProtonQt/refs/heads/main/"
    "CHANGELOG.md"
)
CHANGELOG_TIMEOUT = 10
CHANGELOG_MAX_CHARS = 120000
TOOL_OUTPUT_CHUNK_SIZE = 4096
DOWN_ARROW = "\u2193"
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
PROGRESS_RE = re.compile(
    rf"(?P<percent>\d{{1,3}})%\s+{DOWN_ARROW}\s+"
    r"(?P<done>[^/\r\n]+)/(?P<total>[^/\r\n]+)"
)


def _appimage_path() -> str:
    return os.environ.get("APPIMAGE", "")


def _get_appimage_arch() -> str:
    return os.environ.get("APPIMAGE_ARCH") or platform.machine()


def _cached_tool_path() -> Path:
    return XDG_DATA_HOME / "PortProtonQt" / "bin" / "appimageupdatetool"


def _get_appimageupdatetool_url() -> str:
    default_url = APPIMAGEUPDATETOOL_URL.format(arch=_get_appimage_arch())
    return os.environ.get("APPIMAGEUPDATETOOL_LINK", default_url)


def _find_appimageupdatetool() -> str | None:
    for tool_name in ("appimageupdatetool", "appimageupdate"):
        tool_path = shutil.which(tool_name)
        if tool_path:
            return tool_path

    cached_tool = _cached_tool_path()
    if cached_tool.exists() and os.access(cached_tool, os.X_OK):
        return str(cached_tool)
    return None


def _download_appimageupdatetool() -> str | None:
    tool_path = _cached_tool_path()
    tmp_path = tool_path.with_suffix(".part")
    try:
        tool_path.parent.mkdir(parents=True, exist_ok=True)
        session = get_requests_session()
        with session.get(
            _get_appimageupdatetool_url(),
            timeout=APPIMAGEUPDATETOOL_TIMEOUT,
        ) as response:
            response.raise_for_status()
            tmp_path.write_bytes(response.content)
        tmp_path.chmod(EXECUTABLE_MODE)
        tmp_path.replace(tool_path)
        return str(tool_path)
    except (OSError, requests.RequestException) as error:
        logger.warning("Failed to download appimageupdatetool: %s", error)
        return None
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _ensure_appimageupdatetool() -> str | None:
    return _find_appimageupdatetool() or _download_appimageupdatetool()


def _run_appimageupdatetool(
    args: list[str],
    timeout: int,
) -> subprocess.CompletedProcess[str] | None:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as error:
        logger.warning("Failed to run appimageupdatetool: %s", error)
        return None
    if result.stdout:
        logger.debug("appimageupdatetool stdout: %s", result.stdout.strip())
    if result.stderr:
        logger.debug("appimageupdatetool stderr: %s", result.stderr.strip())
    return result


def _download_changelog() -> str:
    from portprotonqt.portproton_api import get_user_conf_setting

    session = get_requests_session()
    url = (
        CHANGELOG_URL
        if get_user_conf_setting("MIRROR") == "CLOUD"
        else CHANGELOG_GITHUB_URL
    )
    try:
        with session.get(url, timeout=CHANGELOG_TIMEOUT) as response:
            response.raise_for_status()
            data = response.content[:CHANGELOG_MAX_CHARS]
            return data.decode("utf-8", errors="replace")
    except (OSError, requests.RequestException) as error:
        logger.debug("Failed to download changelog from %s: %s", url, error)
        return ""


def _extract_latest_version_changelog(changelog: str, current_version: str = "") -> str:
    version_header = re.compile(r"^##\s+\[([^\]]+)\].*$", re.MULTILINE)
    matches = list(version_header.finditer(changelog))
    if not matches:
        return changelog

    if current_version:
        version_idx = len(matches)
        for i, m in enumerate(matches):
            ver = m.group(1)
            if ver.startswith("["):
                ver = ver[1:]
            if ver == current_version:
                version_idx = i
                break
    else:
        version_idx = len(matches)

    end = len(changelog)
    result_parts = []
    for m in matches[:version_idx]:
        ver = m.group(1)
        if ver.startswith("["):
            ver = ver[1:]
        if ver == "Unreleased":
            continue
        next_match_pos = end
        for later in matches[matches.index(m) + 1:]:
            if later.start() > m.start():
                next_match_pos = later.start()
                break
        result_parts.append(changelog[m.start():next_match_pos].strip())

    return "\n\n".join(result_parts)


def _clean_tool_output(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text).strip()


def _parse_progress(text: str) -> tuple[int, str] | None:
    match = PROGRESS_RE.search(text)
    if not match:
        return None
    percent = min(int(match.group("percent")), 100)
    message = f"{percent}% {DOWN_ARROW} {match.group('done').strip()}/{match.group('total').strip()}"
    return percent, message


class AppImageUpdateWorker(QThread):
    """Check and update the running AppImage in a worker thread."""

    update_available = Signal(str, str)
    update_finished = Signal(bool)
    update_output = Signal(str)
    update_progress = Signal(int, str)

    def __init__(self, action: str = "check", update_info: str = "") -> None:
        super().__init__()
        self.action = action
        self.update_info = update_info

    def _tool_args(self, tool_path: str, appimage_path: str, action: str) -> list[str]:
        args = [tool_path, action]
        if self.update_info:
            args.extend(["-u", self.update_info])
        args.append(appimage_path)
        return args

    def _get_changelog(self) -> str:
        from portprotonqt.app import __app_version__
        return _extract_latest_version_changelog(
            _download_changelog(), __app_version__
        )

    def _emit_tool_output(self, text: str) -> None:
        line = _clean_tool_output(text)
        if not line:
            return
        progress = _parse_progress(line)
        if progress is not None:
            percent, message = progress
            self.update_progress.emit(percent, message)
            return
        self.update_output.emit(line)

    def _read_pty_output(self, master_fd: int, process: subprocess.Popen[bytes]) -> None:
        buffer = ""
        start_time = time.monotonic()
        while process.poll() is None:
            if time.monotonic() - start_time > APPIMAGE_UPDATE_TIMEOUT:
                process.kill()
                logger.warning("AppImage update timed out")
                return
            ready, _, _ = select.select([master_fd], [], [], 0.2)
            if not ready:
                continue
            try:
                data = os.read(master_fd, TOOL_OUTPUT_CHUNK_SIZE)
            except OSError as error:
                if error.errno == errno.EIO:
                    break
                raise
            if not data:
                break
            buffer = self._process_tool_chunk(buffer, data)
        if buffer:
            self._emit_tool_output(buffer)

    def _process_tool_chunk(self, buffer: str, data: bytes) -> str:
        buffer += data.decode("utf-8", errors="replace")
        parts = re.split(r"[\r\n]", buffer)
        for part in parts[:-1]:
            self._emit_tool_output(part)
        return parts[-1]

    def _run_tool_with_progress(self, args: list[str]) -> bool:
        master_fd = -1
        try:
            master_fd, slave_fd = pty.openpty()
            process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
            )
            os.close(slave_fd)
        except OSError as error:
            if master_fd >= 0:
                os.close(master_fd)
            logger.warning("Failed to run appimageupdatetool: %s", error)
            return False

        try:
            self._read_pty_output(master_fd, process)
            return process.wait(timeout=1) == 0
        except (OSError, subprocess.TimeoutExpired) as error:
            process.kill()
            logger.warning("Failed to read appimageupdatetool output: %s", error)
            return False
        finally:
            os.close(master_fd)

    def _run_update(self, tool_path: str, appimage_path: str) -> None:
        success = self._run_tool_with_progress(
            self._tool_args(tool_path, appimage_path, "-Or"),
        )
        self.update_finished.emit(success)

    def _check_for_update(
        self,
        tool_path: str,
        appimage_path: str,
        update_info: str,
    ) -> subprocess.CompletedProcess[str] | None:
        previous_info = self.update_info
        self.update_info = update_info
        result = _run_appimageupdatetool(
            self._tool_args(tool_path, appimage_path, "-j"),
            APPIMAGE_UPDATE_CHECK_TIMEOUT,
        )
        self.update_info = previous_info
        return result

    def run(self) -> None:
        from portprotonqt.portproton_api import get_user_conf_setting

        appimage_path = _appimage_path()
        if not ui_config.get_auto_appimage_updates() or not appimage_path:
            return
        if not os.access(appimage_path, os.W_OK):
            logger.info("AppImage is not writable, skipping self-update")
            return

        tool_path = _ensure_appimageupdatetool()
        if not tool_path:
            return

        if self.action == "update":
            self._run_update(tool_path, appimage_path)
            return

        selected_info = (
            "" if get_user_conf_setting("MIRROR") == "CLOUD" else GITHUB_UPDATE_INFO
        )
        check_code = self._check_for_update(tool_path, appimage_path, selected_info)

        if check_code is None or check_code.returncode != 1:
            return

        logger.info("AppImage update is available")
        self.update_available.emit(self._get_changelog(), selected_info)
