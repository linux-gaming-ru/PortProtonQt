from types import SimpleNamespace
from typing import Any, Protocol
from portprotonqt.game_card import AnimatedCard, GameCard
from portprotonqt.search_utils import (
    SearchOptimizer,
    ThreadedSearch,
    build_search_items,
    search_index,
)
from PySide6.QtWidgets import QAbstractButton
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame, QScrollArea, QSlider, QScroller, QStackedWidget
from PySide6.QtCore import QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QPaintEvent, QPainter, QPainterPath, QPixmap, QRegion
from portprotonqt.custom_widgets import FlowLayout, AutoHideScrollArea
from portprotonqt.config import favorites_config, game_config, ui_config
from portprotonqt.image_utils import load_pixmap_async
from portprotonqt.localization import _
from portprotonqt.detail_pages.utils import remove_cover_background, setup_cover_background
from portprotonqt.context_menu_manager import ContextMenuManager, CustomLineEdit
from collections import deque


class FullLibraryTile(AnimatedCard):
    def __init__(self, theme: Any):
        super().__init__()
        self.name = ""
        self.animation_base_size = theme.fullLibraryTileSize
        self.tile_pixmap = QPixmap()
        self.setup_card_animations(theme, theme.GAME_CARD_HORIZONTAL)
        self.update_scale()

    def set_tile_pixmap(self, pixmap: QPixmap) -> None:
        self.tile_pixmap = pixmap
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        QFrame.paintEvent(self, event)
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.tile_pixmap)
        painter.end()
        border_painter = QPainter(self)
        self.animations.paint_border(border_painter)
        border_painter.end()

class MainWindowProtocol(Protocol):
    """Protocol defining the interface that MainWindow must implement for GameLibraryManager."""

    def openGameDetailPage(self, game_data: dict) -> None: ...

    def createSearchWidget(self) -> tuple[QWidget, CustomLineEdit]: ...

    def on_slider_released(self) -> None: ...

    def _register_gamepad_tooltip(self, widget: QWidget, text: str) -> None: ...

    # Required attributes
    searchEdit: CustomLineEdit
    card_width: int
    current_hovered_card: GameCard | None
    current_focused_card: GameCard | None
    gamesListWidget: QWidget | None
    stackedWidget: QStackedWidget
    _gamepad_tooltip_map: dict[QWidget, str]

class GameLibraryManager:
    def __init__(self, main_window: MainWindowProtocol, theme, context_menu_manager: ContextMenuManager | None):
        self.main_window = main_window
        self.theme = theme
        self.context_menu_manager: ContextMenuManager | None = context_menu_manager
        self.games: list[tuple] = []
        self.filtered_games: list[tuple] = []
        self.game_card_cache = {}
        self.pending_images = {}
        self.card_width = ui_config.get_card_width()
        self.layout_mode = str(getattr(theme, "LIBRARY_LAYOUT_MODE", "grid")).lower()
        self.gamesListWidget: QWidget | None = None
        self.gamesListLayout: FlowLayout | QHBoxLayout | QVBoxLayout | None = None
        self.gamesScrollArea: QScrollArea | None = None
        self.libraryHeaderWidget: QWidget | None = None
        self.libraryContentLayout: QVBoxLayout | None = None
        self.libraryBackgroundLabel: QLabel | None = None
        self.fullLibraryTile: FullLibraryTile | None = None
        self._full_library_tile_covers: list[str] = []
        self._full_library_tile_pixmaps: dict[int, QPixmap] = {}
        self.full_library_open = False
        self.sizeSlider: QSlider | None = None
        self._update_timer: QTimer | None = None
        self._incremental_add_timer: QTimer | None = None
        self._incremental_add_queue: deque[tuple[str, str]] = deque()
        self._incremental_new_games_map: dict[tuple[str, str], tuple] = {}
        self._incremental_search_text: str = ""
        self._incremental_batch_size: int = 16
        self._focus_first_card_after_update = False
        self._pending_update = False
        self.pending_deletions = deque()
        self.is_filtering = False
        self.dirty = False
        # Initialize search optimizer
        self.search_optimizer = SearchOptimizer()
        self.search_thread: ThreadedSearch | None = None

    def create_games_library_widget(self):
        """Creates the games library widget with search, grid, and slider."""
        self.gamesLibraryWidget = QWidget()
        self.gamesLibraryWidget.setProperty("theme_style_name", "LIBRARY_WIDGET_STYLE")
        self.gamesLibraryWidget.setStyleSheet(self.theme.LIBRARY_WIDGET_STYLE)
        library_background = getattr(self.theme, "LIBRARY_BACKGROUND", None)
        if isinstance(library_background, dict):
            stack_layout = QGridLayout(self.gamesLibraryWidget)
            stack_layout.setContentsMargins(*library_background["margins"])
            self.libraryBackgroundLabel = QLabel()
            stack_layout.addWidget(self.libraryBackgroundLabel, 0, 0)
            content_widget = QWidget()
            content_widget.setStyleSheet(self.theme.TRANSPARENT_BACKGROUND_STYLE)
            layout = QVBoxLayout(content_widget)
            stack_layout.addWidget(content_widget, 0, 0)
        else:
            layout = QVBoxLayout(self.gamesLibraryWidget)
        self.libraryContentLayout = layout
        layout.setSpacing(15)

        # Search widget
        searchWidget, self.searchEdit = self.main_window.createSearchWidget()
        layout.addWidget(searchWidget)

        if self.layout_mode == "vertical":
            self.libraryHeaderWidget = self._create_library_header()
            layout.addWidget(self.libraryHeaderWidget)

        # Scroll area for game grid
        scrollArea = AutoHideScrollArea(theme=self.theme)
        scrollArea.setProperty("theme_style_name", "TRANSPARENT_BACKGROUND_STYLE")
        self.gamesScrollArea = scrollArea
        scrollArea.setWidgetResizable(True)
        QScroller.grabGesture(scrollArea.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)

        self.gamesListWidget = QWidget()
        self.gamesListWidget.setProperty("library_layout_mode", self.layout_mode)
        self.gamesListWidget.setProperty("theme_style_name", "LIST_WIDGET_STYLE")
        self.gamesListWidget.setStyleSheet(self.theme.LIST_WIDGET_STYLE)
        if self.layout_mode in {"horizontal", "horizontal_top"}:
            layout_config = self.theme.GAME_CARD_HORIZONTAL
            self.gamesListLayout = QHBoxLayout(self.gamesListWidget)
            self.gamesListLayout.setContentsMargins(*layout_config["layout_margins"])
            self.gamesListLayout.setSpacing(layout_config["layout_spacing"])
            scrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        elif self.layout_mode == "vertical":
            layout_config = self.theme.GAME_CARD_VERTICAL
            self.gamesListLayout = QVBoxLayout(self.gamesListWidget)
            self.gamesListLayout.setContentsMargins(
                *layout_config.get("layout_margins", (0, 0, 0, 0))
            )
            self.gamesListLayout.setSpacing(layout_config.get("layout_spacing", 0))
        else:
            self.gamesListLayout = FlowLayout(self.gamesListWidget)
        self.gamesListWidget.setLayout(self.gamesListLayout)

        scrollArea.setWidget(self.gamesListWidget)
        layout.addWidget(scrollArea)

        # Slider for card size
        sliderLayout = QHBoxLayout()
        sliderLayout.addStretch()

        self.sizeSlider = QSlider(Qt.Orientation.Horizontal)
        self.sizeSlider.setMinimum(100)
        self.sizeSlider.setMaximum(250)
        self.sizeSlider.setValue(self.card_width)
        self.sizeSlider.setTickInterval(10)
        self.sizeSlider.setFixedWidth(150)
        self.sizeSlider.setStyleSheet(self.theme.SLIDER_SIZE_STYLE)
        if hasattr(self.main_window, "_register_gamepad_tooltip"):
            self.main_window._register_gamepad_tooltip(self.sizeSlider, f"{self.card_width} px")
        self.sizeSlider.sliderReleased.connect(self.main_window.on_slider_released)
        sliderLayout.addWidget(self.sizeSlider)
        if self.layout_mode in {"list", "vertical", "horizontal", "horizontal_top"}:
            self.sizeSlider.setVisible(False)
        self._set_card_width_from_slider()

        layout.addLayout(sliderLayout)

        # Initialize update timer
        self._update_timer = QTimer()
        self._update_timer.setSingleShot(True)
        self._update_timer.setInterval(100)  # 100ms debounce
        self._update_timer.timeout.connect(self._perform_update)
        self._incremental_add_timer = QTimer()
        self._incremental_add_timer.setSingleShot(True)
        self._incremental_add_timer.timeout.connect(self._process_incremental_add_batch)

        # Connect scroll event for lazy loading
        scrollArea.verticalScrollBar().valueChanged.connect(self.load_visible_images)
        scrollArea.horizontalScrollBar().valueChanged.connect(self.load_visible_images)

        return self.gamesLibraryWidget

    def _create_library_header(self) -> QWidget:
        """Create the shared header for vertical library columns."""
        config = self.theme.GAME_CARD_VERTICAL
        header = QWidget()
        header.setFixedHeight(config["header_height"])
        header.setProperty("theme_style_name", "LIBRARY_HEADER_STYLE")
        header.setStyleSheet(self.theme.LIBRARY_HEADER_STYLE)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(*config["header_margins"])
        header_layout.setSpacing(config["header_spacing"])
        header_layout.addSpacing(config["header_cover_width"])
        labels = (_("Game Title"), _("LAST LAUNCH"), _("TIME SPENT"), _("Library"))
        for text, stretch in zip(labels, config["column_stretches"], strict=True):
            label = QLabel(text)
            label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            label.setProperty("theme_style_name", "LIBRARY_HEADER_LABEL_STYLE")
            label.setStyleSheet(self.theme.LIBRARY_HEADER_LABEL_STYLE)
            header_layout.addWidget(label, stretch)
        return header

    def rebuild_library_layout(self, layout_mode: str) -> None:
        """Replace the card layout when a theme changes its library mode."""
        if self.gamesListWidget is None or self.gamesListLayout is None:
            return
        self.clear_layout(self.gamesListLayout)
        self.fullLibraryTile = None
        old_layout = self.gamesListLayout
        if layout_mode in {"horizontal", "horizontal_top"}:
            layout_config = self.theme.GAME_CARD_HORIZONTAL
            self.gamesListLayout = QHBoxLayout()
            self.gamesListLayout.setContentsMargins(*layout_config["layout_margins"])
            self.gamesListLayout.setSpacing(layout_config["layout_spacing"])
        elif layout_mode == "vertical":
            layout_config = self.theme.GAME_CARD_VERTICAL
            self.gamesListLayout = QVBoxLayout()
            self.gamesListLayout.setContentsMargins(
                *layout_config.get("layout_margins", (0, 0, 0, 0))
            )
            self.gamesListLayout.setSpacing(layout_config.get("layout_spacing", 0))
        else:
            self.gamesListLayout = FlowLayout()
        QWidget().setLayout(old_layout)
        self.gamesListWidget.setLayout(self.gamesListLayout)
        if self.gamesScrollArea is not None:
            horizontal = layout_mode in {"horizontal", "horizontal_top"}
            vertical_policy = (
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
                if horizontal
                else Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )
            self.gamesScrollArea.setVerticalScrollBarPolicy(vertical_policy)
        theme_mode = str(getattr(self.theme, "LIBRARY_LAYOUT_MODE", "grid")).lower()
        self.full_library_open = theme_mode == "horizontal_top" and layout_mode == "grid"
        if self.full_library_open and self.libraryBackgroundLabel is not None:
            remove_cover_background(self.libraryBackgroundLabel)
        self.layout_mode = layout_mode
        if (
            layout_mode == "vertical"
            and self.libraryHeaderWidget is None
            and self.libraryContentLayout is not None
        ):
            self.libraryHeaderWidget = self._create_library_header()
            self.libraryContentLayout.insertWidget(1, self.libraryHeaderWidget)
        if self.libraryHeaderWidget is not None:
            self.libraryHeaderWidget.setVisible(layout_mode == "vertical")
        self.gamesListWidget.setProperty("library_layout_mode", layout_mode)
        if self.sizeSlider is not None:
            self.sizeSlider.setVisible(
                not self.full_library_open
                and layout_mode not in {"list", "vertical", "horizontal", "horizontal_top"}
            )
            self._set_card_width_from_slider()
            self.main_window.card_width = self.card_width
        self.set_games(self.games, focus_first_card=False)

    def open_full_library(self) -> None:
        """Open the complete grid from the horizontal top mode."""
        if self.layout_mode == "horizontal_top":
            self.rebuild_library_layout("grid")

    def close_full_library(self) -> bool:
        """Return from the complete grid to the horizontal top mode."""
        if not self.full_library_open:
            return False
        self.full_library_open = False
        self.rebuild_library_layout("horizontal_top")
        return True

    def on_slider_released(self):
        """Handles slider release to update card size."""
        if self.full_library_open or self.layout_mode in {
            "list", "vertical", "horizontal", "horizontal_top"
        }:
            return
        if self.sizeSlider is None:
            return
        self._set_card_width_from_slider()
        if hasattr(self.main_window, "_gamepad_tooltip_map"):
            self.main_window._gamepad_tooltip_map[self.sizeSlider] = f"{self.card_width} px"
        ui_config.set_card_width(self.card_width)
        self.main_window.card_width = self.card_width
        for card in self.game_card_cache.values():
            card.update_card_size(self.card_width)
        self.update_game_grid()

    def _set_card_width_from_slider(self):
        """Use max card width for fixed-size layouts."""
        if self.sizeSlider is None:
            return
        if self.full_library_open or self.layout_mode in {
            "list", "vertical", "horizontal", "horizontal_top"
        }:
            self.card_width = self.sizeSlider.maximum()
        else:
            self.card_width = self.sizeSlider.value()
        self.sizeSlider.setValue(self.card_width)

    def load_visible_images(self):
        """Loads images for visible game cards."""
        if self.gamesListWidget is None:
            return
        visible_region = self.gamesListWidget.visibleRegion()
        max_concurrent_loads = 5
        loaded_count = 0
        for card_key, card in self.game_card_cache.items():
            is_visible = self._is_card_in_view(card, visible_region)
            card.set_animated_cover_paused(not is_visible)
            if card_key in self.pending_images and is_visible and loaded_count < max_concurrent_loads:
                cover_path, width, height, callback = self.pending_images.pop(card_key)
                load_pixmap_async(cover_path, width, height, callback)
                loaded_count += 1

    @staticmethod
    def _is_card_in_view(card: GameCard, visible_region: QRegion) -> bool:
        if not card.isVisible():
            return False
        return visible_region.intersects(card.geometry())

    def _pause_all_animated_covers(self) -> None:
        for card in self.game_card_cache.values():
            card.set_animated_cover_paused(True)

    def stop_background_activity(self) -> None:
        for card in self.game_card_cache.values():
            card.stop_background_activity()

    def _on_card_focused(self, game_name: str, is_focused: bool):
        """Handles card focus events."""
        card_key = None
        for key, card in self.game_card_cache.items():
            if card.name == game_name:
                card_key = key
                break

        if not card_key:
            return

        card = self.game_card_cache[card_key]

        if is_focused:
            self._collapse_library_filter_controls()
            if self.main_window.current_hovered_card and self.main_window.current_hovered_card != card:
                try:
                    self.main_window.current_hovered_card._hovered = False
                    self.main_window.current_hovered_card.animations.handle_leave_event()
                except RuntimeError:
                    pass  # Card already deleted
                self.main_window.current_hovered_card = None
            if self.main_window.current_focused_card and self.main_window.current_focused_card != card:
                try:
                    self.main_window.current_focused_card._focused = False
                    self.main_window.current_focused_card.clearFocus()
                except RuntimeError:
                    pass  # Card already deleted
            self.main_window.current_focused_card = card
            self._update_library_background(card)
        else:
            if self.main_window.current_focused_card == card:
                self.main_window.current_focused_card = None

    def _update_library_background(self, card: GameCard) -> None:
        """Render the configured library background from the active cover."""
        if self.full_library_open or self.libraryBackgroundLabel is None:
            return
        pixmap = card.coverLabel.pixmap()
        if pixmap is None or pixmap.isNull():
            return
        library_config = self.theme.LIBRARY_BACKGROUND
        backgrounds = dict(getattr(self.theme, "DETAIL_PAGE_BACKGROUNDS", {}))
        backgrounds.update(library_config.get("backgrounds", {}))
        background_theme = SimpleNamespace(
            DETAIL_PAGE_BG_MODE=library_config.get("mode", "gradient"),
            DETAIL_PAGE_BACKGROUNDS=backgrounds,
        )
        setup_cover_background(
            self.libraryBackgroundLabel, pixmap, self.main_window, background_theme
        )

    def _collapse_library_filter_controls(self) -> None:
        if getattr(self.main_window, "_library_controls_hover_close_delayed", False):
            return
        controls_button = getattr(self.main_window, "libraryControlsButton", None)
        if not isinstance(controls_button, QAbstractButton) or not controls_button.isChecked():
            return
        controls_button.setChecked(False)
        toggle_controls = getattr(self.main_window, "_toggle_library_controls", None)
        if callable(toggle_controls):
            toggle_controls()

    def _on_card_hovered(self, game_name: str, is_hovered: bool):
        """Handles card hover events."""
        card_key = None
        for key, card in self.game_card_cache.items():
            if card.name == game_name:
                card_key = key
                break

        if not card_key:
            return

        card = self.game_card_cache[card_key]

        if is_hovered:
            self._collapse_library_filter_controls()
            if self.main_window.current_focused_card and self.main_window.current_focused_card != card:
                try:
                    if self.main_window.current_focused_card:
                        self.main_window.current_focused_card._focused = False
                        self.main_window.current_focused_card.clearFocus()
                except RuntimeError:
                    pass  # Card already deleted
            if self.main_window.current_hovered_card and self.main_window.current_hovered_card != card:
                try:
                    if self.main_window.current_hovered_card:
                        self.main_window.current_hovered_card._hovered = False
                        self.main_window.current_hovered_card.animations.handle_leave_event()
                except RuntimeError:
                    pass  # Card already deleted
            self.main_window.current_hovered_card = card
            self._update_library_background(card)
        else:
            if self.main_window.current_hovered_card == card:
                self.main_window.current_hovered_card = None

    def _perform_update(self):
        """Performs the actual grid update."""
        if not self._pending_update:
            return
        self._pending_update = False
        self._update_game_grid_immediate()

    def update_game_grid(
        self,
        games_list: list[tuple] | None = None,
        is_filter: bool = False,
        focus_first_card: bool | None = None,
    ):
        """Schedules a game grid update with debouncing."""
        if focus_first_card is not None:
            self._focus_first_card_after_update = focus_first_card
        theme_mode = str(getattr(self.theme, "LIBRARY_LAYOUT_MODE", "grid")).lower()
        if not self.full_library_open:
            self.layout_mode = theme_mode
        if self.sizeSlider is not None:
            self.sizeSlider.setVisible(
                not self.full_library_open
                and self.layout_mode not in {"list", "vertical", "horizontal", "horizontal_top"}
            )
            old_card_width = self.card_width
            self._set_card_width_from_slider()
            self.main_window.card_width = self.card_width
            if old_card_width != self.card_width:
                for card in self.game_card_cache.values():
                    card.update_card_size(self.card_width)
        if not is_filter:
            if games_list is not None:
                self.filtered_games = games_list
            self.dirty = True  # Full rebuild only for non-filter
        else:
            # When filtering, we want to update with the current filtered_games
            # which has already been set by _perform_search
            pass
        if is_filter and self.layout_mode == "horizontal_top":
            self.dirty = True
            is_filter = False
        self.is_filtering = is_filter
        self._pending_update = True

        if self._update_timer is not None:
            self._update_timer.start()
        else:
            self._update_game_grid_immediate()

    def force_update_cards_library(self):
        if self.gamesListWidget and self.gamesListLayout:
            # Use singleShot to ensure UI updates happen after all other operations complete
            # This prevents potential freezing in PySide 6.10.1
            QTimer.singleShot(0, self._perform_force_update)

    def _perform_force_update(self):
        """Perform the actual force update on the layout."""
        if self.gamesListLayout:
            self.gamesListLayout.invalidate()
        if self.gamesListWidget:
            self.gamesListWidget.adjustSize()
            self.gamesListWidget.updateGeometry()

    def _cancel_incremental_add(self) -> None:
        if self._incremental_add_timer is not None and self._incremental_add_timer.isActive():
            self._incremental_add_timer.stop()
        self._incremental_add_queue.clear()
        self._incremental_new_games_map = {}
        self._incremental_search_text = ""

    def _start_incremental_add(
        self,
        card_order: list[tuple[str, str]],
        new_games_map: dict[tuple[str, str], tuple],
        search_text: str
    ) -> None:
        if self.gamesListLayout is None:
            return
        self._cancel_incremental_add()
        while self.gamesListLayout.count():
            self.gamesListLayout.takeAt(0)
        for card in self.game_card_cache.values():
            if card.isVisible():
                card.setVisible(False)
        self._incremental_add_queue = deque(card_order)
        self._incremental_new_games_map = new_games_map
        self._incremental_search_text = search_text
        if self._incremental_add_timer is not None:
            self._incremental_add_timer.start(0)

    def _process_incremental_add_batch(self) -> None:
        if self.gamesListLayout is None or self.gamesListWidget is None:
            self._cancel_incremental_add()
            return

        added_new_card = False
        processed = 0
        max_batch = min(self._incremental_batch_size, len(self._incremental_add_queue))
        self.gamesListWidget.setUpdatesEnabled(False)
        try:
            while processed < max_batch:
                game_key = self._incremental_add_queue.popleft()
                card = self.game_card_cache.get(game_key)
                if card is None:
                    if self.context_menu_manager is None:
                        processed += 1
                        continue
                    game_data = self._incremental_new_games_map.get(game_key)
                    if game_data is None:
                        processed += 1
                        continue
                    card = self._create_game_card(game_data)
                    self.game_card_cache[game_key] = card
                    added_new_card = True
                should_be_visible = (
                    not self._incremental_search_text or
                    self._incremental_search_text in str(game_key[0]).lower()
                )
                if card.isVisible() != should_be_visible:
                    card.setVisible(should_be_visible)
                    card.set_animated_cover_paused(not should_be_visible)
                self.gamesListLayout.addWidget(card)
                processed += 1
        finally:
            self.gamesListWidget.setUpdatesEnabled(True)
            self.gamesListLayout.update()
            self.gamesListWidget.updateGeometry()

        if self._incremental_add_queue:
            if self._incremental_add_timer is not None:
                self._incremental_add_timer.start(0)
            return

        if added_new_card:
            self.load_visible_images()
        self._sync_full_library_tile()
        self.force_update_cards_library()
        self._cancel_incremental_add()
        self._schedule_focus_first_card()

    def _update_game_grid_immediate(self):
        """Updates the game grid with the provided or current game list."""
        if self.gamesListLayout is None or self.gamesListWidget is None:
            return
        self._cancel_incremental_add()

        search_text = self.main_window.searchEdit.text().strip().lower()

        if self.is_filtering:
            # Filter mode: use the pre-computed filtered_games from optimized search
            # This means we already have the exact games to show
            self._update_search_results(search_text)
        else:
            # Full update: sorting, removal/addition, reorganization
            games_list = self.filtered_games
            if self.layout_mode != "horizontal_top" and not games_list:
                games_list = self.games
            favorites = favorites_config.get_games()
            sort_method = game_config.get_sort_method()

            # Batch layout updates (extended scope)
            self.gamesListWidget.setUpdatesEnabled(False)
            if self.gamesListLayout is not None:
                self.gamesListLayout.setEnabled(False)  # Disable layout during batch

            try:
                # Optimized sorting: Partition favorites first, then sort subgroups
                def partition_sort_key(game):
                    name = game[0]
                    is_fav = name in favorites
                    fav_order = 0 if is_fav else 1
                    if sort_method == "playtime":
                        return (fav_order, -game[11] if game[11] else 0, -game[10] if game[10] else 0)
                    elif sort_method == "alphabetical":
                        return (fav_order, name.lower())
                    else:
                        return (fav_order, -game[10] if game[10] else 0, -game[11] if game[11] else 0)

                # Quick partition: Sort favorites and non-favorites separately, then merge
                favorites_set = set(favorites)  # Convert to set for O(1) lookup
                fav_games = [g for g in games_list if g[0] in favorites_set]
                non_fav_games = [g for g in games_list if g[0] not in favorites_set]
                sorted_fav = sorted(fav_games, key=partition_sort_key)
                sorted_non_fav = sorted(non_fav_games, key=partition_sort_key)
                sorted_games = sorted_fav + sorted_non_fav
                if self.layout_mode == "horizontal_top":
                    limit = self.theme.horizontalTopGameLimit
                    tile_games = sorted_games[limit:limit + self.theme.fullLibraryTileGameCount]
                    self._full_library_tile_covers = [str(game[2] or "") for game in tile_games]
                    sorted_games = sorted_games[:limit]
                else:
                    self._full_library_tile_covers = []

                # Build set of current game keys for faster lookup
                current_game_keys = {(game[0], game[5]) for game in sorted_games}

                # Remove cards that no longer exist (batch)
                cards_to_remove = []
                for card_key in list(self.game_card_cache.keys()):
                    if card_key not in current_game_keys:
                        cards_to_remove.append(card_key)

                for card_key in cards_to_remove:
                    card = self.game_card_cache.pop(card_key)
                    if self.gamesListLayout is not None:
                        self.gamesListLayout.removeWidget(card)
                    self.pending_deletions.append(card)  # Defer
                    if card_key in self.pending_images:
                        del self.pending_images[card_key]

                # Track current layout order (only if dirty/full update needed)
                if self.dirty and self.gamesListLayout is not None:
                    current_layout_order = []
                    for i in range(self.gamesListLayout.count()):
                        item = self.gamesListLayout.itemAt(i)
                        if item is not None:
                            widget = item.widget()
                            if widget:
                                for key, card in self.game_card_cache.items():
                                    if card == widget:
                                        current_layout_order.append(key)
                                        break
                else:
                    current_layout_order = None  # Skip reorg if not dirty

                new_card_order = []
                new_games_map: dict[tuple[str, str], tuple] = {}
                has_new_cards = False

                for game_data in sorted_games:
                    game_name = game_data[0]
                    exec_line = game_data[5]
                    game_key = (game_name, exec_line)
                    should_be_visible = not search_text or search_text in game_name.lower()

                    if game_key in self.game_card_cache:
                        card = self.game_card_cache[game_key]
                        if card.isVisible() != should_be_visible:
                            card.setVisible(should_be_visible)
                            card.set_animated_cover_paused(not should_be_visible)
                        new_card_order.append(game_key)
                    else:
                        new_games_map[game_key] = game_data
                        new_card_order.append(game_key)

                # Only reorganize if order changed AND dirty
                if self.dirty and self.gamesListLayout is not None and (current_layout_order is None or new_card_order != current_layout_order):
                    self._start_incremental_add(new_card_order, new_games_map, search_text)
                else:
                    for game_key in new_card_order:
                        if game_key in self.game_card_cache:
                            continue
                        if self.context_menu_manager is None:
                            continue
                        game_data = new_games_map.get(game_key)
                        if game_data is None:
                            continue
                        card = self._create_game_card(game_data)
                        self.game_card_cache[game_key] = card
                        card.setVisible(not search_text or search_text in str(game_key[0]).lower())
                        card.set_animated_cover_paused(not card.isVisible())
                        self.gamesListLayout.addWidget(card)
                        has_new_cards = True

                self.dirty = False  # Reset flag

                # Deferred deletions (run in timer to avoid stack overflow)
                if self.pending_deletions:
                    QTimer.singleShot(0, lambda: self._flush_deletions())

                # Load visible images for new cards only
                if has_new_cards:
                    self.load_visible_images()

            finally:
                if self.gamesListLayout is not None:
                    self.gamesListLayout.setEnabled(True)
                self.gamesListWidget.setUpdatesEnabled(True)
                if self.gamesListLayout is not None:
                    self.gamesListLayout.update()
                self.gamesListWidget.updateGeometry()
                self.force_update_cards_library()

        self.is_filtering = False  # Reset flag in any case
        if not self._incremental_add_queue:
            self._sync_full_library_tile()
        self._schedule_focus_first_card()

    def _sync_full_library_tile(self) -> None:
        if self.fullLibraryTile is not None:
            self.fullLibraryTile.setParent(None)
            self.fullLibraryTile.deleteLater()
            self.fullLibraryTile = None
        if self.layout_mode != "horizontal_top" or self.gamesListLayout is None:
            return
        if len(self.filtered_games) <= self.theme.horizontalTopGameLimit:
            return
        tile = FullLibraryTile(self.theme)
        tile.setProperty("full_library_tile", True)
        tile.setStyleSheet(self.theme.FULL_LIBRARY_TILE_STYLE)
        tile.clicked.connect(self.open_full_library)
        self.gamesListLayout.addWidget(tile)
        self.fullLibraryTile = tile
        self._full_library_tile_pixmaps = {}
        cover_width, cover_height = self.theme.fullLibraryTileSize
        for index, cover_path in enumerate(self._full_library_tile_covers):
            load_pixmap_async(
                cover_path,
                cover_width,
                cover_height,
                lambda pixmap, item=index: self._set_full_library_tile_cover(
                    tile, item, pixmap
                ),
            )

    def _set_full_library_tile_cover(
        self, tile: FullLibraryTile, index: int, pixmap: QPixmap
    ) -> None:
        if tile is not self.fullLibraryTile:
            return
        self._full_library_tile_pixmaps[index] = pixmap
        width, height = self.theme.fullLibraryTileSize
        cell_width = width // self.theme.fullLibraryTileColumns
        cell_height = height // self.theme.fullLibraryTileRows
        canvas = QPixmap(width, height)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(
            QRectF(canvas.rect()),
            self.theme.fullLibraryTileRadius,
            self.theme.fullLibraryTileRadius,
        )
        painter.setClipPath(clip)
        for item, cover in self._full_library_tile_pixmaps.items():
            cell = QRect(
                item % self.theme.fullLibraryTileColumns * cell_width,
                item // self.theme.fullLibraryTileColumns * cell_height,
                cell_width,
                cell_height,
            )
            painter.drawPixmap(cell, cover)
        painter.end()
        tile.set_tile_pixmap(canvas)

    def _schedule_focus_first_card(self) -> None:
        if not self._focus_first_card_after_update:
            return
        QTimer.singleShot(0, self._focus_first_visible_card)

    def _focus_first_visible_card(self) -> None:
        if self.gamesListWidget is None:
            return
        if getattr(self.main_window.stackedWidget, "currentIndex", lambda: -1)() != 0:
            return
        for card in self.gamesListWidget.findChildren(GameCard):
            if card.isVisible() and card.isEnabled():
                self._focus_first_card_after_update = False
                card.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
                if self.gamesScrollArea is not None:
                    self.gamesScrollArea.ensureWidgetVisible(card, 50, 50)
                return

    def _update_search_results(self, search_text: str = ""):
        """Update the grid with pre-computed search results."""
        if self.gamesListLayout is None or self.gamesListWidget is None:
            return

        # Batch layout updates
        self.gamesListWidget.setUpdatesEnabled(False)
        if self.gamesListLayout is not None:
            self.gamesListLayout.setEnabled(False)  # Disable layout during batch

        try:
            # Create set of keys for current filtered games for fast lookup
            filtered_keys = {(game[0], game[5]) for game in self.filtered_games}  # (name, exec_line)

            # Process existing cards: show cards that are in filtered results, hide others
            cards_to_hide = []
            for card_key, card in self.game_card_cache.items():
                if card_key in filtered_keys:
                    # Card should be visible
                    if not card.isVisible():
                        card.setVisible(True)
                    card.set_animated_cover_paused(False)
                else:
                    # Card should be hidden
                    if card.isVisible():
                        card.setVisible(False)
                        cards_to_hide.append(card_key)
                    card.set_animated_cover_paused(True)

            # Now add any missing cards that are in filtered results but not in cache
            cards_to_add = []
            for game_data in self.filtered_games:
                game_name = game_data[0]
                exec_line = game_data[5]
                game_key = (game_name, exec_line)

                if game_key not in self.game_card_cache:
                    if self.context_menu_manager is None:
                        continue

                    card = self._create_game_card(game_data)
                    self.game_card_cache[game_key] = card
                    card.setVisible(True)  # New cards should be visible
                    card.set_animated_cover_paused(False)
                    cards_to_add.append((game_key, card))

            # Add new cards to layout
            for _game_key, card in cards_to_add:
                self.gamesListLayout.addWidget(card)

            # Remove cards that are no longer needed (if any)
            # Note: we're not removing them completely as they might be needed later
            # Instead, we just hide them and they'll be reused if needed

        finally:
            if self.gamesListLayout is not None:
                self.gamesListLayout.setEnabled(True)
            self.gamesListWidget.setUpdatesEnabled(True)
            if self.gamesListLayout is not None:
                self.gamesListLayout.update()
            self.gamesListWidget.updateGeometry()

            self.force_update_cards_library()

            self.gamesListLayout.update()
        if self.gamesListWidget is not None:
            self.gamesListWidget.updateGeometry()

        # If search is empty, load images for visible ones
        if not search_text:
            self.load_visible_images()
        else:
            QTimer.singleShot(0, self.load_visible_images)

    def _create_game_card(self, game_data: tuple) -> GameCard:
        """Creates a new game card with all necessary connections."""
        card = GameCard(
            *game_data,
            select_callback=self.main_window.openGameDetailPage,
            theme=self.theme,
            card_width=self.card_width,
            parent=self.gamesListWidget,
            context_menu_manager=self.context_menu_manager
        )

        card.hoverChanged.connect(self._on_card_hovered)
        card.focusChanged.connect(self._on_card_focused)

        if self.context_menu_manager:
            card.editShortcutRequested.connect(self.context_menu_manager.edit_game_shortcut)
            card.deleteGameRequested.connect(self.context_menu_manager.delete_game)
            card.addToMenuRequested.connect(self.context_menu_manager.add_to_menu)
            card.removeFromMenuRequested.connect(self.context_menu_manager.remove_from_menu)
            card.addToDesktopRequested.connect(self.context_menu_manager.add_to_desktop)
            card.removeFromDesktopRequested.connect(self.context_menu_manager.remove_from_desktop)
            card.addToSteamRequested.connect(self.context_menu_manager.add_to_steam)
            card.removeFromSteamRequested.connect(self.context_menu_manager.remove_from_steam)
            card.openGameFolderRequested.connect(self.context_menu_manager.open_game_folder)

        return card

    def _flush_deletions(self):
        """Delete pending widgets off the main update cycle."""
        for card in list(self.pending_deletions):
            # Clear any references to this card if it's currently focused/hovered
            if self.main_window.current_focused_card == card:
                self.main_window.current_focused_card = None
            if self.main_window.current_hovered_card == card:
                self.main_window.current_hovered_card = None
            card.cleanup()
            card.deleteLater()
            self.pending_deletions.remove(card)

    def clear_layout(self, layout):
        """Clears all widgets from the layout."""
        if layout is None:
            return
        self._cancel_incremental_add()
        # Remove all widgets from the layout and clean up caches
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                widget = child.widget()
                # Clean up cache if widget exists in it
                for key, card in list(self.game_card_cache.items()):
                    if card == widget:
                        del self.game_card_cache[key]
                        if key in self.pending_images:
                            del self.pending_images[key]
                        break
                # Always schedule widget for deletion regardless of cache state
                if isinstance(widget, GameCard):
                    widget.cleanup()
                widget.deleteLater()

        # Also clear the cache completely if needed (in case layout wasn't in sync)
        self.game_card_cache.clear()
        self.pending_images.clear()

    def set_games(self, games: list[tuple], focus_first_card: bool = True):
        """Sets the games list and updates the filtered games."""
        self.games = games
        self.filtered_games = self.games
        self._focus_first_card_after_update = bool(games) and focus_first_card

        # Build search indices for fast searching
        self._build_search_indices(games)

        self.dirty = True  # Full resort needed
        self._pending_update = True
        if self._update_timer is not None:
            if self._update_timer.isActive():
                self._update_timer.stop()
            # Run at the next event loop tick without blocking current UI work.
            self._update_timer.start(0)
        else:
            self._update_game_grid_immediate()
        self._update_missing_exe_button()

    def _build_search_indices(self, games: list[tuple]):
        """Build search indices for fast searching."""
        self.search_optimizer.build_indices(
            build_search_items(
                games,
                lambda game: game[0],
            )
        )

    def _update_missing_exe_button(self) -> None:
        update_button = getattr(self.main_window, "updateDeleteMissingExeButton", None)
        if callable(update_button):
            update_button()

    def add_game_incremental(self, game_data: tuple):
        """Add a single game without full reload."""
        self.games.append(game_data)
        self.filtered_games.append(game_data)  # Assume no filter active; adjust if needed
        self.dirty = True
        self.update_game_grid()
        self._update_missing_exe_button()

    def replace_game_incremental(self, old_name: str, old_exec_line: str, game_data: tuple):
        """Replace a single game without full reload."""
        old_key = (old_name, old_exec_line)
        new_key = (game_data[0], game_data[5])
        self.games = [game_data if (g[0], g[5]) == old_key else g for g in self.games]
        self.filtered_games = [
            game_data if (g[0], g[5]) == old_key else g for g in self.filtered_games
        ]
        if old_key in self.game_card_cache and self.gamesListLayout is not None:
            card = self.game_card_cache.pop(old_key)
            self.gamesListLayout.removeWidget(card)
            card.cleanup()
            self.pending_deletions.append(card)
            if old_key in self.pending_images:
                del self.pending_images[old_key]
        if new_key not in self.game_card_cache and game_data not in self.games:
            self.games.append(game_data)
            self.filtered_games.append(game_data)
        self.dirty = True
        self.update_game_grid()
        self._update_missing_exe_button()

    def remove_game_incremental(self, game_name: str, exec_line: str):
        """Remove a single game without full reload."""
        key = (game_name, exec_line)
        self.games = [g for g in self.games if (g[0], g[5]) != key]
        self.filtered_games = [g for g in self.filtered_games if (g[0], g[5]) != key]
        if key in self.game_card_cache and self.gamesListLayout is not None:
            card = self.game_card_cache.pop(key)
            self.gamesListLayout.removeWidget(card)
            card.cleanup()
            self.pending_deletions.append(card)  # Defer deleteLater
            if key in self.pending_images:
                del self.pending_images[key]
        self.dirty = True
        self.update_game_grid()
        self._update_missing_exe_button()

    def filter_games_delayed(self):
        """Filters games based on search text and updates the grid."""
        search_text = self.main_window.searchEdit.text().strip().lower()

        if not search_text:
            # If search is empty, show all games
            self.filtered_games = self.games
            self.update_game_grid(is_filter=True)
        else:
            # Use the optimized search
            self._perform_search(search_text)

    def _perform_search(self, search_text: str):
        """Perform the actual search using optimized search algorithms."""
        if not search_text:
            self.filtered_games = self.games
            self.update_game_grid(is_filter=True)
            return

        self.filtered_games = search_index(self.search_optimizer, search_text)
        self.update_game_grid(is_filter=True)
