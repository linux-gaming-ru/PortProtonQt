import time

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QListView,
    QMenu,
    QMessageBox,
    QScrollArea,
    QTableWidget,
    QWidget,
)

from portprotonqt.custom_widgets import AutoSizeButton, NavLabel
from portprotonqt.dialogs import AddGameDialog
from portprotonqt.game_card import AnimatedCard
from portprotonqt.image_utils import FullscreenDialog
from portprotonqt.input_manager.constants import (
    PAD_AXIS_LEFT_X,
    PAD_AXIS_LEFT_Y,
    PAD_DPAD_X,
    PAD_DPAD_Y,
)
from portprotonqt.input_manager.mixin import InputMixin
from portprotonqt.logger import get_logger
from portprotonqt.sound_manager import SoundManager
from portprotonqt.virtual_keyboard import VirtualKeyboard

logger = get_logger(__name__)


class DpadInputMixin(InputMixin):
    def handle_dpad_repeat(self) -> None:
        """Handle repeated D-pad input while the D-pad is held."""
        if self.current_dpad_code is not None and self.current_dpad_value != 0:
            now = time.time()
            if (now - self.last_move_time) >= self.current_axis_delay:
                self.handle_dpad_slot(self.current_dpad_code, self.current_dpad_value, now)
                self.last_move_time = now
                self.current_axis_delay = self.repeat_axis_move_delay

    def _get_theme_tab_focusables(self) -> list[QWidget]:
        """Return focusable widgets for the themes tab gamepad navigation."""
        if self._is_theme_store_visible():
            return self._get_theme_store_focusables()

        widgets = []
        for attr_name in (
            "themesCombo",
            "themeVariantCombo",
            "screenshotsCarousel",
            "applyButton",
            "deleteThemeButton",
        ):
            widget = getattr(self._parent, attr_name, None)
            if self._is_visible_enabled_widget(widget):
                widgets.append(widget)
        return widgets

    def _is_visible_enabled_widget(self, widget: object) -> bool:
        return isinstance(widget, QWidget) and widget.isVisible() and widget.isEnabled()

    def _is_theme_store_visible(self) -> bool:
        content_stack = getattr(self._parent, "themeContentStack", None)
        store_page = getattr(self._parent, "themeStorePage", None)
        return content_stack is not None and content_stack.currentWidget() == store_page

    def _get_theme_store_focusables(self) -> list[QWidget]:
        store_stack = getattr(self._parent, "themeStoreStack", None)
        detail_page = getattr(self._parent, "themeStoreDetailPage", None)
        if store_stack is not None and store_stack.currentWidget() == detail_page:
            return self._get_theme_store_detail_focusables()

        widgets = []
        for attr_name in ("themesCombo", "themeStoreSortCombo"):
            widget = getattr(self._parent, attr_name, None)
            if self._is_visible_enabled_widget(widget):
                widgets.append(widget)
        widgets.extend(self._get_theme_store_cards())
        return widgets

    def _get_theme_store_detail_focusables(self) -> list[QWidget]:
        widgets = []
        for attr_name in (
            "themeStoreBackButton",
            "themeStoreDownloadButton",
            "themeStoreCarousel",
            "themeStoreDarkButton",
            "themeStoreLightButton",
        ):
            widget = getattr(self._parent, attr_name, None)
            if self._is_visible_enabled_widget(widget):
                widgets.append(widget)
        return widgets

    def _get_theme_store_cards(self) -> list[QWidget]:
        grid_widget = getattr(self._parent, "themeStoreGridWidget", None)
        if not isinstance(grid_widget, QWidget):
            return []
        cards = grid_widget.findChildren(QWidget, "themeStoreCard")
        return [card for card in cards if card.isVisible() and card.isEnabled()]

    def _handle_theme_tab_navigation(self, code: int, value: int) -> bool:
        """Handle D-pad focus movement in themes tab."""
        theme_tab_index = getattr(self._parent, "theme_tab_index", None)
        if theme_tab_index is None or self._parent.stackedWidget.currentIndex() != theme_tab_index:
            return False

        if self._is_theme_store_visible() and self._handle_theme_store_grid_navigation(code, value):
            return True

        focused = QApplication.focusWidget()
        if code == PAD_DPAD_X and focused in self._get_theme_carousels():
            self._scroll_theme_carousel(focused, value)
            return True

        focusables = self._get_theme_tab_focusables()
        if not focusables:
            return False

        focused = QApplication.focusWidget()
        if focused not in focusables:
            focusables[0].setFocus(Qt.FocusReason.OtherFocusReason)
            return True

        current_index = focusables.index(focused)
        if code == PAD_DPAD_Y and value > 0 or code == PAD_DPAD_X and value > 0:
            next_index = (current_index + 1) % len(focusables)
        else:
            next_index = (current_index - 1) % len(focusables)
        focusables[next_index].setFocus(Qt.FocusReason.OtherFocusReason)
        self._ensure_theme_store_widget_visible(focusables[next_index])
        return True

    def _handle_theme_store_grid_navigation(self, code: int, value: int) -> bool:
        cards = self._get_theme_store_cards()
        return self._navigate_card_grid(cards, code, value)

    def _ensure_theme_store_widget_visible(self, widget: QWidget) -> None:
        scroll_area = getattr(self._parent, "themeStoreScrollArea", None)
        if isinstance(scroll_area, QScrollArea):
            scroll_area.ensureWidgetVisible(widget)

    def _get_theme_carousels(self) -> list[QWidget]:
        widgets = []
        for attr_name in ("screenshotsCarousel", "themeStoreCarousel"):
            widget = getattr(self._parent, attr_name, None)
            if self._is_visible_enabled_widget(widget):
                widgets.append(widget)
        return widgets

    def _scroll_theme_carousel(self, carousel: QWidget, value: int) -> None:
        if value > 0:
            scroll_right = getattr(carousel, "scroll_right", None)
            if callable(scroll_right):
                scroll_right()
        elif value < 0:
            scroll_left = getattr(carousel, "scroll_left", None)
            if callable(scroll_left):
                scroll_left()

    def _focus_first_dialog_widget(self, dialog: QDialog) -> bool:
        focusables = dialog.findChildren(
            QWidget,
            options=Qt.FindChildOption.FindChildrenRecursively,
        )
        focusables = [widget for widget in focusables if widget.focusPolicy() & Qt.FocusPolicy.StrongFocus]
        if not focusables:
            return False
        focusables[0].setFocus(Qt.FocusReason.OtherFocusReason)
        return True

    def _handle_add_game_checkbox_dpad(self, dialog: AddGameDialog, code: int, value: int) -> bool:
        if code not in (PAD_DPAD_X, PAD_AXIS_LEFT_X):
            return False
        if code == PAD_AXIS_LEFT_X:
            if abs(value) < self.dead_zone:
                return True
            value = 1 if value > self.dead_zone else -1
        checkboxes = [
            dialog.add_to_steam_checkbox,
            dialog.add_to_menu_checkbox,
            dialog.add_to_desktop_checkbox,
        ]
        focused = QApplication.focusWidget()
        if not isinstance(focused, QCheckBox) or focused not in checkboxes:
            return False
        current_index = checkboxes.index(focused)
        next_index = current_index + (1 if value > 0 else -1)
        if not 0 <= next_index < len(checkboxes):
            return False
        checkboxes[next_index].setFocus(Qt.FocusReason.OtherFocusReason)
        return True

    def _handle_dialog_dpad(self, active: QWidget, code: int, value: int) -> bool:
        focused = QApplication.focusWidget()
        if isinstance(active, QMessageBox) and not isinstance(focused, QTableWidget):
            if not focused or not active.focusWidget():
                self._focus_first_dialog_widget(active)
            elif code in (PAD_DPAD_X, PAD_DPAD_Y):
                active.focusNextChild() if value > 0 else active.focusPreviousChild()
            return True
        if isinstance(active, AddGameDialog) and code in (PAD_DPAD_X, PAD_AXIS_LEFT_X):
            return self._handle_add_game_checkbox_dpad(active, code, value)
        if not isinstance(active, QDialog):
            return False
        if code not in (PAD_DPAD_X, PAD_DPAD_Y):
            return False
        if code == PAD_DPAD_Y and isinstance(focused, QTableWidget):
            return False
        if not focused or not active.focusWidget():
            self._focus_first_dialog_widget(active)
            return True
        active.focusNextChild() if value > 0 else active.focusPreviousChild()
        return True

    def _handle_popup_dpad(self, popup: QWidget | None, code: int, value: int) -> bool:
        if not isinstance(popup, QMenu):
            return False
        if code == PAD_DPAD_Y:
            self._navigate_menu_actions(popup, direction_down=value > 0)
        return True

    def _handle_list_dpad(self, focused: QWidget | None, code: int, value: int) -> bool:
        if not isinstance(focused, QListView) or code != PAD_DPAD_Y:
            return False
        model = focused.model()
        current_index = focused.currentIndex()
        if not model or not current_index.isValid():
            return True
        next_row = current_index.row() + (1 if value > 0 else -1)
        next_row = max(0, min(next_row, model.rowCount() - 1))
        focused.setCurrentIndex(model.index(next_row, current_index.column()))
        focused.scrollTo(focused.currentIndex(), QListView.ScrollHint.PositionAtCenter)
        return True

    def _handle_fullscreen_dpad(self, active: QWidget, code: int, value: int) -> bool:
        if not isinstance(active, FullscreenDialog) or code != PAD_DPAD_X:
            return False
        if value < 0:
            active.show_prev()
        else:
            active.show_next()
        return True

    def _handle_system_section_horizontal(self, code: int, value: int, initial_press: bool) -> bool:
        if code != PAD_DPAD_X or not initial_press:
            return False
        if self._parent.stackedWidget.currentIndex() != getattr(self._parent, "system_tab_index", -1):
            return False
        switch_relative = getattr(self._parent, "switchSystemSectionRelative", None)
        if not callable(switch_relative) or not switch_relative(1 if value > 0 else -1):
            return False
        section_stack = getattr(self._parent, "systemSectionStack", None)
        section_buttons = getattr(self._parent, "systemSectionButtons", [])
        if section_stack is None or not section_buttons:
            return True
        current_index = section_stack.currentIndex()
        if 0 <= current_index < len(section_buttons):
            section_buttons[current_index].setFocus(Qt.FocusReason.OtherFocusReason)
        return True

    def _focus_toolbar_from_first_card(self, code: int, value: int) -> bool:
        focused = QApplication.focusWidget()
        current_index = self._parent.stackedWidget.currentIndex()
        if code != PAD_DPAD_Y or value >= 0 or current_index not in (0, 1):
            return False
        if not isinstance(focused, AnimatedCard):
            return False
        if current_index == 0:
            container = self._parent.gamesListWidget
            toolbar_widgets = self._get_library_toolbar_widgets()
            focus_target = toolbar_widgets[0] if toolbar_widgets else None
        else:
            container = self._parent.autoInstallContainer
            focus_target = getattr(self._parent, 'autoInstallSearchLineEdit', None)
        if container is None or focus_target is None:
            return False
        cards: list[QWidget] = [
            card for card in container.findChildren(AnimatedCard)
            if card.isVisible() and card.isEnabled()
        ]
        if not cards or focused not in self._get_card_grid_rows(cards)[0]:
            return False
        focus_target.setFocus(Qt.FocusReason.OtherFocusReason)
        return True

    def _handle_system_section_vertical(self, code: int, value: int) -> bool:
        if code != PAD_DPAD_Y:
            return False
        if self._parent.stackedWidget.currentIndex() != getattr(self._parent, "system_tab_index", -1):
            return False
        focused = QApplication.focusWidget()
        section_buttons = getattr(self._parent, "systemSectionButtons", [])
        if focused not in section_buttons:
            return False
        if value < 0:
            return True
        section_stack = getattr(self._parent, "systemSectionStack", None)
        focus_targets = getattr(self._parent, "systemSectionFocusTargets", [])
        if section_stack is None:
            return True
        current_index = section_stack.currentIndex()
        if 0 <= current_index < len(focus_targets):
            target = focus_targets[current_index]
            if target is not None and target.isVisible() and target.isEnabled():
                target.setFocus(Qt.FocusReason.OtherFocusReason)
        return True

    @Slot(int, int, float)
    def handle_dpad_slot(self, code: int, value: int, current_time: float) -> None:
        keyboard = getattr(self._parent, 'system_keyboard', None)
        if keyboard is not None and keyboard.isVisible():
            if value == 0:
                self._reset_dpad_repeat()
                return
            directions = {PAD_DPAD_X: ('left', 'right'), PAD_AXIS_LEFT_X: ('left', 'right'),
                          PAD_DPAD_Y: ('up', 'down'), PAD_AXIS_LEFT_Y: ('up', 'down')}
            if code in directions:
                self._start_dpad_repeat(code, value, current_time)
                keyboard.send('direction', directions[code][value > 0])
            return
        if self._route_surface_dpad(code, value, current_time):
            return
        self._handle_default_dpad(code, value, current_time)

    def _handle_default_dpad(self, code: int, value: int, current_time: float) -> None:
        active_window = QApplication.activeWindow()
        keyboard = getattr(active_window, 'keyboard', None) or getattr(self._parent, 'keyboard', None)

        if value == 0:
            self._reset_dpad_repeat()
            return

        is_initial_press = not self.axis_moving
        self._start_dpad_repeat(code, value, current_time)

        if keyboard and keyboard.isVisible() and self._handle_keyboard_dpad(keyboard, code, value):
            return

        if not self._gamepad_handling_enabled:
            return
        if not hasattr(self._parent, 'gamesListWidget') or self._parent.gamesListWidget is None:
            logger.error("gamesListWidget not available yet, skipping D-pad navigation")
            return

        try:
            self._route_dpad_navigation(code, value, is_initial_press)
        except Exception as e:
            logger.error(f"Error in handle_dpad_slot: {e}", exc_info=True)

    def _route_dpad_navigation(self, code: int, value: int, is_initial_press: bool) -> None:
        app = QApplication.instance()
        active = QApplication.activeWindow()
        focused = QApplication.focusWidget()
        popup = QApplication.activePopupWidget()
        if not app or not active:
            return
        combo_popup = (
            isinstance(focused, QListView)
            and self._find_parent_combo(focused) is not None
        )
        if is_initial_press and not isinstance(focused, AnimatedCard) and not combo_popup:
            SoundManager().play("navigate")
        if self._handle_dialog_dpad(active, code, value):
            return
        if self._handle_popup_dpad(popup, code, value):
            return
        if self._handle_list_dpad(focused, code, value):
            return
        if self._handle_fullscreen_dpad(active, code, value):
            return
        if self._handle_system_section_horizontal(code, value, is_initial_press):
            return
        if isinstance(focused, QTableWidget):
            self.handle_table_navigation(focused, code, value)
            return
        if self._focus_toolbar_from_first_card(code, value):
            return
        if self._handle_library_dpad(code, value):
            return
        if code in (PAD_DPAD_X, PAD_DPAD_Y) and self._handle_theme_tab_navigation(code, value):
            return
        if self._handle_system_section_vertical(code, value):
            return
        if self._handle_detail_page_dpad(code, value):
            return
        self._handle_page_vertical_dpad(code, value)

    def _handle_detail_page_dpad(self, code: int, value: int) -> bool:
        direction = self._normalize_dpad_direction(code, value)
        if direction is None:
            return False
        focused = QApplication.focusWidget()
        page = self._parent.stackedWidget.currentWidget()
        current_detail_page = getattr(self._parent, "currentDetailPage", None)
        if not isinstance(focused, AutoSizeButton) or page != current_detail_page:
            return False
        parent = focused.parentWidget()
        if parent is None:
            return False
        rows = self._get_detail_button_rows(parent)
        if len(rows) == 1 and len(rows[0]) <= 1:
            return False
        target = self._get_detail_button_target(rows, focused, direction)
        if target is None:
            return False
        self._focus_detail_button(target)
        return True

    def _handle_library_dpad(self, code: int, value: int) -> bool:
        if code not in (PAD_DPAD_X, PAD_DPAD_Y):
            return False
        current_index = self._parent.stackedWidget.currentIndex()
        if current_index not in (0, 1):
            return False
        if self._handle_toolbar_navigation(code, value):
            return True
        if code == PAD_DPAD_Y and value < 0 and self._focus_tab_from_search(current_index):
            return True
        container = (
            self._parent.gamesListWidget
            if current_index == 0
            else self._parent.autoInstallContainer
        )
        if container is not None:
            self._navigate_game_cards(container, current_index, code, value)
        return True

    def _handle_page_vertical_dpad(self, code: int, value: int) -> bool:
        if code != PAD_DPAD_Y or value == 0:
            return False
        focused = QApplication.focusWidget()
        if focused is None:
            return False
        if value < 0:
            focused.focusPreviousChild()
            return True
        if not isinstance(focused, NavLabel):
            focused.focusNextChild()
            return True
        page = self._parent.stackedWidget.currentWidget()
        focusables = page.findChildren(
            QWidget,
            options=Qt.FindChildOption.FindChildrenRecursively,
        )
        focusables = [
            widget for widget in focusables
            if widget.focusPolicy() & Qt.FocusPolicy.StrongFocus
        ]
        if not focusables:
            return False
        focusables[0].setFocus()
        return True

    def _normalize_dpad_direction(self, code: int, value: int) -> tuple[int, int] | None:
        if code in (PAD_DPAD_X, PAD_DPAD_Y):
            return (code, value) if value != 0 else None
        if code not in (PAD_AXIS_LEFT_X, PAD_AXIS_LEFT_Y) or abs(value) < self.dead_zone:
            return None
        normalized_code = PAD_DPAD_X if code == PAD_AXIS_LEFT_X else PAD_DPAD_Y
        return normalized_code, 1 if value > self.dead_zone else -1

    def _get_detail_button_rows(self, parent: QWidget) -> list[list[AutoSizeButton]]:
        buttons = parent.findChildren(
            AutoSizeButton,
            options=Qt.FindChildOption.FindDirectChildrenOnly,
        )
        buttons = [button for button in buttons if button.isVisible() and button.isEnabled()]
        centers = {button: button.geometry().center() for button in buttons}
        rows: list[list[AutoSizeButton]] = []
        for button in sorted(buttons, key=lambda item: (centers[item].y(), centers[item].x())):
            if not rows or abs(centers[button].y() - centers[rows[-1][0]].y()) > 24:
                rows.append([button])
            else:
                rows[-1].append(button)
        for row in rows:
            row.sort(key=lambda item: centers[item].x())
        return rows

    def _get_detail_button_target(
        self, rows: list[list[AutoSizeButton]], focused: AutoSizeButton,
        direction: tuple[int, int],
    ) -> AutoSizeButton | None:
        row_index = next((index for index, row in enumerate(rows) if focused in row), -1)
        if row_index < 0:
            return None
        code, value = direction
        if code == PAD_DPAD_X:
            flat = [button for row in rows for button in row]
            index = flat.index(focused) + value
            return flat[index] if 0 <= index < len(flat) else None
        target_row_index = row_index + value
        if not 0 <= target_row_index < len(rows):
            return None
        focused_x = focused.geometry().center().x()
        return min(
            rows[target_row_index],
            key=lambda button: abs(button.geometry().center().x() - focused_x),
        )

    def _focus_detail_button(self, target: AutoSizeButton) -> None:
        target.setFocus(Qt.FocusReason.OtherFocusReason)
        parent = target.parentWidget()
        while parent and not isinstance(parent, QScrollArea):
            parent = parent.parentWidget()
        if isinstance(parent, QScrollArea):
            parent.ensureWidgetVisible(target, 20, 20)

    def _reset_dpad_repeat(self) -> None:
        self.current_dpad_code = None
        self.current_dpad_value = 0
        self.axis_moving = False
        self.current_axis_delay = self.initial_axis_move_delay
        self.dpad_timer.stop()

    def _start_dpad_repeat(self, code: int, value: int, current_time: float) -> None:
        self.current_dpad_code = code
        self.current_dpad_value = value
        if self.axis_moving:
            return
        self.axis_moving = True
        self.last_move_time = current_time
        self.current_axis_delay = self.initial_axis_move_delay
        self.dpad_timer.start(int(self.repeat_axis_move_delay * 1000))

    def _handle_keyboard_dpad(self, keyboard: VirtualKeyboard, code: int, value: int) -> bool:
        directions = {
            PAD_DPAD_X: (keyboard.move_focus_left, keyboard.move_focus_right),
            PAD_AXIS_LEFT_X: (keyboard.move_focus_left, keyboard.move_focus_right),
            PAD_DPAD_Y: (keyboard.move_focus_up, keyboard.move_focus_down),
            PAD_AXIS_LEFT_Y: (keyboard.move_focus_up, keyboard.move_focus_down),
        }
        actions = directions.get(code)
        if actions is None:
            return False
        if code in (PAD_AXIS_LEFT_X, PAD_AXIS_LEFT_Y):
            if abs(value) < self.dead_zone:
                self._reset_dpad_repeat()
                return True
            value = 1 if value > self.dead_zone else -1
        actions[1 if value > 0 else 0]()
        return True
