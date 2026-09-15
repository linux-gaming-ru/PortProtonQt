from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScroller,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from portprotonqt.animations import ExpandingSearchAnimation
from portprotonqt.config import ui_config
from portprotonqt.context_menu_manager import CustomLineEdit
from portprotonqt.custom_widgets import AutoHideScrollArea, AutoSizeButton, FlowLayout
from portprotonqt.game_card import GameCard
from portprotonqt.localization import _
from portprotonqt.logger import get_logger
from portprotonqt.search_utils import SearchOptimizer, build_search_items, search_index

logger = get_logger(__name__)

if TYPE_CHECKING:
    from PySide6.QtWidgets import QMainWindow

    _MainWindowTypingBase = QMainWindow
else:
    _MainWindowTypingBase = object


class MainWindowAutoInstallTabMixin(_MainWindowTypingBase):
    if TYPE_CHECKING:
        autoInstallCustomDataThread: Any

        def __getattr__(self, name: str) -> Any: ...

    def createAutoInstallTab(self):
        autoInstallPage = QWidget()
        autoInstallPage.setProperty("theme_style_name", "LIBRARY_WIDGET_STYLE")
        autoInstallPage.setStyleSheet(self.theme.LIBRARY_WIDGET_STYLE)
        library_background = getattr(self.theme, "LIBRARY_BACKGROUND", None)
        stack_layout = QGridLayout(autoInstallPage)
        if isinstance(library_background, dict):
            stack_layout.setContentsMargins(*library_background["margins"])
        else:
            stack_layout.setContentsMargins(0, 0, 0, 0)
        self.autoInstallBackgroundLabel = QLabel()
        stack_layout.addWidget(self.autoInstallBackgroundLabel, 0, 0)
        content_widget = QWidget()
        content_widget.setStyleSheet(self.theme.TRANSPARENT_BACKGROUND_STYLE)
        autoInstallLayout = QVBoxLayout(content_widget)
        stack_layout.addWidget(content_widget, 0, 0)
        autoInstallLayout.setSpacing(15)

        searchWidget = QWidget()
        searchWidget.setStyleSheet(self.theme.CONTAINER_STYLE)
        searchLayout = QHBoxLayout(searchWidget)
        searchLayout.setContentsMargins(0, 6, 0, 0)
        searchLayout.setSpacing(10)
        searchLayout.addStretch()

        self.autoInstallSearchLineEdit = CustomLineEdit(self, theme=self.theme)
        icon: QIcon = cast(QIcon, self.theme_manager.get_icon("search"))
        action_pos = QLineEdit.ActionPosition.LeadingPosition
        self.autoInstallSearchIconAction = self.autoInstallSearchLineEdit.addAction(icon, action_pos)
        self.autoInstallSearchLineEdit.setMaximumWidth(200)
        self.autoInstallSearchLineEdit.setPlaceholderText(_("Search…"))
        self.autoInstallSearchLineEdit.setClearButtonEnabled(True)
        self.autoInstallSearchLineEdit.setStyleSheet(self.theme.SEARCH_EDIT_STYLE)
        self.autoInstallSearchLineEdit.textChanged.connect(self.filterAutoInstallGames)
        self.autoInstallSearchLineEdit.focusInEvent = self._wrap_autoinstall_search_focus_event(
            self.autoInstallSearchLineEdit.focusInEvent,
            True,
        )
        self.autoInstallSearchLineEdit.focusOutEvent = self._wrap_autoinstall_search_focus_event(
            self.autoInstallSearchLineEdit.focusOutEvent,
            False,
        )
        self.autoInstallSearchLineEdit.resizeEvent = self._wrap_autoinstall_search_resize_event(
            self.autoInstallSearchLineEdit.resizeEvent
        )
        searchLayout.addWidget(self.autoInstallSearchLineEdit)

        self.autoInstallRefreshButton = AutoSizeButton(icon=self.theme_manager.get_icon("update", as_path=True))
        self.autoInstallRefreshButton.setStyleSheet(self.theme.LIBRARY_CONTROLS_BUTTON_STYLE)
        self.autoInstallRefreshButton.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.autoInstallRefreshButton.clicked.connect(self._refresh_autoinstall_games)
        self._register_gamepad_tooltip(self.autoInstallRefreshButton, _("Refresh Grid"))
        searchLayout.addWidget(self.autoInstallRefreshButton)

        autoInstallLayout.addWidget(searchWidget)
        self._setup_autoinstall_search_animation()

        self.autoInstallScrollArea = AutoHideScrollArea(theme=self.theme)
        self.autoInstallScrollArea.setWidgetResizable(True)
        QScroller.grabGesture(self.autoInstallScrollArea.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)

        self.autoInstallContainer = QWidget()
        self.autoInstallContainer.setStyleSheet(self.theme.LIST_WIDGET_STYLE)
        auto_layout_mode = str(getattr(self.theme, "LIBRARY_LAYOUT_MODE", "grid")).lower()
        self._set_autoinstall_container_layout(auto_layout_mode)
        self.autoInstallScrollArea.setWidget(self.autoInstallContainer)

        autoInstallLayout.addWidget(self.autoInstallScrollArea)

        self.auto_size_slider = QSlider(Qt.Orientation.Horizontal, autoInstallPage)
        self.auto_size_slider.setMinimum(100)
        self.auto_size_slider.setMaximum(250)
        self.auto_size_slider.setValue(self.auto_card_width)
        self.auto_size_slider.setTickInterval(10)
        self.auto_size_slider.setFixedWidth(150)
        self.auto_size_slider.setStyleSheet(self.theme.SLIDER_SIZE_STYLE)
        self._register_gamepad_tooltip(self.auto_size_slider, f"{self.auto_card_width} px")
        self.auto_size_slider.sliderReleased.connect(self.on_auto_slider_released)

        sliderLayout = QHBoxLayout()
        sliderLayout.addStretch()
        sliderLayout.addWidget(self.auto_size_slider)
        autoInstallLayout.addLayout(sliderLayout)

        fixed_layout = auto_layout_mode in {
            "list", "vertical", "horizontal", "horizontal_top",
        }
        self.auto_size_slider.setVisible(not fixed_layout)
        if fixed_layout:
            self.auto_card_width = self.auto_size_slider.maximum()
            self.auto_size_slider.setValue(self.auto_card_width)
            self._gamepad_tooltip_map[self.auto_size_slider] = f"{self.auto_card_width} px"

        # Store cards
        self.autoInstallGameCards = {}
        self.allAutoInstallCards = []
        self.autoInstallSearchOptimizer = SearchOptimizer()
        self.autoInstallLoaded = False
        self.autoInstallLoading = False

        # Load games
        def on_autoinstall_games_loaded(games: list[tuple]):
            self.autoInstallLoaded = True
            self.autoInstallLoading = False
            auto_layout_mode = str(
                getattr(self.theme, "LIBRARY_LAYOUT_MODE", "grid")
            ).lower()
            list_layout = auto_layout_mode in {"list", "vertical"}
            self.autoInstallContainer.setProperty(
                "library_layout_mode", auto_layout_mode
            )

            # Clear
            while self.autoInstallContainerLayout.count():
                child = self.autoInstallContainerLayout.takeAt(0)
                if child:
                    widget = child.widget()
                    if widget:
                        widget.deleteLater()

            self.autoInstallGameCards.clear()
            self.allAutoInstallCards.clear()

            if not games:
                return

            # Callback for opening autoinstall detail page
            def select_callback(game_data: dict):
                exec_line = game_data.get("exec_line", "")
                if not exec_line or not exec_line.startswith("autoinstall:"):
                    logger.warning(f"Invalid exec_line for autoinstall: {exec_line}")
                    return
                game_data["game_source"] = "portproton"
                ppai_target = exec_line[12:].strip()
                if ppai_target.startswith(("http://", "https://")):
                    self._open_autoinstall_card_after_script_download(game_data, ppai_target)
                    return
                self.detail_page_manager.openAutoInstallDetailPage(game_data)

            # Create cards
            for game_tuple in sorted(games, key=lambda item: str(item[0]).casefold()):
                name = game_tuple[0]
                description = game_tuple[1]
                cover_path = game_tuple[2]
                appid = game_tuple[3]
                controller_support = game_tuple[4]
                exec_line = game_tuple[5]
                game_source = game_tuple[12]
                exe_name = game_tuple[13]
                compact_cover = game_tuple[14] if len(game_tuple) > 14 else ""
                full_cover = game_tuple[15] if len(game_tuple) > 15 else cover_path
                if list_layout:
                    cover_path = compact_cover or full_cover
                else:
                    cover_path = full_cover or compact_cover

                card = GameCard(
                    name, description, cover_path, appid, controller_support,
                    exec_line, None, None, None,
                    None, None, None, game_source,
                    select_callback=select_callback,
                    theme=self.theme,
                    card_width=self.auto_card_width,
                    parent=self.autoInstallContainer,
                )
                card.autoinstall_exe_name = exe_name
                card.hoverChanged.connect(self._on_autoinstall_card_active)
                card.focusChanged.connect(self._on_autoinstall_card_active)

                # Hide badges and favorite button
                if hasattr(card, 'steamLabel'):
                    card.steamLabel.setVisible(False)
                if hasattr(card, 'portprotonLabel'):
                    card.portprotonLabel.setVisible(False)
                if hasattr(card, 'protondbLabel'):
                    card.protondbLabel.setVisible(False)
                if hasattr(card, 'anticheatLabel'):
                    card.anticheatLabel.setVisible(False)
                if hasattr(card, 'favoriteLabel'):
                    card.favoriteLabel.setVisible(False)

                self.autoInstallGameCards[exe_name] = card
                self.allAutoInstallCards.append(card)
                self.autoInstallContainerLayout.addWidget(card)

            self._build_autoinstall_search_indices()
            self.autoInstallContainer.updateGeometry()
            self.autoInstallScrollArea.updateGeometry()
            self.filterAutoInstallGames()

        self._on_autoinstall_games_loaded = on_autoinstall_games_loaded

        self.stackedWidget.addWidget(autoInstallPage)

    def _on_autoinstall_card_active(self, game_name: str, active: bool) -> None:
        if not active:
            return
        for card in self.allAutoInstallCards:
            if card.name != game_name:
                continue
            self.game_library_manager.render_library_background(
                self.autoInstallBackgroundLabel, card
            )
            return

    def _set_autoinstall_container_layout(self, mode: str) -> None:
        old_layout = getattr(self, "autoInstallContainerLayout", None)
        if old_layout is not None:
            while old_layout.count():
                item = old_layout.takeAt(0)
                if item and item.widget():
                    item.widget().deleteLater()
            QWidget().setLayout(old_layout)
        self.autoInstallContainer.setProperty("library_layout_mode", mode)
        if mode == "vertical":
            config = self.theme.GAME_CARD_VERTICAL
            layout = QVBoxLayout()
            layout.setContentsMargins(*config.get("layout_margins", (0, 0, 0, 0)))
            layout.setSpacing(config.get("layout_spacing", 0))
            layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        elif mode in {"horizontal", "horizontal_top"}:
            config = self.theme.GAME_CARD_HORIZONTAL
            layout = QHBoxLayout()
            layout.setContentsMargins(*config["layout_margins"])
            layout.setSpacing(config["layout_spacing"])
            layout.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
        else:
            layout = FlowLayout()
        self.autoInstallContainerLayout = layout
        self.autoInstallContainer.setLayout(layout)
        horizontal = mode in {"horizontal", "horizontal_top"}
        vertical_policy = (
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            if horizontal else Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        horizontal_policy = (
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if horizontal else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.autoInstallScrollArea.setVerticalScrollBarPolicy(vertical_policy)
        self.autoInstallScrollArea.setHorizontalScrollBarPolicy(horizontal_policy)

    def refresh_autoinstall_layout(self) -> None:
        """Rebuild auto-install cards after a live library layout change."""
        if not hasattr(self, "autoInstallContainer"):
            return
        mode = str(getattr(self.theme, "LIBRARY_LAYOUT_MODE", "grid")).lower()
        fixed_layout = mode in {
            "list", "vertical", "horizontal", "horizontal_top",
        }
        self._set_autoinstall_container_layout(mode)
        self.auto_size_slider.setVisible(not fixed_layout)
        if fixed_layout:
            self.auto_card_width = self.auto_size_slider.maximum()
            self.auto_size_slider.setValue(self.auto_card_width)
        if self.autoInstallLoading:
            return
        self.autoInstallLoaded = False
        self._start_autoinstall_load()

    def _open_autoinstall_card_after_script_download(
        self,
        game_data: dict,
        ppai_url: str,
    ) -> None:
        def on_script_ready(script_path: str) -> None:
            if script_path:
                game_data["exec_line"] = f"autoinstall:{script_path}"
            self.detail_page_manager.openAutoInstallDetailPage(game_data)
            if script_path:
                self.autoInstallCustomDataThread = self.portproton_api.start_autoinstall_custom_data_write(
                    script_path,
                    game_data,
                )
                self.autoInstallCustomDataThread.finished.connect(
                    lambda: setattr(self, "autoInstallCustomDataThread", None)
                )

        self.autoInstallScriptLoadThread = self.portproton_api.start_autoinstall_script_download(
            ppai_url,
            on_script_ready,
        )
        self.autoInstallScriptLoadThread.finished.connect(
            lambda: setattr(self, "autoInstallScriptLoadThread", None)
        )

    def _setup_autoinstall_search_animation(self) -> None:
        self.autoInstallSearchAnimation = ExpandingSearchAnimation(
            self.autoInstallSearchLineEdit,
            self.theme,
            self.searchDebounceTimer.interval(),
        )
        collapsed_width = self.autoInstallRefreshButton.sizeHint().width()
        expanded_width = self.autoInstallSearchLineEdit.maximumWidth()
        self.autoInstallSearchAnimation.setup(collapsed_width, expanded_width)
        QTimer.singleShot(0, self._center_collapsed_autoinstall_search_icon)

    def _wrap_autoinstall_search_focus_event(self, original_event: Callable, expand: bool) -> Callable:
        def handle_focus_event(event):
            original_event(event)
            if not hasattr(self, "autoInstallSearchAnimation"):
                return
            keyboard = getattr(self, "keyboard", None)
            if expand:
                self.autoInstallSearchAnimation.expand()
            elif not (
                keyboard
                and keyboard.isVisible()
                and getattr(keyboard, "current_input_widget", None) is self.autoInstallSearchLineEdit
            ):
                self.autoInstallSearchAnimation.collapse()
            QTimer.singleShot(0, self._center_collapsed_autoinstall_search_icon)
        return handle_focus_event

    def _wrap_autoinstall_search_resize_event(self, original_event: Callable) -> Callable:
        def handle_resize_event(event):
            original_event(event)
            self._center_collapsed_autoinstall_search_icon()
        return handle_resize_event

    def _center_collapsed_autoinstall_search_icon(self) -> None:
        animation = getattr(self, "autoInstallSearchAnimation", None)
        if animation is None or self.autoInstallSearchLineEdit.maximumWidth() != animation.collapsed_width:
            return
        for button in self.autoInstallSearchLineEdit.findChildren(QToolButton):
            if button.defaultAction() is self.autoInstallSearchIconAction:
                size = button.sizeHint()
                x = (self.autoInstallSearchLineEdit.width() - size.width()) // 2
                y = (self.autoInstallSearchLineEdit.height() - size.height()) // 2
                button.setGeometry(x, y, size.width(), size.height())
                return

    def _start_autoinstall_load(self, force_refresh: bool = False) -> None:
        if self.autoInstallLoaded or self.autoInstallLoading:
            return
        if not hasattr(self, "_on_autoinstall_games_loaded"):
            return
        self.autoInstallLoading = True
        self.autoInstallLoadThread = self.portproton_api.start_autoinstall_games_load(
            self._on_autoinstall_games_loaded,
            force_refresh=force_refresh,
        )
        if not self.autoInstallLoadThread:
            self.autoInstallLoading = False
            if hasattr(self, "autoInstallRefreshButton"):
                self.autoInstallRefreshButton.setEnabled(True)
            return

        def on_thread_finished():
            self.autoInstallLoadThread = None  # Release reference
            if hasattr(self, "autoInstallRefreshButton"):
                self.autoInstallRefreshButton.setEnabled(True)
        self.autoInstallLoadThread.finished.connect(on_thread_finished)

    def _refresh_autoinstall_games(self) -> None:
        if self.autoInstallLoading:
            return
        self.autoInstallRefreshButton.setEnabled(False)
        self.autoInstallLoaded = False
        self.portproton_api.clear_autoinstall_image_cache()
        self._start_autoinstall_load(force_refresh=True)

    def on_auto_slider_released(self):
        """Handles auto-install slider release to update card size."""
        auto_layout_mode = str(getattr(self.theme, "LIBRARY_LAYOUT_MODE", "grid")).lower()
        fixed_layout = auto_layout_mode in {
            "list", "vertical", "horizontal", "horizontal_top",
        }
        if hasattr(self, 'auto_size_slider') and self.auto_size_slider:
            if not fixed_layout:
                self.auto_card_width = self.auto_size_slider.value()
            self._gamepad_tooltip_map[self.auto_size_slider] = f"{self.auto_card_width} px"
            if not fixed_layout:
                ui_config.set_auto_card_width(self.auto_card_width)
        if not hasattr(self, 'allAutoInstallCards'):
            return
        for card in self.allAutoInstallCards:
            card.update_card_size(self.auto_card_width)
        self.autoInstallContainerLayout.invalidate()
        self.autoInstallContainer.updateGeometry()
        self.autoInstallScrollArea.updateGeometry()

    def _build_autoinstall_search_indices(self) -> None:
        self.autoInstallSearchOptimizer.build_indices(
            build_search_items(
                self.allAutoInstallCards,
                lambda card: card.name,
            )
        )

    def filterAutoInstallGames(self):
        """Filter auto install game cards based on search text."""
        search_text = self.autoInstallSearchLineEdit.text().lower().strip()
        if not hasattr(self, "autoInstallSearchOptimizer"):
            self.autoInstallSearchOptimizer = SearchOptimizer()
            self._build_autoinstall_search_indices()
        visible_cards = self.allAutoInstallCards
        if search_text:
            visible_cards = search_index(self.autoInstallSearchOptimizer, search_text)

        for card in self.allAutoInstallCards:
            card.setVisible(card in visible_cards)

        # Re-layout the container
        self.autoInstallContainerLayout.invalidate()
        self.autoInstallContainer.updateGeometry()
        self.autoInstallScrollArea.updateGeometry()
