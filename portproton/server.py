"""D-Bus server for headless PortProton clients."""
import asyncio
import logging
import os
import re
import signal
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dbus_fast import BusType, DBusError, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.constants import RequestNameReply
from dbus_fast.service import ServiceInterface, method

from portproton.library import (
    get_autoinstall_games,
    get_library_games,
    get_prefix_options,
    get_wine_options,
)
from portproton.operations import (
    launch_executable,
    run_command,
    scripts_directory,
    validate_executable,
    validate_setting,
)

BUS_NAME = "ru.linux_gaming.PortProton1"
OBJECT_PATH = "/ru/linux_gaming/PortProton"
INTERFACE_NAME = "ru.linux_gaming.PortProton1"
logger = logging.getLogger(__name__)
SETTING_LINE = re.compile(r'^([A-Z][A-Z0-9_]*)=(.*)$')


def dbus_method(annotations: dict[str, str]) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Apply dbus-fast signatures without exposing them as Python types."""
    def decorator(function: Callable[..., Any]) -> Callable[..., Any]:
        function.__annotations__ = annotations
        return method()(function)

    return decorator


def _unwrap_filters(filters: dict[str, Variant]) -> dict[str, object]:
    supported = {"source": "s", "installed": "b", "search": "s"}
    values = {}
    for name, value in filters.items():
        signature = supported.get(name)
        if signature is None or value.signature != signature:
            raise DBusError(
                "org.freedesktop.DBus.Error.InvalidArgs",
                f"Invalid filter: {name}",
            )
        values[name] = value.value
    return values


def _to_dbus_game(game: dict[str, object]) -> dict[str, Variant]:
    return {
        "id": Variant("s", game["id"]),
        "name": Variant("s", game["name"]),
        "executable": Variant("s", game.get("executable", "")),
        "source": Variant("s", game["source"]),
        "installed": Variant("b", game["installed"]),
        "hidden": Variant("b", game["hidden"]),
        "cover": Variant("s", game["cover"]),
        "playtime": Variant("t", game["playtime"]),
        "last_launch": Variant("x", game["last_launch"]),
    }


def _settings_values(output: str) -> str:
    """Keep assignments from PortProton CLI output, without shell quoting."""
    values = []
    for line in output.splitlines():
        match = SETTING_LINE.fullmatch(line)
        if match is None:
            continue
        key, value = match.groups()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        values.append(f"{key}={value}")
    return "\n".join(values)


class PortProtonService(ServiceInterface):
    """Expose the first version of the PortProton D-Bus API."""

    def __init__(self, scripts: Path | None = None) -> None:
        super().__init__(INTERFACE_NAME)
        self.scripts = scripts
        self.processes: dict[int, asyncio.subprocess.Process] = {}
        self.watchers: set[asyncio.Task[None]] = set()

    def _require_scripts(self) -> Path:
        if self.scripts is None:
            raise DBusError("ru.linux_gaming.PortProton1.NotConfigured", "PortProton scripts are unavailable")
        return self.scripts

    async def _watch_process(self, process: asyncio.subprocess.Process) -> None:
        await process.wait()
        if process.pid is not None:
            self.processes.pop(process.pid, None)

    @dbus_method({"return": "u"})
    def GetAPIVersion(self) -> int:
        return 1

    @dbus_method({"return": "as"})
    def GetCapabilities(self) -> list[str]:
        capabilities = ["games.list", "wines.list", "prefixes.list",
                        "autoinstalls.list", "autoinstalls.refresh"]
        if self.scripts is not None:
            capabilities.extend(["exe.launch", "exe.settings", "settings.global", "exe.stop"])
        return capabilities

    @dbus_method({"filters": "a{sv}", "return": "aa{sv}"})
    async def ListGames(self, filters: dict[str, Variant]) -> list[dict[str, Variant]]:
        games = await asyncio.to_thread(get_library_games, _unwrap_filters(filters))
        return [_to_dbus_game(game) for game in games]

    @dbus_method({"return": "as"})
    async def ListWines(self) -> list[str]:
        return await asyncio.to_thread(get_wine_options)

    @dbus_method({"return": "as"})
    async def ListPrefixes(self) -> list[str]:
        return await asyncio.to_thread(get_prefix_options)

    @dbus_method({"return": "aa{sv}"})
    async def ListAutoinstalls(self) -> list[dict[str, Variant]]:
        games = await asyncio.to_thread(get_autoinstall_games)
        return [{key: Variant("s", value) for key, value in game.items()} for game in games]

    @dbus_method({"return": "aa{sv}"})
    async def RefreshAutoinstalls(self) -> list[dict[str, Variant]]:
        games = await asyncio.to_thread(get_autoinstall_games, True)
        return [{key: Variant("s", value) for key, value in game.items()} for game in games]

    @dbus_method({"path": "s", "return": "s"})
    async def GetExeSettings(self, path: str) -> str:
        try:
            target = validate_executable(path)
            return _settings_values(await run_command(self._require_scripts(), ["--show-ppdb", str(target)]))
        except (ValueError, FileNotFoundError, RuntimeError) as error:
            raise DBusError("ru.linux_gaming.PortProton1.InvalidRequest", str(error)) from error

    @dbus_method({"path": "s", "settings": "as", "return": "b"})
    async def SetExeSettings(self, path: str, settings: list[str]) -> bool:
        try:
            target = validate_executable(path)
            values = [validate_setting(setting) for setting in settings]
            if values:
                await run_command(self._require_scripts(), ["--edit-db", str(target), *values])
            return True
        except (ValueError, FileNotFoundError, RuntimeError) as error:
            raise DBusError("ru.linux_gaming.PortProton1.InvalidRequest", str(error)) from error

    @dbus_method({"return": "s"})
    async def GetGlobalSettings(self) -> str:
        return _settings_values(await run_command(self._require_scripts(), ["--get-user-conf"]))

    @dbus_method({"setting": "s", "return": "b"})
    async def SetGlobalSetting(self, setting: str) -> bool:
        key, _, value = validate_setting(setting).partition("=")
        await run_command(self._require_scripts(), ["--set-user-conf", key, value])
        return True

    @dbus_method({"path": "s", "return": "u"})
    async def LaunchExe(self, path: str) -> int:
        try:
            process = await launch_executable(self._require_scripts(), path)
        except (ValueError, FileNotFoundError, RuntimeError) as error:
            raise DBusError("ru.linux_gaming.PortProton1.InvalidRequest", str(error)) from error
        assert process.pid is not None
        self.processes[process.pid] = process
        watcher = asyncio.create_task(self._watch_process(process))
        self.watchers.add(watcher)
        watcher.add_done_callback(self.watchers.discard)
        return process.pid

    @dbus_method({"pid": "u", "return": "b"})
    def StopExe(self, pid: int) -> bool:
        process = self.processes.get(pid)
        if process is None:
            return False
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return False
        return True


async def serve() -> None:
    """Own the public session-bus name until disconnected."""
    with scripts_directory() as scripts:
        bus = await MessageBus(bus_type=BusType.SESSION).connect()
        bus.export(OBJECT_PATH, PortProtonService(scripts))
        result = await bus.request_name(BUS_NAME)
        if result not in (RequestNameReply.PRIMARY_OWNER, RequestNameReply.ALREADY_OWNER):
            bus.disconnect()
            raise RuntimeError(f"D-Bus name is already owned: {BUS_NAME}")
        await bus.wait_for_disconnect()


def main() -> int:
    """Run the headless D-Bus service."""
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        return 0
    except (DBusError, OSError, RuntimeError) as error:
        logger.error("Headless server failed: %s", error)
        return 1
    return 0
