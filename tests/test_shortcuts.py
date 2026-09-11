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

from PySide6.QtCore import QPoint, Qt
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
        game_source="portproton",
        name="Missing Game",
        exec_line="",
        mapToGlobal=lambda position: position,
    )
    manager = ContextMenuManager.__new__(ContextMenuManager)
    manager.parent = parent
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


def test_add_to_steam_for_all_accounts(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    steam_home = tmp_path / "steam"
    user_ids = ("76561197960265729", "76561197960265730")
    executable = tmp_path / "game.exe"
    executable.touch()
    script_path = tmp_path / "game.sh"

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
    monkeypatch.setattr(
        steam_shortcuts,
        "_create_launch_script",
        lambda *_args: (str(script_path), ""),
    )
    monkeypatch.setattr(steam_shortcuts, "_generate_icon", lambda *_args: "")
    monkeypatch.setattr(
        steam_shortcuts.game_config, "get_steam_account_id", lambda: "all"
    )
    monkeypatch.setattr(
        steam_shortcuts.ui_config, "get_economy_mode", lambda: True
    )

    result, _message = steam_shortcuts.add_to_steam(
        "Test Game", str(executable), ""
    )

    assert result is True
    for account_id in ("1", "2"):
        shortcuts_path = (
            steam_home / "userdata" / account_id / "config" / "shortcuts.vdf"
        )
        assert shortcuts_path.is_file()
        shortcuts = steam_shortcuts.safe_vdf_load(shortcuts_path)["shortcuts"]
        assert shortcuts["0"]["AppName"] == "Test Game"


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
    def test_spaces_underscored(self) -> None:
        assert _sanitize_icon_name("My Game") == "My_Game"

    def test_multiple_spaces(self) -> None:
        assert _sanitize_icon_name("Game   Title") == "Game___Title"

    def test_cyrillic(self) -> None:
        assert _sanitize_icon_name("Тест Игра") == "Тест_Игра"

    def test_unicode_trademark(self) -> None:
        assert _sanitize_icon_name("Game™") == "Game™"

    def test_only_removed_chars(self) -> None:
        assert _sanitize_icon_name("!%$&") == ""

    def test_mixed_removed_and_kept(self) -> None:
        result = _sanitize_icon_name("A!B%C$D&E<F")
        assert result == "ABCDEF"

    def test_angle_bracket_open_only(self) -> None:
        assert _sanitize_icon_name("Game<Sub") == "GameSub"

    def test_long_name(self) -> None:
        name = "A" * 200
        assert _sanitize_icon_name(name) == name

    def test_empty_string(self) -> None:
        assert _sanitize_icon_name("") == ""

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

        context_menu.ContextMenuManager._edit_steam_shortcut(
            manager, "Old Game", 730, "/cover.jpg"
        )

        assert created_with["steam_appid"] == "730"
        game_dir = tmp_path / "PortProtonQt" / "custom_data" / "730"
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
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path)
        result = create_desktop_file(exe, game_name="My Game")
        assert result is not None
        entry, _, _ = result
        assert "My Game" in entry

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

    def test_categories_line_present(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path)
        result = create_desktop_file(exe, game_name="Test")
        assert result is not None
        entry, _, _ = result
        assert "Categories=Game;" in entry

    def test_startup_notify_true(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path)
        result = create_desktop_file(exe, game_name="Test")
        assert result is not None
        entry, _, _ = result
        assert "StartupNotify=true" in entry

    def test_terminal_false(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_location(monkeypatch, tmp_path)
        exe = _make_exe(tmp_path)
        result = create_desktop_file(exe, game_name="Test")
        assert result is not None
        entry, _, _ = result
        assert "Terminal=false" in entry


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


def test_edit_shortcut_removes_desktop_file_with_original_filename(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import portprotonqt.context_menu_manager as context_menu

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
    dialog = MagicMock()
    dialog.exec.return_value = context_menu.QDialog.DialogCode.Accepted
    dialog.nameEdit.text.return_value = "Renamed"
    dialog.exeEdit.text.return_value = "/games/game.exe"
    dialog.coverEdit.text.return_value = ""
    dialog.getDesktopEntryData.return_value = (source.read_text(), str(source))
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
    manager.signals.show_warning_dialog.emit.assert_not_called()
