"""Tests for searching MangoHud, vkBasalt, and Gamescope settings."""

import subprocess
from types import SimpleNamespace
from typing import cast

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QStackedWidget,
    QWidget,
)

from portprotonqt.custom_widgets import CustomComboBox
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


_application = QApplication.instance() or QApplication([])


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
