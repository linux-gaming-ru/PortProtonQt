"""Regression checks for library resize layout and batching."""
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from portprotonqt.custom_widgets import FlowLayout, compute_layout
from portprotonqt.game_card import AnimatedCard, GameCard
from portprotonqt.game_library_manager import GameLibraryManager
from portprotonqt.theme_manager import load_theme
from portprotonqt.config import ui_config


@pytest.mark.parametrize("theme_name", ["standart", "classic-light"])
def test_list_rows_alternate_after_filtering(theme_name: str) -> None:
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    layout = QVBoxLayout(parent)
    layout.setContentsMargins(0, 7, 0, 0)
    layout.setSpacing(4)
    theme = load_theme(theme_name)
    colors = (theme.color_bg, theme.color_surface_elevated)
    cards = []
    for _ in range(3):
        card = cast(Any, AnimatedCard(parent))
        card.list_layout = True
        card.theme = theme
        card.animations = SimpleNamespace(paint_border=lambda painter: None)
        card.setFixedSize(100, 80)
        layout.addWidget(card)
        cards.append(card)
    layout.activate()
    for index, card in enumerate(cards):
        assert card.grab().toImage().pixelColor(50, 40) == QColor(
            colors[index % 2]
        )
    cards[0].hide()
    layout.invalidate()
    layout.activate()
    assert cards[1].grab().toImage().pixelColor(50, 40) == QColor(colors[0])
    parent.close()
    app.processEvents()


def test_flow_layout_preserves_rows_and_centering() -> None:
    sizes = [(100, 120), (140, 80), (80, 150), (180, 90)]
    positions, height = compute_layout(sizes, 320, 20, 1.0)
    assert positions == [[30, 0, 100, 120], [150, 0, 140, 80],
                         [20, 140, 80, 150], [120, 140, 180, 90]]
    assert height == 290
    assert compute_layout([], 320, 20, 1.0) == ([], 0)
    assert compute_layout([(100, 120)], 40, 20, 1.0) == ([[20, 0, 100, 120]], 120)


@pytest.mark.parametrize("centered", [False, True])
def test_flow_layout_wrapped_row_alignment(centered: bool) -> None:
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    layout = FlowLayout(parent)
    if centered:
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    widgets = []
    for width in (100, 100, 100):
        widget = QWidget(parent)
        widget.setFixedSize(width, 30)
        layout.addWidget(widget)
        widget.show()
        widgets.append(widget)
    layout.setGeometry(QRect(0, 0, 300, 100))
    assert widgets[0].x() == 40
    assert widgets[1].x() == 160
    assert widgets[2].x() == (100 if centered else 40)
    parent.close()
    app.processEvents()


def test_flow_minimum_size_tracks_fixed_hidden_and_removed_widgets() -> None:
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    layout = FlowLayout(parent)
    card = QWidget(parent)
    card.setFixedSize(100, 150)
    layout.addWidget(card)
    card.show()
    assert layout.minimumSize() == QSize(140, 190)
    assert layout._get_visible_data()[2] == [(100, 150)]
    card.setFixedSize(200, 300)
    assert layout.minimumSize() == QSize(240, 340)
    assert layout._get_visible_data()[2] == [(200, 300)]
    card.hide()
    assert layout.minimumSize() == QSize(40, 40)
    assert layout._get_visible_data()[2] == []
    layout.takeAt(0)
    assert layout.minimumSize() == QSize(39, 39)
    parent.close()
    app.processEvents()


def test_card_resize_does_not_activate_whole_grid(
    tmp_config_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    layout = FlowLayout(parent)
    card = GameCard("Test", "", "", "", "", "", "", "", "", "", 0, 0,
                    "steam", select_callback=lambda _: None,
                    theme=load_theme("standart"), parent=parent)
    layout.addWidget(card)
    activate = MagicMock()
    monkeypatch.setattr(layout, "activate", activate)
    loader = MagicMock()
    monkeypatch.setattr(card, "_load_cover_image", loader)
    card.base_pixmap = None
    card.animated_cover_path = ""
    card.update_card_size(100)
    assert card.base_card_width == 100
    activate.assert_not_called()
    loader.assert_called_once()
    card.update_card_size(100)
    loader.assert_called_once()
    card.stop_background_activity()
    parent.close()
    app.processEvents()


def test_card_resize_batches_keep_latest_width_and_skip_removed_cards() -> None:
    cards = {(str(index), ""): MagicMock() for index in range(40)}
    manager = cast(Any, SimpleNamespace(
        gamesListWidget=MagicMock(), gamesListLayout=MagicMock(),
        game_card_cache=cards, _card_resize_queue=deque(cards),
        _card_resize_batch_size=8, _card_resize_timer=MagicMock(), card_width=100,
        force_update_cards_library=MagicMock(), load_visible_images=MagicMock(),
    ))
    GameLibraryManager._resize_next_card_batch(manager)
    assert sum(card.update_card_size.call_count for card in cards.values()) == 8
    assert len(manager._card_resize_queue) == 32
    assert manager.gamesListLayout.setEnabled.call_args.args == (True,)
    manager.gamesListLayout.activate.assert_called_once()
    manager.load_visible_images.assert_not_called()
    manager.card_width = 220
    removed = cards.pop(("20", ""))
    while manager._card_resize_queue:
        GameLibraryManager._resize_next_card_batch(manager)
    removed.update_card_size.assert_not_called()
    cards[("39", "")].update_card_size.assert_called_once_with(220)
    manager.force_update_cards_library.assert_called_once()
    manager.load_visible_images.assert_called_once()
    assert manager.gamesListLayout.setEnabled.call_args.args == (True,)
    manager.gamesListWidget.setUpdatesEnabled.assert_not_called()


def test_card_resize_reuses_loaded_cover_and_animation() -> None:
    app = QApplication.instance() or QApplication([])
    card = cast(Any, SimpleNamespace(
        base_card_width=180, base_pixmap=QPixmap(250, 375),
        animated_cover_path="", card_geometry_cfg={"cover_aspect_ratio": 1.5},
        cover_path="cover.png", _load_cover_image=MagicMock(), update_scale=MagicMock(),
    ))
    GameCard.update_card_size(card, 100)
    GameCard.update_card_size(card, 250)
    card._load_cover_image.assert_not_called()
    GameCard.update_card_size(card, 300)
    card._load_cover_image.assert_called_once_with("cover.png")
    card.animated_cover_path = "animated.gif"
    GameCard.update_card_size(card, 400)
    card._load_cover_image.assert_called_once()
    assert card.update_scale.call_count == 4
    app.processEvents()


@pytest.mark.parametrize("orientation", ["horizontal", "vertical"])
def test_horizontal_cards_fit_viewport_height(
    tmp_config_dir: Path, monkeypatch: pytest.MonkeyPatch, orientation: str,
) -> None:
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui_config, "get_horizontal_card_orientation", lambda _: orientation)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    parent = QWidget()
    parent.setProperty("library_layout_mode", "horizontal")
    layout = QHBoxLayout(parent)
    theme = load_theme("standart")
    card = GameCard("Test", "", "", "", "", "", "", "", "", "", 0, 0,
                    "steam", select_callback=lambda _: None, theme=theme, parent=parent)
    layout.addWidget(card)
    scroll.setWidget(parent)
    manager = cast(Any, SimpleNamespace(
        layout_mode="horizontal", gamesScrollArea=scroll, gamesListLayout=layout,
        game_card_cache={("Test", ""): card}, card_width=250, theme=theme,
    ))
    scroll.show()
    for height in (600, 300, 200, 600):
        scroll.resize(800, height)
        app.processEvents()
        GameLibraryManager._fit_horizontal_cards(manager)
        layout.activate()
        app.processEvents()
        margins = layout.contentsMargins()
        assert card.height() + margins.top() + margins.bottom() <= scroll.viewport().height()
        assert card.nameLabel.geometry().bottom() < card.height()
        assert card.nameLabel.height() >= card.nameLabel.sizeHint().height()
        assert card.base_card_width <= manager.card_width
    assert card.base_card_width == manager.card_width
    card.stop_background_activity()
    scroll.close()
    app.processEvents()


@pytest.mark.parametrize("initial_width,target_width", [(100, 250), (250, 100)])
def test_large_resize_keeps_cards_separate_between_batches(
    initial_width: int, target_width: int,
) -> None:
    app = QApplication.instance() or QApplication([])
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    content = QWidget()
    layout = FlowLayout(content)
    cards = {}
    for index in range(40):
        card = cast(Any, QWidget(content))
        card.setFixedSize(initial_width, initial_width * 2)
        card.update_card_size = MagicMock(
            side_effect=lambda width, card=card: card.setFixedSize(width, width * 2)
        )
        layout.addWidget(card)
        cards[(str(index), "")] = card
    scroll.setWidget(content)
    scroll.resize(800, 700)
    scroll.show()
    app.processEvents()
    manager = cast(Any, SimpleNamespace(
        gamesListWidget=content, gamesListLayout=layout, game_card_cache=cards,
        _card_resize_queue=deque(cards), _card_resize_batch_size=8,
        _card_resize_timer=MagicMock(), card_width=target_width,
        force_update_cards_library=MagicMock(), load_visible_images=MagicMock(),
    ))
    try:
        while manager._card_resize_queue:
            GameLibraryManager._resize_next_card_batch(manager)
            app.processEvents()
            geometries = [card.geometry() for card in cards.values()]
            for index, geometry in enumerate(geometries):
                assert all(not geometry.intersects(other) for other in geometries[index + 1:])
    finally:
        scroll.close()
