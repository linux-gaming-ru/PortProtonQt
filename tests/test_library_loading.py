"""Progressive library loading, drawing and input regressions."""
from collections.abc import Callable, Generator
from pathlib import Path
from time import perf_counter
import logging
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
from portprotonqt.theme_manager import load_theme


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
def test_real_cover_loading_and_first_paint_focus_latency(
    real_cover_scene: tuple[GameLibraryManager, Path],
    monkeypatch: pytest.MonkeyPatch, animation_type: str,
) -> None:
    manager, cover_path = real_cover_scene
    monkeypatch.setattr(manager.theme, "GAME_CARD_ANIMATION",
                        {**manager.theme.GAME_CARD_ANIMATION, "card_animation_type": animation_type})
    threads: list[bool] = []
    paints: list[tuple[float, bool]] = []
    ticks: list[float] = []
    original_paint = GameCard.paintEvent
    original_cover = GameCard.on_cover_loaded

    def record_paint(card: GameCard, event: Any) -> None:
        if card.name == "Game 0":
            paints.append((perf_counter(), card._focused or card._hovered))
        original_paint(card, event)

    def record_cover(card: GameCard, pixmap: QPixmap) -> None:
        threads.append(QThread.currentThread() == card.thread())
        original_cover(card, pixmap)

    def sample() -> None:
        ticks.append(perf_counter())
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
    QTimer.singleShot(2000, loop.quit)
    manager.set_games(games)
    loop.exec()
    timer.stop()
    assert len(threads) == len(games) and all(threads), threads
    highlighted = next((paint for paint in paints if paint[1]), None)
    assert highlighted is not None
    focus_delay = highlighted[0] - paints[0][0]
    max_gap = max(after - before for before, after in zip(ticks, ticks[1:], strict=False))
    logging.getLogger(__name__).info("%s: highlight %.1f ms, UI pause %.1f ms", animation_type, focus_delay * 1000, max_gap * 1000)
    assert focus_delay < 0.05, paints
    assert max_gap < 0.1, ticks


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
