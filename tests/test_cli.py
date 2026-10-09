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
    PP_EXTENSIONS,
    PREFIX_BACKUP_EXTENSION,
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


@pytest.mark.parametrize("stopped", [False, True])
def test_silent_tray_toggles_pause(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stopped: bool) -> None:
    import signal
    import psutil
    from PySide6.QtWidgets import QApplication
    from portprotonqt import app, time_utils

    qt_app = QApplication.instance() or QApplication([])
    assert isinstance(qt_app, QApplication)
    tray = MagicMock()
    timer = MagicMock()
    launcher = MagicMock(pid=123)
    launcher.poll.return_value = None
    child = MagicMock(pid=124)
    status = psutil.STATUS_STOPPED if stopped else psutil.STATUS_RUNNING
    child.status.return_value = status
    parent = MagicMock()
    parent.children.return_value = [child]
    monkeypatch.setattr(app, "QSystemTrayIcon", MagicMock(return_value=tray))
    monkeypatch.setattr(app, "QTimer", MagicMock(return_value=timer))
    monkeypatch.setattr(app, "get_portproton_tray_icon", MagicMock())
    monkeypatch.setattr(app.subprocess, "Popen", MagicMock(return_value=launcher))
    monkeypatch.setattr(app.psutil, "Process", MagicMock(return_value=parent))
    monkeypatch.setattr(time_utils, "save_last_launch", MagicMock())
    monkeypatch.setattr(time_utils, "save_playtime", MagicMock())

    app.run_silent_tray(qt_app, ["start.sh"], str(tmp_path / "game.exe"))
    menu = tray.setContextMenu.call_args.args[0]
    menu.aboutToShow.emit()
    pause, stop, tools = menu.actions()
    assert tools.menu() is not None
    assert pause.isEnabled()
    assert pause.text() == app._("Resume Game" if stopped else "Pause Game")
    assert stop.text() == app._("Stop Game")
    pause.trigger()
    child.send_signal.assert_called_once_with(signal.SIGCONT if stopped else signal.SIGSTOP)
    parent.children.assert_called_with(recursive=True)

    parent.children.return_value = []
    menu.aboutToShow.emit()
    assert not pause.isEnabled()
    pause.trigger()
    assert child.send_signal.call_count == 1


@pytest.fixture
def silent_startup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    from PySide6 import QtNetwork
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
    socket = MagicMock()
    socket.waitForConnected.return_value = False
    server = MagicMock()
    monkeypatch.setattr(QtNetwork, "QLocalSocket", MagicMock(return_value=socket))
    monkeypatch.setattr(QtNetwork, "QLocalServer", server)
    tray = MagicMock()
    window = MagicMock(side_effect=RuntimeError("main window reached"))
    monkeypatch.setattr(app, "run_silent_tray", tray)
    monkeypatch.setattr(main_window, "MainWindow", window)
    exe = tmp_path / "my game.exe"
    exe.touch()
    return SimpleNamespace(app=app, qt_app=qt_app, socket=socket, server=server,
                           tray=tray, window=window, exe=exe)


@pytest.mark.parametrize("file_uri", [False, True])
def test_silent_exe_keeps_main_window_for_emulation(
    silent_startup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, file_uri: bool,
) -> None:
    startup = silent_startup
    target = startup.exe.as_uri() if file_uri else str(startup.exe)
    monkeypatch.setattr(sys, "argv", ["portprotonqt", "--silent", target])

    with pytest.raises(RuntimeError, match="main window reached"):
        startup.app.main()

    startup.tray.assert_not_called()
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
    startup.tray.assert_not_called()
    startup.window.assert_not_called()
    startup.qt_app.exec.assert_not_called()


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

    startup.tray.assert_not_called()
    startup.window.assert_called_once()


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

    def test_ppack_extension_constant(self):
        assert PREFIX_BACKUP_EXTENSION == ".ppack"


class TestIsAutoinstallFile:
    def test_ppai_file(self, tmp_path: Path):
        ppai = tmp_path / "installer.ppai"
        ppai.touch()
        assert is_autoinstall_file(str(ppai)) is True

    def test_not_ppai(self, tmp_path: Path):
        txt = tmp_path / "installer.txt"
        txt.touch()
        assert is_autoinstall_file(str(txt)) is False

    def test_ppai_extension_constant(self):
        assert PP_EXTENSIONS == (".ppack", ".ppai")


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
