"""Tests for GOG and EGS store integrations."""

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

from pytest import MonkeyPatch, mark

from portprotonqt.config import game_config
from portprotonqt.egs_api import EGSAPI
from portprotonqt.gog_api import GOGAPI
from portprotonqt.main_window import MainWindow
from portprotonqt.tabs.download_tab import MainWindowDownloadTabMixin
from portprotonqt.tabs.download_tab import MainWindowDownloadTabMixin as GOGMixin
import portprotonqt.main_window as main_window_module
import portprotonqt.tabs.download_tab as download_tab_module

def test_gog_logout_removes_credentials_and_library_cache(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    api = GOGAPI()
    api.data_dir.mkdir(parents=True)
    api.auth_path.write_text("{}")
    api.account_path.write_text('{"username": "gog-user"}')
    api.library_path.write_text("[]")

    assert api.get_account_name() == "gog-user"
    assert api.logout() is True
    assert not api.auth_path.exists()
    assert not api.account_path.exists()
    assert not api.library_path.exists()

def test_gog_support_removes_finished_process_before_launching_game() -> None:
    process = SimpleNamespace(poll=lambda: 0)
    launches = []
    timer = MagicMock()
    window = SimpleNamespace(
        game_processes=[process],
        checkProcessTimer=timer,
        _launch_gog_game=lambda app_id, button, play_sound: launches.append(
            (app_id, button, play_sound)
        ),
    )

    GOGMixin._launch_after_gog_support(cast(Any, window), "123", "button")

    assert window.game_processes == []
    assert launches == [("123", "button", False)]
    timer.stop.assert_called_once_with()
    timer.deleteLater.assert_called_once_with()
    assert window.checkProcessTimer is None

def test_gog_support_uses_regular_launch_output_monitor(
    monkeypatch: MonkeyPatch,
) -> None:
    process = SimpleNamespace()
    readers = []
    input_manager = MagicMock()
    timer = MagicMock()
    window = SimpleNamespace(
        gog_api=SimpleNamespace(get_launch_target=lambda _app_id: "/game/Game.exe"),
        game_processes=[],
        current_running_button=None,
        input_manager=input_manager,
        _start_launch_output_reader=readers.append,
        _set_running_button_stop=lambda: None,
        checkTargetExe=lambda: None,
    )
    monkeypatch.setattr(download_tab_module, "QTimer", lambda _parent: timer)

    GOGMixin._track_gog_support_process(
        cast(Any, window), "123", cast(Any, process)
    )

    assert readers == [process]
    timer.start.assert_called_once_with(500)
    input_manager.suspend_gamepad_polling.assert_called_once_with()

def test_gog_launch_starts_playtime_tracking(
    monkeypatch: MonkeyPatch,
) -> None:
    target = "/games/Bio Menace/game.exe"
    saved = []
    window: Any = MainWindow.__new__(MainWindow)
    window.gog_api = SimpleNamespace(
        ensure_launch_parameters=lambda _app_id: None,
        get_installed_path=lambda _app_id: Path("/games/Bio Menace"),
        get_launch_target=lambda _app_id: target,
        needs_support_setup=lambda _app_id: False,
        build_command=lambda arguments: arguments,
        get_environment=lambda: {},
    )
    window.start_sh = ["start.sh"]
    window.game_processes = []
    window.input_manager = MagicMock()
    window._check_alt_i586_dependencies_before_launch = lambda: True
    window._start_launch_output_reader = lambda _process: None
    window._update_last_launch_after_start = lambda *_args: None
    timer = MagicMock()
    monkeypatch.setattr(
        "portprotonqt.main_window.subprocess.Popen",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr("portprotonqt.main_window.QTimer", lambda _parent: timer)
    monkeypatch.setattr(
        "portprotonqt.main_window.save_last_launch",
        lambda *args: saved.append(args),
    )

    window._launch_gog_game("123", play_sound=False)

    assert window.game_start_exe == target
    assert window.game_start_time is not None
    assert window.game_start_exact_path is True
    assert saved == [("gog-123", window.game_start_time)]


def test_gog_launch_checks_alt_i586_dependencies() -> None:
    window: Any = MainWindow.__new__(MainWindow)
    window.gog_api = SimpleNamespace(
        ensure_launch_parameters=lambda _app_id: None,
        get_installed_path=lambda _app_id: Path("/games/game"),
        get_launch_target=lambda _app_id: "/games/game/game.exe",
        needs_support_setup=lambda _app_id: False,
    )
    window.start_sh = ["start.sh"]
    window.game_processes = []
    window._check_alt_i586_dependencies_before_launch = lambda: False
    window._finish_silent_launch = MagicMock()

    window._launch_gog_game("123", play_sound=False)

    window._finish_silent_launch.assert_called_once_with()


def test_egs_launch_checks_alt_i586_dependencies() -> None:
    window: Any = MainWindow.__new__(MainWindow)
    window.egs_api = SimpleNamespace(
        get_launch_target=lambda _app_id: "/games/game/game.exe",
    )
    window.start_sh = ["start.sh"]
    window.game_processes = []
    window._check_alt_i586_dependencies_before_launch = lambda: False
    window._finish_silent_launch = MagicMock()

    window._launch_egs_game("123")

    window._finish_silent_launch.assert_called_once_with()


def test_gog_playtime_updates_live_by_launch_target() -> None:
    target = "/games/Bio Menace/game.exe"
    game = ("Bio Menace", "", "", "123", "", "gog://launch/123",
            "Never", "0 sec.", "", "", 0, 0, "gog")
    window: Any = MainWindow.__new__(MainWindow)
    window.gog_api = SimpleNamespace(get_launch_target=lambda _app_id: target)

    games, changed = window._update_game_list_playtime([game], target, 120)

    assert changed
    assert games[0][11] == 120

def test_repair_gog_game_uses_repair_command(tmp_path: Path) -> None:
    install_path = tmp_path / "Game"
    started: list[tuple] = []
    api = SimpleNamespace(
        config_dir=tmp_path / "gogdl",
        get_installed_path=lambda _app_id: install_path,
        build_command=lambda arguments: ["gogdl", *arguments],
    )
    window = SimpleNamespace(
        gog_process=None,
        gog_api=api,
        gogAccountStatus=SimpleNamespace(setText=lambda _text: None),
        _start_gog_download=lambda *arguments: started.append(arguments),
    )

    GOGMixin._repair_gog_game(cast(Any, window), {"app_id": "123", "title": "Game"})

    assert started[0][2] == [
        "gogdl", "repair", "123", "--path", str(install_path),
        "--support", str(tmp_path / "gogdl/heroic_gogdl/gog-support/123"),
        "--platform", "windows",
    ]

def test_install_gog_game_uses_support_path(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    selected_path = tmp_path / "Games"
    started: list[tuple] = []
    explorer = MagicMock()
    explorer.file_signal.file_selected.connect.side_effect = (
        lambda callback: callback(str(selected_path))
    )
    monkeypatch.setattr(download_tab_module, "FileExplorer", lambda *_args, **_kwargs: explorer)
    api = SimpleNamespace(
        config_dir=tmp_path / "gogdl",
        get_install_path=lambda _app_id, _title: selected_path,
        is_game_installed=lambda _app_id: False,
        build_command=lambda arguments: ["gogdl", *arguments],
    )
    window = SimpleNamespace(
        gog_process=None, gog_download_queue=[], theme=object(), gog_api=api,
        _start_gog_download=lambda *arguments: started.append(arguments),
    )

    GOGMixin._install_gog_game(cast(Any, window), {"app_id": "123", "title": "Game"})

    assert started[0][2] == [
        "gogdl", "download", "123", "--path", str(selected_path),
        "--support", str(tmp_path / "gogdl/heroic_gogdl/gog-support/123"),
        "--platform", "windows",
    ]

def test_install_egs_game_selects_path_and_opens_download(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    selected_path = tmp_path / "Epic"
    started: list[tuple] = []
    explorer = MagicMock()
    explorer.file_signal.file_selected.connect.side_effect = (
        lambda callback: callback(str(selected_path))
    )
    monkeypatch.setattr(download_tab_module, "FileExplorer", lambda *_args, **_kwargs: explorer)
    game = {"app_id": "doom64", "title": "DOOM 64", "cover": "cover"}
    api = SimpleNamespace(
        games_dir=tmp_path / "Games", load_library=lambda: [game],
        build_command=lambda arguments: ["legendary", *arguments],
    )
    window = SimpleNamespace(
        gog_process=None, egs_process=None, theme=object(), egs_api=api,
        _start_egs_download=lambda *arguments: started.append(arguments),
        egsAccountStatus=SimpleNamespace(setText=MagicMock()),
    )

    GOGMixin._install_egs_download(cast(Any, window), "doom64")

    assert started[0] == (
        game, selected_path,
        [
            "legendary", "install", "doom64", "--base-path", str(selected_path),
            "--platform", "Windows", "--skip-sdl", "--skip-dlcs", "-y",
        ],
    )

def test_cancel_gog_download_terminates_then_kills(monkeypatch: MonkeyPatch) -> None:
    process = SimpleNamespace(
        terminate=MagicMock(),
        kill=MagicMock(),
        state=lambda: download_tab_module.QProcess.ProcessState.Running,
    )
    window = SimpleNamespace(
        gog_process=process,
        downloadCancelButton=SimpleNamespace(setEnabled=MagicMock()),
        downloadActiveDetails=SimpleNamespace(setText=MagicMock()),
        _kill_gog_process=lambda active: GOGMixin._kill_gog_process(
            cast(Any, window), active
        ),
    )
    monkeypatch.setattr(download_tab_module.QTimer, "singleShot", lambda _delay, callback: callback())

    GOGMixin._cancel_gog_download(cast(Any, window))

    process.terminate.assert_called_once()
    process.kill.assert_called_once()

def test_import_gog_game_saves_selected_installation(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    selected_path = tmp_path / "Selected"
    game_path = selected_path / "Game"
    saved: list[tuple] = []

    class Explorer:
        def __init__(self, *_args, **_kwargs) -> None:
            self.callback: Callable[[str], None] = lambda _path: None
            self.file_signal = SimpleNamespace(
                file_selected=SimpleNamespace(connect=self._connect)
            )

        def _connect(self, callback: Callable[[str], None]) -> None:
            self.callback = callback

        def setWindowTitle(self, _title: str) -> None:
            return

        def exec(self) -> None:
            self.callback(str(selected_path))

    api = SimpleNamespace(
        find_install_path=lambda _app_id, _path: game_path,
        save_installed_game=lambda *arguments: saved.append(arguments),
        ensure_launch_parameters=lambda _app_id: None,
    )
    window = SimpleNamespace(
        theme=object(),
        gog_api=api,
        gogAccountStatus=SimpleNamespace(setText=lambda _text: None),
        loadGames=lambda **_kwargs: None,
    )
    monkeypatch.setattr(download_tab_module, "FileExplorer", Explorer)

    GOGMixin._import_gog_game(cast(Any, window), {"app_id": "123", "title": "Game"})

    assert saved == [("123", {"install_path": str(game_path), "title": "Game"})]

def test_stop_store_game_waits_for_launcher_to_exit(monkeypatch: MonkeyPatch) -> None:
    window: Any = MainWindow.__new__(MainWindow)
    process = MagicMock()
    window.current_running_button = None
    window.game_processes = [process]
    window.launcher_process_only = True
    window.checkProcessTimer = MagicMock()
    window._analyze_short_launch = MagicMock()
    window._terminate_game_processes = MagicMock()
    window._run_portproton_stop_command = MagicMock(return_value=True)
    window.resetPlayButton = MagicMock()

    assert window.stop_running_game() is True

    assert window.game_processes == [process]
    window._terminate_game_processes.assert_not_called()
    window._analyze_short_launch.assert_not_called()
    window.checkProcessTimer.stop.assert_not_called()
    window.resetPlayButton.assert_not_called()

def test_load_gog_games_includes_compatibility_metadata(monkeypatch: MonkeyPatch) -> None:
    window = MainWindow.__new__(MainWindow)
    test_window = cast(Any, window)
    test_window.gog_api = SimpleNamespace(
        load_installed=lambda: {},
        load_library=lambda: [
            {"app_id": "gog-1", "title": "Game", "steam_appid": "123"}
        ],
        is_game_installed=lambda _app_id, _installed: True,
        get_launch_target=lambda _app_id: "/games/Game/game.exe",
    )
    steam_info = {
        "appid": 123,
        "controller_support": "full",
        "protondb_tier": "gold",
        "anticheat_status": "Supported",
        "anticheat_slug": "game",
        "ppdb_id": "456",
        "ppdb_rating": "good",
    }
    get_steam_info = MagicMock(
        side_effect=lambda _appid, callback, fallback_name: callback(steam_info)
    )
    monkeypatch.setattr(
        "portprotonqt.main_window.get_full_steam_game_info_async", get_steam_info
    )
    monkeypatch.setattr(game_config, "get_only_installed", lambda: False)
    results = []

    MainWindow._load_gog_games_async(window, results.append)

    assert len(results) == 1
    game = results[0][0]
    assert game[3] == "gog-1"
    assert game[4] == "full"
    assert game[8:10] == ("gold", "Supported")
    assert game[13:17] == ("game", "456", "good", 123)
    assert get_steam_info.call_args.args[0] == 123
    assert get_steam_info.call_args.kwargs == {"fallback_name": "Game"}

def test_legacy_gog_library_refreshes_metadata(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    window = MainWindow.__new__(MainWindow)
    test_window = cast(Any, window)
    test_window._load_gog_games_async = MagicMock()
    auth_path = tmp_path / "auth.json"
    auth_path.write_text("{}", encoding="utf-8")
    worker = SimpleNamespace(
        loaded=MagicMock(), failed=MagicMock(), finished=MagicMock(), start=MagicMock()
    )
    monkeypatch.setattr(
        "portprotonqt.main_window.GOGLibraryWorker", lambda _api: worker
    )
    callback = MagicMock()

    started = MainWindow._upgrade_legacy_gog_library(
        window, cast(Any, SimpleNamespace(auth_path=auth_path)),
        [{"app_id": "1"}], callback
    )

    assert started is True
    worker.start.assert_called_once_with()
    worker.loaded.connect.call_args.args[0]([])
    test_window._load_gog_games_async.assert_called_once_with(callback)

def test_installed_filter_excludes_uninstalled_gog_games(
    monkeypatch: MonkeyPatch,
) -> None:
    window = MainWindow.__new__(MainWindow)
    test_window = cast(Any, window)
    test_window.gog_api = SimpleNamespace(
        load_installed=lambda: {"installed": {}},
        load_library=lambda: [
            {"app_id": "installed", "title": "Installed", "steam_appid": ""},
            {"app_id": "uninstalled", "title": "Uninstalled", "steam_appid": ""},
        ],
        is_game_installed=lambda app_id, _installed: app_id == "installed",
        get_launch_target=lambda app_id: f"/games/{app_id}/game.exe",
    )
    monkeypatch.setattr(game_config, "get_only_installed", lambda: True)
    monkeypatch.setattr(
        "portprotonqt.main_window.get_steam_game_info_async",
        lambda _name, _uri, callback: callback({}),
    )
    results = []

    MainWindow._load_gog_games_async(window, results.append)

    assert [game[3] for game in results[0]] == ["installed"]
    assert results[0][0][5] == "gog://launch/installed"

def test_installed_filter_disabled_includes_uninstalled_gog_games(
    monkeypatch: MonkeyPatch,
) -> None:
    window = MainWindow.__new__(MainWindow)
    test_window = cast(Any, window)
    test_window.gog_api = SimpleNamespace(
        load_installed=lambda: {},
        load_library=lambda: [
            {"app_id": "uninstalled", "title": "Uninstalled", "steam_appid": ""},
        ],
        is_game_installed=lambda _app_id, _installed: False,
    )
    monkeypatch.setattr(game_config, "get_only_installed", lambda: False)
    monkeypatch.setattr(
        "portprotonqt.main_window.get_steam_game_info_async",
        lambda _name, _uri, callback: callback({}),
    )
    results = []

    MainWindow._load_gog_games_async(window, results.append)

    assert [game[3] for game in results[0]] == ["uninstalled"]
    assert results[0][0][5] == "gog://install/uninstalled"

@mark.parametrize(
    ("game_name", "launch_uri"),
    (
        ("Unknown GOG Game", "gog://launch/123"),
        ("Unknown Epic Game", "egs://launch/Fortnite"),
    ),
)
def test_store_metadata_search_ignores_uri_components(
    monkeypatch: MonkeyPatch, game_name: str, launch_uri: str
) -> None:
    from portprotonqt.steam_api import get_steam_game_info_async

    searched_candidates = []
    monkeypatch.setattr(
        "portprotonqt.steam_api.api.ui_config.get_economy_mode", lambda: False
    )
    monkeypatch.setattr(
        "portprotonqt.steam_api.api.get_steam_apps_and_index_async",
        lambda callback: callback(([{"appid": 1}], {"game": [{"appid": 1}]})),
    )
    monkeypatch.setattr(
        "portprotonqt.steam_api.api.search_app",
        lambda candidate, _index: searched_candidates.append(candidate),
    )
    fetch_sgdb_cover = MagicMock()
    monkeypatch.setattr(
        "portprotonqt.steam_api.api.fetch_sgdb_cover_async", fetch_sgdb_cover
    )
    monkeypatch.setattr(
        "portprotonqt.steam_api.api.get_weanticheatyet_info_async",
        lambda _name, callback: callback({}),
    )
    monkeypatch.setattr(
        "portprotonqt.steam_api.api._add_ppdb_info",
        lambda result, _name, callback: callback(result),
    )
    results = []

    get_steam_game_info_async(game_name, launch_uri, results.append)

    assert searched_candidates == [game_name]
    assert len(results) == 1
    fetch_sgdb_cover.assert_not_called()

def test_egs_refresh_reopens_current_detail_with_new_description() -> None:
    source_data = {
        "appid": "AmongUs",
        "game_source": "egs",
        "description": "Old description",
        "cover_path": "old.jpg",
    }
    manager = SimpleNamespace(
        _current_detail_source=("game", source_data),
        _detail_page_active=True,
        _reopen_current_detail_page=MagicMock(),
    )
    window = cast(MainWindowDownloadTabMixin, SimpleNamespace(
        detail_page_manager=manager,
        _update_egs_account_state=MagicMock(),
        loadGames=MagicMock(),
    ))

    MainWindowDownloadTabMixin._on_egs_library_loaded(window, [{
        "app_id": "AmongUs",
        "description": "Новое описание",
        "cover": "new.jpg",
    }])

    assert source_data["description"] == "Новое описание"
    assert source_data["cover_path"] == "new.jpg"
    manager._reopen_current_detail_page.assert_called_once_with()
    window.loadGames.assert_called_once_with(force_load=True)

def test_egs_library_uses_steam_description_when_epic_has_title_only(
    monkeypatch: MonkeyPatch,
) -> None:
    game = {"app_id": "WitchIt", "title": "Witch It", "description": "Witch It"}
    api = SimpleNamespace(
        load_library=lambda: [game],
        is_game_installed=lambda _app_id: False,
    )
    results = []
    window = cast(MainWindow, SimpleNamespace(
        egs_api=api, games=[],
    ))
    monkeypatch.setattr(game_config, "get_only_installed", lambda: False)
    monkeypatch.setattr(
        "portprotonqt.main_window.get_steam_game_info_async",
        lambda _name, _uri, callback: callback({
            "description": "Witch It — игра в прятки по сети.",
        }),
    )

    MainWindow._load_egs_games_async(window, results.append)

    assert results[0][0][1] == "Witch It — игра в прятки по сети."

def test_egs_maintenance_uses_legendary_commands() -> None:
    start_operation = MagicMock()
    window = cast(MainWindow, SimpleNamespace(_start_egs_operation=start_operation))

    MainWindow._repair_egs_game(window, "Game")
    MainWindow._update_egs_game(window, "Game")
    MainWindow._delete_egs_game(window, "Game")

    calls = start_operation.call_args_list
    assert calls[0].args[1] == ["repair", "Game", "--skip-sdl", "-y"]
    assert calls[1].args[1] == [
        "update", "Game", "--platform", "Windows", "--skip-sdl", "-y",
    ]
    assert calls[2].args[1] == ["uninstall", "Game", "-y"]

def test_egs_operation_is_sent_to_visible_downloads() -> None:
    game = {"app_id": "Game", "title": "Epic Game", "cover": "cover"}
    visible_operation = MagicMock()
    api = SimpleNamespace(
        build_command=lambda arguments: ["legendary", *arguments],
        load_library=lambda: [game],
    )
    window = cast(MainWindow, SimpleNamespace(
        egs_process=None, egs_api=api,
        _start_egs_visible_operation=visible_operation,
    ))

    MainWindow._start_egs_operation(window, "Game", ["repair", "Game"], "Repair")

    visible_operation.assert_called_once_with(
        game, ["legendary", "repair", "Game"], "Repair"
    )

def test_detached_store_game_keeps_running_state(monkeypatch: MonkeyPatch) -> None:
    dead_launcher = SimpleNamespace(poll=lambda: 0)
    game_process = SimpleNamespace(
        info={"name": "DOOM64_x64.exe", "status": "running"}
    )
    monkeypatch.setattr(
        main_window_module.psutil, "process_iter", lambda attrs: [game_process]
    )
    window = cast(MainWindow, SimpleNamespace(
        game_processes=[dead_launcher], target_exe="DOOM64_x64.exe",
        game_start_time=datetime.now() - timedelta(minutes=1),
    ))

    assert MainWindow._has_running_game_process(window)

def test_zombie_store_game_is_not_running(monkeypatch: MonkeyPatch) -> None:
    dead_launcher = SimpleNamespace(poll=lambda: 0)
    game_process = SimpleNamespace(
        info={
            "name": "DOOM64_x64.exe",
            "status": main_window_module.psutil.STATUS_ZOMBIE,
        }
    )
    monkeypatch.setattr(
        main_window_module.psutil, "process_iter", lambda attrs: [game_process]
    )
    window = cast(MainWindow, SimpleNamespace(
        game_processes=[dead_launcher], target_exe="DOOM64_x64.exe",
        game_start_time=None, game_launch_monotonic=None,
    ))

    assert not MainWindow._has_running_game_process(window)

def test_stopped_store_game_does_not_wait_for_launcher(monkeypatch: MonkeyPatch) -> None:
    launcher = SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(main_window_module.psutil, "process_iter", lambda attrs: [])
    window = cast(MainWindow, SimpleNamespace(
        game_processes=[launcher], target_exe="DOOM64_x64.exe",
        launcher_process_only=True, game_launch_started=False,
        game_stopped_by_user=True, game_launch_monotonic=100.0,
    ))

    assert not MainWindow._has_running_game_process(window)

def test_store_launch_grace_prevents_early_button_reset(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(main_window_module.psutil, "process_iter", lambda attrs: [])
    window = cast(MainWindow, SimpleNamespace(
        game_processes=[], target_exe="DOOM64_x64.exe",
        game_start_time=datetime.now(),
    ))

    assert MainWindow._has_running_game_process(window)

def test_store_launch_grace_starts_after_slow_legendary_login(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(main_window_module.psutil, "process_iter", lambda attrs: [])
    monkeypatch.setattr(main_window_module.time, "monotonic", lambda: 105.0)
    window = cast(MainWindow, SimpleNamespace(
        game_processes=[], target_exe="DOOM64_x64.exe",
        game_start_time=datetime.now() - timedelta(minutes=1),
        game_launch_monotonic=100.0,
    ))

    assert MainWindow._has_running_game_process(window)

def test_cancelled_egs_resolution_does_not_start_portproton(
    monkeypatch: MonkeyPatch,
) -> None:
    launch_data = '{"launch_command": ["start.sh"]}\n'
    process: Any = SimpleNamespace(
        stdout=[launch_data], wait=lambda: None, returncode=0,
    )
    window = cast(MainWindow, SimpleNamespace(egs_launch_cancelled=True))
    popen = MagicMock()
    monkeypatch.setattr(main_window_module.subprocess, "Popen", popen)

    MainWindow._read_egs_launch_output(window, process)

    popen.assert_not_called()

def test_egs_update_progress_shows_downloaded_and_total() -> None:
    details = []
    progress = MagicMock()
    output = b"Download size: 500 MiB\nDownloaded: 125 MiB\n"
    process = SimpleNamespace(
        readAllStandardOutput=lambda: SimpleNamespace(data=lambda: output),
    )
    window = cast(MainWindowDownloadTabMixin, SimpleNamespace(
        egs_process=process, egs_download_output="", egs_download_total=0.0,
        downloadOverallProgress=progress, downloadSpeedLabel=MagicMock(),
        diskSpeedLabel=MagicMock(), downloadActiveDetails=MagicMock(),
        _update_active_download_details=details.append,
    ))

    MainWindowDownloadTabMixin._read_egs_download_output(window)

    assert details == [["125.0 MiB / 500.0 MiB"]]
    progress.setValue.assert_called_with(25)

def test_store_launch_grace_preserves_early_crash_duration(
    monkeypatch: MonkeyPatch,
) -> None:
    monotonic = iter((101.0, 111.0))
    launches = []
    monkeypatch.setattr(main_window_module.psutil, "process_iter", lambda attrs: [])
    monkeypatch.setattr(main_window_module.time, "monotonic", lambda: next(monotonic))
    monkeypatch.setattr(
        main_window_module.ui_config, "get_crash_reports_enabled", lambda: True,
    )
    monkeypatch.setattr(
        main_window_module, "Thread",
        lambda **kwargs: SimpleNamespace(
            start=lambda: launches.append(kwargs["args"][0])
        ),
    )
    exited_installer = SimpleNamespace(poll=lambda: 0)
    window = cast(MainWindow, SimpleNamespace(
        game_processes=[exited_installer], target_exe="DOOM64_x64.exe",
        game_start_exe="game.exe",
        game_start_time=datetime.now() - timedelta(minutes=1),
        game_launch_monotonic=100.0, game_stopped_by_user=False,
        _build_compatibility_report=lambda *_args: None,
    ))

    assert MainWindow._has_running_game_process(window)
    assert not MainWindow._has_running_game_process(window)
    MainWindow._analyze_short_launch(window)

    assert launches[0].duration == 1.0
    assert launches[0].exit_code == 0

def test_egs_verification_uses_total_progress_format() -> None:
    import re

    output = "Verification progress: 37/142 (26.4%) [132.7 MiB/s]"
    match = re.findall(
        r"Verification progress:\s*\d+/\d+\s+\(([\d.]+)%\)"
        r"(?:\s+\[([\d.]+)\s+MiB/s\])?",
        output,
    )

    assert match == [("26.4", "132.7")]

def test_egs_overlay_enable_uses_game_prefix(tmp_path: Path) -> None:
    prefix_path = tmp_path / "data/prefixes/DEFAULT"
    prefix_path.mkdir(parents=True)
    (prefix_path / "user.reg").touch()
    config_dir = tmp_path / "legendary"
    config_dir.mkdir()
    (config_dir / "overlay_install.json").touch()
    api = SimpleNamespace(
        config_dir=config_dir,
        data_dir=tmp_path / "egs",
        get_launch_target=MagicMock(return_value="/games/Game.exe"),
        is_eos_overlay_enabled=EGSAPI.is_eos_overlay_enabled,
    )
    start_operation = MagicMock()
    window = cast(MainWindow, SimpleNamespace(
        egs_api=api,
        portproton_location=str(tmp_path),
        _start_egs_operation=start_operation,
    ))

    MainWindow._enable_egs_overlay(window, "Game")

    arguments = start_operation.call_args.args[1]
    assert arguments == [
        "eos-overlay", "enable", "--prefix", str(prefix_path),
    ]

def test_egs_overlay_disable_uses_game_prefix(tmp_path: Path) -> None:
    prefix_path = tmp_path / "data/prefixes/DEFAULT"
    prefix_path.mkdir(parents=True)
    (prefix_path / "user.reg").write_text(
        '[Software\\\\Epic Games\\\\EOS]\n\n'
        '[SOFTWARE\\\\Epic Games\\\\EOS]\n"OverlayPath"="Z:/overlay"\n',
        encoding="utf-8",
    )
    config_dir = tmp_path / "legendary"
    config_dir.mkdir()
    (config_dir / "overlay_install.json").touch()
    api = SimpleNamespace(
        config_dir=config_dir,
        data_dir=tmp_path / "egs",
        get_launch_target=MagicMock(return_value="/games/Game.exe"),
        is_eos_overlay_enabled=EGSAPI.is_eos_overlay_enabled,
    )
    start_operation = MagicMock()
    window = cast(MainWindow, SimpleNamespace(
        egs_api=api,
        portproton_location=str(tmp_path),
        _start_egs_operation=start_operation,
    ))

    MainWindow._enable_egs_overlay(window, "Game")

    arguments = start_operation.call_args.args[1]
    assert arguments == [
        "eos-overlay", "disable", "--prefix", str(prefix_path),
    ]


@mark.parametrize("store_info", [
    ("egs", "legendary", EGSAPI),
    ("gog", "gogdl", GOGAPI),
])
def test_store_storage_migrates_existing_data(
    tmp_path: Path, monkeypatch: MonkeyPatch,
    store_info: tuple[str, str, type[EGSAPI] | type[GOGAPI]],
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    store, binary, api_class = store_info
    root = tmp_path / "PortProtonQt"
    legacy = root / store
    (legacy / "bin").mkdir(parents=True)
    (legacy / "library.json").write_text("[]")
    (legacy / "bin" / "extra.exe").write_text("extra executable")
    (legacy / "bin" / binary).write_text("executable")
    (legacy / "bin" / binary).chmod(0o700)
    (legacy / "bin" / f"{binary}.version").write_text("v1")

    api = api_class()

    assert api.data_dir == root / "launcher" / store
    assert api.library_path.read_text() == "[]"
    assert api.bin_dir == root / "bin"
    assert (api.bin_dir / binary).read_text() == "executable"
    assert (api.bin_dir / f"{binary}.version").read_text() == "v1"
    assert (api.bin_dir / "extra.exe").read_text() == "extra executable"
    assert not (api.data_dir / "bin").exists()
    assert not legacy.exists()
    assert api_class().library_path.read_text() == "[]"
