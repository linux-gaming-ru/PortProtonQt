"""Tests for desktop shortcut creation, path resolution, and file writing.

Covers:
- create_desktop_file: game names with spaces, special chars, exe paths with spaces
- _get_desktop_path: direct, sanitized, normalized fallback
- _get_shortcut_path / _get_steam_shortcut_path: spaces, slashes, empty names
- _copy_shortcut: paths with spaces
- Migration with paths containing spaces
- Shortcut .desktop content validation
"""
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from PySide6.QtCore import QPoint, Qt, QCoreApplication, QEventLoop, QThread, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QPushButton, QWidget

import portprotonqt.scripts_utils.shortcut_tools as shortcut_tools
import portprotonqt.steam_api.shortcuts as steam_shortcuts
from portprotonqt.config.portproton import (
    _sanitize_icon_name,
    create_desktop_file,
    parse_desktop_entry,
    extract_exec_target_path,
    get_custom_data_dir_name,
)


def test_game_card_context_menu_does_not_block_gamepad_polling(monkeypatch) -> None:
    from portprotonqt.context_menu_manager import ContextMenuManager

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    card = SimpleNamespace(
        batch_selected=False,
        game_source="portproton",
        name="Missing Game",
        exec_line="",
        mapToGlobal=lambda position: position,
    )
    manager = ContextMenuManager.__new__(ContextMenuManager)
    manager.parent = parent
    manager.card_selection_mode = False
    manager.game_library_manager = SimpleNamespace(game_card_cache={})
    manager.theme = SimpleNamespace(CONTEXT_MENU_STYLE="")
    monkeypatch.setattr(
        manager,
        "_get_exec_line",
        lambda game_name, exec_line: None,
    )
    monkeypatch.setattr(manager, "_get_safe_icon", lambda icon_name: QIcon())
    popup_calls = []
    monkeypatch.setattr(QMenu, "popup", lambda menu, pos: popup_calls.append((menu, pos)))
    monkeypatch.setattr(
        QMenu,
        "exec",
        lambda _menu, _pos: (_ for _ in ()).throw(AssertionError("blocking menu")),
    )

    manager.show_context_menu(card, QPoint())

    assert len(popup_calls) == 1
    assert popup_calls[0][0].testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    assert app is not None


@pytest.mark.parametrize("target", ["game.exe", "gog://launch/123", "egs://launch/game-id"])
def test_add_to_steam_for_all_accounts(
    tmp_path: Path,
    monkeypatch: Any,
    target: str,
) -> None:
    steam_home = tmp_path / "steam"
    user_ids = ("76561197960265729", "76561197960265730")
    executable = tmp_path / "game.exe"
    executable.touch()
    monkeypatch.setattr(steam_shortcuts, "get_steam_home", lambda: steam_home)
    monkeypatch.setattr(
        steam_shortcuts,
        "get_steam_users",
        lambda _steam_home: dict.fromkeys(user_ids, {}),
    )
    monkeypatch.setattr(
        steam_shortcuts, "get_portproton_location", lambda: str(tmp_path)
    )
    monkeypatch.setattr(
        steam_shortcuts, "get_portproton_start_command", lambda: "start"
    )
    icon_path = str(tmp_path / "game-icon.png")
    generate_icon = MagicMock(return_value=icon_path)
    monkeypatch.setattr(steam_shortcuts, "_generate_icon", generate_icon)
    monkeypatch.setattr(
        steam_shortcuts.game_config, "get_steam_account_id", lambda: "all"
    )
    monkeypatch.setattr(
        steam_shortcuts.ui_config, "get_economy_mode", lambda: True
    )

    result, _message = steam_shortcuts.add_to_steam(
        "Test Game", str(executable) if target == "game.exe" else target, "", str(executable)
    )

    assert result is True
    generate_icon.assert_called_once_with(str(executable), str(tmp_path))
    for account_id in ("1", "2"):
        shortcuts_path = (
            steam_home / "userdata" / account_id / "config" / "shortcuts.vdf"
        )
        assert shortcuts_path.is_file()
        shortcuts = steam_shortcuts.safe_vdf_load(shortcuts_path)["shortcuts"]
        assert shortcuts["0"]["AppName"] == "Test Game"
        assert shortcuts["0"]["icon"] == icon_path
    script = (tmp_path / "steam_scripts" / "Test Game.sh").read_text()
    assert target in script


def test_custom_data_hash_distinguishes_same_exe_names(tmp_path: Path) -> None:
    first = get_custom_data_dir_name(str(tmp_path / "first" / "launcher.exe"))
    second = get_custom_data_dir_name(str(tmp_path / "second" / "launcher.exe"))

    assert first.startswith("launcher_")
    assert first != second


class _ShortcutResponse:
    def __init__(self, text: str = "", content: bytes = b"", data: dict | None = None) -> None:
        self.text = text
        self.content = content
        self._data = data

    def raise_for_status(self) -> None:
        return

    def json(self) -> dict:
        if self._data is None:
            raise ValueError("invalid json")
        return self._data


class _ShortcutSession:
    def __init__(self, responses: list[_ShortcutResponse]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, int]] = []

    def get(self, url: str, timeout: int = 10) -> _ShortcutResponse:
        self.requests.append((url, timeout))
        return self.responses.pop(0)


def _make_exe(tmp_path: Path, name: str = "game.exe", subdir: str = "") -> str:
    exe_dir = tmp_path / "PortProtonQt" / "data" / subdir
    exe_dir.mkdir(parents=True, exist_ok=True)
    exe = exe_dir / name
    exe.touch()
    return str(exe)


def _patch_location(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "portprotonqt.config.portproton.get_portproton_location",
        lambda: str(tmp_path / "PortProtonQt"),
    )


# ── find_ext_ppdb ────────────────────────────────────────────────────────────

class TestFindExtPPDB:
    def test_existing_ppdb_returns_true(self, tmp_path: Path, monkeypatch: Any) -> None:
        exe = Path(_make_exe(tmp_path))
        ppdb = Path(f"{exe}.ppdb")
        ppdb.write_text("existing", encoding="utf-8")
        monkeypatch.setattr(
            "portprotonqt.downloader.get_requests_session",
            lambda: (_ for _ in ()).throw(AssertionError("unexpected request")),
        )

        assert shortcut_tools.find_ext_ppdb(str(exe)) is True
        assert ppdb.read_text(encoding="utf-8") == "existing"

    def test_downloads_ppdb_next_to_exe(self, tmp_path: Path, monkeypatch: Any) -> None:
        exe = Path(_make_exe(tmp_path, name="Game File.exe"))
        session = _ShortcutSession([
            _ShortcutResponse("{}", data={"ppdb_url": "https://example.org/game.ppdb"}),
            _ShortcutResponse("PW_USE_DXVK=1", content=b"PW_USE_DXVK=1\n"),
        ])
        monkeypatch.setattr(
            "portprotonqt.downloader.get_requests_session",
            lambda: session,
        )

        assert shortcut_tools.find_ext_ppdb(str(exe)) is True

        ppdb = Path(f"{exe}.ppdb")
        assert ppdb.read_bytes() == b"PW_USE_DXVK=1\n"
        assert session.requests[0] == (
            "https://linux-gaming.ru/api/lookup/exe/Game%20File.exe",
            10,
        )
        assert session.requests[1] == ("https://example.org/game.ppdb", 30)

    def test_no_game_found_response_returns_false(
        self,
        tmp_path: Path,
        monkeypatch: Any,
    ) -> None:
        exe = Path(_make_exe(tmp_path, name="MassEffectAndromeda1"))
        session = _ShortcutSession([
            _ShortcutResponse(
                '{"detail":"No game found with executable: MassEffectAndromeda1"}',
                data={"detail": "No game found with executable: MassEffectAndromeda1"},
            ),
        ])
        monkeypatch.setattr(
            "portprotonqt.downloader.get_requests_session",
            lambda: session,
        )

        assert shortcut_tools.find_ext_ppdb(str(exe)) is False
        assert not Path(f"{exe}.ppdb").exists()
        assert len(session.requests) == 1


# ── create_desktop_file ──────────────────────────────────────────────────────

class TestCreateDesktopFile:
    def test_simple_name(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path)
        result = create_desktop_file(exe)
        assert result is not None
        entry, desktop_path, icon_path = result
        assert "Name=game" in entry
        assert entry.endswith("\n")
        assert desktop_path.endswith("game.desktop")
        assert icon_path.endswith("game.png")

    def test_custom_name(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path)
        result = create_desktop_file(exe, game_name="My Cool Game")
        assert result is not None
        entry, desktop_path, _ = result
        assert "Name=My Cool Game" in entry
        assert "My Cool Game.desktop" in desktop_path

    def test_name_with_spaces(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path)
        result = create_desktop_file(exe, game_name="Dark Souls III")
        assert result is not None
        entry, desktop_path, icon_path = result
        assert "Name=Dark Souls III" in entry
        assert "Dark Souls III.desktop" in desktop_path
        assert "Dark_Souls_III.png" in icon_path

    def test_exe_path_with_spaces(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path, subdir="my games folder")
        result = create_desktop_file(exe)
        assert result is not None
        entry, _, _ = result
        assert "my games folder" in entry

    def test_exe_path_with_spaces_and_custom_name(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path, subdir="Steam Games/Portal 2")
        result = create_desktop_file(exe, game_name="Portal 2")
        assert result is not None
        entry, desktop_path, icon_path = result
        assert "Name=Portal 2" in entry
        assert "Portal 2.desktop" in desktop_path
        assert "Portal_2.png" in icon_path

    def test_nonexistent_exe_returns_none(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        result = create_desktop_file("/nonexistent/game.exe")
        assert result is None

    def test_gog_launch_uri_uses_common_desktop_entry(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        _patch_location(monkeypatch, tmp_path)

        result = create_desktop_file(
            "gog://launch/123", game_name="GOG Game"
        )

        assert result is not None
        entry, _, icon_path = result
        assert 'Exec=portprotonqt --silent "gog://launch/123"' in entry
        assert icon_path == "applications-games"

    def test_egs_launch_uri_uses_common_desktop_entry(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        _patch_location(monkeypatch, tmp_path)

        result = create_desktop_file(
            "egs://launch/5b60142e120c4f2d88027595c21d4a04",
            game_name="DOOM 64",
        )

        assert result is not None
        entry, _, icon_path = result
        assert 'Exec=portprotonqt --silent "egs://launch/5b60142e120c4f2d88027595c21d4a04"' in entry
        assert icon_path == "applications-games"

    def test_gog_launch_uri_uses_executable_icon(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path)

        result = create_desktop_file(
            "gog://launch/123", game_name="GOG Game", icon_source=exe
        )

        assert result is not None
        entry, _, icon_path = result
        assert icon_path.endswith("data/img/GOG_Game.png")
        assert f"Icon={icon_path}" in entry

    def test_no_portproton_returns_none(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(
            "portprotonqt.config.portproton.get_portproton_location",
            lambda: None,
        )
        result = create_desktop_file("/tmp/game.exe")
        assert result is None

    def test_desktop_entry_has_required_fields(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path)
        result = create_desktop_file(exe, game_name="Test Game")
        assert result is not None
        entry, _, _ = result
        assert "[Desktop Entry]" in entry
        assert "Terminal=false" in entry
        assert "Type=Application" in entry
        assert "Categories=Game;" in entry
        assert "StartupNotify=true" in entry
        assert "Icon=" in entry
        assert "Exec=" in entry

    def test_desktop_entry_has_launch_actions(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path)
        result = create_desktop_file(exe, game_name="Test Game")
        assert result is not None
        entry, _, _ = result
        assert "Actions=RunSilent;RunLog;" in entry
        assert "[Desktop Action Run]" not in entry
        assert "[Desktop Action RunSilent]" in entry
        assert "[Desktop Action RunLog]" in entry
        assert f'Exec=portprotonqt --log "{exe}"' in entry

    def test_name_with_slash_preserved_in_icon(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path)
        result = create_desktop_file(exe, game_name="Game/Title")
        assert result is not None
        _, _, icon_path = result
        assert "Game/Title.png" in icon_path

    def test_name_with_colon_preserved_in_icon(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path)
        result = create_desktop_file(exe, game_name="Game: Subtitle")
        assert result is not None
        _, _, icon_path = result
        assert "Game:_Subtitle.png" in icon_path

    def test_name_with_special_chars_in_icon(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path)
        result = create_desktop_file(exe, game_name="Game! %$& <Title>")
        assert result is not None
        _, _, icon_path = result
        basename = os.path.basename(icon_path)
        assert "!" not in basename
        assert "%" not in basename
        assert "$" not in basename
        assert "&" not in basename
        assert "<" not in basename

    def test_flatpak_exec_line(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        monkeypatch.setenv("FLATPAK_ID", "ru.linux_gaming.PortProton")
        monkeypatch.delenv("APPIMAGE", raising=False)
        exe = _make_exe(tmp_path)
        result = create_desktop_file(exe)
        assert result is not None
        entry, _, _ = result
        assert "flatpak run ru.linux_gaming.PortProton" in entry

    def test_appimage_exec_line(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        monkeypatch.delenv("FLATPAK_ID", raising=False)
        appimage = tmp_path / "PortProtonQt.AppImage"
        appimage.touch()
        monkeypatch.setenv("APPIMAGE", str(appimage))
        exe = _make_exe(tmp_path)
        result = create_desktop_file(exe)
        assert result is not None
        entry, _, _ = result
        assert "AppImage" in entry
        assert "--silent" in entry

    def test_name_with_cyrillic(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path)
        result = create_desktop_file(exe, game_name="Тест Игра")
        assert result is not None
        entry, desktop_path, icon_path = result
        assert "Name=Тест Игра" in entry
        assert "Тест Игра.desktop" in desktop_path
        assert "Тест_Игра.png" in icon_path

    def test_name_with_unicode_trademark(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path)
        result = create_desktop_file(exe, game_name="Cyberpunk 2077™")
        assert result is not None
        entry, _, _ = result
        assert "Cyberpunk 2077™" in entry

    def test_name_with_single_space(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path)
        result = create_desktop_file(exe, game_name="A B")
        assert result is not None
        entry, _, icon_path = result
        assert "Name=A B" in entry
        assert "A_B.png" in icon_path

    def test_exe_deeply_nested_path_with_spaces(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path, subdir="a/b/c/My Games/Folder")
        result = create_desktop_file(exe)
        assert result is not None
        entry, _, _ = result
        assert "My Games" in entry
        assert "Folder" in entry


# ── parse_desktop_entry round-trip ───────────────────────────────────────────

class TestParseDesktopEntryRoundTrip:
    def test_recovers_multiline_values(self, tmp_path: Path) -> None:
        desktop_path = tmp_path / "multiline.desktop"
        desktop_path.write_text(
            "[Desktop Entry]\n"
            "Name=Game\nSubtitle\n"
            "Comment=Launch Game\nSubtitle\n"
            "Exec=/game.exe\n"
            "Icon=/icons/Game\nSubtitle.png\n",
            encoding="utf-8",
        )

        parsed = parse_desktop_entry(str(desktop_path))

        assert parsed is not None
        assert parsed.get("Name") == "Game Subtitle"
        assert parsed.get("Comment") == "Launch Game Subtitle"
        assert parsed.get("Icon") == "/icons/Game Subtitle.png"
        assert desktop_path.read_text(encoding="utf-8") == (
            "[Desktop Entry]\n"
            "Name=Game Subtitle\n"
            "Comment=Launch Game Subtitle\n"
            "Exec=/game.exe\n"
            "Icon=/icons/Game Subtitle.png\n"
        )

    def test_round_trip_simple(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path)
        result = create_desktop_file(exe, game_name="Test Game")
        assert result is not None
        entry_text, desktop_path, _ = result
        Path(desktop_path).write_text(entry_text, encoding="utf-8")

        parsed = parse_desktop_entry(desktop_path)
        assert parsed is not None
        assert parsed.get("Name") == "Test Game"
        assert parsed.get("Type") == "Application"
        assert parsed.get("Terminal") == "false"

    def test_round_trip_spaces_in_name(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path)
        result = create_desktop_file(exe, game_name="Dark Souls III: Prepare to Die")
        assert result is not None
        entry_text, desktop_path, _ = result
        Path(desktop_path).write_text(entry_text, encoding="utf-8")

        parsed = parse_desktop_entry(desktop_path)
        assert parsed is not None
        assert parsed.get("Name") == "Dark Souls III: Prepare to Die"

    def test_round_trip_exe_path_with_spaces(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path)
        result = create_desktop_file(exe)
        assert result is not None
        entry_text, desktop_path, _ = result
        Path(desktop_path).write_text(entry_text, encoding="utf-8")

        parsed = parse_desktop_entry(desktop_path)
        assert parsed is not None
        exec_val = parsed.get("Exec", "")
        assert "game.exe" in exec_val

    def test_round_trip_cyrillic_name(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path)
        result = create_desktop_file(exe, game_name="Тест Игра")
        assert result is not None
        entry_text, desktop_path, _ = result
        Path(desktop_path).write_text(entry_text, encoding="utf-8")

        parsed = parse_desktop_entry(desktop_path)
        assert parsed is not None
        assert parsed.get("Name") == "Тест Игра"

    def test_multiline_name_is_written_on_one_line(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path)

        result = create_desktop_file(exe, game_name="Game\nSubtitle")

        assert result is not None
        entry_text, desktop_path, _ = result
        assert "Name=Game Subtitle\n" in entry_text
        assert Path(desktop_path).name == "Game Subtitle.desktop"


# ── extract_exec_target_path with spaces ─────────────────────────────────────

class TestExtractExecPathWithSpaces:
    def test_path_with_spaces_quoted(self) -> None:
        result = extract_exec_target_path(
            'portprotonqt --silent "/home/user/my games/game.exe"'
        )
        assert result is not None
        assert "my games" in result
        assert result.endswith("game.exe")

    def test_path_with_spaces_in_list(self) -> None:
        parts = ["portprotonqt", "--silent", "/home/user/my games/game.exe"]
        result = extract_exec_target_path(parts)
        assert result is not None
        assert "my games" in result

    def test_flatpak_path_with_spaces(self) -> None:
        result = extract_exec_target_path(
            'flatpak run ru.linux_gaming.PortProton --silent "/path/to/my game.exe"'
        )
        assert result is not None
        assert "my game.exe" in result

    def test_deep_path_with_spaces(self) -> None:
        result = extract_exec_target_path(
            'portprotonqt --silent "/home/user/My Games/Steam/steamapps/common/Portal 2/portal2.exe"'
        )
        assert result is not None
        assert "My Games" in result
        assert "Portal 2" in result
        assert "portal2.exe" in result

    def test_path_with_multiple_spaces(self) -> None:
        result = extract_exec_target_path(
            'portprotonqt --silent "/a  b  c/game.exe"'
        )
        assert result is not None
        assert "a  b  c" in result

    def test_cyrillic_path_with_spaces(self) -> None:
        result = extract_exec_target_path(
            'portprotonqt --silent "/home/user/Мои Игры/game.exe"'
        )
        assert result is not None
        assert "Мои Игры" in result


# ── _sanitize_icon_name edge cases ───────────────────────────────────────────

class TestSanitizeIconNameEdgeCases:
    def test_multiple_spaces(self) -> None:
        assert _sanitize_icon_name("Game   Title") == "Game___Title"

    def test_cyrillic(self) -> None:
        assert _sanitize_icon_name("Тест Игра") == "Тест_Игра"

    def test_unicode_trademark(self) -> None:
        assert _sanitize_icon_name("Game™") == "Game™"

    def test_mixed_removed_and_kept(self) -> None:
        result = _sanitize_icon_name("A!B%C$D&E<F")
        assert result == "ABCDEF"

    def test_angle_bracket_open_only(self) -> None:
        assert _sanitize_icon_name("Game<Sub") == "GameSub"

    def test_long_name(self) -> None:
        name = "A" * 200
        assert _sanitize_icon_name(name) == name

    def test_slashes_not_sandboxed(self) -> None:
        result = _sanitize_icon_name("Game/Title")
        assert result == "Game/Title"

    def test_name_with_question_mark(self) -> None:
        assert _sanitize_icon_name("Game?") == "Game?"

    def test_name_with_exclamation_only(self) -> None:
        assert _sanitize_icon_name("!") == ""


# ── _get_shortcut_path ───────────────────────────────────────────────────────

class TestGetShortcutPath:
    def _make_stub(self, pp_dir: Path, desktop_path_fn: Any = None) -> Any:
        from portprotonqt.context_menu_manager import ContextMenuManager

        class StubManager:
            portproton_location = str(pp_dir)

            def _get_desktop_path(self, game_name: str) -> str:
                return os.path.join(self.portproton_location, f"{game_name}.desktop")

        if desktop_path_fn is not None:
            StubManager._get_desktop_path = desktop_path_fn  # type: ignore[assignment]
        return ContextMenuManager, StubManager()

    def test_no_desktop_file_uses_game_name(self, tmp_path: Path) -> None:
        cls, mgr = self._make_stub(tmp_path / "PortProtonQt")
        target_dir = tmp_path / "Desktop"
        target_dir.mkdir()
        result = cls._get_shortcut_path(mgr, "New Game", str(target_dir))
        assert result == os.path.join(str(target_dir), "New Game.desktop")

    def test_direct_desktop_file_exists(self, tmp_path: Path) -> None:
        pp_dir = tmp_path / "PortProtonQt"
        pp_dir.mkdir()
        (pp_dir / "My Game.desktop").touch()

        cls, mgr = self._make_stub(pp_dir)
        target_dir = tmp_path / "Desktop"
        target_dir.mkdir()
        result = cls._get_shortcut_path(mgr, "My Game", str(target_dir))
        assert result.endswith("My Game.desktop")
        assert str(target_dir) in result

    def test_fallback_sanitized_name(self, tmp_path: Path) -> None:
        pp_dir = tmp_path / "PortProtonQt"
        pp_dir.mkdir()
        (pp_dir / "My_Game.desktop").touch()

        def desktop_path_fn(self: Any, game_name: str) -> str:
            sanitized = game_name.replace(" ", "_")
            return os.path.join(self.portproton_location, f"{sanitized}.desktop")

        cls, mgr = self._make_stub(pp_dir, desktop_path_fn)
        target_dir = tmp_path / "Desktop"
        target_dir.mkdir()
        result = cls._get_shortcut_path(mgr, "My Game", str(target_dir))
        assert result.endswith("My_Game.desktop")
        assert str(target_dir) in result

    def test_name_with_colon_fallback(self, tmp_path: Path) -> None:
        pp_dir = tmp_path / "PortProtonQt"
        pp_dir.mkdir()
        (pp_dir / "Game__Subtitle.desktop").touch()

        def desktop_path_fn(self: Any, game_name: str) -> str:
            sanitized = game_name.replace("/", "_").replace(":", "_").replace(" ", "_")
            return os.path.join(self.portproton_location, f"{sanitized}.desktop")

        cls, mgr = self._make_stub(pp_dir, desktop_path_fn)
        target_dir = tmp_path / "Desktop"
        target_dir.mkdir()
        result = cls._get_shortcut_path(mgr, "Game: Subtitle", str(target_dir))
        assert "Game__Subtitle.desktop" in result

    def test_name_with_slash_fallback(self, tmp_path: Path) -> None:
        pp_dir = tmp_path / "PortProtonQt"
        pp_dir.mkdir()
        (pp_dir / "Game_Title.desktop").touch()

        def desktop_path_fn(self: Any, game_name: str) -> str:
            sanitized = game_name.replace("/", "_").replace(":", "_").replace(" ", "_")
            return os.path.join(self.portproton_location, f"{sanitized}.desktop")

        cls, mgr = self._make_stub(pp_dir, desktop_path_fn)
        target_dir = tmp_path / "Desktop"
        target_dir.mkdir()
        result = cls._get_shortcut_path(mgr, "Game/Title", str(target_dir))
        assert "Game_Title.desktop" in result

    def test_target_dir_with_spaces(self, tmp_path: Path) -> None:
        cls, mgr = self._make_stub(tmp_path / "PortProtonQt")
        target_dir = tmp_path / "My Games"
        target_dir.mkdir()
        result = cls._get_shortcut_path(mgr, "Test Game", str(target_dir))
        assert str(target_dir) in result
        assert result.endswith("Test Game.desktop")


class TestApplicationsDir:
    def test_uses_xdg_data_home(self, tmp_path: Path, monkeypatch: Any) -> None:
        from portprotonqt.context_menu_manager import ContextMenuManager

        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

        result = ContextMenuManager._get_applications_dir()

        assert result == str(tmp_path / "data" / "applications")


class TestInstallShortcutActions:
    def test_add_to_menu_generates_launch_actions(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        import portprotonqt.context_menu_manager as context_menu

        pp_dir = tmp_path / "PortProtonQt"
        pp_dir.mkdir()
        exe_path = tmp_path / "Game.exe"
        exe_path.touch()
        (pp_dir / "Game.desktop").write_text("[Desktop Entry]\n", encoding="utf-8")
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setattr(
            "portprotonqt.config.portproton.get_portproton_location",
            lambda: str(pp_dir),
        )
        start_detached = MagicMock(return_value=True)
        monkeypatch.setattr(context_menu.QProcess, "startDetached", start_detached)
        manager = object.__new__(context_menu.ContextMenuManager)
        manager.portproton_location = str(pp_dir)
        manager.signals = context_menu.ContextMenuSignals()

        manager.add_to_menu("Game", f"start.sh {exe_path}")

        shortcut = tmp_path / "data" / "applications" / "Game.desktop"
        content = shortcut.read_text(encoding="utf-8")
        assert "Actions=RunSilent;RunLog;" in content
        assert f'Exec=portprotonqt --log "{exe_path}"' in content
        start_detached.assert_called_once_with(
            "update-desktop-database",
            [str(tmp_path / "data" / "applications")],
        )

    def test_add_to_desktop_generates_launch_actions(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        import portprotonqt.context_menu_manager as context_menu

        pp_dir = tmp_path / "PortProtonQt"
        (pp_dir / "data" / "img").mkdir(parents=True)
        exe_path = tmp_path / "Game.exe"
        exe_path.touch()
        (pp_dir / "Game.desktop").write_text("[Desktop Entry]\n", encoding="utf-8")
        (pp_dir / "data" / "img" / "Game.png").touch()
        desktop_dir = tmp_path / "Desktop"
        monkeypatch.setattr(
            "portprotonqt.config.portproton.get_portproton_location",
            lambda: str(pp_dir),
        )
        monkeypatch.setattr(
            context_menu.QStandardPaths,
            "writableLocation",
            lambda _location: str(desktop_dir),
        )
        manager = object.__new__(context_menu.ContextMenuManager)
        manager.portproton_location = str(pp_dir)
        manager.signals = context_menu.ContextMenuSignals()

        manager.add_to_desktop("Game", f"start.sh {exe_path}")

        content = (desktop_dir / "Game.desktop").read_text(encoding="utf-8")
        assert "Actions=RunSilent;RunLog;" in content
        assert f'Exec=portprotonqt --log "{exe_path}"' in content


# ── _get_steam_shortcut_path ─────────────────────────────────────────────────

class TestGetSteamShortcutPath:
    def _make_stub(self) -> tuple[Any, Any]:
        from portprotonqt.context_menu_manager import ContextMenuManager

        class StubManager:
            pass
        return ContextMenuManager, StubManager()

    def test_simple_name(self, tmp_path: Path) -> None:
        cls, mgr = self._make_stub()
        result = cls._get_steam_shortcut_path(mgr, "Counter-Strike 2", str(tmp_path))
        assert result.endswith("Counter-Strike 2.desktop")
        assert str(tmp_path) in result

    def test_name_with_slash(self, tmp_path: Path) -> None:
        cls, mgr = self._make_stub()
        result = cls._get_steam_shortcut_path(mgr, "Game/Title", str(tmp_path))
        assert result.endswith("Game_Title.desktop")

    def test_name_with_colon(self, tmp_path: Path) -> None:
        cls, mgr = self._make_stub()
        result = cls._get_steam_shortcut_path(mgr, "Game: Subtitle", str(tmp_path))
        assert result.endswith("Game_ Subtitle.desktop")

    def test_name_with_null_char(self, tmp_path: Path) -> None:
        cls, mgr = self._make_stub()
        result = cls._get_steam_shortcut_path(mgr, "Game\x00Name", str(tmp_path))
        assert result.endswith("Game_Name.desktop")

    def test_empty_name_fallback(self, tmp_path: Path) -> None:
        cls, mgr = self._make_stub()
        result = cls._get_steam_shortcut_path(mgr, "", str(tmp_path))
        assert result.endswith("Steam Game.desktop")

    def test_whitespace_only_name_fallback(self, tmp_path: Path) -> None:
        cls, mgr = self._make_stub()
        result = cls._get_steam_shortcut_path(mgr, "   ", str(tmp_path))
        assert result.endswith("Steam Game.desktop")

    def test_name_with_spaces_preserved(self, tmp_path: Path) -> None:
        cls, mgr = self._make_stub()
        result = cls._get_steam_shortcut_path(mgr, "Dark Souls III", str(tmp_path))
        assert result.endswith("Dark Souls III.desktop")

    def test_name_with_newline_not_stripped(self, tmp_path: Path) -> None:
        cls, mgr = self._make_stub()
        result = cls._get_steam_shortcut_path(mgr, "Game\nName", str(tmp_path))
        assert "Game\nName.desktop" in result

    def test_target_dir_with_spaces(self, tmp_path: Path) -> None:
        cls, mgr = self._make_stub()
        target = tmp_path / "My Games"
        target.mkdir()
        result = cls._get_steam_shortcut_path(mgr, "Test Game", str(target))
        assert str(target) in result
        assert result.endswith("Test Game.desktop")

    def test_name_with_cyrillic(self, tmp_path: Path) -> None:
        cls, mgr = self._make_stub()
        result = cls._get_steam_shortcut_path(mgr, "Кириллица Игра", str(tmp_path))
        assert result.endswith("Кириллица Игра.desktop")

    def test_name_with_tab_replaced(self, tmp_path: Path) -> None:
        cls, mgr = self._make_stub()
        result = cls._get_steam_shortcut_path(mgr, "Game\tName", str(tmp_path))
        assert "Game" in result
        assert "Name" in result


class TestEditSteamShortcut:
    def test_steam_dialog_has_no_executable_row(self, monkeypatch: Any) -> None:
        from portprotonqt.dialogs.base import AddGameDialog

        _application = QApplication.instance() or QApplication([])
        theme = SimpleNamespace(
            ACTION_BUTTON_STYLE="",
            ADDGAME_INPUT_STYLE="",
            CHECKBOX_STYLE="",
            MAIN_WINDOW_STYLE="",
            MESSAGE_BOX_STYLE="",
            PARAMS_TITLE_STYLE="",
            PREVIEW_WIDGET_STYLE="",
        )
        monkeypatch.setattr(AddGameDialog, "init_keyboard", lambda _self: None)
        monkeypatch.setattr(
            "portprotonqt.dialogs.base.AutoSizeButton",
            lambda text, **_kwargs: QPushButton(text),
        )

        dialog = AddGameDialog(
            theme=theme,
            edit_mode=True,
            game_name="Game",
            steam_appid="730",
        )

        labels = [label.text() for label in dialog.findChildren(QLabel)]
        assert "Path to Executable:" not in labels
        assert dialog.exeEdit.isHidden()
        assert all(
            label.isHidden()
            for label in dialog.findChildren(QLabel)
            if label.text() == "Add shortcut to:"
        )
        dialog.close()

    def test_saves_name_and_cover_by_steam_id(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        import portprotonqt.context_menu_manager as context_menu

        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        source_cover = tmp_path / "selected.webp"
        source_cover.write_bytes(b"cover")
        created_with = {}
        dialog = MagicMock()
        dialog.nameEdit.text.return_value = "New Game"
        dialog.coverEdit.text.return_value = str(source_cover)
        dialog.last_cover_path = str(source_cover)
        dialog.exec.return_value = context_menu.QDialog.DialogCode.Accepted

        def make_dialog(**kwargs: Any) -> MagicMock:
            created_with.update(kwargs)
            return dialog

        manager = context_menu.ContextMenuManager.__new__(
            context_menu.ContextMenuManager
        )
        manager.parent = MagicMock()
        manager.theme = None
        manager.signals = MagicMock()
        old_game = (
            "Old Game", "", "/old.jpg", 730, "", "steam://rungameid/730",
            "", "", "", "", 0, 0, "steam",
        )
        manager.game_library_manager = MagicMock()
        manager.game_library_manager.games = [old_game]
        monkeypatch.setattr(context_menu, "AddGameDialog", make_dialog)

        context_menu.ContextMenuManager._edit_id_shortcut(
            manager, "Old Game", "/cover.jpg", ("steam", "730")
        )

        assert created_with["steam_appid"] == "730"
        game_dir = tmp_path / "PortProtonQt" / "custom_data" / "steam-730"
        assert (game_dir / "cover.webp").read_bytes() == b"cover"
        assert (game_dir / "metadata.txt").read_text(encoding="utf-8") == (
            "name=New Game\n"
        )
        replacement = manager.game_library_manager.replace_game_incremental
        replacement.assert_called_once()
        assert replacement.call_args.args[2][0] == "New Game"
        assert replacement.call_args.args[2][2] == str(game_dir / "cover.webp")
        from portprotonqt.main_window import MainWindow
        assert MainWindow._get_custom_steam_data(730, "Old Game") == (
            "New Game",
            str(game_dir / "cover.webp"),
        )

    def test_saves_name_and_cover_by_store_id(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        import portprotonqt.context_menu_manager as context_menu

        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        source_cover = tmp_path / "selected.png"
        source_cover.write_bytes(b"cover")
        dialog = MagicMock()
        dialog.nameEdit.text.return_value = "Custom GOG Game"
        dialog.coverEdit.text.return_value = str(source_cover)
        dialog.last_cover_path = str(source_cover)
        dialog.exec.return_value = context_menu.QDialog.DialogCode.Accepted
        manager = context_menu.ContextMenuManager.__new__(
            context_menu.ContextMenuManager
        )
        manager.parent = MagicMock()
        manager.theme = None
        manager.signals = MagicMock()
        gog_game = (
            "GOG Game", "", "/old.jpg", "123", "", "gog://launch/123",
            "", "", "", "", 0, 0, "gog",
        )
        egs_game = (
            "EGS Game", "", "/old.jpg", "ABC", "", "egs://launch/ABC",
            "", "", "", "", 0, 0, "egs",
        )
        manager.game_library_manager = MagicMock(games=[gog_game, egs_game])
        monkeypatch.setattr(context_menu, "AddGameDialog", lambda **_kwargs: dialog)

        manager._edit_id_shortcut("GOG Game", "/old.jpg", ("gog", "123"))
        manager._edit_id_shortcut("EGS Game", "/old.jpg", ("egs", "ABC"))

        custom_root = tmp_path / "PortProtonQt" / "custom_data"
        for storage_id in ("gog-123", "egs-ABC"):
            game_dir = custom_root / storage_id
            assert (game_dir / "metadata.txt").read_text() == "name=Custom GOG Game\n"
            assert (game_dir / "cover.png").read_bytes() == b"cover"
        replacement = manager.game_library_manager.replace_game_incremental
        assert replacement.call_count == 2
        assert all(call.args[2][0] == "Custom GOG Game" for call in replacement.call_args_list)


# ── Delete installed shortcuts ───────────────────────────────────────────────

class TestRemoveInstalledShortcuts:
    def test_desktop_database_tuple_failure_is_logged(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        import portprotonqt.context_menu_manager as context_menu

        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(
            context_menu.QProcess, "startDetached", lambda *_args: (False, 0)
        )
        warning = MagicMock()
        monkeypatch.setattr(context_menu.logger, "warning", warning)
        mgr = object.__new__(context_menu.ContextMenuManager)

        mgr._update_desktop_database()

        warning.assert_called_once()

    def test_gog_removal_uses_installed_shortcut_paths(self) -> None:
        from portprotonqt.context_menu_manager import ContextMenuManager

        mgr = object.__new__(ContextMenuManager)
        shortcut_paths = ["/menu/Game.desktop", "/desktop/Game.desktop"]
        mgr._get_installed_shortcut_paths = MagicMock(return_value=shortcut_paths)
        mgr._remove_installed_shortcuts = MagicMock()

        mgr.remove_gog_shortcuts("Game")

        mgr._remove_installed_shortcuts.assert_called_once_with(
            "Game", shortcut_paths
        )

    def test_removes_menu_and_desktop_shortcuts(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        import portprotonqt.context_menu_manager as context_menu

        menu_path = tmp_path / "applications" / "Game.desktop"
        desktop_path = tmp_path / "Desktop" / "Game.desktop"
        menu_path.parent.mkdir()
        desktop_path.parent.mkdir()
        menu_path.touch()
        desktop_path.touch()
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        start_detached = MagicMock(return_value=True)
        monkeypatch.setattr(context_menu.QProcess, "startDetached", start_detached)

        shortcuts = [
            str(menu_path),
            str(desktop_path),
            str(tmp_path / "missing.desktop"),
            str(menu_path),
        ]
        mgr = object.__new__(context_menu.ContextMenuManager)

        mgr._remove_installed_shortcuts("Game", shortcuts)

        assert not menu_path.exists()
        assert not desktop_path.exists()
        start_detached.assert_called_once_with(
            "update-desktop-database",
            [str(tmp_path / "applications")],
        )


# ── Desktop migration with spaces in paths ───────────────────────────────────

class TestMigrationWithSpaces:
    def test_exe_path_with_spaces_migrated(self, monkeypatch: Any) -> None:
        from portprotonqt.config.portproton import _migrate_launcher_line

        monkeypatch.setattr(
            "portprotonqt.config.portproton._get_current_launcher_command",
            lambda: ["portprotonqt", "--silent"],
        )
        old = 'Exec=flatpak run ru.linux_gaming.PortProton --silent "/home/user/My Games/Portal 2/portal2.exe"'
        result = _migrate_launcher_line(old, ["portprotonqt", "--silent"])
        assert "My Games" in result
        assert "portal2.exe" in result
        assert "flatpak" not in result

    def test_game_name_with_spaces_in_exec(self, monkeypatch: Any) -> None:
        from portprotonqt.config.portproton import _migrate_launcher_line

        monkeypatch.setattr(
            "portprotonqt.config.portproton._get_current_launcher_command",
            lambda: ["portprotonqt", "--silent"],
        )
        old = 'portprotonqt --silent "/home/user/Games/Dark Souls III/game.exe"'
        result = _migrate_launcher_line(old, ["portprotonqt", "--silent"])
        assert "Dark Souls III" in result

    def test_full_path_with_multiple_spaces(self, monkeypatch: Any) -> None:
        from portprotonqt.config.portproton import _migrate_launcher_line

        monkeypatch.setattr(
            "portprotonqt.config.portproton._get_current_launcher_command",
            lambda: ["portprotonqt", "--silent"],
        )
        old = 'portprotonqt --silent "/home/user/My Games/Steam/steamapps/common/Portal 2/portal2.exe"'
        result = _migrate_launcher_line(old, ["portprotonqt", "--silent"])
        assert "My Games" in result
        assert "steamapps" in result
        assert "Portal 2" in result

    def test_migrate_desktop_with_space_in_exe_path(self, tmp_path: Path, monkeypatch: Any) -> None:
        from portprotonqt.config.portproton import migrate_legacy_shortcut

        desktop_dir = tmp_path / "desktop"
        desktop_dir.mkdir()
        pp_dir = tmp_path / "PortProtonQt"
        pp_dir.mkdir()

        (desktop_dir / "My Game.desktop").write_text(
            "[Desktop Entry]\n"
            "Name=My Game\n"
            'Exec=flatpak run ru.linux_gaming.PortProton --silent "/home/user/My Games/game.exe"\n',
        )

        monkeypatch.setattr(
            "portprotonqt.config.portproton._get_current_launcher_command",
            lambda: ["portprotonqt", "--silent"],
        )
        monkeypatch.setattr(
            "portprotonqt.config.portproton._get_desktop_paths",
            lambda d: (d,) if d else (),
        )

        migrated = migrate_legacy_shortcut(str(pp_dir), str(desktop_dir))
        assert migrated >= 1

        content = (desktop_dir / "My Game.desktop").read_text()
        assert "My Games" in content
        assert "portprotonqt" in content
        assert "flatpak" not in content

    def test_cyrillic_path_in_exec(self, monkeypatch: Any) -> None:
        from portprotonqt.config.portproton import _migrate_launcher_line

        monkeypatch.setattr(
            "portprotonqt.config.portproton._get_current_launcher_command",
            lambda: ["portprotonqt", "--silent"],
        )
        old = 'portprotonqt --silent "/home/user/Мои Игры/game.exe"'
        result = _migrate_launcher_line(old, ["portprotonqt", "--silent"])
        assert "Мои Игры" in result

    def test_path_with_trailing_spaces_preserved(self, monkeypatch: Any) -> None:
        from portprotonqt.config.portproton import _migrate_launcher_line

        monkeypatch.setattr(
            "portprotonqt.config.portproton._get_current_launcher_command",
            lambda: ["portprotonqt", "--silent"],
        )
        old = 'portprotonqt --silent "/home/user/My Games/game.exe"'
        result = _migrate_launcher_line(old, ["portprotonqt", "--silent"])
        assert "My Games" in result

    def test_double_space_path(self, monkeypatch: Any) -> None:
        from portprotonqt.config.portproton import _migrate_launcher_line

        monkeypatch.setattr(
            "portprotonqt.config.portproton._get_current_launcher_command",
            lambda: ["portprotonqt", "--silent"],
        )
        old = 'portprotonqt --silent "/home/user/My  Games/game.exe"'
        result = _migrate_launcher_line(old, ["portprotonqt", "--silent"])
        assert "My  Games" in result


# ── Desktop shortcut content validation ──────────────────────────────────────

class TestDesktopEntryContent:
    def test_exec_has_quoted_path(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path)
        result = create_desktop_file(exe, game_name="Test")
        assert result is not None
        entry, _, _ = result
        assert "Exec=" in entry
        exec_value = entry.split("Exec=")[1].split("\n")[0]
        assert '"' in exec_value

    def test_comment_has_name(self, tmp_path: Path, monkeypatch: Any) -> None:
        monkeypatch.setattr("portprotonqt.config.portproton._", lambda text: text)
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path)
        result = create_desktop_file(exe, game_name="My Game")
        assert result is not None
        entry, _, _ = result
        assert 'Comment=Launch "My Game" with PortProton' in entry.splitlines()

    def test_icon_path_is_absolute(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path)
        result = create_desktop_file(exe, game_name="Test")
        assert result is not None
        _, _, icon_path = result
        assert os.path.isabs(icon_path)

    def test_desktop_path_is_absolute(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path)
        result = create_desktop_file(exe, game_name="Test")
        assert result is not None
        _, desktop_path, _ = result
        assert os.path.isabs(desktop_path)

    def test_no_path_line_in_entry(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path)
        result = create_desktop_file(exe, game_name="Test")
        assert result is not None
        entry, _, _ = result
        assert "Path=" not in entry


# ── _copy_shortcut ───────────────────────────────────────────────────────────

class TestCopyShortcut:
    def test_basic_copy(self, tmp_path: Path) -> None:
        from portprotonqt.scripts_utils.prefix_backup import _copy_shortcut

        src_dir = tmp_path / "source"
        src_dir.mkdir()
        src = src_dir / "Game.desktop"
        src.write_text("[Desktop Entry]\nName=Game\n")

        target_dir = tmp_path / "target"
        target_dir.mkdir()

        _copy_shortcut(str(src), str(target_dir))
        dest = target_dir / "Game.desktop"
        assert dest.exists()
        assert dest.read_text() == "[Desktop Entry]\nName=Game\n"

    def test_path_with_spaces(self, tmp_path: Path) -> None:
        from portprotonqt.scripts_utils.prefix_backup import _copy_shortcut

        src_dir = tmp_path / "my games"
        src_dir.mkdir()
        src = src_dir / "Dark Souls.desktop"
        src.write_text("[Desktop Entry]\nName=Dark Souls\n")

        target_dir = tmp_path / "target dir"
        target_dir.mkdir()

        _copy_shortcut(str(src), str(target_dir))
        dest = target_dir / "Dark Souls.desktop"
        assert dest.exists()
        assert dest.read_text() == "[Desktop Entry]\nName=Dark Souls\n"

    def test_nonexistent_target_creates_it(self, tmp_path: Path) -> None:
        from portprotonqt.scripts_utils.prefix_backup import _copy_shortcut

        src_dir = tmp_path / "source"
        src_dir.mkdir()
        src = src_dir / "Game.desktop"
        src.write_text("[Desktop Entry]\nName=Game\n")

        target_dir = tmp_path / "nonexistent" / "nested"
        _copy_shortcut(str(src), str(target_dir))
        assert (target_dir / "Game.desktop").exists()

    def test_empty_target_dir_noop(self, tmp_path: Path) -> None:
        from portprotonqt.scripts_utils.prefix_backup import _copy_shortcut

        src_dir = tmp_path / "source"
        src_dir.mkdir()
        src = src_dir / "Game.desktop"
        src.write_text("[Desktop Entry]\nName=Game\n")

        _copy_shortcut(str(src), "")
        assert not (tmp_path / "Game.desktop").exists()

    def test_cyrillic_filename(self, tmp_path: Path) -> None:
        from portprotonqt.scripts_utils.prefix_backup import _copy_shortcut

        src_dir = tmp_path / "source"
        src_dir.mkdir()
        src = src_dir / "Тест.desktop"
        src.write_text("[Desktop Entry]\nName=Тест\n")

        target_dir = tmp_path / "target"
        target_dir.mkdir()

        _copy_shortcut(str(src), str(target_dir))
        dest = target_dir / "Тест.desktop"
        assert dest.exists()
        assert "Тест" in dest.read_text()

    def test_file_permissions(self, tmp_path: Path) -> None:
        from portprotonqt.scripts_utils.prefix_backup import _copy_shortcut

        src_dir = tmp_path / "source"
        src_dir.mkdir()
        src = src_dir / "Game.desktop"
        src.write_text("[Desktop Entry]\nName=Game\n")

        target_dir = tmp_path / "target"
        target_dir.mkdir()

        _copy_shortcut(str(src), str(target_dir))
        dest = target_dir / "Game.desktop"
        assert os.access(str(dest), os.X_OK)


def test_relocate_missing_executable_data(tmp_path: Path, monkeypatch: Any) -> None:
    from portprotonqt.context_menu_manager import ContextMenuManager

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    old_exe = tmp_path / "Old Game.exe"
    new_exe = tmp_path / "New Game.exe"
    new_exe.touch()
    old_ppdb = Path(f"{old_exe}.ppdb")
    old_ppdb.write_text('export WINEPREFIX="GamePrefix"\n')
    root = tmp_path / "PortProtonQt" / "custom_data"
    old_folder = root / "Old Game"
    old_folder.mkdir(parents=True)
    (old_folder / "metadata.txt").write_text("name=My Game\n")
    (old_folder / "cover.png").write_bytes(b"cover")
    (old_folder / "screenshots").mkdir()
    (old_folder / "screenshots" / "1.png").write_bytes(b"screenshot")
    manager = object.__new__(ContextMenuManager)

    manager._relocate_shortcut_data(str(old_exe), str(new_exe))

    new_folder = root / get_custom_data_dir_name(str(new_exe))
    assert not old_folder.exists()
    assert not old_ppdb.exists()
    assert (new_folder / "metadata.txt").read_text() == "name=My Game\n"
    assert (new_folder / "cover.png").read_bytes() == b"cover"
    assert (new_folder / "screenshots" / "1.png").read_bytes() == b"screenshot"
    assert Path(f"{new_exe}.ppdb").read_text() == 'export WINEPREFIX="GamePrefix"\n'


def test_relocate_data_conflict_preserves_source(tmp_path: Path, monkeypatch: Any) -> None:
    import pytest
    from portprotonqt.context_menu_manager import ContextMenuManager

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr("portprotonqt.context_menu_manager._", lambda _text: "Conflict: {file_name}")
    old_exe, new_exe = str(tmp_path / "old.exe"), str(tmp_path / "new.exe")
    root = tmp_path / "PortProtonQt" / "custom_data"
    source = root / get_custom_data_dir_name(old_exe)
    source.mkdir(parents=True)
    (source / "metadata.txt").write_text("original")
    Path(new_exe + ".ppdb").write_text("destination")
    Path(old_exe + ".ppdb").write_text("source")
    manager = object.__new__(ContextMenuManager)

    with pytest.raises(FileExistsError) as error:
        manager._relocate_shortcut_data(old_exe, new_exe)

    assert str(error.value) == f"Conflict: {new_exe}.ppdb"
    assert (source / "metadata.txt").read_text() == "original"
    assert Path(new_exe + ".ppdb").read_text() == "destination"
    assert Path(old_exe + ".ppdb").read_text() == "source"


def test_relocate_statistics_preserves_other_games(tmp_path: Path, monkeypatch: Any) -> None:
    from portprotonqt.context_menu_manager import ContextMenuManager
    from portprotonqt.time_utils import get_last_launch_path, get_statistics_path

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    old_exe, new_exe = str(tmp_path / "Old Game.exe"), str(tmp_path / "New Game.exe")
    statistics = Path(get_statistics_path())
    statistics.parent.mkdir(parents=True, exist_ok=True)
    statistics.write_text(f"{old_exe.replace(' ', '#@_@#')} sha256 125\n/other.exe hash 10\n")
    last_launch = Path(get_last_launch_path())
    last_launch.write_text("Old Game 2026-09-11T12:00:00\nOther 2026-01-01T00:00:00\n")
    manager = object.__new__(ContextMenuManager)

    manager._relocate_shortcut_statistics(old_exe, new_exe)

    assert statistics.read_text() == f"{new_exe.replace(' ', '#@_@#')} sha256 125\n/other.exe hash 10\n"
    assert last_launch.read_text() == "New Game 2026-09-11T12:00:00\nOther 2026-01-01T00:00:00\n"


def test_missing_executable_dialog_actions(monkeypatch: Any) -> None:
    import portprotonqt.context_menu_manager as context_menu

    manager = object.__new__(context_menu.ContextMenuManager)
    manager.parent = None
    manager.delete_game = MagicMock()
    manager.edit_game_shortcut = MagicMock()
    card = SimpleNamespace(name="Game", exec_line="missing.exe", cover_path="cover.png",
                           missing_executable_path="missing.exe")
    dialog = MagicMock()
    buttons = [object(), object(), object()]
    monkeypatch.setattr(context_menu, "QMessageBox", MagicMock(return_value=dialog))
    for selection in range(3):
        dialog.addButton.side_effect = buttons
        dialog.clickedButton.return_value = buttons[selection]
        manager.handle_missing_executable(cast(Any, card))

    manager.delete_game.assert_called_once_with("Game", "missing.exe")
    manager.edit_game_shortcut.assert_called_once_with("Game", "missing.exe", "cover.png")


def test_missing_executable_editor_can_be_cancelled(tmp_path: Path, monkeypatch: Any) -> None:
    import portprotonqt.context_menu_manager as context_menu

    manager = object.__new__(context_menu.ContextMenuManager)
    manager.parent = None
    manager.theme = SimpleNamespace()
    manager._check_portproton = MagicMock(return_value=True)
    manager._get_exec_line = MagicMock(return_value=f'portprotonqt --silent "{tmp_path}/missing.exe"')
    manager._relocate_shortcut_data = MagicMock()
    dialog = MagicMock()
    dialog.exec.return_value = context_menu.QDialog.DialogCode.Rejected
    factory = MagicMock(return_value=dialog)
    monkeypatch.setattr(context_menu, "AddGameDialog", factory)

    manager.edit_game_shortcut("Game", "old command", "cover.png")

    assert factory.call_args.kwargs["exe_path"] == str(tmp_path / "missing.exe")
    manager._relocate_shortcut_data.assert_not_called()


def test_missing_dialog_buttons_fit_translated_text(monkeypatch: Any) -> None:
    import portprotonqt.context_menu_manager as context_menu
    from portprotonqt.themes.standart.styles.base import MAIN_WINDOW_STYLE, MESSAGE_BOX_STYLE

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.setStyleSheet(MAIN_WINDOW_STYLE + MESSAGE_BOX_STYLE)
    manager = object.__new__(context_menu.ContextMenuManager)
    manager.parent = parent
    card = SimpleNamespace(missing_executable_path="/games/Long Game Name/missing.exe")
    translations = {"Delete from PortProton": "Удалить из PortProton",
                    "Select another executable": "Указать другой исполняемый файл"}
    monkeypatch.setattr(context_menu, "_", lambda text: translations.get(text, text))
    widths = []

    def inspect_dialog(dialog: Any) -> int:
        dialog.show()
        app.processEvents()
        widths.extend((button.width(), button.sizeHint().width()) for button in dialog.buttons())
        dialog.reject()
        return 0

    monkeypatch.setattr(context_menu.QMessageBox, "exec", inspect_dialog)
    manager.handle_missing_executable(cast(Any, card))

    assert len(widths) == 3
    assert all(actual >= required for actual, required in widths)


@pytest.mark.parametrize("edited_name", ["Renamed", "Custom Alias"])
@pytest.mark.parametrize("edited_executable", ["/games/game.exe", "/games/other.exe"])
def test_edit_shortcut_removes_desktop_file_with_original_filename(
    tmp_path: Path, monkeypatch: Any, edited_name: str, edited_executable: str,
) -> None:
    import portprotonqt.context_menu_manager as context_menu

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    desktop_dir = tmp_path / "Desktop"
    desktop_dir.mkdir()
    source = tmp_path / "Original.desktop"
    source.write_text("[Desktop Entry]\nName=Renamed\nExec=/games/game.exe\n")
    desktop_shortcut = desktop_dir / source.name
    desktop_shortcut.write_text(source.read_text())
    manager = object.__new__(context_menu.ContextMenuManager)
    manager.parent = None
    manager.theme = SimpleNamespace()
    manager.signals = MagicMock()
    manager._check_portproton = MagicMock(return_value=True)
    manager._get_exec_line = MagicMock(return_value="/games/game.exe")
    manager._get_desktop_path = MagicMock(return_value=str(source))
    manager._get_menu_shortcut_path = MagicMock(return_value=str(tmp_path / "missing.desktop"))
    manager._relocate_shortcut_data = MagicMock(return_value=[])
    manager._relocate_shortcut_statistics = MagicMock()
    dialog = MagicMock()
    dialog.exec.return_value = context_menu.QDialog.DialogCode.Accepted
    dialog.nameEdit.text.return_value = edited_name
    dialog.exeEdit.text.return_value = edited_executable
    dialog.coverEdit.text.return_value = ""
    dialog.getDesktopEntryData.return_value = (
        source.read_text().replace("/games/game.exe", edited_executable), str(source),
    )
    dialog.add_to_menu_checkbox.isChecked.return_value = False
    dialog.add_to_desktop_checkbox.isChecked.return_value = False
    dialog.add_to_steam_checkbox.isChecked.return_value = False
    monkeypatch.setattr(context_menu, "AddGameDialog", lambda **_kwargs: dialog)
    monkeypatch.setattr(context_menu, "is_game_in_steam", lambda _name: False)
    monkeypatch.setattr(
        context_menu.QStandardPaths, "writableLocation", lambda _location: str(desktop_dir)
    )

    manager.edit_game_shortcut("Renamed", "/games/game.exe", "")

    assert not desktop_shortcut.exists()
    assert source.exists()
    assert "Name=Renamed\n" in source.read_text()
    assert f"Exec={edited_executable}\n" in source.read_text()
    if edited_name != "Renamed":
        metadata = next((tmp_path / "data/PortProtonQt/custom_data").glob("*/metadata.txt"))
        assert metadata.read_text() == f"name={edited_name}\n"
    manager.signals.show_warning_dialog.emit.assert_not_called()


@pytest.mark.parametrize("legacy", [False, True])
def test_local_shortcut_name_preserves_metadata_and_resolves_desktop(
    tmp_path: Path, monkeypatch: Any, legacy: bool,
) -> None:
    from portprotonqt.context_menu_manager import ContextMenuManager
    from portprotonqt.config import get_custom_data_dir_name
    from portprotonqt.localization import read_metadata_translations

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    executable = str(tmp_path / "Game.exe")
    desktop = tmp_path / "Original.desktop"
    desktop.write_text(f"[Desktop Entry]\nName=Original\nExec=portprotonqt --silent {executable}\n")
    folder = "Game" if legacy else get_custom_data_dir_name(executable)
    game_dir = tmp_path / "data/PortProtonQt/custom_data" / folder
    game_dir.mkdir(parents=True)
    metadata = game_dir / "metadata.txt"
    metadata.write_text("name=Original\nname_ru=Original RU\ndescription=Details\ndescription_ru=Details RU\n")
    manager = object.__new__(ContextMenuManager)
    manager.portproton_location = str(tmp_path)

    for name in ["Custom Alias", "Another Alias"]:
        manager._save_local_shortcut_name(executable, name)
        assert manager._get_desktop_path(name) == str(desktop)
        assert read_metadata_translations(str(metadata), "ru") == {
            "name": name, "description": "Details RU",
        }
        assert "description=Details\n" in metadata.read_text()
    assert "Name=Original\n" in desktop.read_text()


def test_local_shortcut_name_keeps_metadata_on_write_failure(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import portprotonqt.context_menu_manager as context_menu
    from portprotonqt.config import get_custom_data_dir_name

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    executable = str(tmp_path / "Game.exe")
    game_dir = tmp_path / "PortProtonQt/custom_data" / get_custom_data_dir_name(executable)
    game_dir.mkdir(parents=True)
    metadata = game_dir / "metadata.txt"
    metadata.write_text("name=Original\ndescription=Details\n")
    manager = object.__new__(context_menu.ContextMenuManager)
    monkeypatch.setattr(context_menu.os, "replace", MagicMock(side_effect=OSError("Cannot replace")))
    with pytest.raises(OSError, match="Cannot replace"):
        manager._save_local_shortcut_name(executable, "Renamed")
    assert metadata.read_text() == "name=Original\ndescription=Details\n"
    assert list(game_dir.iterdir()) == [metadata]


@pytest.mark.parametrize("target", ["game.exe", "gog://launch/123", "egs://launch/game-id"])
@pytest.mark.parametrize("batch,result,expected", [
    (True, (True, "restart"), (0, 0)),
    (False, (True, "Game added to Steam via CEF API"), (0, 0)),
    (False, (True, "Please restart Steam"), (1, 0)),
    (False, (False, "Failed to create shortcut"), (0, 1)),
])
def test_steam_addition_dialogs(monkeypatch: Any, batch: bool, result: tuple[bool, str],
                              expected: tuple[int, int], target: str) -> None:
    from portprotonqt.context_menu_manager import ContextMenuManager

    manager = object.__new__(ContextMenuManager)
    manager._batch_action = batch
    manager._check_portproton = lambda: True
    monkeypatch.setattr(manager, "_get_exec_line", lambda game_name, exec_line: exec_line)
    if target == "game.exe":
        monkeypatch.setattr(manager, "_parse_exe_path", lambda exec_line, game_name: exec_line)
    manager.signals = MagicMock()
    api = SimpleNamespace(get_launch_target=MagicMock(return_value="installed.exe"))
    manager.parent = SimpleNamespace(gog_api=api, egs_api=api)
    add_shortcut = MagicMock(return_value=result)
    monkeypatch.setattr("portprotonqt.context_menu_manager.add_to_steam", add_shortcut)
    manager.add_to_steam("Game", target, "cover")
    if target != "game.exe":
        api.get_launch_target.assert_called_once_with(target.rsplit("/", 1)[-1])
        add_shortcut.assert_called_once_with("Game", target, "cover", "installed.exe")
    assert manager.signals.show_info_dialog.emit.call_count == expected[0]
    assert manager.signals.show_warning_dialog.emit.call_count == expected[1]


def test_context_menu_enters_and_cancels_selection_mode(monkeypatch: Any) -> None:
    from portprotonqt.context_menu_manager import ContextMenuManager

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    card = SimpleNamespace(
        batch_selected=False, game_source="portproton", name="Game", exec_line="missing.exe",
        mapToGlobal=lambda position: position, update=MagicMock(), setFocus=MagicMock(),
        isVisible=lambda: True,
    )
    manager = object.__new__(ContextMenuManager)
    manager.parent = parent
    manager.theme = SimpleNamespace(CONTEXT_MENU_STYLE="")
    manager.card_selection_mode = False
    manager.game_library_manager = SimpleNamespace(game_card_cache={"game": card})
    monkeypatch.setattr(manager, "_get_exec_line", lambda *args: None)
    monkeypatch.setattr(manager, "_get_safe_icon", lambda icon: QIcon())
    menus: list[QMenu] = []
    monkeypatch.setattr(QMenu, "popup", lambda menu, position: menus.append(menu))
    manager.show_context_menu(card, QPoint())
    menus[-1].actions()[0].trigger()
    assert manager.card_selection_mode and card.batch_selected
    card.batch_selected = False
    manager.show_context_menu(card, QPoint())
    assert manager.card_selection_mode
    assert all(action.isSeparator() for action in menus[-1].actions()[:-1])
    menus[-1].actions()[-1].trigger()
    assert not manager.card_selection_mode and not card.batch_selected
    parent.deleteLater()
    assert app is not None


def test_batch_steam_removal_has_no_success_dialog(monkeypatch: Any) -> None:
    from portprotonqt.context_menu_manager import ContextMenuManager

    manager = object.__new__(ContextMenuManager)
    manager._batch_action = True
    manager._check_portproton = lambda: True
    monkeypatch.setattr(manager, "_get_exec_line", lambda name, command: command)
    monkeypatch.setattr("portprotonqt.context_menu_manager.extract_exec_target_path", lambda command: command)
    monkeypatch.setattr("portprotonqt.context_menu_manager.remove_from_steam", lambda *args: (True, "restart"))
    manager.signals = MagicMock()
    manager.remove_from_steam("Game", "game.exe", "portproton")
    manager.signals.show_info_dialog.emit.assert_not_called()


def test_steam_removal_has_no_success_dialog(monkeypatch: Any) -> None:
    from portprotonqt.context_menu_manager import ContextMenuManager

    manager = object.__new__(ContextMenuManager)
    manager._batch_action = False
    manager._check_portproton = lambda: True
    monkeypatch.setattr(manager, "_get_exec_line", lambda name, command: command)
    monkeypatch.setattr("portprotonqt.context_menu_manager.extract_exec_target_path", lambda command: command)
    monkeypatch.setattr("portprotonqt.context_menu_manager.remove_from_steam", lambda *args: (True, "removed"))
    manager.signals = MagicMock()
    manager.remove_from_steam("Game", "game.exe", "portproton")
    manager.signals.show_info_dialog.emit.assert_not_called()



@pytest.fixture
def selection_scene(tmp_path: Path, monkeypatch: Any) -> Any:
    from portprotonqt.context_menu_manager import ContextMenuManager

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    cards = [SimpleNamespace(
        name=name, exec_line=f"{name}.exe", cover_path="cover", appid=name,
        batch_selected=True, game_source="portproton", isVisible=lambda: True,
        update=MagicMock(), setFocus=MagicMock(), mapToGlobal=lambda position: position,
    ) for name in ("First", "Second")]
    library = SimpleNamespace(game_card_cache=dict(enumerate(cards)), update_game_grid=MagicMock())
    manager = ContextMenuManager(parent, str(tmp_path), SimpleNamespace(CONTEXT_MENU_STYLE=""), library)
    manager.card_selection_mode = True
    scene = SimpleNamespace(manager=manager, cards=cards, parent=parent, menus=[], steam=set(), root=tmp_path,
                            popup=QMenu.popup)
    monkeypatch.setattr(manager, "_get_safe_icon", lambda icon: QIcon())
    monkeypatch.setattr(manager, "_get_exec_line", lambda name, command: command)
    monkeypatch.setattr(manager, "_parse_exe_path", lambda command, name: command)
    monkeypatch.setattr(manager, "_is_game_running", lambda card: False)
    monkeypatch.setattr(manager, "_get_menu_shortcut_path", lambda name: str(tmp_path / f"menu-{name}"))
    monkeypatch.setattr(manager, "_get_shortcut_path", lambda name, directory: str(tmp_path / f"desktop-{name}"))
    monkeypatch.setattr(manager, "_get_steam_shortcut_path", manager._get_shortcut_path)
    monkeypatch.setattr(manager, "_get_steam_menu_shortcut_path", manager._get_menu_shortcut_path)
    monkeypatch.setattr("portprotonqt.context_menu_manager.get_steam_home", lambda: tmp_path)
    monkeypatch.setattr("portprotonqt.context_menu_manager.is_game_in_steam", lambda name: name in scene.steam)
    monkeypatch.setattr("portprotonqt.context_menu_manager.favorites_config.get_games", lambda: [])
    monkeypatch.setattr(QMenu, "popup", lambda menu, position: scene.menus.append(menu))
    monkeypatch.setattr(parent, "_is_egs_overlay_enabled", MagicMock(return_value=False), raising=False)
    yield scene
    manager.stop_card_actions()
    app.processEvents()
    parent.deleteLater()


@pytest.mark.parametrize("source", ["gog", "egs"])
@pytest.mark.parametrize("in_steam", [True, False])
@pytest.mark.parametrize("installed", [True, False])
def test_store_steam_menu_action(selection_scene: Any, source: str,
                                in_steam: bool, installed: bool) -> None:
    from portprotonqt.localization import _

    scene = selection_scene
    card = scene.cards[0]
    card.game_source = source
    card.exec_line = f"{source}://{'launch' if installed else 'install'}/{card.appid}"
    if in_steam:
        scene.steam.add(card.name)
    scene.manager.add_to_steam = MagicMock()
    scene.manager.remove_from_steam = MagicMock()
    menu = scene.manager.show_context_menu(card, QPoint(), build_only=True)
    text = _("Remove from Steam") if in_steam else _("Add to Steam")
    actions = [action for action in menu.actions() if action.text() == text]
    assert len(actions) == int(installed)
    if not installed:
        return
    actions[0].trigger()
    if in_steam:
        scene.manager.remove_from_steam.assert_called_once_with(card.name, card.exec_line, source)
    else:
        scene.manager.add_to_steam.assert_called_once_with(card.name, card.exec_line, card.cover_path)


@pytest.mark.parametrize("source", ["portproton", "gog", "egs", "steam"])
@pytest.mark.parametrize("installed", [True, False])
def test_batch_menu_contains_all_normal_card_actions(selection_scene: Any, source: str, installed: bool) -> None:
    from portprotonqt.localization import _

    scene = selection_scene
    for card in scene.cards:
        card.game_source = source
        card.exec_line = f"{source}://{'launch' if installed else 'install'}/{card.appid}"
    expected: set[str] = set()
    for card in scene.cards:
        single = scene.manager.show_context_menu(card, QPoint(), build_only=True)
        expected.update(action.text() for action in single.actions() if not action.isSeparator())
    scene.manager.show_context_menu(scene.cards[0], QPoint())
    actual = {action.text() for action in scene.menus[-1].actions() if not action.isSeparator()}
    assert actual == expected | {_("Cancel")}
    if installed:
        assert _("Add to Desktop") in actual
        assert (_("Delete") if source in ("gog", "egs") else _("Edit Shortcut")) in actual


@pytest.mark.parametrize("present", [set(), {"First", "Second"}, {"First"}])
def test_batch_shortcut_actions_follow_each_games_state(selection_scene: Any, present: set[str]) -> None:
    from portprotonqt.localization import _

    scene = selection_scene
    scene.steam.update(present)
    for name in present:
        (scene.root / f"menu-{name}").touch()
        (scene.root / f"desktop-{name}").touch()
    scene.manager.show_context_menu(scene.cards[0], QPoint())
    texts = {action.text() for action in scene.menus[-1].actions()}
    for location in ("Steam", "Menu", "Desktop"):
        assert (_(f"Add to {location}") in texts) == (len(present) < len(scene.cards))
        assert (_(f"Remove from {location}") in texts) == bool(present)


@pytest.mark.parametrize("source", ["portproton", "gog", "egs", "steam"])
def test_batch_desktop_action_only_touches_games_missing_shortcuts(selection_scene: Any, source: str) -> None:
    from portprotonqt.localization import _

    scene = selection_scene
    for card in scene.cards:
        card.game_source = source
        card.exec_line = f"{source}://launch/{card.appid}"
    (scene.root / "desktop-First").touch()
    scene.manager.add_to_desktop = MagicMock()
    scene.manager.add_steam_to_desktop = MagicMock()
    scene.manager.show_context_menu(scene.cards[0], QPoint())
    next(action for action in scene.menus[-1].actions() if action.text() == _("Add to Desktop")).trigger()
    for _index in range(5):
        QCoreApplication.processEvents()
    if source == "steam":
        scene.manager.add_steam_to_desktop.assert_called_once_with("Second", "Second")
        scene.manager.add_to_desktop.assert_not_called()
    else:
        scene.manager.add_to_desktop.assert_called_once_with("Second", scene.cards[1].exec_line)
    assert not scene.manager._batch_action
    assert not any(card.batch_selected for card in scene.cards)


def test_batch_steam_removal_only_touches_existing_entries(selection_scene: Any) -> None:
    from portprotonqt.localization import _

    scene = selection_scene
    scene.steam.add("First")
    scene.manager.remove_from_steam = MagicMock()
    scene.manager.show_context_menu(scene.cards[0], QPoint())
    next(action for action in scene.menus[-1].actions() if action.text() == _("Remove from Steam")).trigger()
    QCoreApplication.processEvents()
    scene.manager.remove_from_steam.assert_called_once_with("First", "First.exe", "portproton")


def test_batch_queue_waits_for_background_operation(selection_scene: Any) -> None:
    from threading import Event
    from PySide6.QtGui import QAction

    release = Event()

    class Operation(QThread):
        def run(self) -> None:
            release.wait()

    scene = selection_scene
    worker = Operation(scene.parent)
    worker.finished.connect(lambda: setattr(scene.parent, "gog_delete_worker", None))
    actions = [QAction("First", scene.parent), QAction("Second", scene.parent)]
    calls: list[str] = []

    def start_operation() -> None:
        scene.parent.gog_delete_worker = worker
        calls.append("First")
        worker.start()

    actions[0].triggered.connect(start_operation)
    actions[1].triggered.connect(lambda: calls.append("Second"))
    try:
        scene.manager._start_card_actions(actions, [])
        QCoreApplication.processEvents()
        assert calls == ["First"]
        loop = QEventLoop()
        actions[1].triggered.connect(loop.quit)
        QTimer.singleShot(0, release.set)
        QTimer.singleShot(1000, loop.quit)
        loop.exec()
        QCoreApplication.processEvents()
        assert calls == ["First", "Second"]
        assert not scene.manager._batch_action
    finally:
        release.set()
        worker.wait()


def test_shutdown_discards_pending_batch_actions(selection_scene: Any) -> None:
    from PySide6.QtGui import QAction

    scene = selection_scene
    calls: list[str] = []
    actions = [QAction("First", scene.parent), QAction("Second", scene.parent)]
    actions[0].triggered.connect(lambda: calls.append("First"))
    actions[1].triggered.connect(lambda: calls.append("Second"))
    scene.manager._start_card_actions(actions, [])
    scene.manager.stop_card_actions()
    QCoreApplication.processEvents()
    assert calls == ["First"]
    assert not scene.manager._batch_action


def test_mixed_store_selection_displays_only_one_menu(selection_scene: Any, monkeypatch: Any) -> None:
    scene = selection_scene
    for card, source in zip(scene.cards, ("gog", "egs"), strict=True):
        card.game_source = source
        card.exec_line = f"{source}://install/{card.appid}"

    def popup(menu: QMenu, position: QPoint) -> None:
        scene.menus.append(menu)
        scene.popup(menu, position)

    monkeypatch.setattr(QMenu, "popup", popup)
    scene.manager.show_context_menu(scene.cards[0], QPoint())
    QCoreApplication.processEvents()
    visible = [widget for widget in QApplication.topLevelWidgets() if isinstance(widget, QMenu) and widget.isVisible()]
    assert visible == [scene.menus[-1]]
    assert all(not child.isVisible() for child in scene.menus[-1].findChildren(QMenu))
    scene.menus[-1].close()


def test_batch_action_includes_selected_cards_hidden_by_search(selection_scene: Any) -> None:
    from portprotonqt.localization import _

    scene = selection_scene
    scene.cards[0].isVisible = lambda: False
    scene.manager.add_to_desktop = MagicMock()
    scene.manager.show_context_menu(scene.cards[1], QPoint())
    next(action for action in scene.menus[-1].actions() if action.text() == _("Add to Desktop")).trigger()
    for _index in range(5):
        QCoreApplication.processEvents()
    assert scene.manager.add_to_desktop.call_args_list == [
        (("First", "First.exe"),), (("Second", "Second.exe"),),
    ]
    assert not scene.manager._batch_action
    assert not any(card.batch_selected for card in scene.cards)


def test_game_folder_scan_selects_one_executable_per_game(tmp_path: Path) -> None:
    from portprotonqt.dialogs.base import GameFolderScanWorker

    app = QApplication.instance() or QApplication([])
    for relative in (
        "First Game/bin/FirstGame.exe", "First Game/launcher.exe", "First Game/unins000.exe",
        "First Game/Redist/vc.exe", "First Game/.hidden/game.exe",
        "Second/Binaries/Win64/Second-Win64-Shipping.exe", "Second/tool.exe",
        "Empty/readme.txt", "Ignored/setup.exe", "loose.exe",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    (tmp_path / "First Game" / "outside.exe").symlink_to(tmp_path / "loose.exe")
    (tmp_path / "Linked").symlink_to(tmp_path / "First Game", target_is_directory=True)
    worker = GameFolderScanWorker(str(tmp_path), app)
    worker.start()
    assert worker.wait(5000)

    assert [name for name, _ in worker.games] == ["First Game", tmp_path.name.replace("_", " "), "Second"]
    assert worker.games[0][1] == str(tmp_path / "First Game/bin/FirstGame.exe")
    assert worker.games[1][1] == str(tmp_path / "loose.exe")
    assert worker.errors == []


def test_game_folder_scan_reports_unreadable_root(tmp_path: Path) -> None:
    from portprotonqt.dialogs.base import GameFolderScanWorker

    app = QApplication.instance() or QApplication([])
    worker = GameFolderScanWorker(str(tmp_path / "missing"), app)
    worker.run()
    assert worker.games == []
    assert len(worker.errors) == 1


def test_game_folder_import_skips_existing_paths_and_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import portprotonqt.dialogs.base as module

    app = QApplication.instance() or QApplication([])
    shortcuts = tmp_path / "shortcuts"
    shortcuts.mkdir()
    games = [(name, str(tmp_path / f"{name}.exe")) for name in ("Existing", "Collision", "New")]
    existing_file = shortcuts / "Existing.desktop"
    existing_file.write_text(f'[Desktop Entry]\nName=Old\nExec=portprotonqt --silent "{games[0][1]}"\n')
    collision = shortcuts / "Collision.desktop"
    collision.write_text("preserve this shortcut")
    monkeypatch.setattr(module, "get_portproton_location", lambda: str(shortcuts))
    monkeypatch.setattr(module, "create_desktop_file", lambda exe, name: (f"Exec={exe}\n", str(shortcuts / f"{name}.desktop"), ""))
    worker = module.GameFolderImportWorker(games + [("Duplicate", games[-1][1])], app)
    worker.start()
    assert worker.wait(5000)

    assert worker.added == 1 and worker.skipped == 3
    assert worker.errors == []
    assert collision.read_text() == "preserve this shortcut"
    assert (shortcuts / "New.desktop").stat().st_mode & 0o111
    assert not (shortcuts / "Duplicate.desktop").exists()


def test_game_folder_import_removes_failed_write_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import portprotonqt.dialogs.base as module

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(module, "get_portproton_location", lambda: str(tmp_path))
    monkeypatch.setattr(module, "create_desktop_file", lambda exe, name: ("entry", str(tmp_path / f"{name}.desktop"), ""))
    chmod = os.chmod

    def fail_first(path: str, mode: int) -> None:
        if path.endswith("Broken.desktop"):
            raise PermissionError("not writable")
        chmod(path, mode)

    monkeypatch.setattr(module.os, "chmod", fail_first)
    worker = module.GameFolderImportWorker([("Broken", "broken.exe"), ("Good", "good.exe")], app)
    worker.run()

    assert worker.added == 1 and len(worker.errors) == 1
    assert not (tmp_path / "Broken.desktop").exists()
    assert (tmp_path / "Good.desktop").exists()


def test_game_folder_workers_registered_for_shutdown() -> None:
    from portprotonqt.tabs.workers import MainWindowWorkersMixin

    worker = SimpleNamespace()
    stopped = []
    window = SimpleNamespace(
        _gameFolderWorkers=[worker],
        _stopWorkerThread=lambda *args: None,
        _stopWorkerThreads=lambda name: MainWindowWorkersMixin._stopWorkerThreads(cast(Any, window), name),
        _stopWorker=lambda *args: stopped.append(args),
    )
    MainWindowWorkersMixin._stopBackgroundWorkers(cast(Any, window))

    assert stopped == [(worker, "_gameFolderWorkers", None)]
    assert window._gameFolderWorkers == []


@pytest.mark.parametrize("cancelled", [False, True])
def test_game_folder_import_completion_refreshes_completed_games(
    monkeypatch: pytest.MonkeyPatch, cancelled: bool,
) -> None:
    from PySide6.QtWidgets import QMessageBox
    import portprotonqt.dialogs.base as module

    app = QApplication.instance() or QApplication([])
    owner = cast(Any, QWidget())
    worker = module.GameFolderImportWorker([], owner)
    worker.added = 2
    owner._gameFolderWorkers = [worker]
    progress = SimpleNamespace(wasCanceled=lambda: cancelled, close=MagicMock(), deleteLater=MagicMock())
    dialog = SimpleNamespace(parentWidget=lambda: owner, gamesAdded=MagicMock(), reject=MagicMock())
    message = MagicMock()
    monkeypatch.setattr(QMessageBox, "information", message)

    module.AddGameDialog._finish_folder_worker(cast(Any, dialog), worker, cast(Any, progress))

    dialog.gamesAdded.emit.assert_called_once()
    assert owner._gameFolderWorkers == []
    message.assert_not_called()
    assert app is not None


@pytest.mark.parametrize("edit_mode", [False, True])
def test_add_game_file_picker_offers_folder_selection_only_for_adding(
    monkeypatch: pytest.MonkeyPatch, edit_mode: bool,
) -> None:
    from PySide6.QtWidgets import QHBoxLayout
    import portprotonqt.dialogs.base as module
    import portprotonqt.dialogs.file_explorer as explorer_module

    app = QApplication.instance() or QApplication([])
    explorer = SimpleNamespace(file_signal=MagicMock(), button_layout=QHBoxLayout(), show=MagicMock())
    monkeypatch.setattr(explorer_module, "FileExplorer", lambda *_args, **_kwargs: explorer)
    monkeypatch.setattr(module, "AutoSizeButton", lambda text, **_kwargs: QPushButton(text))
    dialog = SimpleNamespace(
        last_exe_path=None, edit_mode=edit_mode, onExeSelected=MagicMock(),
        _select_game_folder=MagicMock(), parentWidget=lambda: None,
        theme=SimpleNamespace(ACTION_BUTTON_STYLE=""),
    )

    module.AddGameDialog.browseExe(cast(Any, dialog))

    explorer.file_signal.file_selected.connect.assert_called_once_with(dialog.onExeSelected)
    assert explorer.button_layout.count() == int(not edit_mode)
    if not edit_mode:
        explorer.button_layout.itemAt(0).widget().click()
        dialog._select_game_folder.assert_called_once_with(explorer)
    assert app is not None


def test_game_folder_completion_after_shutdown_does_not_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtWidgets import QMessageBox
    import portprotonqt.dialogs.base as module

    app = QApplication.instance() or QApplication([])
    owner = cast(Any, QWidget())
    owner._gameFolderWorkers = []
    worker = module.GameFolderImportWorker([], owner)
    worker.added = 1
    progress = SimpleNamespace(wasCanceled=lambda: False, close=MagicMock(), deleteLater=MagicMock())
    dialog = SimpleNamespace(parentWidget=lambda: owner, gamesAdded=MagicMock(), reject=MagicMock())
    message = MagicMock()
    monkeypatch.setattr(QMessageBox, "information", message)

    module.AddGameDialog._finish_folder_worker(cast(Any, dialog), worker, cast(Any, progress))

    dialog.gamesAdded.emit.assert_not_called()
    message.assert_not_called()
    assert app is not None


def test_game_folder_import_cancellation_stops_after_current_game(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import portprotonqt.dialogs.base as module

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(module, "get_portproton_location", lambda: str(tmp_path))
    calls = []

    def create(executable: str, name: str) -> tuple[str, str, str]:
        calls.append(name)
        module.QThread.currentThread().requestInterruption()
        return "entry", str(tmp_path / f"{name}.desktop"), ""

    monkeypatch.setattr(module, "create_desktop_file", create)
    worker = module.GameFolderImportWorker([("First", "first.exe"), ("Second", "second.exe")], app)
    worker.start()
    assert worker.wait(5000)

    assert calls == ["First"]
    assert worker.added == 1
    assert not (tmp_path / "Second.desktop").exists()


def test_game_folder_scan_separates_nested_steam_library_executables(tmp_path: Path) -> None:
    from portprotonqt.dialogs.base import GameFolderScanWorker

    app = QApplication.instance() or QApplication([])
    executables = [
        tmp_path / "SteamLibrary/steamapps/common/First/Binaries/Win64/game.exe",
        tmp_path / "SteamLibrary/steamapps/common/Second/bin/game.exe",
        tmp_path / "Games/Third/launch.exe",
    ]
    for executable in executables:
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.touch()
    worker = GameFolderScanWorker(str(tmp_path), app)
    worker.run()

    assert {executable for _, executable in worker.games} == {str(path) for path in executables}
    assert len({name for name, _ in worker.games}) == 3
    assert all(os.sep not in name for name, _ in worker.games)
    assert all(name not in ("SteamLibrary", "Games") for name, _ in worker.games)


def test_game_folder_scan_progress_reports_directory_counts(tmp_path: Path) -> None:
    from portprotonqt.dialogs.base import GameFolderScanWorker

    app = QApplication.instance() or QApplication([])
    for name in ("First/bin", "Second/bin"):
        folder = tmp_path / name
        folder.mkdir(parents=True)
        (folder / "game.exe").touch()
    worker = GameFolderScanWorker(str(tmp_path), app)
    states = []
    worker.progressChanged.connect(states.append)
    worker.run()

    assert states[0][:2] == (0, 1)
    assert states[-1][:2] == (5, 5)
    assert all(0 <= completed <= total for completed, total, _ in states)
    assert [completed for completed, _, _ in states] == sorted(completed for completed, _, _ in states)
    assert any(str(tmp_path / "First/bin") in label for _, _, label in states)


def test_game_folder_import_progress_counts_success_and_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import portprotonqt.dialogs.base as module

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(module, "get_portproton_location", lambda: str(tmp_path))
    monkeypatch.setattr(module, "create_desktop_file", lambda executable, name: ("entry", str(tmp_path / f"{name}.desktop"), ""))
    worker = module.GameFolderImportWorker([("First", "game.exe"), ("Second", "game.exe")], app)
    states = []
    worker.progressChanged.connect(states.append)
    worker.run()

    assert [state[:2] for state in states] == [(0, 2), (1, 2), (1, 2), (2, 2)]
    assert worker.added == 1 and worker.skipped == 1


def test_game_folder_progress_updates_bar_and_respects_cancel() -> None:
    from PySide6.QtWidgets import QProgressDialog
    from portprotonqt.dialogs.base import AddGameDialog

    app = QApplication.instance() or QApplication([])
    progress = QProgressDialog()
    progress.setAutoClose(False)
    progress.setAutoReset(False)
    AddGameDialog._update_folder_progress(cast(Any, None), progress, (2, 5, "Current folder"))

    assert progress.maximum() == 5 and progress.value() == 2
    assert "2/5" in progress.labelText() and "Current folder" in progress.labelText()
    progress.cancel()
    AddGameDialog._update_folder_progress(cast(Any, None), progress, (3, 5, "Next folder"))
    assert progress.wasCanceled()
    assert "Next folder" not in progress.labelText()
    progress.close()
    assert app is not None


def test_game_folder_scan_progress_reaches_dialog_on_ui_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QDialog
    import portprotonqt.dialogs.base as module

    app = QApplication.instance() or QApplication([])
    (tmp_path / "game.exe").touch()
    owner = QWidget()
    dialog = module.AddGameDialog.__new__(module.AddGameDialog)
    QDialog.__init__(dialog, owner)
    dialog.theme = SimpleNamespace(MESSAGE_BOX_STYLE="", PROGRESS_BAR_STYLE="")
    shown = MagicMock()
    monkeypatch.setattr(dialog, "_show_folder_games", shown)
    states = []
    update = dialog._update_folder_progress

    def capture(progress: Any, state: tuple[int, int, str]) -> None:
        assert QThread.currentThread() == app.thread()
        update(progress, state)
        states.append((progress.value(), progress.maximum()))

    monkeypatch.setattr(dialog, "_update_folder_progress", capture)
    worker = module.GameFolderScanWorker(str(tmp_path), owner)
    dialog._start_folder_worker(worker)
    assert worker.wait(5000)
    app.processEvents()

    assert states[-1] == (1, 1)
    shown.assert_called_once_with([(tmp_path.name.replace("_", " "), str(tmp_path / "game.exe"))])
    assert cast(Any, owner)._gameFolderWorkers == []
    dialog.close()
    owner.close()


def test_game_folder_scan_excludes_runtime_and_installer_executables(tmp_path: Path) -> None:
    from portprotonqt.dialogs.base import GameFolderScanWorker

    app = QApplication.instance() or QApplication([])
    junk = (
        "SteamLibrary/steamapps/common/Proton Hotfix/files/lib/wine/x86_64-windows/control.exe",
        "SteamLibrary/steamapps/common/Proton - Experimental/files/share/wine/mono/wine-mono-10.4.1/compiler.exe",
        "prism/java/java-runtime-gamma/bin/java.exe",
        "Games/Mortal Kombat/DiscContentPC/jre/bin/keytool.exe",
        "Games/Unity/MonoBleedingEdge/bin/mono.exe",
        "prefixes/DEFAULT/drive_c/windows/system32/notepad.exe",
        "prefixes/DEFAULT/drive_c/Program Files/Internet Explorer/iexplore.exe",
        "installers/VulkanRT-X64-1.4.357.0-Installer.exe",
        "installers/picasa39-setup.exe", "Games/Game/overlay_test_x64.exe", "tools/oalinst.exe",
    )
    good = (
        "Games/Control/Control.exe", "Games/Unity/Unity.exe", "prism/prismlauncher.exe",
        "prefixes/DEFAULT/drive_c/Program Files/Game/game.exe",
    )
    for relative in junk + good:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    worker = GameFolderScanWorker(str(tmp_path), app)
    worker.run()

    assert {path for _, path in worker.games} == {str(tmp_path / relative) for relative in good}
    assert worker.errors == []


def test_game_folder_scan_skips_proton_distribution_root(tmp_path: Path) -> None:
    from portprotonqt.dialogs.base import GameFolderScanWorker

    app = QApplication.instance() or QApplication([])
    proton = tmp_path / "Proton Custom"
    proton.mkdir()
    (proton / "proton").touch()
    (proton / "tool.exe").touch()
    worker = GameFolderScanWorker(str(tmp_path), app)
    worker.run()

    assert worker.games == []
    assert worker.errors == []


@pytest.fixture(autouse=True)
def isolate_folder_import_resources(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    if not request.node.name.startswith("test_game_folder_"):
        return
    pe = MagicMock()
    pe.__enter__.return_value.FileInfo = []
    monkeypatch.setattr("portprotonqt.dialogs.base.pefile.PE", lambda *_args, **_kwargs: pe)
    monkeypatch.setattr("portprotonqt.dialogs.base.generate_thumbnail", lambda *_args, **_kwargs: False)


@pytest.mark.parametrize("highlight", ["Games/", "../", "other.exe", None])
def test_game_folder_selection_uses_highlighted_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, highlight: str | None,
) -> None:
    import portprotonqt.dialogs.base as module

    app = QApplication.instance() or QApplication([])
    (tmp_path / "Games").mkdir()
    started = []
    explorer = SimpleNamespace(
        current_path=str(tmp_path), accept=MagicMock(),
        file_list=SimpleNamespace(currentItem=lambda: SimpleNamespace(text=lambda: highlight) if highlight else None),
    )
    dialog = SimpleNamespace(parentWidget=lambda: app, _start_folder_worker=started.append)
    module.AddGameDialog._select_game_folder(cast(Any, dialog), cast(Any, explorer))
    expected = tmp_path / "Games" if highlight == "Games/" else tmp_path
    assert started[0].folder == str(expected)
    assert dialog._game_folder_root == str(expected)
    explorer.accept.assert_called_once()


def test_game_folder_scan_stays_inside_selected_folder(tmp_path: Path) -> None:
    from portprotonqt.dialogs.base import GameFolderScanWorker

    app = QApplication.instance() or QApplication([])
    games = tmp_path / "Games"
    games.mkdir()
    (games / "Game.exe").touch()
    outside = tmp_path / "Other"
    outside.mkdir()
    (outside / "Other.exe").touch()
    (games / "Link").symlink_to(outside, target_is_directory=True)
    worker = GameFolderScanWorker(str(games), app)
    worker.run()
    assert worker.games == [("Games", str(games / "Game.exe"))]


@pytest.mark.parametrize("metadata", [{"ProductName": "Actual_Game"}, {"ProductName": "BootstrapPackagedGame"}])
def test_game_folder_scan_identifies_pe_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, metadata: dict,
) -> None:
    from portprotonqt.dialogs.base import GameFolderScanWorker

    app = QApplication.instance() or QApplication([])
    game = tmp_path / "Folder Name"
    game.mkdir()
    (game / "Game.exe").touch()
    pe = MagicMock()
    entries = {key.encode(): value.encode() for key, value in metadata.items()}
    pe.__enter__.return_value.FileInfo = [[SimpleNamespace(StringTable=[SimpleNamespace(entries=entries)])]]
    monkeypatch.setattr("portprotonqt.dialogs.base.pefile.PE", lambda *_args, **_kwargs: pe)
    worker = GameFolderScanWorker(str(game), app)
    worker.run()
    assert worker.games[0][0] == ("Actual Game" if metadata["ProductName"] == "Actual_Game" else "Folder Name")


def test_game_folder_scan_prefers_gog_metadata(tmp_path: Path) -> None:
    from portprotonqt.dialogs.base import GameFolderScanWorker

    app = QApplication.instance() or QApplication([])
    (tmp_path / "game.exe").touch()
    (tmp_path / "goggame-123.info").write_text('{"name": "GOG Game"}')
    worker = GameFolderScanWorker(str(tmp_path), app)
    worker.run()
    assert worker.games[0][0] == "GOG Game"


def test_game_folder_review_imports_checked_games_with_edited_names_and_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtWidgets import QCheckBox, QDialog, QLineEdit
    import portprotonqt.dialogs.base as module

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    theme = SimpleNamespace(MAIN_WINDOW_STYLE="", MESSAGE_BOX_STYLE="", CHECKBOX_STYLE="",
                            PARAMS_TITLE_STYLE="", ACTION_BUTTON_STYLE="", ADDGAME_INPUT_STYLE="",
                            GAME_FOLDER_IMPORT_DIALOG_SIZE=(800, 600), STATUS_BAR_STYLE="", HINTS_LABEL_STYLE="")
    started = []
    dialog = module.AddGameDialog.__new__(module.AddGameDialog)
    QDialog.__init__(dialog, parent)
    dialog.theme = theme
    monkeypatch.setattr(dialog, "_start_folder_worker", started.append)
    monkeypatch.setattr(module, "AutoSizeButton", lambda text, **_kwargs: QPushButton(text))
    monkeypatch.setattr(module, "VirtualKeyboard", lambda parent, **_kwargs: QWidget(parent))

    def review(review: QDialog) -> int:
        review.findChildren(QLineEdit)[0].setText("Edited")
        review.findChildren(QLineEdit, "gameFolderPath")[0].setText("replacement.exe")
        review.findChildren(QCheckBox)[1].setChecked(False)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", review)
    dialog._show_folder_games([("First", "first.exe"), ("Second", "second.exe")])
    assert started[0].games == [("Edited", "replacement.exe")]
    assert app is not None
    dialog.deleteLater()


def test_game_folder_scan_video_layout_skips_mod_tools_and_keeps_game_names(tmp_path: Path) -> None:
    from portprotonqt.dialogs.base import GameFolderScanWorker

    app = QApplication.instance() or QApplication([])
    expected = {
        "Fireworks Mania": "Fireworks.Mania.v2025.07.17/game/Fireworks Mania.exe",
        "Mortal Kombat 9 Komplete Edition": "Mortal Kombat 9 Komplete Edition/DiscContentPC/MKKE.exe",
        "Plants Vs Zombies": "Plants Vs. Zombies/PlantsVsZombiesRH.exe",
        "Супер Корова": "Супер Корова/game/launcher.exe",
    }
    junk = (
        "Plants Vs. Zombies/MelonLoader/Dependencies/Il2CppAssemblyGenerator/Cpp2IL/Cpp2IL.exe",
        "Plants Vs. Zombies/MelonLoader/net35/MonoMod.exe",
        "Plants Vs. Zombies/PlantsVsZombiesRH_Data/Resources/Tool.exe",
        "Mortal Kombat 9 Komplete Edition/DiscContentPC/MKLauncher.exe",
        "Mortal Kombat 9 Komplete Edition/DiscContentPC/jre/bin/java.exe",
    )
    for relative in (*expected.values(), *junk):
        executable = tmp_path / relative
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.touch()
    worker = GameFolderScanWorker(str(tmp_path), app)
    states = []
    worker.progressChanged.connect(states.append)
    worker.run()
    assert dict(worker.games) == {name: str(tmp_path / path) for name, path in expected.items()}
    assert not any("MelonLoader" in label or "_Data" in label for _, _, label in states)


def test_game_folder_scan_prefers_game_over_api_and_exact_name_over_variant(tmp_path: Path) -> None:
    from portprotonqt.dialogs.base import GameFolderScanWorker

    app = QApplication.instance() or QApplication([])
    for relative in (
        "Control/Control.exe", "Control/Control_DX12.exe", "World_of_Tanks_EU/WorldOfTanks.exe",
        "World_of_Tanks_EU/wgc_api.exe", "GameCenter/wgc.exe", "GameCenter/wargamingerrormonitor.exe",
        "GameCenter/dlls/pluginhost.exe", "GameCenter/api/wgc_api.exe",
    ):
        executable = tmp_path / relative
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.touch()
    worker = GameFolderScanWorker(str(tmp_path), app)
    worker.run()
    assert {Path(path).name for _, path in worker.games} == {"Control.exe", "WorldOfTanks.exe", "wgc.exe"}


def test_game_folder_scan_uses_base_gog_name_instead_of_dlc(tmp_path: Path) -> None:
    from portprotonqt.dialogs.base import GameFolderScanWorker

    app = QApplication.instance() or QApplication([])
    (tmp_path / "Biomutant.exe").touch()
    (tmp_path / "goggame-1.info").write_text('{"name":"Mercenary DLC","gameId":"1","rootGameId":"2"}')
    (tmp_path / "goggame-2.info").write_text('{"name":"Biomutant","gameId":"2","rootGameId":"2"}')
    worker = GameFolderScanWorker(str(tmp_path), app)
    worker.run()
    assert worker.games == [("Biomutant", str(tmp_path / "Biomutant.exe"))]


def test_game_folder_scan_does_not_walk_content_after_finding_game(tmp_path: Path) -> None:
    from portprotonqt.dialogs.base import GameFolderScanWorker

    app = QApplication.instance() or QApplication([])
    folder = tmp_path / "Game"
    folder.mkdir()
    (folder / "Play.exe").touch()
    for index in range(GameFolderScanWorker.MAX_SCAN_DIRECTORIES + 1):
        (folder / "Maps" / str(index)).mkdir(parents=True)
    worker = GameFolderScanWorker(str(tmp_path), app)
    states = []
    worker.progressChanged.connect(states.append)
    worker.run()
    assert states[-1][:2] == (2, 2)
    assert len(worker.games) == 1
    assert worker.errors == []


def test_game_folder_scan_invalid_pe_uses_folder_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import portprotonqt.dialogs.base as module

    app = QApplication.instance() or QApplication([])
    (tmp_path / "play.exe").touch()
    monkeypatch.setattr(module.pefile, "PE", MagicMock(side_effect=module.pefile.PEFormatError("invalid PE")))
    worker = module.GameFolderScanWorker(str(tmp_path), app)
    worker.run()
    assert worker.games[0][0] == tmp_path.name.replace("_", " ")


@pytest.mark.parametrize("invalid", ["name", "path", "unchecked"])
def test_game_folder_review_validates_selected_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: str,
) -> None:
    from PySide6.QtWidgets import QCheckBox, QDialog, QLineEdit, QMessageBox
    import portprotonqt.dialogs.base as module

    app = QApplication.instance() or QApplication([])
    exe = tmp_path / "Correct.exe"
    exe.touch()
    title = QLineEdit("" if invalid == "name" else "Game")
    path = QLineEdit(str(tmp_path / "missing.exe") if invalid in ("path", "unchecked") else str(exe))
    checkbox = QCheckBox()
    checkbox.setChecked(invalid != "unchecked")
    review = QDialog()
    warning = MagicMock()
    monkeypatch.setattr(QMessageBox, "warning", warning)
    module.AddGameDialog._accept_folder_games(cast(Any, None), review, [(title, path, checkbox)])
    assert warning.call_count == int(invalid != "unchecked")
    assert review.result() == (QDialog.DialogCode.Accepted if invalid == "unchecked" else QDialog.DialogCode.Rejected)
    assert app is not None


def test_game_folder_browse_updates_edited_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtWidgets import QDialog, QLineEdit
    import portprotonqt.dialogs.base as module
    import portprotonqt.dialogs.file_explorer as explorer_module

    app = QApplication.instance() or QApplication([])
    review = QDialog()
    field = QLineEdit(str(tmp_path / "Wrong.exe"), review)
    selected = str(tmp_path / "api/Correct.exe")
    arguments = {}

    class Picker(QDialog):
        def __init__(self, parent: QWidget, **kwargs: Any) -> None:
            super().__init__(parent)
            arguments.update(kwargs)
            self.file_signal = module.FileSelectedSignal()

        def exec(self) -> int:
            self.file_signal.file_selected.emit(selected)
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(explorer_module, "FileExplorer", Picker)
    module.AddGameDialog._browse_folder_exe(cast(Any, SimpleNamespace(theme=None)), field)
    assert field.text() == selected
    assert arguments["initial_path"] == str(tmp_path)
    assert arguments["file_filter"] == (".exe",)
    assert app is not None


def test_game_folder_review_gamepad_navigation_scrolls_to_last_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtWidgets import QCheckBox, QDialog, QLineEdit, QScrollArea
    from portprotonqt.input_manager import InputManager, PAD_DPAD_Y
    import portprotonqt.dialogs.base as module

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    dialog = module.AddGameDialog.__new__(module.AddGameDialog)
    QDialog.__init__(dialog, parent)
    dialog.theme = SimpleNamespace(MAIN_WINDOW_STYLE="", MESSAGE_BOX_STYLE="", CHECKBOX_STYLE="",
                                   ACTION_BUTTON_STYLE="", ADDGAME_INPUT_STYLE="", GAME_FOLDER_IMPORT_DIALOG_SIZE=(800, 600),
                                   STATUS_BAR_STYLE="", HINTS_LABEL_STYLE="")
    monkeypatch.setattr(module, "AutoSizeButton", lambda text, **_kwargs: QPushButton(text))
    monkeypatch.setattr(module, "VirtualKeyboard", lambda parent, **_kwargs: QWidget(parent))
    manager = InputManager.__new__(InputManager)

    def review(window: QDialog) -> int:
        window.show()
        window.activateWindow()
        app.processEvents()
        first = window.findChildren(QCheckBox)[0]
        first.setFocus(Qt.FocusReason.OtherFocusReason)
        assert manager._handle_dialog_dpad(window, PAD_DPAD_Y, 1)
        assert QApplication.focusWidget() is window.findChildren(QLineEdit)[0]
        target = window.findChildren(QLineEdit, "gameFolderPath")[-1]
        for _step in range(4 * 12):
            if QApplication.focusWidget() is target:
                break
            manager._handle_dialog_dpad(window, PAD_DPAD_Y, 1)
        assert QApplication.focusWidget() is target
        scroll = window.findChild(QScrollArea)
        assert scroll is not None
        assert scroll.verticalScrollBar().value() > 0
        window.reject()
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", review)
    dialog._show_folder_games([(f"Game {index}", f"game{index}.exe") for index in range(12)])
    dialog.deleteLater()


def test_game_folder_review_x_imports_edited_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtWidgets import QDialog, QLineEdit
    from portprotonqt.input_manager import InputManager, BUTTONS
    import portprotonqt.dialogs.base as module

    app = QApplication.instance() or QApplication([])
    executable = tmp_path / "Correct.exe"
    executable.touch()
    owner = QWidget()
    dialog = module.AddGameDialog.__new__(module.AddGameDialog)
    QDialog.__init__(dialog, owner)
    dialog.theme = SimpleNamespace(MAIN_WINDOW_STYLE="", MESSAGE_BOX_STYLE="", CHECKBOX_STYLE="",
                                   ACTION_BUTTON_STYLE="", ADDGAME_INPUT_STYLE="", GAME_FOLDER_IMPORT_DIALOG_SIZE=(800, 600),
                                   STATUS_BAR_STYLE="", HINTS_LABEL_STYLE="")
    started = []
    monkeypatch.setattr(dialog, "_start_folder_worker", started.append)
    monkeypatch.setattr(module, "AutoSizeButton", lambda text, **_kwargs: QPushButton(text))
    monkeypatch.setattr(module, "VirtualKeyboard", lambda parent, **_kwargs: QWidget(parent))
    manager = InputManager.__new__(InputManager)

    def review(window: QDialog) -> int:
        window.show()
        app.processEvents()
        from PySide6.QtWidgets import QLabel
        from portprotonqt.localization import _

        hint_texts = [label.text() for label in window.findChildren(QLabel)]
        assert _("Apply") in hint_texts
        assert _("Close") in hint_texts
        window.findChildren(QLineEdit, "gameFolderPath")[0].setText(str(executable))
        assert manager._handle_active_window_button(window, next(iter(BUTTONS["add_game"])))
        return window.result()

    monkeypatch.setattr(QDialog, "exec", review)
    dialog._show_folder_games([("Game", "Wrong.exe")])
    assert started[0].games == [("Game", str(executable))]
    dialog.deleteLater()


def test_exe_dialog_saves_custom_icon(tmp_path: Path, monkeypatch: Any) -> None:
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QDialog
    from portprotonqt.context_menu_manager import CustomLineEdit
    from portprotonqt.dialogs.base import AddGameDialog
    from portprotonqt.config.portproton import get_custom_icon_path

    _application = QApplication.instance() or QApplication([])
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    source = tmp_path / "selected.png"
    image = QPixmap(16, 16)
    image.fill()
    assert image.save(str(source))
    executable = str(tmp_path / "game.exe")
    dialog = AddGameDialog.__new__(AddGameDialog)
    QDialog.__init__(dialog)
    dialog.edit_mode = False
    dialog.iconEdit = CustomLineEdit(str(source), dialog)
    dialog.exeEdit = CustomLineEdit(executable, dialog)
    dialog.accept()
    saved_icon = get_custom_icon_path(executable)
    assert saved_icon
    assert not QPixmap(saved_icon).isNull()
    assert source.is_file()
    assert dialog.result() == QDialog.DialogCode.Accepted
    dialog.close()
