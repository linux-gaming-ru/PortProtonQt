"""Progressive library loading, drawing and input regressions."""
from collections.abc import Callable, Generator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QThread, Qt, QTimer
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

from portprotonqt import image_utils
from portprotonqt.game_card import GameCard
from portprotonqt.game_library_manager import GameLibraryManager
from portprotonqt.theme_manager import ThemeManager, load_theme

LOAD_TIMEOUT_MS = 30000


@pytest.fixture
def library_scene(
    monkeypatch: pytest.MonkeyPatch, tmp_config_dir: Path,
) -> Generator[tuple[GameLibraryManager, list[Callable[[QPixmap], None]]], None, None]:
    app = QApplication.instance() or QApplication([])
    callbacks: list[Callable[[QPixmap], None]] = []
    monkeypatch.setattr("portprotonqt.game_card.load_pixmap_async",
                        lambda *args, **_kwargs: callbacks.append(args[3]))
    monkeypatch.setattr("portprotonqt.config.ui_config.get_library_layout_mode", lambda _: "grid")
    main = cast(Any, SimpleNamespace(
        searchEdit=QLineEdit(), card_width=180, on_slider_released=lambda: None,
        openGameDetailPage=MagicMock(), current_hovered_card=None, current_focused_card=None,
    ))
    main.createSearchWidget = lambda: (QWidget(), main.searchEdit)
    manager = GameLibraryManager(main, load_theme("standart"), cast(Any, MagicMock()))
    manager.create_games_library_widget()
    cast(Any, manager.gamesLibraryWidget).game_library_manager = manager
    manager.gamesLibraryWidget.resize(1000, 700)
    manager.gamesLibraryWidget.show()
    app.processEvents()
    try:
        yield manager, callbacks
    finally:
        assert manager._incremental_add_timer is not None
        manager._incremental_add_timer.stop()
        cover = QPixmap(300, 450)
        cover.fill(Qt.GlobalColor.darkBlue)
        for callback in callbacks:
            callback(cover)
        manager.stop_background_activity()
        app.processEvents()
        manager.gamesLibraryWidget.close()
        manager.gamesLibraryWidget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_native_card_uses_linux_source_corner(
    library_scene: tuple[GameLibraryManager, list[Callable[[QPixmap], None]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _ = library_scene
    monkeypatch.setattr(ThemeManager(), "current_theme_name", "standart")
    card = manager._create_game_card((
        "Native", "", "", "", "", "native:///game.desktop", "", "", "", "", 0, 0, "native",
    ))
    assert card.native_visible
    assert isinstance(card.nativeLabel._icon, str)
    assert Path(card.nativeLabel._icon).name == "badge_linux.svg"
    assert Path(card.nativeLabel._icon).is_file()
    assert not card.portproton_visible
    card.deleteLater()


@pytest.mark.parametrize("layout_mode", ["horizontal", "horizontal_top"])
@pytest.mark.parametrize("orientation", ["horizontal", "vertical"])
def test_new_horizontal_cards_fit_before_layout_insertion(
    library_scene: tuple[GameLibraryManager, list[Callable[[QPixmap], None]]],
    monkeypatch: pytest.MonkeyPatch, layout_mode: str, orientation: str,
) -> None:
    manager, _ = library_scene
    monkeypatch.setattr("portprotonqt.config.ui_config.get_horizontal_card_orientation",
                        lambda _: orientation)
    manager.rebuild_library_layout(layout_mode)
    manager.gamesLibraryWidget.resize(800, 400)
    QApplication.processEvents()
    assert manager.gamesListLayout is not None and manager.gamesScrollArea is not None
    for name in ("First", "Second"):
        card = manager._create_game_card((name, "", "", "", "", name, "", "", "", "", 0, 0, "steam"))
        margins = manager.gamesListLayout.contentsMargins()
        scale = max(card.card_layout_cfg.get(key, manager.theme.GAME_CARD_ANIMATION[key])
                    for key in ("default_scale", "hover_scale", "focus_scale"))
        ratio = card.card_geometry_cfg["card_height_ratio"]
        assert (card.base_card_width * ratio + card.base_extra_margin) * scale <= (
            manager.gamesScrollArea.viewport().height() - margins.top() - margins.bottom()
        )
        initial_size = card.size()
        manager.game_card_cache[(name, name)] = card
        manager.gamesListLayout.addWidget(card)
        manager._fit_horizontal_cards()
        assert card.size() == initial_size


@pytest.mark.parametrize("layout_mode", ["horizontal", "horizontal_top"])
def test_library_clear_releases_full_library_tile(
    library_scene: tuple[GameLibraryManager, list[Callable[[QPixmap], None]]],
    layout_mode: str,
) -> None:
    manager, _ = library_scene
    manager.layout_mode = "horizontal_top"
    manager.filtered_games = [()] * (manager.theme.horizontalTopGameLimit + 1)
    manager._sync_full_library_tile()
    tile = manager.fullLibraryTile
    assert tile is not None

    manager.clear_layout(manager.gamesListLayout)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    manager.layout_mode = layout_mode
    manager._sync_full_library_tile()
    manager._set_full_library_tile_cover(tile, 0, QPixmap())

    if layout_mode == "horizontal":
        assert manager.fullLibraryTile is None
    else:
        assert manager.fullLibraryTile is not None
        assert manager.fullLibraryTile is not tile


def test_cached_library_stays_visible_when_order_changes(
    library_scene: tuple[GameLibraryManager, list[Callable[[QPixmap], None]]],
) -> None:
    manager, _ = library_scene
    assert manager.gamesListLayout is not None
    for name in ("First", "Second"):
        card = manager._create_game_card((name, "", "", "", "", name, "", "", "", "", 0, 0, "steam"))
        manager.game_card_cache[(name, name)] = card
        manager.gamesListLayout.addWidget(card)
        card.show()
    QApplication.processEvents()
    order = [("Second", "Second"), ("First", "First")]

    manager._start_incremental_add(order, {}, "")

    assert all(card.isVisible() for card in manager.game_card_cache.values())
    assert manager.gamesListLayout.count() == 2
    assert [cast(Any, manager.gamesListLayout.itemAt(index)).widget().name for index in range(2)] == ["Second", "First"]
    assert not manager._incremental_add_queue


@pytest.mark.parametrize("layout_mode", ["horizontal", "horizontal_top"])
def test_horizontal_loading_keeps_card_geometry_stable(
    library_scene: tuple[GameLibraryManager, list[Callable[[QPixmap], None]]],
    monkeypatch: pytest.MonkeyPatch, layout_mode: str,
) -> None:
    manager, _ = library_scene
    monkeypatch.setattr("portprotonqt.config.ui_config.get_horizontal_card_orientation",
                        lambda _: "vertical")
    manager.rebuild_library_layout(layout_mode)
    manager.gamesLibraryWidget.resize(800, 400)
    games = [(f"Game {i}", "", "", "", "", str(i), "", "", "", "", 0, 0, "steam")
             for i in range(4)]
    manager.set_games(games, focus_first_card=False)
    assert manager._incremental_add_timer is not None
    for _ in range(20):
        QApplication.processEvents()
        if manager._incremental_add_queue:
            manager._process_incremental_add_batch()
        manager._incremental_add_timer.stop()
    assert not manager._incremental_add_queue
    card = next(iter(manager.game_card_cache.values()))
    geometry = card.geometry()
    for _ in range(20):
        QApplication.processEvents()
        assert card.geometry() == geometry
    assert manager.gamesScrollArea is not None
    assert card.height() <= manager.gamesScrollArea.viewport().height()
    manager.rebuild_library_layout("grid")
    assert manager.gamesScrollArea.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded


@pytest.mark.parametrize("layout_mode", ["horizontal", "horizontal_top"])
@pytest.mark.parametrize("orientation", ["horizontal", "vertical"])
def test_horizontal_batches_keep_existing_cards_in_place(
    library_scene: tuple[GameLibraryManager, list[Callable[[QPixmap], None]]],
    monkeypatch: pytest.MonkeyPatch, layout_mode: str, orientation: str,
) -> None:
    manager, _ = library_scene
    monkeypatch.setattr("portprotonqt.config.ui_config.get_horizontal_card_orientation",
                        lambda _: orientation)
    manager.rebuild_library_layout(layout_mode)
    manager.gamesLibraryWidget.resize(1280, 800)
    QApplication.processEvents()
    manager._incremental_batch_size = 1
    games = [(f"Game {i}", "", "", "", "", str(i), "", "", "", "", 0, 0, "steam")
             for i in range(8)]
    keys = [(game[0], game[5]) for game in games]
    manager._start_incremental_add(keys, dict(zip(keys, games, strict=True)), "")
    assert manager._incremental_add_timer is not None
    manager._incremental_add_timer.stop()
    QApplication.processEvents()
    manager._incremental_add_timer.stop()
    while manager._incremental_add_queue:
        geometries = {card: card.geometry() for card in manager.game_card_cache.values()}
        manager._process_incremental_add_batch()
        manager._incremental_add_timer.stop()
        assert all(card.geometry() == previous for card, previous in geometries.items())
        QApplication.processEvents()
        manager._incremental_add_timer.stop()
        assert all(card.geometry() == previous for card, previous in geometries.items())


def test_batches_keep_drawing_enabled_and_accept_clicks_before_completion(
    library_scene: tuple[GameLibraryManager, list[Callable[[QPixmap], None]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _ = library_scene
    assert manager.gamesListWidget is not None and manager.gamesListLayout is not None
    update_toggle = MagicMock(wraps=manager.gamesListWidget.setUpdatesEnabled)
    monkeypatch.setattr(manager.gamesListWidget, "setUpdatesEnabled", update_toggle)
    games = [(f"Game {index}", "", "", "", "", str(index), "", "", "", "", 0, 0, "steam") for index in range(40)]
    keys = [(game[0], game[5]) for game in games]
    manager._start_incremental_add(keys, dict(zip(keys, games, strict=True)), "")
    assert manager._incremental_add_timer is not None
    manager._incremental_add_timer.stop()
    if not manager.game_card_cache:
        manager._process_incremental_add_batch()
        manager._incremental_add_timer.stop()
    card = next(iter(manager.game_card_cache.values()))
    position = card.rect().center().toPointF()
    for event_type, buttons in ((QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
                                (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
        QCoreApplication.postEvent(card, QMouseEvent(event_type, position, position,
                                   Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier))
    QApplication.processEvents()
    manager._incremental_add_timer.stop()

    cast(Any, manager.main_window).openGameDetailPage.assert_called_once()
    assert manager._incremental_add_queue
    while manager._incremental_add_queue:
        count_before = manager.gamesListLayout.count()
        manager._process_incremental_add_batch()
        manager._incremental_add_timer.stop()
        QApplication.processEvents()
        assert manager.gamesListLayout.count() > count_before
        assert manager.gamesListWidget.updatesEnabled()
        assert all(card.isVisible() for card in manager.game_card_cache.values())
    update_toggle.assert_not_called()


def test_switch_during_loading_cancels_old_cards_and_reuses_cached_cards(
    library_scene: tuple[GameLibraryManager, list[Callable[[QPixmap], None]]],
) -> None:
    manager, _ = library_scene
    games = [(f"Game {i}", "", "", "", "", str(i), "", "", "", "", 0, 0, "steam") for i in range(40)]
    keys = [(game[0], game[5]) for game in games]
    manager._start_incremental_add(keys, dict(zip(keys, games, strict=True)), "")
    cached = manager.game_card_cache[keys[0]]
    manager._start_incremental_add([keys[0]], {}, "")
    QApplication.processEvents()
    assert manager.game_card_cache[keys[0]] is cached
    assert cached.isVisible()
    assert not manager._incremental_add_queue
    assert len(manager.game_card_cache) < len(games)
    assert manager.gamesListLayout is not None
    assert manager.gamesListLayout.count() == 1


def test_previous_source_completion_is_cached_without_replacing_current_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from portprotonqt.main_window import MainWindow

    monkeypatch.setattr("portprotonqt.main_window.game_config.get_display_filter", lambda: "egs")
    monkeypatch.setattr("portprotonqt.main_window.game_config.get_only_installed", lambda: False)
    manager = SimpleNamespace(set_games=MagicMock())
    window = cast(Any, SimpleNamespace(
        _loading_library_filter=("steam", False), _loaded_library_cache={},
        game_library_manager=manager, _on_only_installed_changed=MagicMock(),
    ))
    games = [("Steam game", "", "", "", "", "steam://1")]
    MainWindow.on_games_loaded(window, games)
    assert window._loaded_library_cache == {"steam": games}
    window._on_only_installed_changed.assert_called_once_with(False)
    manager.set_games.assert_not_called()
    assert not window._loading_games


def test_source_switch_keeps_cached_widgets_and_shutdown_cancels_loading(
    library_scene: tuple[GameLibraryManager, list[Callable[[QPixmap], None]]],
) -> None:
    manager, _ = library_scene
    games = [(name, "", "", "", "", name, "", "", "", "", 0, 0, "steam") for name in ("First", "Second")]
    main = cast(Any, manager.main_window)
    main._loaded_library_cache = {"steam": games, "egs": games[:1]}
    manager.games = manager.filtered_games = games
    manager.dirty = True
    manager._update_game_grid_immediate()
    assert manager._incremental_add_timer is not None
    while manager._incremental_add_queue:
        manager._process_incremental_add_batch()
        manager._incremental_add_timer.stop()
    second = manager.game_card_cache[("Second", "Second")]
    manager.games = manager.filtered_games = games[:1]
    manager.dirty = True
    manager._update_game_grid_immediate()
    assert not second.isVisible()
    manager.games = manager.filtered_games = games
    manager.dirty = True
    manager._update_game_grid_immediate()
    assert manager.game_card_cache[("Second", "Second")] is second
    assert second.isVisible()
    assert manager._incremental_add_timer is not None
    manager._incremental_add_timer.start(0)
    manager.stop_background_activity()
    assert not manager._incremental_add_timer.isActive()
    assert not manager._incremental_add_queue


def test_first_batch_receives_focus_without_waiting_for_remaining_cards(
    library_scene: tuple[GameLibraryManager, list[Callable[[QPixmap], None]]],
) -> None:
    manager, _ = library_scene
    main = cast(Any, manager.main_window)
    main.stackedWidget = SimpleNamespace(currentIndex=lambda: 0)
    manager.gamesLibraryWidget.activateWindow()
    main.searchEdit.setFocus()
    QApplication.processEvents()
    manager._focus_first_card_after_update = True
    games = [(f"Game {i}", "", "", "", "", str(i), "", "", "", "", 0, 0, "steam") for i in range(80)]
    keys = [(game[0], game[5]) for game in games]
    manager._start_incremental_add(keys, dict(zip(keys, games, strict=True)), "")
    assert manager._incremental_add_timer is not None
    manager._incremental_add_timer.stop()
    QApplication.processEvents()

    first = manager.game_card_cache[keys[0]]
    assert manager._incremental_add_queue
    assert first.hasFocus()
    assert main.current_focused_card is first
    while keys[1] not in manager.game_card_cache:
        manager._process_incremental_add_batch()
        manager._incremental_add_timer.stop()
        QApplication.processEvents()
    second = manager.game_card_cache[keys[1]]
    second.setFocus()
    while manager._incremental_add_queue:
        manager._process_incremental_add_batch()
        manager._incremental_add_timer.stop()
        QApplication.processEvents()
    assert second.hasFocus()
    assert main.current_focused_card is second


@pytest.mark.parametrize("layout_mode", ["grid", "horizontal"])
def test_scrolling_defers_card_creation_until_scroll_stops(
    library_scene: tuple[GameLibraryManager, list[Callable[[QPixmap], None]]],
    layout_mode: str,
) -> None:
    manager, _ = library_scene
    manager.rebuild_library_layout(layout_mode)
    QApplication.processEvents()
    games = [(f"Game {i}", "", "", "", "", str(i), "", "", "", "", 0, 0, "steam") for i in range(80)]
    keys = [(game[0], game[5]) for game in games]
    manager._start_incremental_add(keys, dict(zip(keys, games, strict=True)), "")
    assert manager._incremental_add_timer is not None
    assert manager.gamesScrollArea is not None
    scrollbar = (manager.gamesScrollArea.horizontalScrollBar() if layout_mode == "horizontal"
                 else manager.gamesScrollArea.verticalScrollBar())
    while scrollbar.maximum() < 100:
        manager._incremental_add_timer.stop()
        manager._process_incremental_add_batch()
        QApplication.processEvents()
    manager._incremental_add_timer.stop()
    count_before = len(manager.game_card_cache)

    def scroll() -> None:
        scrollbar.setValue(0 if scrollbar.value() else 50)

    loop = QEventLoop()
    scroll_timer = QTimer()
    scroll_timer.timeout.connect(scroll)
    scroll_timer.start(20)
    manager._incremental_add_timer.start(manager._incremental_batch_budget_ms)
    scroll()
    QTimer.singleShot(manager._incremental_scroll_delay_ms * 2, loop.quit)
    loop.exec()
    scroll_timer.stop()
    assert len(manager.game_card_cache) == count_before
    assert manager._incremental_add_queue
    assert manager.gamesListWidget is not None and manager.gamesListWidget.updatesEnabled()

    manager._incremental_add_timer.timeout.connect(loop.quit)
    QTimer.singleShot(manager._incremental_scroll_delay_ms * 2, loop.quit)
    loop.exec()
    manager._incremental_add_timer.timeout.disconnect(loop.quit)
    manager._incremental_add_timer.stop()
    assert len(manager.game_card_cache) > count_before


@pytest.fixture
def real_cover_scene(
    library_scene: tuple[GameLibraryManager, list[Callable[[QPixmap], None]]],
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> tuple[GameLibraryManager, Path]:
    manager, _ = library_scene
    main = cast(Any, manager.main_window)
    main.stackedWidget = SimpleNamespace(currentIndex=lambda: 0)
    main.getColorPalette_from_pixmap = MagicMock()
    manager.gamesLibraryWidget.activateWindow()
    QApplication.processEvents()
    cover = QPixmap(600, 900)
    cover.fill(Qt.GlobalColor.darkBlue)
    cover_path = tmp_path / "cover.jpg"
    assert cover.save(str(cover_path))
    monkeypatch.setattr("portprotonqt.game_card.load_pixmap_async", image_utils.load_pixmap_async)
    return manager, cover_path


@pytest.mark.parametrize("animation_type", ["gradient", "glow"])
def test_real_cover_loading_yields_and_focuses_first_paint(
    real_cover_scene: tuple[GameLibraryManager, Path],
    monkeypatch: pytest.MonkeyPatch, animation_type: str,
) -> None:
    manager, cover_path = real_cover_scene
    monkeypatch.setattr(manager.theme, "GAME_CARD_ANIMATION",
                        {**manager.theme.GAME_CARD_ANIMATION, "card_animation_type": animation_type})
    threads: list[bool] = []
    paints: list[bool] = []
    ticks: list[tuple[int, int]] = []
    original_paint = GameCard.paintEvent
    original_cover = GameCard.on_cover_loaded

    def record_paint(card: GameCard, event: Any) -> None:
        if card.name == "Game 0":
            paints.append(card._focused or card._hovered)
        original_paint(card, event)

    def record_cover(card: GameCard, pixmap: QPixmap) -> None:
        threads.append(QThread.currentThread() == card.thread())
        original_cover(card, pixmap)

    def sample() -> None:
        ticks.append((len(manager.game_card_cache), len(threads)))
        if len(threads) == len(games) and not manager._incremental_add_queue:
            loop.quit()

    monkeypatch.setattr(GameCard, "paintEvent", record_paint)
    monkeypatch.setattr(GameCard, "on_cover_loaded", record_cover)
    games = [(f"Game {i}", "", str(cover_path), "", "", str(i), "", "", "", "", 0, 0, "steam") for i in range(16)]
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(sample)
    timer.start()
    QTimer.singleShot(LOAD_TIMEOUT_MS, loop.quit)
    manager.set_games(games)
    loop.exec()
    timer.stop()
    assert len(threads) == len(games) and all(threads), threads
    assert paints and paints[0], paints
    assert any(0 < cards < len(games) for cards, _ in ticks), ticks
    assert any(0 < covers < len(games) for _, covers in ticks), ticks


@pytest.mark.parametrize("scenario", [("grid", 0), ("grid", 1), ("vertical", 0), ("vertical", 1)])
def test_failed_protondb_completion_preserves_library_scroll(
    library_scene: tuple[GameLibraryManager, list[Callable[[QPixmap], None]]],
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, scenario: tuple[str, int],
) -> None:
    from portprotonqt.main_window import MainWindow
    from portprotonqt.steam_api import api
    import portprotonqt.portproton_api as portproton_api

    manager, _ = library_scene
    manager.rebuild_library_layout(scenario[0])
    main = cast(Any, manager.main_window)
    main.stackedWidget = SimpleNamespace(currentIndex=lambda: 0)
    main.getColorPalette_from_pixmap = MagicMock()
    main.game_library_manager = manager
    main._get_portproton_desktop_files = lambda: set()
    monkeypatch.setattr(portproton_api, "get_user_conf_setting", lambda _key: None)
    monkeypatch.setattr(api, "load_protondb_status", lambda _appid: None)
    monkeypatch.setattr(api, "CacheManager", lambda: SimpleNamespace(cache_dir=tmp_path))
    responses: list[Callable[[str | None], None]] = []
    monkeypatch.setattr(api.downloader, "download_async",
                        lambda *_args, **kwargs: responses.append(kwargs["callback"]))
    games = [(f"Game {i}", "", "", "", "", str(i), "", "", "", "", 0, 0, "steam") for i in range(40)]
    manager.set_games(games)
    QApplication.processEvents()
    assert manager._incremental_add_timer is not None
    while manager._incremental_add_queue:
        manager._process_incremental_add_batch()
        manager._incremental_add_timer.stop()
        QApplication.processEvents()
    api.get_protondb_tier_async(1, lambda _tier: MainWindow.on_games_loaded(main, games))
    assert manager.gamesScrollArea is not None
    scrollbar = manager.gamesScrollArea.verticalScrollBar()
    scrollbar.setValue(scrollbar.maximum() // 2)
    previous_value = scrollbar.value()
    assert previous_value > 0
    main.stackedWidget.currentIndex = lambda: scenario[1]

    responses[0](None)
    QApplication.processEvents()
    QApplication.processEvents()

    assert scrollbar.value() == previous_value
    assert not manager._focus_first_card_after_update


def test_initial_favorite_icon_does_not_restart_library_loading(
    library_scene: tuple[GameLibraryManager, list[Callable[[QPixmap], None]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _ = library_scene
    cast(Any, manager.gamesLibraryWidget).game_library_manager = manager
    update_grid = MagicMock()
    monkeypatch.setattr(manager, "update_game_grid", update_grid)
    monkeypatch.setattr("portprotonqt.game_card.favorites_config.get_games", lambda: [])
    monkeypatch.setattr("portprotonqt.game_card.favorites_config.set_games", lambda _games: None)
    game = ("Game", "", "", "", "", "steam://1", "", "", "", "", 0, 0, "steam")
    card = manager._create_game_card(game)
    manager.game_card_cache[(game[0], game[5])] = card
    QApplication.processEvents()
    update_grid.assert_not_called()
    card.update_favorite_icon()
    QApplication.processEvents()
    update_grid.assert_not_called()
    card.toggle_favorite()
    QApplication.processEvents()
    update_grid.assert_called_once()


def test_vertical_library_headers_align_with_values(
    library_scene: tuple[GameLibraryManager, list[Callable[[QPixmap], None]]],
) -> None:
    manager, _ = library_scene
    manager.rebuild_library_layout("vertical")
    assert manager._update_timer is not None
    manager._update_timer.stop()
    assert manager.gamesListLayout is not None
    assert manager.libraryHeaderWidget is not None
    card = manager._create_game_card(
        ("Game", "", "", "", "", "game", "", "", "", "", 0, 0, "steam")
    )
    manager.game_card_cache[("Game", "game")] = card
    manager.gamesListLayout.addWidget(card)
    card.show()
    header = cast(Any, manager.libraryHeaderWidget.layout())
    for width in (900, 1300):
        manager.gamesLibraryWidget.resize(width, 500)
        QApplication.processEvents()
        QApplication.processEvents()
        for index in range(1, 5):
            heading = header.itemAt(index).widget()
            value = cast(Any, card.layout_.itemAt(index)).widget()
            assert heading.text() == heading.text().upper()
            if index == 1:
                assert heading.mapToGlobal(heading.rect().topLeft()).x() == value.mapToGlobal(value.rect().topLeft()).x()
            else:
                assert heading.alignment() == value.alignment() == Qt.AlignmentFlag.AlignCenter
                assert abs(heading.mapToGlobal(heading.rect().center()).x()
                           - value.mapToGlobal(value.rect().center()).x()) <= 1


def test_space_enters_and_toggles_card_selection_without_opening_details(
    library_scene: tuple[GameLibraryManager, list[Callable[[QPixmap], None]]],
) -> None:
    manager, _ = library_scene
    game = ("Game", "", "", "", "", "game.exe", "", "", "", "", 0, 0, "portproton")
    card = manager._create_game_card(game)
    from portprotonqt.context_menu_manager import ContextMenuManager
    from PySide6.QtGui import QKeyEvent

    selection_manager = object.__new__(ContextMenuManager)
    selection_manager.game_library_manager = manager
    selection_manager.card_selection_mode = False
    manager.game_card_cache[(card.name, card.exec_line)] = card
    card.context_menu_manager = selection_manager
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
    card.keyPressEvent(event)
    assert card.batch_selected
    assert selection_manager.card_selection_mode
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
    card.keyPressEvent(event)
    assert not card.batch_selected
    assert not selection_manager.card_selection_mode
    cast(Any, manager.main_window).openGameDetailPage.assert_not_called()


@pytest.mark.parametrize("activation", ["mouse", "gamepad"])
@pytest.mark.parametrize("game_source", ["portproton", "gog", "egs"])
def test_selection_mode_toggles_without_opening_game(
    library_scene: tuple[GameLibraryManager, list[Callable[[QPixmap], None]]],
    monkeypatch: pytest.MonkeyPatch, activation: str, game_source: str,
) -> None:
    from portprotonqt.context_menu_manager import ContextMenuManager
    from portprotonqt.main_window import MainWindow

    library, _ = library_scene
    menu = object.__new__(ContextMenuManager)
    menu.game_library_manager = library
    game = ("Game", "", "", "", "", "missing.exe", "", "", "", "", 0, 0, game_source)
    card = library._create_game_card(game)
    card.context_menu_manager = menu
    library.game_card_cache[(card.name, card.exec_line)] = card
    monkeypatch.setattr(QApplication, "focusWidget", lambda: card)
    menu.start_card_selection(card)
    assert menu.card_selection_mode and card.batch_selected
    for selected in (False, True):
        if activation == "mouse":
            position = card.rect().center().toPointF()
            card.mousePressEvent(QMouseEvent(
                QEvent.Type.MouseButtonPress, position, position,
                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
            ))
        else:
            MainWindow.activateFocusedWidget(cast(Any, library.main_window))
        assert card.batch_selected is selected
    cast(Any, library.main_window).openGameDetailPage.assert_not_called()
    menu.clear_card_selection()
    assert not menu.card_selection_mode and not card.batch_selected


@pytest.mark.parametrize("layout_mode", ["grid", "horizontal", "horizontal_top", "list", "vertical"])
def test_search_preserves_selection_across_different_queries(
    library_scene: tuple[GameLibraryManager, list[Callable[[QPixmap], None]]],
    monkeypatch: pytest.MonkeyPatch, layout_mode: str,
) -> None:
    from portprotonqt.context_menu_manager import ContextMenuManager

    library, _ = library_scene
    monkeypatch.setattr("portprotonqt.config.ui_config.get_library_layout_mode", lambda _: layout_mode)
    monkeypatch.setattr(library, "_incremental_batch_size", 1)
    library.rebuild_library_layout(layout_mode)
    games = [(name, "", "", "", "", name, "", "", "", "", 0, 0, "portproton")
             for name in ("DOOM64", "Akalabeth of Doom", "Biomance")]
    cast(Any, library.main_window)._loaded_library_cache = {"portproton": games}
    library.set_games(games, focus_first_card=False)
    assert library._update_timer is not None and library._incremental_add_timer is not None
    library._update_timer.stop()
    library._update_game_grid_immediate()
    while library._incremental_add_queue:
        library._process_incremental_add_batch()
    library._incremental_add_timer.stop()
    menu = object.__new__(ContextMenuManager)
    menu.game_library_manager = library
    cards = {card.name: card for card in library.game_card_cache.values()}
    for card in cards.values():
        card.context_menu_manager = menu
    for query in ("doom", "bio", ""):
        library.main_window.searchEdit.setText(query)
        library.filter_games_delayed()
        library._update_timer.stop()
        library._update_game_grid_immediate()
        while library._incremental_add_queue:
            library._process_incremental_add_batch()
        library._incremental_add_timer.stop()
        if query == "doom":
            menu.start_card_selection(cards["DOOM64"])
            cards["Akalabeth of Doom"].click()
        elif query == "bio":
            cards["Biomance"].click()
            assert not cards["DOOM64"].isVisible()
        if query != "doom":
            assert all(card.batch_selected for card in cards.values())
        assert menu.card_selection_mode
    menu.clear_card_selection()
    assert not any(card.batch_selected for card in cards.values())
    cast(Any, library.main_window).openGameDetailPage.assert_not_called()
