"""Native macOS Wine launching; Linux PortProton scripts are not used."""

import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import tempfile

from portprotonqt.logger import get_logger

logger = get_logger(__name__)
MACOS_WINE_METADATA_URL = (
    "https://git.linux-gaming.ru/Boria138/PortProton-Wine-Metadata/"
    "raw/branch/main/macos_wine_metadata.json"
)
WINE_TOOLS = {
    "--winecfg": "winecfg", "--winereg": "regedit", "--winecmd": "cmd",
    "--winefile": "winefile", "--wine_uninstaller": "uninstaller",
}


def data_root() -> Path:
    """Respect explicit data paths, otherwise use macOS Application Support."""
    explicit = os.environ.get("PORT_DATA_PATH")
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / "Library" / "Application Support" / "PortProtonQt"


def version_directory(root: Path, name: str) -> Path:
    """Keep catalog version names inside the managed distribution directory."""
    if not name or name in (".", "..") or Path(name).name != name:
        raise ValueError(f"Invalid Wine version name: {name}")
    destination = root / "data" / "dist" / name
    if not destination.resolve().is_relative_to((root / "data" / "dist").resolve()):
        raise ValueError(f"Wine version escapes distribution directory: {name}")
    return destination


def validate_catalog(metadata: object) -> None:
    """Reject unsafe remote names before they become download paths."""
    if not isinstance(metadata, dict):
        raise ValueError("Invalid macOS Wine catalog")
    for entries in metadata.values():
        if not isinstance(entries, list):
            raise ValueError("Invalid macOS Wine catalog entries")
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                raise ValueError("Invalid macOS Wine version")
            version_directory(data_root(), entry["name"])
            if not isinstance(entry.get("url"), str) or not entry["url"].startswith("https://"):
                raise ValueError("macOS Wine downloads require HTTPS")


def find_wine(version: Path) -> Path | None:
    """Find Wine in supported plain, application and Wine wrapper layouts."""
    candidates = [version / "bin" / "wine", version / "bin" / "wine64"]
    candidates.extend(version.glob("Contents/Resources/wine/bin/wine*"))
    candidates.extend(version.glob("*.app/Contents/Resources/wine/bin/wine*"))
    candidates.extend(version.glob("*.app/Contents/Resources/wine*/bin/wine64"))
    candidates.extend(version.glob("wswine.bundle/bin/wine*"))
    candidates.extend(version.glob("*/bin/wine*"))
    candidates.extend(version.glob("*.app/Contents/SharedSupport/wine/bin/wine*"))
    return next((path for path in candidates if path.name in ("wine", "wine64")
                 and path.is_file() and os.access(path, os.X_OK)), None)


def read_settings(path: Path) -> dict[str, str]:
    """Read shell-style assignments as data, never execute configuration."""
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = shlex.split(line, comments=True)
        if fields and fields[0] == "export":
            fields = fields[1:]
        if len(fields) == 1 and "=" in fields[0]:
            key, value = fields[0].split("=", 1)
            values[key] = value
    return values


def write_settings(path: Path, values: dict[str, str]) -> None:
    """Persist macOS settings without evaluating shell expressions."""
    for key, value in values.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"Invalid setting name: {key}")
        if "\n" in value or "\r" in value:
            raise ValueError(f"Setting must contain a single line: {key}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write("".join(f"export {key}={shlex.quote(value)}\n"
                                 for key, value in values.items()))
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def wine_command(root: Path, arguments: list[str], settings: dict[str, str]) -> tuple[list[str], dict[str, str]]:
    """Build the native Wine command and isolated prefix environment."""
    version = settings.get("PW_WINE_USE") or settings.get("PW_DEFAULT_WINE_USE", "")
    system_wine = version == "USE_SYSTEM_WINE"
    wine = find_wine(version_directory(root, version)) if version and not system_wine else None
    if wine is None and not version:
        wine = next((found for child in sorted((root / "data" / "dist").glob("*"))
                     if not child.name.startswith(".") and (found := find_wine(child)) is not None), None)
    executable = str(wine) if wine else (shutil.which("wine") if not version or system_wine else None)
    if not executable:
        raise FileNotFoundError("Install and select a macOS Wine version in the Wine manager")
    prefix = settings.get("PW_PREFIX_NAME") or settings.get("PW_DEFAULT_PREFIX_NAME") or "DEFAULT"
    if Path(prefix).name != prefix or prefix in (".", ".."):
        raise ValueError("Invalid Wine prefix name")
    prefix_path = root / "data" / "prefixes" / prefix
    if not prefix_path.resolve().is_relative_to((root / "data" / "prefixes").resolve()):
        raise ValueError("Wine prefix escapes prefix directory")
    prefix_path.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["WINEPREFIX"] = str(prefix_path)
    environment["PATH"] = str(Path(executable).parent) + os.pathsep + environment.get("PATH", "")
    if wine is not None:
        wineserver = wine.with_name("wineserver")
        if wineserver.is_file() and os.access(wineserver, os.X_OK):
            environment["WINESERVER"] = str(wineserver)
    return [executable, *arguments], environment


def settings_command(root: Path, arguments: list[str]) -> bool:
    """Implement settings operations used by the existing settings dialog."""
    action = arguments[0]
    user_conf = root / "data" / "user.conf"
    path = Path(arguments[1] + ".ppdb") if action in ("--show-ppdb", "--edit-db") else user_conf
    values = read_settings(path)
    if action in ("--get-user-conf", "--show-ppdb"):
        if action == "--get-user-conf" and len(arguments) > 1:
            sys.stdout.write(values.get(arguments[1], "") + "\n")
        else:
            sys.stdout.write("".join(f'{key}="{value}"\n' for key, value in values.items()))
    elif action == "--edit-db":
        for change in arguments[2:]:
            key, value = change.split("=", 1)
            values[key] = value
        write_settings(path, values)
    elif action == "--set-user-conf":
        values[arguments[1]] = arguments[2]
        write_settings(path, values)
    elif action == "--delete-user-conf":
        values.pop(arguments[1], None)
        write_settings(path, values)
    else:
        return False
    return True


def main(arguments: list[str] | None = None) -> int:
    """Run the native adapter through the existing PortProton command interface."""
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    root = data_root()
    try:
        if not arguments:
            raise ValueError("An executable or Wine tool is required")
        settings = read_settings(root / "data" / "user.conf")
        if arguments[0] == "cli":
            arguments = arguments[1:]
            if not arguments:
                raise ValueError("A CLI operation is required")
            if settings_command(root, arguments):
                return 0
            tool = WINE_TOOLS.get(arguments[0])
            if not tool or len(arguments) != 3:
                raise ValueError(f"Unsupported macOS operation: {arguments[0]}")
            settings.update(PW_WINE_USE=arguments[1], PW_PREFIX_NAME=arguments[2])
            arguments = [tool]
        else:
            settings.update(read_settings(Path(arguments[0] + ".ppdb")))
            target = Path(arguments[0]).expanduser().resolve(strict=True)
            arguments[0] = str(target)
            dispatch = {".msi": ["msiexec", "/i"], ".bat": ["cmd", "/c"],
                        ".cmd": ["cmd", "/c"], ".reg": ["regedit"]}
            arguments = [*dispatch.get(target.suffix.lower(), []), *arguments]
            os.chdir(target.parent)
        command, environment = wine_command(root, arguments, settings)
        os.execvpe(command[0], command, environment)
    except (OSError, ValueError, IndexError) as error:
        logger.error("macOS Wine operation failed: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
