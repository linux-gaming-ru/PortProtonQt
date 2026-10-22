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
