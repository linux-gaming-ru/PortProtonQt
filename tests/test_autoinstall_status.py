"""Tests for auto-install installed status matching."""

from pathlib import Path
from typing import Any, cast

import portprotonqt.detail_pages as detail_pages
from portprotonqt.detail_pages import DetailPageManager
from portprotonqt.detail_pages.utils import (
    _check_autoinstall_installed_sync,
    find_autoinstall_entry_path,
)


def _write_desktop_entry(desktop_path: Path, name: str, exe_path: Path) -> None:
    desktop_path.write_text(
        "[Desktop Entry]\n"
        f"Name={name}\n"
        f'Exec="{exe_path}"\n',
        encoding="utf-8",
    )


def test_autoinstall_status_rejects_unrelated_launcher_exe(tmp_path: Path) -> None:
    script_path = tmp_path / "Lost_Light.ppai"
    script_path.write_text(
        'export PW_EXE_FILE="$WINEPREFIX/drive_c/Program Files (x86)/LostLight/launcher.exe"\n',
        encoding="utf-8",
    )
    portproton_dir = tmp_path / "portproton"
    portproton_dir.mkdir()
    launcher_path = tmp_path / "prefix" / "drive_c" / "HoYoPlay" / "launcher.exe"
    launcher_path.parent.mkdir(parents=True)
    launcher_path.touch()
    _write_desktop_entry(portproton_dir / "HoYoPlay.desktop", "HoYoPlay", launcher_path)

    assert not _check_autoinstall_installed_sync(
        str(script_path), "Lost Light", str(portproton_dir)
    )


def test_find_autoinstall_entry_matches_target_path(tmp_path: Path) -> None:
    script_path = tmp_path / "Lost_Light.ppai"
    script_path.write_text(
        'export PW_EXE_FILE="$WINEPREFIX/drive_c/Program Files (x86)/LostLight/launcher.exe"\n',
        encoding="utf-8",
    )
    portproton_dir = tmp_path / "portproton"
    portproton_dir.mkdir()
    wrong_path = tmp_path / "prefix" / "drive_c" / "HoYoPlay" / "launcher.exe"
    target_path = tmp_path / "prefix" / "drive_c" / "Program Files (x86)" / "LostLight" / "launcher.exe"
    wrong_path.parent.mkdir(parents=True)
    target_path.parent.mkdir(parents=True)
    wrong_path.touch()
    target_path.touch()
    _write_desktop_entry(portproton_dir / "HoYoPlay.desktop", "HoYoPlay", wrong_path)
    target_desktop = portproton_dir / "Lost Light.desktop"
    _write_desktop_entry(target_desktop, "Lost Light", target_path)

    assert find_autoinstall_entry_path(str(script_path), str(portproton_dir)) == str(target_desktop)


def test_autoinstall_status_ignores_desktop_name(tmp_path: Path) -> None:
    script_path = tmp_path / "Secret_World_Legends.ppai"
    script_path.write_text(
        '#    PW_EXE_FILE="${WINEPREFIX}/drive_c/Program Files (x86)/Funcom/Secret World Legends/SecretWorldLegendsDX11.exe"\n'
        'PW_EXE_FILE="${WINEPREFIX}/drive_c/Program Files (x86)/Funcom/Secret World Legends/ClientPatcher.exe"\n',
        encoding="utf-8",
    )
    portproton_dir = tmp_path / "portproton"
    portproton_dir.mkdir()
    target_path = tmp_path / "prefix" / "drive_c" / "Program Files (x86)"
    target_path = target_path / "Funcom" / "Secret World Legends" / "ClientPatcher.exe"
    target_path.parent.mkdir(parents=True)
    target_path.touch()
    _write_desktop_entry(portproton_dir / "SWL.desktop", "Funcom Launcher", target_path)

    assert _check_autoinstall_installed_sync(
        str(script_path), "Secret World Legends", str(portproton_dir)
    )


def test_autoinstall_status_falls_back_to_basename_without_path(tmp_path: Path) -> None:
    script_path = tmp_path / "Itch_io.ppai"
    script_path.write_text(
        'PW_EXE_FILE=$(find "$WINEPREFIX/drive_c/users" -type f -name "itch.exe")\n',
        encoding="utf-8",
    )
    portproton_dir = tmp_path / "portproton"
    portproton_dir.mkdir()
    target_path = tmp_path / "prefix" / "drive_c" / "users" / "steamuser" / "AppData" / "itch.exe"
    target_path.parent.mkdir(parents=True)
    target_path.touch()
    _write_desktop_entry(portproton_dir / "Itch.desktop", "Itch", target_path)

    assert _check_autoinstall_installed_sync(
        str(script_path), "Itch.io", str(portproton_dir)
    )


def test_open_installed_autoinstall_card_switches_to_library(monkeypatch: Any) -> None:
    class FakeMainWindow:
        portproton_location = "/tmp/portproton"
        auto_install_tab_index = 1

        def __init__(self) -> None:
            self.switched_index: int | None = None

        def switchTab(self, index: int) -> None:
            self.switched_index = index

        def _process_desktop_file_async(self, _path: str, callback: Any) -> None:
            callback((
                "Installed Game", "", "", "", "", "/tmp/InstalledGame.exe",
                "Never", "0h 0m", "", "", 0, 0, "portproton", "", "", "",
            ))

    opened_data: dict | None = None
    manager = DetailPageManager.__new__(DetailPageManager)
    manager.main_window = FakeMainWindow()
    monkeypatch.setattr(
        detail_pages,
        "find_autoinstall_entry_path",
        lambda _script, _location: "/tmp/Installed Game.desktop",
    )
    monkeypatch.setattr(manager, "_remove_current_detail_page", lambda: None)

    def open_detail(game_data: dict) -> None:
        nonlocal opened_data
        opened_data = game_data

    monkeypatch.setattr(manager, "openGameDetailPage", open_detail)

    manager._open_installed_autoinstall_card("/tmp/game.ppai", "Auto Game")

    assert manager.main_window.switched_index == 0
    assert manager._return_to_tab_index == 0
    assert opened_data is not None


def test_list_status_worker_uses_cached_script_and_checks_installation(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from portprotonqt.tabs.autoinstall_tab import AutoInstallStatusWorker

    script = tmp_path / "game.ppai"
    script.write_text('PW_EXE_FILE="$WINEPREFIX/drive_c/Game/game.exe"\n')
    location = tmp_path / "portproton"
    location.mkdir()
    exe = tmp_path / "prefix" / "drive_c" / "Game" / "game.exe"
    exe.parent.mkdir(parents=True)
    exe.touch()
    desktop = location / "game.desktop"
    _write_desktop_entry(desktop, "Game", exe)
    worker = AutoInstallStatusWorker()
    worker.api = SimpleNamespace(
        _get_autoinstall_script_path=lambda _: str(script),
        download_autoinstall_script=MagicMock(),
    )
    worker.games = [("Game", "", "", "", "", "autoinstall:https://example/game.ppai",
                     "", "", "", "", 0, 0, "autoinstall", "game_1")]
    worker.portproton_location = str(location)
    results: list[tuple[str, bool | None]] = []
    worker.status_ready.connect(lambda name, status: results.append((name, status)))
    worker.run()
    desktop.unlink()
    worker.run()
    assert results == [("game_1", True), ("game_1", False)]
    worker.api.download_autoinstall_script.assert_not_called()
    monkeypatch.setattr(worker, "isInterruptionRequested", lambda: True)
    worker.run()
    assert len(results) == 2


def test_list_status_callback_ignores_replaced_cards(monkeypatch: Any) -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    import portprotonqt.tabs.autoinstall_tab as tab

    worker = MagicMock()
    monkeypatch.setattr(tab, "AutoInstallStatusWorker", lambda _: worker)
    label = MagicMock()
    card = SimpleNamespace(installStatusLabel=label)
    window = SimpleNamespace(autoInstallGameCards={"game_1": card},
                             autoInstallStatusLabels={"game_1": label},
                             portproton_api=MagicMock(), portproton_location=None)
    tab.MainWindowAutoInstallTabMixin._load_autoinstall_statuses(cast(Any, window), [])
    callback = worker.status_ready.connect.call_args.args[0]
    callback("game_1", True)
    assert label.setText.call_args.args == ("✓",)
    callback("game_1", False)
    assert label.setText.call_args.args == ("—",)
    callback("game_1", None)
    assert label.setText.call_args.args == ("?",)
    window.autoInstallGameCards.clear()
    label.reset_mock()
    callback("game_1", True)
    label.setText.assert_not_called()
    assert window.autoInstallStatusWorkers == [worker]
