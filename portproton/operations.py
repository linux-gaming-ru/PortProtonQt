"""Headless access to PortProton's existing command line operations."""

import asyncio
import os
import re
import sys
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from portproton.library import _get_portproton_directory

SETTING_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")
LAUNCH_SUFFIXES = {".exe", ".bat", ".cmd", ".msi", ".reg"}


@contextmanager
def scripts_directory() -> Iterator[Path | None]:
    """Locate installed scripts or unpack the development bundle."""
    archive = Path(sys.argv[0])
    if archive.is_file() and zipfile.is_zipfile(archive):
        with tempfile.TemporaryDirectory(prefix="portproton-server-") as temporary:
            with zipfile.ZipFile(archive) as bundle:
                for name in bundle.namelist():
                    if name.startswith(("portproton_assets/", "portproton_vendor/")):
                        bundle.extract(name, temporary)
            yield Path(temporary) / "portproton_assets" / "scripts"
        return
    roots = [Path.cwd() / "build-aux/share/portproton/scripts"]
    roots.extend(
        Path(directory) / "portproton/scripts"
        for directory in os.getenv("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")
        if directory
    )
    yield next((root for root in roots if (root / "start.sh").is_file()), None)


def validate_executable(path: str) -> Path:
    """Require an existing absolute Windows target."""
    target = Path(path)
    if not target.is_absolute() or target.suffix.lower() not in LAUNCH_SUFFIXES:
        raise ValueError("Expected an absolute Windows executable path")
    if not target.is_file():
        raise FileNotFoundError(path)
    return target


def _environment(scripts: Path) -> dict[str, str]:
    directory = _get_portproton_directory()
    if directory is None:
        raise FileNotFoundError("PortProton data directory is not configured")
    environment = os.environ.copy()
    environment["PORT_DATA_PATH"] = str(directory)
    archive = Path(sys.argv[0])
    if archive.is_file() and zipfile.is_zipfile(archive):
        vendor = scripts.parent.parent / "portproton_vendor"
        environment["PYTHONPATH"] = os.pathsep.join(filter(None, (
            str(vendor), str(archive), environment.get("PYTHONPATH", ""),
        )))
    return environment


async def run_command(scripts: Path, args: list[str]) -> str:
    """Run a short CLI command outside the D-Bus event loop."""
    process = await asyncio.create_subprocess_exec(
        "bash", str(scripts / "start.sh"), "cli", *args,
        env=_environment(scripts), stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError("PortProton command timed out") from None
    if process.returncode:
        raise RuntimeError(stderr.decode("utf-8", "replace").strip() or "PortProton command failed")
    return stdout.decode("utf-8", "replace")


async def launch_executable(scripts: Path, path: str) -> asyncio.subprocess.Process:
    """Start and retain the PortProton launcher process."""
    target = validate_executable(path)
    return await asyncio.create_subprocess_exec(
        "bash", str(scripts / "start.sh"), str(target),
        env=_environment(scripts), stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )


def validate_setting(setting: str) -> str:
    """Reject assignments unsafe for the sourced PortProton settings file."""
    key, separator, value = setting.partition("=")
    if (not separator or not SETTING_KEY.fullmatch(key)
            or any(char in value for char in "\n\r`$")):
        raise ValueError(f"Invalid setting: {key}")
    return setting
