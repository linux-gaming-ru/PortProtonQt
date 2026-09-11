"""Tests for main window library data processing."""

import shlex
import signal
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
import threading
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import psutil
from pytest import MonkeyPatch, mark
from PySide6.QtCore import QEventLoop, QObject, Qt, QTimer
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QGridLayout,
    QLabel,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from portprotonqt.animations.library_controls import _animation_duration
from portprotonqt.animations.game_card import GameCardAnimations
from portprotonqt.config import game_config
from portprotonqt.custom_widgets import AutoHideScrollArea, AutoSizeButton
from portprotonqt.detail_pages import DetailPageManager
from portprotonqt.game_card import GameCard, SourceCorner
from portprotonqt.game_library_manager import FullLibraryTile, GameLibraryManager
from portprotonqt.main_window import MainWindow
from portprotonqt.tray_manager import TrayManager
from portprotonqt.themes.standart.styles.constants import GAME_CARD_ANIMATION
from portprotonqt.portproton_api import remove_empty_custom_data_dirs
import portprotonqt.tabs.autoinstall_tab as autoinstall_tab_module
import portprotonqt.tabs.download_tab as download_tab_module
import portprotonqt.tabs.library_tab as library_tab_module
import portprotonqt.tabs.system_tab as system_tab_module
import portprotonqt.steam_api.api as steam_api_module
import portprotonqt.main_window as main_window_module

from portprotonqt.tabs import (
    MainWindowAutoInstallTabMixin,
    MainWindowLibraryTabMixin,
    MainWindowSettingsTabMixin,
    MainWindowSystemTabMixin,
    MainWindowThemeTabMixin,
    MainWindowWineTabMixin,
)
from portprotonqt.tabs.autoinstall_tab import MainWindowAutoInstallTabMixin as AutoInstallMixin
from portprotonqt.tabs.download_tab import MainWindowDownloadTabMixin as GOGMixin
from portprotonqt.tabs.library_tab import MainWindowLibraryTabMixin as LibraryMixin
from portprotonqt.tabs.settings_tab import MainWindowSettingsTabMixin as SettingsMixin
from portprotonqt.tabs.theme_store import THEME_STORE_ITEM, ThemeStoreMixin
from portprotonqt.tabs.theme_tab import (
    MainWindowThemeTabMixin as ThemeMixin,
)
from portprotonqt.tabs.wine_tab import MainWindowWineTabMixin as WineMixin

def _tile_theme() -> Any:
    return SimpleNamespace(
        fullLibraryTileSize=(180, 180),
        fullLibraryTileColumns=2,
        fullLibraryTileRows=2,
        fullLibraryTileRadius=10,
        GAME_CARD_HORIZONTAL={},
        GAME_CARD_ANIMATION=GAME_CARD_ANIMATION,
    )

def test_minimal_tray_contains_game_actions() -> None:
    _application = QApplication.instance() or QApplication([])
    manager = TrayManager.__new__(TrayManager)
    manager.tray_menu = QMenu()
    manager.pause_game_action = QAction("Pause Game", manager.tray_menu)
    manager.stop_game_action = QAction("Stop Game", manager.tray_menu)
    manager.minimal_mode = True
    manager.update_game_actions = MagicMock()

    manager.refresh_tray_menu()

    assert manager.tray_menu.actions() == [
        manager.pause_game_action,
        manager.stop_game_action,
    ]
    manager.update_game_actions.assert_called_once_with()

def test_tray_pauses_game_process_tree(monkeypatch: MonkeyPatch) -> None:
    child = MagicMock(pid=12)
    child.status.return_value = "running"
    parent = MagicMock(pid=11)
    parent.children.return_value = [child]
    manager = TrayManager.__new__(TrayManager)
    manager.main_window = SimpleNamespace(
        game_processes=[SimpleNamespace(pid=11)], target_exe=None,
    )
    manager.update_game_actions = MagicMock()
    monkeypatch.setattr("portprotonqt.tray_manager.psutil.Process", lambda _pid: parent)

    manager.toggle_game_pause()

    child.send_signal.assert_called_once_with(signal.SIGSTOP)
    manager.update_game_actions.assert_called_once_with()

def test_tray_resumes_target_process(monkeypatch: MonkeyPatch) -> None:
    process = MagicMock(pid=21, info={"name": "game.exe"})
    process.status.return_value = psutil.STATUS_STOPPED
    process.children.return_value = []
    manager = TrayManager.__new__(TrayManager)
    manager.main_window = SimpleNamespace(game_processes=[], target_exe="GAME.EXE")
    manager.update_game_actions = MagicMock()
    monkeypatch.setattr(
        "portprotonqt.tray_manager.psutil.process_iter", lambda attrs: [process]
    )

    manager.toggle_game_pause()

    process.send_signal.assert_called_once_with(signal.SIGCONT)
    manager.update_game_actions.assert_called_once_with()

def test_minimal_tray_exits_after_stopping_game(monkeypatch: MonkeyPatch) -> None:
    manager = TrayManager.__new__(TrayManager)
    manager.main_window = SimpleNamespace(stop_running_game=lambda: True)
    manager.minimal_mode = True
    manager.tray_icon = MagicMock()
    manager.update_game_actions = MagicMock()
    quit_app = MagicMock()
    monkeypatch.setattr("portprotonqt.tray_manager.QApplication.quit", quit_app)

    manager.stop_game()

    manager.tray_icon.hide.assert_called_once_with()
    quit_app.assert_called_once_with()

@mark.parametrize(("vertical_layout", "ribbon_visible"), [(False, True), (True, False)])
def test_source_ribbon_visibility(
    monkeypatch: MonkeyPatch,
    vertical_layout: bool,
    ribbon_visible: bool,
) -> None:
    card = MagicMock()
    card.coverLabel = MagicMock()
    card.game_source = "portproton"
    card.ppdb_id = "report-id"
    card.protondb_tier = "Platinum"
    card.anticheat_status = "Supported"
    card.badge_view_mode = "hidden"
    card.vertical_layout = vertical_layout
    card.coverWidget.width.return_value = 300
    card.getAntiCheatText.return_value = "Supported"
    card.parentWidget.return_value = None
    monkeypatch.setattr("portprotonqt.game_card.ui_config.get_economy_mode", lambda: False)

    GameCard.update_badge_visibility(card, "portproton")

    card.portprotonLabel.setVisible.assert_called_with(ribbon_visible)
    card.ppdbLabel.setVisible.assert_called_with(False)
    card.protondbLabel.setVisible.assert_called_with(False)
    card.anticheatLabel.setVisible.assert_called_with(False)

def test_cached_metadata_index_is_reused(tmp_path: Path) -> None:
    cache_file = tmp_path / "games.json"
    cache_file.write_text('[{"normalized_name": "game"}]', encoding="utf-8")
    build_index = MagicMock(return_value={"game": {"normalized_name": "game"}})
    steam_api_module._load_cached_data_and_index.cache_clear()

    first = steam_api_module._get_cached_data_and_index(cache_file, build_index)
    second = steam_api_module._get_cached_data_and_index(cache_file, build_index)

    assert first == second
    build_index.assert_called_once_with([{"normalized_name": "game"}])

def test_cached_metadata_index_is_built_once_concurrently(tmp_path: Path) -> None:
    cache_file = tmp_path / "games.json"
    cache_file.write_text('[{"normalized_name": "game"}]', encoding="utf-8")
    build_barrier = threading.Barrier(5)

    def build_index(data: list) -> dict:
        try:
            build_barrier.wait(timeout=0.05)
        except threading.BrokenBarrierError:
            pass
        return {"game": data[0]}

    build_index_mock = MagicMock(side_effect=build_index)
    steam_api_module._load_cached_data_and_index.cache_clear()

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(
                steam_api_module._get_cached_data_and_index,
                cache_file,
                build_index_mock,
            )
            for _ in range(5)
        ]
        results = [future.result() for future in futures]

    assert all(result == results[0] for result in results)
    build_index_mock.assert_called_once_with([{"normalized_name": "game"}])

TAB_METHODS = {
    AutoInstallMixin: (
        "createAutoInstallTab",
        "_open_autoinstall_card_after_script_download",
        "_setup_autoinstall_search_animation",
        "_wrap_autoinstall_search_focus_event",
        "_wrap_autoinstall_search_resize_event",
        "_center_collapsed_autoinstall_search_icon",
        "_start_autoinstall_load",
        "_refresh_autoinstall_games",
        "on_auto_slider_released",
        "filterAutoInstallGames",
    ),
    LibraryMixin: (
        "_load_empty_library_on_tab_enter",
        "_set_combo_current_key",
        "_create_library_combo",
        "_on_library_sort_changed",
        "_on_library_filter_changed",
        "_on_only_installed_changed",
        "_on_library_badge_view_changed",
        "_toggle_library_controls",
        "_close_library_controls",
        "_create_library_controls_widget",
        "_add_library_action_buttons",
        "_add_library_search",
        "_add_library_refresh_button",
        "_add_library_delete_missing_button",
        "_add_library_controls_button",
        "_setup_library_search_animation",
        "_wrap_search_focus_event",
        "_wrap_search_resize_event",
        "_center_collapsed_search_icon",
        "_add_library_filter_controls",
        "_delay_library_controls_hover_close",
        "_allow_library_controls_hover_close",
        "createSearchWidget",
        "refreshGames",
        "_get_games_without_exe",
        "updateDeleteMissingExeButton",
        "deleteMissingExeCards",
        "quickLaunch",
        "on_search_text_changed",
        "on_search_changed",
        "startSearchDebounce",
        "createInstalledTab",
        "resizeEvent",
        "dragEnterEvent",
        "dropEvent",
        "openAddGameDialog",
        "_sync_game_shortcuts_from_dialog",
    ),
    WineMixin: (
        "createWineTab",
        "save_wine_defaults",
        "launch_generic_tool",
        "_start_wine_process_monitor",
        "_check_wine_process",
        "_on_wine_tool_finished",
        "_on_wine_tool_error",
        "show_proton_manager",
        "clear_prefix",
        "_on_clear_prefix_finished",
        "_on_clear_prefix_error",
        "create_prefix_backup",
        "_perform_backup",
        "load_prefix_backup",
        "_perform_restore",
        "_perform_legacy_restore",
        "_on_backup_finished",
        "_on_restore_finished",
        "delete_prefix",
        "refresh_wine_combo",
        "refresh_prefix_combo",
        "_normalize_prefix_directories",
        "open_winetricks",
    ),
    SettingsMixin: (
        "createPortProtonTab",
        "resetSettings",
        "migrateLegacyShortcuts",
        "clearCache",
        "applySettingsDelayed",
        "_format_game_tuple_playtime",
        "_refresh_loaded_playtime_format",
        "_refresh_current_detail_time",
        "savePortProtonSettings",
        "_apply_gamepad_type_setting",
    ),
    ThemeMixin: (
        "createThemeTab",
        "_refresh_theme_store_visibility",
        "restart_application",
        "restore_state",
    ),
}

THEME_STORE_METHODS = (
    "_create_theme_store_page",
    "_show_theme_store",
    "_load_theme_store",
    "_on_theme_store_slider_released",
    "_set_theme_store_preview_variant",
    "_download_current_store_theme",
)

def test_main_window_inherits_all_tab_mixins() -> None:
    expected_mixins = (
        MainWindowAutoInstallTabMixin,
        MainWindowLibraryTabMixin,
        MainWindowSettingsTabMixin,
        MainWindowThemeTabMixin,
        MainWindowWineTabMixin,
    )

    for mixin in expected_mixins:
        assert issubclass(MainWindow, mixin)

def test_settings_retranslate_existing_interface(monkeypatch: MonkeyPatch) -> None:
    _application = QApplication.instance() or QApplication([])
    label = QLabel("Настройки")
    combo = QComboBox()
    combo.addItem("Системный")
    table = QTableWidget(0, 1)
    table.setHorizontalHeaderItem(0, QTableWidgetItem("Профиль"))
    mixin = MainWindowSettingsTabMixin()
    mixin.steamAccountTitle = QLabel("Аккаунт Steam:")
    mixin.gogAccountTitle = QLabel("Аккаунт GOG:")
    mixin.egsAccountTitle = QLabel("Аккаунт Epic Games:")
    mixin.autoDownloadPPDBTitle = QLabel("Автозагрузка PPDB с linux-gaming.ru")
    mixin.enableThemeStoreTitle = QLabel("Магазин тем linux-gaming.ru")
    mixin.findChildren = MagicMock(return_value=[label, combo, table])
    translations = {
        "Настройки": "Settings",
        "Системный": "System",
        "Профиль": "Profile",
        "Account": "Account",
        "Auto download PPDB from": "Auto download PPDB from",
        "Enable Theme Store from %(source)s (%(warning)s)": (
            "Enable Theme Store from %(source)s (%(warning)s)"
        ),
        "third-party themes may be unsafe": "third-party themes may be unsafe",
    }
    monkeypatch.setattr(
        "portprotonqt.tabs.settings_tab.retranslate",
        lambda text: translations.get(text, text),
    )
    monkeypatch.setattr(
        "portprotonqt.tabs.settings_tab._",
        lambda text: translations.get(text, text),
    )

    mixin._retranslate_interface()

    assert label.text() == "Settings"
    assert combo.itemText(0) == "System"
    header_item = table.horizontalHeaderItem(0)
    assert header_item is not None
    assert header_item.text() == "Profile"
    assert mixin.steamAccountTitle.text() == "Account Steam:"
    assert mixin.gogAccountTitle.text() == "Account GOG:"
    assert mixin.egsAccountTitle.text() == "Account Epic Games:"
    assert mixin.autoDownloadPPDBTitle.text() == (
        "Auto download PPDB from linux-gaming.ru"
    )
    assert mixin.enableThemeStoreTitle.text() == (
        "Enable Theme Store from linux-gaming.ru "
        "(third-party themes may be unsafe)"
    )

def test_tray_initialization_runs_once(monkeypatch: MonkeyPatch) -> None:
    tray_manager = MagicMock()
    create_tray = MagicMock(return_value=tray_manager)
    window = cast(
        Any,
        SimpleNamespace(tray_manager=None, current_theme_name="standart"),
    )
    monkeypatch.setattr(main_window_module, "TrayManager", create_tray)

    MainWindow._initialize_tray(window, "PortProtonQt")
    MainWindow._initialize_tray(window, "PortProtonQt")

    create_tray.assert_called_once_with(window, "PortProtonQt", "standart")
    assert window.tray_manager is tray_manager


def test_tray_theme_switch_applies_theme_without_restart(
    monkeypatch: MonkeyPatch,
) -> None:
    manager = TrayManager.__new__(TrayManager)
    manager.main_window = SimpleNamespace(_apply_theme_live=MagicMock())
    restart = MagicMock()
    monkeypatch.setattr("portprotonqt.tray_manager.restart_application_process", restart)

    manager.switch_theme("console")

    manager.main_window._apply_theme_live.assert_called_once_with("console")
    restart.assert_not_called()


def test_live_theme_style_replacement_does_not_rewrite_new_paths() -> None:
    mixin = MainWindowThemeTabMixin()
    style = "url(/themes/standart/images/check.svg)"
    replacements = [
        ("/themes/standart/", "/themes/standart-light/"),
        ("standart", "standart-light"),
    ]

    result = mixin._theme_style_replacer(replacements, {style})(style)

    assert result == "url(/themes/standart-light/images/check.svg)"

def test_live_theme_style_replacement_handles_exact_styles() -> None:
    mixin = MainWindowThemeTabMixin()
    style = "QWidget { color: #ffffff; }"
    replacements = [(style, "QWidget { color: #000000; }")]

    result = mixin._theme_style_replacer(replacements, {style})(style)

    assert result == "QWidget { color: #000000; }"

def test_live_theme_style_replacements_skip_ambiguous_values() -> None:
    mixin = MainWindowThemeTabMixin()
    old_theme = SimpleNamespace(FIRST_STYLE="same", SECOND_STYLE="same")
    new_theme = SimpleNamespace(FIRST_STYLE="first", SECOND_STYLE="second")

    replacements = mixin._theme_style_replacements(old_theme, new_theme)

    assert replacements == []

def test_live_theme_joins_named_composite_styles() -> None:
    mixin = MainWindowThemeTabMixin()
    widget = SimpleNamespace(
        property=lambda name: (
            ("OTHER_PAGES_WIDGET_STYLE", "THEME_TAB_FOCUS_STYLE")
            if name == "theme_style_names"
            else None
        )
    )
    theme = SimpleNamespace(
        OTHER_PAGES_WIDGET_STYLE="page",
        THEME_TAB_FOCUS_STYLE="focus",
    )

    style = mixin._get_named_theme_style(cast(Any, widget), theme)

    assert style == "pagefocus"


def test_live_theme_refreshes_auto_size_button_padding() -> None:
    _application = QApplication.instance() or QApplication([])
    button = AutoSizeButton("Test", padding=None)

    button.refresh_theme(SimpleNamespace(autoSizeButtonPadding=(10, 20)))

    assert button._pad_top == 10
    assert button._pad_bottom == 10
    assert button._pad_left == 20
    assert button._pad_right == 20


def test_live_theme_rebuilds_library_when_layout_mode_changes() -> None:
    mixin = cast(Any, MainWindowThemeTabMixin())
    layout = object()
    manager = SimpleNamespace(
        gamesListLayout=layout,
        games=[("Game",)],
        rebuild_library_layout=MagicMock(),
    )
    mixin.game_library_manager = manager

    mixin._refresh_theme_library_layout(
        SimpleNamespace(LIBRARY_LAYOUT_MODE="list"),
        SimpleNamespace(LIBRARY_LAYOUT_MODE="grid"),
    )

    manager.rebuild_library_layout.assert_called_once_with("grid")


def test_library_background_is_removed_when_live_theme_has_no_config(
    monkeypatch: MonkeyPatch,
) -> None:
    _application = QApplication.instance() or QApplication([])
    manager: Any = GameLibraryManager.__new__(GameLibraryManager)
    manager.full_library_open = False
    manager.libraryBackgroundLabel = QLabel()
    manager.theme = SimpleNamespace()
    cover_label = QLabel()
    cover_label.setPixmap(QPixmap(1, 1))
    remove_background = MagicMock()
    monkeypatch.setattr(
        "portprotonqt.game_library_manager.remove_cover_background",
        remove_background,
    )

    manager._update_library_background(SimpleNamespace(coverLabel=cover_label))

    remove_background.assert_called_once_with(manager.libraryBackgroundLabel)


def test_library_creates_background_layer_for_live_theme_switch() -> None:
    _application = QApplication.instance() or QApplication([])
    theme = SimpleNamespace(
        LIBRARY_LAYOUT_MODE="grid",
        LIBRARY_WIDGET_STYLE="",
        LIST_WIDGET_STYLE="",
        SCROLL_STYLE="",
        SLIDER_SIZE_STYLE="",
        TRANSPARENT_BACKGROUND_STYLE="",
    )
    main_window: Any = SimpleNamespace(
        createSearchWidget=lambda: (QWidget(), QLabel()),
        on_slider_released=lambda: None,
        _register_gamepad_tooltip=lambda _widget, _text: None,
    )
    manager = GameLibraryManager(main_window, theme, None)

    manager.create_games_library_widget()

    assert manager.libraryBackgroundLabel is not None
    assert isinstance(manager.gamesLibraryWidget.layout(), QGridLayout)


def test_auto_hide_scroll_area_tracks_horizontal_overflow() -> None:
    _application = QApplication.instance() or QApplication([])
    theme = SimpleNamespace(TRANSPARENT_BACKGROUND_STYLE="", SCROLL_STYLE="")
    scroll_area = AutoHideScrollArea(theme=theme)
    scroll_area.resize(100, 100)
    content = QWidget()
    content_layout = QVBoxLayout(content)
    child = QWidget()
    child.setFixedSize(200, 50)
    content_layout.addWidget(child)
    scroll_area.setWidget(content)
    scroll_area.show()
    QApplication.processEvents()

    scroll_area._update_scroll_needed()
    scroll_area._on_horizontal_scroll(1)

    assert scroll_area._h_scroll_needed is True
    assert scroll_area._h_is_visible is True
    assert scroll_area._h_hide_timer.isActive()

def test_vertical_library_uses_column_layout() -> None:
    _application = QApplication.instance() or QApplication([])
    manager: Any = GameLibraryManager.__new__(GameLibraryManager)
    manager.gamesListWidget = QWidget()
    manager.gamesListLayout = QGridLayout(manager.gamesListWidget)
    manager._incremental_add_timer = None
    manager._incremental_add_queue = []
    manager._incremental_new_games_map = {}
    manager._incremental_search_text = ""
    manager.game_card_cache = {}
    manager.pending_images = {}
    manager.theme = SimpleNamespace(
        LIBRARY_LAYOUT_MODE="vertical",
        GAME_CARD_VERTICAL={"layout_margins": (1, 2, 3, 4), "layout_spacing": 5},
    )
    manager.fullLibraryTile = None
    manager.full_library_open = False
    manager.libraryBackgroundLabel = None
    manager.libraryHeaderWidget = None
    manager.libraryContentLayout = None
    manager.gamesScrollArea = None
    manager.sizeSlider = None
    manager.games = []
    manager.set_games = MagicMock()

    manager.rebuild_library_layout("vertical")

    assert isinstance(manager.gamesListLayout, QVBoxLayout)
    assert manager.gamesListLayout.contentsMargins().left() == 1
    assert manager.gamesListLayout.spacing() == 5

def test_full_library_tile_accepts_async_cover_result() -> None:
    application = QApplication.instance() or QApplication([])
    assert application is not None
    manager: Any = GameLibraryManager.__new__(GameLibraryManager)
    theme = _tile_theme()
    tile = FullLibraryTile(theme)
    manager.fullLibraryTile = tile
    manager._full_library_tile_pixmaps = {}
    manager.theme = theme
    cover = QPixmap(60, 90)
    cover.fill(Qt.GlobalColor.red)

    manager._set_full_library_tile_cover(tile, 0, cover)

    assert not tile.tile_pixmap.isNull()

def test_full_library_tile_uses_card_scale() -> None:
    application = QApplication.instance() or QApplication([])
    assert application is not None
    theme = _tile_theme()
    tile = FullLibraryTile(theme)

    tile.setScale(1.1)

    assert tile.size().toTuple() == (198, 198)

def test_close_full_library_restores_top_layout() -> None:
    manager: Any = GameLibraryManager.__new__(GameLibraryManager)
    manager.full_library_open = True
    manager.rebuild_library_layout = MagicMock()

    assert manager.close_full_library()
    manager.rebuild_library_layout.assert_called_once_with("horizontal_top")

def test_live_theme_reopens_visible_detail_page() -> None:
    mixin = cast(Any, MainWindowThemeTabMixin())
    manager = SimpleNamespace(
        _can_rebuild_after_resize=lambda: True,
        _reopen_current_detail_page=MagicMock(),
    )
    mixin.detail_page_manager = manager

    mixin._refresh_open_detail_page()

    manager._reopen_current_detail_page.assert_called_once_with()

def test_qt_color_scheme_change_applies_confirmed_system_theme(
    monkeypatch: MonkeyPatch,
) -> None:
    mixin = cast(Any, MainWindowThemeTabMixin())
    mixin.system_theme_watcher = SimpleNamespace(_last_light=False)
    mixin._on_system_theme_detected = MagicMock()
    monkeypatch.setattr(
        "portprotonqt.tabs.theme_tab.ui_config.get_theme_variant", lambda: "auto"
    )
    monkeypatch.setattr(
        "portprotonqt.tabs.theme_tab._is_system_light_theme", lambda: True
    )

    mixin._on_qt_color_scheme_changed(Qt.ColorScheme.Light)

    assert mixin.system_theme_watcher._last_light is True
    mixin._on_system_theme_detected.assert_called_once_with(True)

def test_qt_color_scheme_change_ignores_theme_repolish(
    monkeypatch: MonkeyPatch,
) -> None:
    mixin = cast(Any, MainWindowThemeTabMixin())
    mixin._theme_change_in_progress = True
    mixin._on_system_theme_detected = MagicMock()
    monkeypatch.setattr(
        "portprotonqt.tabs.theme_tab.ui_config.get_theme_variant", lambda: "auto"
    )

    mixin._on_qt_color_scheme_changed(Qt.ColorScheme.Light)

    mixin._on_system_theme_detected.assert_not_called()

def test_deferred_theme_update_applies_current_generation(
    monkeypatch: MonkeyPatch,
) -> None:
    mixin = cast(Any, MainWindowThemeTabMixin())
    mixin._theme_update_generation = 2
    widget = MagicMock()
    widget.styleSheet.return_value = "old"
    refresh_theme = MagicMock()
    theme = object()
    monkeypatch.setattr("portprotonqt.tabs.theme_tab.isValid", lambda _widget: True)

    mixin._apply_deferred_theme_updates(
        [(widget, "new", refresh_theme)], theme, 2
    )

    refresh_theme.assert_called_once_with(theme)
    widget.setStyleSheet.assert_called_once_with("new")

def test_deferred_theme_update_ignores_old_generation() -> None:
    mixin = cast(Any, MainWindowThemeTabMixin())
    mixin._theme_update_generation = 2
    widget = MagicMock()

    mixin._apply_deferred_theme_updates([(widget, "new", None)], object(), 1)

    widget.setStyleSheet.assert_not_called()

def test_deferred_theme_update_skips_deleted_widget(
    monkeypatch: MonkeyPatch,
) -> None:
    mixin = cast(Any, MainWindowThemeTabMixin())
    mixin._theme_update_generation = 1
    widget = MagicMock()
    refresh_theme = MagicMock()
    monkeypatch.setattr("portprotonqt.tabs.theme_tab.isValid", lambda _widget: False)

    mixin._apply_deferred_theme_updates(
        [(widget, "new", refresh_theme)], object(), 1
    )

    refresh_theme.assert_not_called()
    widget.setStyleSheet.assert_not_called()

def test_game_card_animation_refresh_supports_all_modes() -> None:
    config = {
        "default_border_width": 1,
        "hover_border_width": 4,
        "focus_border_width": 6,
        "pulse_min_border_width": 3,
        "pulse_max_border_width": 5,
        "thickness_anim_duration": 10,
        "pulse_anim_duration": 10,
        "gradient_anim_duration": 10,
        "gradient_start_angle": 360,
        "gradient_end_angle": 0,
        "default_scale": 1.0,
        "hover_scale": 1.1,
        "focus_scale": 1.05,
        "scale_anim_duration": 10,
    }
    card = cast(Any, QObject())
    card._hovered = True
    card._focused = False
    card.update = MagicMock()
    animations = GameCardAnimations(card, SimpleNamespace(GAME_CARD_ANIMATION=config))

    for animation_type in ("gradient", "glow", "fill", "stripe", "scale", "scale_fill"):
        theme = SimpleNamespace(
            GAME_CARD_ANIMATION={**config, "card_animation_type": animation_type}
        )
        animations.refresh_theme(theme)
        expected_scale = 1.1 if animation_type in {"scale", "scale_fill"} else 1.0
        assert card._scale == expected_scale
        assert animations.theme is theme

    animations.cleanup()

def test_game_card_animation_type_uses_layout_override() -> None:
    card = SimpleNamespace(
        card_layout_cfg={
            "card_animation_type": "scale",
            "hover_scale": 1.055,
            "hover_border_width": 6,
            "fill_alpha": 40,
        }
    )
    theme = SimpleNamespace(
        GAME_CARD_ANIMATION={
            "card_animation_type": "gradient",
            "hover_scale": 1.1,
            "hover_border_width": 8,
            "fill_alpha": 90,
            "focus_scale": 1.05,
        }
    )

    animations = GameCardAnimations(card, theme)

    assert animations._animation_type() == "scale"
    assert animations._config_value("hover_scale") == 1.055
    assert animations._config_value("hover_border_width") == 6
    assert animations._optional_config_value("fill_alpha", 0) == 40
    assert animations._config_value("focus_scale") == 1.05

def test_game_card_click_uses_select_callback() -> None:
    select_callback = MagicMock()
    card = SimpleNamespace(
        name="Game",
        description="Description",
        cover_path="cover.png",
        appid="1",
        controller_support="full",
        exec_line="game.exe",
        last_launch="today",
        formatted_playtime="1 hour",
        playtime_seconds=3600,
        protondb_tier="gold",
        game_source="steam",
        anticheat_status="supported",
        anticheat_slug="anti-cheat",
        ppdb_id="report",
        ppdb_rating="platinum",
        protondb_appid="1",
        autoinstall_exe_name="",
        select_callback=select_callback,
        _get_missing_executable_path=lambda: "",
    )

    GameCard.click(cast(Any, card))

    select_callback.assert_called_once()
    assert select_callback.call_args.args[0]["name"] == "Game"


def test_missing_game_card_click_offers_repair() -> None:
    card = SimpleNamespace(
        _get_missing_executable_path=lambda: "/missing/game.exe",
        context_menu_manager=MagicMock(),
        select_callback=MagicMock(),
    )

    GameCard.click(cast(Any, card))

    card.context_menu_manager.handle_missing_executable.assert_called_once_with(card)
    card.select_callback.assert_not_called()

def test_game_card_theme_refresh_updates_hidden_badge_styles() -> None:
    card = MagicMock()
    card.list_layout = False
    card.protondb_tier = "gold"
    card.ppdb_id = "report"
    card.ppdb_rating = "Platinum"
    card.anticheat_status = "Supported"
    card.getAntiCheatText.return_value = "Supported"
    card.current_theme_name = "new-theme"
    animation_config = {"card_animation_type": "gradient"}
    card.theme = SimpleNamespace(
        GAME_CARD_ANIMATION=animation_config,
        COMPACT_CARD={},
        favoriteLabelSize=(24, 24),
        favoriteLabelIconSize=18,
    )
    card.card_layout_cfg = {}
    theme = SimpleNamespace(
        GAME_CARD_GRID={},
        GAME_CARD_ANIMATION=animation_config,
        COMPACT_CARD={},
        favoriteLabelSize=(24, 24),
        favoriteLabelIconSize=18,
        shadow_blur_radius=10,
        color_shadow_card="#000000",
        shadow_offset=(0, 1),
        GAME_CARD_WINDOW_STYLE="card",
        COVER_LABEL_STYLE="cover",
        GAME_CARD_NAME_LABEL_STYLE="name",
        STEAM_BADGE_STYLE="steam",
        missing_exe_cover_opacity=0.5,
        get_protondb_badge_style=lambda _tier: "protondb",
        get_ppdb_badge_style=lambda _rating: "ppdb",
        get_anticheat_badge_style=lambda _status: "anticheat",
        get_source_corner_config=lambda: {},
    )

    GameCard.refresh_theme(card, theme)

    card.protondbLabel.setStyleSheet.assert_called_once_with("protondb")
    card.ppdbLabel.setStyleSheet.assert_called_once_with("ppdb")
    card.anticheatLabel.setStyleSheet.assert_called_once_with("anticheat")
    card.animations.refresh_theme.assert_not_called()
    card.update_scale.assert_not_called()

def test_source_corner_does_not_shadow_generic_theme_refresh() -> None:
    assert hasattr(SourceCorner, "refresh_source_theme")
    assert not hasattr(SourceCorner, "refresh_theme")

def test_source_corner_refresh_updates_ribbon_colors() -> None:
    _application = QApplication.instance() or QApplication([])
    corner = SourceCorner(
        config={"ribbon_color": "#111111", "ribbon_fold_color": "#222222"}
    )

    corner.refresh_source_theme(
        {"ribbon_color": "#eeeeee", "ribbon_fold_color": "#dddddd"}, None
    )

    assert corner._color.name() == "#eeeeee"
    assert corner._fold_color.name() == "#dddddd"

def test_library_source_filter_stays_top_aligned_without_checkbox(
    monkeypatch: MonkeyPatch,
) -> None:
    _application = QApplication.instance() or QApplication([])
    window = MainWindow.__new__(MainWindow)
    test_window = cast(Any, window)
    test_window.theme = SimpleNamespace(CHECKBOX_STYLE="")
    test_window._create_library_combo = lambda labels, _tooltip: QComboBox()
    test_window._set_combo_current_key = lambda *_args: None
    test_window._register_gamepad_tooltip = lambda *_args: None
    monkeypatch.setattr(game_config, "get_sort_method", lambda: "last_launch")
    monkeypatch.setattr(game_config, "get_display_filter", lambda: "gog")
    monkeypatch.setattr(game_config, "get_only_installed", lambda: False)
    monkeypatch.setattr(library_tab_module.ui_config, "get_badge_view_mode", lambda: "detailed")
    monkeypatch.setattr(library_tab_module.ui_config, "get_economy_mode", lambda: False)
    controls_widget = QWidget()
    controls_layout = QGridLayout(controls_widget)

    LibraryMixin._add_library_filter_controls(window, controls_layout)

    display_filter_item = controls_layout.itemAtPosition(0, 1)
    assert display_filter_item is not None
    assert display_filter_item.widget() is test_window.gamesDisplayCombo
    controls_widget.show()
    _application.processEvents()
    expanded_height = controls_widget.sizeHint().height()
    test_window.onlyInstalledCheckBox.hide()
    position_target = SimpleNamespace(
        libraryControlsWidget=controls_widget,
        libraryControlsButton=SimpleNamespace(
            height=lambda: 30,
            width=lambda: 30,
            mapTo=lambda _parent, point: point,
        ),
        width=lambda: 1000,
    )

    LibraryMixin._position_library_controls_widget(cast(Any, position_target))

    assert controls_widget.height() < expanded_height

def test_downloads_tab_is_hidden_without_downloads() -> None:
    tab_button = SimpleNamespace(setVisible=MagicMock())
    window = SimpleNamespace(
        downloadActiveCard=SimpleNamespace(isHidden=lambda: True),
        downloadQueuedTable=SimpleNamespace(rowCount=lambda: 0),
        downloadCompletedTable=SimpleNamespace(rowCount=lambda: 0),
        tabButtons={6: tab_button},
        stackedWidget=SimpleNamespace(currentIndex=lambda: 0),
        switchTab=MagicMock(),
    )

    GOGMixin._update_downloads_tab_visibility(cast(Any, window))

    tab_button.setVisible.assert_called_once_with(False)

def test_downloads_tab_is_visible_with_completed_download() -> None:
    tab_button = SimpleNamespace(setVisible=MagicMock())
    window = SimpleNamespace(
        downloadActiveCard=SimpleNamespace(isHidden=lambda: True),
        downloadQueuedTable=SimpleNamespace(rowCount=lambda: 0),
        downloadCompletedTable=SimpleNamespace(rowCount=lambda: 1),
        tabButtons={6: tab_button},
        stackedWidget=SimpleNamespace(currentIndex=lambda: 0),
        switchTab=MagicMock(),
    )

    GOGMixin._update_downloads_tab_visibility(cast(Any, window))

    tab_button.setVisible.assert_called_once_with(True)

def test_library_controls_animation_ignores_game_card_scale_duration() -> None:
    theme = SimpleNamespace(GAME_CARD_ANIMATION={"scale_anim_duration": 10})

    assert _animation_duration(theme, 150) == 150

def test_library_controls_animation_uses_own_duration() -> None:
    theme = SimpleNamespace(
        GAME_CARD_ANIMATION={
            "library_controls_anim_duration": 220,
            "scale_anim_duration": 10,
        },
    )

    assert _animation_duration(theme, 150) == 220

def test_switch_tab_closes_library_controls_when_leaving_library() -> None:
    class Button:
        def __init__(self) -> None:
            self.checked = False

        def isVisible(self) -> bool:
            return True

        def setChecked(self, checked: bool) -> None:
            self.checked = checked

    class Stack:
        def __init__(self) -> None:
            self.index = 0

        def setCurrentIndex(self, index: int) -> None:
            self.index = index

        def currentIndex(self) -> int:
            return self.index

    window = SimpleNamespace(
        tabButtons={0: Button(), 1: Button()},
        stackedWidget=Stack(),
        auto_install_tab_index=-1,
        system_tab_index=-1,
        library_controls_closed=False,
    )
    window._close_library_controls = lambda: setattr(
        window,
        "library_controls_closed",
        True,
    )

    MainWindow.switchTab(cast(Any, window), 1)

    assert window.library_controls_closed is True

def test_library_search_keeps_expanded_for_active_virtual_keyboard(monkeypatch: MonkeyPatch) -> None:
    class Window(LibraryMixin):
        pass

    search_edit = object()
    animation = SimpleNamespace(expanded=False, collapsed=False)
    keyboard = SimpleNamespace(
        current_input_widget=search_edit,
        isVisible=lambda: True,
    )
    window: Any = Window()
    window.searchEdit = search_edit
    window.searchAnimation = animation
    window.keyboard = keyboard
    window._center_collapsed_search_icon = lambda: None
    animation.expand = lambda: setattr(animation, "expanded", True)
    animation.collapse = lambda: setattr(animation, "collapsed", True)
    monkeypatch.setattr(library_tab_module.QTimer, "singleShot", lambda _ms, callback: callback())

    handler = window._wrap_search_focus_event(lambda _event: None, False)
    handler(object())

    assert animation.collapsed is False

def test_autoinstall_search_keeps_expanded_for_active_virtual_keyboard(monkeypatch: MonkeyPatch) -> None:
    class Window(AutoInstallMixin):
        pass

    search_edit = object()
    animation = SimpleNamespace(expanded=False, collapsed=False)
    keyboard = SimpleNamespace(
        current_input_widget=search_edit,
        isVisible=lambda: True,
    )
    window: Any = Window()
    window.autoInstallSearchLineEdit = search_edit
    window.autoInstallSearchAnimation = animation
    window.keyboard = keyboard
    window._center_collapsed_autoinstall_search_icon = lambda: None
    animation.expand = lambda: setattr(animation, "expanded", True)
    animation.collapse = lambda: setattr(animation, "collapsed", True)
    monkeypatch.setattr(autoinstall_tab_module.QTimer, "singleShot", lambda _ms, callback: callback())

    handler = window._wrap_autoinstall_search_focus_event(lambda _event: None, False)
    handler(object())

    assert animation.collapsed is False

def test_autoinstall_search_uses_card_names() -> None:
    class Window(AutoInstallMixin):
        pass

    class FakeSearchEdit:
        def __init__(self, text: str) -> None:
            self._text = text

        def text(self) -> str:
            return self._text

    class FakeCard:
        def __init__(self, name: str, description: str) -> None:
            self.name = name
            self.description = description
            self.visible = False

        def setVisible(self, visible: bool) -> None:
            self.visible = visible

    window: Any = Window()
    target_card = FakeCard("VK Play", "Launcher for the VK Play game library.")
    other_card = FakeCard("Another Game", "Different installer.")
    window.allAutoInstallCards = [target_card, other_card]
    window.autoInstallSearchLineEdit = FakeSearchEdit("vk")
    window.autoInstallContainerLayout = SimpleNamespace(invalidate=lambda: None)
    window.autoInstallContainer = SimpleNamespace(updateGeometry=lambda: None)
    window.autoInstallScrollArea = SimpleNamespace(updateGeometry=lambda: None)

    window.filterAutoInstallGames()

    assert target_card.visible is True
    assert other_card.visible is False

def test_tab_methods_resolve_from_expected_modules() -> None:
    for mixin, method_names in TAB_METHODS.items():
        for method_name in method_names:
            assert getattr(MainWindow, method_name) is getattr(mixin, method_name)
            assert method_name not in MainWindow.__dict__

def test_theme_store_methods_resolve_from_store_mixin() -> None:
    assert issubclass(ThemeMixin, ThemeStoreMixin)
    for method_name in THEME_STORE_METHODS:
        assert getattr(MainWindow, method_name) is getattr(ThemeStoreMixin, method_name)
        assert method_name not in ThemeMixin.__dict__


def test_custom_theme_file_change_reloads_active_theme() -> None:
    manager = MagicMock()
    manager.is_custom_theme.return_value = True
    window = SimpleNamespace(
        current_theme_name="console",
        theme_manager=manager,
        _apply_theme_live=MagicMock(),
        _watch_active_theme_files=MagicMock(),
    )

    ThemeMixin._reload_active_custom_theme(cast(Any, window))

    manager.invalidate_theme.assert_called_once_with("console")
    window._apply_theme_live.assert_called_once_with("console")
    window._watch_active_theme_files.assert_called_once_with()

def test_tabs_package_exports_tab_mixins() -> None:
    import portprotonqt.tabs as tabs

    for mixin in TAB_METHODS:
        assert getattr(tabs, mixin.__name__) is mixin

def test_autoinstall_script_name_supports_spaced_paths(tmp_path: Path) -> None:
    script_path = tmp_path / "Game Installer.ppai"
    script_path.touch()
    manager = DetailPageManager.__new__(DetailPageManager)

    script_name = manager._extract_script_name(f"autoinstall:{shlex.quote(str(script_path))}")

    assert script_name == str(script_path)

def test_open_local_autoinstall_card_uses_autoinstall_page(tmp_path: Path) -> None:
    script_path = tmp_path / "Game Installer.ppai"
    script_path.touch()
    opened = []

    class FakePortProtonAPI:
        def read_local_autoinstall_metadata(self, path: str) -> dict[str, str]:
            assert path == str(script_path)
            return {"name": "Game", "description": "Description"}

    class FakeThemeManager:
        def get_icon(self, *args: Any, **kwargs: Any) -> str:
            return ""

    class FakeDetailPageManager:
        def openAutoInstallDetailPage(self, game_data: dict, return_tab_index: int = 1) -> None:
            opened.append((game_data, return_tab_index))

    window: Any = MainWindow.__new__(MainWindow)
    window.portproton_api = FakePortProtonAPI()
    window.theme_manager = FakeThemeManager()
    window.detail_page_manager = FakeDetailPageManager()

    window.open_local_autoinstall_card(str(script_path))

    game_data, return_tab_index = opened[0]
    assert game_data["name"] == "Game"
    assert game_data["exec_line"] == f"autoinstall:{shlex.quote(str(script_path))}"
    assert return_tab_index == 0

def test_open_game_detail_starts_pending_log(tmp_path: Path) -> None:
    exe_path = tmp_path / "Game.exe"
    exe_path.touch()
    started = []

    class FakeDetailPageManager:
        _debug_log_button = object()

        def openGameDetailPage(self, _game_data: dict) -> None:
            return

        def _start_debug_log(self, path: str, button: object) -> None:
            started.append((path, button))

    class FakeStackedWidget:
        def currentIndex(self) -> int:
            return 0

        def currentWidget(self) -> None:
            return None

    window: Any = MainWindow.__new__(MainWindow)
    window.detail_page_manager = FakeDetailPageManager()
    window.stackedWidget = FakeStackedWidget()
    window.currentDetailPage = None
    window._pending_log_exe = str(exe_path)

    window.openGameDetailPage({"name": "Game", "exec_line": str(exe_path)})

    assert started == [(str(exe_path), window.detail_page_manager._debug_log_button)]
    assert window._pending_log_exe is None

def test_launch_exe_skips_library_load_for_ppai() -> None:
    window: Any = MainWindow.__new__(MainWindow)
    window._loading_games = False
    window.launch_exe = "/tmp/Game Installer.ppai"

    window.loadGames()

    assert window._loading_games is False

def test_meson_installs_tab_modules() -> None:
    meson_build = Path("portprotonqt/meson.build").read_text(encoding="utf-8")
    expected_files = (
        "tabs/autoinstall_tab.py",
        "tabs/library_tab.py",
        "tabs/settings_tab.py",
        "tabs/theme_store.py",
        "tabs/theme_store_workers.py",
        "tabs/theme_tab.py",
        "tabs/wine_tab.py",
    )

    for file_name in expected_files:
        assert file_name in meson_build

class FakeComboBox:
    def __init__(self, items: list[tuple[str, object]], current_index: int = 0) -> None:
        self.items = items
        self.current_index = current_index

    def findData(self, value: object) -> int:
        return next(
            (index for index, item in enumerate(self.items) if item[1] == value),
            -1,
        )

    def addItem(self, text: str, data: object) -> None:
        self.items.append((text, data))

    def currentIndex(self) -> int:
        return self.current_index

    def setCurrentIndex(self, index: int) -> None:
        self.current_index = index

    def removeItem(self, index: int) -> None:
        self.items.pop(index)

class FakeInputManager:
    def __init__(self) -> None:
        self.suspended = False

    def suspend_gamepad_polling(self) -> None:
        self.suspended = True

    def resume_gamepad_polling(self) -> None:
        self.suspended = False

class FakeButton:
    def __init__(self) -> None:
        self.text = ""
        self.icon = None

    def setText(self, text: str) -> None:
        self.text = text

    def setIcon(self, icon: object) -> None:
        self.icon = icon

class FakeThemeManager:
    def get_icon(self, _name: str, as_path: bool = False) -> str:
        return "icon.svg"

class FakeTimer:
    def __init__(self, _parent: object) -> None:
        self.interval = 0

    @property
    def timeout(self) -> "FakeTimer":
        return self

    def connect(self, _callback: object) -> None:
        pass

    def start(self, interval: int) -> None:
        self.interval = interval

class FakeSignal:
    def __init__(self) -> None:
        self._callbacks: list[Any] = []

    def connect(self, callback: Any) -> None:
        self._callbacks.append(callback)

    def emit(self) -> None:
        for callback in self._callbacks:
            callback()

class FakeWorker:
    def __init__(self) -> None:
        self.finished = FakeSignal()

class FakeDetailPageManager:
    def __init__(self) -> None:
        self.opened_data: dict | None = None

    def openAutoInstallDetailPage(self, game_data: dict) -> None:
        self.opened_data = dict(game_data)

def test_stop_running_game_analyzes_before_stop_command_failure(
    monkeypatch: MonkeyPatch,
) -> None:
    window: Any = MainWindow.__new__(MainWindow)
    events = []
    window.current_running_button = None
    window.game_processes = [MagicMock()]
    window.checkProcessTimer = None
    monkeypatch.setattr(window, "_analyze_short_launch", lambda: events.append("analyze"))
    monkeypatch.setattr(window, "_terminate_game_processes", lambda: events.append("terminate"))
    monkeypatch.setattr(
        window, "_run_portproton_stop_command",
        lambda: events.append("portproton-stop") or False,
    )
    monkeypatch.setattr(window, "resetPlayButton", lambda: events.append("reset"))

    assert window.stop_running_game() is False
    assert events == ["analyze", "terminate", "portproton-stop", "reset"]
    assert window.game_processes == []

def test_terminate_game_processes_kills_launcher(monkeypatch: MonkeyPatch) -> None:
    process = MagicMock(pid=1234)
    process.poll.return_value = None
    window: Any = MainWindow.__new__(MainWindow)
    window.game_processes = [process]
    kill_group = MagicMock()
    monkeypatch.setattr("portprotonqt.main_window.os.getpgid", lambda _pid: 4321)
    monkeypatch.setattr("portprotonqt.main_window.os.killpg", kill_group)

    window._terminate_game_processes()

    kill_group.assert_called_once_with(4321, main_window_module.signal.SIGTERM)
    process.kill.assert_called_once_with()

def test_dxvk_incompatibility_reports_after_manual_stop(
    monkeypatch: MonkeyPatch,
) -> None:
    window: Any = MainWindow.__new__(MainWindow)
    reports = []
    launch = SimpleNamespace(executable="/games/game.exe", duration=60.0)
    window.portproton_location = "/portproton"
    window.compatibility_report_ready = SimpleNamespace(emit=reports.append)
    monkeypatch.setattr(
        "portprotonqt.main_window.has_dxvk_vulkan_incompatibility",
        lambda _path: True,
    )
    monkeypatch.setattr(
        "portprotonqt.main_window.analyze_launch",
        lambda _launch, _path: "forced report",
    )

    window._build_compatibility_report(launch, stopped_by_user=True)

    assert reports == ["forced report"]

def test_disabled_crash_reports_skip_launch_analysis(
    monkeypatch: MonkeyPatch,
) -> None:
    window: Any = MainWindow.__new__(MainWindow)
    started = []
    monkeypatch.setattr(
        "portprotonqt.main_window.ui_config.get_crash_reports_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "portprotonqt.main_window.Thread",
        lambda **_kwargs: SimpleNamespace(start=lambda: started.append(True)),
    )

    window._analyze_short_launch()

    assert started == []

def test_launch_marker_starts_crash_timer(monkeypatch: MonkeyPatch) -> None:
    window: Any = MainWindow.__new__(MainWindow)
    window.launch_output_queue = Queue()
    window.game_launch_started = False
    window.game_launch_monotonic = None
    window.wine_download_seen = False
    monkeypatch.setattr("portprotonqt.main_window.time.monotonic", lambda: 90.0)

    state = window._parse_process_status_line("PORTPROTONQT_GAME_LAUNCH_STARTED")
    window.launch_output_queue.put(state)
    window._drain_launch_output_progress()

    assert window.game_launch_monotonic == 90.0
    assert window.game_launch_started is True

def test_update_prefix_log_does_not_mark_wine_launch_start() -> None:
    window: Any = MainWindow.__new__(MainWindow)

    state = window._parse_process_status_line("[INFO] Info: Update prefix log:")

    assert state is None

def test_show_compatibility_report_uses_report_dialog(monkeypatch: MonkeyPatch) -> None:
    calls = []
    window: Any = MainWindow.__new__(MainWindow)
    window.theme = object()

    class ReportDialog:
        def __init__(self, parent: object, theme: object, report: str) -> None:
            calls.append((parent, theme, report))

        def exec(self) -> None:
            calls.append("exec")

    monkeypatch.setattr("portprotonqt.main_window.CompatibilityReportDialog", ReportDialog)

    window._show_compatibility_report("report text")

    assert calls == [(window, window.theme, "report text"), "exec"]

def test_refresh_theme_store_visibility_adds_store(monkeypatch: Any) -> None:
    window: Any = MainWindow.__new__(MainWindow)
    window.themesCombo = FakeComboBox([("Standard", None)])
    monkeypatch.setattr(
        "portprotonqt.tabs.theme_tab.ui_config.get_enable_theme_store",
        lambda: True,
    )

    window._refresh_theme_store_visibility()

    assert window.themesCombo.findData(THEME_STORE_ITEM) == 1

def test_refresh_theme_store_visibility_removes_selected_store(monkeypatch: Any) -> None:
    window: Any = MainWindow.__new__(MainWindow)
    window.themesCombo = FakeComboBox(
        [("Standard", None), (THEME_STORE_ITEM, THEME_STORE_ITEM)],
        current_index=1,
    )
    monkeypatch.setattr(
        "portprotonqt.tabs.theme_tab.ui_config.get_enable_theme_store",
        lambda: False,
    )

    window._refresh_theme_store_visibility()

    assert window.themesCombo.findData(THEME_STORE_ITEM) == -1
    assert window.themesCombo.currentIndex() == 0

def test_autoinstall_script_thread_reference_clears_after_thread_finished() -> None:
    class FakePortProtonAPI:
        def __init__(self) -> None:
            self.script_callback: Any = None
            self.script_worker = FakeWorker()
            self.custom_data_worker = FakeWorker()

        def start_autoinstall_script_download(
            self,
            _url: str,
            callback: Any,
        ) -> FakeWorker:
            self.script_callback = callback
            return self.script_worker

        def start_autoinstall_custom_data_write(
            self,
            _path: str,
            _game_data: dict,
        ) -> FakeWorker:
            return self.custom_data_worker

    api = FakePortProtonAPI()
    window: Any = MainWindow.__new__(MainWindow)
    window.portproton_api = api
    window.detail_page_manager = FakeDetailPageManager()
    game_data = {"exec_line": "autoinstall:https://example.org/game.ppai"}

    window._open_autoinstall_card_after_script_download(
        game_data,
        "https://example.org/game.ppai",
    )
    api.script_callback("/tmp/game.ppai")

    assert window.autoInstallScriptLoadThread is api.script_worker
    assert window.detail_page_manager.opened_data == {
        "exec_line": "autoinstall:/tmp/game.ppai",
    }
    assert window.autoInstallCustomDataThread is api.custom_data_worker

    api.script_worker.finished.emit()
    api.custom_data_worker.finished.emit()

    assert window.autoInstallScriptLoadThread is None
    assert window.autoInstallCustomDataThread is None

def test_launch_autoinstall_checks_alt_i586_dependencies() -> None:
    window: Any = MainWindow.__new__(MainWindow)
    window.installing = False
    window._check_alt_i586_dependencies_before_launch = lambda: False

    window.launch_autoinstall("/tmp/game.ppai")

    assert window.installing is False

@mark.parametrize("returncode, expected", [(0, False), (1, True)])
def test_alt_package_check_uses_install_script(
    monkeypatch: MonkeyPatch,
    returncode: int,
    expected: bool,
) -> None:
    process_events = MagicMock()
    monkeypatch.setattr("portprotonqt.main_window.QApplication.processEvents", process_events)
    monkeypatch.setattr("portprotonqt.main_window.time.sleep", lambda _seconds: None)
    run = MagicMock(return_value=SimpleNamespace(returncode=returncode))
    monkeypatch.setattr("portprotonqt.main_window.subprocess.run", run)
    window: Any = MainWindow.__new__(MainWindow)
    window.start_sh = ["/tmp/scripts/start.sh"]

    assert window._has_missing_alt_i586_packages() is expected
    run.assert_called_once_with(
        ["/tmp/scripts/start.sh", "cli", "--alt-i586-dependencies"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    process_events.assert_called()

def test_initial_library_card_focus_does_not_use_navigation_reason() -> None:
    focus_reasons: list[Qt.FocusReason] = []
    card = SimpleNamespace(
        isVisible=lambda: True,
        isEnabled=lambda: True,
        setFocus=lambda reason: focus_reasons.append(reason),
    )
    manager: Any = GameLibraryManager.__new__(GameLibraryManager)
    manager.main_window = SimpleNamespace(
        stackedWidget=SimpleNamespace(currentIndex=lambda: 0),
    )
    manager.gamesListWidget = SimpleNamespace(findChildren=lambda _type: [card])
    manager.gamesScrollArea = None
    manager._focus_first_card_after_update = True

    manager._focus_first_visible_card()

    assert focus_reasons == [Qt.FocusReason.ActiveWindowFocusReason]

def test_launch_dependency_percent_updates_button_before_status() -> None:
    window: Any = MainWindow.__new__(MainWindow)
    button = FakeButton()
    window.current_running_button = button
    window.theme_manager = FakeThemeManager()
    window.launch_output_queue = Queue()
    window.launch_output_queue.put((None, 0.1, False))
    window.wine_download_seen = False
    window.wine_download_percent = 0.0
    window.wine_download_status = "Downloading Wine…"
    window.game_launch_started = False

    assert window._drain_launch_output_progress()
    window._set_running_button_progress()

    assert button.text == "Downloading Wine… 0.1%"

def test_reset_play_button_refreshes_new_portproton_shortcuts() -> None:
    window: Any = MainWindow.__new__(MainWindow)
    reloads = []
    shortcut_refreshes = []
    window.current_running_button = None
    window.game_start_time = None
    window.game_start_exe = None
    window.target_exe = "Game.exe"
    window.wine_download_seen = False
    window.wine_download_percent = 0.0
    window.wine_download_status = ""
    window.game_launch_started = True
    window.game_processes = []
    window._animated_covers_suspended = False
    window.input_manager = FakeInputManager()
    window.loadGames = lambda **kwargs: reloads.append(kwargs)
    window._refresh_portproton_shortcuts = lambda: shortcut_refreshes.append(True)

    window.resetPlayButton()

    assert reloads == []
    assert shortcut_refreshes == [True]
    assert window.target_exe is None

def test_toggle_game_replaces_invalid_launch_output_bytes(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    exe_path = tmp_path / "Game.exe"
    exe_path.write_text("", encoding="utf-8")
    process = object()
    popen_kwargs: dict[str, object] = {}
    launch_events: list[str] = []
    launch_button_states: list[str] = []
    window: Any = MainWindow.__new__(MainWindow)
    window.start_sh = ["portproton"]
    window.game_processes = []
    window.target_exe = None
    window.current_play_button = None
    button = FakeButton()
    window.theme_manager = FakeThemeManager()
    window.input_manager = FakeInputManager()
    window.games = []

    def fake_popen(_command: list[str], **kwargs: object) -> object:
        launch_events.append("popen")
        popen_kwargs.update(kwargs)
        return process

    def check_alt_dependencies() -> bool:
        launch_button_states.append(button.text)
        launch_events.append("dependencies")
        return True

    monkeypatch.setattr("portprotonqt.main_window.subprocess.Popen", fake_popen)
    monkeypatch.setattr(
        "portprotonqt.main_window.SoundManager",
        lambda: SimpleNamespace(play=launch_events.append),
    )
    monkeypatch.setattr("portprotonqt.main_window.QTimer", FakeTimer)
    monkeypatch.setattr("portprotonqt.main_window.save_last_launch", lambda *_args: None)
    monkeypatch.setattr(
        window,
        "_check_alt_i586_dependencies_before_launch",
        check_alt_dependencies,
    )
    monkeypatch.setattr(window, "_check_missing_prefix_before_launch", lambda *_args: None)
    monkeypatch.setattr(window, "_start_launch_output_reader", lambda _process: None)
    monkeypatch.setattr(window, "_update_last_launch_after_start", lambda *_args: None)

    window.toggleGame(str(exe_path), button)

    assert window.game_processes == [process]
    assert popen_kwargs["text"] is True
    assert popen_kwargs["errors"] == "replace"
    assert window.input_manager.suspended
    assert launch_button_states == [""]
    assert launch_events == ["dependencies", "game_launch", "popen"]

def test_steam_launch_plays_game_launch_sound(monkeypatch: MonkeyPatch) -> None:
    launch_events: list[str] = []
    window: Any = MainWindow.__new__(MainWindow)
    monkeypatch.setattr(
        "portprotonqt.main_window.get_steam_launch_commands",
        lambda _appid: [["steam", "-applaunch", "1"]],
    )
    monkeypatch.setattr(
        "portprotonqt.main_window.subprocess.Popen",
        lambda _command: launch_events.append("popen"),
    )
    monkeypatch.setattr(
        "portprotonqt.main_window.SoundManager",
        lambda: SimpleNamespace(play=launch_events.append),
    )

    window._launch_steam_game("steam://rungameid/1")

    assert launch_events == ["popen", "game_launch"]

def test_process_portproton_desktop_calls_callback_without_asset_download(
    tmp_config_dir: Path,
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    exe_path = tmp_path / "Game.exe"
    exe_path.write_text("", encoding="utf-8")
    desktop_path = tmp_path / "Game.desktop"
    desktop_path.write_text(
        "[Desktop Entry]\n"
        "Name=Test Game\n"
        f"Exec=portproton {exe_path}\n"
        "Icon=\n",
        encoding="utf-8",
    )

    window = MainWindow.__new__(MainWindow)
    window.portproton_location = str(tmp_path)
    results: list[tuple | None] = []

    def fake_steam_info(_name: str, _exec_line: str, callback: Any) -> None:
        callback({})

    monkeypatch.setattr(
        "portprotonqt.main_window.generate_thumbnail",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr("portprotonqt.main_window.get_steam_game_info_async", fake_steam_info)
    monkeypatch.setattr("portprotonqt.main_window.get_last_launch", lambda _exe_name: "Never")
    monkeypatch.setattr(
        "portprotonqt.main_window.get_last_launch_timestamp",
        lambda _exe_name: 0,
    )
    monkeypatch.setattr("portprotonqt.main_window.get_playtime_for_exe", lambda *_args: None)
    monkeypatch.setattr("portprotonqt.main_window.ui_config.get_economy_mode", lambda: False)

    window._process_desktop_file_async(str(desktop_path), results.append)

    assert len(results) == 1
    assert results[0] is not None
    assert results[0][0] == "Test Game"
    assert results[0][5] == f"portproton {exe_path}"
    custom_data_path = tmp_config_dir.parent / "data" / "PortProtonQt" / "custom_data"
    assert not custom_data_path.exists()

def test_remove_empty_custom_data_dirs_keeps_non_empty_dirs(tmp_config_dir: Path) -> None:
    custom_data_path = tmp_config_dir.parent / "data" / "PortProtonQt" / "custom_data"
    (custom_data_path / "praest").mkdir(parents=True)
    (custom_data_path / "Akalabeth - World of Doom").mkdir()
    kept_dir = custom_data_path / "Edited Game"
    kept_dir.mkdir()
    (kept_dir / "metadata.txt").write_text("name=Edited Game\n", encoding="utf-8")

    remove_empty_custom_data_dirs(str(custom_data_path))

    assert not (custom_data_path / "praest").exists()
    assert not (custom_data_path / "Akalabeth - World of Doom").exists()
    assert kept_dir.exists()

def test_get_games_without_exe_only_includes_portproton(tmp_path: Path) -> None:
    exe_path = tmp_path / "Game.exe"
    exe_path.write_text("", encoding="utf-8")
    window = MainWindow.__new__(MainWindow)
    test_window = cast(Any, window)
    test_window.game_library_manager = SimpleNamespace(
        games=[
            ("Existing", "", "", "", "", str(exe_path), "", "", "", "", 0, 0, "portproton"),
            (
                "Missing",
                "",
                "",
                "",
                "",
                str(tmp_path / "Missing.exe"),
                "",
                "",
                "",
                "",
                0,
                0,
                "portproton",
            ),
            ("Steam", "", "", "", "", "steam://rungameid/1", "", "", "", "", 0, 0, "steam"),
            ("GOG", "", "", "", "", "gog://install/1", "", "", "", "", 0, 0, "gog"),
        ]
    )

    missing_games = MainWindowLibraryTabMixin._get_games_without_exe(window)

    assert [game[0] for game in missing_games] == ["Missing"]

def test_update_delete_missing_exe_button_visibility(tmp_path: Path) -> None:
    exe_path = tmp_path / "Game.exe"
    exe_path.write_text("", encoding="utf-8")
    window = MainWindow.__new__(MainWindow)
    test_window = cast(Any, window)
    button = SimpleNamespace(visible=None)
    button.setVisible = lambda visible: setattr(button, "visible", visible)
    test_window.deleteMissingExeButton = button
    test_window.game_library_manager = SimpleNamespace(
        games=[
            ("Existing", "", "", "", "", str(exe_path), "", "", "", "", 0, 0, "portproton"),
            ("Steam", "", "", "", "", "steam://rungameid/1", "", "", "", "", 0, 0, "steam"),
        ]
    )

    MainWindowLibraryTabMixin.updateDeleteMissingExeButton(window)
    assert button.visible is False

    test_window.game_library_manager.games.append(
        (
            "Missing",
            "",
            "",
            "",
            "",
            str(tmp_path / "Missing.exe"),
            "",
            "",
            "",
            "",
            0,
            0,
            "portproton",
        )
    )
    MainWindowLibraryTabMixin.updateDeleteMissingExeButton(window)

    assert button.visible is True

def test_system_action_uses_systemctl_with_systemd(monkeypatch: MonkeyPatch) -> None:
    calls: list[tuple[str, list[str]]] = []
    process = SimpleNamespace(startDetached=lambda *args: calls.append(args) or True)
    window = cast(MainWindowSystemTabMixin, SimpleNamespace())
    monkeypatch.setattr(system_tab_module.os.path, "isdir", lambda path: True)
    monkeypatch.setattr(system_tab_module, "QProcess", process)

    MainWindowSystemTabMixin._runSystemAction(window, "reboot")

    assert calls == [("systemctl", ["reboot"])]

def test_system_action_uses_loginctl_with_elogind(monkeypatch: MonkeyPatch) -> None:
    calls: list[tuple[str, list[str]]] = []
    process = SimpleNamespace(startDetached=lambda *args: calls.append(args) or True)
    window = cast(MainWindowSystemTabMixin, SimpleNamespace())
    monkeypatch.setattr(system_tab_module.os.path, "isdir", lambda path: False)
    monkeypatch.setattr(system_tab_module, "QProcess", process)

    MainWindowSystemTabMixin._runSystemAction(window, "suspend")

    assert calls == [("loginctl", ["suspend"])]

@mark.parametrize(
    ("command", "expected"),
    [
        (
            "/path/return script --user player",
            ("/path/return", ["script", "--user", "player"]),
        ),
        (
            '"/usr/bin/scripts/return to desktop" --user player',
            ("/usr/bin/scripts/return to desktop", ["--user", "player"]),
        ),
        (
            'python "/usr/bin/scripts/return to desktop.py" --user player',
            ("python", ["/usr/bin/scripts/return to desktop.py", "--user", "player"]),
        ),
    ],
)
def test_return_to_desktop_runs_configured_command(
    monkeypatch: MonkeyPatch,
    command: str,
    expected: tuple[str, list[str]],
) -> None:
    calls: list[tuple[str, list[str]]] = []
    process = SimpleNamespace(startDetached=lambda *args: calls.append(args) or True)
    window = cast(MainWindowSystemTabMixin, SimpleNamespace())
    monkeypatch.setenv("PORTPROTONQT_RETURN_TO_DESKTOP_SCRIPT", command)
    monkeypatch.setattr(system_tab_module, "QProcess", process)

    MainWindowSystemTabMixin.returnToDesktop(window)

    assert calls == [expected]

def test_return_to_desktop_rejects_invalid_command(monkeypatch: MonkeyPatch) -> None:
    process = SimpleNamespace(startDetached=MagicMock())
    window = cast(MainWindowSystemTabMixin, SimpleNamespace())
    monkeypatch.setenv("PORTPROTONQT_RETURN_TO_DESKTOP_SCRIPT", 'bash "unterminated')
    monkeypatch.setattr(system_tab_module, "QProcess", process)

    MainWindowSystemTabMixin.returnToDesktop(window)

    process.startDetached.assert_not_called()

def test_logout_uses_current_session_id(monkeypatch: MonkeyPatch) -> None:
    calls: list[tuple[str, list[str]]] = []
    process = SimpleNamespace(startDetached=lambda *args: calls.append(args) or True)
    window = cast(MainWindowSystemTabMixin, SimpleNamespace())
    monkeypatch.setenv("XDG_SESSION_ID", "session-1")
    monkeypatch.setattr(system_tab_module, "QProcess", process)

    MainWindowSystemTabMixin.logoutSystem(window)

    assert calls == [("loginctl", ["terminate-session", "session-1"])]

def test_logout_skips_without_session_id(monkeypatch: MonkeyPatch) -> None:
    calls: list[tuple[str, list[str]]] = []
    process = SimpleNamespace(startDetached=lambda *args: calls.append(args) or True)
    window = cast(MainWindowSystemTabMixin, SimpleNamespace())
    monkeypatch.delenv("XDG_SESSION_ID", raising=False)
    monkeypatch.setattr(system_tab_module, "QProcess", process)

    MainWindowSystemTabMixin.logoutSystem(window)

    assert calls == []

def test_delayed_system_adapters_appear_on_retry() -> None:
    application = QApplication.instance() or QApplication([])
    assert application is not None
    event_loop = QEventLoop()
    network_timer = QTimer()
    bluetooth_timer = QTimer()
    network_timer.setInterval(1)
    bluetooth_timer.setInterval(1)
    available_sections: list[str] = []
    window = cast(
        MainWindowSystemTabMixin,
        SimpleNamespace(
            networkRetryTimer=network_timer,
            bluetoothRetryTimer=bluetooth_timer,
            networkRetryCount=0,
            bluetoothRetryCount=0,
            _setBluetoothScanPreloaderVisible=lambda _visible: None,
            populateSystemNetworks=lambda payload: (
                available_sections.append("wifi") if payload["available"] else None
            ),
            populateSystemBluetoothDevices=lambda payload: (
                available_sections.append("bluetooth") if payload["available"] else None
            ),
            setNetworkBusy=lambda _busy: None,
            setBluetoothBusy=lambda _busy: None,
        ),
    )

    def make_adapters_available() -> None:
        MainWindowSystemTabMixin.onNetworkOperationFinished(window, "load", {"available": True})
        MainWindowSystemTabMixin.onBluetoothOperationFinished(window, "load", {"available": True})
        event_loop.quit()

    network_timer.timeout.connect(make_adapters_available)
    MainWindowSystemTabMixin.onNetworkOperationFinished(window, "load", {"available": False})
    MainWindowSystemTabMixin.onBluetoothOperationFinished(window, "load", {"available": False})

    QTimer.singleShot(100, event_loop.quit)
    event_loop.exec()

    assert available_sections == ["wifi", "bluetooth"]
    assert not network_timer.isActive()
    assert not bluetooth_timer.isActive()

def test_missing_system_adapters_stop_after_retries() -> None:
    _application = QApplication.instance() or QApplication([])
    network_timer = QTimer()
    bluetooth_timer = QTimer()
    window = cast(
        MainWindowSystemTabMixin,
        SimpleNamespace(
            networkRetryTimer=network_timer,
            bluetoothRetryTimer=bluetooth_timer,
            networkRetryCount=0,
            bluetoothRetryCount=0,
            networkRows=[],
            vpnRows=[],
            bluetoothRows=[],
            populateSystemNetworks=lambda _payload: None,
            populateSystemBluetoothDevices=lambda _payload: None,
            setNetworkBusy=lambda _busy: None,
            setBluetoothBusy=lambda _busy: None,
            _setBluetoothScanPreloaderVisible=lambda _visible: None,
        ),
    )

    for _attempt in range(system_tab_module.SYSTEM_DEVICE_RETRY_LIMIT):
        MainWindowSystemTabMixin.onNetworkOperationFinished(window, "load", {"available": False})
        MainWindowSystemTabMixin.onBluetoothOperationFinished(window, "load", {"available": False})
        assert network_timer.isActive()
        assert bluetooth_timer.isActive()
        network_timer.stop()
        bluetooth_timer.stop()

    MainWindowSystemTabMixin.onNetworkOperationFinished(window, "load", {"available": False})
    MainWindowSystemTabMixin.onBluetoothOperationFinished(window, "load", {"available": False})

    assert window.networkRetryCount == system_tab_module.SYSTEM_DEVICE_RETRY_LIMIT
    assert window.bluetoothRetryCount == system_tab_module.SYSTEM_DEVICE_RETRY_LIMIT
    assert not network_timer.isActive()
    assert not bluetooth_timer.isActive()


def test_installed_filter_reuses_loaded_store_games(monkeypatch: MonkeyPatch) -> None:
    installed = ("Installed", "", "", "1", "", "egs://launch/1")
    uninstalled = ("Uninstalled", "", "", "2", "", "egs://install/2")
    manager = SimpleNamespace(
        games=[], filtered_games=[], _build_search_indices=MagicMock(),
        update_game_grid=MagicMock(),
    )
    window = cast(Any, SimpleNamespace(
        searchEdit=SimpleNamespace(clear=MagicMock()),
        games=[installed, uninstalled],
        game_library_manager=manager,
        _loaded_library_cache={"egs": [installed, uninstalled]},
        loadGames=MagicMock(),
    ))
    monkeypatch.setattr(game_config, "set_only_installed", lambda _checked: None)
    monkeypatch.setattr(game_config, "get_display_filter", lambda: "egs")

    LibraryMixin._on_only_installed_changed(window, True)

    assert manager.games == [installed]
    assert manager.filtered_games == [installed]
    manager._build_search_indices.assert_called_once_with([installed])
    manager.update_game_grid.assert_called_once_with(
        is_filter=True, focus_first_card=False
    )

    LibraryMixin._on_only_installed_changed(window, False)

    assert manager.games == [installed, uninstalled]
    assert manager.filtered_games == [installed, uninstalled]
    window.loadGames.assert_not_called()

def test_gog_account_state_detects_saved_auth(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    class Control:
        def __init__(self) -> None:
            self.text = ""
            self.enabled = False

        def setText(self, text: str) -> None:
            self.text = text

        def setEnabled(self, enabled: bool) -> None:
            self.enabled = enabled

    auth_path = tmp_path / "auth.json"
    auth_path.write_text("{}")
    window = SimpleNamespace(
        gog_api=SimpleNamespace(
            auth_path=auth_path,
            get_account_name=lambda: "gog-user",
        ),
        gogAccountStatus=Control(),
        gogLoginButton=Control(),
    )
    monkeypatch.setattr(download_tab_module, "_", lambda text: text)

    GOGMixin._update_gog_account_state(cast(Any, window))

    assert window.gogAccountStatus.text == "gog-user"
    assert window.gogLoginButton.text == "Log out"

def test_gog_account_action_logs_out_and_reloads_library(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    auth_path = tmp_path / "auth.json"
    auth_path.write_text("{}")
    calls = []

    def logout() -> bool:
        calls.append("logout")
        auth_path.unlink()
        return True

    window = SimpleNamespace(
        gog_api=SimpleNamespace(
            auth_path=auth_path,
            get_account_name=lambda: "",
            logout=logout,
        ),
        gogAccountStatus=SimpleNamespace(setText=lambda text: calls.append(text)),
        gogLoginButton=SimpleNamespace(
            setEnabled=lambda enabled: calls.append(("enabled", enabled)),
            setText=lambda text: calls.append(("button", text)),
        ),
        loadGames=lambda **kwargs: calls.append(("load", kwargs)),
    )
    window._update_gog_account_state = lambda: GOGMixin._update_gog_account_state(
        cast(Any, window)
    )
    monkeypatch.setattr(download_tab_module, "_", lambda text: text)

    GOGMixin._handle_gog_account_action(cast(Any, window))

    assert "logout" in calls
    assert ("button", "Open login page") in calls
    assert ("load", {"force_load": True}) in calls

def test_gog_account_name_callback_updates_status() -> None:
    values = []
    window = SimpleNamespace(
        gogAccountStatus=SimpleNamespace(setText=values.append),
    )

    GOGMixin._on_gog_account_name_loaded(cast(Any, window), "gog-user")

    assert values == ["gog-user"]

def test_gog_library_refresh_restores_account_status() -> None:
    calls = []
    window = SimpleNamespace(
        _update_gog_account_state=lambda: calls.append("account"),
        loadGames=lambda **kwargs: calls.append(("load", kwargs)),
    )

    GOGMixin._on_gog_library_loaded(cast(Any, window), [])

    assert calls == ["account", ("load", {"force_load": True})]

def test_library_refresh_updates_connected_gog_library(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    auth_path = tmp_path / "auth.json"
    auth_path.touch()
    monkeypatch.setattr(game_config, "get_display_filter", lambda: "gog")
    monkeypatch.setattr(
        library_tab_module.QTimer,
        "singleShot",
        lambda _delay, callback: callback(),
    )
    calls = []
    refresh_button = MagicMock()
    refresh_button.setEnabled.side_effect = lambda enabled: calls.append(enabled)
    window = SimpleNamespace(
        _refresh_in_progress=False,
        searchEdit=SimpleNamespace(clear=lambda: calls.append("clear")),
        refreshButton=refresh_button,
        _gamepad_tooltip_map={},
        game_library_manager=None,
        gog_api=SimpleNamespace(auth_path=auth_path),
        gog_library_worker=None,
        _load_gog_games_async=lambda callback: callback([]),
        _refresh_gog_library=lambda: calls.append("gog"),
        loadGames=lambda **kwargs: calls.append(("load", kwargs)),
    )

    LibraryMixin.refreshGames(cast(Any, window))

    assert calls == [
        "clear",
        False,
        "gog",
        ("load", {"force_load": True}),
    ]

def test_library_refresh_updates_connected_stores_for_all_filter(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    gog_auth_path = tmp_path / "gog_auth.json"
    egs_user_path = tmp_path / "egs_user.json"
    gog_auth_path.touch()
    egs_user_path.touch()
    monkeypatch.setattr(game_config, "get_display_filter", lambda: "all")
    monkeypatch.setattr(
        library_tab_module.QTimer,
        "singleShot",
        lambda _delay, callback: callback(),
    )
    calls = []
    window = SimpleNamespace(
        _refresh_in_progress=False,
        searchEdit=SimpleNamespace(clear=lambda: None),
        refreshButton=MagicMock(),
        _gamepad_tooltip_map={},
        game_library_manager=None,
        gog_api=SimpleNamespace(auth_path=gog_auth_path),
        egs_api=SimpleNamespace(user_path=egs_user_path),
        _refresh_gog_library=lambda: calls.append("gog"),
        _refresh_egs_library=lambda: calls.append("egs"),
        loadGames=lambda **kwargs: calls.append(("load", kwargs)),
    )

    LibraryMixin.refreshGames(cast(Any, window))

    assert calls == [
        "gog",
        "egs",
        ("load", {"force_load": True}),
    ]

def test_library_refresh_skips_gog_for_portproton_filter(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    auth_path = tmp_path / "auth.json"
    auth_path.touch()
    calls = []
    monkeypatch.setattr(game_config, "get_display_filter", lambda: "portproton")
    monkeypatch.setattr(
        library_tab_module.QTimer,
        "singleShot",
        lambda _delay, callback: callback(),
    )
    window = SimpleNamespace(
        _refresh_in_progress=False,
        searchEdit=SimpleNamespace(clear=lambda: None),
        refreshButton=MagicMock(),
        _gamepad_tooltip_map={},
        game_library_manager=None,
        gog_api=SimpleNamespace(auth_path=auth_path),
        gog_library_worker=None,
        _load_portproton_games_async=lambda callback: callback([]),
        _refresh_gog_library=lambda: calls.append("gog"),
        loadGames=lambda **kwargs: calls.append(("load", kwargs)),
    )

    LibraryMixin.refreshGames(cast(Any, window))

    assert calls == [("load", {"force_load": True})]

def test_library_refresh_uses_selected_source_refresh(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    auth_path = tmp_path / "auth.json"
    auth_path.touch()
    calls = []
    monkeypatch.setattr(game_config, "get_display_filter", lambda: "custom")
    window = SimpleNamespace(
        _refresh_in_progress=False,
        searchEdit=SimpleNamespace(clear=lambda: None),
        refreshButton=MagicMock(),
        _gamepad_tooltip_map={},
        game_library_manager=None,
        gog_api=SimpleNamespace(auth_path=auth_path),
        gog_library_worker=None,
        _load_custom_games_async=lambda callback: callback([]),
        _refresh_custom_library=lambda: calls.append("custom"),
        _refresh_gog_library=lambda: calls.append("gog"),
    )

    LibraryMixin.refreshGames(cast(Any, window))

    assert calls == ["custom"]

def test_gog_library_refresh_failure_reloads_cached_games(
    monkeypatch: MonkeyPatch,
) -> None:
    calls = []
    window = SimpleNamespace(
        gogAccountStatus=SimpleNamespace(setText=lambda text: calls.append(text)),
        loadGames=lambda **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(download_tab_module, "_", lambda text: text)

    GOGMixin._on_gog_library_failed(cast(Any, window), "network error")

    assert calls == [
        "Failed to refresh GOG library: network error",
        {"force_load": True},
    ]

def test_gog_login_shows_cached_games_before_refresh(monkeypatch: MonkeyPatch) -> None:
    calls = []
    window = SimpleNamespace(
        gog_api=SimpleNamespace(get_account_name=lambda: "gog-user"),
        gogAccountStatus=SimpleNamespace(setText=lambda text: calls.append(text)),
        loadGames=lambda **kwargs: calls.append(("load", kwargs)),
        _refresh_gog_library=lambda: calls.append("refresh"),
    )
    monkeypatch.setattr(download_tab_module, "_", lambda text: text)

    GOGMixin._on_gog_authenticated(cast(Any, window), True, "")

    assert calls == [
        "gog-user",
        ("load", {"force_load": True}),
        "refresh",
    ]

def test_egs_library_progress_shows_game_count(monkeypatch: MonkeyPatch) -> None:
    values = []
    window = SimpleNamespace(
        egsAccountStatus=SimpleNamespace(setText=values.append),
    )
    monkeypatch.setattr(download_tab_module, "_", lambda text: text)

    GOGMixin._on_egs_library_progress(cast(Any, window), 7, 12)

    assert values == ["Refreshing Epic library… 7/12"]
