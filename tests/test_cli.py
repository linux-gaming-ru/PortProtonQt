"""Tests for cli.py — URL parsing, path normalization, file detection, resolution parsing."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from portprotonqt.cli import (
    normalize_launch_path,
    is_autoinstall_file,
    is_launch_file,
    is_prefix_backup_file,
    parse_portproton_url,
    parse_portprotonqt_theme_url,
    parse_resolution,
    LAUNCH_FILE_EXTENSIONS,
    parse_args,
)


class TestParseArgs:
    def test_log_silent_launch(self, monkeypatch):
        monkeypatch.setattr(
            sys,
            "argv",
            ["portprotonqt", "--log", "--silent", "file:///tmp/game.exe"],
        )

        args = parse_args()

        assert args.log is True
        assert args.silent is True
        assert args.file_or_url == "file:///tmp/game.exe"


@pytest.fixture
def silent_startup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    from PySide6 import QtCore, QtNetwork
    from portprotonqt import app, main_window, port_data_path_selector

    monkeypatch.delenv("STEAM_COMPAT", raising=False)
    monkeypatch.delenv("PORTPROTONQT_INTEGRATE_APPIMAGE", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("MANGOHUD", "1")
    monkeypatch.setenv("LD_PRELOAD", "libMangoHud_shim.so")
    monkeypatch.setattr(app, "get_steam_language", lambda: "english")
    monkeypatch.setattr(app, "get_portproton_location", lambda: str(tmp_path))
    monkeypatch.setattr("portprotonqt.native_games.get_portproton_location", lambda: str(tmp_path))
    monkeypatch.setattr("portprotonqt.config.portproton.get_portproton_location", lambda: str(tmp_path))
    monkeypatch.setattr(app, "get_portproton_start_command", lambda: ["start.sh"])
    monkeypatch.setattr(app, "consume_download_counter_skip", lambda: False)
    monkeypatch.setattr(app, "update_app_version", lambda _version: False)
    monkeypatch.setattr(app.ui_config, "get_disable_runtime_download", lambda: False)
    monkeypatch.setattr(app.display_config, "get_fullscreen", lambda: False)
    monkeypatch.setattr(port_data_path_selector, "is_portdata_path_read_write", lambda _path: True)
    qt_app = MagicMock()
    qt_app.exec.return_value = 0
    monkeypatch.setattr(app, "QApplication", MagicMock(return_value=qt_app))
    lock = MagicMock()
    lock.tryLock.return_value = True
    monkeypatch.setattr(QtCore, "QLockFile", MagicMock(return_value=lock))
    monkeypatch.setattr(QtCore.QStandardPaths, "writableLocation", lambda _location: str(tmp_path))
    socket = MagicMock()
    socket.waitForConnected.return_value = False
    server = MagicMock()
    monkeypatch.setattr(QtNetwork, "QLocalSocket", MagicMock(return_value=socket))
    monkeypatch.setattr(QtNetwork, "QLocalServer", server)
    window = MagicMock(side_effect=RuntimeError("main window reached"))
    monkeypatch.setattr(main_window, "MainWindow", window)
    exe = tmp_path / "my game.exe"
    exe.touch()
    return SimpleNamespace(app=app, qt_app=qt_app, socket=socket, server=server, lock=lock,
                           window=window, exe=exe)


@pytest.mark.parametrize("file_uri", [False, True])
def test_silent_exe_keeps_main_window_for_emulation(
    silent_startup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, file_uri: bool,
) -> None:
    startup = silent_startup
    target = startup.exe.as_uri() if file_uri else str(startup.exe)
    monkeypatch.setattr(sys, "argv", ["portprotonqt", "--silent", target])

    with pytest.raises(RuntimeError, match="main window reached"):
        startup.app.main()

    startup.window.assert_called_once()
    assert startup.window.call_args.kwargs["launch_exe"] == str(startup.exe)
    assert os.environ["MANGOHUD"] == "1"
    assert os.environ["LD_PRELOAD"] == "libMangoHud_shim.so"


def test_silent_exe_uses_existing_instance(
    silent_startup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    startup = silent_startup
    startup.socket.waitForConnected.return_value = True
    monkeypatch.setattr(sys, "argv", ["portprotonqt", "--silent", str(startup.exe)])

    startup.app.main()

    startup.socket.write.assert_called_once_with(f"silent:{startup.exe}".encode())
    startup.window.assert_not_called()
    startup.qt_app.exec.assert_not_called()


def test_existing_instance_with_unavailable_ipc_does_not_start_another(
    silent_startup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    startup = silent_startup
    startup.lock.tryLock.return_value = False
    monkeypatch.setattr(sys, "argv", ["portprotonqt", "--silent", str(startup.exe)])

    startup.app.main()

    startup.server.removeServer.assert_not_called()
    startup.server.assert_not_called()
    startup.window.assert_not_called()
    startup.qt_app.exec.assert_not_called()


@pytest.mark.parametrize("silent", [False, True])
def test_silent_launch_skips_startup_workers(
    silent_startup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, silent: bool,
) -> None:
    from PySide6.QtCore import QThread
    from portprotonqt import appimage_updater

    startup = silent_startup
    window = MagicMock()
    startup.window.side_effect = None
    startup.window.return_value = window
    monkeypatch.setattr(startup.app, "QTimer", MagicMock())
    monkeypatch.setattr(QThread, "start", MagicMock())
    update_worker = MagicMock()
    monkeypatch.setattr(appimage_updater, "AppImageUpdateWorker", update_worker)
    monkeypatch.setattr(startup.app.display_config, "get_auto_fullscreen_gamepad", lambda: False)
    monkeypatch.setattr(startup.app.display_config, "get_start_minimized", lambda: False)
    monkeypatch.setattr(startup.app.display_config, "set_fullscreen", MagicMock())
    flags = ["--silent"] if silent else []
    monkeypatch.setattr(sys, "argv", ["portprotonqt", *flags, str(startup.exe)])

    with pytest.raises(SystemExit) as result:
        startup.app.main()

    assert result.value.code == 0
    assert window.silent_launch_mode is silent
    assert ("initialCommandWorker" in vars(window)) is (not silent)
    assert update_worker.called is (not silent)
    assert ("appimageUpdateWorker" in vars(window)) is (not silent)
    startup.window.assert_called_once()


@pytest.mark.parametrize("target", ["exe", "gog://launch/123", "egs://launch/example"])
@pytest.mark.parametrize("decision", [
    ("No", True, False), ("Yes", True, False), ("No", False, False),
    ("Yes", False, False), ("Yes", True, True),
])
def test_silent_ipc_confirms_restarting_application(
    silent_startup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
    target: str, decision: tuple[str, bool, bool],
) -> None:
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QMessageBox
    startup = silent_startup
    reply, running, stop_failed = decision
    window = MagicMock(game_processes=[])
    startup.window.side_effect = None
    startup.window.return_value = window
    timers = MagicMock()
    monkeypatch.setattr(startup.app, "QTimer", timers)
    monkeypatch.setattr(QThread, "start", MagicMock())
    monkeypatch.setattr(startup.app.display_config, "get_auto_fullscreen_gamepad", lambda: False)
    monkeypatch.setattr(startup.app.display_config, "get_start_minimized", lambda: False)
    monkeypatch.setattr(sys, "argv", ["portprotonqt", "--silent", str(startup.exe)])
    question = MagicMock()
    question.exec.return_value = getattr(QMessageBox.StandardButton, reply)
    message_box = MagicMock(return_value=question, StandardButton=QMessageBox.StandardButton,
                            Icon=QMessageBox.Icon)
    monkeypatch.setattr(startup.app, "QMessageBox", message_box)
    restart, stop = MagicMock(), MagicMock()
    monkeypatch.setattr(startup.app.os, "execv", restart)
    monkeypatch.setattr(startup.app.psutil, "Process", MagicMock(return_value=MagicMock(children=lambda **kw: [])))
    monkeypatch.setattr(startup.app.psutil, "wait_procs", MagicMock(return_value=([], [])))
    stop.side_effect = OSError("stop failed") if stop_failed else None
    monkeypatch.setattr(startup.app.subprocess, "run", stop)
    target = str(startup.exe) if target == "exe" else target
    def event_loop() -> int:
        timers.singleShot.call_args_list[0].args[1]()
        message_box.assert_not_called()
        window.game_processes = [MagicMock()] if running else []
        conn = MagicMock()
        conn.readAll.return_value.data.return_value = f"silent:{target}".encode()
        startup.server.return_value.nextPendingConnection.return_value = conn
        startup.server.return_value.newConnection.connect.call_args.args[0]()
        timers.singleShot.call_args.args[1]()
        return 0
    startup.qt_app.exec.side_effect = event_loop
    with pytest.raises(SystemExit):
        startup.app.main()
    question.setDefaultButton.assert_called_once_with(QMessageBox.StandardButton.No)
    window.toggleGame.assert_called_once_with("'" + str(startup.exe) + "'")
    assert startup.qt_app.quit.called is (reply == "Yes")
    assert (stop.called, window._stopBackgroundWorkers.called) == (reply == "Yes",) * 2
    if reply == "Yes" and not stop_failed:
        restart.assert_called_once_with(sys.executable, [sys.executable, "-m", "portprotonqt.app", "--silent", target])
    else:
        assert not restart.called and not startup.lock.unlock.called


@pytest.mark.parametrize("flags,target", [
    ([], "exe"),
    (["--silent", "--log"], "exe"),
    (["--silent"], "gog://launch/123"),
    (["--silent"], "egs://launch/example"),
    (["--silent", "--restore-prefix"], "exe"),
    (["--silent", "--create-backup", "DEFAULT", "/tmp"], "exe"),
])
def test_other_launch_modes_keep_main_window(
    silent_startup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
    flags: list[str], target: str,
) -> None:
    startup = silent_startup
    target = str(startup.exe) if target == "exe" else target
    monkeypatch.setattr(sys, "argv", ["portprotonqt", *flags, target])

    with pytest.raises(RuntimeError, match="main window reached"):
        startup.app.main()

    startup.window.assert_called_once()


@pytest.mark.parametrize("flags", [[], ["--silent"], ["--log"], ["--silent", "--log"]])
@pytest.mark.parametrize("existing", [False, True])
def test_native_shortcut_launch_modes(
    silent_startup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, flags: list[str], existing: bool,
) -> None:
    from urllib.parse import quote
    from PySide6.QtCore import QThread
    from portprotonqt.native_games import create_native_desktop_file

    startup = silent_startup
    executable = startup.exe.with_name("native game")
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    result = create_native_desktop_file(str(executable), "Native")
    assert result is not None
    content, destination = result
    Path(destination).write_text(content)
    uri = "native://" + destination
    startup.socket.waitForConnected.return_value = existing
    monkeypatch.setattr(sys, "argv", ["portprotonqt", *flags, str(executable)])
    mode = "log" if "--log" in flags else "silent" if "--silent" in flags else "open"
    if existing:
        startup.app.main()
        startup.socket.write.assert_called_once_with(f"{mode}:{quote(uri, safe='')}".encode())
        startup.window.assert_not_called()
        return
    window, timers = MagicMock(), MagicMock()
    window.game_processes = []
    startup.window.side_effect, startup.window.return_value = None, window
    monkeypatch.setattr(startup.app, "QTimer", timers)
    monkeypatch.setattr(QThread, "start", MagicMock())
    monkeypatch.setattr(startup.app.display_config, "get_auto_fullscreen_gamepad", lambda: False)
    monkeypatch.setattr(startup.app.display_config, "get_start_minimized", lambda: False)
    def event_loop() -> int:
        callback = next(call.args[1] for call in timers.singleShot.call_args_list
                        if getattr(call.args[1], "__name__", "") == "handle_native_launch")
        callback()
        return 0
    startup.qt_app.exec.side_effect = event_loop
    with pytest.raises(SystemExit):
        startup.app.main()
    assert window.silent_launch_mode is (mode == "silent")
    if mode == "silent":
        window.toggleGame.assert_called_once_with(uri)
    else:
        window._load_native_games_async.assert_called_once()
        window._load_native_games_async.call_args.args[0]([
            ("Native", "", "", "", "", uri, "", "", "", "", 0, 0, "native", "", "", "")])
        assert window.openGameDetailPage.call_args.args[0]["exec_line"] == uri
        if mode == "log":
            assert window._pending_log_exe == uri


class TestNormalizeLaunchPath:
    def test_plain_path(self):
        assert normalize_launch_path("/tmp/game.exe") == "/tmp/game.exe"

    def test_expanduser(self):
        result = normalize_launch_path("~/game.exe")
        assert result.startswith(os.path.expanduser("~"))
        assert result.endswith("game.exe")

    def test_file_uri(self):
        result = normalize_launch_path("file:///tmp/game.exe")
        assert result == "/tmp/game.exe"

    def test_file_uri_with_spaces(self):
        result = normalize_launch_path("file:///tmp/my%20game.exe")
        assert result == "/tmp/my game.exe"

    def test_file_uri_with_tilde(self):
        result = normalize_launch_path("file:///~/game.exe")
        assert result == "/~/game.exe"

    def test_relative_path_becomes_absolute(self):
        result = normalize_launch_path("game.exe")
        assert os.path.isabs(result)


class TestIsLaunchFile:
    def test_exe_file(self, tmp_path: Path):
        exe = tmp_path / "game.exe"
        exe.touch()
        assert is_launch_file(str(exe)) is True

    def test_bat_file(self, tmp_path: Path):
        bat = tmp_path / "setup.bat"
        bat.touch()
        assert is_launch_file(str(bat)) is True

    def test_cmd_file(self, tmp_path: Path):
        cmd = tmp_path / "launch.cmd"
        cmd.touch()
        assert is_launch_file(str(cmd)) is True

    def test_msi_file(self, tmp_path: Path):
        msi = tmp_path / "installer.msi"
        msi.touch()
        assert is_launch_file(str(msi)) is True

    def test_iso_file(self, tmp_path: Path):
        iso = tmp_path / "game.iso"
        iso.touch()
        assert is_launch_file(str(iso)) is True

    def test_not_launch_file(self, tmp_path: Path):
        txt = tmp_path / "readme.txt"
        txt.touch()
        assert is_launch_file(str(txt)) is False

    def test_nonexistent_file(self):
        assert is_launch_file("/nonexistent/game.exe") is False

    def test_launch_file_extensions_complete(self):
        assert ".exe" in LAUNCH_FILE_EXTENSIONS
        assert ".bat" in LAUNCH_FILE_EXTENSIONS
        assert ".cmd" in LAUNCH_FILE_EXTENSIONS
        assert ".msi" in LAUNCH_FILE_EXTENSIONS
        assert ".reg" in LAUNCH_FILE_EXTENSIONS
        assert ".iso" in LAUNCH_FILE_EXTENSIONS
        assert ".mdf" in LAUNCH_FILE_EXTENSIONS
        assert ".nrg" in LAUNCH_FILE_EXTENSIONS


class TestIsPrefixBackupFile:
    def test_ppack_file(self, tmp_path: Path):
        ppack = tmp_path / "backup.ppack"
        ppack.touch()
        assert is_prefix_backup_file(str(ppack)) is True

    def test_not_ppack(self, tmp_path: Path):
        txt = tmp_path / "backup.zip"
        txt.touch()
        assert is_prefix_backup_file(str(txt)) is False

    def test_nonexistent_file(self):
        assert is_prefix_backup_file("/nonexistent/backup.ppack") is False


class TestIsAutoinstallFile:
    def test_ppai_file(self, tmp_path: Path):
        ppai = tmp_path / "installer.ppai"
        ppai.touch()
        assert is_autoinstall_file(str(ppai)) is True

    def test_not_ppai(self, tmp_path: Path):
        txt = tmp_path / "installer.txt"
        txt.touch()
        assert is_autoinstall_file(str(txt)) is False


class TestParsePortprotonUrl:
    def test_https_url(self):
        url = "portproton://https//linux-gaming.ru/api/games/130127/ppdb/download"
        result = parse_portproton_url(url)
        assert result == "https://linux-gaming.ru/api/games/130127/ppdb/download"

    def test_http_url(self):
        url = "portproton://http//example.com/download"
        result = parse_portproton_url(url)
        assert result == "http://example.com/download"

    def test_bare_url_without_protocol(self):
        url = "portproton://example.com/game"
        result = parse_portproton_url(url)
        assert result == "https://example.com/game"

    def test_url_with_existing_protocol(self):
        url = "portproton://https://example.com/game"
        result = parse_portproton_url(url)
        assert result == "https://example.com/game"

    def test_invalid_prefix(self):
        assert parse_portproton_url("http://example.com") is None

    def test_empty_string(self):
        assert parse_portproton_url("") is None


class TestParsePortprotonqtThemeUrl:
    def test_theme_url(self):
        assert parse_portprotonqt_theme_url("portprotonqt://theme/6") == 6

    def test_theme_url_trailing_slash(self):
        assert parse_portprotonqt_theme_url("portprotonqt://theme/42/") == 42

    def test_invalid_prefix(self):
        assert parse_portprotonqt_theme_url("portproton://theme/6") is None

    def test_invalid_theme_id(self):
        assert parse_portprotonqt_theme_url("portprotonqt://theme/mix") is None


class TestParseResolution:
    def test_standard_1080p(self):
        assert parse_resolution("1920x1080") == (1920, 1080)

    def test_standard_4k(self):
        assert parse_resolution("3840x2160") == (3840, 2160)

    def test_case_insensitive(self):
        assert parse_resolution("1920X1080") == (1920, 1080)

    def test_invalid_format(self):
        assert parse_resolution("1920") is None

    def test_invalid_letters(self):
        assert parse_resolution("abcxdef") is None

    def test_too_small_width(self):
        assert parse_resolution("100x1080") is None

    def test_too_small_height(self):
        assert parse_resolution("1920x100") is None

    def test_too_large_width(self):
        assert parse_resolution("9999x1080") is None

    def test_too_large_height(self):
        assert parse_resolution("1920x9999") is None

    def test_min_valid(self):
        assert parse_resolution("320x200") == (320, 200)

    def test_max_valid(self):
        assert parse_resolution("7680x4320") == (7680, 4320)

    def test_empty_string(self):
        assert parse_resolution("") is None


def test_list_games_json_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from portprotonqt.cli import _list_portproton_games
    from portprotonqt.config import portproton

    executable = tmp_path / "Game with spaces.exe"
    shortcut = tmp_path / "game.desktop"
    shortcut.write_text(
        '[Desktop Entry]\nName=Test Game\n'
        f'Exec=portprotonqt --silent "{executable}"\nIcon=test-icon\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(portproton, "get_portproton_location", lambda: str(tmp_path))
    monkeypatch.setattr(portproton, "get_portproton_scripts_path", lambda: None)
    monkeypatch.setattr("portprotonqt.cli._get_game_metadata", lambda *args: {
        "name": "Test Game", "description": "Description", "cover": "cover.png",
        "appid": 123, "custom_icon": "",
    })
    games = _list_portproton_games(str(tmp_path), {}, {})
    assert len(games) == 1
    assert games[0]["description"] == "Description"
    assert games[0]["cover"] == "cover.png"
    assert games[0]["appid"] == 123
    assert not {"metadata", "desktop_entry", "custom_icon"} & games[0].keys()
    assert {key: games[0][key] for key in (
        "id", "name", "desktop_file", "exec", "executable", "directory", "icon", "ppdb"
    )} == {
        "id": "portproton:game.desktop", "name": "Test Game",
        "desktop_file": str(shortcut),
        "exec": f'portprotonqt --silent "{executable}"',
        "executable": str(executable), "directory": str(tmp_path),
        "icon": "test-icon", "ppdb": f"{executable}.ppdb",
    }


def test_list_games_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    from portprotonqt.cli import _list_portproton_games
    from portprotonqt.config import portproton

    monkeypatch.setattr(portproton, "get_portproton_location", lambda: None)
    assert _list_portproton_games(None, {}, {}) == []


def test_parse_list_games(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["portprotonqt", "--list-games"])
    assert parse_args().list_games


def test_export_custom_artwork(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from portprotonqt.cli import _get_game_metadata
    from portprotonqt.config.portproton import resolve_custom_data_dir

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr("portprotonqt.steam_api.api.get_cached_steam_game_info", lambda *args: {
        "name": "Cached", "description": "Cached description", "appid": "123",
    })
    monkeypatch.setattr("portprotonqt.localization.get_metadata_language", lambda: "en")
    monkeypatch.setattr("portprotonqt.time_utils.get_playtime_for_exe", lambda *args: 42)
    monkeypatch.setattr("portprotonqt.time_utils.get_last_launch_timestamp", lambda *args: 100)
    executable = str(tmp_path / "Game.exe")
    folder = Path(resolve_custom_data_dir(str(tmp_path / "PortProtonQt/custom_data"), executable))
    folder.mkdir(parents=True)
    (folder / "metadata.txt").write_text("name_en=Custom\ndescription_en=Description\n")
    (folder / "cover.png").touch()
    (folder / "icon.png").touch()
    metadata = _get_game_metadata("Original", "launch", executable)
    assert metadata["name"] == "Custom"
    assert metadata["description"] == "Description"
    assert metadata["cover"] == str(folder / "cover.png")
    assert metadata["custom_icon"] == str(folder / "icon.png")
    assert metadata["appid"] == "123"
    assert metadata["playtime_seconds"] == 42


def test_export_runtime(tmp_path: Path) -> None:
    from portprotonqt.cli import _get_game_runtime

    executable = str(tmp_path / "Game.exe")
    Path(f"{executable}.ppdb").write_text(
        'export PW_WINE_USE="PROTON_LG"\nexport PW_PREFIX_NAME="GAME"\n'
    )
    runner = tmp_path / "data/dist/PROTON_TEST"
    runner.mkdir(parents=True)
    runtime = _get_game_runtime(tmp_path, executable, {"PW_PROTON_LG_VER": "PROTON_TEST"}, {})
    assert runtime["runner"] == "PROTON_TEST"
    assert "runner_version" not in runtime
    assert runtime["runner_path"] == str(runner)
    assert runtime["runner_installed"]
    assert runtime["prefix_path"] == str(tmp_path / "data/prefixes/GAME")


def test_settings_do_not_execute_shell(tmp_path: Path) -> None:
    from portprotonqt.cli import _read_game_settings

    marker = tmp_path / "should-not-exist"
    settings = tmp_path / "settings"
    settings.write_text(
        f'export PW_WINE_USE="$(touch {marker})"\n'
        'export PW_PREFIX_NAME="Game prefix"\n'
        'check_variables PW_VULKAN_USE "1"\n'
    )
    assert _read_game_settings(settings) == {"PW_PREFIX_NAME": "Game prefix", "PW_VULKAN_USE": "1"}
    assert not marker.exists()


def test_list_games_exits_before_gui(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    import orjson
    from portprotonqt import app

    monkeypatch.setattr(app, "parse_args", lambda: SimpleNamespace(list_games=True, game_info=None, edit_game=None, pretty=True, fields=None, all_games=True))
    monkeypatch.setattr("portprotonqt.cli.list_games", lambda: [{"name": "Игра"}])
    gui = MagicMock(side_effect=AssertionError("GUI must not start"))
    monkeypatch.setattr(app, "QApplication", gui)
    assert app.main() == 0
    output = capsys.readouterr().out
    assert orjson.loads(output) == [{"name": "Игра"}]
    assert output == '[\n  {\n    "name": "Игра"\n  }\n]\n'
    gui.assert_not_called()


@pytest.mark.parametrize("external", [False, True])
def test_runtime_wine_layout(tmp_path: Path, external: bool) -> None:
    from portprotonqt.cli import _get_game_runtime

    runner = tmp_path / "External Wine" if external else tmp_path / "data/dist/PROTON_TEST"
    (runner / "files/bin-wow64").mkdir(parents=True)
    selected = str(runner) if external else "PROTON_TEST"
    runtime = _get_game_runtime(tmp_path, None, {}, {
        "PW_WINE_USE": selected, "PW_USE_WOW64": "1", "PW_PREFIX_NAME": "CUSTOM",
    })
    assert runtime["wine_path"] == str(runner / "files/bin-wow64/wine")
    assert runtime["wineserver_path"] == str(runner / "files/bin-wow64/wineserver")
    assert runtime["prefix_path"] == str(tmp_path / "data/prefixes/CUSTOM")


@pytest.mark.parametrize("source,backend", [("gog", "gog_api.GOGAPI"), ("egs", "egs_api.EGSAPI")])
def test_list_store_games(source: str, backend: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from portprotonqt.cli import _list_store_games

    api = MagicMock()
    api.load_library.return_value = [
        {"app_id": "123", "title": "Installed", "description": "Details", "cover": "store.jpg"},
        {"app_id": "456", "title": "Owned"},
    ]
    api.load_installed.return_value = {"123": {}}
    api.is_game_installed.side_effect = lambda app_id, installed: app_id in installed
    api.get_launch_target.return_value = "/games/game.exe"
    monkeypatch.setattr(f"portprotonqt.{backend}", lambda: api)
    monkeypatch.setattr("portprotonqt.main_window.MainWindow._get_custom_store_data",
                        lambda source, app_id, name: (name, "custom.jpg"))
    monkeypatch.setattr("portprotonqt.cli._get_game_metadata", lambda *args: {"custom_icon": "icon.png"})
    games = _list_store_games(source, None, {}, {})
    assert [game["id"] for game in games] == [f"{source}:123", f"{source}:456"]
    assert all(game["source"] == source for game in games)
    assert games[0]["description"] == "Details"
    assert games[0]["cover"] == "custom.jpg"
    assert games[0]["icon"] == "icon.png"
    assert games[0]["exec"] == f"{source}://launch/123"
    assert games[1]["exec"] == f"{source}://install/456"
    assert games[1]["executable"] is None
    api.get_launch_target.assert_called_once_with("123")


def test_list_steam_games(monkeypatch: pytest.MonkeyPatch) -> None:
    from portprotonqt.cli import _list_steam_games

    monkeypatch.setattr("portprotonqt.steam_api.get_steam_installed_games", lambda: [("Game", 123, 100, 42)])
    monkeypatch.setattr("portprotonqt.steam_api.api.get_cached_full_steam_game_info",
                        lambda *args: {"description": "Details", "cover": "cached.jpg"})
    monkeypatch.setattr("portprotonqt.main_window.MainWindow._get_custom_store_data",
                        lambda *args: ("Custom", "custom.jpg"))
    game = _list_steam_games()[0]
    assert game["id"] == "steam:123"
    assert game["source"] == "steam"
    assert game["name"] == "Custom"
    assert game["cover"] == "custom.jpg"
    assert game["exec"] == "steam://rungameid/123"
    assert game["playtime_seconds"] == 42


def test_list_all_sources_without_portproton(monkeypatch: pytest.MonkeyPatch) -> None:
    from portprotonqt.cli import list_games

    monkeypatch.setattr("portprotonqt.config.portproton.get_portproton_location", lambda: None)
    monkeypatch.setattr("portprotonqt.config.portproton.get_portproton_scripts_path", lambda: None)
    monkeypatch.setattr("portprotonqt.cli._list_steam_games", lambda: [{"source": "steam"}])
    monkeypatch.setattr("portprotonqt.cli._list_store_games", lambda source, *args: [{"source": source}])
    assert [game["source"] for game in list_games()] == ["steam", "gog", "egs"]


@pytest.mark.parametrize("format_flag,pretty", [("--pretty", True), ("--raw", False)])
def test_json_format_args(format_flag: str, pretty: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["portprotonqt", "--game-info", "steam:123", format_flag])
    args = parse_args()
    assert args.game_info == "steam:123"
    assert args.pretty is pretty


@pytest.mark.parametrize("game_id", ["steam:123", "gog:123", "missing"])
def test_game_info_output(game_id: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    import orjson
    from portprotonqt import app

    monkeypatch.setattr(app, "parse_args", lambda: SimpleNamespace(
        list_games=False, game_info=game_id, edit_game=None, pretty=False, fields=None,
    ))
    monkeypatch.setattr("portprotonqt.cli.list_games", lambda: [
        {"id": "steam:123", "source": "steam"}, {"id": "gog:123", "source": "gog"},
    ])
    code = app.main()
    output = capsys.readouterr().out
    if game_id == "missing":
        assert code == 1
        assert output == ""
    else:
        assert code == 0
        assert orjson.loads(output)["id"] == game_id
        assert len(output.splitlines()) == 1


@pytest.mark.parametrize("flags", [
    ["--pretty", "--raw"], ["--list-games", "--game-info", "steam:123"], ["--game-info"],
])
def test_library_conflicting_args(flags: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["portprotonqt", *flags])
    with pytest.raises(SystemExit) as error:
        parse_args()
    assert error.value.code == 2


@pytest.fixture
def editable_game(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    from portprotonqt.cli import _read_game_settings

    executable = tmp_path / "Game with spaces.exe"
    executable.touch()
    ppdb = Path(f"{executable}.ppdb")
    ppdb.write_text('# Keep this comment\nexport PW_MANGOHUD="0"\nexport PW_WINDOWS_VER="10"\n')
    game = {"id": "portproton:game.desktop", "source": "portproton", "executable": str(executable)}
    monkeypatch.setattr("portprotonqt.cli.list_games", lambda: [
        {**game, "runtime": {"settings": _read_game_settings(ppdb)}},
    ])
    helper = Path("build-aux/share/portproton/scripts/functions_helper").read_text()
    functions = "\n".join(
        name + helper.split(name, 1)[1].split("\n}\n", 1)[0] + "\n}"
        for name in ("set_several_variables () {", "edit_db_from_gui () {")
    )
    script = tmp_path / "start.sh"
    script.write_text(
        '#!/usr/bin/env bash\nset -e\n' + functions + '\n'
        'print_info () { printf "%s\\n" "$*"; }\n'
        'print_error () { printf "%s\\n" "$*" >&2; }\n'
        'PORTWINE_DB_FILE="${3}.ppdb"\n'
        'set_several_variables "${@:4}"\nedit_db_from_gui $keys_all\n'
    )
    monkeypatch.setattr("portprotonqt.config.portproton.get_portproton_start_command",
                        lambda: ["bash", str(script)])
    return {**game, "ppdb": ppdb, "script": script}


def test_edit_game_roundtrip(editable_game: dict) -> None:
    from portprotonqt.cli import edit_game

    result = edit_game(editable_game["id"], [
        "PW_MANGOHUD=1", 'LAUNCH_PARAMETERS=--option=value "quoted"',
        "PW_PREFIX_NAME=GAME", "WINEDLLOVERRIDES=d3d11=n,b;dxgi=n",
    ])
    settings = result["runtime"]["settings"]
    assert settings["PW_MANGOHUD"] == "1"
    assert settings["LAUNCH_PARAMETERS"] == '--option=value "quoted"'
    assert settings["WINEDLLOVERRIDES"] == "d3d11=n,b;dxgi=n"
    assert settings["PW_PREFIX_NAME"] == "GAME"
    assert settings["PW_WINDOWS_VER"] == "10"
    assert editable_game["ppdb"].read_text().startswith("# Keep this comment\n")


@pytest.mark.parametrize("change", [
    "PW_MANGOHUD=2", "NOT_A_SETTING=1", "PW_MANGOHUD", "PW_PREFIX_NAME=../other",
    "PW_PREFIX_NAME=", "PW_MANGOHUD=$(touch /tmp/forbidden)", "PW_MANGOHUD=1\ntrue",
    "LAUNCH_PARAMETERS=a|b", "LAUNCH_PARAMETERS=`id`",
])
def test_edit_game_rejects_invalid_values(editable_game: dict, change: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from portprotonqt.cli import edit_game

    run = MagicMock()
    monkeypatch.setattr("subprocess.run", run)
    before = editable_game["ppdb"].read_bytes()
    with pytest.raises(ValueError):
        edit_game(editable_game["id"], ["PW_MANGOHUD=1", change])
    run.assert_not_called()
    assert editable_game["ppdb"].read_bytes() == before


@pytest.mark.parametrize("source", ["portproton", "gog", "egs"])
def test_edit_game_sources(editable_game: dict, source: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from portprotonqt.cli import edit_game

    monkeypatch.setattr("portprotonqt.cli.list_games", lambda: [{**editable_game, "source": source}])
    edit_game(editable_game["id"], ["PW_MANGOHUD=1"])
    assert 'export PW_MANGOHUD="1"' in editable_game["ppdb"].read_text()


@pytest.mark.parametrize("mode", ["missing", "steam", "uninstalled", "no-script", "failed", "not-saved"])
def test_edit_game_errors(editable_game: dict, mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from portprotonqt.cli import edit_game

    if mode == "missing":
        monkeypatch.setattr("portprotonqt.cli.list_games", lambda: [])
    elif mode in {"steam", "uninstalled"}:
        game = {**editable_game, "source": "steam"} if mode == "steam" else {**editable_game, "executable": None}
        monkeypatch.setattr("portprotonqt.cli.list_games", lambda: [game])
    elif mode == "no-script":
        monkeypatch.setattr("portprotonqt.config.portproton.get_portproton_start_command", lambda: None)
    else:
        editable_game["script"].write_text("exit 4\n" if mode == "failed" else "exit 0\n")
    expected = RuntimeError if mode in {"failed", "not-saved"} else ValueError
    with pytest.raises(expected):
        edit_game(editable_game["id"], ["PW_MANGOHUD=1"])


@pytest.mark.parametrize("flags", [
    ["--set", "PW_MANGOHUD=1"], ["--edit-game", "gog:123"],
    ["--edit-game", "gog:123", "--set", "PW_MANGOHUD=1", "--list-games"],
])
def test_edit_game_argument_errors(flags: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["portprotonqt", *flags])
    with pytest.raises(SystemExit) as error:
        parse_args()
    assert error.value.code == 2


@pytest.mark.parametrize("failure", [False, True])
def test_edit_game_cli_output(failure: bool, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    import orjson
    from portprotonqt import app

    monkeypatch.setattr(sys, "argv", [
        "portprotonqt", "--edit-game", "gog:123", "--set", "PW_MANGOHUD=1", "--raw",
    ])
    edit = MagicMock(return_value={"id": "gog:123"})
    if failure:
        edit.side_effect = RuntimeError("write failed")
    monkeypatch.setattr("portprotonqt.cli.edit_game", edit)
    assert app.main() == (1 if failure else 0)
    output = capsys.readouterr().out
    assert output == "" if failure else orjson.loads(output) == {"id": "gog:123"}
    edit.assert_called_once_with("gog:123", ["PW_MANGOHUD=1"])


@pytest.mark.parametrize("single", [False, True])
@pytest.mark.parametrize("pretty", [False, True])
def test_library_selected_fields(single: bool, pretty: bool, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    import orjson
    from portprotonqt import app

    command = ["--game-info", "gog:123"] if single else ["--list-games"]
    monkeypatch.setattr(sys, "argv", [
        "portprotonqt", *command, "--fields", "executable, icon,name,source",
        "--pretty" if pretty else "--raw",
    ])
    monkeypatch.setattr("portprotonqt.cli.list_games", lambda: [
        {"id": "gog:123", "name": "Game", "icon": "icon.png", "source": "gog",
         "executable": "/games/game.exe", "description": "Not selected", "installed": True},
        {"id": "steam:456", "name": "Steam Game", "source": "steam", "installed": True},
    ])
    assert app.main() == 0
    output = capsys.readouterr().out
    expected = {"executable": "/games/game.exe", "icon": "icon.png", "name": "Game", "source": "gog"}
    assert orjson.loads(output) == (expected if single else [
        expected, {"executable": None, "icon": None, "name": "Steam Game", "source": "steam"},
    ])
    assert (len(output.splitlines()) > 1) is pretty


def test_library_selected_fields_empty(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    from portprotonqt import app

    monkeypatch.setattr(sys, "argv", ["portprotonqt", "--list-games", "--fields", "name"])
    monkeypatch.setattr("portprotonqt.cli.list_games", lambda: [])
    assert app.main() == 0
    assert capsys.readouterr().out == "[]\n"


@pytest.mark.parametrize("flags", [
    ["--fields", "name"], ["--list-games", "--fields", ""],
    ["--list-games", "--fields", "name,,icon"], ["--list-games", "--fields", "name,"],
    ["--list-games", "--fields", "name;icon"],
    ["--edit-game", "gog:123", "--set", "PW_MANGOHUD=1", "--fields", "name"],
])
def test_library_selected_fields_argument_errors(flags: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["portprotonqt", *flags])
    with pytest.raises(SystemExit) as error:
        parse_args()
    assert error.value.code == 2


@pytest.mark.parametrize("include_all", [False, True])
def test_list_games_installed_filter(include_all: bool, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    import orjson
    from portprotonqt import app

    arguments = ["portprotonqt", "--list-games", "--fields", "id", "--raw"]
    if include_all:
        arguments.append("--all")
    monkeypatch.setattr(sys, "argv", arguments)
    games = [
        {"id": "portproton:missing.desktop", "installed": False},
        {"id": "steam:123", "installed": True},
        {"id": "gog:456", "installed": False},
        {"id": "egs:789", "installed": True},
    ]
    monkeypatch.setattr("portprotonqt.cli.list_games", lambda: games)
    assert app.main() == 0
    expected = [game for game in games if include_all or game["installed"]]
    assert orjson.loads(capsys.readouterr().out) == [{"id": game["id"]} for game in expected]


@pytest.mark.parametrize("flags", [["--all"], ["--game-info", "gog:123", "--all"]])
def test_all_requires_list_games(flags: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["portprotonqt", *flags])
    with pytest.raises(SystemExit) as error:
        parse_args()
    assert error.value.code == 2
