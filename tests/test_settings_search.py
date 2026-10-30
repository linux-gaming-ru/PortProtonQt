"""Tests for searching MangoHud, vkBasalt, and Gamescope settings."""

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from PySide6.QtCore import QEvent, QRect, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QDialog,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QStackedWidget,
    QWidget,
)

from portprotonqt.custom_widgets import CustomComboBox
from portprotonqt.tabs.settings_tab import SettingsButtonsLayout
from portprotonqt.dialogs.settings_gamescope import (
    GAMESCOPE_TOGGLE_CATEGORIES,
    GAMESCOPE_TOGGLE_DESCRIPTIONS,
    GamescopeSettingsMixin,
)
from portprotonqt.dialogs.settings_mangohud import (
    MANGOHUD_TOGGLE_CATEGORIES,
    MANGOHUD_TOGGLE_DESCRIPTIONS,
    MangoHudSettingsMixin,
)
from portprotonqt.dialogs.settings_vkbasalt import VkBasaltSettingsMixin


PAINT_SETTLE_MS = 250
_application = QApplication.instance() or QApplication([])


def test_settings_dialog_search_accepts_typing_without_search_focus() -> None:
    from portprotonqt.dialogs.settings_dialog import ExeSettingsDialog

    dialog = ExeSettingsDialog.__new__(ExeSettingsDialog)
    QDialog.__init__(dialog)
    dialog.search_edit = QLineEdit(dialog)
    dialog.vkbasalt_toggle_key_button = None
    dialog._gamepad_tooltip_map = {}
    dialog.input_manager = None
    dialog.gamepad_tooltip = QLabel(dialog)
    dialog.gamepad_tooltip_timer = QTimer(dialog)
    button = QPushButton(dialog)
    other_input = QLineEdit(dialog)
    dialog.search_edit.show()
    button.show()
    other_input.show()
    dialog.setModal(True)
    dialog.show()
    QApplication.processEvents()
    _application.installEventFilter(dialog)

    try:
        button.setFocus()
        QTest.keyClicks(button, "fps")
        assert dialog.search_edit.text() == "fps"
        assert QApplication.focusWidget() is button

        QTest.keyClick(button, Qt.Key.Key_Backspace)
        assert dialog.search_edit.text() == "fp"
        QTest.keyClick(button, Qt.Key.Key_Backspace)
        QTest.keyClick(button, Qt.Key.Key_Backspace)
        assert dialog.search_edit.text() == ""
        QTest.keyClick(button, Qt.Key.Key_Backspace)
        assert dialog.search_edit.text() == ""
        assert dialog.isVisible()

        other_input.setFocus()
        QTest.keyClicks(other_input, "text")
        assert other_input.text() == "text"
        assert dialog.search_edit.text() == ""
    finally:
        _application.removeEventFilter(dialog)
        dialog.close()
        dialog.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_mangohud_search_ignores_unavailable_categories() -> None:
    settings = MangoHudSettingsMixin()
    settings.mangohud_category_groups = {}

    settings._filter_mangohud_settings("fps")


def test_mangohud_parser_recognizes_font_settings() -> None:
    settings = MangoHudSettingsMixin()

    parsed, raw_tokens = settings._parse_mangohud_config(
        "font_scale=1.25,font_size=28,font_file=/usr/share/fonts/test.ttf"
    )

    assert parsed["font_scale"] == "1.25"
    assert parsed["font_size"] == "28"
    assert parsed["font_file"] == "/usr/share/fonts/test.ttf"
    assert raw_tokens == []


@pytest.mark.parametrize("original_enabled", ["0", "1"])
@pytest.mark.parametrize("original_config", ["", "cpu_stats,font_size=28"])
def test_disabled_mangohud_preserves_config(
    monkeypatch: pytest.MonkeyPatch, original_enabled: str, original_config: str,
) -> None:
    monkeypatch.setenv("MANGOHUD", "1")
    settings = MangoHudSettingsMixin()
    settings.current_settings = {"PW_MANGOHUD": "0", "PW_MANGOHUD_USER_CONF": "1"}
    monkeypatch.setattr(settings, "original_values", {
        "PW_MANGOHUD": original_enabled, "PW_MANGOHUD_USER_CONF": "0",
    }, raising=False)
    settings.mangohud_original_values = {"MANGOHUD_CONFIG": original_config, "FPS_LIMIT": "60"}

    changes = settings._collect_mangohud_changes()

    expected = ["PW_MANGOHUD_USER_CONF=1"]
    if original_enabled == "1":
        expected.insert(0, "PW_MANGOHUD=0")
    assert changes == expected


def test_enabled_mangohud_collects_config_and_fps(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = MangoHudSettingsMixin()
    settings.current_settings = {"PW_MANGOHUD": "1"}
    monkeypatch.setattr(settings, "original_values", {"PW_MANGOHUD": "0"}, raising=False)
    settings.mangohud_original_values = {"MANGOHUD_CONFIG": "", "FPS_LIMIT": ""}
    checkbox = QCheckBox()
    checkbox.setChecked(True)
    settings.mangohud_fps_widgets = {"60": checkbox}
    monkeypatch.setattr(settings, "_build_mangohud_config", lambda: "fps_limit=60")

    assert settings._collect_mangohud_changes() == [
        "PW_MANGOHUD=1", "MANGOHUD_CONFIG=fps_limit=60", "FPS_LIMIT=60",
    ]


def test_mangohud_font_options_use_fc_list(monkeypatch: pytest.MonkeyPatch) -> None:
    output = (
        "Noto Sans Regular\t/usr/share/fonts/NotoSans.ttf\n"
        "Bitmap Regular\t/usr/share/fonts/misc.pcf.gz\n"
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )

    assert MangoHudSettingsMixin()._get_mangohud_font_options() == [
        ("Noto Sans Regular", "/usr/share/fonts/NotoSans.ttf")
    ]


def test_gamescope_search_ignores_unavailable_categories() -> None:
    settings = GamescopeSettingsMixin()
    settings.gamescope_category_groups = {}

    settings._filter_gamescope_settings("fullscreen")


def test_vkbasalt_search_filters_and_moves_matching_shader_first() -> None:
    settings = VkBasaltSettingsMixin()
    settings.theme = SimpleNamespace(mangoHudSwitchesColumns=2)
    settings.current_settings = {"PW_VKBASALT": "1", "PW_VKBASALT_USER_CONF": "0"}
    settings.vkbasalt_tab = QWidget()
    settings.vkbasalt_actions_group = QGroupBox("Actions", settings.vkbasalt_tab)
    settings.vkbasalt_shaders_group = QGroupBox("Shaders", settings.vkbasalt_tab)
    shaders_layout = QGridLayout(settings.vkbasalt_shaders_group)
    settings.vkbasalt_shaders_layout = shaders_layout
    settings.vkbasalt_shader_widgets = {
        "Curves": QCheckBox("Curves"),
        "AdaptiveSharpen": QCheckBox("AdaptiveSharpen"),
    }
    for index, checkbox in enumerate(settings.vkbasalt_shader_widgets.values()):
        shaders_layout.addWidget(checkbox, 0, index * 2 + 1)

    settings._filter_vkbasalt_settings("adaptive")

    assert settings.vkbasalt_shader_widgets["Curves"].isHidden()
    matching = settings.vkbasalt_shader_widgets["AdaptiveSharpen"]
    assert not matching.isHidden()
    row, column, _row_span, _column_span = cast(
        tuple[int, int, int, int],
        shaders_layout.getItemPosition(shaders_layout.indexOf(matching)),
    )
    assert (row, column) == (0, 1)


def test_mangohud_search_uses_description_and_selects_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(MANGOHUD_TOGGLE_DESCRIPTIONS, "cpu_efficiency", "Frames/joule")
    monkeypatch.setitem(MANGOHUD_TOGGLE_DESCRIPTIONS, "gpu_efficiency", "Frames/joule")
    settings = MangoHudSettingsMixin()
    settings.theme = SimpleNamespace(mangoHudSwitchesColumns=2)
    settings._update_mangohud_category_stack_height = lambda: None
    settings.current_settings = {"PW_MANGOHUD": "1", "PW_MANGOHUD_USER_CONF": "0"}
    settings.mangohud_tab = QWidget()
    settings.mangohud_actions_group = QGroupBox("Actions", settings.mangohud_tab)
    settings.mangohud_toggle_group = QGroupBox("MangoHud switches", settings.mangohud_tab)
    settings.mangohud_category_combo = CustomComboBox()
    general_name = next(name for name, keys in MANGOHUD_TOGGLE_CATEGORIES.items() if "battery" in keys)
    cpu_gpu_name = next(name for name, keys in MANGOHUD_TOGGLE_CATEGORIES.items() if "cpu_efficiency" in keys)
    settings.mangohud_category_combo.addItems([general_name, cpu_gpu_name])
    general = QWidget()
    cpu_gpu = QWidget()
    battery = QCheckBox("Battery")
    efficiency = QCheckBox("CPU efficiency")
    gpu_efficiency = QCheckBox("GPU efficiency")
    QGridLayout(general).addWidget(battery)
    cpu_gpu_layout = QGridLayout(cpu_gpu)
    cpu_gpu_layout.addWidget(efficiency)
    cpu_gpu_layout.addWidget(gpu_efficiency)
    general.setParent(settings.mangohud_toggle_group)
    cpu_gpu.setParent(settings.mangohud_toggle_group)
    settings.mangohud_category_groups = {general_name: general, cpu_gpu_name: cpu_gpu}
    settings.mangohud_category_stack = QStackedWidget(settings.mangohud_toggle_group)
    settings.mangohud_category_stack.addWidget(general)
    settings.mangohud_category_stack.addWidget(cpu_gpu)
    settings.mangohud_toggle_widgets = {
        "battery": battery,
        "cpu_efficiency": efficiency,
        "gpu_efficiency": gpu_efficiency,
    }
    settings.mangohud_toggle_widget_keys = {
        battery: "battery",
        efficiency: "cpu_efficiency",
        gpu_efficiency: "gpu_efficiency",
    }

    settings._filter_mangohud_settings("frames/joule")
    assert settings.mangohud_category_combo.isHidden()
    assert battery.isHidden()
    assert not efficiency.isHidden()
    result_parent = efficiency.parentWidget()
    assert result_parent is not None
    result_layout = cast(QGridLayout, result_parent.layout())
    positions = set()
    for checkbox in (efficiency, gpu_efficiency):
        row, column, _row_span, _column_span = cast(
            tuple[int, int, int, int],
            result_layout.getItemPosition(result_layout.indexOf(checkbox)),
        )
        positions.add((row, column))
    assert positions == {(0, 1), (0, 3)}


def test_mangohud_search_prefers_hidden_over_arch_for_hid() -> None:
    settings = MangoHudSettingsMixin()
    settings.theme = SimpleNamespace(mangoHudSwitchesColumns=2)
    settings._update_mangohud_category_stack_height = lambda: None
    settings.current_settings = {"PW_MANGOHUD": "1", "PW_MANGOHUD_USER_CONF": "0"}
    settings.mangohud_tab = QWidget()
    settings.mangohud_actions_group = QGroupBox("Actions", settings.mangohud_tab)
    settings.mangohud_toggle_group = QGroupBox("MangoHud switches", settings.mangohud_tab)
    settings.mangohud_category_combo = CustomComboBox()
    keys = ("arch", "hide_fsr_sharpness", "no_display")
    category_names = [
        next(name for name, category_keys in MANGOHUD_TOGGLE_CATEGORIES.items() if key in category_keys)
        for key in keys
    ]
    settings.mangohud_category_combo.addItems(category_names)
    categories = {name: QWidget() for name in category_names}
    arch = QCheckBox("Arch")
    hide_fsr = QCheckBox("Hide FSR sharpness")
    hidden = QCheckBox("Hidden by default")
    for widget, checkbox in zip(categories.values(), (arch, hide_fsr, hidden), strict=True):
        QGridLayout(widget).addWidget(checkbox)
        widget.setParent(settings.mangohud_toggle_group)
    settings.mangohud_category_groups = categories
    settings.mangohud_category_stack = QStackedWidget(settings.mangohud_toggle_group)
    for widget in categories.values():
        settings.mangohud_category_stack.addWidget(widget)
    settings.mangohud_toggle_widgets = {
        "arch": arch,
        "hide_fsr_sharpness": hide_fsr,
        "no_display": hidden,
    }
    settings.mangohud_toggle_widget_keys = {
        arch: "arch",
        hide_fsr: "hide_fsr_sharpness",
        hidden: "no_display",
    }

    settings._filter_mangohud_settings("h")
    assert settings.mangohud_category_combo.isHidden()

    settings._filter_mangohud_settings("hid")
    assert arch.isHidden()
    assert not hide_fsr.isHidden()
    assert not hidden.isHidden()
    assert hide_fsr.parentWidget() is hidden.parentWidget()
    general_layout = cast(QGridLayout, categories[category_names[0]].layout())
    assert general_layout.rowCount() == 1
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    settings._filter_mangohud_settings("")
    assert arch.text() == "Arch"


def test_mangohud_stack_height_expands_after_filtered_results() -> None:
    settings = MangoHudSettingsMixin()
    settings.theme = SimpleNamespace(mangoHudSwitchesColumns=2)
    settings.current_settings = {"PW_MANGOHUD": "1", "PW_MANGOHUD_USER_CONF": "0"}
    settings.mangohud_tab = QWidget()
    settings.mangohud_actions_group = QGroupBox("Actions", settings.mangohud_tab)
    settings.mangohud_toggle_group = QGroupBox("MangoHud switches", settings.mangohud_tab)
    settings.mangohud_category_combo = CustomComboBox()
    general_name = next(name for name, category_keys in MANGOHUD_TOGGLE_CATEGORIES.items() if "arch" in category_keys)
    settings.mangohud_category_combo.addItem(general_name)
    page = QWidget()
    layout = QGridLayout(page)
    settings.mangohud_toggle_widgets = {}
    settings.mangohud_toggle_widget_keys = {}
    keys = [
        "arch", "battery", "battery_icon", "battery_time",
        "battery_watt", "exec_name", "time", "version",
    ]
    for row, key in enumerate(keys):
        checkbox = QCheckBox(f"Option {key}")
        layout.addWidget(checkbox, row, 0)
        settings.mangohud_toggle_widgets[key] = checkbox
        settings.mangohud_toggle_widget_keys[checkbox] = key
    settings.mangohud_category_groups = {general_name: page}
    page.setParent(settings.mangohud_toggle_group)
    settings.mangohud_category_stack = QStackedWidget()
    settings.mangohud_category_stack.addWidget(page)

    settings._filter_mangohud_settings("option arch")
    filtered_height = settings.mangohud_category_stack.maximumHeight()
    settings._filter_mangohud_settings("")

    assert settings.mangohud_category_stack.maximumHeight() > filtered_height


def test_gamescope_search_uses_description_and_selects_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(GAMESCOPE_TOGGLE_DESCRIPTIONS, "hdr_debug_heatmap", "Debug view")
    settings = GamescopeSettingsMixin()
    settings._update_gamescope_category_stack_height = lambda: None
    settings.current_settings = {"PW_GAMESCOPE": "1"}
    settings.gamescope_tab = QWidget()
    settings.gamescope_actions_group = QGroupBox("Actions", settings.gamescope_tab)
    settings.gamescope_toggle_group = QGroupBox("Gamescope switches", settings.gamescope_tab)
    settings.gamescope_category_combo = CustomComboBox()
    window_name = next(name for name, keys in GAMESCOPE_TOGGLE_CATEGORIES.items() if "fullscreen" in keys)
    hdr_name = next(name for name, keys in GAMESCOPE_TOGGLE_CATEGORIES.items() if "hdr_debug_heatmap" in keys)
    settings.gamescope_category_combo.addItems([window_name, hdr_name])
    window = QWidget()
    hdr = QWidget()
    fullscreen = QCheckBox("Fullscreen window")
    heatmap = QCheckBox("HDR luminance heatmap")
    QGridLayout(window).addWidget(fullscreen)
    QGridLayout(hdr).addWidget(heatmap)
    window.setParent(settings.gamescope_toggle_group)
    hdr.setParent(settings.gamescope_toggle_group)
    settings.gamescope_category_groups = {window_name: window, hdr_name: hdr}
    settings.gamescope_category_stack = QStackedWidget(settings.gamescope_toggle_group)
    settings.gamescope_category_stack.addWidget(window)
    settings.gamescope_category_stack.addWidget(hdr)
    settings.gamescope_toggle_widgets = {"fullscreen": fullscreen, "hdr_debug_heatmap": heatmap}
    settings.gamescope_toggle_widget_keys = {fullscreen: "fullscreen", heatmap: "hdr_debug_heatmap"}

    settings._filter_gamescope_settings("debug view")
    assert settings.gamescope_category_combo.isHidden()
    assert fullscreen.isHidden()
    assert not heatmap.isHidden()
    result_parent = heatmap.parentWidget()
    assert result_parent is not None
    result_layout = cast(QGridLayout, result_parent.layout())
    row, column, _row_span, _column_span = cast(
        tuple[int, int, int, int],
        result_layout.getItemPosition(result_layout.indexOf(heatmap)),
    )
    assert (row, column) == (0, 1)
    settings._filter_gamescope_settings("full")
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert fullscreen.text() == "Fullscreen window"


@pytest.mark.parametrize("theme_name", ["standart", "standart-light", "classic-light"])
def test_settings_table_descriptions_and_centered_controls(theme_name: str) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    from portprotonqt.dialogs.settings_dialog import ExeSettingsDialog
    from portprotonqt.theme_manager import ThemeWrapper, load_theme

    theme = ThemeWrapper(load_theme(theme_name))
    table = QTableWidget()
    table.setStyleSheet(theme.WINETRICKS_TABBLE_STYLE)
    table.viewport().setProperty("ppqt_settings_values", True)
    table.resize(1000, 600)
    table.setColumnCount(3)
    table.setColumnHidden(2, True)
    table.setRowCount(2)
    table.setColumnWidth(0, 700)
    dialog = SimpleNamespace(favorites_table=table, theme=theme)
    for row, description in enumerate(("Short <description> & text", "Long description " * 30)):
        ExeSettingsDialog._set_favorite_text_cells(
            cast(ExeSettingsDialog, dialog), row, "key", "Setting", description,
        )
        combo = CustomComboBox(theme=theme)
        combo.addItem("Value")
        table.setCellWidget(row, 1, combo)
    table.resizeRowsToContents()
    table.show()
    QApplication.processEvents()
    ExeSettingsDialog.eventFilter(
        cast(ExeSettingsDialog, dialog), table.viewport(), QEvent(QEvent.Type.Paint),
    )
    assert table.rowHeight(1) > table.rowHeight(0)
    for row in range(2):
        combo = table.cellWidget(row, 1)
        assert isinstance(combo, CustomComboBox)
        rect = table.visualRect(table.model().index(row, 1))
        assert combo.height() == combo.sizeHint().height()
        assert abs(combo.geometry().center().y() - rect.center().y()) <= 1
        name_item = table.item(row, 0)
        description_item = table.item(row, 2)
        assert name_item is not None and description_item is not None
        label = table.cellWidget(row, 0)
        assert isinstance(label, QLabel)
        from html import escape

        assert label.textFormat() == Qt.TextFormat.RichText
        description_style = (
            theme.SETTINGS_SELECTED_DESCRIPTION_HTML if row == table.currentRow()
            else theme.SETTINGS_DESCRIPTION_HTML
        )
        expected_text = "Setting<br>" + description_style.format(
            description=escape(description_item.text()),
        )
        if row == table.currentRow():
            expected_text = theme.SETTINGS_SELECTED_TEXT_HTML.format(text=expected_text)
        assert label.text() == expected_text
        assert name_item.data(Qt.ItemDataRole.AccessibleTextRole) == f"Setting\n{description_item.text()}"
        expected_color = (
            QColor(theme.color_text_accent_hover) if row == table.currentRow()
            else table.palette().color(label.foregroundRole())
        )
        assert label.palette().color(label.foregroundRole()) == expected_color
        assert name_item.text() == ""
    if theme_name.endswith("-light"):
        from PySide6.QtGui import QPalette

        assert table.palette().color(QPalette.ColorRole.Text) == QColor(theme.color_text_dark)
    table.selectRow(1)
    ExeSettingsDialog.eventFilter(cast(ExeSettingsDialog, dialog), table.viewport(), QEvent(QEvent.Type.Paint))
    assert isinstance(table.cellWidget(1, 0), QLabel)
    label = table.cellWidget(1, 0)
    ExeSettingsDialog._set_favorite_text_cells(
        cast(ExeSettingsDialog, dialog), 1, "key", "Updated", "New <description>",
    )
    ExeSettingsDialog.eventFilter(cast(ExeSettingsDialog, dialog), table.viewport(), QEvent(QEvent.Type.Paint))
    assert table.cellWidget(1, 0) is label
    assert isinstance(label, QLabel)
    assert label.text() == theme.SETTINGS_SELECTED_TEXT_HTML.format(
        text="Updated<br>" + theme.SETTINGS_SELECTED_DESCRIPTION_HTML.format(
            description="New &lt;description&gt;",
        ),
    )
    updated_item = table.item(1, 0)
    assert updated_item is not None
    assert updated_item.data(Qt.ItemDataRole.AccessibleTextRole) == "Updated\nNew <description>"
    assert updated_item.text() == ""
    table.close()


@pytest.mark.parametrize("close_dialog", [False, True])
@pytest.mark.parametrize("themed", [False, True])
def test_combo_tooltip_only_for_clipped_visible_popup(close_dialog: bool, themed: bool) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QComboBox, QDialog
    from portprotonqt.dialogs.settings_dialog import ExeSettingsDialog

    dialog = ExeSettingsDialog.__new__(ExeSettingsDialog)
    QDialog.__init__(dialog)
    dialog.vkbasalt_toggle_key_button = None
    dialog.input_manager = None
    dialog.gamepad_tooltip = QLabel(dialog)
    dialog.gamepad_tooltip_timer = QTimer(dialog)
    dialog.gamepad_tooltip_timer.setSingleShot(True)
    combo = QComboBox(dialog)
    if themed:
        from portprotonqt.theme_manager import ThemeWrapper
        from portprotonqt.themes.standart import styles

        combo.setStyleSheet(ThemeWrapper(styles).COMBOBOX_STYLE)
        dialog.gamepad_tooltip.setStyleSheet(ThemeWrapper(styles).TOOLTIP_STYLE)
    combo.addItems(["Proton", "WINE-11.18-AMD64-WOW64" if themed else "Proton " * 40])
    dialog.resize(600, 400)
    dialog.move(20, 20)
    combo.setGeometry(450, 20, 140, 40)
    combo.view().setFixedWidth(180)
    combo.view().installEventFilter(dialog)
    combo.view().selectionModel().currentChanged.connect(
        lambda index, _previous: dialog._on_combo_highlighted(index.row(), combo),
    )
    combo.setCurrentIndex(1)
    dialog.show()
    combo.showPopup()
    QApplication.processEvents()

    assert dialog.gamepad_tooltip.isVisible()
    assert dialog.gamepad_tooltip.text() == combo.itemText(1)
    assert dialog.rect().contains(dialog.gamepad_tooltip.geometry())
    combo.view().setCurrentIndex(combo.model().index(0, 0))
    assert not dialog.gamepad_tooltip.isVisible()
    assert not dialog.gamepad_tooltip_timer.isActive()
    combo.view().setCurrentIndex(combo.model().index(1, 0))
    assert dialog.gamepad_tooltip.isVisible()

    if close_dialog:
        dialog.hide()
    else:
        combo.hidePopup()
    assert not dialog.gamepad_tooltip.isVisible()
    assert not dialog.gamepad_tooltip_timer.isActive()
    dialog._on_combo_highlighted(1, combo)
    assert not dialog.gamepad_tooltip.isVisible()
    combo.hidePopup()
    dialog.close()


def test_favorite_combo_preserves_separator_actions_and_source_updates() -> None:
    from PySide6.QtWidgets import QComboBox
    from portprotonqt.dialogs.settings_dialog import ExeSettingsDialog
    from portprotonqt.theme_manager import ThemeWrapper, load_theme

    table = QTableWidget(1, 2)
    source = QComboBox(table)
    source.addItems(["Wine", "Proton"])
    source.insertSeparator(source.count())
    source.addItem("Download", "download_wine")
    activated = []
    source.activated.connect(activated.append)
    source.activated.connect(lambda _index: source.setCurrentIndex(0))
    highlighted = []
    dialog = ExeSettingsDialog.__new__(ExeSettingsDialog)
    QDialog.__init__(dialog)
    dialog.vkbasalt_toggle_key_button = None
    dialog.input_manager = None
    dialog.theme = ThemeWrapper(load_theme("standart"))
    dialog.favorites_table = table
    dialog._on_combo_highlighted = lambda row, combo: highlighted.append((row, combo))
    dialog._add_favorite_combo(0, source)
    combo = cast(QComboBox, table.cellWidget(0, 1))

    assert combo.model() is source.model()
    assert not combo.model().flags(combo.model().index(2, 0)) & Qt.ItemFlag.ItemIsEnabled
    assert combo.itemData(3) == "download_wine"
    combo.setCurrentIndex(3)
    combo.activated.emit(3)
    assert activated == [3]
    assert combo.currentText() == source.currentText() == "Wine"
    source.addItem("New Wine")
    assert combo.itemText(combo.count() - 1) == "New Wine"
    highlighted.clear()
    combo.view().setCurrentIndex(combo.model().index(1, 0))
    assert highlighted == [(1, combo)]
    table.deleteLater()


@pytest.fixture
def linked_settings_combos() -> tuple:
    from PySide6.QtWidgets import QComboBox
    from portprotonqt.dialogs.settings_dialog import ExeSettingsDialog
    from portprotonqt.theme_manager import ThemeWrapper, load_theme

    dialog = ExeSettingsDialog.__new__(ExeSettingsDialog)
    QDialog.__init__(dialog)
    dialog.vkbasalt_toggle_key_button = None
    dialog.input_manager = None
    dialog.theme = ThemeWrapper(load_theme("standart"))
    dialog.gamepad_tooltip = QLabel(dialog)
    dialog.gamepad_tooltip.setStyleSheet(dialog.theme.TOOLTIP_STYLE)
    dialog.gamepad_tooltip_timer = QTimer(dialog)
    stack = QStackedWidget(dialog)
    stack.setGeometry(0, 0, 600, 400)
    dialog.favorites_table = QTableWidget(1, 2)
    advanced = QTableWidget(1, 2)
    stack.addWidget(dialog.favorites_table)
    stack.addWidget(advanced)
    source = QComboBox()
    source.addItems(["Wine", "WINE-11.18-AMD64-WOW64 " * 3])
    advanced.setCellWidget(0, 1, source)
    source.view().installEventFilter(dialog)
    source.view().setMouseTracking(True)
    source.view().entered.connect(lambda index: dialog._on_combo_highlighted(index.row(), source))
    source.view().selectionModel().currentChanged.connect(
        lambda index, _old: dialog._on_combo_highlighted(index.row(), source),
    )
    dialog._add_favorite_combo(0, source)
    favorite = cast(QComboBox, dialog.favorites_table.cellWidget(0, 1))
    dialog.resize(600, 400)
    dialog.show()
    return dialog, stack, favorite, source


@pytest.mark.parametrize("navigation", ["gamepad", "mouse"])
def test_linked_settings_combos_keep_visible_tooltip_during_navigation(
    linked_settings_combos: tuple, navigation: str,
) -> None:
    from PySide6.QtGui import QMouseEvent

    dialog, stack, favorite, source = linked_settings_combos
    for page, combo in enumerate((favorite, source)):
        stack.setCurrentIndex(page)
        combo.view().setFixedWidth(180)
        combo.showPopup()
        QApplication.processEvents()
        for row in (1, 0):
            if navigation == "mouse":
                rect = combo.view().visualRect(combo.model().index(row, 0))
                point = rect.intersected(combo.view().viewport().rect()).center().toPointF()
                QApplication.sendEvent(combo.view().viewport(), QMouseEvent(
                    QEvent.Type.MouseMove, point, point, Qt.MouseButton.NoButton,
                    Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                ))
            else:
                combo.setCurrentIndex(row)
            assert dialog.gamepad_tooltip.isVisible() == bool(row), page
            if row:
                assert dialog.gamepad_tooltip.text() == combo.itemText(row)
                assert dialog.rect().contains(dialog.gamepad_tooltip.geometry())
                assert not dialog.gamepad_tooltip.isWindow()
        combo.hidePopup()
    dialog.close()


@pytest.mark.parametrize("theme_name", ["standart", "standart-light", "classic", "classic-light"])
def test_settings_selected_row_keeps_text_readable(theme_name: str) -> None:
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QTableWidgetItem

    from portprotonqt.dialogs.settings_dialog import ExeSettingsDialog
    from portprotonqt.theme_manager import ThemeWrapper, load_theme

    theme = ThemeWrapper(load_theme(theme_name))
    table = QTableWidget(2, 3)
    table.setStyleSheet(theme.WINETRICKS_TABBLE_STYLE)
    table.viewport().setProperty("ppqt_settings_values", True)
    for row in range(2):
        table.setItem(row, 0, QTableWidgetItem("Setting\nDescription"))
    dialog = SimpleNamespace(theme=theme)
    for selected_row in range(2):
        table.setCurrentCell(selected_row, 0)
        table.selectRow(selected_row)
        ExeSettingsDialog.eventFilter(
            cast(ExeSettingsDialog, dialog), table.viewport(), QEvent(QEvent.Type.Paint),
        )
        for row in range(2):
            label = table.cellWidget(row, 0)
            assert isinstance(label, QLabel)
            selected = row == selected_row
            assert label.autoFillBackground() == selected
            if selected:
                assert label.palette().color(QPalette.ColorRole.Window) == QColor(theme.color_accent)
                assert label.palette().color(QPalette.ColorRole.Text) == QColor(theme.color_text_accent_hover)
                expected_text = "Setting<br>" + theme.SETTINGS_SELECTED_DESCRIPTION_HTML.format(
                    description="Description",
                )
                assert label.text() == theme.SETTINGS_SELECTED_TEXT_HTML.format(text=expected_text)
            else:
                assert label.text() == "Setting<br>" + theme.SETTINGS_DESCRIPTION_HTML.format(
                    description="Description",
                )
    table.close()


def test_settings_buttons_switch_between_one_and_two_rows() -> None:
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    layout = SettingsButtonsLayout()
    layout.setSpacing(10)
    parent.setLayout(layout)
    buttons = []
    for _ in range(2):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch()
        button = QWidget(parent)
        button.setFixedSize(100, 30)
        row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)
        buttons.append(button)
    for width, height in ((210, 30), (200, 70), (300, 30)):
        layout.setGeometry(QRect(0, 0, width, height))
        assert layout.heightForWidth(width) == height
        if height == 30:
            assert layout.direction() == QBoxLayout.Direction.LeftToRight
            assert buttons[0].y() == buttons[1].y()
            assert buttons[1].x() - buttons[0].x() == 110
            assert buttons[0].x() == (width - 210) // 2
        else:
            assert layout.direction() == QBoxLayout.Direction.TopToBottom
            assert buttons[0].x() == buttons[1].x() == 50
            assert buttons[1].y() > buttons[0].y()
    parent.close()
    app.processEvents()


@pytest.mark.parametrize("theme_name", ["standart", "standart-light", "classic", "classic-light"])
def test_winetricks_centered_checkboxes_and_install_selection(
    tmp_path: Path, theme_name: str,
) -> None:
    from unittest.mock import Mock
    from portprotonqt.dialogs.base import DraggableDialog
    from portprotonqt.dialogs.winetricks_dialog import WinetricksDialog
    from portprotonqt.input_manager.dialog_modes import DialogInputModesMixin
    from portprotonqt.input_manager.constants import BUTTONS
    from portprotonqt.theme_manager import ThemeWrapper, load_theme

    theme = ThemeWrapper(load_theme(theme_name))
    dialog = WinetricksDialog.__new__(WinetricksDialog)
    DraggableDialog.__init__(dialog)
    dialog.theme = theme
    dialog.setup_ui()
    dialog.log_path = str(tmp_path / "winetricks.log")
    (tmp_path / "winetricks.log").write_text("amstream\n")
    dialog._start_install_process = Mock()
    dialog.show()
    for index, table in enumerate((dialog.dll_table, dialog.fonts_table, dialog.settings_table)):
        dialog.populate_table(table, "amstream MS amstream.dll\nart2kmin Access", r"^$", dialog.log_path)
        assert table.columnWidth(0) == theme.WINETRICKS_CHECK_COLUMN_WIDTH
        dialog.tab_widget.setCurrentIndex(index)
        cast(QStackedWidget, dialog.tab_widget.currentWidget()).setCurrentWidget(table)
        QApplication.processEvents()
        cell = table.cellWidget(0, 0)
        assert cell is not None
        assert cell.geometry() == table.visualRect(table.model().index(0, 0))
        checkbox = cell.findChild(QCheckBox)
        assert checkbox is not None and checkbox.isChecked()
        assert table.item(0, 0) is None
        assert abs(checkbox.geometry().center().x() - cell.rect().center().x()) <= 1
        assert abs(checkbox.geometry().center().y() - cell.rect().center().y()) <= 1
        table.setCurrentCell(1, 0)
        table.setFocus()
        assert table.focusProxy() is table.cellWidget(1, 0).findChild(QCheckBox)
        assert QApplication.focusWidget() is table.focusProxy()
        manager = cast(DialogInputModesMixin, SimpleNamespace(
            winetricks_dialog=dialog, _handle_common_ui_elements=lambda _code: False,
        ))
        DialogInputModesMixin.handle_winetricks_button(manager, next(iter(BUTTONS["confirm"])), 1)
        cell = table.cellWidget(1, 0)
        assert cell is not None
        checkbox = cell.findChild(QCheckBox)
        assert checkbox is not None and checkbox.isChecked()
    dialog.install_selected(force=True)
    dialog._start_install_process.assert_called_once_with(["art2kmin"], True)
    dialog.deleteLater()


@pytest.mark.parametrize("theme_name", ["standart", "standart-light", "classic", "classic-light"])
def test_settings_table_stops_repainting_when_idle(theme_name: str) -> None:
    from PySide6.QtCore import QObject
    from PySide6.QtWidgets import QTableWidgetItem
    from portprotonqt.dialogs.settings_dialog import ExeSettingsDialog
    from portprotonqt.theme_manager import ThemeWrapper, load_theme

    theme = ThemeWrapper(load_theme(theme_name))
    dialog = cast(ExeSettingsDialog, SimpleNamespace(theme=theme))

    class PaintFilter(QObject):
        paints = 0

        def eventFilter(self, obj: QObject, event: QEvent) -> bool:
            if event.type() == QEvent.Type.Paint:
                self.paints += 1
                return ExeSettingsDialog.eventFilter(dialog, obj, event)
            return False

    table = QTableWidget(3, 3)
    table.resize(800, 400)
    table.setStyleSheet(theme.WINETRICKS_TABBLE_STYLE)
    table.setColumnWidth(0, 500)
    table.setColumnHidden(2, True)
    table.viewport().setProperty("ppqt_settings_values", True)
    paint_filter = PaintFilter(table)
    table.viewport().installEventFilter(paint_filter)
    for row in range(3):
        table.setItem(row, 0, QTableWidgetItem("Setting\nDescription " * 5))
        combo = CustomComboBox(theme=theme)
        combo.addItem("Value")
        table.setCellWidget(row, 1, combo)
    table.show()
    for selected_row, width in ((0, 500), (1, 300)):
        table.selectRow(selected_row)
        table.setColumnWidth(0, width)
        for _ in range(10):
            QApplication.processEvents()
        QTest.qWait(PAINT_SETTLE_MS)
        paints = paint_filter.paints
        QTest.qWait(PAINT_SETTLE_MS)
        assert paint_filter.paints == paints
    table.close()


@pytest.fixture
def autosave_dialog(request, monkeypatch, tmp_path) -> tuple[QDialog, list[list[str]], bool]:
    from PySide6.QtCore import QProcess
    from portprotonqt.dialogs import settings_dialog as module

    dialog = module.ExeSettingsDialog.__new__(module.ExeSettingsDialog)
    QDialog.__init__(dialog)
    dialog.saving = False
    dialog.settings_loading = False
    dialog.close_after_save = False
    user_conf = bool(request.param)
    dialog.user_conf = user_conf
    dialog.exe_path = str(tmp_path / 'game.exe')
    dialog.save_timer = QTimer(dialog)
    dialog.clear_ppdb_button = cast(module.AutoSizeButton, QPushButton(dialog))
    dialog.original_values = {'TEST': '0'}
    dialog.original_display_values = {}
    dialog.current_settings = {}
    dialog.blocked_keys = set()
    prefix = CustomComboBox(dialog)
    prefix.setEditable(True)
    prefix.setCurrentText('lower prefix')
    dialog.advanced_widgets = {} if user_conf else {'PW_PREFIX_NAME': prefix}
    dialog.value_mapping = {}
    dialog.game_source = ''
    dialog.gamescope_available = False
    dialog.settings_table = QTableWidget(1, 1, dialog)
    from PySide6.QtWidgets import QTableWidgetItem
    item = QTableWidgetItem('TEST')
    item.setData(Qt.ItemDataRole.UserRole, 'TEST')
    dialog.settings_table.setItem(0, 0, item)
    checkbox = QCheckBox(dialog)
    dialog.value_widgets = {(0, 1): checkbox}
    dialog.mangohud_original_values = {}
    dialog.vkbasalt_original_values = {}
    dialog.gamescope_original_values = {}
    calls: list[list[str]] = []
    monkeypatch.setattr(dialog, '_collect_mangohud_changes', lambda: [])
    monkeypatch.setattr(dialog, '_collect_vkbasalt_changes', lambda: [])
    monkeypatch.setattr(dialog, '_get_process_args', lambda args: ['test-cli', *args])
    monkeypatch.setattr(QProcess, 'start', lambda _self, program, args: calls.append(args))

    return dialog, calls, user_conf


@pytest.mark.parametrize('autosave_dialog', [False, True], indirect=True)
def test_settings_autosave_ignores_download_action(autosave_dialog: tuple) -> None:
    from portprotonqt.dialogs.settings_dialog import ExeSettingsDialog

    widget, calls, user_conf = autosave_dialog
    dialog = cast(ExeSettingsDialog, widget)
    combo = CustomComboBox(dialog)
    combo.addItem("Wine")
    combo.addItem("Download", "download_wine")
    combo.setCurrentIndex(1)
    key = 'PW_DEFAULT_WINE_USE' if user_conf else 'PW_WINE_USE'
    dialog.advanced_widgets = {key: combo}
    dialog.original_display_values = {key: "Wine"}
    dialog.apply_changes()
    assert calls == []
    assert not dialog.saving
    dialog.deleteLater()


@pytest.mark.parametrize('autosave_dialog', [False, True], indirect=True)
def test_settings_autosave_serializes_changes(autosave_dialog) -> None:
    from PySide6.QtCore import QProcess
    from portprotonqt.dialogs.settings_dialog import ExeSettingsDialog

    widget, calls, user_conf = autosave_dialog
    dialog = cast(ExeSettingsDialog, widget)
    checkbox = dialog.value_widgets[(0, 1)]
    assert isinstance(checkbox, QCheckBox)
    checkbox.setChecked(True)
    dialog.apply_changes()
    assert dialog.saving
    assert len(calls) == 1
    checkbox.setChecked(False)
    dialog.apply_changes()
    assert len(calls) == 1
    process = dialog.user_conf_process if user_conf else dialog.save_process
    process.finished.emit(0, QProcess.ExitStatus.NormalExit)
    assert dialog.saving
    assert len(calls) == 2
    expected = ['TEST', '0'] if user_conf else ['TEST=0']
    assert calls[-1][-len(expected):] == expected
    process = dialog.user_conf_process if user_conf else dialog.save_process
    process.finished.emit(0, QProcess.ExitStatus.NormalExit)
    assert not dialog.saving
    assert dialog.original_values['TEST'] == '0'
    assert len(calls) == 2
    dialog.deleteLater()


def test_settings_autosave_ignores_search_and_initial_loading() -> None:
    from portprotonqt.dialogs.settings_dialog import ExeSettingsDialog

    dialog = ExeSettingsDialog.__new__(ExeSettingsDialog)
    QDialog.__init__(dialog)
    dialog.settings_loading = True
    dialog.save_timer = QTimer(dialog)
    dialog.search_edit = QLineEdit(dialog)
    checkbox = QCheckBox(dialog)
    dialog._connect_autosave()
    checkbox.setChecked(True)
    assert not dialog.save_timer.isActive()
    dialog.settings_loading = False
    dialog.search_edit.setText('search')
    assert not dialog.save_timer.isActive()
    checkbox.setChecked(False)
    assert dialog.save_timer.isActive()
    dialog.save_timer.stop()
    dialog.deleteLater()


def test_settings_close_waits_for_pending_save(monkeypatch) -> None:
    from portprotonqt.dialogs.settings_dialog import ExeSettingsDialog
    from PySide6.QtGui import QCloseEvent

    dialog = ExeSettingsDialog.__new__(ExeSettingsDialog)
    QDialog.__init__(dialog)
    dialog.save_timer = QTimer(dialog)
    dialog.saving = True
    dialog.close_after_save = False
    monkeypatch.setattr(dialog, 'apply_changes', lambda: None)
    event = QCloseEvent()
    dialog.closeEvent(event)
    assert not event.isAccepted()
    assert dialog.close_after_save
    dialog.close_after_save = False
    dialog.reject()
    assert dialog.close_after_save
    dialog.deleteLater()


def test_run_after_normalization_preserves_duplicates(tmp_path: Path) -> None:
    from portprotonqt.dialogs.settings_dialog import ExeSettingsDialog

    dialog = SimpleNamespace(exe_path=str(tmp_path / "Game.exe"))
    dialog._resolve_run_after_exe_path = lambda value: ExeSettingsDialog._resolve_run_after_exe_path(cast(ExeSettingsDialog, dialog), value)
    value = "EVE.exe,EVE.exe,Trainer.exe"
    assert dialog._resolve_run_after_exe_path(value) == ",".join(
        str(tmp_path / name) for name in value.split(",")
    )


def test_run_after_inline_entries_preserve_duplicates(tmp_path: Path) -> None:
    from portprotonqt.dialogs.settings_dialog import ExeSettingsDialog

    owner = cast(Any, QWidget())
    owner.advanced_table = QTableWidget(2, 3)
    owner.theme = SimpleNamespace(ACTION_BUTTON_STYLE="", LINE_EDIT_STYLE="")
    container = QWidget()
    target = QLineEdit(container)
    owner.advanced_table.setCellWidget(0, 1, container)
    from PySide6.QtWidgets import QTableWidgetItem

    owner.advanced_table.setItem(1, 0, QTableWidgetItem("next setting"))
    exe = tmp_path / "Game.exe"
    exe.touch()
    target.setText(f"{exe},{exe}")
    ExeSettingsDialog._toggle_run_after_entries(cast(ExeSettingsDialog, owner), target)
    assert owner.advanced_table.rowCount() == 4
    item = owner.advanced_table.item(1, 0)
    assert item is not None and item.text() == str(exe)
    item = owner.advanced_table.item(2, 0)
    assert item is not None and item.text() == str(exe)
    ExeSettingsDialog._toggle_run_after_entries(cast(ExeSettingsDialog, owner), target)
    assert owner.advanced_table.rowCount() == 2
    item = owner.advanced_table.item(1, 0)
    assert item is not None and item.text() == "next setting"
    owner.advanced_table.deleteLater()


def test_run_after_entry_paint_preserves_text_and_height() -> None:
    from PySide6.QtWidgets import QTableWidgetItem
    from portprotonqt.dialogs.settings_dialog import ExeSettingsDialog

    table = QTableWidget(1, 2)
    table.viewport().setProperty("ppqt_settings_values", True)
    table.setItem(0, 0, QTableWidgetItem("Game.exe"))
    entry = QLineEdit("Game.exe")
    table.setCellWidget(0, 0, entry)
    table.resizeRowsToContents()
    table.show()
    QApplication.processEvents()
    height = table.rowHeight(0)

    for _ in range(2):
        ExeSettingsDialog.eventFilter(
            cast(ExeSettingsDialog, SimpleNamespace()),
            table.viewport(), QEvent(QEvent.Type.Paint),
        )

    assert entry.text() == "Game.exe"
    item = table.item(0, 0)
    assert item is not None and item.text() == "Game.exe"
    assert table.rowHeight(0) == height
    assert entry.height() >= entry.sizeHint().height()
    table.close()
    table.deleteLater()


def test_run_after_removing_only_entry_clears_field(tmp_path: Path) -> None:
    from PySide6.QtWidgets import QTableWidgetItem
    from portprotonqt.dialogs.settings_dialog import ExeSettingsDialog

    owner = cast(Any, QWidget())
    owner.advanced_table = QTableWidget(2, 3)
    owner.theme = SimpleNamespace(ACTION_BUTTON_STYLE="", LINE_EDIT_STYLE="")
    owner._toggle_run_after_entries = lambda target: ExeSettingsDialog._toggle_run_after_entries(cast(ExeSettingsDialog, owner), target)
    container = QWidget()
    target = QLineEdit(container)
    owner.advanced_table.setCellWidget(0, 1, container)
    owner.advanced_table.setItem(1, 0, QTableWidgetItem("next setting"))
    exe = tmp_path / "Game.exe"
    exe.touch()
    target.setText(str(exe))
    owner._toggle_run_after_entries(target)
    ExeSettingsDialog._remove_run_after_entry(cast(ExeSettingsDialog, owner), target, 0)
    assert target.text() == ""
    assert owner.advanced_table.rowCount() == 2
    owner.advanced_table.deleteLater()
