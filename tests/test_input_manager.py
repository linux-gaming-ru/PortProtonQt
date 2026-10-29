"""Tests for gamepad input navigation."""

from inspect import signature
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

from PySide6.QtCore import QEvent, QObject, QStringListModel, Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLineEdit, QListView, QMenu, QPushButton, QSlider, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from pytest import MonkeyPatch, raises, mark
from shiboken6 import delete

import portprotonqt.input_manager as input_manager
import portprotonqt.input_manager.buttons as input_buttons
import portprotonqt.input_manager.dpad as input_dpad
import portprotonqt.input_manager.runtime as input_runtime
import portprotonqt.native_gamepad as native_gamepad
from portprotonqt.input_manager.constants import (
    GamepadType,
    KEY_LEFT,
    PAD_BUTTON_SOUTH,
    PAD_BUTTON_SELECT,
    PAD_BUTTON_GUIDE,
    PAD_BUTTON_START,
    SDL_GAMEPAD_TYPE_PS5,
    SDL_GAMEPAD_BUTTON_DPAD_DOWN,
    SDL_GAMEPAD_BUTTON_DPAD_UP,
)
from portprotonqt.input_manager import InputManager, MainWindowProtocol, PAD_DPAD_X, PAD_DPAD_Y
from portprotonqt.game_library_manager import FullLibraryTile
from portprotonqt.native_gamepad import GamepadBackendError, SDLGamepad
from portprotonqt.themes.standart.styles.constants import GAME_CARD_ANIMATION

FIRST_CARD_X = 0
HIDDEN_CARD_X = 20
NEXT_CARD_X = 40


@mark.parametrize("event_type", [QEvent.Type.Destroy, QEvent.Type.ChildRemoved, QEvent.Type.DeferredDelete])
def test_keyboard_filter_ignores_deleted_layout(event_type: QEvent.Type) -> None:
    app = QApplication.instance() or QApplication([])
    manager = InputManager.__new__(InputManager)
    QObject.__init__(manager)
    layout = QVBoxLayout()
    delete(layout)

    assert manager.eventFilter(layout, QEvent(event_type)) is False
    assert app is not None


@mark.parametrize("event_type", [QEvent.Type.Destroy, QEvent.Type.ChildRemoved, QEvent.Type.DeferredDelete])
def test_keyboard_filter_teardown_does_not_lookup_application(
    monkeypatch: MonkeyPatch, event_type: QEvent.Type,
) -> None:
    app = QApplication.instance() or QApplication([])
    manager = InputManager.__new__(InputManager)
    QObject.__init__(manager)
    watched = QObject()
    lookup = MagicMock(side_effect=AssertionError("Application lookup during teardown"))
    monkeypatch.setattr(QApplication, "instance", lookup)

    assert manager.eventFilter(watched, QEvent(event_type)) is False
    lookup.assert_not_called()
    assert app is not None


@mark.parametrize("initial", [True, False])
def test_gamepad_auto_fullscreen_shows_boot_on_hotplug(monkeypatch: MonkeyPatch, initial: bool) -> None:
    app = QApplication.instance() or QApplication([])
    window = cast(Any, QWidget())
    window.start_boot_animation = MagicMock()
    manager: Any = InputManager.__new__(InputManager)
    QObject.__init__(manager)
    manager._parent = window
    manager._is_fullscreen = False
    manager._initial_gamepad_check = initial
    manager._gamepad_polling_suspended = False
    manager.gamepad = None
    manager.find_gamepad = lambda: SimpleNamespace(path="test", name="test")
    manager.detect_gamepad_axes = MagicMock()
    manager._reset_input_state = MagicMock()
    manager._refresh_gamepad_ui = MagicMock()
    manager._get_effective_gamepad_type = MagicMock()
    manager.toggle_fullscreen.connect(manager.handle_fullscreen_slot)
    monkeypatch.setattr(input_runtime.display_config, "get_auto_fullscreen_gamepad", lambda: True)
    monkeypatch.setattr(input_runtime.display_config, "get_fullscreen", lambda: False)
    monkeypatch.setattr(input_manager.window_config, "set_geometry", MagicMock())
    monkeypatch.setattr(input_manager.window_config, "get_geometry", lambda: (640, 480))
    manager.check_gamepad()
    assert window.isFullScreen() is (not initial)
    assert window.start_boot_animation.call_count == (0 if initial else 1)
    if not initial:
        manager.handle_fullscreen_slot(True)
        assert window.start_boot_animation.call_count == 1
        window.boot_animation = MagicMock()
        manager.handle_fullscreen_slot(False)
        window.boot_animation.finish.assert_called_once_with()
        assert not window.isFullScreen()
    window.close()
    assert app is not None


def _tile_theme() -> Any:
    return SimpleNamespace(
        fullLibraryTileSize=(180, 180),
        fullLibraryTileColumns=2,
        fullLibraryTileRows=2,
        fullLibraryTileRadius=10,
        GAME_CARD_HORIZONTAL={},
        GAME_CARD_ANIMATION=GAME_CARD_ANIMATION,
    )


def test_dpad_first_repeat_uses_long_press_delay() -> None:
    parameters = signature(InputManager).parameters

    assert parameters["initial_axis_move_delay"].default == 0.5


def test_theme_tab_focusables_include_delete_button(monkeypatch: MonkeyPatch) -> None:
    app = QApplication.instance() or QApplication([])
    manager = InputManager.__new__(InputManager)
    widgets = [QWidget() for _index in range(5)]
    cast(Any, manager)._parent = SimpleNamespace(
        themesCombo=widgets[0],
        themeVariantCombo=widgets[1],
        screenshotsCarousel=widgets[2],
        applyButton=widgets[3],
        deleteThemeButton=widgets[4],
    )
    monkeypatch.setattr(manager, "_is_theme_store_visible", lambda: False)
    monkeypatch.setattr(manager, "_is_visible_enabled_widget", lambda _widget: True)

    assert manager._get_theme_tab_focusables() == widgets
    assert app is not None


def test_native_gamepad_result_preserves_python_interface(monkeypatch: MonkeyPatch) -> None:
    controller = 42
    monkeypatch.setattr(native_gamepad._library, "portproton_gamepad_find", lambda: controller)
    monkeypatch.setattr(native_gamepad._library, "portproton_gamepad_close", lambda _handle: None)
    monkeypatch.setattr(native_gamepad._library, "portproton_gamepad_get_instance_id", lambda _handle: 7)
    monkeypatch.setattr(native_gamepad._library, "portproton_gamepad_get_name", lambda _handle: b"DualSense")
    monkeypatch.setattr(
        native_gamepad._library,
        "portproton_gamepad_get_type",
        lambda _handle: SDL_GAMEPAD_TYPE_PS5,
    )

    gamepad = native_gamepad.find_gamepad()

    assert gamepad is not None
    assert gamepad.controller == controller
    assert gamepad.name == "DualSense"
    assert gamepad.path == "sdl3-gamepad:7"
    manager = InputManager.__new__(InputManager)
    assert manager._detect_gamepad_type(gamepad) == GamepadType.PLAYSTATION
    gamepad.close()


def test_native_gamepad_update_passes_collection_handle(monkeypatch: MonkeyPatch) -> None:
    updated_handles: list[int] = []
    gamepad = SDLGamepad(42, "Gamepads", "sdl3-gamepad:7", 7, 1)
    monkeypatch.setattr(native_gamepad._library, "portproton_gamepad_close", lambda _handle: None)
    monkeypatch.setattr(
        native_gamepad._library,
        "portproton_gamepad_update",
        updated_handles.append,
    )
    monkeypatch.setattr(
        native_gamepad._library,
        "portproton_gamepad_get_active_instance_id",
        lambda _handle: 9,
    )
    monkeypatch.setattr(
        native_gamepad._library,
        "portproton_gamepad_get_type",
        lambda _handle: SDL_GAMEPAD_TYPE_PS5,
    )

    changed = gamepad.update()

    assert updated_handles == [42]
    assert changed is True
    assert gamepad.active_instance_id == 9
    assert gamepad.sdl_type == SDL_GAMEPAD_TYPE_PS5
    assert gamepad.update() is False
    gamepad.close()


def test_native_gamepad_reports_sdl_discovery_error(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(native_gamepad._library, "portproton_gamepad_find", lambda: None)
    monkeypatch.setattr(
        native_gamepad._library,
        "portproton_gamepad_get_error",
        lambda: b"SDL gamepad initialization failed",
    )

    with raises(GamepadBackendError, match="SDL gamepad initialization failed"):
        native_gamepad.find_gamepad()


def test_native_gamepad_absence_is_not_an_error(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(native_gamepad._library, "portproton_gamepad_find", lambda: None)
    monkeypatch.setattr(native_gamepad._library, "portproton_gamepad_get_error", lambda: b"")

    assert native_gamepad.find_gamepad() is None


def test_repeated_gamepad_backend_error_is_logged_once(monkeypatch: MonkeyPatch) -> None:
    logged_errors: list[tuple[object, ...]] = []
    manager = InputManager.__new__(InputManager)
    manager._last_gamepad_error = None

    def fail_discovery() -> None:
        raise GamepadBackendError("SDL initialization failed")

    monkeypatch.setattr(input_runtime, "find_gamepad", fail_discovery)
    monkeypatch.setattr(
        input_runtime.logger,
        "error",
        lambda *args, **_kwargs: logged_errors.append(args),
    )

    assert manager.find_gamepad() is None
    assert manager.find_gamepad() is None

    assert len(logged_errors) == 1


def test_qt_event_to_input_key_supports_cyrillic() -> None:
    event = cast(
        QEvent,
        SimpleNamespace(
            nativeScanCode=lambda: 0,
            text=lambda: "Я",
            key=lambda: 0,
        ),
    )
    manager = InputManager.__new__(InputManager)

    assert manager._qt_event_to_input_key(event) == ord("я")


def test_sdl_dpad_vertical_directions() -> None:
    emitted: list[tuple[int, int, float]] = []
    pressed_button = SDL_GAMEPAD_BUTTON_DPAD_UP
    gamepad = cast(
        SDLGamepad,
        SimpleNamespace(get_button=lambda button: int(button == pressed_button)),
    )
    manager = InputManager.__new__(InputManager)
    QObject.__init__(manager)
    manager._hat_states = {}
    manager.mouse_emulation_enabled = False
    manager.emulation_active = False
    manager.emulation_triggered = False
    manager.dpad_moved.connect(lambda code, value, now: emitted.append((code, value, now)))

    InputManager._poll_hat_events(manager, gamepad, 1.0)
    pressed_button = SDL_GAMEPAD_BUTTON_DPAD_DOWN
    InputManager._poll_hat_events(manager, gamepad, 2.0)

    assert emitted == [(PAD_DPAD_Y, -1, 1.0), (PAD_DPAD_Y, 1, 2.0)]


def test_disabling_mouse_emulation_keeps_gamepad_events_working() -> None:
    emitted: list[tuple[int, int]] = []
    manager = InputManager.__new__(InputManager)
    QObject.__init__(manager)
    cast(Any, manager)._parent = SimpleNamespace(boot_animation=None)
    manager._button_states = {}
    manager.mouse_emulation_enabled = True
    manager.emulation_active = True
    manager.emulation_triggered = True
    manager.start_held = True
    manager.select_held = False
    manager.pending_menu_fullscreen_time = 0.0
    manager.button_event.connect(lambda code, value: emitted.append((code, value)))

    manager._handle_button_value(0, PAD_BUTTON_SELECT, 1, 1.0)
    manager._handle_button_value(1, PAD_BUTTON_SOUTH, 1, 2.0)

    assert manager.emulation_triggered is False
    assert emitted == [(PAD_BUTTON_SOUTH, 1)]


@mark.parametrize("partner", [PAD_BUTTON_GUIDE, PAD_BUTTON_START])
def test_sdl_simultaneous_button_combinations(partner: int) -> None:
    app = QApplication.instance() or QApplication([])
    manager: Any = InputManager.__new__(InputManager)
    QObject.__init__(manager)
    manager._parent = SimpleNamespace(refreshGames=MagicMock(), isActiveWindow=lambda: True)
    manager._button_states = {}
    manager.guide_held = manager.select_held = manager.start_held = False
    manager.guide_pressed_time = manager.select_pressed_time = 0
    manager.guide_combination_timeout = 0.3
    manager.in_guide_combination_attempt = False
    manager.guide_timer = SimpleNamespace(start=MagicMock(), stop=MagicMock())
    manager.pending_menu_fullscreen_time = 0.0
    manager._is_gamescope_session = False
    manager.mouse_emulation_enabled = False
    manager.emulation_triggered = False
    manager.button_event.connect(
        lambda code, value: manager._handle_guide_combination(code, 1.0) if value else None,
        Qt.ConnectionType.QueuedConnection,
    )
    pressed: set[int] = set()
    gamepad = cast(SDLGamepad, SimpleNamespace(
        get_button=lambda index: int(input_runtime.SDL_CONTROLLER_BUTTON_TO_PAD[index] in pressed),
    ))
    manager._poll_button_events(gamepad, 0.0)
    app.processEvents()
    for expected_emulation in (True, False):
        pressed.update((PAD_BUTTON_SELECT, partner))
        manager._poll_button_events(gamepad, 1.0)
        app.processEvents()
        assert manager.pending_menu_fullscreen_time == 0.0
        if partner == PAD_BUTTON_START:
            assert manager.emulation_triggered is expected_emulation
            manager._parent.refreshGames.assert_not_called()
        else:
            manager._parent.refreshGames.assert_called_once()
            manager._parent.refreshGames.reset_mock()
        pressed.clear()
        manager._poll_button_events(gamepad, 1.1)
        app.processEvents()


class DummyCard(QFrame):
    def __init__(self, parent: QWidget, x_pos: int) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setGeometry(x_pos, 0, 10, 10)


def test_game_card_navigation_skips_hidden_cards(monkeypatch: MonkeyPatch) -> None:
    app = QApplication.instance() or QApplication([])
    container = QWidget()
    container.show()

    next_card = DummyCard(container, NEXT_CARD_X)
    hidden_card = DummyCard(container, HIDDEN_CARD_X)
    first_card = DummyCard(container, FIRST_CARD_X)
    first_card.show()
    hidden_card.hide()
    next_card.show()
    app.processEvents()

    monkeypatch.setattr(input_manager, "AnimatedCard", DummyCard)
    monkeypatch.setattr(input_dpad, "AnimatedCard", DummyCard)
    manager = InputManager.__new__(InputManager)
    manager._parent = cast(MainWindowProtocol, SimpleNamespace(tabButtons={0: QWidget()}))

    first_card.setFocus(Qt.FocusReason.OtherFocusReason)
    manager._navigate_game_cards(container, 0, PAD_DPAD_X, 1)

    assert QApplication.focusWidget() is next_card

    manager._navigate_game_cards(container, 0, PAD_DPAD_X, -1)

    assert QApplication.focusWidget() is first_card


def test_card_grid_navigation_uses_visual_rows() -> None:
    app = QApplication.instance() or QApplication([])
    container = QWidget()
    container.show()

    bottom_right = DummyCard(container, NEXT_CARD_X)
    bottom_right.move(NEXT_CARD_X, 20)
    top_left = DummyCard(container, FIRST_CARD_X)
    bottom_left = DummyCard(container, FIRST_CARD_X)
    bottom_left.move(FIRST_CARD_X, 20)
    top_right = DummyCard(container, NEXT_CARD_X)
    for card in (bottom_right, top_left, bottom_left, top_right):
        card.show()
    app.processEvents()

    manager = InputManager.__new__(InputManager)
    top_left.setFocus(Qt.FocusReason.OtherFocusReason)

    assert manager._navigate_card_grid(
        [bottom_right, top_left, bottom_left, top_right], PAD_DPAD_X, 1
    )
    assert QApplication.focusWidget() is top_right

    assert manager._navigate_card_grid(
        [bottom_right, top_left, bottom_left, top_right], PAD_DPAD_Y, 1
    )
    assert QApplication.focusWidget() is bottom_right


def test_horizontal_library_navigation_wraps_at_both_ends() -> None:
    app = QApplication.instance() or QApplication([])
    container = QWidget()
    layout = QHBoxLayout(container)
    cards: list[QWidget] = [QPushButton() for _index in range(3)]
    for card in cards:
        layout.addWidget(card)
        card.show()
    container.show()
    app.processEvents()

    manager = InputManager.__new__(InputManager)
    manager._parent = cast(
        MainWindowProtocol,
        SimpleNamespace(
            game_library_manager=SimpleNamespace(
                layout_mode="horizontal",
                gamesListLayout=layout,
            )
        ),
    )
    cards[-1].setFocus(Qt.FocusReason.OtherFocusReason)

    assert manager._navigate_horizontal_library(cards, 0, PAD_DPAD_X, 1)
    assert QApplication.focusWidget() is cards[0]

    assert manager._navigate_horizontal_library(cards, 0, PAD_DPAD_X, -1)
    assert QApplication.focusWidget() is cards[-1]

    tile = FullLibraryTile(_tile_theme())
    tile.setParent(container)
    layout.addWidget(tile)
    tile.show()
    manager._parent.game_library_manager.layout_mode = "horizontal_top"
    manager._parent.game_library_manager.fullLibraryTile = tile
    navigable_cards = [*cards, tile]
    assert manager._navigate_horizontal_library(navigable_cards, 0, PAD_DPAD_X, 1)
    assert QApplication.focusWidget() is tile

    assert manager._navigate_horizontal_library(navigable_cards, 0, PAD_DPAD_X, -1)
    assert QApplication.focusWidget() is cards[-1]

    assert manager._navigate_horizontal_library(navigable_cards, 0, PAD_DPAD_X, 1)
    assert QApplication.focusWidget() is tile

    assert manager._navigate_horizontal_library(navigable_cards, 0, PAD_DPAD_X, 1)
    assert QApplication.focusWidget() is cards[0]


def test_horizontal_autoinstall_navigation_uses_its_layout() -> None:
    app = QApplication.instance() or QApplication([])
    container = QWidget()
    layout = QHBoxLayout(container)
    cards: list[QWidget] = [QPushButton() for _index in range(3)]
    for card in cards:
        layout.addWidget(card)
        card.show()
    container.show()
    app.processEvents()

    manager = InputManager.__new__(InputManager)
    manager._parent = cast(
        MainWindowProtocol,
        SimpleNamespace(
            theme=SimpleNamespace(LIBRARY_LAYOUT_MODE="horizontal"),
            autoInstallContainerLayout=layout,
        ),
    )
    cards[0].setFocus(Qt.FocusReason.OtherFocusReason)

    assert manager._navigate_horizontal_library(cards, 1, PAD_DPAD_X, 1)
    assert QApplication.focusWidget() is cards[1]


def test_full_library_tile_arrow_does_not_switch_tabs() -> None:
    app = QApplication.instance() or QApplication([])
    tile = FullLibraryTile(_tile_theme())
    tile.show()
    tile.setFocus(Qt.FocusReason.OtherFocusReason)
    app.processEvents()
    manager = InputManager.__new__(InputManager)
    manager.file_explorer = None
    switch_tab = MagicMock()
    manager._parent = cast(
        MainWindowProtocol,
        SimpleNamespace(switchTab=switch_tab),
    )

    assert not manager._handle_input_tab_key(KEY_LEFT)
    switch_tab.assert_not_called()


def test_backspace_uses_standard_back_navigation() -> None:
    manager = InputManager.__new__(InputManager)
    standard_back = MagicMock()
    cast(Any, manager)._handle_standard_back = standard_back

    assert manager._handle_input_back_key(QWidget())
    standard_back.assert_called_once_with()


def test_library_toolbar_navigation_includes_delete_missing_button() -> None:
    app = QApplication.instance() or QApplication([])
    toolbar = QWidget()
    toolbar.show()

    widgets = []
    for _index in range(5):
        widget = QWidget(toolbar)
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        widget.show()
        widgets.append(widget)
    app.processEvents()

    parent = SimpleNamespace(
        quickLaunchButton=widgets[0],
        addGameButton=widgets[1],
        searchEdit=widgets[2],
        refreshButton=widgets[3],
        deleteMissingExeButton=widgets[4],
        libraryControlsButton=QWidget(toolbar),
        stackedWidget=QStackedWidget(),
        tabButtons={0: QWidget()},
    )
    parent.stackedWidget.addWidget(QWidget())
    manager = InputManager.__new__(InputManager)
    manager._parent = cast(MainWindowProtocol, parent)

    widgets[3].setFocus(Qt.FocusReason.OtherFocusReason)
    handled = manager._handle_toolbar_navigation(PAD_DPAD_X, 1)

    assert handled is True
    assert QApplication.focusWidget() is widgets[4]


def test_library_filter_navigation_includes_only_installed_checkbox() -> None:
    app = QApplication.instance() or QApplication([])
    controls = QWidget()
    controls.show()
    widgets = [QComboBox(controls) for _ in range(4)] + [QCheckBox(controls)]
    for widget in widgets:
        widget.show()
    app.processEvents()

    parent = SimpleNamespace(
        libraryControlsWidget=controls,
        gamesSortCombo=widgets[0],
        gamesDisplayCombo=widgets[1],
        gamesBadgeViewCombo=widgets[2],
        gamesLayoutCombo=widgets[3],
        onlyInstalledCheckBox=widgets[4],
        stackedWidget=SimpleNamespace(currentIndex=lambda: 0),
        libraryControlsButton=QWidget(controls),
    )
    parent.libraryControlsButton.show()
    manager = InputManager.__new__(InputManager)
    manager._parent = cast(MainWindowProtocol, parent)

    assert manager._get_library_filter_widgets() == widgets
    manager._get_library_toolbar_widgets = lambda: []
    manager._focused_widget = QApplication.focusWidget
    manager._focus_first_library_card = MagicMock(return_value=True)
    widgets[0].setFocus()
    for widget in widgets[1:]:
        assert manager._handle_toolbar_navigation(PAD_DPAD_Y, 1)
        assert QApplication.focusWidget() is widget
    assert manager._handle_toolbar_navigation(PAD_DPAD_Y, 1)
    manager._focus_first_library_card.assert_called_once()
    for widget in reversed(widgets[:-1]):
        assert manager._handle_toolbar_navigation(PAD_DPAD_Y, -1)
        assert QApplication.focusWidget() is widget
    assert manager._handle_toolbar_navigation(PAD_DPAD_Y, -1)
    assert QApplication.focusWidget() is parent.libraryControlsButton
    widgets[-1].hide()
    assert manager._get_library_filter_widgets() == widgets[:-1]
    controls.close()


def test_library_size_adjustment_uses_original_step() -> None:
    app = QApplication.instance() or QApplication([])
    slider = QSlider()
    slider.setRange(100, 300)
    slider.setValue(200)
    slider.setTickInterval(25)
    callbacks: list[bool] = []
    parent = SimpleNamespace(
        stackedWidget=SimpleNamespace(currentIndex=lambda: 0),
        system_tab_index=4,
        game_library_manager=SimpleNamespace(sizeSlider=slider),
        on_slider_released=lambda: callbacks.append(True),
    )
    manager = InputManager.__new__(InputManager)
    manager._parent = cast(MainWindowProtocol, parent)

    assert manager._adjust_active_slider(1)
    assert slider.value() == 210
    assert callbacks == [True]
    assert app is not None


def test_system_volume_adjustment_uses_original_step() -> None:
    app = QApplication.instance() or QApplication([])
    section_stack = QStackedWidget()
    for _index in range(5):
        section_stack.addWidget(QWidget())
    section_stack.setCurrentIndex(4)
    slider = QSlider()
    slider.setRange(0, 100)
    slider.setValue(50)
    slider.setPageStep(17)
    callbacks: list[bool] = []
    parent = SimpleNamespace(
        stackedWidget=SimpleNamespace(currentIndex=lambda: 3),
        system_tab_index=3,
        systemSectionStack=section_stack,
        audioVolumeSlider=slider,
        _applySelectedAudioVolume=lambda: callbacks.append(True),
    )
    manager = InputManager.__new__(InputManager)
    manager._parent = cast(MainWindowProtocol, parent)

    assert manager._adjust_active_slider(-1)
    assert slider.value() == 45
    assert callbacks == [True]
    assert app is not None


def test_context_menu_button_routes_to_table_current_item() -> None:
    app = QApplication.instance() or QApplication([])
    table = QTableWidget(1, 1)
    table.setItem(0, 0, QTableWidgetItem("Game"))
    table.setCurrentCell(0, 0)
    emitted = []
    table.customContextMenuRequested.connect(emitted.append)
    manager = InputManager.__new__(InputManager)
    context_button = next(iter(input_manager.BUTTONS["context_menu"]))

    assert manager._open_focused_context_menu(table, context_button)
    item = table.item(0, 0)
    assert item is not None
    assert emitted == [table.visualItemRect(item).center()]
    assert app is not None


def test_context_menu_button_ignores_widget_without_custom_menu() -> None:
    app = QApplication.instance() or QApplication([])
    widget = QWidget()
    manager = InputManager.__new__(InputManager)
    context_button = next(iter(input_manager.BUTTONS["context_menu"]))

    assert not manager._open_focused_context_menu(widget, context_button)
    assert app is not None


def test_popup_menu_buttons_activate_and_close_menu() -> None:
    app = QApplication.instance() or QApplication([])
    menu = QMenu()
    action = menu.addAction("Launch")
    triggered = []
    action.triggered.connect(lambda: triggered.append(True))
    menu.setActiveAction(action)
    manager = InputManager.__new__(InputManager)
    confirm_button = next(iter(input_manager.BUTTONS["confirm"]))
    back_button = next(iter(input_manager.BUTTONS["back"]))

    assert manager._handle_popup_menu_button(menu, confirm_button)
    assert manager._handle_popup_menu_button(menu, back_button)
    assert triggered == [True]
    assert app is not None


def test_confirm_button_opens_combo_popup() -> None:
    app = QApplication.instance() or QApplication([])
    combo = QComboBox()
    combo.addItems(["First", "Second"])
    manager = InputManager.__new__(InputManager)
    confirm_button = next(iter(input_manager.BUTTONS["confirm"]))

    assert manager._handle_combo_button(combo, confirm_button)
    assert combo.view().isVisible()
    combo.hidePopup()
    assert app is not None


@mark.parametrize("table_name", ["advanced_table", "favorites_table"])
def test_settings_gamepad_skips_separator_and_activates_download(
    monkeypatch: MonkeyPatch, table_name: str,
) -> None:
    from portprotonqt.dialogs.settings_dialog import ExeSettingsDialog
    from portprotonqt.input_manager.constants import BUTTONS
    from portprotonqt.input_manager.settings import SettingsInputMixin

    app = QApplication.instance() or QApplication([])
    dialog = QDialog()
    table = QTableWidget(1, 2, dialog)
    combo = QComboBox()
    combo.addItem("Proton")
    combo.insertSeparator(1)
    combo.addItem("Download Wine/Proton...", "download_wine")
    table.setCellWidget(0, 1, combo)
    table.setCurrentCell(0, 1)
    highlighted = []
    combo.highlighted.connect(highlighted.append)
    settings = SimpleNamespace(
        original_display_values={"PW_WINE_USE": "Proton"},
        portproton_path=None, input_manager=None,
    )
    opened = MagicMock()
    monkeypatch.setattr("portprotonqt.dialogs.settings_dialog.show_proton_manager", opened)
    combo.activated.connect(lambda index: ExeSettingsDialog._open_wine_manager_from_combo(
        cast(ExeSettingsDialog, settings), index, combo, "PW_WINE_USE",
    ))
    manager = SimpleNamespace(
        settings_dialog=SimpleNamespace(advanced_table=None, settings_table=None, favorites_table=None),
        _is_current_settings_tool_tab=lambda: False,
        _handle_table_action_navigation=lambda *_args: False,
        _get_dialog_action_buttons=lambda _dialog: [],
        _get_current_settings_table=lambda: table,
        _get_open_settings_combo=lambda: combo,
        _handle_common_ui_elements=lambda _code: False,
    )
    setattr(manager.settings_dialog, table_name, table)
    dialog.show()
    combo.showPopup()
    app.processEvents()
    SettingsInputMixin.handle_settings_dpad(cast(SettingsInputMixin, manager), PAD_DPAD_Y, 1, 0)
    assert combo.view().currentIndex().row() == 2
    assert combo.currentText() == "Proton"
    SettingsInputMixin.handle_settings_button(
        cast(SettingsInputMixin, manager), next(iter(BUTTONS["confirm"])), 1,
    )
    opened.assert_called_once()
    assert combo.currentText() == "Proton"
    assert not combo.view().isVisible()
    dialog.close()


def test_settings_combo_navigation_with_keyboard_events_intercepted() -> None:
    from portprotonqt.input_manager.settings import SettingsInputMixin

    class KeyFilter(QObject):
        def eventFilter(self, obj: QObject, event: QEvent) -> bool:
            return event.type() == QEvent.Type.KeyPress

    app = QApplication.instance() or QApplication([])
    dialog = QDialog()
    table = QTableWidget(1, 2, dialog)
    combo = QComboBox()
    combo.addItems(["First", "Second", "Third"])
    table.setCellWidget(0, 1, combo)
    table.setCurrentCell(0, 1)
    manager = SimpleNamespace(
        settings_dialog=SimpleNamespace(advanced_table=table, settings_table=None),
        _is_current_settings_tool_tab=lambda: False,
        _handle_table_action_navigation=lambda *_args: False,
        _get_dialog_action_buttons=lambda _dialog: [],
        _get_current_settings_table=lambda: table,
    )
    key_filter = KeyFilter()
    app.installEventFilter(key_filter)
    try:
        dialog.show()
        combo.showPopup()
        app.processEvents()
        for direction, expected in ((1, 1), (1, 2), (1, 2), (-1, 1), (-1, 0), (-1, 0)):
            SettingsInputMixin.handle_settings_dpad(cast(SettingsInputMixin, manager), PAD_DPAD_Y, direction, 0)
            assert combo.currentIndex() == 0
            assert combo.view().currentIndex().row() == expected
            assert combo.view().isVisible()
    finally:
        app.removeEventFilter(key_filter)
        combo.hidePopup()
        dialog.close()


def test_user_conf_table_combo_gets_focus_and_opens() -> None:
    app = QApplication.instance() or QApplication([])
    table = QTableWidget(1, 2)
    combo = QComboBox()
    combo.addItems(["Default", "Yes", "No"])
    table.setCellWidget(0, 1, combo)
    table.setCurrentCell(0, 1)
    table.show()
    combo.show()
    app.processEvents()
    manager = InputManager.__new__(InputManager)
    manager.settings_dialog = SimpleNamespace(settings_table=table)

    manager._focus_settings_advanced_value_widget(table, 0)
    assert QApplication.focusWidget() is combo
    assert manager.handle_table_confirm(table)
    assert combo.view().isVisible()
    combo.hidePopup()
    assert app is not None


def test_back_button_closes_visible_combo_popup() -> None:
    app = QApplication.instance() or QApplication([])
    combo = QComboBox()
    combo.addItems(["First", "Second"])
    combo.showPopup()
    manager = InputManager.__new__(InputManager)
    back_button = next(iter(input_manager.BUTTONS["back"]))

    assert manager._handle_combo_button(combo, back_button)
    assert not combo.view().isVisible()
    assert app is not None


def test_list_confirm_emits_selection_actions() -> None:
    app = QApplication.instance() or QApplication([])
    view = QListView()
    model = QStringListModel(["First", "Second"])
    view.setModel(model)
    view.setCurrentIndex(model.index(1, 0))
    activated = []
    clicked = []
    view.activated.connect(activated.append)
    view.clicked.connect(clicked.append)
    manager = InputManager.__new__(InputManager)

    manager._activate_list_view_selection(view)

    assert [index.row() for index in activated] == [1]
    assert [index.row() for index in clicked] == [1]
    assert app is not None


def test_list_back_preserves_dialog_fallthrough() -> None:
    app = QApplication.instance() or QApplication([])
    view = QListView()
    model = QStringListModel(["First"])
    view.setModel(model)
    view.setCurrentIndex(model.index(0, 0))
    manager = InputManager.__new__(InputManager)
    back_button = next(iter(input_manager.BUTTONS["back"]))

    assert not manager._handle_list_view_button(view, back_button)
    assert not view.selectionModel().hasSelection()
    assert app is not None


def test_system_table_button_routes_action_and_sound(monkeypatch: MonkeyPatch) -> None:
    app = QApplication.instance() or QApplication([])
    actions = []
    sounds = []
    manager = InputManager.__new__(InputManager)
    manager._parent = cast(
        MainWindowProtocol,
        SimpleNamespace(
            handleSystemTableGamepadAction=lambda _table, action: actions.append(action) or True,
        ),
    )
    monkeypatch.setattr(input_manager, "SoundManager", lambda: SimpleNamespace(play=sounds.append))
    monkeypatch.setattr(input_buttons, "SoundManager", lambda: SimpleNamespace(play=sounds.append))
    table = QTableWidget()
    back_button = next(iter(input_manager.BUTTONS["back"]))

    assert manager._handle_system_table_button(table, back_button)
    assert actions == ["back"]
    assert sounds == ["back"]
    assert app is not None


def test_confirm_button_activates_table_callback(monkeypatch: MonkeyPatch) -> None:
    app = QApplication.instance() or QApplication([])
    table = QTableWidget(1, 1)
    table.setItem(0, 0, QTableWidgetItem("Game"))
    table.setCurrentCell(0, 0)
    activated = []
    table._on_confirm_callback = lambda _table, row, column: activated.append(  # type: ignore[attr-defined]
        (row, column)
    )
    manager = InputManager.__new__(InputManager)
    monkeypatch.setattr(
        input_buttons, "SoundManager", lambda: SimpleNamespace(play=lambda _sound: None)
    )
    confirm_button = next(iter(input_manager.BUTTONS["confirm"]))

    assert manager._handle_table_button(table, confirm_button)

    assert activated == [(0, 0)]
    assert app is not None


def test_confirm_button_routes_line_edit_to_keyboard() -> None:
    app = QApplication.instance() or QApplication([])
    shown_for = []
    manager = InputManager.__new__(InputManager)
    manager._parent = cast(
        MainWindowProtocol,
        SimpleNamespace(keyboard=SimpleNamespace(show_for_widget=shown_for.append)),
    )
    line_edit = QLineEdit()
    confirm_button = next(iter(input_manager.BUTTONS["confirm"]))

    assert manager._route_button_to_text_input(QWidget(), line_edit, confirm_button)
    assert shown_for == [line_edit]
    assert app is not None


def test_prev_dir_button_focuses_search_for_current_tab() -> None:
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    search = QLineEdit(window)
    window.show()
    search.show()
    app.processEvents()
    manager = InputManager.__new__(InputManager)
    manager._parent = cast(
        MainWindowProtocol,
        SimpleNamespace(
            keyboard=None,
            stackedWidget=SimpleNamespace(currentIndex=lambda: 0),
            searchEdit=search,
        ),
    )
    prev_dir_button = next(iter(input_manager.BUTTONS["prev_dir"]))

    assert manager._route_button_to_text_input(window, None, prev_dir_button)
    assert search.hasFocus()


def test_system_quick_button_routes_add_game_and_sound(monkeypatch: MonkeyPatch) -> None:
    actions = []
    sounds = []
    manager = InputManager.__new__(InputManager)
    manager._parent = cast(
        MainWindowProtocol,
        SimpleNamespace(handleSystemGamepadAction=lambda action: actions.append(action) or True),
    )
    monkeypatch.setattr(input_manager, "SoundManager", lambda: SimpleNamespace(play=sounds.append))
    monkeypatch.setattr(input_buttons, "SoundManager", lambda: SimpleNamespace(play=sounds.append))
    add_button = next(iter(input_manager.BUTTONS["add_game"]))

    assert manager._handle_system_quick_button(add_button)
    assert actions == ["add_game"]
    assert sounds == ["open"]


def test_standard_confirm_activates_focused_widget(monkeypatch: MonkeyPatch) -> None:
    app = QApplication.instance() or QApplication([])
    activations = []
    sounds = []
    focused = QWidget()
    manager = InputManager.__new__(InputManager)
    manager._parent = cast(
        MainWindowProtocol,
        SimpleNamespace(activateFocusedWidget=lambda: activations.append(True)),
    )
    monkeypatch.setattr(
        input_manager,
        "SoundManager",
        lambda: SimpleNamespace(play_widget_sound=sounds.append),
    )
    monkeypatch.setattr(
        input_buttons,
        "SoundManager",
        lambda: SimpleNamespace(play_widget_sound=sounds.append),
    )
    confirm_button = next(iter(input_manager.BUTTONS["confirm"]))

    manager._handle_standard_button(focused, confirm_button, 1)

    assert activations == []
    app.processEvents()
    assert activations == [True]
    assert sounds == [focused]


def test_guide_select_combination_refreshes_games() -> None:
    timer_events: list[str | int] = []
    refreshes: list[bool] = []
    manager: Any = InputManager.__new__(InputManager)
    manager._parent = cast(
        MainWindowProtocol,
        SimpleNamespace(refreshGames=lambda: refreshes.append(True)),
    )
    manager.guide_timer = SimpleNamespace(
        start=lambda timeout: timer_events.append(timeout),
        stop=lambda: timer_events.append("stop"),
    )
    manager.guide_combination_timeout = 0.3
    manager.guide_held = False
    manager.guide_pressed_time = 0
    manager.select_pressed_time = 0
    manager.in_guide_combination_attempt = False
    guide_button = next(iter(input_manager.BUTTONS["guide"]))
    menu_button = next(iter(input_manager.BUTTONS["menu"]))

    assert manager._handle_guide_combination(guide_button, 1.0)
    assert manager._handle_guide_combination(menu_button, 1.2)

    assert timer_events == [300, "stop"]
    assert refreshes == [True]
    assert manager.guide_held is False


def test_dialog_surface_receives_connected_input_signals() -> None:
    app = QApplication.instance() or QApplication([])
    button_events: list[tuple[int, int]] = []
    dpad_events: list[tuple[int, int, float]] = []
    default_events: list[tuple[int, int]] = []
    manager: Any = InputManager.__new__(InputManager)
    QObject.__init__(manager)
    manager._parent = SimpleNamespace(boot_animation=None)
    manager._input_surfaces = []
    manager._input_surface_base_state = None
    manager._gamepad_handling_enabled = False
    manager.dpad_timer = SimpleNamespace(stop=lambda: None)
    manager.current_dpad_code = None
    manager.current_dpad_value = 0
    manager._handle_default_button = lambda code, value: default_events.append((code, value))
    manager.button_event.connect(manager.handle_button_slot)
    manager.dpad_moved.connect(manager.handle_dpad_slot)

    manager._setup_mode_handlers(
        object(),
        lambda code, value: button_events.append((code, value)),
        lambda code, value, now: dpad_events.append((code, value, now)),
        "settings_dialog",
    )
    manager.button_event.emit(1, 1)
    manager.dpad_moved.emit(PAD_DPAD_Y, 1, 2.0)

    assert button_events == [(1, 1)]
    assert dpad_events == [(PAD_DPAD_Y, 1, 2.0)]
    assert default_events == []
    manager._restore_original_handlers("settings_dialog")
    manager.button_event.emit(2, 1)
    assert default_events == [(2, 1)]
    assert app is not None


def test_gamepad_ui_events_are_queued_after_polling() -> None:
    app = QApplication.instance() or QApplication([])
    events: list[tuple[int, int]] = []
    manager: Any = InputManager.__new__(InputManager)
    QObject.__init__(manager)
    manager._parent = SimpleNamespace(boot_animation=None)
    manager._input_surfaces = []
    manager._handle_default_button = lambda code, value: events.append((code, value))
    manager.button_event.connect(
        manager.handle_button_slot,
        Qt.ConnectionType.QueuedConnection,
    )

    manager.button_event.emit(1, 1)

    assert events == []
    app.processEvents()
    assert events == [(1, 1)]


def test_dialog_surface_disconnects_owned_callbacks() -> None:
    callback_events: list[tuple[int, ...]] = []
    manager: Any = InputManager.__new__(InputManager)
    QObject.__init__(manager)
    manager._input_surfaces = []
    manager._input_surface_base_state = None
    manager._gamepad_handling_enabled = False
    manager.dpad_timer = SimpleNamespace(stop=lambda: None)
    manager.current_dpad_code = None
    manager.current_dpad_value = 0
    manager._setup_mode_handlers(object(), lambda *_args: None, lambda *_args: None, "dialog")
    manager.connect_surface_updates("dialog", lambda *args: callback_events.append(args))

    manager.button_event.emit(1, 1)
    manager._restore_original_handlers("dialog")
    manager.button_event.emit(2, 1)
    manager.dpad_moved.emit(PAD_DPAD_Y, 1, 2.0)

    assert callback_events == [(1, 1)]


def test_nested_input_surfaces_restore_base_state() -> None:
    manager: Any = InputManager.__new__(InputManager)
    manager._input_surfaces = []
    manager._input_surface_base_state = None
    manager._gamepad_handling_enabled = False
    manager.dpad_timer = SimpleNamespace(stop=lambda: None)
    manager.current_dpad_code = None
    manager.current_dpad_value = 0
    first_events: list[int] = []
    second_events: list[int] = []

    manager._setup_mode_handlers(
        object(), lambda code, _value: first_events.append(code), lambda *_args: None,
        "settings_dialog",
    )
    manager._setup_mode_handlers(
        object(), lambda code, _value: second_events.append(code), lambda *_args: None,
        "file_explorer",
    )
    manager._restore_original_handlers("settings_dialog")
    assert manager._route_surface_button(1, 1)
    assert first_events == []
    assert second_events == [1]
    assert manager._gamepad_handling_enabled is True

    manager._restore_original_handlers("file_explorer")
    assert manager._gamepad_handling_enabled is False
    assert not manager._route_surface_button(2, 1)


def test_gamepad_polling_uses_qt_event_loop() -> None:
    app = QApplication.instance() or QApplication([])
    checks: list[bool] = []
    manager: Any = InputManager.__new__(InputManager)
    QObject.__init__(manager)
    manager.check_gamepad = lambda: checks.append(True)
    manager.gamepad_hotplug.connect(lambda _action: None)

    manager.init_gamepad()

    assert checks == [True]
    assert manager.gamepad_poll_timer.isActive()
    assert manager.gamepad_poll_timer.interval() == 10
    assert manager.gamepad_poll_timer.thread() is manager.thread()
    manager.gamepad_poll_timer.stop()
    assert app is not None


def test_gamepad_poll_reports_disconnected_device() -> None:
    actions: list[str] = []
    updates: list[bool] = []
    manager: Any = InputManager.__new__(InputManager)
    QObject.__init__(manager)
    manager.running = True
    manager._gamepad_polling_suspended = False
    manager.gamepad = SimpleNamespace(
        update=lambda: updates.append(True),
        connected=lambda: False,
    )
    manager.gamepad_hotplug.connect(actions.append)

    manager._poll_gamepad()

    assert updates == [True]
    assert actions == ["remove"]


def test_gamepad_poll_refreshes_type_when_active_device_changes(
    monkeypatch: MonkeyPatch,
) -> None:
    refreshed: list[bool] = []
    manager: Any = InputManager.__new__(InputManager)
    manager.running = True
    manager._gamepad_polling_suspended = False
    manager.gamepad = SimpleNamespace(
        update=lambda: True,
        connected=lambda: True,
        active_instance_id=7,
        sdl_type=SDL_GAMEPAD_TYPE_PS5,
    )
    manager._reset_input_state = lambda: setattr(
        manager, "gamepad_type", GamepadType.UNKNOWN,
    )
    manager._refresh_gamepad_ui = lambda: refreshed.append(True)
    manager._poll_button_events = lambda *_args: None
    manager._handle_pending_menu_fullscreen = lambda *_args: None
    manager._poll_hat_events = lambda *_args: None
    manager._poll_axis_events = lambda *_args: None
    manager.last_update = 0.0
    manager.update_interval = float("inf")
    monkeypatch.setattr(input_runtime.gamepad_config, "get_gamepad_type", lambda: "auto")

    manager._poll_gamepad()

    assert manager.gamepad_type == GamepadType.PLAYSTATION
    assert refreshed == [True]


def test_suspend_gamepad_polling_sets_runtime_guard() -> None:
    manager: Any = InputManager.__new__(InputManager)
    manager._gamepad_polling_suspended = False
    manager._gamepad_handling_enabled = True
    manager.dpad_timer = SimpleNamespace(stop=lambda: None)
    manager.nav_timer = SimpleNamespace(stop=lambda: None)

    manager.suspend_gamepad_polling()

    assert manager._gamepad_polling_suspended is True
    assert manager._gamepad_handling_enabled is False


def test_dialog_dpad_moves_focus_forward() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = QDialog()
    first_button = QPushButton(dialog)
    second_button = QPushButton(dialog)
    first_button.move(0, 0)
    second_button.move(0, 30)
    dialog.show()
    first_button.show()
    second_button.show()
    app.processEvents()
    first_button.setFocus(Qt.FocusReason.OtherFocusReason)
    manager = InputManager.__new__(InputManager)

    assert manager._handle_dialog_dpad(dialog, PAD_DPAD_Y, 1)
    assert QApplication.focusWidget() is second_button


def test_list_dpad_moves_current_row() -> None:
    app = QApplication.instance() or QApplication([])
    view = QListView()
    model = QStringListModel(["First", "Second"])
    view.setModel(model)
    view.setCurrentIndex(model.index(0, 0))
    manager = InputManager.__new__(InputManager)

    assert manager._handle_list_dpad(view, PAD_DPAD_Y, 1)
    assert view.currentIndex().row() == 1
    assert app is not None


def test_first_card_row_moves_focus_to_toolbar(monkeypatch: MonkeyPatch) -> None:
    app = QApplication.instance() or QApplication([])
    container = QWidget()
    container.show()
    card = DummyCard(container, FIRST_CARD_X)
    toolbar_button = QWidget(container)
    toolbar_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    toolbar_button.move(0, 30)
    toolbar_button.show()
    card.show()
    app.processEvents()
    card.setFocus(Qt.FocusReason.OtherFocusReason)
    monkeypatch.setattr(input_manager, "AnimatedCard", DummyCard)
    monkeypatch.setattr(input_dpad, "AnimatedCard", DummyCard)
    parent = SimpleNamespace(
        stackedWidget=SimpleNamespace(currentIndex=lambda: 0),
        gamesListWidget=container,
    )
    manager: Any = InputManager.__new__(InputManager)
    manager._parent = cast(MainWindowProtocol, parent)
    manager._get_library_toolbar_widgets = lambda: [toolbar_button]

    assert manager._focus_toolbar_from_first_card(PAD_DPAD_Y, -1)
    assert QApplication.focusWidget() is toolbar_button


def test_system_section_horizontal_focuses_selected_button() -> None:
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    section_stack = QStackedWidget(window)
    section_stack.addWidget(QWidget())
    section_stack.addWidget(QWidget())
    section_buttons = [QPushButton(window), QPushButton(window)]
    section_buttons[1].move(0, 30)
    window.show()
    section_buttons[0].show()
    section_buttons[1].show()
    app.processEvents()
    switched: list[int] = []

    def switch_relative(step: int) -> bool:
        switched.append(step)
        section_stack.setCurrentIndex(1)
        return True

    parent = SimpleNamespace(
        stackedWidget=SimpleNamespace(currentIndex=lambda: 3),
        system_tab_index=3,
        switchSystemSectionRelative=switch_relative,
        systemSectionStack=section_stack,
        systemSectionButtons=section_buttons,
    )
    manager = InputManager.__new__(InputManager)
    manager._parent = cast(MainWindowProtocol, parent)

    assert manager._handle_system_section_horizontal(PAD_DPAD_X, 1, True)
    assert switched == [1]
    assert section_buttons[1].hasFocus()
    assert app is not None


def test_detail_page_dpad_uses_visual_button_rows(monkeypatch: MonkeyPatch) -> None:
    app = QApplication.instance() or QApplication([])
    page = QWidget()
    buttons = [QPushButton(page) for _index in range(3)]
    buttons[0].setGeometry(0, 0, 20, 20)
    buttons[1].setGeometry(40, 0, 20, 20)
    buttons[2].setGeometry(0, 40, 20, 20)
    page.show()
    for button in buttons:
        button.show()
    app.processEvents()
    buttons[1].setFocus(Qt.FocusReason.OtherFocusReason)
    monkeypatch.setattr(input_dpad, "AutoSizeButton", QPushButton)
    manager = InputManager.__new__(InputManager)
    manager._parent = cast(
        MainWindowProtocol,
        SimpleNamespace(
            stackedWidget=SimpleNamespace(currentWidget=lambda: page),
            currentDetailPage=page,
        ),
    )

    assert manager._handle_detail_page_dpad(PAD_DPAD_Y, 1)
    assert QApplication.focusWidget() is buttons[2]


def test_page_vertical_dpad_moves_focus_forward() -> None:
    app = QApplication.instance() or QApplication([])
    page = QWidget()
    first = QPushButton(page)
    second = QPushButton(page)
    second.move(0, 30)
    page.show()
    first.show()
    second.show()
    app.processEvents()
    first.setFocus(Qt.FocusReason.OtherFocusReason)
    manager = InputManager.__new__(InputManager)
    manager._parent = cast(
        MainWindowProtocol,
        SimpleNamespace(stackedWidget=SimpleNamespace(currentWidget=lambda: page)),
    )

    assert manager._handle_page_vertical_dpad(PAD_DPAD_Y, 1)
    assert QApplication.focusWidget() is second


def test_settings_grid_vertical_navigation_does_not_wrap_columns() -> None:
    _app = QApplication.instance() or QApplication([])
    dialog = QWidget()
    checkboxes: list[QWidget] = [QCheckBox(dialog) for _index in range(4)]
    for checkbox, position in zip(
        checkboxes, ((0, 0), (100, 0), (0, 40), (100, 40)), strict=True
    ):
        checkbox.move(*position)
    manager = InputManager.__new__(InputManager)
    manager.settings_dialog = dialog

    assert manager._find_mangohud_vertical_grid_target(
        checkboxes[0], 1, checkboxes
    ) is checkboxes[2]
    assert manager._find_mangohud_vertical_grid_target(
        checkboxes[2], 1, checkboxes
    ) is None
    assert manager._find_mangohud_vertical_grid_target(
        checkboxes[1], -1, checkboxes
    ) is None


@mark.parametrize("tool_tab", [False, True])
def test_settings_gamepad_reaches_clear_ppdb(monkeypatch: MonkeyPatch, tool_tab: bool) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = QDialog()
    layout = QHBoxLayout(dialog)
    table = QTableWidget(1, 2)
    table.setCurrentCell(0, 1)
    layout.addWidget(table)
    buttons = [QPushButton(name) for name in ("Apply", "Cancel", "Edit", "Clear")]
    for button in buttons:
        layout.addWidget(button)
    manager = InputManager.__new__(InputManager)
    settings = SimpleNamespace(
        keyboard=None, advanced_table=table, settings_table=table,
        mangohud_fps_widgets={}, mangohud_toggle_widgets={},
        tab_widget=SimpleNamespace(currentWidget=lambda: table),
        apply_button=buttons[0], cancel_button=buttons[1],
        open_ppdb_button=buttons[2], clear_ppdb_button=buttons[3],
    )
    for name, value in vars(settings).items():
        setattr(dialog, name, value)
    manager.settings_dialog = cast(Any, dialog)
    manager.dpad_timer = MagicMock()
    manager.current_dpad_code = None
    manager.current_dpad_value = 0
    monkeypatch.setattr(manager, "_get_current_settings_table", lambda: table)
    monkeypatch.setattr(manager, "_is_current_settings_tool_tab", lambda: tool_tab)
    monkeypatch.setattr(manager, "_get_open_settings_combo", lambda: None)
    monkeypatch.setattr(manager, "_get_mangohud_nav_sections", lambda: [[table]])
    monkeypatch.setattr(manager, "_handle_common_ui_elements", lambda _code: False)
    clicked = MagicMock()
    buttons[3].clicked.connect(clicked)
    dialog.show()
    table.setFocus()
    app.processEvents()
    manager.handle_settings_dpad(PAD_DPAD_Y, 1, 0)
    assert QApplication.focusWidget() is buttons[0]
    for button in buttons[1:]:
        manager.handle_settings_dpad(PAD_DPAD_X, 1, 0)
        assert QApplication.focusWidget() is button
    manager.handle_settings_button(next(iter(input_manager.BUTTONS["confirm"])), 1)
    clicked.assert_called_once()
    manager.handle_settings_dpad(PAD_DPAD_Y, -1, 0)
    assert QApplication.focusWidget() is table
    dialog.close()


@mark.parametrize("mode", ["winetricks", "proton_manager"])
@mark.parametrize("empty", [False, True])
def test_manager_gamepad_table_actions(mode: str, empty: bool, monkeypatch: MonkeyPatch) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = QDialog()
    layout = QHBoxLayout(dialog)
    table = QTableWidget(0 if empty else 2, 1)
    layout.addWidget(table)
    if not empty:
        table.setCurrentCell(0, 0)
        table.setRowHidden(1, True)
    buttons = [QPushButton(name) for name in ("First", "Disabled", "Last")]
    for button in buttons:
        layout.addWidget(button)
    buttons[1].setEnabled(False)
    manager = InputManager.__new__(InputManager)
    setattr(manager, mode + "_dialog", dialog)
    manager.dpad_timer = MagicMock()
    manager.current_dpad_code = None
    manager.current_dpad_value = 0
    monkeypatch.setattr(manager, "_handle_common_ui_elements", lambda _code: False)
    clicked = MagicMock()
    buttons[-1].clicked.connect(clicked)
    navigate = getattr(manager, "handle_" + mode + "_dpad")
    confirm = getattr(manager, "handle_" + mode + "_button")
    dialog.show()
    table.setFocus()
    app.processEvents()
    navigate(PAD_DPAD_Y, 1, 0)
    assert QApplication.focusWidget() is buttons[0]
    navigate(PAD_DPAD_X, 1, 0)
    assert QApplication.focusWidget() is buttons[-1]
    confirm(next(iter(input_manager.BUTTONS["confirm"])), 1)
    clicked.assert_called_once()
    navigate(PAD_DPAD_X, -1, 0)
    assert QApplication.focusWidget() is buttons[0]
    navigate(PAD_DPAD_Y, -1, 0)
    assert QApplication.focusWidget() is table
    dialog.close()


@mark.parametrize("tool", ["mangohud", "vkbasalt", "gamescope"])
def test_settings_tool_gamepad_reaches_action_buttons(tool: str, monkeypatch: MonkeyPatch) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = cast(Any, QDialog())
    layout = QHBoxLayout(dialog)
    tool_tab = QWidget()
    tool_layout = QHBoxLayout(tool_tab)
    control = QLineEdit()
    tool_layout.addWidget(control)
    layout.addWidget(tool_tab)
    button = QPushButton("Clear")
    layout.addWidget(button)
    dialog.keyboard = None
    dialog.tab_widget = SimpleNamespace(currentWidget=lambda: tool_tab)
    setattr(dialog, tool + "_tab", tool_tab)
    dialog.mangohud_widgets = {}
    dialog.mangohud_fps_widgets = {}
    manager = InputManager.__new__(InputManager)
    manager.settings_dialog = dialog
    manager.dpad_timer = MagicMock()
    manager.current_dpad_code = None
    manager.current_dpad_value = 0
    monkeypatch.setattr(manager, "_get_current_settings_table", lambda: None)
    monkeypatch.setattr(manager, "_get_open_settings_combo", lambda: None)
    monkeypatch.setattr(manager, "_get_mangohud_nav_sections", lambda: [[control]])
    dialog.show()
    control.setFocus()
    app.processEvents()
    manager.handle_settings_dpad(PAD_DPAD_Y, 1, 0)
    assert QApplication.focusWidget() is button
    manager.handle_settings_dpad(PAD_DPAD_Y, -1, 0)
    assert QApplication.focusWidget() is control
    dialog.close()


def test_confirm_in_dialog_uses_its_own_keyboard() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = cast(Any, QDialog())
    field = QLineEdit(dialog)
    shown_for = []
    dialog.keyboard = SimpleNamespace(show_for_widget=shown_for.append)
    main_keyboard = MagicMock()
    manager = InputManager.__new__(InputManager)
    manager._parent = cast(MainWindowProtocol, SimpleNamespace(keyboard=main_keyboard))
    confirm = next(iter(input_manager.BUTTONS["confirm"]))

    assert manager._route_button_to_text_input(dialog, field, confirm)
    assert shown_for == [field]
    main_keyboard.show_for_widget.assert_not_called()
    assert app is not None


def test_dpad_stays_on_active_dialog_keyboard(monkeypatch: MonkeyPatch) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = cast(Any, QDialog())
    field = QLineEdit(dialog)
    key = QPushButton("Key", dialog)
    key.move(0, 40)
    down = MagicMock(side_effect=key.setFocus)
    dialog.keyboard = SimpleNamespace(isVisible=lambda: True, move_focus_left=MagicMock(), move_focus_right=MagicMock(),
                                       move_focus_up=MagicMock(), move_focus_down=down)
    dialog.show()
    dialog.activateWindow()
    app.processEvents()
    field.setFocus()
    manager = InputManager.__new__(InputManager)
    manager._parent = cast(MainWindowProtocol, SimpleNamespace(keyboard=None, gamesListWidget=QWidget()))
    manager.axis_moving = False
    manager._gamepad_handling_enabled = True
    navigation = MagicMock()
    monkeypatch.setattr(manager, "_start_dpad_repeat", MagicMock())
    monkeypatch.setattr(manager, "_route_dpad_navigation", navigation)
    monkeypatch.setattr(QApplication, "activeWindow", lambda: dialog)
    manager._handle_default_dpad(PAD_DPAD_Y, 1, 0.0)
    down.assert_called_once()
    navigation.assert_not_called()
    assert QApplication.focusWidget() is key
    dialog.close()


@mark.parametrize("mode", ["import", "exe", "directory"])
def test_file_picker_x_does_not_put_folder_in_executable_field(
    tmp_path: Any, monkeypatch: MonkeyPatch, mode: str,
) -> None:
    from PySide6.QtWidgets import QListWidget
    from portprotonqt.dialogs.base import FileSelectedSignal

    app = QApplication.instance() or QApplication([])
    folder = tmp_path / "Games"
    folder.mkdir()
    picker = cast(Any, QDialog())
    picker.current_path = str(tmp_path)
    picker.directory_only = mode == "directory"
    picker.file_list = QListWidget(picker)
    picker.file_list.addItem("Games/")
    picker.file_list.setCurrentRow(0)
    picker.file_signal = FileSelectedSignal()
    selected = []
    picker.file_signal.file_selected.connect(selected.append)
    action = QPushButton(picker)
    if mode == "import":
        action.setObjectName("gamepadAddButton")
    clicked = MagicMock()
    action.clicked.connect(clicked)
    picker.show()
    app.processEvents()
    manager = InputManager.__new__(InputManager)
    manager._parent = cast(MainWindowProtocol, SimpleNamespace(keyboard=None))
    manager.file_explorer = picker
    monkeypatch.setattr(QApplication, "activeWindow", lambda: picker)
    monkeypatch.setattr(QApplication, "activePopupWidget", lambda: None)
    manager.handle_file_explorer_button(next(iter(input_manager.BUTTONS["add_game"])), 1)
    assert clicked.call_count == int(mode == "import")
    assert selected == ([str(folder)] if mode == "directory" else [])
    assert picker.result() == (QDialog.DialogCode.Accepted if mode == "directory" else QDialog.DialogCode.Rejected)
    picker.close()


def test_x_edits_keyboard_without_triggering_dialog_action(monkeypatch: MonkeyPatch) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = cast(Any, QDialog())
    keyboard = QFrame(dialog)
    dialog.keyboard = keyboard
    action = QPushButton(dialog)
    action.setObjectName("gamepadAddButton")
    clicked = MagicMock()
    action.clicked.connect(clicked)
    dialog.show()
    app.processEvents()
    manager = InputManager.__new__(InputManager)
    manager._parent = cast(MainWindowProtocol, SimpleNamespace(keyboard=None))
    handled = MagicMock()
    monkeypatch.setattr(manager, "_handle_common_ui_elements", lambda _button: False)
    monkeypatch.setattr(manager, "handle_virtual_keyboard", handled)
    monkeypatch.setattr(input_buttons, "VirtualKeyboard", QFrame)
    monkeypatch.setattr(QApplication, "activeWindow", lambda: dialog)
    button = next(iter(input_manager.BUTTONS["add_game"]))
    manager._handle_default_button(button, 1)
    handled.assert_called_once_with(button, 1)
    clicked.assert_not_called()
    dialog.close()


@mark.parametrize("row", [0, 1])
def test_gamepad_combo_confirm_emits_activation(row: int) -> None:
    application = QApplication.instance() or QApplication([])
    combo = QComboBox()
    combo.addItems(["GOG", "PortProton"])
    activated = []
    combo.activated.connect(activated.append)
    combo.show()
    combo.showPopup()
    combo.view().setCurrentIndex(combo.model().index(row, 0))
    manager = InputManager.__new__(InputManager)
    confirm = next(iter(input_manager.BUTTONS["confirm"]))

    assert manager._handle_list_view_button(combo.view(), confirm)

    assert activated == [row]
    assert combo.currentIndex() == row
    assert not combo.view().isVisible()
    combo.close()
    application.processEvents()


def test_readonly_combo_confirm_opens_popup_without_keyboard() -> None:
    application = QApplication.instance() or QApplication([])
    combo = QComboBox()
    combo.addItems(["GOG", "PortProton"])
    combo.setEditable(True)
    field = combo.lineEdit()
    assert field is not None
    field.setReadOnly(True)
    keyboard = MagicMock()
    manager = InputManager.__new__(InputManager)
    manager._parent = cast(MainWindowProtocol, SimpleNamespace(keyboard=keyboard))
    confirm = next(iter(input_manager.BUTTONS["confirm"]))
    combo.show()

    assert not manager._route_button_to_text_input(combo, field, confirm)
    assert manager._handle_combo_button(field, confirm)
    assert combo.view().isVisible()
    keyboard.show_for_widget.assert_not_called()
    combo.hidePopup()
    combo.close()
    application.processEvents()


def test_confirm_on_open_combo_activates_highlighted_row() -> None:
    application = QApplication.instance() or QApplication([])
    combo = QComboBox()
    combo.addItems(["GOG", "PortProton"])
    activated = []
    combo.activated.connect(activated.append)
    combo.show()
    combo.showPopup()
    combo.view().setCurrentIndex(combo.model().index(1, 0))
    manager = InputManager.__new__(InputManager)
    confirm = next(iter(input_manager.BUTTONS["confirm"]))

    assert manager._handle_combo_button(combo, confirm)

    assert activated == [1]
    assert not combo.view().isVisible()
    combo.close()
    application.processEvents()
