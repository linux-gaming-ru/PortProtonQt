"""Tests for detail page utilities: gradient stops, wave background, shortcut buttons."""
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

from pytest import MonkeyPatch
from PySide6.QtWidgets import QWidget

import portprotonqt.detail_pages.utils as detail_utils
from portprotonqt.detail_pages import DetailPageManager
from portprotonqt.animations.detail_background import DetailBackgroundAnimations
from portprotonqt.detail_pages.utils import (
    _build_palette_stops,
    _reveal_cover,
    _resolve_gradient_stops,
    _setup_wave_background,
    _remove_wave_background,
    _wave_states,
    remove_cover_background,
)


def test_bounce_cover_reveal_uses_bounce_duration(monkeypatch: MonkeyPatch) -> None:
    animation = MagicMock()
    effect = MagicMock()
    image_label = MagicMock()
    image_label.graphicsEffect.return_value = effect
    theme = SimpleNamespace(GAME_CARD_ANIMATION={
        "detail_page_animation_type": "bounce",
        "detail_page_fade_duration": 100,
        "detail_page_bounce_duration": 700,
    })
    monkeypatch.setattr(detail_utils, "QGraphicsOpacityEffect", MagicMock)
    monkeypatch.setattr(detail_utils, "QPropertyAnimation", MagicMock(return_value=animation))

    _reveal_cover(image_label, theme)

    animation.setDuration.assert_called_once_with(700)


def test_detail_page_exe_fallback_uses_image_cache(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    exe_path = tmp_path / "game.exe"
    exe_path.write_bytes(b"MZ")
    monkeypatch.setattr("portprotonqt.icon_extractor.CACHE_DIR", tmp_path / "cache" / "PortProtonQt")

    fallback_exe, fallback_path = DetailPageManager._get_exe_icon_fallback({
        "exec_line": str(exe_path),
        "name": "Game",
    })

    assert fallback_exe == str(exe_path)
    assert fallback_path == str(
        tmp_path / "cache" / "PortProtonQt" / "images" / "exe_icons" / "game.exe.png"
    )


def test_gog_size_result_ignores_deleted_labels(monkeypatch: MonkeyPatch) -> None:
    label = MagicMock()
    monkeypatch.setattr("portprotonqt.detail_pages.isValid", lambda _label: True)

    DetailPageManager._set_gog_size_values(
        [lambda: None, lambda: None], (100, 200)
    )
    DetailPageManager._set_gog_size_values(
        [lambda: label, lambda: label], (1024 ** 2, 1024 ** 3)
    )

    assert [call.args[0] for call in label.setText.call_args_list] == [
        "1.0 MiB", "1.0 GiB",
    ]


def test_play_button_disables_click_sound() -> None:
    button = MagicMock()
    manager = SimpleNamespace(
        main_window=SimpleNamespace(
            target_exe=None,
            theme_manager=SimpleNamespace(get_icon=lambda *_args, **_kwargs: "play"),
            toggleGame=lambda *_args: None,
        ),
        _make_action_button=lambda *_args: button,
    )

    result = DetailPageManager._create_play_button(
        cast(Any, manager), "/games/game.exe", "game.exe"
    )

    assert result is button
    button.setProperty.assert_called_once_with("sound_event", False)


def test_detail_page_loads_exe_fallback_without_cover(monkeypatch: MonkeyPatch) -> None:
    detail_page = MagicMock()
    detail_page.property.side_effect = {
        "fallbackExe": "/games/game.exe",
        "fallbackIconPath": "/cache/images/Game.png",
    }.get
    image_label = MagicMock()
    relay = SimpleNamespace(pixmap_ready=MagicMock())
    load_pixmap = MagicMock()
    monkeypatch.setattr(detail_utils, "_PixmapReadyRelay", lambda _parent: relay)
    monkeypatch.setattr(detail_utils, "_prepare_cover_reveal", MagicMock())
    monkeypatch.setattr(detail_utils, "load_pixmap_async", load_pixmap)

    detail_utils.setup_image_loading(
        detail_page,
        image_label,
        None,
        SimpleNamespace(theme=MagicMock()),
    )

    assert load_pixmap.call_args.args[:3] == ("", 300, 450)
    assert load_pixmap.call_args.kwargs == {
        "app_name": "",
        "fallback_exe": "/games/game.exe",
        "fallback_icon_path": "/cache/images/Game.png",
    }


def test_compact_game_detail_loads_exe_icon_before_cover() -> None:
    manager = DetailPageManager.__new__(DetailPageManager)
    manager.main_window = SimpleNamespace(current_exec_line="")
    manager._get_content_frame_layout = MagicMock(return_value=None)
    manager._get_main_layout = MagicMock(return_value=None)
    manager._setup_detail_page_animation = MagicMock()
    detail_page = MagicMock(spec=QWidget)
    detail_page.property.return_value = "/games/game.exe"
    image_label = MagicMock()

    manager._finalize_compact_game_page(detail_page, {
        "exec_line": "/games/game.exe",
        "image_label": image_label,
        "cover_path": "/covers/game.jpg",
    })

    manager._setup_detail_page_animation.assert_called_once_with(
        detail_page,
        image_label,
        detail_page,
        None,
    )


def test_compact_steam_detail_loads_local_cover_without_exe(monkeypatch: MonkeyPatch) -> None:
    manager = DetailPageManager.__new__(DetailPageManager)
    manager.main_window = SimpleNamespace(current_exec_line="")
    manager._get_content_frame_layout = MagicMock(return_value=None)
    manager._get_main_layout = MagicMock(return_value=None)
    manager._setup_detail_page_animation = MagicMock()
    detail_page = MagicMock(spec=QWidget)
    detail_page.property.return_value = ""
    image_label = MagicMock()
    monkeypatch.setattr(
        "portprotonqt.detail_pages.get_local_steam_cover",
        lambda _appid: "/steam/librarycache/242760/library_600x900.jpg",
    )
    page_data = manager._create_compact_game_data(
        (MagicMock(), image_label),
        {
            "name": "The Forest",
            "description": "",
            "exec_line": "steam://rungameid/242760",
            "cover_path": "/covers/the-forest.jpg",
            "game_source": "steam",
            "appid": 242760,
        },
        MagicMock(),
        MagicMock(),
    )

    manager._finalize_compact_game_page(detail_page, page_data)

    manager._setup_detail_page_animation.assert_called_once_with(
        detail_page,
        image_label,
        detail_page,
        "/steam/librarycache/242760/library_600x900.jpg",
    )


def test_hltb_results_ignored_after_detail_page_replaced(monkeypatch):
    manager = DetailPageManager.__new__(DetailPageManager)
    original_page: QWidget = MagicMock(spec=QWidget)
    manager.main_window = MagicMock()
    manager._current_detail_page = original_page
    manager._is_compact_detail_layout = MagicMock(return_value=False)
    manager._on_hltb_results = MagicMock()
    hltb = MagicMock()
    monkeypatch.setattr("portprotonqt.detail_pages.HowLongToBeat", MagicMock(return_value=hltb))

    manager._setup_hltb_data("Game", MagicMock(), MagicMock())
    callback = hltb.searchCompleted.connect.call_args.args[0]
    manager._current_detail_page = MagicMock(spec=QWidget)
    callback([MagicMock()])

    manager._on_hltb_results.assert_not_called()


def test_compact_layout_rebuild_preserves_running_button() -> None:
    manager = DetailPageManager.__new__(DetailPageManager)
    old_page = MagicMock(spec=QWidget)
    old_button = MagicMock()
    new_page = MagicMock(spec=QWidget)
    new_button = MagicMock()
    old_page.isAncestorOf.return_value = True
    manager.main_window = SimpleNamespace(
        current_running_button=old_button,
        _set_running_button_stop=MagicMock(),
    )
    manager._current_detail_source = ("game", {"name": "Game"})
    manager._current_detail_page = old_page
    cast(Any, manager).debug_log_manager = SimpleNamespace(is_running=False)
    manager._debug_log_button = None
    manager._return_to_tab_index = 0
    manager._remove_current_detail_page = MagicMock()
    manager.openGameDetailPage = MagicMock(
        side_effect=lambda _data: setattr(manager, "_current_detail_page", new_page)
    )
    manager._find_play_button = MagicMock(return_value=new_button)

    manager._reopen_current_detail_page()

    assert manager.main_window.current_running_button is new_button
    manager.main_window._set_running_button_stop.assert_called_once_with()


def test_compact_layout_rebuild_preserves_debug_log_button(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr("portprotonqt.detail_pages._", lambda text: text)
    manager = DetailPageManager.__new__(DetailPageManager)
    old_page = MagicMock(spec=QWidget)
    old_button = MagicMock()
    new_button = MagicMock()
    stop_icon = object()
    old_page.isAncestorOf.return_value = True
    manager.main_window = SimpleNamespace(
        current_running_button=None,
        theme_manager=SimpleNamespace(
            get_icon=MagicMock(return_value=stop_icon),
        ),
    )
    cast(Any, manager).debug_log_manager = SimpleNamespace(is_running=True)
    manager._debug_log_button = old_button
    manager._current_detail_source = ("game", {"name": "Game"})
    manager._current_detail_page = old_page
    manager._return_to_tab_index = 0
    manager._remove_current_detail_page = MagicMock()
    manager.openGameDetailPage = MagicMock(
        side_effect=lambda _data: setattr(manager, "_debug_log_button", new_button)
    )

    manager._reopen_current_detail_page()

    new_button.setText.assert_called_once_with("Stop Log")
    new_button.setIcon.assert_called_once_with(stop_icon)


def _make_palette(colors):
    """Create mock palette with name() returning hex colors."""
    palette = []
    for c in colors:
        m = MagicMock()
        m.name.return_value = c
        palette.append(m)
    return palette


# === _build_palette_stops ===


class TestBuildPaletteStops:
    def test_even_distribution(self):
        palette = _make_palette(["#aaa", "#bbb", "#ccc"])
        result = _build_palette_stops(palette)
        assert "stop:0.00 #aaa" in result
        assert "stop:0.50 #bbb" in result
        assert "stop:1.00 #ccc" in result

    def test_single_color(self):
        palette = _make_palette(["#fff"])
        result = _build_palette_stops(palette)
        assert "stop:0 #fff" in result


# === _resolve_gradient_stops ===


class TestResolveGradientStops:
    def test_none_returns_palette(self):
        theme = MagicMock()
        theme.DETAIL_PAGE_GRADIENT = None
        palette = _make_palette(["#111", "#222"])
        result = _resolve_gradient_stops(theme, palette)
        assert "#111" in result
        assert "#222" in result

    def test_missing_attr_returns_palette(self):
        theme = MagicMock(spec=[])
        palette = _make_palette(["#111", "#222"])
        result = _resolve_gradient_stops(theme, palette)
        assert "#111" in result

    def test_string_passthrough(self):
        theme = MagicMock()
        theme.DETAIL_PAGE_GRADIENT = "stop:0 #ff0000, stop:1 #00ff00"
        result = _resolve_gradient_stops(theme, [])
        assert result == "stop:0 #ff0000, stop:1 #00ff00"

    def test_positions_only(self):
        theme = MagicMock()
        theme.DETAIL_PAGE_GRADIENT = [0, 0.5, 1]
        palette = _make_palette(["#aaa", "#bbb", "#ccc"])
        result = _resolve_gradient_stops(theme, palette)
        assert "stop:0 #aaa" in result
        assert "stop:0.5 #bbb" in result
        assert "stop:1 #ccc" in result

    def test_positions_fewer_than_palette(self):
        theme = MagicMock()
        theme.DETAIL_PAGE_GRADIENT = [0, 1]
        palette = _make_palette(["#aaa", "#bbb", "#ccc"])
        result = _resolve_gradient_stops(theme, palette)
        assert "stop:0 #aaa" in result
        assert "stop:1 #bbb" in result

    def test_positions_more_than_palette(self):
        theme = MagicMock()
        theme.DETAIL_PAGE_GRADIENT = [0, 0.33, 0.66, 1]
        palette = _make_palette(["#aaa", "#bbb"])
        result = _resolve_gradient_stops(theme, palette)
        assert "stop:0 #aaa" in result
        assert "stop:0.33 #bbb" in result
        assert "stop:0.66 #bbb" in result
        assert "stop:1 #bbb" in result

    def test_dicts_override_colors(self):
        theme = MagicMock()
        theme.DETAIL_PAGE_GRADIENT = [
            {"position": 0, "color": "#ff0000"},
            {"position": 1, "color": "#00ff00"},
        ]
        palette = _make_palette(["#aaa", "#bbb"])
        result = _resolve_gradient_stops(theme, palette)
        assert "stop:0 #ff0000" in result
        assert "stop:1 #00ff00" in result
        assert "#aaa" not in result

    def test_tuples_override_colors(self):
        theme = MagicMock()
        theme.DETAIL_PAGE_GRADIENT = (
            (0, "#ff0000"),
            (1, "#00ff00"),
        )
        palette = _make_palette(["#aaa", "#bbb"])
        result = _resolve_gradient_stops(theme, palette)
        assert "stop:0 #ff0000" in result
        assert "stop:1 #00ff00" in result

    def test_string_items_in_list(self):
        theme = MagicMock()
        theme.DETAIL_PAGE_GRADIENT = ["stop:0 #ff0000", "stop:1 #00ff00"]
        palette = _make_palette(["#aaa", "#bbb"])
        result = _resolve_gradient_stops(theme, palette)
        assert "stop:0 #ff0000" in result
        assert "stop:1 #00ff00" in result

    def test_nested_background_gradient(self):
        theme = SimpleNamespace(DETAIL_PAGE_BACKGROUNDS={
            "gradient": {"stops": "stop:0 #123456, stop:1 #654321"},
        })
        result = _resolve_gradient_stops(theme, [])
        assert result == "stop:0 #123456, stop:1 #654321"

    def test_legacy_gradient_overrides_nested_background(self):
        theme = SimpleNamespace(
            DETAIL_PAGE_BACKGROUNDS={
                "gradient": {"stops": "stop:0 #123456"},
            },
            DETAIL_PAGE_GRADIENT="stop:0 #abcdef",
        )
        result = _resolve_gradient_stops(theme, [])
        assert result == "stop:0 #abcdef"


# === _setup_wave_background ===


class TestSetupWaveBackground:
    def test_gradient_mode_removes_waves(self):
        theme = MagicMock()
        theme.DETAIL_PAGE_BG_MODE = "gradient"
        page = MagicMock()
        page.width.return_value = 800
        page.height.return_value = 600
        _wave_states[page] = {"timer": MagicMock()}
        _setup_wave_background(page, [], theme)
        assert page not in _wave_states

    def test_static_waves_no_timer(self):
        theme = MagicMock()
        theme.DETAIL_PAGE_BG_MODE = "static_waves"
        theme.DETAIL_PAGE_WAVES = {}
        page = MagicMock()
        page.width.return_value = 800
        page.height.return_value = 600
        _setup_wave_background(page, _make_palette(["#111"]), theme)
        state = _wave_states.get(page)
        assert state is not None
        assert state.get("timer") is None

    def test_waves_creates_timer(self, monkeypatch):
        mock_timer = MagicMock()
        mock_qtimer = MagicMock(return_value=mock_timer)
        monkeypatch.setattr(
            "portprotonqt.detail_pages.utils.QTimer", mock_qtimer,
        )
        theme = MagicMock()
        theme.DETAIL_PAGE_BG_MODE = "waves"
        theme.DETAIL_PAGE_WAVES = {"animation_speed": 0.05, "animation_interval_ms": 50}
        page = MagicMock()
        page.width.return_value = 800
        page.height.return_value = 600
        _setup_wave_background(page, _make_palette(["#111"]), theme)
        state = _wave_states.get(page)
        assert state is not None
        assert state.get("timer") is mock_timer
        mock_timer.setInterval.assert_called_once_with(50)
        mock_timer.timeout.connect.assert_called_once()
        mock_timer.start.assert_called_once()

    def test_waves_use_nested_background_config(self, monkeypatch):
        timer = MagicMock()
        monkeypatch.setattr(
            "portprotonqt.detail_pages.utils.QTimer", MagicMock(return_value=timer),
        )
        theme = SimpleNamespace(
            DETAIL_PAGE_BG_MODE="waves",
            DETAIL_PAGE_BACKGROUNDS={
                "waves": {
                    "animation_speed": 0.04,
                    "animation_interval_ms": 45,
                },
            },
        )
        page = MagicMock()
        _setup_wave_background(page, _make_palette(["#111"]), theme)
        timer.setInterval.assert_called_once_with(45)

    def test_called_twice_updates_palette(self):
        theme = MagicMock()
        theme.DETAIL_PAGE_BG_MODE = "static_waves"
        theme.DETAIL_PAGE_WAVES = {}
        page = MagicMock()
        page.width.return_value = 800
        page.height.return_value = 600
        palette1 = _make_palette(["#111"])
        palette2 = _make_palette(["#222"])
        _setup_wave_background(page, palette1, theme)
        _setup_wave_background(page, palette2, theme)
        state = _wave_states.get(page)
        assert state is not None
        assert state["palette"] == palette2
        assert state.get("original_paint") is not None


# === DetailBackgroundAnimations ===


class TestDetailBackgroundAnimations:
    def test_leaf_replaces_sakura_background(self) -> None:
        manager = DetailBackgroundAnimations()
        assert "leaf" in manager.effects
        assert "sakura" not in manager.effects

    def test_builds_supported_leaf_shapes(self) -> None:
        manager = DetailBackgroundAnimations()
        for leaf_type in ("generic", "sakura", "oak", "maple", "birch"):
            assert manager._leaf_path(leaf_type, 10).elementCount() > 0

    def test_supports_all_omikuji_backgrounds_in_static_mode(self):
        manager = DetailBackgroundAnimations()
        page = MagicMock()
        for effect in manager.effects:
            config = {effect: {}}
            theme = SimpleNamespace(
                DETAIL_PAGE_BG_MODE=f"static_{effect}",
                DETAIL_PAGE_BACKGROUNDS=config,
            )
            assert manager.setup(page, _make_palette(["#111"]), theme)
            assert manager._states[page]["effect"] == effect
            assert manager._states[page]["timer"] is None

    def test_animated_mode_starts_timer(self, monkeypatch):
        timer = MagicMock()
        monkeypatch.setattr(
            "portprotonqt.animations.detail_background.QTimer",
            MagicMock(return_value=timer),
        )
        manager = DetailBackgroundAnimations()
        page = MagicMock()
        theme = SimpleNamespace(
            DETAIL_PAGE_BG_MODE="aurora",
            DETAIL_PAGE_BACKGROUNDS={
                "animation_interval_ms": 40,
                "animation_speed": 0.02,
                "aurora": {},
            },
        )
        assert manager.setup(page, _make_palette(["#111"]), theme)
        timer.setInterval.assert_called_once_with(40)
        timer.start.assert_called_once()
        assert manager._states[page]["timer"] is timer

    def test_incomplete_effect_config_is_not_installed(self):
        manager = DetailBackgroundAnimations()
        page = MagicMock()
        theme = SimpleNamespace(
            DETAIL_PAGE_BG_MODE="leaf",
            DETAIL_PAGE_BACKGROUNDS={"animation_interval_ms": 30},
        )

        assert not manager.setup(page, _make_palette(["#111"]), theme)
        assert page not in manager._states

    def test_wave_mode_is_not_claimed(self):
        manager = DetailBackgroundAnimations()
        page = MagicMock()
        theme = SimpleNamespace(DETAIL_PAGE_BG_MODE="waves")
        assert not manager.setup(page, _make_palette(["#111"]), theme)
        assert page not in manager._states

# === _remove_wave_background ===


def test_remove_cover_background_stops_procedural_effect() -> None:
    page = MagicMock()
    timer = MagicMock()
    original_paint = MagicMock()
    detail_utils._detail_backgrounds._states[page] = {
        "timer": timer,
        "original_paint": original_paint,
    }

    remove_cover_background(page)

    timer.stop.assert_called_once()
    timer.deleteLater.assert_called_once()
    assert page.paintEvent is original_paint


class TestRemoveWaveBackground:
    def test_no_state(self):
        page = MagicMock()
        _remove_wave_background(page)

    def test_stops_timer(self):
        page = MagicMock()
        timer = MagicMock()
        _wave_states[page] = {
            "timer": timer,
            "original_paint": MagicMock(),
        }
        _remove_wave_background(page)
        timer.stop.assert_called_once()
        timer.deleteLater.assert_called_once()
        assert page not in _wave_states

    def test_restores_paint_event(self):
        page = MagicMock()
        original = MagicMock()
        _wave_states[page] = {"timer": None, "original_paint": original}
        _remove_wave_background(page)
        assert page.paintEvent == original


# === Shortcut button exclusivity (regression: 7e38d9a) ===


def _make_manager_with_shortcut_mock(has_shortcut: bool, monkeypatch=None) -> DetailPageManager:
    manager = DetailPageManager.__new__(DetailPageManager)
    manager.main_window = MagicMock()
    manager.main_window.theme = MagicMock()
    manager._has_game_shortcut = MagicMock(return_value=has_shortcut)
    mock_button = MagicMock()
    mock_button.clicked = MagicMock()
    mock_button.clicked.connect = MagicMock()
    manager._make_action_button = MagicMock(return_value=mock_button)
    manager._create_play_button = MagicMock(return_value=MagicMock())
    manager._get_current_exe = MagicMock(return_value=None)
    if monkeypatch is not None:
        from portprotonqt.custom_widgets import FlowLayout
        monkeypatch.setattr(FlowLayout, "addWidget", lambda self, w: None)
        monkeypatch.setattr(FlowLayout, "count", lambda self: 0)
    return manager


def _get_added_buttons(manager) -> list[str]:
    """Collect button texts added via _make_action_button."""
    texts = []
    for call in manager._make_action_button.call_args_list:
        texts.append(call.args[0])
    return texts


def test_non_steam_with_shortcut_shows_edit_not_add(monkeypatch) -> None:
    manager = _make_manager_with_shortcut_mock(has_shortcut=True, monkeypatch=monkeypatch)
    manager._create_game_buttons_layout({
        "game_source": "portproton",
        "exec_line": "/games/test.exe",
        "name": "Test Game",
    })

    button_texts = _get_added_buttons(manager)
    edit_count = sum(1 for t in button_texts if "Edit" in t or "Редактир" in t)
    add_count = sum(1 for t in button_texts if "Add" in t or "Добавить" in t)
    assert edit_count == 1
    assert add_count == 0


def test_non_steam_without_shortcut_shows_add_not_edit(monkeypatch) -> None:
    manager = _make_manager_with_shortcut_mock(has_shortcut=False, monkeypatch=monkeypatch)
    manager._create_game_buttons_layout({
        "game_source": "portproton",
        "exec_line": "/games/test.exe",
        "name": "Test Game",
    })

    button_texts = _get_added_buttons(manager)
    edit_count = sum(1 for t in button_texts if "Edit" in t or "Редактир" in t)
    add_count = sum(1 for t in button_texts if "Add" in t or "Добавить" in t)
    assert edit_count == 0
    assert add_count == 1


def test_egs_install_detail_shows_install_button(monkeypatch) -> None:
    monkeypatch.setattr("portprotonqt.detail_pages._", lambda text: text)
    manager = _make_manager_with_shortcut_mock(has_shortcut=False, monkeypatch=monkeypatch)
    play_button = cast(Any, manager._create_play_button).return_value

    manager._create_game_buttons_layout({
        "game_source": "egs",
        "exec_line": "egs://install/doom64",
        "appid": "doom64",
        "name": "DOOM 64",
    })

    play_button.setText.assert_called_once_with("Install")


def test_installed_egs_detail_shows_store_controls(monkeypatch) -> None:
    monkeypatch.setattr("portprotonqt.detail_pages._", lambda text: text)
    manager = _make_manager_with_shortcut_mock(has_shortcut=False, monkeypatch=monkeypatch)
    manager.main_window.egs_api.get_launch_target.return_value = "/games/DOOM64.exe"

    manager._create_game_buttons_layout({
        "game_source": "egs",
        "exec_line": "egs://launch/doom64",
        "appid": "doom64",
        "name": "DOOM 64",
    })

    assert _get_added_buttons(manager) == ["Settings", "Create Log", "Open Folder"]


def test_steam_with_appid_shows_edit_not_add(monkeypatch) -> None:
    manager = _make_manager_with_shortcut_mock(has_shortcut=False, monkeypatch=monkeypatch)
    manager._create_game_buttons_layout({
        "game_source": "steam",
        "exec_line": "steam://rungameid/12345",
        "appid": 12345,
        "name": "Steam Game",
    })

    button_texts = _get_added_buttons(manager)
    edit_count = sum(1 for t in button_texts if "Edit" in t or "Редактир" in t)
    add_count = sum(1 for t in button_texts if "Add" in t or "Добавить" in t)
    assert edit_count == 1
    assert add_count == 0
