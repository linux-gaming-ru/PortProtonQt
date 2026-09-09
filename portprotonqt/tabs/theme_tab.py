import os
import re
import time
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from PySide6.QtCore import QFileSystemWatcher, QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QAction
from shiboken6 import isValid

from portprotonqt.config import load_theme_metainfo, ui_config, window_config
from portprotonqt.config.ui import _is_system_light_theme
from portprotonqt.custom_widgets import AutoSizeButton, CustomComboBox
from portprotonqt.image_utils import ImageCarousel
from portprotonqt.localization import _
from portprotonqt.logger import get_logger
from portprotonqt.tabs.theme_store import THEME_STORE_ITEM, ThemeStoreMixin
from portprotonqt.theme_manager import _find_theme_folder, load_theme_screenshots
from portprotonqt.tray_manager import restart_application_process

logger = get_logger(__name__)
THEME_STYLE_BATCH_SIZE = 24

if TYPE_CHECKING:
    from PySide6.QtWidgets import QMainWindow

    _MainWindowTypingBase = QMainWindow
else:
    _MainWindowTypingBase = object


class MainWindowThemeTabMixin(ThemeStoreMixin, _MainWindowTypingBase):
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...

    def createThemeTab(self):
        """Themes tab"""
        self.themeTabWidget = QWidget()
        self.themeTabWidget.setProperty(
            "theme_style_names",
            ("OTHER_PAGES_WIDGET_STYLE", "THEME_TAB_FOCUS_STYLE"),
        )
        self.themeTabWidget.setStyleSheet(self.theme.OTHER_PAGES_WIDGET_STYLE + self.theme.THEME_TAB_FOCUS_STYLE)
        self.themeTabWidget.setObjectName("otherPage")
        mainLayout = QVBoxLayout(self.themeTabWidget)
        mainLayout.setContentsMargins(10, 14, 10, 10)
        mainLayout.setSpacing(10)

        # 1. Top line: Title and theme list
        self.themeTabHeaderLayout = QHBoxLayout()

        self.themeTabTitleLabel = QLabel(_("Select Theme:"))
        self.themeTabTitleLabel.setObjectName("tabTitle")
        self.themeTabTitleLabel.setStyleSheet(self.theme.TAB_TITLE_STYLE)
        self.themeTabTitleLabel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.themeTabHeaderLayout.addWidget(self.themeTabTitleLabel)

        self.themesCombo = CustomComboBox(theme=self.theme)
        self.themesCombo.view().window().setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self.themesCombo.view().window().setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )
        self.themesCombo.setStyleSheet(self.theme.COMBOBOX_STYLE + self.theme.SCROLL_STYLE)
        self.themesCombo.setObjectName("themeTabCombo")
        self.themesCombo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        theme_names = self.theme_manager.get_available_themes()
        available_themes = ui_config.get_theme_bases(theme_names)
        current_theme_base = ui_config.get_theme_base()
        if current_theme_base in available_themes:
            available_themes.remove(current_theme_base)
            available_themes.insert(0, current_theme_base)
        self.themesCombo.addItems(available_themes)
        if ui_config.get_enable_theme_store():
            self.themesCombo.addItem(_(THEME_STORE_ITEM), THEME_STORE_ITEM)
        self.themeTabHeaderLayout.addWidget(self.themesCombo)

        self.themeVariantCombo = CustomComboBox(theme=self.theme)
        self.themeVariantCombo.view().window().setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self.themeVariantCombo.view().window().setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )
        self.themeVariantCombo.setStyleSheet(self.theme.COMBOBOX_STYLE + self.theme.SCROLL_STYLE)
        self.themeVariantCombo.setObjectName("themeVariantCombo")
        self.themeVariantCombo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.themeVariantCombo.addItem(_("Dark"), "dark")
        self.themeVariantCombo.addItem(_("Light"), "light")
        self.themeVariantCombo.addItem(_("Auto"), "auto")
        current_variant = ui_config.get_theme_variant()
        variant_index = self.themeVariantCombo.findData(current_variant)
        if variant_index >= 0:
            self.themeVariantCombo.setCurrentIndex(variant_index)
        self.themeTabHeaderLayout.addWidget(self.themeVariantCombo)
        self.themeTabHeaderLayout.addStretch(1)

        mainLayout.addLayout(self.themeTabHeaderLayout)

        self.themeContentStack = QStackedWidget()
        self.themeInstalledPage = QWidget()
        installedLayout = QVBoxLayout(self.themeInstalledPage)
        installedLayout.setContentsMargins(0, 0, 0, 0)
        installedLayout.setSpacing(10)

        def hasThemeVariants(theme_name: str) -> bool:
            if theme_name == _(THEME_STORE_ITEM):
                return False
            return ui_config.resolve_theme(theme_name, "dark") != ui_config.resolve_theme(theme_name, "light")

        def updateThemeVariantVisibility(*_args: object) -> None:
            self.themeVariantCombo.setVisible(hasThemeVariants(self.themesCombo.currentText()))

        # 2. Screenshots carousel
        self.screenshotsCarousel = ImageCarousel([])
        self.screenshotsCarousel.setStyleSheet(self.theme.CAROUSEL_WIDGET_STYLE)
        self.screenshotsCarousel.setObjectName("themeScreenshotsCarousel")
        self.screenshotsCarousel.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.screenshotsCarousel.prevArrow.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.screenshotsCarousel.nextArrow.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        installedLayout.addWidget(self.screenshotsCarousel, stretch=1)

        # 3. Theme info
        self.themeInfoLayout = QVBoxLayout()
        self.themeInfoLayout.setSpacing(10)

        self.themeMetainfoLabel = QLabel()
        self.themeMetainfoLabel.setWordWrap(True)
        self.themeMetainfoLabel.setOpenExternalLinks(True)
        self.themeMetainfoLabel.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.themeMetainfoLabel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.themeInfoLayout.addWidget(self.themeMetainfoLabel)

        self.applyButton = AutoSizeButton(_("Apply Theme"), icon=self.theme_manager.get_icon("apply", as_path=True))
        self.applyButton.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
        self.applyButton.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.applyButton.setObjectName("themeApplyButton")
        self.applyButton.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.themeInfoLayout.addWidget(self.applyButton)

        self.deleteThemeButton = AutoSizeButton(
            _("Delete Theme"),
            icon=self.theme_manager.get_icon("delete", as_path=True),
        )
        self.deleteThemeButton.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
        self.deleteThemeButton.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.deleteThemeButton.setObjectName("themeDeleteButton")
        self.deleteThemeButton.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.themeInfoLayout.addWidget(self.deleteThemeButton)

        installedLayout.addLayout(self.themeInfoLayout)
        self.themeContentStack.addWidget(self.themeInstalledPage)
        self.themeStorePage = self._create_theme_store_page()
        self.themeContentStack.addWidget(self.themeStorePage)
        mainLayout.addWidget(self.themeContentStack, stretch=1)

        # Preview update function
        def updateThemePreview(*_args: object) -> None:
            if self.themesCombo.currentData() == THEME_STORE_ITEM:
                self._show_theme_store()
                return
            self.themeContentStack.setCurrentWidget(self.themeInstalledPage)
            updateThemeVariantVisibility()
            base_theme = self.themesCombo.currentText()
            variant = self.themeVariantCombo.currentData() or "light"
            theme_name = ui_config.resolve_theme(base_theme, variant)
            custom_themes = self._get_selected_custom_themes()
            self.deleteThemeButton.setVisible(bool(custom_themes))
            meta = load_theme_metainfo(theme_name)
            link = meta.get("author_link", "")
            link_html = f'<a href="{link}">{link}</a>' if link else _("No link")
            unknown_author = _("Unknown")

            preview_text = (
                "<b>" + _("Name:") + "</b> " + meta.get('name', theme_name) + "<br>" +
                "<b>" + _("Description:") + "</b> " + meta.get('description', '') + "<br>" +
                "<b>" + _("Author:") + "</b> " + meta.get('author', unknown_author) + "<br>" +
                "<b>" + _("Link:") + "</b> " + link_html
            )
            self.themeMetainfoLabel.setText(preview_text)
            self.themeMetainfoLabel.setStyleSheet(self.theme.CONTENT_STYLE)

            screenshots = load_theme_screenshots(theme_name)
            if screenshots:
                self.screenshotsCarousel.update_images([
                    (pixmap, caption)
                    for pixmap, caption in screenshots
                ])
                self.screenshotsCarousel.show()
            else:
                self.screenshotsCarousel.hide()

        updateThemePreview()
        self.themesCombo.currentTextChanged.connect(updateThemePreview)
        self.themeVariantCombo.currentTextChanged.connect(updateThemePreview)

        # Theme apply logic
        def on_apply() -> None:
            selected_theme = ui_config.resolve_theme(
                self.themesCombo.currentText(),
                self.themeVariantCombo.currentData() or "light",
            )
            if selected_theme:
                self._apply_theme_and_restart(
                    selected_theme,
                    self.themeVariantCombo.currentData() or "light",
                )

        self.applyButton.clicked.connect(on_apply)
        self.deleteThemeButton.clicked.connect(self._delete_selected_theme)

        # Add widget to stackedWidget
        self.theme_tab_index = self.stackedWidget.addWidget(self.themeTabWidget)
        self._setup_theme_file_watcher()

    def _setup_theme_file_watcher(self) -> None:
        self.themeFileWatcher = QFileSystemWatcher(self)
        self.themeFileWatcher.fileChanged.connect(self._schedule_theme_reload)
        self.themeFileWatcher.directoryChanged.connect(self._schedule_theme_reload)
        self.themeReloadTimer = QTimer(self)
        self.themeReloadTimer.setSingleShot(True)
        self.themeReloadTimer.setInterval(250)
        self.themeReloadTimer.timeout.connect(self._reload_active_custom_theme)
        self._watch_active_theme_files()

    def _watch_active_theme_files(self) -> None:
        watcher = self.themeFileWatcher
        watched_paths = [*watcher.files(), *watcher.directories()]
        if watched_paths:
            watcher.removePaths(watched_paths)
        theme_name = self.current_theme_name
        if not self.theme_manager.is_custom_theme(theme_name):
            return
        theme_folder = _find_theme_folder(theme_name)
        if theme_folder is None:
            return
        paths = [theme_folder]
        for root, dirs, files in os.walk(theme_folder):
            dirs[:] = [name for name in dirs if name != "__pycache__"]
            paths.extend(os.path.join(root, name) for name in dirs)
            paths.extend(os.path.join(root, name) for name in files)
        watcher.addPaths(paths)

    def _schedule_theme_reload(self, _path: str) -> None:
        self._watch_active_theme_files()
        self.themeReloadTimer.start()

    def _reload_active_custom_theme(self) -> None:
        theme_name = self.current_theme_name
        if not self.theme_manager.is_custom_theme(theme_name):
            return
        self.theme_manager.invalidate_theme(theme_name)
        try:
            self._apply_theme_live(theme_name)
        except Exception as e:
            logger.warning("Failed to reload theme '%s': %s", theme_name, e)
        self._watch_active_theme_files()

    def _get_selected_custom_themes(self) -> list[str]:
        base_theme = self.themesCombo.currentText()
        variants = {
            ui_config.resolve_theme(base_theme, "dark"),
            ui_config.resolve_theme(base_theme, "light"),
        }
        return [name for name in variants if self.theme_manager.is_custom_theme(name)]

    def _delete_selected_theme(self) -> None:
        theme_names = self._get_selected_custom_themes()
        if not theme_names:
            return
        message = _("Delete theme '{0}'?").format(self.themesCombo.currentText())
        message_box = QMessageBox(self)
        message_box.setIcon(QMessageBox.Icon.Question)
        message_box.setWindowTitle(_("Confirm Deletion"))
        message_box.setText(message)
        message_box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        message_box.setDefaultButton(QMessageBox.StandardButton.No)
        message_box.setButtonText(QMessageBox.StandardButton.Yes, _("Yes"))
        message_box.setButtonText(QMessageBox.StandardButton.No, _("No"))
        if message_box.exec() != QMessageBox.StandardButton.Yes:
            return
        removal_results = [
            self.theme_manager.remove_custom_theme(name) for name in theme_names
        ]
        if not all(removal_results):
            QMessageBox.warning(self, _("Error"), _("Failed to delete theme."))
            return
        active_theme_deleted = ui_config.get_theme_base() == self.themesCombo.currentText()
        self._refresh_theme_combo("standart")
        if active_theme_deleted:
            self._apply_theme_and_restart("standart", self.themeVariantCombo.currentData() or "light")
            return
        self.themesCombo.setCurrentIndex(-1)
        self.themesCombo.setCurrentIndex(0)

    def _refresh_theme_store_visibility(self) -> None:
        store_index = self.themesCombo.findData(THEME_STORE_ITEM)
        if ui_config.get_enable_theme_store():
            if store_index < 0:
                self.themesCombo.addItem(_(THEME_STORE_ITEM), THEME_STORE_ITEM)
            return
        if store_index < 0:
            return
        if self.themesCombo.currentIndex() == store_index:
            self.themesCombo.setCurrentIndex(0)
        self.themesCombo.removeItem(store_index)

    def restart_application(self):
        """Restart application."""
        if not self.isFullScreen():
            window_config.set_geometry(self.width(), self.height())
        restart_application_process()

    def _refresh_theme_combo(self, selected_theme: str) -> None:
        theme_names = self.theme_manager.get_available_themes()
        available_themes = ui_config.get_theme_bases(theme_names)
        selected_base = ui_config.get_theme_bases([selected_theme])[0]
        if selected_base in available_themes:
            available_themes.remove(selected_base)
            available_themes.insert(0, selected_base)
        self.themesCombo.blockSignals(True)
        self.themesCombo.clear()
        self.themesCombo.addItems(available_themes)
        if ui_config.get_enable_theme_store():
            self.themesCombo.addItem(_(THEME_STORE_ITEM), THEME_STORE_ITEM)
        self.themesCombo.blockSignals(False)

    def _apply_theme_and_restart(self, theme_name: str, variant: str) -> None:
        base_theme = ui_config.get_theme_bases([theme_name])[0]
        ui_config.set_theme(theme_name)
        ui_config.set_theme_variant(variant)
        self._apply_theme_live(theme_name)
        if variant == "auto":
            ui_config.set_theme(base_theme)
            ui_config.set_theme_variant(variant)

    def _apply_theme_live(self, theme_name: str) -> None:
        old_theme = self.theme
        old_qicons, old_icon_paths = self.theme_manager.get_cached_icon_names(
            self.current_theme_name
        )
        theme_module = self.theme_manager.apply_theme(theme_name)
        if not theme_module:
            return
        widgets = [self, *self.findChildren(QWidget)]
        widget_styles = {widget.styleSheet() for widget in widgets}
        combined_styles = "".join(widget_styles)
        style_icon_paths = {
            path: icon_name
            for path, icon_name in old_icon_paths.items()
            if path in combined_styles
        }
        replacement_cache = getattr(self, "_theme_replacement_cache", {})
        replacement_key = (id(old_theme), id(theme_module))
        replacements = replacement_cache.get(replacement_key)
        if replacements is None:
            replacements = self._theme_style_replacements(old_theme, theme_module)
            replacement_cache[replacement_key] = replacements
            self._theme_replacement_cache = replacement_cache
        replacements = list(replacements)
        icon_replacements = self._theme_icon_path_replacements(
            theme_name, style_icon_paths
        )
        replacements.extend(icon_replacements)
        replace_style = self._theme_style_replacer(replacements, widget_styles)
        self.theme = theme_module
        self.current_theme_name = theme_name
        self._theme_change_in_progress = True
        self.setUpdatesEnabled(False)
        try:
            style_cache: dict[str, str] = {}
            style_updates = 0
            refresh_time = 0.0
            stylesheet_time = 0.0
            slow_updates: list[tuple[float, str]] = []
            deferred_updates: list[
                tuple[QWidget, str, Callable[[object], object] | None]
            ] = []
            for widget in widgets:
                if hasattr(widget, "theme"):
                    widget.theme = theme_module
                if hasattr(widget, "current_theme_name"):
                    widget.current_theme_name = theme_name
                refresh_theme = getattr(widget, "refresh_theme", None)
                visible = widget is self or widget.isVisible()
                if callable(refresh_theme) and visible:
                    refresh_started = time.perf_counter()
                    refresh_theme(theme_module)
                    refresh_time += time.perf_counter() - refresh_started
                style = widget.styleSheet()
                named_style = self._get_named_theme_style(widget, theme_module)
                if isinstance(named_style, str):
                    new_style = named_style
                elif style in style_cache:
                    new_style = style_cache[style]
                else:
                    new_style = replace_style(style)
                    style_cache[style] = new_style
                if not visible:
                    deferred_updates.append((widget, new_style, refresh_theme))
                elif new_style != style:
                    stylesheet_started = time.perf_counter()
                    widget.setStyleSheet(new_style)
                    update_time = time.perf_counter() - stylesheet_started
                    stylesheet_time += update_time
                    if update_time >= 0.005:
                        widget_name = widget.objectName() or type(widget).__name__
                        slow_updates.append((update_time, widget_name))
                    style_updates += 1
            self._update_theme_components(theme_module, theme_name)
            if old_qicons or old_icon_paths:
                self._refresh_theme_icons(theme_name, old_qicons, old_icon_paths)
            self._refresh_theme_library_layout(old_theme, theme_module)
            self._refresh_open_detail_page()
        finally:
            self.setUpdatesEnabled(True)
            self.update()
            self._theme_change_in_progress = False
        generation = getattr(self, "_theme_update_generation", 0) + 1
        self._theme_update_generation = generation
        if deferred_updates:
            QTimer.singleShot(
                0,
                lambda: self._apply_deferred_theme_updates(
                    deferred_updates, theme_module, generation
                ),
            )
        self.updateControlHints("force")
        if hasattr(self, "themeFileWatcher"):
            self._watch_active_theme_files()

    def _apply_deferred_theme_updates(
        self,
        updates: list[tuple[QWidget, str, Callable[[object], object] | None]],
        theme: object,
        generation: int,
    ) -> None:
        if generation != getattr(self, "_theme_update_generation", 0):
            return
        batch = updates[:THEME_STYLE_BATCH_SIZE]
        del updates[:THEME_STYLE_BATCH_SIZE]
        for widget, new_style, refresh_theme in batch:
            if not isValid(widget):
                continue
            if callable(refresh_theme):
                refresh_theme(theme)
            if new_style != widget.styleSheet():
                widget.setStyleSheet(new_style)
        if updates:
            QTimer.singleShot(
                0,
                lambda: self._apply_deferred_theme_updates(
                    updates, theme, generation
                ),
            )

    def _get_named_theme_style(self, widget: QWidget, theme: object) -> str | None:
        style_names = widget.property("theme_style_names")
        if not isinstance(style_names, (list, tuple)):
            style_name = widget.property("theme_style_name")
            style_names = (style_name,) if isinstance(style_name, str) else ()
        styles = [getattr(theme, name, None) for name in style_names]
        if not styles or not all(isinstance(style, str) for style in styles):
            return None
        return "".join(style for style in styles if isinstance(style, str))

    def _refresh_theme_library_layout(
        self, old_theme: object, new_theme: object
    ) -> None:
        old_mode = getattr(old_theme, "LIBRARY_LAYOUT_MODE", "grid")
        new_mode = getattr(new_theme, "LIBRARY_LAYOUT_MODE", "grid")
        if old_mode == new_mode:
            return
        manager = getattr(self, "game_library_manager", None)
        layout = getattr(manager, "gamesListLayout", None)
        if manager is None or layout is None:
            return
        manager.rebuild_library_layout(str(new_mode).lower())

    def _refresh_open_detail_page(self) -> None:
        manager = getattr(self, "detail_page_manager", None)
        if manager is None or not manager._can_rebuild_after_resize():
            return
        manager._reopen_current_detail_page()

    def _theme_style_replacer(
        self, replacements: list[tuple[str, str]], styles: set[str] | None = None
    ) -> Callable[[str], str]:
        replacement_map = {old: new for old, new in replacements if old}
        if not replacement_map:
            return lambda style: style
        partial_values = [
            old_value
            for old_value in replacement_map
            if styles is None
            or any(old_value in style and old_value != style for style in styles)
        ]
        if not partial_values:
            return lambda style: replacement_map.get(style, style)
        partial_values.sort(key=len, reverse=True)
        pattern = re.compile("|".join(re.escape(value) for value in partial_values))

        def replace_style(style: str) -> str:
            if not style:
                return style
            exact_style = replacement_map.get(style)
            if exact_style is not None:
                return exact_style
            return pattern.sub(lambda match: replacement_map[match.group(0)], style)

        return replace_style

    def _theme_icon_path_replacements(
        self, theme_name: str, old_paths: dict[str, str]
    ) -> list[tuple[str, str]]:
        replacements = []
        for old_path, icon_name in old_paths.items():
            new_path = self.theme_manager.get_icon(icon_name, theme_name, as_path=True)
            if isinstance(new_path, str) and old_path != new_path:
                replacements.append((old_path, new_path))
        return replacements

    def _update_theme_components(self, theme_module: object, theme_name: str) -> None:
        for component in vars(self).values():
            if hasattr(component, "theme"):
                component.theme = theme_module
            if hasattr(component, "current_theme_name"):
                component.current_theme_name = theme_name
        control_hints = getattr(self, "controlHintsWidget", None)
        hint_bar_style = getattr(theme_module, "HINT_BAR_STYLE", "")
        if isinstance(control_hints, QWidget):
            control_hints.setStyleSheet(hint_bar_style)
        hints_label_style = getattr(theme_module, "HINTS_LABEL_STYLE", "")
        for label in getattr(self, "hintTextLabels", ()):
            if isinstance(label, QWidget):
                label.setStyleSheet(hints_label_style)
        tray_manager = getattr(self, "tray_manager", None)
        if tray_manager is not None:
            tray_icon = self.theme_manager.get_icon("tray_portproton", theme_name)
            tray_manager.tray_icon.setIcon(tray_icon)

    def _refresh_theme_icons(
        self, theme_name: str, qicons: dict[int, str], paths: dict[str, str]
    ) -> None:
        for widget in self.findChildren(QWidget):
            control_hint_path = getattr(widget, "_icon_path", None)
            if isinstance(control_hint_path, str) and control_hint_path:
                icon_name = paths.get(control_hint_path)
                if icon_name:
                    new_path = self.theme_manager.get_icon(
                        icon_name, theme_name, as_path=True
                    )
                    set_paths = getattr(widget, "set_icon_paths", None)
                    if isinstance(new_path, str) and callable(set_paths):
                        set_paths((new_path,))
            icon_path = getattr(widget, "_icon", None)
            icon_name = paths.get(icon_path) if isinstance(icon_path, str) else None
            icon_setter = getattr(widget, "setIcon", None)
            if icon_name and callable(icon_setter):
                icon_setter(self.theme_manager.get_icon(icon_name, theme_name, as_path=True))
            if isinstance(widget, QAbstractButton):
                icon_name = qicons.get(widget.icon().cacheKey())
                if icon_name:
                    widget.setIcon(self.theme_manager.get_icon(icon_name, theme_name))
        for action in self.findChildren(QAction):
            icon_name = qicons.get(action.icon().cacheKey())
            if icon_name:
                action.setIcon(self.theme_manager.get_icon(icon_name, theme_name))

    def _theme_style_replacements(self, old_theme: object, new_theme: object) -> list[tuple[str, str]]:
        names = self._theme_attribute_names(old_theme) | self._theme_attribute_names(new_theme)
        candidates: dict[str, set[str]] = {}
        for name in sorted(names):
            if not name.endswith("_STYLE"):
                continue
            old_value = getattr(old_theme, name, None)
            new_value = getattr(new_theme, name, None)
            if isinstance(old_value, str) and isinstance(new_value, str) and old_value != new_value:
                candidates.setdefault(old_value, set()).add(new_value)
        replacements = [
            (old_value, next(iter(new_values)))
            for old_value, new_values in candidates.items()
            if len(new_values) == 1
        ]
        return sorted(replacements, key=lambda pair: len(pair[0]), reverse=True)

    def _theme_attribute_names(self, theme: object) -> set[str]:
        names = {name for name in vars(theme) if name.isupper()}
        custom_theme = getattr(theme, "custom_theme", None)
        if custom_theme is not None:
            names.update(name for name in vars(custom_theme) if name.isupper())
        generated = getattr(theme, "_generated_styles", None)
        if generated:
            names.update(name for name in generated if name.isupper())
        parent = getattr(theme, "_default_theme", None)
        if parent is not None:
            names.update(self._theme_attribute_names(parent))
        return names

    def _on_system_theme_detected(self, is_light: bool) -> None:
        if ui_config.get_theme_variant() != "auto":
            return
        self._apply_system_theme_variant("light" if is_light else "dark")

    def _on_qt_color_scheme_changed(self, color_scheme: Qt.ColorScheme) -> None:
        if getattr(self, "_theme_change_in_progress", False):
            return
        if ui_config.get_theme_variant() != "auto":
            return
        is_light = color_scheme == Qt.ColorScheme.Light
        if _is_system_light_theme() != is_light:
            return
        watcher = getattr(self, "system_theme_watcher", None)
        if watcher is not None:
            watcher._last_light = is_light
        self._on_system_theme_detected(is_light)

    def _apply_system_theme_variant(self, variant: str) -> None:
        base_theme = ui_config.get_theme_base()
        theme_name = ui_config.resolve_theme(base_theme, variant)
        if theme_name == self.current_theme_name:
            return
        self._apply_theme_live(theme_name)
        ui_config.set_theme(base_theme)
        ui_config.set_theme_variant("auto")

    def _save_theme_tab_state(self) -> None:
        xdg_data_home = os.getenv("XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share"))
        state_file = os.path.join(xdg_data_home, "PortProtonQt", "state.txt")
        os.makedirs(os.path.dirname(state_file), exist_ok=True)
        try:
            with open(state_file, "w", encoding="utf-8") as f:
                f.write("theme_tab\n")
            logger.info(f"State saved to {state_file}")
        except OSError as e:
            logger.error(f"Failed to save state to {state_file}: {e}")

    def restore_state(self):
        """Restore application state after restart."""
        xdg_data_home = os.getenv("XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share"))
        state_file = os.path.join(xdg_data_home, "PortProtonQt", "state.txt")
        logger.info(f"Checking for state file: {state_file}")
        if os.path.exists(state_file):
            try:
                with open(state_file, encoding="utf-8") as f:
                    state = f.read().strip()
                    logger.info(f"State file contents: '{state}'")
                    if state == "theme_tab":
                        logger.info("Restoring to theme tab")
                        theme_index = getattr(self, "theme_tab_index", -1)
                        if theme_index >= 0 and self.stackedWidget.count() > theme_index:
                            self.switchTab(theme_index)
                        else:
                            logger.warning("Theme tab is not available yet")
                    else:
                        logger.warning(f"Unexpected state value: '{state}'")
                os.remove(state_file)
                logger.info(f"State file {state_file} removed")
            except Exception as e:
                logger.error(f"Failed to read or process state file {state_file}: {e}")
        else:
            logger.info(f"State file {state_file} does not exist")
