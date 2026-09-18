"""Store account actions and shared game download manager."""

import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
import orjson
import requests
from shiboken6 import isValid

from PySide6.QtCore import QProcess, QProcessEnvironment, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from portprotonqt.dialogs.file_explorer import FileExplorer
from portprotonqt.config.cache import CacheManager
from portprotonqt.egs_api import EGSAPI, EGS_LOGIN_URL
from portprotonqt.gog_api import GOGAPI, GOG_LOGIN_URL
from portprotonqt.image_utils import load_pixmap_async, round_corners
from portprotonqt.localization import _
from portprotonqt.logger import get_logger
from portprotonqt.sound_manager import SoundManager

logger = get_logger(__name__)
GOG_CANCEL_KILL_TIMEOUT_MS = 3000
GOG_LOGIN_TIMEOUT_MS = 300000
EGS_LOGIN_TIMEOUT_MS = 300000
MIB_PER_GIB = 1024.0
STORE_INFO_TIMEOUT_SECONDS = 120
STORE_DLC_ART_TIMEOUT_SECONDS = 15
STORE_DLC_CACHE_TTL_SECONDS = 300


def _format_download_size(size_mib: float) -> str:
    if size_mib >= MIB_PER_GIB:
        return f"{size_mib / MIB_PER_GIB:.2f} GiB"
    return f"{size_mib:.1f} MiB"

if TYPE_CHECKING:
    from PySide6.QtWidgets import QMainWindow

    _MainWindowTypingBase = QMainWindow
else:
    _MainWindowTypingBase = object


class GOGLibraryWorker(QThread):
    """Refresh the GOG library outside the UI thread."""

    loaded = Signal(list)
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, api: GOGAPI) -> None:
        super().__init__()
        self.api = api

    def run(self) -> None:
        try:
            self.loaded.emit(self.api.refresh_library(self.progress.emit))
        except Exception as error:
            logger.exception("Failed to refresh GOG library")
            self.failed.emit(str(error))


class EGSLibraryWorker(QThread):
    """Refresh the Epic library outside the UI thread."""

    loaded = Signal(list)
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, api: EGSAPI) -> None:
        super().__init__()
        self.api = api

    def run(self) -> None:
        try:
            self.loaded.emit(self.api.refresh_library(self.progress.emit))
        except Exception as error:
            logger.exception("Failed to refresh Epic library")
            self.failed.emit(str(error))


class EGSAuthWorker(QThread):
    """Authenticate an Epic account outside the UI thread."""

    authenticated = Signal(bool, str)

    def __init__(self, api: EGSAPI, code: str) -> None:
        super().__init__()
        self.api = api
        self.code = code

    def run(self) -> None:
        try:
            self.authenticated.emit(*self.api.authenticate(self.code))
        except Exception as error:
            logger.exception("Failed to authenticate with Epic")
            self.authenticated.emit(False, str(error))


class GOGAuthWorker(QThread):
    """Exchange the GOG OAuth code outside the UI thread."""

    authenticated = Signal(bool, str)

    def __init__(self, api: GOGAPI, code: str) -> None:
        super().__init__()
        self.api = api
        self.code = code

    def run(self) -> None:
        try:
            authenticated, error = self.api.authenticate(self.code)
            self.authenticated.emit(authenticated, error)
        except Exception as error:
            logger.exception("Failed to authenticate with GOG: %s", error)
            self.authenticated.emit(False, str(error))


class GOGAccountWorker(QThread):
    """Load the GOG account name outside the UI thread."""

    loaded = Signal(str)

    def __init__(self, api: GOGAPI) -> None:
        super().__init__()
        self.api = api

    def run(self) -> None:
        try:
            self.loaded.emit(self.api.refresh_account_name())
        except Exception:
            logger.exception("Failed to refresh GOG account name")
            self.loaded.emit("")


class GOGSupportWorker(QThread):
    """Install GOG support instructions outside the UI thread."""

    failed = Signal(str)
    launched = Signal(object)
    succeeded = Signal()

    def __init__(self, api: GOGAPI, app_id: str, start_command: list[str]) -> None:
        super().__init__()
        self.api = api
        self.app_id = app_id
        self.start_command = start_command
        self.error = ""

    def run(self) -> None:
        try:
            self.api.install_support(
                self.app_id, self.start_command, self.launched.emit
            )
            self.succeeded.emit()
        except (OSError, subprocess.SubprocessError) as error:
            logger.exception("Failed to install GOG support for %s", self.app_id)
            self.error = str(error)
            self.failed.emit(self.error)


class GOGRepairWorker(QThread):
    """Restore an imported game's manifest outside the UI thread."""

    def __init__(self, api: GOGAPI, game: dict) -> None:
        super().__init__()
        self.api = api
        self.game = game
        self.error = ""

    def run(self) -> None:
        try:
            app_id = str(self.game["app_id"])
            install_path = self.api.get_installed_path(app_id)
            if install_path is None:
                raise OSError(f"GOG installation not found: {app_id}")
            self.api.prepare_repair_manifest(app_id, install_path)
        except Exception as error:
            logger.exception("Failed to prepare GOG repair")
            self.error = str(error)


class StoreDLCWorker(QThread):
    """Read owned, installable store DLC outside the UI thread."""

    loaded = Signal(list)
    failed = Signal(str)

    def __init__(self, api: GOGAPI | EGSAPI, app_id: str) -> None:
        super().__init__()
        self.api = api
        self.app_id = app_id

    def run(self) -> None:
        try:
            epic = isinstance(self.api, EGSAPI)
            arguments = ["info", self.app_id, "--platform", "Windows" if epic else "windows"]
            if epic:
                arguments.append("--json")
            environment = os.environ.copy()
            environment["LEGENDARY_CONFIG_PATH" if epic else "GOGDL_CONFIG_PATH"] = str(self.api.config_dir)
            cache = CacheManager()
            cache_name = f"store-dlc-{'egs' if epic else 'gog'}-{self.app_id}"
            data = self._load_epic_dlc_info() if epic else cache.load_json(cache_name) if cache.is_fresh(cache_name, STORE_DLC_CACHE_TTL_SECONDS) else None
            if data is None:
                result = subprocess.run(
                    self.api.build_command(arguments), env=environment, capture_output=True,
                    timeout=STORE_INFO_TIMEOUT_SECONDS, check=True,
                )
                data = orjson.loads(result.stdout)
                cache.save_json(cache_name, data)
            entries = data.get("game", {}).get("owned_dlc", []) if epic else data.get("dlcs", [])
            installed = set(self.api.load_installed()) if epic else set()
            if isinstance(self.api, GOGAPI):
                install_path = self.api.get_installed_path(self.app_id)
                if install_path is not None:
                    installed = {path.stem.removeprefix("goggame-") for path in install_path.glob("goggame-*.info")}
                    installed.discard(self.app_id)
                    self.api.prepare_repair_manifest(self.app_id, install_path)
            dlcs = []
            for entry in entries:
                if epic and not any("Windows" in release.get("platform", []) for release in entry.get("installable", [])):
                    continue
                app_id = str(entry.get("app_name" if epic else "id", ""))
                if not app_id or app_id.startswith("-") or (not epic and not app_id.isdecimal()):
                    continue
                dlcs.append({"app_id": app_id, "title": str(entry.get("title") or app_id), "installed": app_id in installed})
            if not epic:
                known = {dlc["app_id"] for dlc in dlcs}
                dlcs.extend({"app_id": app_id, "title": app_id, "installed": True} for app_id in sorted(installed - known))
            covers = self._load_dlc_covers() if dlcs else {}
            for dlc in dlcs:
                if covers.get(dlc["app_id"]):
                    dlc["cover"] = covers[dlc["app_id"]]
            if not self.isInterruptionRequested():
                self.loaded.emit(dlcs)
        except Exception as error:
            logger.exception("Failed to load store DLC for %s", self.app_id)
            if not self.isInterruptionRequested():
                self.failed.emit(str(error))

    def _load_epic_dlc_info(self) -> dict | None:
        assets = self.api._load_json(self.api.config_dir / "assets.json", None)
        data = self.api._load_json(self.api.config_dir / "metadata" / f"{self.app_id}.json", None)
        if not isinstance(assets, dict) or not isinstance(data, dict):
            return None
        owned = {asset.get("app_name") or asset.get("appName") for asset in assets.get("Windows", [])}
        dlcs = []
        for entry in data.get("metadata", {}).get("dlcItemList", []):
            for release in entry.get("releaseInfo", []):
                app_id = release.get("appId")
                if app_id in owned and "Windows" in release.get("platform", []):
                    dlcs.append({"app_name": app_id, "title": entry.get("title", app_id), "installable": [release]})
                    owned.remove(app_id)
        return {"game": {"owned_dlc": dlcs}}

    def _load_dlc_covers(self) -> dict[str, str]:
        if isinstance(self.api, EGSAPI):
            data = self.api._load_json(self.api.config_dir / "metadata" / f"{self.app_id}.json", {})
            covers = {}
            for entry in data.get("metadata", {}).get("dlcItemList", []):
                images = entry.get("keyImages", [])
                cover = next((image.get("url", "") for image in images
                              if image.get("type") in {"DieselGameBox", "OfferImageWide", "Thumbnail"}), "")
                cover = cover or next((image.get("url", "") for image in images), "")
                for release in entry.get("releaseInfo", []):
                    if release.get("appId"):
                        covers[str(release["appId"])] = str(cover)
            return covers
        cache = CacheManager()
        cache_name = f"store-dlc-art-gog-{self.app_id}"
        data = cache.load_json(cache_name)
        if data is None:
            try:
                response = requests.get(
                    f"https://api.gog.com/products/{self.app_id}?expand=expanded_dlcs",
                    timeout=STORE_DLC_ART_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                data = response.json()
                cache.save_json(cache_name, data)
            except requests.RequestException as error:
                logger.warning("Failed to load GOG DLC covers: %s", error)
                return {}
        covers = {}
        for entry in data.get("expanded_dlcs", []):
            images = entry.get("images", {})
            cover = images.get("logo2x") or images.get("logo") or images.get("icon") or ""
            covers[str(entry.get("id", ""))] = f"https:{cover}" if cover.startswith("//") else cover
        return covers


class MainWindowDownloadTabMixin(_MainWindowTypingBase):
    """Add account actions and the shared downloads page."""

    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...

    def createGOGDownloadsTab(self) -> None:
        self.gog_process = None
        self.egs_process = None
        self.gog_repair_worker = None
        self.egs_install_importing = False
        self.gog_download_queue = []
        self.gog_download_output = ""
        self.egs_download_output = ""
        self.egs_download_total = 0.0
        self.gog_support_workers = []
        self.downloadTableHeadings = {}
        page = QWidget()
        page.setProperty("theme_style_name", "OTHER_PAGES_WIDGET_STYLE")
        page.setStyleSheet(self.theme.OTHER_PAGES_WIDGET_STYLE)
        layout = QVBoxLayout(page)
        layout.setSpacing(self.theme.downloadsSectionSpacing)
        title = QLabel(_("Downloads"))
        title.setStyleSheet(self.theme.TAB_TITLE_STYLE)
        layout.addWidget(title)
        self._create_active_download_card(layout)
        self.downloadQueuedTable = self._create_download_table(_("Queued"), layout)
        completed_header = QHBoxLayout()
        completed_header.addWidget(QLabel(_("Completed")))
        clear_button = QPushButton(_("Clear List"))
        clear_button.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
        clear_button.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        clear_button.clicked.connect(self._clear_completed_downloads)
        completed_header.addWidget(clear_button)
        completed_header.addStretch()
        layout.addLayout(completed_header)
        self.downloadCompletedTable = self._create_download_table("", layout)
        layout.addStretch()
        self.stackedWidget.addWidget(page)
        self._update_downloads_tab_visibility()

    def _update_downloads_tab_visibility(self) -> None:
        has_downloads = (
            not self.downloadActiveCard.isHidden()
            or self.downloadQueuedTable.rowCount() > 0
            or self.downloadCompletedTable.rowCount() > 0
        )
        self.tabButtons[6].setVisible(has_downloads)
        if not has_downloads and self.stackedWidget.currentIndex() == 6:
            self.switchTab(0)

    def _create_active_download_card(self, layout: QVBoxLayout) -> None:
        self.downloadActiveHeading = QLabel(_("Now Downloading"))
        self.downloadActiveHeading.setStyleSheet(self.theme.SETTINGS_TITLE_STYLE)
        layout.addWidget(self.downloadActiveHeading)
        self.downloadActiveCard = QFrame()
        self.downloadActiveCard.setObjectName("downloadsActiveCard")
        self.downloadActiveCard.setStyleSheet(self.theme.DOWNLOADS_ACTIVE_STYLE)
        self.downloadActiveCard.setFixedHeight(self.theme.downloadsActiveCardHeight)
        card_layout = QVBoxLayout(self.downloadActiveCard)
        card_layout.setContentsMargins(*self.theme.downloadsActiveCardMargins)
        card_layout.setSpacing(self.theme.downloadsActiveCardSpacing)
        content = QHBoxLayout()
        content.setSpacing(self.theme.downloadsActiveCardSpacing)
        self.downloadActiveCover = QLabel()
        self.downloadActiveCover.setFixedSize(*self.theme.downloadsActiveCoverSize)
        content.addWidget(self.downloadActiveCover)
        info = QVBoxLayout()
        header = QHBoxLayout()
        self.downloadActiveTitle = QLabel()
        self.downloadActiveTitle.setStyleSheet(self.theme.SETTINGS_TITLE_STYLE)
        header.addWidget(self.downloadActiveTitle)
        header.addStretch()
        self.downloadCancelButton = QPushButton(_("Cancel"))
        self.downloadCancelButton.setProperty("theme_style_name", "ACTION_BUTTON_STYLE")
        self.downloadCancelButton.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
        self.downloadCancelButton.clicked.connect(self._cancel_gog_download)
        header.addWidget(self.downloadCancelButton)
        info.addLayout(header)
        self.downloadActiveDetails = QLabel(_("Waiting…"))
        self.downloadActiveDetails.setStyleSheet(self.theme.CONTENT_STYLE)
        info.addWidget(self.downloadActiveDetails)
        metrics = QHBoxLayout()
        self.downloadSpeedLabel = QLabel(_("Downloading: ") + "\u2014")
        self.diskSpeedLabel = QLabel(_("Disk: ") + "\u2014")
        metrics.addWidget(self.downloadSpeedLabel)
        metrics.addWidget(self.diskSpeedLabel)
        metrics.addStretch()
        info.addLayout(metrics)
        content.addLayout(info, stretch=1)
        card_layout.addLayout(content)
        self.downloadOverallProgress = QProgressBar()
        self.downloadOverallProgress.setStyleSheet(self.theme.PROGRESS_BAR_STYLE)
        card_layout.addWidget(self.downloadOverallProgress)
        layout.addWidget(self.downloadActiveCard)
        self.downloadActiveHeading.setVisible(False)
        self.downloadActiveCard.setVisible(False)

    def _create_download_table(self, heading: str, layout: QVBoxLayout) -> QTableWidget:
        label = None
        if heading:
            label = QLabel(heading)
            label.setStyleSheet(self.theme.SETTINGS_TITLE_STYLE)
            layout.addWidget(label)
        columns = (_("Game Title"), _("Started at"), _("Type"), _("Store"))
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setStyleSheet(self.theme.DOWNLOADS_TABLE_STYLE)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setShowGrid(False)
        header = table.horizontalHeader()
        header.setFixedHeight(self.theme.downloadsTableHeaderHeight)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, len(columns)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setVisible(False)
        self._update_download_table_height(table)
        layout.addWidget(table)
        if label is not None:
            self.downloadTableHeadings[table] = label
            label.setVisible(False)
        table.setVisible(False)
        return table

    def _update_download_table_height(self, table: QTableWidget) -> None:
        rows = max(1, table.rowCount())
        height = self.theme.downloadsTableHeaderHeight + rows * self.theme.downloadsTableRowHeight
        table.setFixedHeight(height)
        has_rows = table.rowCount() > 0
        table.setVisible(has_rows)
        heading = self.downloadTableHeadings.get(table)
        if heading is not None:
            heading.setVisible(has_rows)

    def _clear_completed_downloads(self) -> None:
        self.downloadCompletedTable.setRowCount(0)
        self._update_download_table_height(self.downloadCompletedTable)
        self._update_downloads_tab_visibility()

    def _start_gog_login(self) -> None:
        if getattr(self, "gog_auth_worker", None) is not None:
            return
        clipboard = QApplication.clipboard()
        if not getattr(self, "gog_auth_clipboard_connected", False):
            clipboard.dataChanged.connect(self._check_gog_login_clipboard)
            self.gog_auth_clipboard_connected = True
        self.gog_auth_timer = QTimer(self)
        self.gog_auth_timer.setSingleShot(True)
        self.gog_auth_timer.timeout.connect(self._cancel_gog_login)
        self.gog_auth_timer.start(GOG_LOGIN_TIMEOUT_MS)
        self.gogLoginButton.setEnabled(False)
        self.gogAccountStatus.setText(_("Copy the link to clipboard"))
        if not QDesktopServices.openUrl(QUrl(GOG_LOGIN_URL)):
            self._stop_gog_login_clipboard()
            self.gogLoginButton.setEnabled(True)
            self._update_gog_account_state()

    def _handle_gog_account_action(self) -> None:
        if not self.gog_api.auth_path.is_file():
            self._start_gog_login()
            return
        if not self.gog_api.logout():
            self.gogAccountStatus.setText(_("Failed to log out of GOG account"))
            return
        self._update_gog_account_state()
        self.loadGames(force_load=True)

    def _check_gog_login_clipboard(self) -> None:
        code = self.gog_api.extract_auth_code(QApplication.clipboard().text().strip())
        if not code:
            return
        self._stop_gog_login_clipboard()
        self.gogAccountStatus.setText(_("Refreshing…"))
        worker = GOGAuthWorker(self.gog_api, code)
        worker.authenticated.connect(self._on_gog_authenticated)
        worker.finished.connect(self._on_gog_auth_worker_finished)
        self.gog_auth_worker = worker
        worker.start()

    def _stop_gog_login_clipboard(self) -> None:
        timer = getattr(self, "gog_auth_timer", None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
            self.gog_auth_timer = None
        if not getattr(self, "gog_auth_clipboard_connected", False):
            return
        QApplication.clipboard().dataChanged.disconnect(
            self._check_gog_login_clipboard
        )
        self.gog_auth_clipboard_connected = False

    def _cancel_gog_login(self) -> None:
        self._stop_gog_login_clipboard()
        self.gogLoginButton.setEnabled(True)
        self._update_gog_account_state()

    def _on_gog_authenticated(self, authenticated: bool, error: str) -> None:
        if not authenticated:
            message = error or _("Unknown error")
            self.gogAccountStatus.setText(_("GOG login failed: {0}").format(message))
            return
        account_name = self.gog_api.get_account_name()
        self.gogAccountStatus.setText(
            account_name or _("GOG account connected")
        )
        self.loadGames(force_load=True)
        self._refresh_gog_library()

    def _on_gog_auth_worker_finished(self) -> None:
        self.gogLoginButton.setEnabled(True)
        button_text = (
            _("Log out")
            if self.gog_api.auth_path.is_file() else _("Open login page")
        )
        self.gogLoginButton.setText(button_text)
        self.gog_auth_worker = None

    def _update_gog_account_state(self) -> None:
        connected = self.gog_api.auth_path.is_file()
        account_name = self.gog_api.get_account_name() if connected else ""
        status = (
            account_name or _("GOG account connected")
            if connected else _("GOG account not connected")
        )
        self.gogAccountStatus.setText(status)
        self.gogLoginButton.setEnabled(True)
        self.gogLoginButton.setText(
            _("Log out") if connected else _("Open login page")
        )
        if connected and not account_name:
            self._refresh_gog_account_name()

    def _refresh_gog_account_name(self) -> None:
        if getattr(self, "gog_account_worker", None) is not None:
            return
        worker = GOGAccountWorker(self.gog_api)
        worker.loaded.connect(self._on_gog_account_name_loaded)
        worker.finished.connect(self._on_gog_account_worker_finished)
        self.gog_account_worker = worker
        worker.start()

    def _on_gog_account_name_loaded(self, account_name: str) -> None:
        if account_name:
            self.gogAccountStatus.setText(account_name)

    def _on_gog_account_worker_finished(self) -> None:
        self.gog_account_worker = None

    def _refresh_gog_library(self) -> None:
        if not self.gog_api.auth_path.is_file():
            return
        if getattr(self, "gog_library_worker", None) is not None:
            return
        self.gogAccountStatus.setText(_("Refreshing…"))
        worker = GOGLibraryWorker(self.gog_api)
        worker.loaded.connect(self._on_gog_library_loaded)
        worker.failed.connect(self._on_gog_library_failed)
        worker.progress.connect(self._on_gog_library_progress)
        worker.finished.connect(self._on_gog_library_worker_finished)
        self.gog_library_worker = worker
        worker.start()

    def _on_gog_library_progress(self, completed: int, total: int) -> None:
        self.gogAccountStatus.setText(
            _("Refreshing GOG library… {0}/{1}").format(completed, total)
        )

    def _on_gog_library_loaded(self, _games: list) -> None:
        self._update_gog_account_state()
        self.loadGames(force_load=True)

    def _on_gog_library_failed(self, message: str) -> None:
        self.gogAccountStatus.setText(_("Failed to refresh GOG library: {0}").format(message))
        self.loadGames(force_load=True)

    def _on_gog_library_worker_finished(self) -> None:
        self.gog_library_worker = None

    def _handle_egs_account_action(self) -> None:
        if not self.egs_api.user_path.is_file():
            self._start_egs_login()
            return
        if not self.egs_api.logout():
            self.egsAccountStatus.setText(_("Failed to log out of Epic account"))
            return
        self._update_egs_account_state()
        self.loadGames(force_load=True)

    def _start_egs_login(self) -> None:
        if getattr(self, "egs_auth_worker", None) is not None:
            return
        clipboard = QApplication.clipboard()
        if not getattr(self, "egs_auth_clipboard_connected", False):
            clipboard.dataChanged.connect(self._check_egs_login_clipboard)
            self.egs_auth_clipboard_connected = True
        self.egs_auth_timer = QTimer(self)
        self.egs_auth_timer.setSingleShot(True)
        self.egs_auth_timer.timeout.connect(self._cancel_egs_login)
        self.egs_auth_timer.start(EGS_LOGIN_TIMEOUT_MS)
        self.egsLoginButton.setEnabled(False)
        self.egsAccountStatus.setText(_("Copy the authorization code to clipboard"))
        if not QDesktopServices.openUrl(QUrl(EGS_LOGIN_URL)):
            self._cancel_egs_login()

    def _check_egs_login_clipboard(self) -> None:
        code = self.egs_api.extract_auth_code(QApplication.clipboard().text())
        if len(code) < 16:
            return
        self._stop_egs_login_clipboard()
        self.egsAccountStatus.setText(_("Epic authorization…"))
        worker = EGSAuthWorker(self.egs_api, code)
        worker.authenticated.connect(self._on_egs_authenticated)
        worker.finished.connect(self._on_egs_auth_worker_finished)
        self.egs_auth_worker = worker
        worker.start()

    def _stop_egs_login_clipboard(self) -> None:
        timer = getattr(self, "egs_auth_timer", None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
            self.egs_auth_timer = None
        if getattr(self, "egs_auth_clipboard_connected", False):
            QApplication.clipboard().dataChanged.disconnect(
                self._check_egs_login_clipboard
            )
            self.egs_auth_clipboard_connected = False

    def _cancel_egs_login(self) -> None:
        self._stop_egs_login_clipboard()
        self.egsLoginButton.setEnabled(True)
        self._update_egs_account_state()

    def _on_egs_authenticated(self, authenticated: bool, error: str) -> None:
        if not authenticated:
            self.egsAccountStatus.setText(
                _("Epic login failed: {0}").format(error or _("Unknown error"))
            )
            return
        self._refresh_egs_library()

    def _on_egs_auth_worker_finished(self) -> None:
        self.egsLoginButton.setEnabled(True)
        self.egs_auth_worker = None

    def _update_egs_account_state(self) -> None:
        connected = self.egs_api.user_path.is_file()
        account_name = self.egs_api.get_account_name() if connected else ""
        self.egsAccountStatus.setText(
            account_name or (_("Epic account connected") if connected
                             else _("Epic account not connected"))
        )
        self.egsLoginButton.setText(_("Log out") if connected else _("Open login page"))
        self.egsLoginButton.setEnabled(True)

    def _refresh_egs_library(self) -> None:
        if not self.egs_api.user_path.is_file():
            return
        if getattr(self, "egs_library_worker", None) is not None:
            return
        worker = EGSLibraryWorker(self.egs_api)
        worker.loaded.connect(self._on_egs_library_loaded)
        worker.failed.connect(self._on_egs_library_failed)
        worker.progress.connect(self._on_egs_library_progress)
        worker.finished.connect(self._on_egs_library_worker_finished)
        self.egs_library_worker = worker
        worker.start()

    def _on_egs_library_progress(self, completed: int, total: int) -> None:
        self.egsAccountStatus.setText(
            _("Refreshing Epic library… {0}/{1}").format(completed, total)
        )

    def _on_egs_library_loaded(self, games: list) -> None:
        self._update_egs_account_state()
        manager = self.detail_page_manager
        source = manager._current_detail_source
        if source and source[0] == "game":
            source_data = source[1]
            if str(source_data.get("game_source", "")).lower() == "egs":
                app_id = str(source_data.get("appid", ""))
                game = next(
                    (item for item in games if str(item.get("app_id", "")) == app_id),
                    None,
                )
                if game:
                    source_data["description"] = str(game.get("description", ""))
                    source_data["cover_path"] = str(game.get("cover", ""))
                    if manager._detail_page_active:
                        manager._reopen_current_detail_page()
        self.loadGames(force_load=True)

    def _on_egs_library_failed(self, error: str) -> None:
        self.egsAccountStatus.setText(
            _("Failed to refresh Epic library: {0}").format(error)
        )

    def _on_egs_library_worker_finished(self) -> None:
        self.egs_library_worker = None

    def _install_gog_game(self, game: dict) -> None:
        if getattr(self, "gog_repair_worker", None) is not None:
            return
        if self.gog_process is not None:
            self.gog_download_queue.append(game)
            self._append_download_row(self.downloadQueuedTable, game, _("Install"))
            self.switchTab(6)
            return
        app_id = str(game["app_id"])
        install_path = self.gog_api.get_install_path(app_id, str(game["title"]))
        install_path.mkdir(parents=True, exist_ok=True)
        selected_paths: list[str] = []
        file_explorer = FileExplorer(
            self,
            theme=self.theme,
            initial_path=str(install_path),
            directory_only=True,
        )
        file_explorer.setWindowTitle(_("Select installation folder"))
        file_explorer.file_signal.file_selected.connect(selected_paths.append)
        file_explorer.exec()
        if not selected_paths:
            return
        install_path = Path(selected_paths[0])
        game_path = self.gog_api.find_install_path(app_id, install_path)
        if game_path is not None:
            self.gog_api.save_installed_game(
                app_id, {"install_path": str(game_path), "title": str(game["title"])}
            )
            self._repair_gog_game(game)
            return
        manifest_path = (
            self.gog_api.config_dir / "heroic_gogdl" / "manifests" / app_id
        )
        if manifest_path.is_file() and not self.gog_api.is_game_installed(app_id):
            try:
                manifest_path.unlink()
            except OSError as error:
                logger.error("Failed to reset incomplete GOG download: %s", error)
                self.gogAccountStatus.setText(str(error))
                return
        support_path = (
            self.gog_api.config_dir / "heroic_gogdl" / "gog-support" / app_id
        )
        try:
            command = self.gog_api.build_command(
                [
                    "download", app_id, "--path", str(install_path),
                    "--support", str(support_path), "--platform", "windows",
                    *(["--with-dlcs", "--dlcs", ",".join(dlc["app_id"] for dlc in game["_dlcs"])]
                      if game.get("_dlcs") else ["--skip-dlcs"] if "_dlcs" in game else []),
                ]
            )
        except FileNotFoundError as error:
            self.gogAccountStatus.setText(str(error))
            return
        self._start_gog_download(game, install_path, command, _("Install"))

    def _select_store_dlcs(self, source: str, game: dict) -> None:
        if (getattr(self, "store_dlc_worker", None) is not None
                or self.gog_process is not None or self.egs_process is not None):
            QMessageBox.warning(self, _("Error"), _("Another download is running"))
            return
        api = self.egs_api if source == "egs" else self.gog_api
        worker = StoreDLCWorker(api, str(game["app_id"]))
        worker.loaded.connect(lambda dlcs: self._on_store_dlcs_loaded(source, game, dlcs))
        worker.failed.connect(lambda error: QMessageBox.warning(self, _("Error"), error))
        worker.finished.connect(self._on_store_dlc_worker_finished)
        self.store_dlc_worker = worker
        worker.start()

    def _on_store_dlc_worker_finished(self) -> None:
        worker = self.store_dlc_worker
        self.store_dlc_worker = None
        if worker is not None:
            worker.deleteLater()

    def _on_store_dlcs_loaded(self, source: str, game: dict, dlcs: list[dict]) -> None:
        selected = []
        if dlcs:
            dialog = QDialog(self)
            dialog.setWindowTitle(f"{game['title']} — DLC")
            dialog.setMinimumWidth(self.theme.storeDlcDialogWidth)
            dialog.setStyleSheet(self.theme.MESSAGE_BOX_STYLE)
            layout = QVBoxLayout(dialog)
            scroll = QScrollArea(dialog)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidgetResizable(True)
            scroll.setMinimumHeight(min(len(dlcs), self.theme.storeDlcVisibleRows) * self.theme.storeDlcRowHeight)
            content = QWidget()
            content.setObjectName("storeDlcList")
            content.setStyleSheet(self.theme.STORE_DLC_LIST_STYLE)
            rows = QVBoxLayout(content)
            checkboxes = []
            for dlc in dlcs:
                row, checkbox = self._create_store_dlc_row(dlc, str(game.get("cover", "")))
                rows.addWidget(row)
                checkboxes.append((checkbox, dlc))
            scroll.setWidget(content)
            scroll.setStyleSheet(self.theme.SCROLL_STYLE)
            layout.addWidget(scroll)
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )
            buttons.button(QDialogButtonBox.StandardButton.Ok).setText(_("Install"))
            buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(_("Cancel"))
            buttons.setStyleSheet(self.theme.ACTION_BUTTON_STYLE)
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            result = dialog.exec()
            dialog.deleteLater()
            if result != QDialog.DialogCode.Accepted:
                return
            selected = [dlc for checkbox, dlc in checkboxes if checkbox.isChecked() and (source == "gog" or not dlc.get("installed"))]
        game = {**game, "_dlcs": selected}
        if source == "gog":
            self._install_gog_game(game)
        else:
            self.egs_selected_dlc_game = game
            self._install_egs_download(str(game["app_id"]))

    def _create_store_dlc_row(self, dlc: dict, fallback_cover: str) -> tuple[QWidget, QCheckBox]:
        row, details = self._create_download_game_cell({**dlc, "cover": dlc.get("cover") or fallback_cover})
        details.hide()
        row.setObjectName("storeDlcRow")
        row.setStyleSheet(self.theme.STORE_DLC_ROW_STYLE)
        row.setMinimumHeight(self.theme.storeDlcRowHeight)
        cover = row.findChild(QLabel, "downloadGameCover")
        if cover is not None:
            cover.setFixedSize(*self.theme.storeDlcCoverSize)
            cover.setScaledContents(True)
        title = row.findChild(QLabel, "downloadGameTitle")
        if title is not None:
            title.setWordWrap(True)
        checkbox = QCheckBox()
        checkbox.setAccessibleName(dlc["title"])
        checkbox.setStyleSheet(self.theme.CHECKBOX_STYLE)
        checkbox.setFixedWidth(checkbox.sizeHint().width())
        checkbox.setChecked(bool(dlc.get("installed")))
        checkbox.setEnabled(not dlc.get("installed", False))
        layout = row.layout()
        assert layout is not None
        layout.addWidget(checkbox)
        return row, checkbox

    def _start_next_egs_dlc(self, game: dict, install_path: Path) -> None:
        dlc = game["_dlcs"][0]
        command = self.egs_api.build_command([
            "install", dlc["app_id"], "--base-path", str(install_path.parent),
            "--game-folder", install_path.name, "--platform", "Windows",
            "--skip-sdl", "--skip-dlcs", "-y",
        ])
        game = {**game, "_dlcs": game["_dlcs"][1:]}
        self._start_egs_download(game, install_path, command)

    def _install_egs_download(self, app_id: str) -> None:
        if self.gog_process is not None or self.egs_process is not None:
            QMessageBox.warning(self, _("Error"), _("Another download is running"))
            return
        game = next(
            (item for item in self.egs_api.load_library()
             if str(item.get("app_id", "")) == app_id),
            {"app_id": app_id, "title": app_id, "cover": ""},
        )
        selected_game = getattr(self, "egs_selected_dlc_game", None)
        if selected_game is not None and str(selected_game["app_id"]) == app_id:
            game = selected_game
            self.egs_selected_dlc_game = None
        selected_paths: list[str] = []
        explorer = FileExplorer(
            self, theme=self.theme, initial_path=str(self.egs_api.games_dir),
            directory_only=True,
        )
        explorer.setWindowTitle(_("Select installation folder"))
        explorer.file_signal.file_selected.connect(selected_paths.append)
        explorer.exec()
        if not selected_paths:
            return
        install_path = Path(selected_paths[0])
        folder_name = Path(str(game.get("folder_name") or app_id)).name
        try:
            game_path = install_path
            child_path = install_path / folder_name
            if child_path.is_dir() and not any(path.is_file() for path in install_path.iterdir()):
                game_path = child_path
            existing_game = game_path.is_dir() and any(game_path.iterdir())
            arguments = [
                "install", app_id, "--base-path", str(install_path),
                "--platform", "Windows", "--skip-sdl", "--skip-dlcs", "-y",
            ]
            if existing_game:
                arguments = [
                    "import", app_id, str(game_path), "--platform", "Windows",
                    "--skip-dlcs", "--disable-check", "-y",
                ]
                installed = self.egs_api.load_installed()
                if app_id in installed:
                    if installed[app_id].get("install_path") != str(game_path):
                        installed[app_id]["install_path"] = str(game_path)
                        self.egs_api._save_json(self.egs_api.config_dir / "installed.json", installed)
                    arguments = [
                        "repair", app_id, "--repair-and-update", "--skip-sdl", "-y",
                    ]
            command = self.egs_api.build_command(arguments)
        except OSError as error:
            self.egsAccountStatus.setText(str(error))
            return
        self.egs_install_importing = arguments[0] == "import"
        self._start_egs_download(game, install_path, command)

    def _repair_gog_game(self, game: dict) -> None:
        if self.gog_process is not None or getattr(self, "gog_repair_worker", None) is not None:
            self.gogAccountStatus.setText(_("Another GOG operation is already running"))
            return
        app_id = str(game["app_id"])
        install_path = self.gog_api.get_installed_path(app_id)
        if install_path is None:
            self.gogAccountStatus.setText(_("GOG installation not found"))
            return
        manifest_path = self.gog_api.config_dir / "heroic_gogdl" / "manifests" / app_id
        if not manifest_path.is_file():
            worker = GOGRepairWorker(self.gog_api, game)
            worker.finished.connect(self._on_gog_repair_prepared)
            self.gog_repair_worker = worker
            worker.start()
            return
        support_path = (
            self.gog_api.config_dir / "heroic_gogdl" / "gog-support" / app_id
        )
        if "_dlcs" in game:
            selected = {dlc["app_id"] for dlc in game["_dlcs"]}
            selected.update(path.stem.removeprefix("goggame-") for path in install_path.glob("goggame-*.info"))
            selected.discard(app_id)
            game = {**game, "_dlcs": [{"app_id": dlc_id} for dlc_id in sorted(selected)]}
        try:
            command = self.gog_api.build_command(
                [
                    "repair", app_id, "--path", str(install_path),
                    "--support", str(support_path), "--platform", "windows",
                    *(["--with-dlcs", "--dlcs", ",".join(dlc["app_id"] for dlc in game["_dlcs"])]
                      if game.get("_dlcs") else ["--skip-dlcs"] if "_dlcs" in game else []),
                ]
            )
        except FileNotFoundError as error:
            self.gogAccountStatus.setText(str(error))
            return
        self._start_gog_download(game, install_path, command, _("Repair"))

    def _on_gog_repair_prepared(self) -> None:
        worker = self.gog_repair_worker
        self.gog_repair_worker = None
        if worker is None or worker.isInterruptionRequested():
            return
        if worker.error:
            self.gogAccountStatus.setText(worker.error)
            return
        self._repair_gog_game(worker.game)

    def _import_gog_game(self, game: dict) -> None:
        selected_paths: list[str] = []
        file_explorer = FileExplorer(
            self, theme=self.theme, initial_path=str(Path.home() / "Games"),
            directory_only=True,
        )
        file_explorer.setWindowTitle(_("Select GOG game folder"))
        file_explorer.file_signal.file_selected.connect(selected_paths.append)
        file_explorer.exec()
        if not selected_paths:
            return
        app_id = str(game["app_id"])
        game_path = self.gog_api.find_install_path(app_id, Path(selected_paths[0]))
        if game_path is None:
            self.gogAccountStatus.setText(_("Selected folder is not this GOG game"))
            return
        self.gog_api.save_installed_game(
            app_id, {"install_path": str(game_path), "title": str(game["title"])}
        )
        self.gog_api.ensure_launch_parameters(app_id)
        self.loadGames(force_load=True)

    def _delete_gog_game(self, game: dict) -> None:
        app_id = str(game["app_id"])
        install_path = self.gog_api.get_installed_path(app_id)
        if install_path is None:
            self.gogAccountStatus.setText(_("GOG installation not found"))
            return
        message_box = QMessageBox(self)
        message_box.setIcon(QMessageBox.Icon.Question)
        message_box.setWindowTitle(_("Confirm Deletion"))
        message_box.setText(
            _("Delete '{0}' and all files in its installation folder?").format(
                game["title"]
            )
        )
        message_box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        message_box.setDefaultButton(QMessageBox.StandardButton.No)
        message_box.setButtonText(QMessageBox.StandardButton.Yes, _("Yes"))
        message_box.setButtonText(QMessageBox.StandardButton.No, _("No"))
        if message_box.exec() != QMessageBox.StandardButton.Yes:
            return
        try:
            shutil.rmtree(install_path)
        except OSError as error:
            logger.error("Failed to delete GOG game %s: %s", app_id, error)
            self.gogAccountStatus.setText(str(error))
            return
        manifest_path = (
            self.gog_api.config_dir / "heroic_gogdl" / "manifests" / app_id
        )
        try:
            manifest_path.unlink(missing_ok=True)
        except OSError as error:
            logger.warning("Failed to delete GOG manifest %s: %s", app_id, error)
        self.gog_api.remove_installed_game(app_id)
        self.context_menu_manager.remove_gog_shortcuts(str(game["title"]))
        self.loadGames(force_load=True)

    def _start_gog_download(
        self, game: dict, install_path: Path, command: list[str], action: str
    ) -> None:
        app_id = str(game["app_id"])
        self.downloadActiveTitle.setText(str(game["title"]))
        self.downloadActiveDetails.setText(_("Starting"))
        cover_width, cover_height = self.theme.downloadsActiveCoverSize
        load_pixmap_async(
            str(game.get("cover", "")), cover_width, cover_height,
            self.downloadActiveCover.setPixmap,
            app_name=f"download-active-{app_id}",
        )
        self.downloadActiveHeading.setVisible(True)
        self.downloadActiveCard.setVisible(True)
        self._update_downloads_tab_visibility()
        process = QProcess(self)
        process.setProgram(command[0])
        process.setArguments(command[1:])
        process.setProcessEnvironment(self._gog_process_environment())
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._read_gog_download_output)
        process.finished.connect(self._on_gog_download_finished)
        self.gog_process = process
        self.gog_active_app_id = app_id
        self.gog_active_game = game
        self.gog_active_install_path = install_path
        self.gog_active_action = action
        self.gog_download_output = ""
        self.downloadOverallProgress.setValue(0)
        self.downloadCancelButton.setEnabled(True)
        self.switchTab(6)
        process.start()

    def _start_egs_download(
        self, game: dict, install_path: Path, command: list[str]
    ) -> None:
        app_id = str(game["app_id"])
        self.downloadActiveTitle.setText(str(game["title"]))
        self.downloadActiveDetails.setText(_("Starting"))
        cover_width, cover_height = self.theme.downloadsActiveCoverSize
        load_pixmap_async(
            str(game.get("cover", "")), cover_width, cover_height,
            self.downloadActiveCover.setPixmap,
            app_name=f"download-active-{app_id}",
        )
        self.downloadActiveHeading.setVisible(True)
        self.downloadActiveCard.setVisible(True)
        self._update_downloads_tab_visibility()
        process = QProcess(self)
        process.setProgram(command[0])
        process.setArguments(command[1:])
        process.setProcessEnvironment(self._egs_process_environment())
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._read_egs_download_output)
        process.finished.connect(self._on_egs_download_finished)
        self.egs_process = process
        self.egs_active_game = game
        self.egs_active_install_path = install_path
        self.egs_download_output = ""
        self.egs_download_total = 0.0
        self.downloadOverallProgress.setValue(0)
        self.downloadCancelButton.setEnabled(True)
        self.switchTab(6)
        process.start()

    def _start_egs_visible_operation(
        self, game: dict, command: list[str], action: str
    ) -> None:
        app_id = str(game["app_id"])
        display_action = "EOS Overlay" if action.startswith("eos-") else action
        self.downloadActiveTitle.setText(str(game["title"]))
        self.downloadActiveDetails.setText(display_action)
        cover_width, cover_height = self.theme.downloadsActiveCoverSize
        load_pixmap_async(
            str(game.get("cover", "")), cover_width, cover_height,
            self.downloadActiveCover.setPixmap,
            app_name=f"download-active-{app_id}",
        )
        self.downloadActiveHeading.setVisible(True)
        self.downloadActiveCard.setVisible(True)
        self._update_downloads_tab_visibility()
        process = QProcess(self)
        process.setProgram(command[0])
        process.setArguments(command[1:])
        process.setProcessEnvironment(self._egs_process_environment())
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._read_egs_download_output)
        process.finished.connect(
            lambda code, _status: self._on_egs_operation_finished(
                app_id, action, code
            )
        )
        self.egs_process = process
        self.egs_active_game = game
        self.egs_download_output = ""
        self.egs_download_total = 0.0
        self.downloadOverallProgress.setValue(0)
        self.downloadCancelButton.setEnabled(True)
        self.switchTab(6)
        process.start()

    def _cancel_gog_download(self) -> None:
        process = self.gog_process or self.egs_process
        if process is None:
            return
        if self.egs_process is not None:
            self.egs_active_game.pop("_dlcs", None)
        self.downloadCancelButton.setEnabled(False)
        self.downloadActiveDetails.setText(_("Cancel"))
        process.terminate()
        QTimer.singleShot(
            GOG_CANCEL_KILL_TIMEOUT_MS,
            lambda: self._kill_gog_process(process),
        )

    def _kill_gog_process(self, process: QProcess) -> None:
        try:
            if process.state() != QProcess.ProcessState.NotRunning:
                logger.warning("gogdl did not terminate after cancellation; killing it")
                process.kill()
        except RuntimeError:
            # QProcess may be deleted by its finished handler before the timer fires.
            return

    def _clear_egs_data_lock(self) -> None:
        lock_path = self.egs_api.config_dir / "installed.json.lock"
        try:
            lock_path.unlink(missing_ok=True)
        except OSError as error:
            logger.warning("Failed to clear Legendary data lock: %s", error)

    def _append_download_row(
        self, table: QTableWidget, game: dict, action: str, store: str = "GOG"
    ) -> tuple[int, QLabel]:
        row = table.rowCount()
        table.insertRow(row)
        game_cell, details_label = self._create_download_game_cell(game)
        table.setCellWidget(row, 0, game_cell)
        values = (datetime.now().strftime("%H:%M:%S"), action, store)
        for column, value in enumerate(values, 1):
            table.setItem(row, column, QTableWidgetItem(value))
        table.setRowHeight(row, self.theme.downloadsTableRowHeight)
        if table is self.downloadQueuedTable:
            details_label.setText(_("Queued"))
        else:
            details_label.setText(action)
        self._update_download_table_height(table)
        self._update_downloads_tab_visibility()
        return row, details_label

    def _create_download_game_cell(self, game: dict) -> tuple[QWidget, QLabel]:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(*self.theme.downloadsCellMargins)
        layout.setSpacing(self.theme.downloadsCellSpacing)
        cover = QLabel()
        cover.setObjectName("downloadGameCover")
        cover_width, cover_height = self.theme.downloadsCoverSize
        cover.setFixedSize(cover_width, cover_height)
        layout.addWidget(cover)
        text_layout = QVBoxLayout()
        title = QLabel(str(game["title"]))
        title.setObjectName("downloadGameTitle")
        details = QLabel(_("Waiting…"))
        details.setStyleSheet(self.theme.CONTENT_STYLE)
        text_layout.addWidget(title)
        text_layout.addWidget(details)
        layout.addLayout(text_layout)
        def set_cover(pixmap: QPixmap) -> None:
            if isValid(cover):
                cover.setPixmap(round_corners(pixmap, self.theme.downloadsCoverRadius))

        load_pixmap_async(
            str(game.get("cover", "")), cover_width, cover_height, set_cover,
            app_name=f"download-{game['app_id']}",
        )
        return widget, details

    def _gog_process_environment(self) -> QProcessEnvironment:
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("GOGDL_CONFIG_PATH", str(self.gog_api.config_dir))
        return environment

    def _read_gog_download_output(self) -> None:
        if self.gog_process is None:
            return
        output = bytes(
            self.gog_process.readAllStandardOutput().data()
        ).decode(errors="replace")
        self.gog_download_output = (self.gog_download_output + output)[-4096:]
        percentages = re.findall(
            r"Progress:\s+(\d{1,3}(?:\.\d+)?)", self.gog_download_output
        )
        if percentages:
            self.downloadOverallProgress.setValue(int(float(percentages[-1])))
        download_speeds = re.findall(
            r"Download\t-\s+(\S+)\s+MiB", self.gog_download_output
        )
        disk_speeds = re.findall(
            r"Disk\t-\s+(\S+)\s+MiB", self.gog_download_output
        )
        downloaded = re.findall(
            r"Downloaded:\s+([\d.]+\s+MiB)", self.gog_download_output
        )
        eta = re.findall(r"ETA:\s+(\d{2}:\d{2}:\d{2})", self.gog_download_output)
        if download_speeds:
            self.downloadSpeedLabel.setText(
                _("Download: {0} MiB/s").format(download_speeds[-1])
            )
        if disk_speeds:
            self.diskSpeedLabel.setText(
                _("Disk: {0} MiB/s").format(disk_speeds[-1])
            )
        details = []
        if downloaded:
            details.append(downloaded[-1])
        if download_speeds:
            details.append(f"{download_speeds[-1]} MiB/s")
        if eta:
            details.append(_("ETA: {0}").format(eta[-1]))
        if details:
            self._update_active_download_details(details)

    def _read_egs_download_output(self) -> None:
        if self.egs_process is None:
            return
        output = bytes(
            self.egs_process.readAllStandardOutput().data()
        ).decode(errors="replace")
        self.egs_download_output = (self.egs_download_output + output)[-4096:]
        total = re.findall(r"Download size:\s+([\d.]+)\s+MiB", output)
        if total:
            self.egs_download_total = float(total[-1])
        verification = re.findall(
            r"Verification progress:\s*\d+/\d+\s+\(([\d.]+)%\)"
            r"(?:\s+\[([\d.]+)\s+MiB/s\])?",
            self.egs_download_output,
        )
        if verification:
            percent, speed = verification[-1]
            self.downloadOverallProgress.setValue(min(100, int(float(percent))))
            details = [f"{percent}%"]
            if speed:
                details.append(f"{speed} MiB/s")
            self._update_active_download_details(details)
        downloaded = re.findall(
            r"Downloaded:\s+([\d.]+)\s+MiB", self.egs_download_output
        )
        if downloaded and self.egs_download_total > 0:
            progress = float(downloaded[-1]) / self.egs_download_total * 100
            self.downloadOverallProgress.setValue(min(100, int(progress)))
        download_speeds = re.findall(
            r"Download\t-\s+(\S+)\s+MiB", self.egs_download_output
        )
        disk_speeds = re.findall(
            r"Disk\t-\s+(\S+)\s+MiB", self.egs_download_output
        )
        eta = re.findall(r"ETA:\s+(\d{2}:\d{2}:\d{2})", self.egs_download_output)
        if download_speeds:
            self.downloadSpeedLabel.setText(
                _("Download: {0} MiB/s").format(download_speeds[-1])
            )
        if disk_speeds:
            self.diskSpeedLabel.setText(
                _("Disk: {0} MiB/s").format(disk_speeds[-1])
            )
        details = []
        if downloaded and self.egs_download_total > 0:
            details.append(
                f"{_format_download_size(float(downloaded[-1]))} / "
                f"{_format_download_size(self.egs_download_total)}"
            )
        elif downloaded:
            details.append(f"{downloaded[-1]} MiB")
        if eta:
            details.append(_("ETA: {0}").format(eta[-1]))
        if details:
            self._update_active_download_details(details)
        elif output.strip():
            self.downloadActiveDetails.setText(output.strip().splitlines()[-1])

    def _update_active_download_details(self, details: list[str]) -> None:
        self.downloadActiveDetails.setText("  ·  ".join(details))

    def _on_gog_download_finished(
        self, code: int, _status: QProcess.ExitStatus
    ) -> None:
        game = self.gog_active_game
        install_path = self.gog_active_install_path
        app_id = str(game["app_id"])
        self.downloadActiveHeading.setVisible(False)
        self.downloadActiveCard.setVisible(False)
        game_path = self.gog_api.find_install_path(app_id, install_path)
        if code == 0 and game_path is None:
            code = 1
        completed_action = _("Failed")
        if code == 0:
            completed_action = (
                _("Repaired") if self.gog_active_action == _("Repair")
                else _("Installed")
            )
        _completed_row, completed_details = self._append_download_row(
            self.downloadCompletedTable, game, completed_action,
        )
        if code == 0:
            self.gog_api.save_installed_game(
                app_id, {"install_path": str(game_path), "title": game["title"]}
            )
            self._update_installed_gog_detail(app_id)
            self.loadGames(force_load=True)
        else:
            error = self._get_gog_download_error()
            completed_details.setText(error)
            logger.error("GOG download failed for %s: %s", app_id, error)
        self.gog_process = None
        self.downloadOverallProgress.setValue(0)
        self.downloadSpeedLabel.setText(_("Downloading: ") + "\u2014")
        self.diskSpeedLabel.setText(_("Disk: ") + "\u2014")
        if self.gog_download_queue:
            next_game = self.gog_download_queue.pop(0)
            self.downloadQueuedTable.removeRow(0)
            self._update_download_table_height(self.downloadQueuedTable)
            self._install_gog_game(next_game)

    def _on_egs_download_finished(
        self, code: int, _status: QProcess.ExitStatus
    ) -> None:
        game = self.egs_active_game
        app_id = str(game["app_id"])
        if self.egs_install_importing:
            self.egs_install_importing = False
            imported = app_id in self.egs_api.load_installed()
            no_game_files = "No files belonging to" in self.egs_download_output
            if code == 0 and (imported or no_game_files):
                process = self.egs_process
                self.egs_process = None
                self._clear_egs_data_lock()
                if process is not None:
                    process.deleteLater()
                try:
                    arguments = [
                        "repair", app_id, "--repair-and-update", "--skip-sdl", "-y",
                    ]
                    if not imported:
                        arguments = [
                            "install", app_id, "--base-path", str(self.egs_active_install_path),
                            "--platform", "Windows", "--skip-sdl", "--skip-dlcs", "-y",
                        ]
                    command = self.egs_api.build_command(arguments)
                except OSError as error:
                    logger.error("Failed to start Epic repair: %s", error)
                    self.egs_download_output = str(error)
                    code = 1
                else:
                    self._start_egs_download(game, self.egs_active_install_path, command)
                    return
            else:
                code = 1
        if code == 0 and game.get("_dlcs"):
            process = self.egs_process
            self.egs_process = None
            self._clear_egs_data_lock()
            if process is not None:
                process.deleteLater()
            try:
                install_path = Path(self.egs_api.load_installed()[app_id]["install_path"])
                self._start_next_egs_dlc(game, install_path)
            except Exception as error:
                logger.exception("Failed to start Epic DLC installation")
                self.egs_download_output = str(error)
                code = 1
            else:
                return
        self.downloadActiveHeading.setVisible(False)
        self.downloadActiveCard.setVisible(False)
        completed_action = _("Installed") if code == 0 else _("Failed")
        _row, completed_details = self._append_download_row(
            self.downloadCompletedTable, game, completed_action, "Epic Games"
        )
        if code == 0:
            self._update_installed_egs_detail(app_id)
            self.loadGames(force_load=True)
        else:
            error = self._get_egs_download_error()
            completed_details.setText(error)
            logger.error("Epic download failed for %s: %s", app_id, error)
        process = self.egs_process
        self.egs_process = None
        self._clear_egs_data_lock()
        if process is not None:
            process.deleteLater()
        self.downloadOverallProgress.setValue(0)
        self.downloadSpeedLabel.setText(_("Downloading: ") + "\u2014")
        self.diskSpeedLabel.setText(_("Disk: ") + "\u2014")

    def _finish_egs_visible_operation(self, action: str, success: bool) -> None:
        game = self.egs_active_game
        display_action = "EOS Overlay" if action.startswith("eos-") else action
        self.downloadActiveHeading.setVisible(False)
        self.downloadActiveCard.setVisible(False)
        _row, details = self._append_download_row(
            self.downloadCompletedTable, game, display_action, "Epic Games"
        )
        details.setText(_("Completed") if success else self._get_egs_download_error())
        process = self.egs_process
        self.egs_process = None
        self._clear_egs_data_lock()
        if process is not None:
            process.deleteLater()
        self.downloadOverallProgress.setValue(0)
        self.downloadSpeedLabel.setText(_("Downloading: ") + "\u2014")
        self.diskSpeedLabel.setText(_("Disk: ") + "\u2014")

    def _start_gog_support_setup(self, app_id: str, button=None) -> None:
        if getattr(self, "gog_support_workers", []):
            return
        start_command = getattr(self, "start_sh", None)
        if not start_command:
            logger.warning("PortProton is unavailable for GOG support setup")
            return
        self.downloadActiveTitle.setText("GOG Redist")
        self.downloadActiveDetails.setText(_("Starting"))
        self.downloadActiveCover.clear()
        self.downloadActiveHeading.setVisible(True)
        self.downloadActiveCard.setVisible(True)
        self._update_downloads_tab_visibility()
        self.downloadCancelButton.setEnabled(False)
        self.downloadOverallProgress.setValue(0)
        worker = GOGSupportWorker(self.gog_api, app_id, start_command)
        worker.failed.connect(self.gogAccountStatus.setText)
        worker.launched.connect(
            lambda process: self._track_gog_support_process(
                app_id, process, button
            )
        )
        worker.succeeded.connect(
            lambda: self._launch_after_gog_support(app_id, button)
        )
        worker.finished.connect(lambda: self._finish_gog_support_setup(worker))
        self.gog_support_workers.append(worker)
        SoundManager().play("game_launch")
        worker.start()

    def _track_gog_support_process(
        self, app_id: str, process: subprocess.Popen, button=None
    ) -> None:
        target = self.gog_api.get_launch_target(app_id)
        self.game_processes.append(process)
        self.target_exe = os.path.basename(target or app_id)
        self.current_running_button = button
        self._start_launch_output_reader(process)
        self.input_manager.suspend_gamepad_polling()
        self._set_running_button_stop()
        self.checkProcessTimer = QTimer(self)
        self.checkProcessTimer.timeout.connect(self.checkTargetExe)
        self.checkProcessTimer.start(500)

    def _launch_after_gog_support(self, app_id: str, button=None) -> None:
        self.game_processes = [
            process for process in self.game_processes
            if process.poll() is None
        ]
        timer = self.checkProcessTimer
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        self.checkProcessTimer = None
        self._launch_gog_game(app_id, button, play_sound=False)

    def _finish_gog_support_setup(self, worker: GOGSupportWorker) -> None:
        workers = getattr(self, "gog_support_workers", [])
        if worker in workers:
            workers.remove(worker)
        self.downloadActiveHeading.setVisible(False)
        self.downloadActiveCard.setVisible(False)
        action = _("Failed") if worker.error else _("Installed")
        redist = {"app_id": "gog-redist", "title": "GOG Redist", "cover": ""}
        _row, details = self._append_download_row(
            self.downloadCompletedTable, redist, action
        )
        if worker.error:
            details.setText(worker.error)
            self.resetPlayButton()

    def _get_gog_download_error(self) -> str:
        lines = [line.strip() for line in self.gog_download_output.splitlines()]
        error_lines = [line for line in lines if "ERROR" in line.upper()]
        if error_lines:
            return error_lines[-1]
        useful = [line for line in lines if line and "[PROGRESS]" not in line]
        return useful[-1] if useful else _("Download process failed")

    def _get_egs_download_error(self) -> str:
        lines = [line.strip() for line in self.egs_download_output.splitlines()]
        errors = [line for line in lines if "ERROR" in line.upper()]
        if errors:
            return errors[-1]
        useful = [line for line in lines if line]
        return useful[-1] if useful else _("Download process failed")

    def _update_installed_gog_detail(self, app_id: str) -> None:
        install_uri = f"gog://install/{app_id}"
        if self.current_exec_line != install_uri:
            return
        if self.stackedWidget.currentWidget() is not self.currentDetailPage:
            return
        source = self.detail_page_manager._current_detail_source
        if source is None or source[0] != "game":
            return
        source[1]["exec_line"] = f"gog://launch/{app_id}"
        self.current_exec_line = source[1]["exec_line"]
        self.detail_page_manager._reopen_current_detail_page()

    def _update_installed_egs_detail(self, app_id: str) -> None:
        install_uri = f"egs://install/{app_id}"
        if self.current_exec_line != install_uri:
            return
        if self.stackedWidget.currentWidget() is not self.currentDetailPage:
            return
        source = self.detail_page_manager._current_detail_source
        if source is None or source[0] != "game":
            return
        source[1]["exec_line"] = f"egs://launch/{app_id}"
        self.current_exec_line = source[1]["exec_line"]
        self.detail_page_manager._reopen_current_detail_page()
