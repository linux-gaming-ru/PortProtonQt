"""Native desktop discovery, library completion and launch regressions."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock
import shutil
import sys
import os
import signal
import subprocess
from datetime import datetime, timedelta

import pytest
from PySide6.QtCore import QEventLoop, QStandardPaths, QThread, QTimer, Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QPushButton
from PySide6.QtGui import QIcon

from portprotonqt.config import favorites_config, game_config
from portprotonqt.context_menu_manager import ContextMenuManager
from portprotonqt.main_window import MainWindow
from portprotonqt.localization import _
from portprotonqt.native_games import (
    NativeLibraryWorker, read_native_game, create_native_desktop_file, get_native_launch,
    save_native_settings, load_native_settings, build_native_launch_command,
)


@pytest.fixture(autouse=True)
def isolated_native_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.delenv("FLATPAK_ID", raising=False)
    monkeypatch.setattr("portprotonqt.native_games.get_portproton_scripts_path", lambda: None)
    monkeypatch.setattr("portprotonqt.context_menu_manager.is_game_in_steam", lambda _name: False)
    monkeypatch.setattr("portprotonqt.tabs.library_tab.is_game_in_steam", lambda _name: False)
    monkeypatch.setattr("portprotonqt.debug_utils.debug_log_manager.generate_system_info", lambda *_args: "Operating system: test\nCPU: test")
    monkeypatch.setattr("portprotonqt.time_utils._stats_migrated", True)
    from portprotonqt.native_games import get_native_ppdb_path
    monkeypatch.setattr("portprotonqt.native_games.get_native_ppdb_path", lambda desktop, settings:
                        (path if path.is_relative_to(tmp_path) else tmp_path / path.name)
                        if (path := get_native_ppdb_path(desktop, settings)) else path)
    monkeypatch.setattr(QStandardPaths, "writableLocation", lambda _location: str(tmp_path / "Desktop"))


@pytest.mark.parametrize("extra", [
    "Hidden=true", "NoDisplay=true", "Type=Link", "Categories=ArcadeGame;",
    "Exec=steam steam://rungameid/42", 'Exec=wine "game.exe"',
    "TryExec=missing-native-game-test",
    'Exec="unterminated', "Exec=", "Name=",
    "MimeType=x-scheme-handler/unknown-launcher;",
])
def test_discovery_rejects_unavailable_or_non_native_entries(tmp_path: Path, extra: str) -> None:
    path = tmp_path / "game.desktop"
    path.write_text("[Desktop Entry]\nType=Application\nName=Game\nExec=true\nCategories=Game;\n" + extra + "\n")
    assert read_native_game(path) is None


@pytest.mark.parametrize("command", ["custom-wrapper --game", "flatpak run org.example.Game"])
def test_discovery_does_not_depend_on_launcher_names(tmp_path: Path, command: str) -> None:
    path = tmp_path / "game.desktop"
    path.write_text("[Desktop Entry]\nType=Application\nName=Game\nCategories=Game;\nExec=" + command + "\n")
    game = read_native_game(path)
    assert game is not None
    assert game[5] == "native://" + str(path)


def test_scan_respects_xdg_overrides_and_flatpak_exports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, system = tmp_path / "user", tmp_path / "system"
    monkeypatch.setenv("XDG_DATA_HOME", str(home))
    monkeypatch.setenv("XDG_DATA_DIRS", str(system))
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    monkeypatch.setattr(QStandardPaths, "writableLocation", lambda _location: str(desktop))
    entry = "[Desktop Entry]\nType=Application\nName=Native Game\nExec=true %U\nCategories=Game;\n"
    for root in (home, system, home / "flatpak/exports/share"):
        (root / "applications").mkdir(parents=True)
    (system / "applications/hidden.desktop").write_text(entry)
    (home / "applications/hidden.desktop").write_text("[Desktop Entry]\nHidden=true\n")
    path = home / "applications/game.desktop"
    path.write_text(entry)
    (system / "applications/game.desktop").write_text(entry)
    (home / "flatpak/exports/share/applications/flatpak.desktop").write_text(entry.replace("Native Game", "Flatpak Game"))
    (desktop / "desktop.desktop").write_text(entry.replace("Native Game", "Desktop Game"))
    original_rglob = Path.rglob
    monkeypatch.setattr(Path, "rglob", lambda path, pattern:
                        original_rglob(path, pattern) if path.is_relative_to(tmp_path) else iter(()))
    worker = NativeLibraryWorker()
    worker.run()
    assert [game[0] for game in worker.games] == ["Native Game", "Flatpak Game", "Desktop Game"]
    assert worker.games[0][5] == "native://" + str(path)
    assert all(game[12] == "native" for game in worker.games)
    assert path.read_text() == entry


@pytest.mark.parametrize("display_filter", ["all", "favorites", "native"])
def test_native_source_completes_library_loading(
    monkeypatch: pytest.MonkeyPatch, display_filter: str,
) -> None:
    monkeypatch.setattr(game_config, "get_display_filter", lambda: display_filter)
    monkeypatch.setattr(game_config, "get_only_installed", lambda: False)
    monkeypatch.setattr(favorites_config, "get_games", lambda: ["Native"])
    game = ("Native", "", "", "", "", "native:///game.desktop")
    window = cast(Any, SimpleNamespace(
        _loading_games=False, launch_exe=None, games_loaded=MagicMock(),
        _load_portproton_games_async=lambda callback: callback([]),
        _load_steam_games_async=lambda callback: callback([]),
        _load_gog_games_async=lambda callback: callback([]),
        _load_egs_games_async=lambda callback: callback([]),
        _load_native_games_async=lambda callback: callback([game]),
    ))
    MainWindow.loadGames(window)
    window.games_loaded.emit.assert_called_once_with([game])


def test_native_launch_preserves_desktop_file_and_bypasses_wine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "Game with spaces.desktop"
    path.write_text(f"[Desktop Entry]\nExec=game %U\nPath={tmp_path}\n")
    process = MagicMock(pid=1234)
    popen = MagicMock(return_value=process)
    monkeypatch.setattr("portprotonqt.main_window.subprocess.Popen", popen)
    monkeypatch.setattr("portprotonqt.main_window.save_last_launch", MagicMock())
    monkeypatch.setattr("portprotonqt.main_window.QTimer", MagicMock())
    window = cast(Any, SimpleNamespace(
        game_processes=[], input_manager=MagicMock(), _update_last_launch_after_start=MagicMock(),
        _start_launch_output_reader=MagicMock(), _set_running_button_stop=MagicMock(), checkTargetExe=MagicMock(),
    ))
    button = MagicMock()
    MainWindow._launch_native_game(window, "native://" + str(path), button)
    assert popen.call_args.args[0] == ["game"]
    assert popen.call_args.kwargs["cwd"] == str(tmp_path)
    assert popen.call_args.kwargs["start_new_session"]
    assert window.game_processes == [process]
    assert window.current_running_button is button
    assert window.native_game_running
    window._set_running_button_stop.assert_called_once()


def test_native_context_launch_does_not_require_portproton() -> None:
    parent = SimpleNamespace(toggleGame=MagicMock())
    manager = cast(Any, SimpleNamespace(parent=parent))
    card = SimpleNamespace(game_source="native", exec_line="native:///game.desktop", name="Game")
    ContextMenuManager._launch_game(manager, card)
    parent.toggleGame.assert_called_once_with(card.exec_line, game_name="Game")


def test_native_scan_completes_once_on_owner_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow.__new__(MainWindow)
    QMainWindow.__init__(window)
    monkeypatch.setattr(NativeLibraryWorker, "run", lambda self: None)
    results: list[tuple[list, QThread]] = []
    loop = QEventLoop()

    def completed(games: list) -> None:
        results.append((games, QThread.currentThread()))
        loop.quit()

    window._load_native_games_async(completed)
    worker = window.native_library_worker
    assert worker is not None
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    worker.wait()
    app.processEvents()
    assert results == [([], window.thread())]
    assert window.native_library_worker is None
    window.deleteLater()


@pytest.mark.parametrize("filename", ['start', 'game with spaces', 'game%name$"\\test'])
def test_manual_native_shortcut_round_trips_linux_paths(
    tmp_path: Path, filename: str,
) -> None:
    executable = tmp_path / filename
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    result = create_native_desktop_file(str(executable), "My Native Game")
    assert result is not None
    content, destination = result
    Path(destination).write_text(content)
    assert get_native_launch(destination) == ([str(executable)], str(tmp_path))
    game = read_native_game(Path(destination))
    assert game is not None and game[12] == "native"


@pytest.mark.parametrize("custom_icon", [False, True])
def test_native_shortcut_uses_saved_icon_or_theme_fallback(
    tmp_path: Path, custom_icon: bool,
) -> None:
    from portprotonqt.config import get_custom_data_dir_name

    executable = tmp_path / "start"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    icon = Path(os.environ["XDG_DATA_HOME"]) / "PortProtonQt/custom_data" / get_custom_data_dir_name(str(executable)) / "icon.png"
    if custom_icon:
        icon.parent.mkdir(parents=True)
        icon.write_bytes(b"saved icon")
    result = create_native_desktop_file(str(executable), "Native")
    assert result is not None
    content, _destination = result
    assert f"Icon={icon if custom_icon else 'applications-games'}\n" in content


def test_saved_native_desktop_has_valid_keys_and_preserves_settings(tmp_path: Path) -> None:
    executable = tmp_path / "start"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    result = create_native_desktop_file(str(executable), "Native")
    assert result is not None
    content, destination = result
    Path(destination).write_text(content + "\n[X-PortProtonQt]\nPW_USE_GAMEMODE=1\n")
    save_native_settings(destination, {})
    saved = Path(destination).read_text()
    assert "[X-PortProtonQt]" not in saved
    assert "PW_USE_GAMEMODE" not in saved
    assert f'Exec="portprotonqt" "--silent" "{executable}"\n' in saved
    assert "gamemoderun" not in saved
    assert 'export PW_USE_GAMEMODE="1"' in Path(str(executable) + ".ppdb").read_text()
    assert load_native_settings(destination)["PW_USE_GAMEMODE"] == "1"
    assert "gamemoderun" in get_native_launch(destination)[0]
    validator = shutil.which("desktop-file-validate")
    if validator:
        checked = subprocess.run([validator, destination], capture_output=True, text=True)
        assert checked.returncode == 0, checked.stdout + checked.stderr


@pytest.mark.parametrize("package", ["native", "flatpak", "appimage"])
def test_native_desktop_matches_standard_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, package: str,
) -> None:
    import configparser
    import shlex

    executable = tmp_path / "start"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    launcher = ["portprotonqt"]
    if package == "flatpak":
        monkeypatch.setenv("FLATPAK_ID", "test.PortProtonQt")
        launcher = ["flatpak", "run", "test.PortProtonQt"]
    elif package == "appimage":
        appimage = tmp_path / "PortProtonQt portable"
        appimage.touch()
        monkeypatch.setenv("APPIMAGE", str(appimage))
        launcher = [str(appimage)]
    content, destination = cast(tuple[str, str], create_native_desktop_file(str(executable), "Native"))
    Path(destination).write_text(content)
    save_native_settings(destination, {})
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(destination)
    assert parser["Desktop Entry"]["Comment"] == _('Launch "{name}" with PortProton').format(name="Native")
    assert parser["Desktop Entry"]["Actions"] == "RunSilent;RunLog;"
    for section, mode in (("Desktop Entry", "--silent"), ("Desktop Action RunSilent", "--silent"),
                          ("Desktop Action RunLog", "--log")):
        assert shlex.split(parser[section]["Exec"]) == [*launcher, mode, str(executable)]
        assert parser[section]["Icon"] == parser["Desktop Entry"]["Icon"]
    assert get_native_launch(destination) == ([str(executable)], str(tmp_path))


def test_native_settings_use_shared_linux_tools_without_wine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "start"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    result = create_native_desktop_file(str(executable), "Native")
    assert result is not None
    content, destination = result
    Path(destination).write_text(content)
    changes = {"PW_MANGOHUD": "1", "MANGOHUD_CONFIG": "fps,cpu_temp", "PW_USE_GAMEMODE": "1",
               "PW_GAMESCOPE": "1", "PW_GAMESCOPE_ARGS_NEW": "-f -w 1280", "LAUNCH_PARAMETERS": '--name "a b"',
               "PW_VKBASALT": "1", "PW_VKBASALT_EFFECTS": "cas", "PW_VKBASALT_FFX_CAS": "0.75"}
    monkeypatch.setattr("portprotonqt.native_games.get_native_tool_paths", lambda: {})
    save_native_settings(destination, changes)
    command, directory = get_native_launch(destination)
    assert "gamescope" in command and "gamemoderun" in command and "mangohud" in command
    assert "ENABLE_VKBASALT=1" in command
    assert "MANGOHUD_CONFIG=fps,cpu_temp" in command
    assert command[-3:] == [str(executable), "--name", "a b"]
    assert directory == str(tmp_path)
    assert "casSharpness = 0.75" in Path(destination).with_suffix(".vkbasalt.conf").read_text()
    assert load_native_settings(destination)["PW_USE_GAMEMODE"] == "1"
    save_native_settings(destination, {"PW_USE_GAMEMODE": "0"})
    assert "gamemoderun" not in get_native_launch(destination)[0]
    assert Path(str(executable) + ".ppdb").is_file()


def test_native_container_uses_existing_runtime_without_wine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    wrapper = runtime / "pressure-vessel/bin/pressure-vessel-unruntime"
    wrapper.parent.mkdir(parents=True)
    wrapper.touch()
    (runtime / "runtime/files").mkdir(parents=True)
    monkeypatch.setattr("portprotonqt.native_games.get_native_tool_paths", lambda: {"runtime": str(runtime)})
    command = build_native_launch_command('"/game/start"', {"PW_USE_RUNTIME": "1"})
    assert "pressure-vessel-unruntime" in command
    assert "PRESSURE_VESSEL_RUNTIME_BASE=" in command
    assert "wine" not in command.lower()


def test_native_metadata_completes_once_and_preserves_custom_cover(monkeypatch: pytest.MonkeyPatch) -> None:
    callbacks = []
    monkeypatch.setattr("portprotonqt.main_window.ui_config.get_economy_mode", lambda: False)
    monkeypatch.setattr("portprotonqt.main_window.get_steam_game_info_async", lambda _name, _exec, callback: callbacks.append(callback))
    games = [("Game", "", "custom.png", "", "", "native:///a.desktop"),
             ("Other", "", "", "", "", "native:///b.desktop")]
    complete = MagicMock()
    window = SimpleNamespace(native_library_worker=SimpleNamespace(games=games, deleteLater=MagicMock()),
                             _native_games_callback=complete)
    MainWindow._on_native_games_loaded(cast(Any, window))
    callbacks[1]({"cover": "downloaded.jpg"})
    complete.assert_not_called()
    callbacks[0]({"cover": "wrong.jpg"})
    complete.assert_called_once()
    result = complete.call_args.args[0]
    assert [game[2] for game in result] == ["downloaded.jpg", "custom.png"]


def test_native_stop_uses_own_process_group_without_portproton() -> None:
    stop = MagicMock()
    window = SimpleNamespace(native_game_running=True, _terminate_game_processes=stop)
    assert MainWindow.stop_running_game(cast(Any, window))
    stop.assert_called_once()


def test_native_settings_show_linux_tabs_and_ppdb_without_wine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from portprotonqt.dialogs.settings_dialog import ExeSettingsDialog
    from portprotonqt.dialogs.settings_gamescope import GamescopeSettingsMixin
    from portprotonqt.theme_manager import load_theme
    _app = QApplication.instance() or QApplication([])
    path = tmp_path / "native.desktop"
    path.write_text(f'[Desktop Entry]\nType=Application\nName=Native\nExec="/game/start"\nPath={tmp_path}\n')
    monkeypatch.setattr("portprotonqt.dialogs.settings_dialog.get_portproton_location", lambda: None)
    monkeypatch.setattr("portprotonqt.dialogs.settings_dialog.get_portproton_start_command", lambda: None)
    monkeypatch.setattr("portprotonqt.native_games.get_native_tool_paths", lambda: {})
    monkeypatch.setattr(GamescopeSettingsMixin, "_detect_gamescope_supported_options", lambda _self: None)
    monkeypatch.setattr(ExeSettingsDialog, "init_virtual_keyboard", lambda self: setattr(self, "keyboard", QWidget(self)))
    original_which = shutil.which
    monkeypatch.setattr(shutil, "which", lambda command: "/fake/gamescope" if command == "gamescope" else original_which(command))
    dialog = ExeSettingsDialog(theme=load_theme("standart"), exe_path=str(path), game_source="native")
    keys = {item.data(Qt.ItemDataRole.UserRole) for row in range(dialog.settings_table.rowCount())
            if (item := dialog.settings_table.item(row, 0)) is not None}
    assert {"PW_USE_GAMEMODE", "PW_USE_RUNTIME"} <= keys
    assert not ({"PW_WINE_USE", "PW_PREFIX_NAME", "PW_USE_ESYNC"} & keys)
    assert not ({"PW_WINE_USE", "WINEDLLOVERRIDES"} & dialog.advanced_settings_by_key.keys())
    assert not ({"Exec", "Path"} & dialog.advanced_settings_by_key.keys())
    tabs = {dialog.tab_widget.tabText(index) for index in range(dialog.tab_widget.count())}
    assert {"MangoHud", "vkBasalt", "Gamescope"} <= tabs
    assert not dialog.open_ppdb_button.isHidden()
    assert not dialog.clear_ppdb_button.isHidden()
    assert dialog.current_settings["Exec"] == '"/game/start"'
    dialog.close()
    dialog.deleteLater()


@pytest.mark.parametrize("action", ["confirm", "cancel", "missing"])
def test_native_clear_ppdb_uses_executable_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action: str,
) -> None:
    from PySide6.QtWidgets import QMessageBox
    from portprotonqt.dialogs.settings_dialog import ExeSettingsDialog
    _app = QApplication.instance() or QApplication([])
    executable = tmp_path / "start"
    executable.touch()
    desktop = tmp_path / "native.desktop"
    desktop.write_text(f'[Desktop Entry]\nName=Native\nExec="{executable}"\nPath={tmp_path}\n')
    database = Path(str(executable) + ".ppdb")
    if action != "missing":
        database.write_text('export PW_USE_RUNTIME="1"\n')
    dialog = cast(Any, QWidget())
    dialog.exe_path = str(desktop)
    dialog.game_source = "native"
    dialog.load_current_settings = MagicMock()
    monkeypatch.setattr(QMessageBox, "exec", lambda _self:
                        QMessageBox.StandardButton.Yes if action == "confirm" else QMessageBox.StandardButton.No)
    monkeypatch.setattr(QMessageBox, "information", MagicMock())
    ExeSettingsDialog.clear_ppdb_file(dialog)
    assert database.exists() is (action == "cancel")
    assert desktop.is_file()
    assert dialog.load_current_settings.call_count == (0 if action == "cancel" else 1)
    if action != "cancel":
        assert load_native_settings(str(desktop))["PW_USE_RUNTIME"] == "0"
    dialog.close()
    dialog.deleteLater()


@pytest.mark.parametrize("matched", [False, True])
def test_native_metadata_skips_pe_protondb_and_uses_cover_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, matched: bool,
) -> None:
    import portprotonqt.steam_api.api as api
    monkeypatch.setattr(api.ui_config, "get_economy_mode", lambda: False)
    monkeypatch.setattr(api, "CacheManager", lambda: SimpleNamespace(
        is_fresh=lambda *_: False, save_json=MagicMock(), cache_dir=tmp_path,
    ))
    monkeypatch.setattr(api, "get_steam_apps_and_index_async", lambda callback: callback(([{}], {"game": {}})))
    monkeypatch.setattr(api, "search_app", lambda *_: {"appid": 42} if matched else None)
    monkeypatch.setattr(api, "fetch_app_info_async", lambda _appid, callback: callback({"name": "Game"}))
    monkeypatch.setattr(api, "fetch_sgdb_cover_async", lambda _name, callback: callback("actual-cover.jpg"))
    monkeypatch.setattr(api, "get_local_steam_cover", lambda *_args, **_kwargs: "")
    pe = MagicMock(side_effect=AssertionError("Native games must not use PE metadata"))
    protondb = MagicMock(side_effect=AssertionError("Native games must not query ProtonDB"))
    monkeypatch.setattr("portprotonqt.steam_api.cache.get_exiftool_data", pe)
    monkeypatch.setattr(api, "get_protondb_tier_async", protondb)
    results = []
    api.get_steam_game_info_async("Game", "native:///Game With Spaces.desktop", results.append)
    assert len(results) == 1
    assert results[0]["cover"] == "actual-cover.jpg"
    pe.assert_not_called()
    protondb.assert_not_called()


def test_native_process_group_remains_running_after_wrapper_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    process = SimpleNamespace(pid=42, poll=lambda: 0)
    child = SimpleNamespace(pid=43, info={"status": "running"})
    window = SimpleNamespace(native_game_running=True, game_processes=[process])
    monkeypatch.setattr("portprotonqt.main_window.psutil.process_iter", lambda **_: [child])
    monkeypatch.setattr("portprotonqt.main_window.os.getpgid", lambda _pid: 42)
    assert MainWindow._has_running_game_process(cast(Any, window))
    child.info["status"] = "zombie"
    assert not MainWindow._has_running_game_process(cast(Any, window))


def test_native_play_stop_cycle_controls_a_real_linux_process(tmp_path: Path) -> None:
    _app = QApplication.instance() or QApplication([])
    result = create_native_desktop_file(sys.executable, "Native process test")
    assert result is not None
    content, destination = result
    Path(destination).write_text(content)
    save_native_settings(destination, {"LAUNCH_PARAMETERS": '-c "import time; time.sleep(30)"'})
    window = MainWindow.__new__(MainWindow)
    QMainWindow.__init__(window)
    test_window = cast(Any, window)
    test_window.game_processes = []
    test_window.input_manager = MagicMock()
    test_window.theme_manager = SimpleNamespace(get_icon=lambda *_args, **_kwargs: QIcon())
    test_window._update_last_launch_after_start = MagicMock()
    test_window._update_playtime_after_exit = MagicMock()
    test_window._refresh_portproton_shortcuts = MagicMock()
    button = QPushButton()
    uri = "native://" + destination
    process = None
    try:
        window.toggleGame(uri, button)
        process = window.game_processes[0]
        assert button.text() == _("Stop")
        assert process.poll() is None
        window.game_start_time = datetime.now() - timedelta(seconds=3)
        window.toggleGame(uri, button)
        process.wait(timeout=5)
        window.checkTargetExe()
        assert button.text() == _("Start")
        assert window.target_exe is None
        assert window.game_processes == []
        assert not window.native_game_running
        test_window._update_playtime_after_exit.assert_called_once()
    finally:
        if process is None and window.game_processes:
            process = window.game_processes[0]
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        timer = getattr(window, "checkProcessTimer", None)
        if timer is not None:
            timer.stop()
        window.deleteLater()


@pytest.mark.parametrize("switch_source", [False, True])
def test_manual_native_add_creates_shortcuts_and_respects_late_source_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, switch_source: bool,
) -> None:
    import portprotonqt.tabs.library_tab as tab
    from PySide6.QtWidgets import QDialog
    callbacks, selected = [], ["native"]
    executable = tmp_path / "start"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    dialog = SimpleNamespace(
        setFocus=MagicMock(), finished=MagicMock(), exec=lambda: QDialog.DialogCode.Accepted,
        nameEdit=SimpleNamespace(text=lambda: "Native"), exeEdit=SimpleNamespace(text=lambda: str(executable)),
        coverEdit=SimpleNamespace(text=lambda: ""), last_cover_path="",
        native_checkbox=SimpleNamespace(isChecked=lambda: True),
        add_to_menu_checkbox=SimpleNamespace(isChecked=lambda: True),
        add_to_desktop_checkbox=SimpleNamespace(isChecked=lambda: True),
        add_to_steam_checkbox=SimpleNamespace(isChecked=lambda: False),
        getDesktopEntryData=lambda: create_native_desktop_file(str(executable), "Native"),
    )
    monkeypatch.setattr(tab, "AddGameDialog", lambda *_: dialog)
    monkeypatch.setattr(tab.ui_config, "get_auto_download_ppdb", lambda: False)
    monkeypatch.setattr(tab.ui_config, "get_economy_mode", lambda: False)
    monkeypatch.setattr(game_config, "get_display_filter", lambda: selected[0])
    monkeypatch.setattr("portprotonqt.steam_api.get_steam_game_info_async", lambda _name, _exec, callback: callbacks.append(callback))
    window = MainWindow.__new__(MainWindow)
    owner = cast(Any, window)
    owner.current_add_game_dialog, owner.theme = None, None
    owner._loaded_library_cache = {source: [] for source in ("all", "native", "steam", "favorites")}
    owner.game_library_manager = SimpleNamespace(add_game_incremental=MagicMock(), load_visible_images=MagicMock())
    owner._write_desktop_file = lambda content, path: Path(path).write_text(content)
    window.openAddGameDialog()
    assert set(owner._loaded_library_cache) == {"steam"}
    selected[0] = "steam" if switch_source else "native"
    callbacks[0]({"cover": "cover.jpg"})
    assert owner.game_library_manager.add_game_incremental.call_count == int(not switch_source)
    if not switch_source:
        assert owner.game_library_manager.add_game_incremental.call_args.args[0][12] == "native"
    data_home = Path(os.environ["XDG_DATA_HOME"])
    saved = list((data_home / "PortProtonQt/native_games").glob("*.desktop"))
    assert len(saved) == 1
    assert Path(str(executable) + ".ppdb").is_file()
    for directory in (data_home / "applications", tmp_path / "Desktop"):
        assert (directory / saved[0].name).read_text() == saved[0].read_text()


def test_native_ppdb_edits_apply_cpu_affinity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    executable = tmp_path / "game"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    content, destination = cast(tuple[str, str], create_native_desktop_file(str(executable), "Game"))
    Path(destination).write_text(content)
    monkeypatch.setattr(os, "sched_getaffinity", lambda _pid: {2, 4, 6})
    save_native_settings(destination, {"PW_WINE_CPU_TOPOLOGY": "2"})
    assert get_native_launch(destination)[0] == ["taskset", "-c", "2,4", str(executable)]
    database = Path(str(executable) + ".ppdb")
    database.write_text(database.read_text().replace('PW_WINE_CPU_TOPOLOGY="2"', 'PW_WINE_CPU_TOPOLOGY="1"'))
    assert get_native_launch(destination)[0] == ["taskset", "-c", "2", str(executable)]
    with pytest.raises(ValueError, match="CPU cores"):
        build_native_launch_command("game", {"PW_WINE_CPU_TOPOLOGY": "4"})


def test_native_debug_log_captures_output_without_portproton(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from portprotonqt.debug_utils.debug_log_manager import DebugLogManager

    monkeypatch.setattr("portprotonqt.debug_utils.debug_log_manager.get_portproton_location", lambda: None)
    entry = tmp_path / "game.desktop"
    entry.write_text(f'[Desktop Entry]\nExec="{sys.executable}" -c "import sys; sys.stdout.write(\\\"native output\\\"); sys.stderr.write(\\\"native error\\\")"\nPath={tmp_path}\n')
    manager = DebugLogManager()
    assert manager.start("native://" + str(entry), [])
    assert manager.process is not None
    manager.process.wait(timeout=5)
    assert not manager.check_running()
    destination = manager.stop()
    assert destination == str(tmp_path / "PortProtonQt.log")
    assert destination is not None
    log = Path(destination).read_text()
    assert "native output" in log and "native error" in log
    assert manager.native_output is None


def test_native_folder_opens_working_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from portprotonqt.detail_pages import DetailPageManager

    entry = tmp_path / "game.desktop"
    entry.write_text(f"[Desktop Entry]\nExec=true\nPath={tmp_path}\n")
    opened = MagicMock(return_value=True)
    monkeypatch.setattr("portprotonqt.detail_pages.QDesktopServices.openUrl", opened)
    manager = DetailPageManager.__new__(DetailPageManager)
    manager._open_executable_folder("native://" + str(entry))
    assert opened.call_args.args[0].toLocalFile() == str(tmp_path)


def test_native_debug_shutdown_saves_log(tmp_path: Path) -> None:
    from portprotonqt.debug_utils.debug_log_manager import DebugLogManager

    entry = tmp_path / "game.desktop"
    entry.write_text(f'[Desktop Entry]\nExec="{sys.executable}" -c "import time; time.sleep(30)"\nPath={tmp_path}\n')
    manager = DebugLogManager()
    assert manager.start("native://" + str(entry), [])
    process = manager.process
    assert process is not None
    try:
        manager.cleanup_on_exit()
        process.wait(timeout=5)
        assert (tmp_path / "PortProtonQt.log").is_file()
        assert manager.native_output is None
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def test_native_folder_without_path_uses_game_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from portprotonqt.detail_pages import DetailPageManager

    executable = tmp_path / "game"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    entry = tmp_path / "game.desktop"
    entry.write_text(f'[Desktop Entry]\nExec=env TEST=1 "{executable}"\n')
    assert get_native_launch(str(entry))[1] == str(tmp_path)
    opened = MagicMock(return_value=True)
    monkeypatch.setattr("portprotonqt.detail_pages.QDesktopServices.openUrl", opened)
    manager = DetailPageManager.__new__(DetailPageManager)
    manager._open_executable_folder("native://" + str(entry))
    assert opened.call_args.args[0].toLocalFile() == str(tmp_path)


@pytest.mark.parametrize("native", [True, False])
def test_debug_report_keeps_system_sections_and_filters_wine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, native: bool,
) -> None:
    from portprotonqt.debug_utils import system_info, env_utils

    executable = tmp_path / "game"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    entry = tmp_path / "game.desktop"
    entry.write_text(f'[Desktop Entry]\nExec="{executable}"\nPath={tmp_path}\n')
    Path(str(executable) + ".ppdb").write_text('export PW_USE_RUNTIME="0"\n')
    monkeypatch.setattr("portprotonqt.config.get_portproton_location", lambda: None if native else str(tmp_path))
    monkeypatch.setattr("portprotonqt.native_games.get_native_tool_paths", lambda: {})
    for name in ("get_libc_version", "get_os_info", "get_ram_info_detailed", "get_graphics_info_detailed",
                 "get_locale_info", "get_locale_available"):
        monkeypatch.setattr(system_info, name, lambda: "system detail")
    monkeypatch.setattr(system_info, "get_screen_info", lambda: ("screen detail", "primary screen"))
    monkeypatch.setattr(system_info, "get_cpu_info", lambda: {"model": "CPU detail", "physical_cores": "2", "logical_cores": "4"})
    monkeypatch.setattr(system_info, "get_filesystem_info", lambda *_args: "filesystem detail")
    for name in ("get_vulkan_use_info", "get_wine_version", "get_d3d_extras_status"):
        def wine_only(*args: object) -> str:
            assert not native
            return "wine detail"
        monkeypatch.setattr(env_utils, name, wine_only)
    monkeypatch.setattr(system_info, "get_prefix_name", lambda _path: pytest.fail("native prefix lookup") if native else "DEFAULT")
    monkeypatch.setattr(system_info, "get_winetricks_log", lambda *_args: "winetricks detail")
    report = system_info.generate_system_info("native://" + str(entry) if native else str(executable))
    for heading in ("Operating system:", "CPU:", "RAM:", "Kernel:", "Graphic cards and drivers:", "locale:"):
        assert heading in report
    assert "screen detail" in report and "filesystem detail" in report
    assert ("Version WINE in use:" in report) is not native
    assert ("winetricks.log:" in report) is not native
    assert ("Program bit depth:" in report) is not native
    if native:
        assert 'PW_USE_RUNTIME="0"' in report
        assert str(executable) in report


def test_native_ppdb_migrates_settings_and_var_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from portprotonqt.native_games import read_native_variables, get_native_defaults

    executable = tmp_path / "start"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    entry = tmp_path / "game.desktop"
    entry.write_text(f'[Desktop Entry]\nExec="{executable}"\nPath={tmp_path}\n[X-PortProtonQt]\nPW_MANGOHUD=1\n')
    Path(str(entry) + ".ppdb").write_text('[X-PortProtonQt]\nPW_USE_GAMEMODE=1\n')
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "var").write_text('check_variables PW_VKBASALT_FFX_CAS "0.50"\ncheck_variables PW_USE_RUNTIME "1"\nexport DEFAULT_MANGOHUD_CONFIG="fps,cpu_temp,wine,winesync"\n')
    monkeypatch.setattr("portprotonqt.native_games.get_portproton_scripts_path", lambda: str(scripts))
    assert get_native_defaults()["PW_USE_RUNTIME"] == "0"
    save_native_settings(str(entry), {"LAUNCH_PARAMETERS": '--name "a b" --literal "$HOME`id`"'})
    database = Path(str(executable) + ".ppdb")
    content = database.read_text()
    assert content.startswith("export ") and "[X-PortProtonQt]" not in content
    values = read_native_variables(database)
    assert values["PW_MANGOHUD"] == values["PW_USE_GAMEMODE"] == "1"
    assert values["MANGOHUD_CONFIG"] == "fps,cpu_temp"
    assert values["PW_VKBASALT_FFX_CAS"] == "0.50"
    assert values["LAUNCH_PARAMETERS"] == '--name "a b" --literal "$HOME`id`"'
    assert "Exec" not in values and "Path" not in values
    assert load_native_settings(str(entry))["LAUNCH_PARAMETERS"] == values["LAUNCH_PARAMETERS"]


def test_native_runtime_uses_alt_driver_paths_and_portable_mangohud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from portprotonqt.native_games import build_native_runtime

    runtime, plugins = tmp_path / "runtime", tmp_path / "plugins"
    wrapper = runtime / "pressure-vessel/bin/pressure-vessel-unruntime"
    wrapper.parent.mkdir(parents=True)
    wrapper.touch()
    (runtime / "runtime/files").mkdir(parents=True)
    shim = plugins / "portable/lib/lib64/libMangoHud_shim.so"
    shim.parent.mkdir(parents=True)
    shim.touch()
    monkeypatch.setattr("portprotonqt.native_games.get_native_tool_paths", lambda: {"runtime": str(runtime), "plugins": str(plugins)})
    monkeypatch.setattr("portprotonqt.native_games.platform.freedesktop_os_release", lambda: {"ID": "altlinux"})
    original_is_dir, original_resolve = Path.is_dir, Path.resolve
    driver_paths = {"/etc/libnvidiacurrent": "/usr/lib64/nvidia-test", "/etc/libnvidia32current": "/usr/lib/nvidia-test"}
    monkeypatch.setattr(Path, "is_dir", lambda path: str(path) in driver_paths or original_is_dir(path))
    monkeypatch.setattr(Path, "resolve", lambda path: Path(driver_paths[str(path)]) if str(path) in driver_paths else original_resolve(path))
    monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)
    monkeypatch.delenv("LD_PRELOAD", raising=False)
    command, environment = build_native_runtime({"PW_MANGOHUD": "1"})
    assert "PRESSURE_VESSEL_APP_LD_LIBRARY_PATH=/usr/lib64/nvidia-test:/usr/lib/nvidia-test" in environment
    assert "PRESSURE_VESSEL_IMPORT_VULKAN_LAYERS=0" in environment
    assert "MANGOHUD=1" in command and "LD_PRELOAD=libMangoHud_shim.so" in command
    assert "mangohud" not in command
    assert f"VK_ADD_IMPLICIT_LAYER_PATH={plugins / 'portable/share/vulkan/implicit_layer.d'}" in command


def test_native_context_shortcuts_and_delete_preserve_game(tmp_path: Path) -> None:
    executable = tmp_path / "start"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    content, destination = cast(tuple[str, str], create_native_desktop_file(str(executable), "Game"))
    source = Path(destination)
    source.write_text(content)
    save_native_settings(destination, {})
    manager = ContextMenuManager.__new__(ContextMenuManager)
    owner = cast(Any, manager)
    owner.parent = SimpleNamespace(refreshGames=MagicMock(), _loaded_library_cache={"native": [], "steam": []})
    owner.signals = SimpleNamespace(show_warning_dialog=MagicMock())
    owner._update_desktop_database = MagicMock()
    owner._remove_statistics_entry = MagicMock()
    owner.game_library_manager = SimpleNamespace(remove_game_incremental=MagicMock())
    directories = [Path(os.environ["XDG_DATA_HOME"]) / "applications", tmp_path / "Desktop"]
    for directory in directories:
        manager._toggle_native_shortcut("native://" + destination, str(directory))
        assert (directory / source.name).read_text() == source.read_text()
    manager._toggle_native_shortcut("native://" + destination, str(directories[0]))
    assert not (directories[0] / source.name).exists()
    assert source.is_file()
    manager._delete_game_without_confirm("Game", "native://" + destination)
    assert not source.exists() and not (directories[1] / source.name).exists()
    assert executable.is_file() and Path(str(executable) + ".ppdb").is_file()
    assert "native" not in owner.parent._loaded_library_cache
    owner.game_library_manager.remove_game_incremental.assert_called_once_with("Game", "native://" + destination)


@pytest.mark.parametrize("in_steam", [False, True])
def test_native_context_menu_exposes_shortcut_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, in_steam: bool,
) -> None:
    from PySide6.QtWidgets import QMenu

    _app = QApplication.instance() or QApplication([])
    manager = ContextMenuManager.__new__(ContextMenuManager)
    owner = cast(Any, manager)
    owner._get_safe_icon = lambda _name: QIcon()
    owner._toggle_native_shortcut = MagicMock()
    owner._edit_native_shortcut = MagicMock()
    owner.add_to_steam, owner.remove_from_steam = MagicMock(), MagicMock()
    monkeypatch.setattr("portprotonqt.context_menu_manager.get_steam_home", lambda: tmp_path)
    monkeypatch.setattr("portprotonqt.context_menu_manager.is_game_in_steam", lambda _name: in_steam)
    owner.delete_game = MagicMock()
    owner.parent = SimpleNamespace(detail_page_manager=SimpleNamespace(_open_executable_folder=MagicMock()))
    card = SimpleNamespace(name="Game", exec_line="native://" + str(tmp_path / "game.desktop"), cover_path="cover.png")
    menu = QMenu()
    manager._add_native_actions(menu, cast(Any, card))
    actions = {action.text(): action for action in menu.actions()}
    assert {_('Add to Desktop'), _('Add to Menu'), _('Edit Shortcut'), _('Delete'), _('Open Game Folder')} <= actions.keys()
    actions[_("Remove from Steam") if in_steam else _("Add to Steam")].trigger()
    if in_steam:
        owner.remove_from_steam.assert_called_once_with("Game", card.exec_line, "native")
    else:
        owner.add_to_steam.assert_called_once_with("Game", card.exec_line, "cover.png")
    actions[_('Edit Shortcut')].trigger()
    owner._edit_native_shortcut.assert_called_once_with(card)
    actions[_('Delete')].trigger()
    owner.delete_game.assert_called_once_with("Game", card.exec_line)


def test_native_steam_add_uses_existing_shortcut_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    executable = tmp_path / "native game"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    content, destination = cast(tuple[str, str], create_native_desktop_file(str(executable), "Native"))
    Path(destination).write_text(content)
    manager = ContextMenuManager.__new__(ContextMenuManager)
    owner = cast(Any, manager)
    owner._check_portproton = lambda: True
    owner._batch_action = False
    owner.signals = SimpleNamespace(show_warning_dialog=MagicMock(), show_info_dialog=MagicMock())
    add = MagicMock(return_value=(True, "added"))
    remove = MagicMock(return_value=(True, "removed"))
    monkeypatch.setattr("portprotonqt.context_menu_manager.add_to_steam", add)
    monkeypatch.setattr("portprotonqt.context_menu_manager.remove_from_steam", remove)
    manager.add_to_steam("Native", "native://" + destination, "cover.png")
    add.assert_called_once_with("Native", next(line[5:] for line in content.splitlines() if line.startswith("Exec=")), "cover.png")
    manager.remove_from_steam("Native", "native://" + destination, "native")
    remove.assert_called_once_with("Native", add.call_args.args[1])
    owner.signals.show_warning_dialog.emit.assert_not_called()


def test_native_shortcut_edit_preserves_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtWidgets import QDialog

    executable = tmp_path / "start"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    content, destination = cast(tuple[str, str], create_native_desktop_file(str(executable), "Old"))
    Path(destination).write_text(content)
    save_native_settings(destination, {"MANGOHUD_CONFIG": "fps,cpu_temp"})
    dialog = SimpleNamespace(exec=lambda: QDialog.DialogCode.Accepted,
        native_checkbox=SimpleNamespace(setChecked=MagicMock()),
        add_to_steam_checkbox=SimpleNamespace(setChecked=MagicMock(), isChecked=lambda: False),
        add_to_menu_checkbox=SimpleNamespace(setChecked=MagicMock(), isChecked=lambda: True),
        add_to_desktop_checkbox=SimpleNamespace(setChecked=MagicMock(), isChecked=lambda: True),
        getDesktopEntryData=lambda: create_native_desktop_file(str(executable), "Renamed"))
    monkeypatch.setattr("portprotonqt.context_menu_manager.AddGameDialog", lambda **_kwargs: dialog)
    manager = ContextMenuManager.__new__(ContextMenuManager)
    owner = cast(Any, manager)
    owner.parent, owner.theme = SimpleNamespace(refreshGames=MagicMock()), None
    owner.signals = SimpleNamespace(show_warning_dialog=MagicMock())
    owner._update_desktop_database = MagicMock()
    manager._edit_native_shortcut(cast(Any, SimpleNamespace(name="Old", exec_line="native://" + destination, cover_path="")))
    assert "Name=Renamed" in Path(destination).read_text()
    assert load_native_settings(destination)["MANGOHUD_CONFIG"] == "fps,cpu_temp"
    for directory in (Path(os.environ["XDG_DATA_HOME"]) / "applications", tmp_path / "Desktop"):
        assert "Name=Renamed" in (directory / Path(destination).name).read_text()
    owner.signals.show_warning_dialog.assert_not_called()
    owner.parent.refreshGames.assert_called_once()


@pytest.mark.parametrize("filename, executable, expected", [
    ("game", False, True),
    ("game.sh", False, True),
    ("game.bin", False, True),
    ("game.bash", False, True),
    ("game.AppImage", False, True),
    ("game.x86_64", True, True),
    ("game.txt", False, False),
    ("game.exe", True, False),
    ("game.iso", True, False),
])
def test_native_executable_detection(
    tmp_path: Path, filename: str, executable: bool, expected: bool,
) -> None:
    from portprotonqt.native_games import is_native_executable

    path = tmp_path / filename
    path.write_bytes(b"test")
    path.chmod(0o755 if executable else 0o644)
    assert is_native_executable(str(path)) is expected
