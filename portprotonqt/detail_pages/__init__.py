"""Detail pages for PortProtonQt."""

import os
import weakref
from collections.abc import Callable, Sequence

from shiboken6 import isValid
from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QHBoxLayout,
    QVBoxLayout,
    QFrame,
    QMessageBox,
    QScrollArea,
    QBoxLayout,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QUrl, QTimer, QProcess, QProcessEnvironment
from PySide6.QtGui import QDesktopServices

from portprotonqt.detail_pages.widgets import (
    create_scroll_area,
    create_back_button,
    create_content_frame,
    create_cover_frame,
    create_protondb_badge,
    create_portproton_badge,
    create_anticheat_badge,
    create_details_widget,
    create_compact_detail_header,
    create_compact_layout_panel,
    create_compact_description_panel,
    create_detail_separator,
)
from portprotonqt.detail_pages.utils import (
    setup_image_loading,
    validate_detail_page,
    set_opacity_safe,
    create_focus_helper,
    toggle_favorite,
    check_autoinstall_installed,
    find_autoinstall_entry_path,
)
from portprotonqt.howlongtobeat_api import HowLongToBeat, GameEntry
from portprotonqt.config import (
    extract_exec_target_path,
    favorites_config,
    get_portproton_start_command,
    ui_config,
)
from portprotonqt.custom_widgets import AutoSizeButton, ClickableLabel, FlowLayout
from portprotonqt.localization import _
from portprotonqt.logger import get_logger
from portprotonqt.animations import DetailPageAnimations
from portprotonqt.debug_utils import DebugLogManager
from portprotonqt.image_utils import cleanup_widget_animated_covers
from portprotonqt.icon_extractor import get_exe_icon_cache_path
from portprotonqt.steam_api import (
    get_local_steam_cover,
    get_steam_compat_tool,
    get_steam_home,
    get_steam_libs,
    safe_vdf_load,
)
from portprotonqt.time_utils import format_playtime

logger = get_logger(__name__)


class DetailPageManager:
    """Manages detail pages for games."""

    def __init__(self, main_window) -> None:
        self.main_window = main_window
        self._detail_page_active = False
        self._current_detail_page: QWidget | None = None
        self._exit_animation_in_progress = False
        self._animations: dict = {}
        self.debug_log_manager = DebugLogManager()
        self._debug_log_button: AutoSizeButton | None = None
        self._debug_log_timer = None
        self._autoinstall_status_controls = None
        self._current_detail_source: tuple[str, dict] | None = None
        self._resize_rebuild_pending = False
        self._gog_size_requests: dict[
            str, tuple[QProcess, list[list[Callable[[], QLabel | None]]]]
        ] = {}
        self._egs_size_requests: dict[
            str, tuple[QProcess, list[list[Callable[[], QLabel | None]]]]
        ] = {}

    def openGameDetailPage(self, game_data: dict) -> None:
        """Open detailed game information page."""
        self._current_detail_source = ("game", dict(game_data))
        detail_page = QWidget()
        detail_page.setProperty("coverCacheKey", str(game_data.get("appid", "")))
        fallback_exe, fallback_icon_path = self._get_exe_icon_fallback(game_data)
        detail_page.setProperty("fallbackExe", fallback_exe)
        detail_page.setProperty("fallbackIconPath", fallback_icon_path)
        compact_layout = self._is_compact_detail_layout()
        image_label = self._create_detail_image_label(compact_layout)

        self._setup_detail_page_common(detail_page, image_label, 0)
        detail_page.setProperty("force_compact_detail_layout", compact_layout)

        cover_frame = self._create_game_cover_frame(
            detail_page, game_data, image_label, compact_layout
        )

        description = game_data["description"]
        game_info_layout = self._create_game_info_layout(game_data)
        buttons_layout = self._create_game_buttons_layout(game_data)
        if compact_layout:
            page_data = self._create_compact_game_data(
                (cover_frame, image_label), game_data,
                game_info_layout, buttons_layout
            )
            self._finalize_compact_game_page(detail_page, page_data)
            return

        details_widget = create_details_widget(
            parent=detail_page,
            main_window=self.main_window,
            title=game_data["name"],
            description=description,
            game_info_layout=game_info_layout,
            controller_support=(
                None if compact_layout else game_data.get("controller_support")
            ),
            buttons_layout=buttons_layout,
            show_description=not compact_layout,
        )

        self._finalize_detail_page(
            detail_page, cover_frame, details_widget, image_label,
            game_data.get("exec_line", ""), game_data.get("cover_path")
        )

    @staticmethod
    def _get_exe_icon_fallback(game_data: dict) -> tuple[str, str]:
        exe_path = extract_exec_target_path(game_data.get("exec_line", ""))
        if not exe_path or not os.path.isfile(exe_path):
            return "", ""
        if not exe_path.lower().endswith(".exe"):
            return "", ""
        return exe_path, get_exe_icon_cache_path(exe_path)

    def _get_favorite_icon_name(self, name: str) -> str:
        return "star_fav_full" if name in favorites_config.get_games() else "star_fav"

    def _create_game_cover_frame(
        self,
        detail_page: QWidget,
        game_data: dict,
        image_label: QLabel,
        compact_layout: bool,
    ) -> QWidget:
        frame_width, frame_height = self._get_cover_frame_size(compact_layout)
        badges = self._create_game_badges(detail_page, game_data)
        return create_cover_frame(
            parent=detail_page,
            theme=self.main_window.theme,
            image_label=image_label,
            favorite_icon_name=self._get_favorite_icon_name(game_data["name"]),
            on_favorite_click=lambda: self._on_favorite_click(game_data["name"]),
            badges=badges,
            cover_width=frame_width,
            cover_height=frame_height,
            game_source=str(game_data.get("game_source", "")),
            theme_manager=self.main_window.theme_manager,
        )

    def _create_compact_game_data(
        self,
        cover_widgets: tuple[QWidget, QLabel],
        game_data: dict,
        game_info_layout: QVBoxLayout,
        buttons_layout: FlowLayout,
    ) -> dict:
        cover_frame, image_label = cover_widgets
        cover_path = game_data.get("cover_path")
        if str(game_data.get("game_source", "")).lower() == "steam":
            appid = game_data.get("appid", "")
            xdg_data_home = os.getenv(
                "XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share")
            )
            custom_dir = os.path.join(xdg_data_home, "PortProtonQt", "custom_data", str(appid))
            if os.path.dirname(os.path.abspath(cover_path or "")) != custom_dir:
                cover_path = get_local_steam_cover(appid) or cover_path
        return {
            "cover_frame": cover_frame,
            "image_label": image_label,
            "description": game_data.get("description", ""),
            "game_info_layout": game_info_layout,
            "buttons_layout": buttons_layout,
            "name": game_data.get("name", ""),
            "exec_line": game_data.get("exec_line", ""),
            "cover_path": cover_path,
        }

    def _is_compact_detail_layout(self) -> bool:
        if self._is_forced_compact_detail_layout():
            return True
        compact_cfg = getattr(self.main_window.theme, "DETAIL_COMPACT", {})
        return self._detail_view_width() <= compact_cfg.get("width", 1280)

    def _is_forced_compact_detail_layout(self) -> bool:
        layout_mode = str(
            getattr(self.main_window.theme, "DETAIL_PAGE_LAYOUT_MODE", "full")
        ).lower()
        return ui_config.get_economy_mode() or layout_mode == "compact"

    def _detail_view_width(self) -> int:
        widths = []
        for widget in (getattr(self.main_window, "stackedWidget", None), self.main_window):
            if widget is not None and widget.width() > 0:
                widths.append(widget.width())
        return min(widths) if widths else 0

    def _create_detail_image_label(self, compact_layout: bool) -> QLabel:
        cover_width, cover_height = self._get_cover_label_size(compact_layout)
        image_label = QLabel()
        image_label.setFixedSize(cover_width, cover_height)
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return image_label

    def _get_cover_label_size(self, compact_layout: bool) -> tuple[int, int]:
        cover_cfg = getattr(self.main_window.theme, "COVER", {})
        if not compact_layout:
            return cover_cfg.get("width", 300), cover_cfg.get("height", 450)
        size = getattr(
            self.main_window.theme,
            "detailCompactCoverImageSize",
            getattr(self.main_window.theme, "DETAIL_COMPACT", {}).get("cover_size", 128),
        )
        return size, size

    def _get_cover_frame_size(self, compact_layout: bool) -> tuple[int, int]:
        cover_cfg = getattr(self.main_window.theme, "COVER", {})
        if not compact_layout:
            return cover_cfg.get("width", 300), cover_cfg.get("height", 450)
        size = getattr(
            self.main_window.theme,
            "detailCompactCoverFrameSize",
            getattr(self.main_window.theme, "DETAIL_COMPACT", {}).get("cover_size", 128),
        )
        return size, size

    def _create_game_badges(self, parent: QWidget, game_data: dict) -> list:

        if self._is_compact_detail_layout():
            return []

        ppdb_id = str(game_data.get("ppdb_id", ""))
        ppdb_rating = str(game_data.get("ppdb_rating", ""))

        badges = []
        protondb_badge = self._create_protondb_badge(parent, game_data)
        if protondb_badge:
            badges.append(protondb_badge)
        if ppdb_id:
            badges.append(self._create_portproton_badge(parent, ppdb_id, ppdb_rating))
        anticheat_badge = self._create_anticheat_badge(parent, game_data)
        if anticheat_badge:
            badges.append(anticheat_badge)
        return badges

    def _create_protondb_badge(self, parent: QWidget, game_data: dict) -> dict | None:
        badge, visible = create_protondb_badge(
            parent, game_data.get("protondb_tier", ""),
            game_data.get("protondb_appid", game_data.get("appid", "")),
            self.main_window
        )
        return {"label": badge, "visible": True} if badge and visible else None

    def _create_portproton_badge(
        self,
        parent: QWidget,
        ppdb_id: str,
        ppdb_rating: str,
    ) -> dict:
        badge = create_portproton_badge(
            parent,
            self.main_window,
            ppdb_id,
            ppdb_rating,
        )
        return {"label": badge, "visible": True}

    def _create_anticheat_badge(self, parent: QWidget, game_data: dict) -> dict | None:
        badge, visible = create_anticheat_badge(
            parent,
            game_data.get("anticheat_status", ""),
            game_data.get("name", ""),
            game_data.get("anticheat_slug", ""),
            self.main_window
        )
        return {"label": badge, "visible": True} if badge and visible else None

    def _create_game_info_layout(self, game_data: dict) -> QVBoxLayout:
        game_info_layout = QVBoxLayout()
        game_info_layout.setSpacing(10)

        if ui_config.get_time_detail_level() != "hidden":
            formatted_playtime = game_data.get("formatted_playtime", "")
            playtime_seconds = game_data.get("playtime_seconds")
            if playtime_seconds is not None:
                formatted_playtime = format_playtime(playtime_seconds)
            first_row = self._create_playtime_row(
                game_data.get("last_launch", ""), formatted_playtime
            )
            game_info_layout.addLayout(first_row)

        self._setup_gog_size_data(game_data, game_info_layout)
        self._setup_egs_size_data(game_data, game_info_layout)

        hltb_layout = QHBoxLayout()
        hltb_layout.setSpacing(10)
        self._setup_hltb_data(game_data.get("name", ""), hltb_layout, game_info_layout)

        return game_info_layout

    def _setup_gog_size_data(
        self, game_data: dict, game_info_layout: QVBoxLayout
    ) -> None:
        exec_line = str(game_data.get("exec_line", ""))
        if str(game_data.get("game_source", "")).lower() != "gog":
            return
        if not exec_line.startswith("gog://install/"):
            return
        row = QHBoxLayout()
        values = []
        for title_text in (_("Download"), _("Size")):
            title = QLabel(title_text.upper())
            title.setStyleSheet(self.main_window.theme.LAST_LAUNCH_TITLE_STYLE)
            value = QLabel("—")
            value.setStyleSheet(self.main_window.theme.LAST_LAUNCH_VALUE_STYLE)
            row.addWidget(title)
            row.addWidget(value)
            row.addSpacing(30)
            values.append(weakref.ref(value))
        game_info_layout.addLayout(row)
        app_id = exec_line.rsplit("/", 1)[-1]
        cached = self.main_window.gog_api.get_cached_download_sizes(app_id)
        if cached is not None:
            self._set_gog_size_values(values, cached)
            return
        request = self._gog_size_requests.get(app_id)
        if request is not None:
            request[1].append(values)
            return
        try:
            command = self.main_window.gog_api.build_command(
                ["info", app_id, "--platform", "windows", "--skip-dlcs"]
            )
        except FileNotFoundError as error:
            logger.warning("Failed to get GOG download size: %s", error)
            return
        process = QProcess(self.main_window)
        process.setProgram(command[0])
        process.setArguments(command[1:])
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("GOGDL_CONFIG_PATH", str(self.main_window.gog_api.config_dir))
        process.setProcessEnvironment(environment)
        self._gog_size_requests[app_id] = (process, [values])
        process.finished.connect(
            lambda code, _status: self._finish_gog_size_request(app_id, code)
        )
        process.start()

    def _setup_egs_size_data(
        self, game_data: dict, game_info_layout: QVBoxLayout
    ) -> None:
        exec_line = str(game_data.get("exec_line", ""))
        if str(game_data.get("game_source", "")).lower() != "egs":
            return
        if not exec_line.startswith("egs://install/"):
            return
        row = QHBoxLayout()
        values = []
        for title_text in (_("Download"), _("Size")):
            title = QLabel(title_text.upper())
            title.setStyleSheet(self.main_window.theme.LAST_LAUNCH_TITLE_STYLE)
            value = QLabel("—")
            value.setStyleSheet(self.main_window.theme.LAST_LAUNCH_VALUE_STYLE)
            row.addWidget(title)
            row.addWidget(value)
            row.addSpacing(30)
            values.append(weakref.ref(value))
        game_info_layout.addLayout(row)
        app_id = exec_line.rsplit("/", 1)[-1]
        api = self.main_window.egs_api
        cached = api.get_cached_download_sizes(app_id)
        if cached is not None:
            self._set_gog_size_values(values, cached)
            return
        request = self._egs_size_requests.get(app_id)
        if request is not None:
            request[1].append(values)
            return
        try:
            command = api.build_command(["info", app_id, "--json", "--platform", "Windows"])
        except (FileNotFoundError, OSError) as error:
            logger.warning("Failed to get EGS download size: %s", error)
            return
        process = QProcess(self.main_window)
        process.setProgram(command[0])
        process.setArguments(command[1:])
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("LEGENDARY_CONFIG_PATH", str(api.config_dir))
        process.setProcessEnvironment(environment)
        self._egs_size_requests[app_id] = (process, [values])
        process.finished.connect(
            lambda code, _status: self._finish_egs_size_request(app_id, code)
        )
        process.start()

    def _finish_egs_size_request(self, app_id: str, code: int) -> None:
        request = self._egs_size_requests.pop(app_id, None)
        if request is None:
            return
        process, value_groups = request
        if code != 0:
            logger.warning("legendary info exited with code %s", code)
            process.deleteLater()
            return
        try:
            sizes = self.main_window.egs_api.parse_download_sizes(
                bytes(process.readAllStandardOutput().data())
            )
        except (ValueError, TypeError) as error:
            logger.warning("Failed to parse EGS download size: %s", error)
            process.deleteLater()
            return
        self.main_window.egs_api.save_download_sizes(app_id, sizes)
        for value_refs in value_groups:
            self._set_gog_size_values(value_refs, sizes)
        process.deleteLater()

    def _finish_gog_size_request(self, app_id: str, code: int) -> None:
        request = self._gog_size_requests.pop(app_id, None)
        if request is None:
            return
        process, value_groups = request
        if code != 0:
            logger.warning("gogdl info exited with code %s", code)
            process.deleteLater()
            return
        try:
            sizes = self.main_window.gog_api.parse_download_sizes(
                bytes(process.readAllStandardOutput().data())
            )
        except (ValueError, TypeError) as error:
            logger.warning("Failed to parse GOG download size: %s", error)
            process.deleteLater()
            return
        self.main_window.gog_api.save_download_sizes(app_id, sizes)
        for value_refs in value_groups:
            self._set_gog_size_values(value_refs, sizes)
        process.deleteLater()

    @staticmethod
    def _set_gog_size_values(
        value_refs: list[Callable[[], QLabel | None]], sizes: tuple[int, int]
    ) -> None:
        for value_ref, size in zip(value_refs, sizes, strict=True):
            label = value_ref()
            if label is None or not isValid(label):
                continue
            divisor, unit = (
                (1024 ** 3, "GiB") if size >= 1024 ** 3 else (1024 ** 2, "MiB")
            )
            label.setText(f"{size / divisor:.1f} {unit}")

    def _create_playtime_row(self, last_launch: str, formatted_playtime: str) -> QHBoxLayout:
        """Create first row with last launch and playtime."""
        first_row = QHBoxLayout()
        first_row.setSpacing(10)

        last_launch_title = QLabel(_("LAST LAUNCH"))
        last_launch_title.setObjectName("detailLastLaunchTitle")
        last_launch_title.setStyleSheet(self.main_window.theme.LAST_LAUNCH_TITLE_STYLE)
        last_launch_value = QLabel(last_launch)
        last_launch_value.setObjectName("detailLastLaunchValue")
        last_launch_value.setStyleSheet(self.main_window.theme.LAST_LAUNCH_VALUE_STYLE)

        playtime_title = QLabel(_("TIME SPENT"))
        playtime_title.setObjectName("detailPlaytimeTitle")
        playtime_title.setStyleSheet(self.main_window.theme.PLAY_TIME_TITLE_STYLE)
        playtime_value = QLabel(formatted_playtime)
        playtime_value.setObjectName("detailPlaytimeValue")
        playtime_value.setStyleSheet(self.main_window.theme.PLAY_TIME_VALUE_STYLE)

        for widget in (last_launch_title, last_launch_value, playtime_title, playtime_value):
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        first_row.addWidget(last_launch_title)
        first_row.addWidget(last_launch_value)
        first_row.addSpacing(30)
        first_row.addWidget(playtime_title)
        first_row.addWidget(playtime_value)

        return first_row

    def _setup_hltb_data(
        self, name: str, hltb_layout: QHBoxLayout, game_info_layout: QVBoxLayout
    ) -> None:
        """Setup HowLongToBeat data loading."""
        if self._is_compact_detail_layout():
            return
        hltb = HowLongToBeat(parent=self.main_window)
        detail_page = self._current_detail_page

        def on_hltb_results(results: list) -> None:
            if detail_page is not self._current_detail_page:
                return
            self._on_hltb_results(results, hltb, hltb_layout, game_info_layout)

        hltb.searchCompleted.connect(on_hltb_results)
        hltb.search_with_callback(name, case_sensitive=False)

    def _on_hltb_results(
        self,
        results: list,
        hltb: HowLongToBeat,
        hltb_layout: QHBoxLayout,
        game_info_layout: QVBoxLayout,
    ) -> None:
        """Handle HLTB search results."""
        if not self._detail_page_active or not self._current_detail_page:
            return
        if not self._current_detail_page.parent() or self._current_detail_page.isHidden():
            return

        if not results:
            return

        game = results[0]
        has_data = self._add_hltb_times(game, hltb, hltb_layout)

        if has_data:
            game_info_layout.addLayout(hltb_layout)
            QTimer.singleShot(0, self._refresh_current_detail_page_layout)

    def _refresh_current_detail_page_layout(self) -> None:
        """Refresh layout after asynchronous detail content changes."""
        if not self._detail_page_active or not self._current_detail_page:
            return

        content_frame_layout = self._get_content_frame_layout(self._current_detail_page)
        if content_frame_layout:
            content_frame_layout.invalidate()
            self._queue_resize_rebuild()

        self._current_detail_page.updateGeometry()

    def _add_hltb_times(
        self, game: GameEntry, hltb: HowLongToBeat, hltb_layout: QHBoxLayout
    ) -> bool:
        """Add HLTB time displays to layout."""
        self._add_hltb_time_field(game, hltb, hltb_layout, "main_story", _("MAIN STORY"))
        self._add_hltb_time_field(game, hltb, hltb_layout, "main_extra", _("MAIN + SIDES"))
        self._add_hltb_time_field(game, hltb, hltb_layout, "completionist", _("COMPLETIONIST"))
        return hltb_layout.count() > 0

    def _add_hltb_time_field(
        self,
        game: GameEntry,
        hltb: HowLongToBeat,
        layout: QHBoxLayout,
        field: str,
        title_text: str,
    ) -> None:
        """Add single HLTB time field to layout."""
        time_value = hltb.format_game_time(game, field)
        if not time_value:
            return

        title_style = self.main_window.theme.LAST_LAUNCH_TITLE_STYLE
        value_style = self.main_window.theme.LAST_LAUNCH_VALUE_STYLE

        if field == "main_extra":
            title_style = self.main_window.theme.PLAY_TIME_TITLE_STYLE
            value_style = self.main_window.theme.PLAY_TIME_VALUE_STYLE

        title = QLabel(title_text)
        title.setStyleSheet(title_style)
        value = QLabel(time_value)
        value.setStyleSheet(value_style)
        layout.addWidget(title)
        layout.addWidget(value)
        layout.addSpacing(30)

    def _create_game_buttons_layout(self, game_data: dict) -> FlowLayout:
        """Create buttons layout for game detail page."""
        buttons_layout = FlowLayout(center_rows=False)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        exec_line = game_data.get("exec_line", "")
        game_source = game_data.get("game_source", "")
        appid = game_data.get("appid", "")
        game_name = game_data.get("name", "")
        cover_path = game_data.get("cover_path", "")

        current_exe = self._get_current_exe(exec_line)
        play_button = self._create_play_button(exec_line, current_exe)
        source = str(game_source).lower()
        install_uri = exec_line.startswith(f"{source}://install/")
        if source in {"gog", "egs"} and install_uri:
            play_button.setText(_("Install"))
            play_button.setIcon(
                self.main_window.theme_manager.get_icon("update", as_path=True)
            )
        buttons_layout.addWidget(play_button)

        if source in {"steam", "gog", "egs"} and appid:
            edit_button = self._make_action_button(
                _("Edit Shortcut"),
                self.main_window.theme_manager.get_icon("edit", as_path=True),
            )
            if source == "steam":
                edit_button.clicked.connect(
                    lambda: self.main_window.context_menu_manager.edit_game_shortcut(
                        game_name, exec_line, cover_path, appid
                    )
                )
            else:
                edit_button.clicked.connect(
                    lambda: self.main_window.context_menu_manager._edit_id_shortcut(
                        game_name, cover_path, (source, str(appid))
                    )
                )
            buttons_layout.addWidget(edit_button)
        elif self._has_game_shortcut(game_name):
            edit_button = self._make_action_button(
                _("Edit Shortcut"),
                self.main_window.theme_manager.get_icon("edit", as_path=True),
            )
            edit_button.clicked.connect(
                lambda: self.main_window.context_menu_manager.edit_game_shortcut(
                    game_name, exec_line, cover_path
                )
            )
            buttons_layout.addWidget(edit_button)
        if str(game_source).lower() == "steam" and appid:
            open_folder_button = self._make_action_button(
                _("Open Folder"),
                self.main_window.theme_manager.get_icon("search", as_path=True),
            )
            open_folder_button.clicked.connect(
                lambda: self._open_steam_game_folder(str(appid))
            )
            buttons_layout.addWidget(open_folder_button)
        elif (
            str(game_source).lower() not in {"gog", "egs"}
            and not self._has_game_shortcut(game_name)
        ):
            add_button = self._make_action_button(
                _("Add a shortcut"),
                self.main_window.theme_manager.get_icon("addgame", as_path=True),
            )
            add_button.clicked.connect(
                lambda: self.main_window.openAddGameDialog(
                    self._get_file_from_exec(exec_line) or exec_line
                )
            )
            buttons_layout.addWidget(add_button)

        # Show settings button for PortProton games or Steam games using PortProtonQt
        if str(game_source).lower() == "portproton":
            self._add_portproton_buttons(buttons_layout, exec_line)
        elif (
            source in {"gog", "egs"}
            and appid
            and exec_line.startswith(f"{source}://launch/")
        ):
            store_api = (
                self.main_window.gog_api if source == "gog"
                else self.main_window.egs_api
            )
            store_exe = store_api.get_launch_target(str(appid))
            if not store_exe:
                return buttons_layout
            if source == "gog":
                store_api.ensure_launch_parameters(str(appid))
            settings_button = self._make_action_button(
                _("Settings"),
                self.main_window.theme_manager.get_icon("settings", as_path=True),
            )
            settings_button.clicked.connect(
                lambda: self.main_window.open_exe_settings(
                    store_exe, game_source=source,
                )
            )
            buttons_layout.addWidget(settings_button)
            log_button = self._make_action_button(
                _("Create Log"),
                self.main_window.theme_manager.get_icon("edit", as_path=True),
            )
            log_button.clicked.connect(
                lambda: self.toggleDebugLog(store_exe, log_button)
            )
            buttons_layout.addWidget(log_button)
            self._debug_log_button = log_button
            folder_button = self._make_action_button(
                _("Open Folder"),
                self.main_window.theme_manager.get_icon("search", as_path=True),
            )
            folder_button.clicked.connect(
                lambda: self._open_executable_folder(store_exe)
            )
            buttons_layout.addWidget(folder_button)
        elif str(game_source).lower() == "steam" and appid:
            try:
                compat_tool = get_steam_compat_tool(int(appid))
                if compat_tool == "PortProtonQt":
                    self._add_steam_settings_button(buttons_layout, exec_line, str(appid))
            except (ValueError, TypeError):
                pass

        return buttons_layout

    def _get_current_exe(self, exec_line: str) -> str | None:
        """Extract current executable from exec line."""
        file_to_check = extract_exec_target_path(exec_line)
        return os.path.basename(file_to_check) if file_to_check else None

    def _create_play_button(self, exec_line: str, current_exe: str | None) -> AutoSizeButton:
        """Create play/stop button."""
        if self.main_window.target_exe is not None and current_exe == self.main_window.target_exe:
            text = _("Stop")
            icon = self.main_window.theme_manager.get_icon("stop", as_path=True)
        else:
            text = _("Start")
            icon = self.main_window.theme_manager.get_icon("play", as_path=True)

        play_button = self._make_action_button(text, icon)
        play_button.setProperty("sound_event", False)
        play_button.clicked.connect(lambda: self.main_window.toggleGame(exec_line, play_button))
        return play_button

    def _add_portproton_buttons(self, buttons_layout: FlowLayout, exec_line: str) -> None:
        """Add settings, log, and open folder buttons for PortProton games."""
        file_to_check = self._get_file_from_exec(exec_line)

        settings_icon = self.main_window.theme_manager.get_icon("settings", as_path=True)
        settings_button = self._make_action_button(_("Settings"), settings_icon)
        settings_button.clicked.connect(
            lambda: self.main_window.open_exe_settings(file_to_check, game_source="portproton")
        )
        buttons_layout.addWidget(settings_button)

        log_icon = self.main_window.theme_manager.get_icon("edit", as_path=True)
        log_button = self._make_action_button(_("Create Log"), log_icon)
        log_button.clicked.connect(lambda: self.toggleDebugLog(file_to_check, log_button))
        buttons_layout.addWidget(log_button)
        self._debug_log_button = log_button

        open_folder_button = self._make_action_button(
            _("Open Folder"),
            self.main_window.theme_manager.get_icon("search", as_path=True),
        )
        open_folder_button.clicked.connect(
            lambda: self._open_portproton_game_folder(exec_line)
        )
        buttons_layout.addWidget(open_folder_button)

    def _add_steam_settings_button(self, buttons_layout: FlowLayout, exec_line: str, appid: str) -> None:
        """Add only settings button for Steam games."""
        # Create fake exe path in steam_scripts folder
        portproton_location = self.main_window.portproton_location
        if not portproton_location:
            return
        steam_scripts_dir = os.path.join(portproton_location, "steam_scripts")
        os.makedirs(steam_scripts_dir, exist_ok=True)
        fake_exe_path = os.path.join(steam_scripts_dir, f"{appid}.exe")
        # Create empty file if it doesn't exist
        if not os.path.exists(fake_exe_path):
            open(fake_exe_path, 'a').close()

        settings_icon = self.main_window.theme_manager.get_icon("settings", as_path=True)
        settings_button = self._make_action_button(_("Settings"), settings_icon)
        settings_button.clicked.connect(
            lambda: self.main_window.open_exe_settings(fake_exe_path, appid, "steam")
        )
        buttons_layout.addWidget(settings_button)

    def _get_file_from_exec(self, exec_line: str) -> str | None:
        """Get file path from exec line."""
        return extract_exec_target_path(exec_line)

    def _open_steam_game_folder(self, appid: str) -> None:
        """Open Steam game installation folder by appid."""
        steam_home = get_steam_home()
        if steam_home is None:
            return

        for lib in get_steam_libs(steam_home):
            manifest = lib / "steamapps" / f"appmanifest_{appid}.acf"
            if not manifest.exists():
                continue
            data = safe_vdf_load(manifest)
            install_dir = data.get("AppState", {}).get("installdir")
            if not install_dir:
                return
            folder_path = lib / "steamapps" / "common" / install_dir
            if not folder_path.exists():
                return
            linux_subdir = folder_path / f"{install_dir}_linux"
            if linux_subdir.exists():
                folder_path = linux_subdir
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder_path)))
            return

    def _open_portproton_game_folder(self, exec_line: str) -> None:
        """Open folder containing the PortProton game executable."""
        file_to_check = self._get_file_from_exec(exec_line)
        self._open_executable_folder(file_to_check)

    def _open_executable_folder(self, exe_path: str | None) -> None:
        """Open the folder containing an executable."""
        if not exe_path or not os.path.exists(exe_path):
            return
        folder_path = os.path.dirname(os.path.abspath(exe_path))
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder_path))

    def _has_game_shortcut(self, game_name: str) -> bool:
        """Check whether game has a desktop shortcut in PortProton location."""
        context_menu_manager = getattr(self.main_window, "context_menu_manager", None)
        if context_menu_manager is None:
            return False
        desktop_path = context_menu_manager._get_desktop_path(game_name)
        return bool(desktop_path and os.path.exists(desktop_path))

    def _make_action_button(self, text: str, icon) -> AutoSizeButton:
        """Create styled action button."""
        button = AutoSizeButton(text, icon=icon)
        button.setFixedHeight(40)
        button.setMinimumWidth(120)
        button.setStyleSheet(self.main_window.theme.PLAY_BUTTON_STYLE)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        return button

    def _setup_detail_page_common(
        self, detail_page: QWidget, image_label: QLabel, return_tab_index: int
    ) -> None:
        """Common setup for all detail pages."""
        self._detail_page_active = True
        self._current_detail_page = detail_page
        self._return_to_tab_index = return_tab_index

        scroll_area, scroll_content, main_layout = create_scroll_area(
            detail_page, self.main_window.theme
        )

        create_back_button(
            main_layout,
            self.main_window.theme,
            self.main_window.theme_manager,
            lambda: self.goBackDetailPage(detail_page),
        )

        content_frame, content_frame_layout = create_content_frame(
            main_layout, self.main_window.theme
        )
        if self._is_compact_detail_layout():
            content_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._setup_resize_rebuild(detail_page)

        self.main_window.stackedWidget.addWidget(detail_page)
        self.main_window.stackedWidget.setCurrentWidget(detail_page)
        self.main_window.currentDetailPage = detail_page

    def _setup_resize_rebuild(self, detail_page: QWidget) -> None:
        if self._is_forced_compact_detail_layout():
            return

        def handle_resize_event(event) -> None:
            QWidget.resizeEvent(detail_page, event)
            self._queue_resize_rebuild()

        detail_page.resizeEvent = handle_resize_event

    def _queue_resize_rebuild(self) -> None:
        if self._is_forced_compact_detail_layout() or self._resize_rebuild_pending:
            return

        self._resize_rebuild_pending = True
        QTimer.singleShot(120, self._rebuild_after_resize)

    def _rebuild_after_resize(self) -> None:
        self._resize_rebuild_pending = False
        if not self._can_rebuild_after_resize():
            return

        detail_page = self._current_detail_page
        if detail_page is None:
            return

        current_compact = bool(detail_page.property("force_compact_detail_layout"))
        requested_compact = self._is_compact_detail_layout()
        if current_compact == requested_compact:
            return

        self._reopen_current_detail_page()

    def _can_rebuild_after_resize(self) -> bool:
        return (
            self._detail_page_active
            and self._current_detail_page is not None
            and self._current_detail_source is not None
            and self._current_detail_page.parent() is not None
            and not self._current_detail_page.isHidden()
        )

    def _reopen_current_detail_page(self) -> None:
        source = self._current_detail_source
        if source is None:
            return

        source_kind, source_data = source
        return_tab_index = getattr(self, "_return_to_tab_index", 0)
        current_page = self._current_detail_page
        running_button = self.main_window.current_running_button
        debug_log_button = self._debug_log_button
        replace_running_button = (
            current_page is not None
            and running_button is not None
            and current_page.isAncestorOf(running_button)
        )
        replace_debug_log_button = (
            current_page is not None
            and debug_log_button is not None
            and current_page.isAncestorOf(debug_log_button)
        )
        self._remove_current_detail_page()
        if source_kind == "autoinstall":
            self.openAutoInstallDetailPage(source_data)
        else:
            self.openGameDetailPage(source_data)
        self._return_to_tab_index = return_tab_index
        if (
            replace_debug_log_button
            and self.debug_log_manager.is_running
            and self._debug_log_button is not None
        ):
            self._debug_log_button.setText(_("Stop Log"))
            icon = self.main_window.theme_manager.get_icon("stop", as_path=True)
            if icon:
                self._debug_log_button.setIcon(icon)
        if replace_running_button and self._current_detail_page is not None:
            play_button = self._find_play_button(self._current_detail_page)
            if play_button is not None:
                self.main_window.current_running_button = play_button
                self.main_window._set_running_button_stop()

    def _finalize_detail_page(
        self,
        detail_page: QWidget,
        cover_frame: QWidget,
        details_widget: QWidget,
        image_label: QLabel,
        exec_line: str,
        cover_path: str | None,
    ) -> None:
        """Finalize detail page setup with animations and focus."""
        content_frame_layout = self._get_content_frame_layout(detail_page)
        if content_frame_layout:
            content_frame_layout.addWidget(cover_frame)
            content_frame_layout.addWidget(details_widget)

        main_layout = self._get_main_layout(detail_page)
        if main_layout:
            main_layout.addStretch()

        self.main_window.current_exec_line = exec_line
        self._setup_detail_page_animation(detail_page, image_label, details_widget, cover_path)

    def _finalize_compact_game_page(self, detail_page: QWidget, page_data: dict) -> None:
        """Finalize compact game detail page."""
        content_frame_layout = self._get_content_frame_layout(detail_page)
        if content_frame_layout:
            self._populate_compact_game_layout(detail_page, content_frame_layout, page_data)

        main_layout = self._get_main_layout(detail_page)
        if main_layout:
            main_layout.addStretch()

        self.main_window.current_exec_line = page_data["exec_line"]
        cover_path = (
            None
            if detail_page.property("fallbackExe")
            else page_data["cover_path"]
        )
        self._setup_detail_page_animation(
            detail_page,
            page_data["image_label"],
            detail_page,
            cover_path,
        )

    def _populate_compact_game_layout(
        self, detail_page: QWidget, content_frame_layout: QBoxLayout, page_data: dict
    ) -> None:
        content_frame_layout.setDirection(QBoxLayout.Direction.TopToBottom)
        content_frame_layout.setSpacing(self._get_compact_content_spacing())
        content_frame_layout.addWidget(
            create_compact_detail_header(
                detail_page, self.main_window.theme,
                page_data["cover_frame"], page_data["name"]
            )
        )
        # content_frame_layout.addWidget(create_detail_separator(self.main_window.theme))
        if page_data["description"].strip():
            content_frame_layout.addWidget(
                create_compact_description_panel(
                    detail_page, self.main_window.theme, page_data["description"]
                )
            )
        content_frame_layout.addWidget(
            create_compact_layout_panel(
                detail_page, self.main_window.theme, page_data["game_info_layout"]
            )
        )
        content_frame_layout.addLayout(page_data["buttons_layout"])

    def _get_compact_content_spacing(self) -> int:
        return getattr(
            self.main_window.theme,
            "detailCompactContentSpacing",
            self.main_window.theme.portProtonPageVerticalSpacing,
        )

    def _setup_detail_page_animation(
        self, detail_page: QWidget, image_label: QLabel, details_widget: QWidget, cover_path: str | None
    ) -> None:
        """Setup animation for detail page."""
        play_button = self._find_play_button(details_widget)

        def setup_focus() -> None:
            if play_button:
                self._setup_focus_after_animation(detail_page, play_button)

        self._start_detail_page_animation(
            detail_page, image_label, cover_path, setup_focus
        )

    def _get_content_frame_layout(self, detail_page: QWidget) -> QBoxLayout | None:
        """Get content frame layout from detail page."""
        scroll_area = detail_page.findChild(QScrollArea)
        if not scroll_area:
            return None
        scroll_content = scroll_area.widget()
        if not scroll_content or not scroll_content.layout():
            return None
        return self._find_content_layout_in_frame(scroll_content.layout())

    def _find_content_layout_in_frame(self, layout) -> QBoxLayout | None:
        """Find content layout inside frame."""
        for i in range(layout.count()):
            item = layout.itemAt(i)
            widget = item.widget() if item else None
            if isinstance(widget, QFrame):
                return self._find_box_layout_in_widget(widget)
        return None

    def _find_box_layout_in_widget(self, widget: QWidget) -> QBoxLayout | None:
        """Find QBoxLayout in widget children."""
        for child in widget.children():
            if isinstance(child, QBoxLayout):
                return child
        return None

    def _get_main_layout(self, detail_page: QWidget) -> QVBoxLayout | None:
        """Get main layout from detail page."""
        scroll_area = detail_page.findChild(QScrollArea)
        if not scroll_area:
            return None
        scroll_content = scroll_area.widget()
        if not scroll_content:
            return None
        layout = scroll_content.layout()
        return layout if isinstance(layout, QVBoxLayout) else None

    def _setup_focus_after_animation(self, detail_page: QWidget, play_button: QWidget) -> None:
        """Setup focus on play button after animation."""
        focus_helper = create_focus_helper(
            detail_page, self.main_window, play_button, self.main_window.stackedWidget
        )
        QTimer.singleShot(50, focus_helper)

    def _find_play_button(self, details_widget: QWidget) -> QWidget | None:
        """Find play button in details widget."""
        for child in details_widget.findChildren(AutoSizeButton):
            if self._is_action_button_text(child.text()):
                return child
        return None

    def _is_action_button_text(self, text: str) -> bool:
        """Check if button text is a primary game action."""
        return text in (_("Start"), _("Stop"), _("Install"))

    def _on_favorite_click(self, name: str) -> str:
        """Handle favorite toggle click."""
        return toggle_favorite(name, self.main_window)

    def openAutoInstallDetailPage(self, game_data: dict, return_tab_index: int = 1) -> None:
        """Open minimal detail page for auto-install games."""
        self._current_detail_source = ("autoinstall", dict(game_data))
        detail_page = QWidget()
        compact_layout = self._is_compact_detail_layout()
        frame_width, frame_height = self._get_cover_frame_size(compact_layout)
        image_label = self._create_detail_image_label(compact_layout)

        self._setup_detail_page_common(detail_page, image_label, return_tab_index)
        detail_page.setProperty("force_compact_detail_layout", compact_layout)

        exec_line = game_data.get("exec_line", "")
        script_name = self._extract_script_name(exec_line)
        self._return_to_autoinstall_card = game_data.get("autoinstall_exe_name", "")
        description = self._get_enhanced_description(script_name, game_data.get("description", ""))

        cover_frame = create_cover_frame(
            parent=detail_page,
            theme=self.main_window.theme,
            image_label=image_label,
            cover_width=frame_width,
            cover_height=frame_height,
        )

        buttons_layout = FlowLayout(center_rows=False)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        install_button = self._create_autoinstall_buttons_layout(
            script_name, game_data.get("name", ""), buttons_layout
        )

        if compact_layout:
            widgets = (cover_frame, image_label, buttons_layout)
            page_data = self._create_compact_autoinstall_data(
                widgets, description, game_data
            )
            self._finalize_compact_autoinstall_page(
                detail_page, page_data, install_button
            )
            return

        details_widget = create_details_widget(
            parent=detail_page,
            main_window=self.main_window,
            title=game_data.get("name", ""),
            description=description,
            buttons_layout=buttons_layout,
        )
        self._finalize_autoinstall_page(
            detail_page, cover_frame, details_widget, image_label,
            game_data.get("cover_path"), install_button
        )

    def _create_compact_autoinstall_data(
        self,
        widgets: tuple[QWidget, QLabel, FlowLayout],
        description: str,
        game_data: dict,
    ) -> dict:
        cover_frame, image_label, buttons_layout = widgets
        return {
            "cover_frame": cover_frame,
            "image_label": image_label,
            "description": description,
            "buttons_layout": buttons_layout,
            "name": game_data.get("name", ""),
            "cover_path": game_data.get("cover_path"),
        }

    def _finalize_compact_autoinstall_page(
        self,
        detail_page: QWidget,
        page_data: dict,
        install_button: AutoSizeButton,
    ) -> None:
        """Finalize compact auto-install detail page."""
        content_frame_layout = self._get_content_frame_layout(detail_page)
        if content_frame_layout:
            content_frame_layout.setDirection(QBoxLayout.Direction.TopToBottom)
            content_frame_layout.setSpacing(self._get_compact_content_spacing())
            content_frame_layout.addWidget(
                create_compact_detail_header(
                    detail_page, self.main_window.theme,
                    page_data["cover_frame"], page_data["name"]
                )
            )
            content_frame_layout.addWidget(
                create_detail_separator(self.main_window.theme)
            )
            content_frame_layout.addWidget(
                create_compact_description_panel(
                    detail_page, self.main_window.theme, page_data["description"]
                )
            )
            content_frame_layout.addLayout(page_data["buttons_layout"])

        main_layout = self._get_main_layout(detail_page)
        if main_layout:
            main_layout.addStretch()

        self._setup_autoinstall_animation(
            detail_page, page_data["image_label"],
            page_data["cover_path"], install_button
        )

    def _extract_script_name(self, exec_line: str) -> str:
        """Extract script name from exec line."""
        if exec_line and exec_line.startswith("autoinstall:"):
            script_name = exec_line[11:].lstrip(":").strip()
            return extract_exec_target_path(script_name) or script_name
        return ""

    def _get_enhanced_description(self, script_name: str, description: str) -> str:
        """Get enhanced description from metadata if available."""
        return description

    def _create_autoinstall_buttons_layout(
        self, script_name: str, name: str, buttons_layout: FlowLayout
    ) -> AutoSizeButton:
        """Create install button for auto-install page."""
        install_button = self._make_action_button(
            _("Install"),
            self.main_window.theme_manager.get_icon("save", as_path=True),
        )
        install_button.clicked.connect(
            lambda: self.main_window.launch_autoinstall(script_name, install_button)
        )
        buttons_layout.addWidget(install_button)

        open_button = self._make_action_button(
            _("Open Card"),
            self.main_window.theme_manager.get_icon("play", as_path=True),
        )
        open_button.clicked.connect(
            lambda: self._open_installed_autoinstall_card(script_name, name)
        )
        open_button.setVisible(False)
        buttons_layout.addWidget(open_button)

        self._autoinstall_status_controls = (
            script_name, name, install_button, open_button
        )
        self._check_install_status(script_name, name, install_button, open_button)

        return install_button

    def refresh_autoinstall_install_status(self, script_name: str | None) -> None:
        """Refresh install buttons for opened auto-install page."""
        controls = self._autoinstall_status_controls
        if not script_name or not controls or controls[0] != script_name:
            return
        self._check_install_status(*controls)

    def _check_install_status(
        self,
        script_name: str,
        name: str,
        install_button: AutoSizeButton,
        open_button: AutoSizeButton,
    ) -> None:
        """Check install status asynchronously and update button."""
        def on_result(is_installed: bool) -> None:
            text = _("Reinstall") if is_installed else _("Install")
            icon_name = "update" if is_installed else "save"
            icon = self.main_window.theme_manager.get_icon(icon_name, as_path=True)
            if icon:
                install_button.setIcon(icon)
            install_button.setText(text)
            open_button.setVisible(is_installed)

            if (
                self.main_window.installing
                and self.main_window.current_install_script == script_name
            ):
                self.main_window._set_install_button_stop(install_button)
                status = getattr(self.main_window, "current_install_status", None)
                percent = getattr(self.main_window, "current_percent", None)
                self.main_window._set_install_button_progress_text(status, percent)
                return

        check_autoinstall_installed(
            script_name, name, self.main_window.portproton_location, callback=on_result
        )

    def _open_installed_autoinstall_card(self, script_name: str, name: str) -> None:
        """Open detail page for installed autoinstall game."""
        desktop_path = find_autoinstall_entry_path(
            script_name, self.main_window.portproton_location
        )
        if not desktop_path:
            QMessageBox.warning(self.main_window, _("Error"), _("Game not found."))
            return

        def on_game_data(game_tuple: tuple | None) -> None:
            if not game_tuple:
                QMessageBox.warning(self.main_window, _("Error"), _("Game not found."))
                return
            game_data = self._game_tuple_to_data(game_tuple)
            self._return_to_autoinstall_card = self._get_exec_name(game_data["exec_line"])
            self._remove_current_detail_page()
            self.main_window.switchTab(0)
            self.openGameDetailPage(game_data)
            self._return_to_tab_index = 0

        self.main_window._process_desktop_file_async(desktop_path, on_game_data)

    def _get_exec_name(self, exec_line: str) -> str:
        exec_path = extract_exec_target_path(exec_line)
        if not exec_path:
            return ""
        return os.path.splitext(os.path.basename(exec_path))[0]

    def _remove_current_detail_page(self) -> None:
        page = self.main_window.currentDetailPage
        if page and self._page_in_stacked(page):
            self.main_window.detach_install_button(page)
            self.main_window.stackedWidget.removeWidget(page)
            page.deleteLater()
        self._autoinstall_status_controls = None
        self.main_window.currentDetailPage = None
        self._current_detail_page = None

    def _game_tuple_to_data(self, game_tuple: Sequence[object]) -> dict:
        return {
            "name": game_tuple[0],
            "description": game_tuple[1],
            "cover_path": game_tuple[2],
            "appid": game_tuple[3],
            "controller_support": game_tuple[4],
            "exec_line": game_tuple[5],
            "last_launch": game_tuple[6],
            "formatted_playtime": game_tuple[7],
            "protondb_tier": game_tuple[8],
            "anticheat_status": game_tuple[9],
            "playtime_seconds": game_tuple[11],
            "game_source": game_tuple[12],
            "anticheat_slug": game_tuple[13] if len(game_tuple) > 13 else "",
            "ppdb_id": game_tuple[14] if len(game_tuple) > 14 else "",
            "ppdb_rating": game_tuple[15] if len(game_tuple) > 15 else "",
            "protondb_appid": game_tuple[16] if len(game_tuple) > 16 else game_tuple[3],
        }

    def _finalize_autoinstall_page(
        self,
        detail_page: QWidget,
        cover_frame: QWidget,
        details_widget: QWidget,
        image_label: QLabel,
        cover_path: str | None,
        install_button: AutoSizeButton,
    ) -> None:
        """Finalize auto-install detail page."""
        content_frame_layout = self._get_content_frame_layout(detail_page)
        if content_frame_layout:
            content_frame_layout.addWidget(cover_frame)
            content_frame_layout.addWidget(details_widget)

        main_layout = self._get_main_layout(detail_page)
        if main_layout:
            main_layout.addStretch()

        self._setup_autoinstall_animation(detail_page, image_label, cover_path, install_button)

    def _setup_autoinstall_animation(self, detail_page: QWidget, image_label: QLabel, cover_path: str | None, install_button: AutoSizeButton) -> None:
        """Setup animation for auto-install page."""
        self._start_detail_page_animation(
            detail_page,
            image_label,
            cover_path,
            lambda: self._setup_autoinstall_focus(detail_page, install_button),
        )

    def _start_detail_page_animation(
        self,
        detail_page: QWidget,
        image_label: QLabel,
        cover_path: str | None,
        setup_focus: Callable[[], None],
    ) -> None:
        """Start detail page animation and image loading."""
        setup_image_loading(
            detail_page,
            image_label,
            cover_path,
            self.main_window,
            image_label.width(),
            image_label.height(),
        )

        def restore_after_animation() -> None:
            if not validate_detail_page(detail_page):
                return
            if not set_opacity_safe(detail_page):
                return
            setup_focus()

        def cleanup_animation() -> None:
            if detail_page in self._animations:
                del self._animations[detail_page]

        detail_animations = DetailPageAnimations(self.main_window, self.main_window.theme)
        detail_animations.animate_detail_page(
            detail_page, restore_after_animation, cleanup_animation
        )

    def _setup_autoinstall_focus(self, detail_page: QWidget, install_button: AutoSizeButton) -> None:
        """Setup focus on install button after animation."""
        focus_helper = create_focus_helper(
            detail_page, self.main_window, install_button, self.main_window.stackedWidget
        )
        QTimer.singleShot(50, focus_helper)

    def toggleFavoriteInDetailPage(self, game_name: str, label: ClickableLabel) -> None:
        """Toggle favorite status from detail page."""
        favorite_icon_name = toggle_favorite(game_name, self.main_window)
        label.setText("")
        label.setIcon(self.main_window.theme_manager.get_icon(favorite_icon_name, as_path=True))

    def toggleDebugLog(self, exe_path: str | None, button: AutoSizeButton) -> None:
        """Toggle debug log creation."""
        if self.debug_log_manager.is_running:
            self._stop_debug_log(button)
        else:
            self._start_debug_log(exe_path, button)

    def _stop_debug_log(self, button: AutoSizeButton) -> None:
        """Stop debug logging and save log."""
        self._stopDebugTimer()
        log_file = self.debug_log_manager.stop()

        button.setText(_("Create Log"))
        icon = self.main_window.theme_manager.get_icon("edit", as_path=True)
        if icon:
            button.setIcon(icon)

        if log_file:
            self._show_log_saved_dialog(log_file)

    def _start_debug_log(self, exe_path: str | None, button: AutoSizeButton) -> None:
        """Start debug logging session."""
        if exe_path is None:
            return
        resolved_exe_path = self.main_window.resolve_launch_file_path(exe_path)
        if resolved_exe_path is None:
            return

        start_command = get_portproton_start_command()
        if not start_command:
            return

        if self.debug_log_manager.start(resolved_exe_path, start_command):
            button.setText(_("Stop Log"))
            icon = self.main_window.theme_manager.get_icon("stop", as_path=True)
            if icon:
                button.setIcon(icon)
            self._startDebugTimer()
        else:
            QMessageBox.warning(
                self.main_window,
                _("Error"),
                _("Failed to start debug session"),
            )

    def _show_log_saved_dialog(self, log_file: str) -> None:
        """Show dialog with log file location."""
        msg_box = QMessageBox(self.main_window)
        msg_box.setWindowTitle(_("Log Saved"))
        msg_box.setText(_("Debug log saved to:") + f"\n{log_file}")
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Open)
        msg_box.setButtonText(QMessageBox.StandardButton.Open, _("Open Folder"))

        result = msg_box.exec()

        if result == QMessageBox.StandardButton.Open:
            log_folder = os.path.dirname(log_file)
            try:
                QDesktopServices.openUrl(QUrl.fromLocalFile(log_folder))
            except Exception as e:
                logger.error("Failed to open folder %s: %s", log_folder, e)

    def _startDebugTimer(self) -> None:
        """Start timer to periodically read debug output."""
        if self._debug_log_timer is not None:
            self._debug_log_timer.stop()

        self._debug_log_timer = QTimer(self.main_window)
        self._debug_log_timer.timeout.connect(self._onDebugTimerTick)
        self._debug_log_timer.start(500)

    def _stopDebugTimer(self) -> None:
        """Stop debug output timer."""
        if self._debug_log_timer is not None:
            self._debug_log_timer.stop()
            self._debug_log_timer.deleteLater()
            self._debug_log_timer = None

    def _onDebugTimerTick(self) -> None:
        """Handle debug timer tick."""
        if not self.debug_log_manager.check_running():
            self._stopDebugTimer()
            log_file = self.debug_log_manager.stop()
            self._update_debug_log_button(log_file)

    def _update_debug_log_button(self, log_file: str | None) -> None:
        """Update debug log button and show dialog if log saved."""
        if self._debug_log_button:
            self._debug_log_button.setText(_("Create Log"))
            icon = self.main_window.theme_manager.get_icon("edit", as_path=True)
            if icon:
                self._debug_log_button.setIcon(icon)

        if log_file:
            logger.info("Debug session ended. Log saved to %s", log_file)
            self._show_log_saved_dialog(log_file)

    def goBackDetailPage(self, page: QWidget | None) -> None:
        """Navigate back from detail page."""
        if page is None or not self._is_valid_page(page) or self._exit_animation_in_progress:
            return

        self._exit_animation_in_progress = True
        self._detail_page_active = False
        self._current_detail_page = None

        def cleanup() -> None:
            self._cleanup_page(page)

        if page and not page.isHidden() and page.parent() is not None:
            detail_animations = DetailPageAnimations(self.main_window, self.main_window.theme)
            detail_animations.animate_detail_page_exit(page, cleanup)
        else:
            logger.warning("Detail page not valid, bypassing animation")
            self._exit_animation_in_progress = False
            cleanup()

    def _is_valid_page(self, page: QWidget) -> bool:
        """Check if page is valid and current."""
        return page == self.main_window.stackedWidget.currentWidget()

    def _cleanup_page(self, page: QWidget) -> None:
        """Clean up detail page and return to tab."""
        try:
            self._cleanup_animations(page)
            cleanup_widget_animated_covers(page)

            if not self._page_in_stacked(page):
                logger.debug("Page not found in stacked widget")
                self._finalize_cleanup()
                return

            self.main_window.detach_install_button(page)
            self.main_window.stackedWidget.removeWidget(page)
            page.deleteLater()
            return_tab_index = getattr(self, "_return_to_tab_index", 0)
            self.main_window.stackedWidget.setCurrentIndex(return_tab_index)

            self._refresh_tab_content(return_tab_index)
            self._finalize_cleanup()

        except RuntimeError:
            logger.debug("Detail page already deleted during cleanup")
            self._exit_animation_in_progress = False
        except Exception as e:
            logger.error("Unexpected error in cleanup: %s", e, exc_info=True)
            self._exit_animation_in_progress = False

    def _cleanup_animations(self, page: QWidget) -> None:
        """Clean up animations for page."""
        if not hasattr(self, "_animations") or page not in self._animations:
            return
        try:
            animation = self._animations[page]
            self._stop_animation_if_running(animation)
            del self._animations[page]
        except (KeyError, RuntimeError):
            pass

    def _stop_animation_if_running(self, animation) -> None:
        if hasattr(animation, "state") and animation.state() == 1:
            animation.stop()

    def _page_in_stacked(self, page: QWidget) -> bool:
        for i in range(self.main_window.stackedWidget.count()):
            if self.main_window.stackedWidget.widget(i) is page:
                return True
        return False

    def _refresh_tab_content(self, tab_index: int) -> None:
        if tab_index == 0 and hasattr(self.main_window, "game_library_manager"):
            if self.main_window.games:
                QTimer.singleShot(10, lambda: self.main_window.game_library_manager.update_game_grid())
            else:
                QTimer.singleShot(10, lambda: self.main_window.loadGames(force_load=True))
            QTimer.singleShot(50, self._focus_first_library_card)
        elif tab_index == 1 and hasattr(self.main_window, "autoInstallContainer"):
            QTimer.singleShot(10, lambda: self.main_window.autoInstallContainer.updateGeometry())
            if hasattr(self.main_window, "autoInstallContainerLayout"):
                QTimer.singleShot(15, lambda: self.main_window.autoInstallContainerLayout.update())
            QTimer.singleShot(50, self._focus_return_autoinstall_card)

    def _focus_return_autoinstall_card(self) -> None:
        exe_name = getattr(self, "_return_to_autoinstall_card", "")
        if not exe_name:
            return
        cards = getattr(self.main_window, "autoInstallGameCards", {})
        card = cards.get(exe_name)
        if card is None or not card.isVisible():
            return
        self._clear_current_card_state(card)
        card.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        self.main_window.current_focused_card = card
        card.update()

    def _clear_current_card_state(self, target_card: QWidget) -> None:
        current_card = getattr(self.main_window, "current_focused_card", None)
        if current_card and current_card != target_card:
            try:
                current_card._focused = False
                current_card.clearFocus()
                current_card.update()
            except RuntimeError:
                pass

    def _focus_first_library_card(self) -> None:
        container = getattr(self.main_window, "gamesListWidget", None)
        if container is None:
            return
        cards = [
            widget for widget in container.findChildren(QWidget)
            if widget.__class__.__name__ == "GameCard"
        ]
        if not cards:
            return
        cards.sort(key=lambda card: (card.pos().y(), card.pos().x()))
        cards[0].setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        scroll_area = container.parentWidget()
        while scroll_area and not isinstance(scroll_area, QScrollArea):
            scroll_area = scroll_area.parentWidget()
        if scroll_area:
            scroll_area.ensureWidgetVisible(cards[0], 50, 50)

    def _finalize_cleanup(self) -> None:
        self.main_window.currentDetailPage = None
        self.main_window.current_exec_line = None
        self.main_window.current_play_button = None
        self._exit_animation_in_progress = False
