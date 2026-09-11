import os
import hashlib
import shutil
from datetime import datetime, timedelta
from babel.dates import format_timedelta, format_date
from babel.numbers import format_decimal
from portprotonqt.config import ui_config
from portprotonqt.localization import _, get_system_locale
from portprotonqt.logger import get_logger

logger = get_logger(__name__)

_migrated = False


# Remove after the legacy statistics migration period.
def _migrate_last_launch_file(data_home: str) -> str:
    """Migrate last_launch from old cache dir to XDG_DATA_HOME."""
    global _migrated
    if _migrated:
        return ""
    _migrated = True
    new_path = os.path.join(data_home, "PortProtonQt", "last_launch")
    cache_home = os.getenv("XDG_CACHE_HOME", os.path.join(os.path.expanduser("~"), ".cache"))
    old_path = os.path.join(cache_home, "PortProtonQt", "last_launch")
    if not os.path.exists(old_path) or os.path.exists(new_path):
        return ""
    try:
        os.makedirs(os.path.dirname(new_path), exist_ok=True)
        shutil.move(old_path, new_path)
        logger.info("Migrated last_launch from %s to %s", old_path, new_path)
        return old_path
    except OSError as e:
        logger.warning("Failed to migrate last_launch: %s", e)
        return ""


def get_last_launch_path():
    """Return path to last_launch state file."""
    data_home = os.getenv("XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share"))
    _migrate_last_launch_file(data_home)
    return os.path.join(data_home, "PortProtonQt", "last_launch")

_stats_migrated = False


# Remove after the legacy statistics migration period.
def _migrate_statistics_file(data_home: str) -> str:
    """Migrate statistics from old cache/tmp dir to XDG_DATA_HOME."""
    global _stats_migrated
    if _stats_migrated:
        return ""
    _stats_migrated = True
    new_path = os.path.join(data_home, "PortProtonQt", "statistics")
    if os.path.exists(new_path):
        return ""
    from portprotonqt.config import get_portproton_location
    portproton_location = get_portproton_location()
    if not portproton_location:
        return ""
    old_path = os.path.join(portproton_location, "data", "tmp", "statistics")
    if not os.path.exists(old_path):
        return ""
    try:
        os.makedirs(os.path.dirname(new_path), exist_ok=True)
        playtime_data = {}
        with open(old_path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                parts = line.strip().split()
                if len(parts) < 2:
                    continue
                exe_path = parts[0]
                if "steamapps" in exe_path.lower():
                    continue
                sha = parts[1] if (len(parts) > 1 and len(parts[1]) == 64) else "-"
                seconds = next((int(t) for t in parts[1:] if t.isdigit()), None)
                if seconds is not None:
                    playtime_data[exe_path] = (sha, seconds)
        with open(new_path, "w", encoding="utf-8") as f:
            for path, (sha, seconds) in playtime_data.items():
                f.write(f"{path} {sha} {seconds}\n")
        logger.info("Migrated statistics from %s to %s", old_path, new_path)
        return old_path
    except Exception as e:
        logger.warning("Failed to migrate statistics: %s", e)
        return ""


def get_statistics_path() -> str:
    """Return path to statistics state file."""
    data_home = os.getenv("XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share"))
    _migrate_statistics_file(data_home)
    return os.path.join(data_home, "PortProtonQt", "statistics")

def _parse_last_launch_line(line: str) -> tuple[str, str] | None:
    parts = line.strip().rsplit(maxsplit=1)
    if len(parts) != 2:
        return None
    return parts[0], parts[1]

def save_last_launch(exe_name, launch_time):
    """
    Save launch time for exe.
    File format: <exe_name> <isoformatted_time>
    """
    file_path = get_last_launch_path()
    data = {}
    if os.path.exists(file_path):
        with open(file_path, encoding="utf-8") as f:
            for line in f:
                parsed_line = _parse_last_launch_line(line)
                if parsed_line:
                    data[parsed_line[0]] = parsed_line[1]
    data[exe_name] = launch_time.isoformat()
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        for key, iso_time in data.items():
            f.write(f"{key} {iso_time}\n")


def remove_last_launch(exe_name: str) -> None:
    """Remove the last launch entry for an executable."""
    file_path = get_last_launch_path()
    if not exe_name or not os.path.exists(file_path):
        return
    try:
        with open(file_path, encoding="utf-8") as f:
            lines = f.readlines()
        kept_lines = []
        for line in lines:
            parsed_line = _parse_last_launch_line(line)
            if parsed_line and parsed_line[0] == exe_name:
                continue
            kept_lines.append(line)
        if len(kept_lines) == len(lines):
            return
        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(kept_lines)
    except OSError as e:
        logger.warning("Failed to remove last launch for %s: %s", exe_name, e)


def save_playtime(
    exe_path: str, additional_seconds: int, exact_path: bool = False
) -> None:
    """Save and accumulate playtime for the executable."""
    if not exe_path or additional_seconds <= 0 or "steamapps" in exe_path.lower():
        return
    file_path = get_statistics_path()
    target_path = os.path.normpath(exe_path)
    target_sha = ""
    try:
        sha = hashlib.sha256()
        with open(target_path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                sha.update(chunk)
        target_sha = sha.hexdigest()
    except OSError:
        pass

    entries: list[str] = []
    updated = False
    lines: list[str] = []
    if os.path.exists(file_path):
        try:
            with open(file_path, encoding="utf-8") as f:
                lines = f.readlines()
        except OSError as e:
            logger.warning("Failed to read statistics: %s", e)

    for line in lines:
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        seconds = next((int(t) for t in parts[1:] if t.isdigit()), None)
        if seconds is None:
            continue
        stat_path = os.path.normpath(parts[0].replace("#@_@#", " "))
        stat_sha = parts[1] if len(parts[1]) == 64 else ""
        hash_matches = not exact_path and target_sha and stat_sha == target_sha
        if (hash_matches or stat_path == target_path) and not updated:
            entries.append(f"{target_path.replace(' ', '#@_@#')} {target_sha or stat_sha} {seconds + additional_seconds}\n")
            updated = True
        else:
            entries.append(line)

    if not updated:
        entries.append(f"{target_path.replace(' ', '#@_@#')} {target_sha} {additional_seconds}\n")

    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(entries)
    except OSError as e:
        logger.error("Failed to save playtime: %s", e)

def format_last_launch(launch_time):
    """
    Format launch time using Babel.

    For detail_level "detailed" returns relative format with "ago" added
    (e.g., "2 min. ago"). If time is less than a minute - returns translated string.
    For "brief" – date in "day month year" format (e.g., "April 1, 2023")
    based on system locale.
    """
    detail_level = ui_config.get_time_detail_level() or "detailed"
    system_locale = get_system_locale()
    if detail_level == "detailed":
        # Calculate delta as launch_time - datetime.now() to get negative value for elapsed time.
        delta = launch_time - datetime.now()
        if abs(delta.total_seconds()) < 60:
            return _("just now")
        return format_timedelta(delta, locale=system_locale, granularity='second', format='short', add_direction=True)
    else:
        return format_date(launch_time, format="d MMMM yyyy", locale=system_locale)

def get_last_launch(exe_name):
    """
    Read last launch time for given exe from cache file.
    Return launch time in required format or translated "Never" string.
    """
    file_path = get_last_launch_path()
    if not os.path.exists(file_path):
        return _("Never")
    with open(file_path, encoding="utf-8") as f:
        for line in f:
            parsed_line = _parse_last_launch_line(line)
            if parsed_line and parsed_line[0] == exe_name:
                iso_time = parsed_line[1]
                launch_time = datetime.fromisoformat(iso_time)
                return format_last_launch(launch_time)
    return _("Never")

def parse_playtime_file(file_path):
    """
    Parse playtime data file.

    Line format in file:
      <full exe path> <hash> <playtime_seconds> <platform> <build>

    Return dictionary like:
      {
         '<exe_path>': playtime_seconds (int),
         ...
      }
    """
    playtime_data = {}
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return playtime_data

    with open(file_path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            parts = line.strip().split()
            if len(parts) < 3:
                continue
            exe_path = parts[0]
            # Find playtime: first numeric value after exe_path
            # Format: <exe_path> <hash> <playtime_seconds> <platform> ...
            # Hash is 64 hex chars, playtime is digits only
            for i in range(1, len(parts)):
                if parts[i].isdigit():
                    playtime_data[exe_path] = int(parts[i])
                    break
    return playtime_data


def get_playtime_for_exe(
    file_path: str, exe_path: str, exact_path: bool = False
) -> int | None:
    """Return playtime for the target executable from statistics file."""
    if not exe_path or not os.path.exists(file_path):
        return None

    target_path = os.path.normpath(exe_path)
    target_name = os.path.splitext(os.path.basename(target_path))[0].lower()
    target_sha = None
    try:
        sha = hashlib.sha256()
        with open(target_path, "rb") as exe_file:
            for chunk in iter(lambda: exe_file.read(65536), b""):
                sha.update(chunk)
        target_sha = sha.hexdigest()
    except OSError:
        target_sha = None

    sha_seconds = None
    exact_seconds = None
    fallback_seconds = None

    with open(file_path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            parts = line.strip().split()
            if len(parts) < 3:
                continue

            stat_path = os.path.normpath(parts[0].replace("#@_@#", " "))
            stat_sha = parts[1]
            try:
                seconds = int(parts[2])
            except ValueError:
                continue

            if not exact_path and target_sha and stat_sha == target_sha:
                sha_seconds = seconds
                continue

            if stat_path == target_path:
                exact_seconds = seconds
                continue

            stat_name = os.path.splitext(os.path.basename(stat_path))[0].lower()
            if not exact_path and stat_name == target_name:
                fallback_seconds = seconds

    if sha_seconds is not None:
        return sha_seconds
    if exact_seconds is not None:
        return exact_seconds
    return fallback_seconds

def format_playtime(seconds):
    """
    Convert time in seconds to formatted string using Babel.

    For "detailed" outputs full time breakdown, without rounding
    (e.g., "1 h 1 min 15 sec").

    For "brief":
      - if time is less than hour, output exact time with seconds (e.g., "9 min 28 sec"),
      - if more than hour – only hours (e.g., "3 h").

    For "steam" outputs hours with one decimal digit and ignores seconds.
    """
    detail_level = ui_config.get_time_detail_level() or "detailed"
    system_locale = get_system_locale()
    seconds = int(seconds)

    if detail_level == "detailed":
        days, rem = divmod(seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, secs = divmod(rem, 60)
        parts = []
        if days > 0:
            parts.append(f"{days} " + _("d."))
        if hours > 0:
            parts.append(f"{hours} " + _("h."))
        if minutes > 0:
            parts.append(f"{minutes} " + _("min."))
        if secs > 0 or not parts:
            parts.append(f"{secs} " + _("sec."))
        return " ".join(parts)
    elif detail_level == "steam":
        minutes = seconds // 60
        hours = minutes / 60
        formatted_hours = format_decimal(hours, format="#,##0.#", locale=system_locale)
        return f"{formatted_hours} " + _("h.")
    else:
        # Brief mode
        if seconds < 3600:
            minutes, secs = divmod(seconds, 60)
            parts = []
            if minutes > 0:
                parts.append(f"{minutes} " + _("min."))
            if secs > 0 or not parts:
                parts.append(f"{secs} " + _("sec."))
            return " ".join(parts)
        else:
            hours = seconds // 3600
            return format_timedelta(timedelta(hours=hours), locale=system_locale, granularity='hour', format='short')

def get_last_launch_timestamp(exe_name):
    """
    Return last launch timestamp for given exe.
    If no record, return 0.
    """
    file_path = get_last_launch_path()
    if not os.path.exists(file_path):
        return 0
    with open(file_path, encoding="utf-8") as f:
        for line in f:
            parsed_line = _parse_last_launch_line(line)
            if parsed_line and parsed_line[0] == exe_name:
                iso_time = parsed_line[1]
                dt = datetime.fromisoformat(iso_time)
                return dt.timestamp()
    return 0
