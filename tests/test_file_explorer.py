"""Tests for themed file explorer icons."""

import os
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

from pytest import MonkeyPatch
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyleOptionViewItem,
)

import portprotonqt.dialogs.file_explorer as file_explorer_module
from portprotonqt.input_manager.file_explorer import FileExplorerInputMixin
from portprotonqt.input_manager.constants import BUTTONS
from portprotonqt.dialogs.file_explorer import (
    FileExplorer,
    FileIconDelegate,
    THEMED_ICON_ROLE,
)

_application = QApplication.instance() or QApplication([])


def test_executable_filter_keeps_exe_and_linux_executables(tmp_path: Path) -> None:
    from PySide6.QtCore import QMimeDatabase
    from PySide6.QtWidgets import QLabel

    for name in ("Game.EXE", "launcher", "notes.txt"):
        (tmp_path / name).touch()
    (tmp_path / "launcher").chmod(0o755)
    (tmp_path / "folder").mkdir()
    explorer = SimpleNamespace(
        file_list=QListWidget(), current_path=str(tmp_path), directory_only=False,
        thumbnail_cache={}, pending_thumbnails={}, deferred_thumbnails={}, file_items={},
        path_history={}, path_label=QLabel(), mime_db=QMimeDatabase(),
        file_filter=lambda path: path.lower().endswith(".exe") or os.access(path, os.X_OK),
        _get_list_icon=lambda name: None, _get_file_type_icon=lambda path: None,
        schedule_thumbnail_loading=lambda: None,
    )

    FileExplorer.update_file_list(cast(FileExplorer, explorer))

    assert [explorer.file_list.item(i).text() for i in range(explorer.file_list.count())] == [
        "../", "folder/", "Game.EXE", "launcher",
    ]


def test_gamepad_opens_file_explorer_context_menu(monkeypatch: MonkeyPatch) -> None:
    explorer = FileExplorer.__new__(FileExplorer)
    QDialog.__init__(explorer)
    explorer.file_list = QListWidget(explorer)
    explorer.file_list.addItem("folder/")
    explorer.file_list.setCurrentRow(0)
    context_manager = MagicMock()
    explorer.context_menu_manager = context_manager
    manager = SimpleNamespace(file_explorer=explorer, _parent=SimpleNamespace())
    monkeypatch.setattr(QApplication, "activeWindow", lambda: explorer)
    monkeypatch.setattr(QApplication, "activePopupWidget", lambda: None)

    FileExplorerInputMixin.handle_file_explorer_button(
        cast(FileExplorerInputMixin, manager), next(iter(BUTTONS["context_menu"])), 1,
    )

    item = explorer.file_list.currentItem()
    assert item is not None
    context_manager.show_file_explorer_context_menu.assert_called_once_with(
        explorer, explorer.file_list.visualItemRect(item).center(),
    )


class FakeIcon:
    """Record icon files assigned to Qt modes."""

    Mode = QIcon.Mode

    def __init__(self) -> None:
        self.files: dict[QIcon.Mode, str] = {}

    def addFile(self, path: str, _size: QSize, mode: QIcon.Mode) -> None:
        self.files[mode] = path


def test_file_icon_delegate_uses_active_icon_on_hover() -> None:
    list_widget = QListWidget()
    item = QListWidgetItem("folder/")
    normal_pixmap = QPixmap(4, 4)
    normal_pixmap.fill(QColor("#111111"))
    active_pixmap = QPixmap(4, 4)
    active_pixmap.fill(QColor("#222222"))
    icon = QIcon()
    icon.addPixmap(normal_pixmap, QIcon.Mode.Normal)
    icon.addPixmap(active_pixmap, QIcon.Mode.Active)
    item.setIcon(icon)
    item.setData(THEMED_ICON_ROLE, True)
    list_widget.addItem(item)
    option = QStyleOptionViewItem()
    option.state = QStyle.StateFlag.State_MouseOver
    option.decorationSize = QSize(4, 4)

    FileIconDelegate(list_widget).initStyleOption(
        option,
        list_widget.model().index(0, 0),
    )

    rendered = option.icon.pixmap(QSize(4, 4)).toImage()
    assert rendered.pixelColor(0, 0) == QColor("#222222")


def test_list_icon_uses_theme_state_colors(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    icon_path = tmp_path / "folder.svg"
    icon_path.write_text("<svg/>", encoding="utf-8")
    explorer = FileExplorer.__new__(FileExplorer)
    explorer.theme = SimpleNamespace(ICON_COLORS={
        "folder_hover": "#111111",
        "*_focused": "#222222",
        "*_disabled": "#333333",
    })
    monkeypatch.setattr(file_explorer_module, "QIcon", FakeIcon)
    monkeypatch.setattr(
        file_explorer_module.theme_manager,
        "get_icon",
        lambda *_args, **_kwargs: str(icon_path),
    )
    monkeypatch.setattr(
        file_explorer_module.theme_manager,
        "get_colored_icon_path",
        lambda name, color: f"{name}-{color}.svg",
    )

    icon = cast(FakeIcon, explorer._get_list_icon("folder"))

    assert icon.files == {
        QIcon.Mode.Normal: str(icon_path),
        QIcon.Mode.Active: "folder-#111111.svg",
        QIcon.Mode.Selected: "folder-#222222.svg",
        QIcon.Mode.Disabled: "folder-#333333.svg",
    }
