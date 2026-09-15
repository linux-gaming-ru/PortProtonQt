"""Create and restore PortProton prefix backups."""

import argparse
import os
import shutil
import stat
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

import libarchive
from libarchive.entry import FileType
from libarchive.flags import READDISK_NO_XATTR

from portprotonqt.logger import get_logger

logger = get_logger(__name__)
BACKUP_EXTENSION = ".ppack"
ARCHIVE_FORMAT = "pax"
ARCHIVE_FILTER = "zstd"
SQUASHFS_MAGIC = b"hsqs"


@dataclass(frozen=True)
class BackupProgress:
    percent: int
    path: str
    files_done: int
    files_total: int
    speed: float


ProgressCallback = Callable[[BackupProgress], None]


def _prefix_path(port_data_path: str, prefix_name: str) -> str:
    safe_name = os.path.basename(prefix_name)
    return os.path.join(port_data_path, "data", "prefixes", safe_name)


def _backup_path(backup_dir: str, prefix_name: str) -> tuple[str, str]:
    safe_name = os.path.basename(prefix_name)
    final_path = os.path.join(backup_dir, f"{safe_name}{BACKUP_EXTENSION}")
    return final_path, f"{final_path}.part"


def is_legacy_squashfs_backup(backup_file: str) -> bool:
    try:
        with open(backup_file, "rb") as file:
            return file.read(4) == SQUASHFS_MAGIC
    except OSError as e:
        logger.warning("Failed to read backup header %s: %s", backup_file, e)
        return False


def _make_user_writable(path: str) -> None:
    for root, dirs, files in os.walk(path):
        for name in dirs + files:
            item_path = os.path.join(root, name)
            try:
                item_stat = os.lstat(item_path)
                if stat.S_ISLNK(item_stat.st_mode):
                    continue
                os.chmod(item_path, item_stat.st_mode | stat.S_IWUSR)
            except OSError as e:
                logger.warning("Failed to update permissions for %s: %s", item_path, e)


def _collect_entries(prefix_dir: str) -> list[tuple[str, str, int]]:
    entries = []
    for root, dirs, files in os.walk(prefix_dir):
        names = sorted(dirs) + sorted(files)
        for name in names:
            source_path = os.path.join(root, name)
            archive_path = os.path.relpath(source_path, prefix_dir)
            try:
                item_stat = os.lstat(source_path)
                size = item_stat.st_size if stat.S_ISREG(item_stat.st_mode) else 0
            except OSError:
                size = 0
            entries.append((source_path, archive_path, size))
    return entries


def _archive_symlink(archive, source_path: str, archive_path: str) -> bool:
    try:
        item_stat = os.lstat(source_path)
        link_path = os.readlink(source_path)
    except OSError as e:
        logger.warning("Skipped symlink %s: %s", source_path, e)
        return False

    if not os.path.exists(source_path):
        logger.warning("Skipped broken symlink %s -> %s", source_path, link_path)
        return False

    archive.add_file_from_memory(
        archive_path,
        0,
        b"",
        filetype=int(FileType.SYMBOLINK_LINK),
        permission=stat.S_IMODE(item_stat.st_mode),
        linkpath=link_path,
        mtime=item_stat.st_mtime,
    )
    return True


def _archive_entry(archive, source_path: str, archive_path: str) -> bool:
    try:
        item_stat = os.lstat(source_path)
    except OSError as e:
        logger.warning("Skipped archive entry %s: %s", source_path, e)
        return False

    if stat.S_ISLNK(item_stat.st_mode):
        return _archive_symlink(archive, source_path, archive_path)
    archive.add_files(
        source_path,
        flags=READDISK_NO_XATTR,
        pathname=archive_path,
        recursive=False,
    )
    return True


def _write_shortcut_manifest(port_data_path: str, prefix_name: str) -> None:
    shortcuts = []
    marker = f"/{prefix_name}/"
    for name in os.listdir(port_data_path):
        if not name.endswith(".desktop"):
            continue
        desktop_path = os.path.join(port_data_path, name)
        try:
            with open(desktop_path, encoding="utf-8", errors="ignore") as file:
                for line in file:
                    if marker in line:
                        shortcuts.append(line.split(marker, 1)[1].split('"', 1)[0])
        except OSError as e:
            logger.warning("Failed to read desktop file %s: %s", desktop_path, e)

    if not shortcuts:
        return

    manifest_path = os.path.join(_prefix_path(port_data_path, prefix_name), ".create_shortcut")
    try:
        os.remove(manifest_path)
    except FileNotFoundError:
        pass
    with open(manifest_path, "w", encoding="utf-8") as file:
        file.write("\n".join(shortcuts))
        file.write("\n")


def _emit_progress(
    callback: ProgressCallback | None,
    progress: BackupProgress,
) -> None:
    if callback:
        callback(progress)


def create_backup(
    port_data_path: str,
    prefix_name: str,
    backup_dir: str,
    progress_callback: ProgressCallback | None = None,
) -> int:
    prefix_dir = _prefix_path(port_data_path, prefix_name)
    final_path, part_path = _backup_path(backup_dir, prefix_name)
    if not os.path.isdir(prefix_dir):
        logger.error("Prefix directory not found: %s", prefix_dir)
        return 1

    os.makedirs(backup_dir, exist_ok=True)
    _write_shortcut_manifest(port_data_path, prefix_name)
    _make_user_writable(prefix_dir)

    try:
        entries = _collect_entries(prefix_dir)
        total_files = len(entries)
        total_size = sum(entry[2] for entry in entries) or 1
        processed_size = 0
        start_time = time.monotonic()
        with libarchive.file_writer(part_path, ARCHIVE_FORMAT, ARCHIVE_FILTER) as archive:
            for index, (source_path, archive_path, size) in enumerate(entries, 1):
                _archive_entry(archive, source_path, archive_path)
                processed_size += size
                elapsed = max(time.monotonic() - start_time, 0.001)
                speed = processed_size / (1024 * 1024) / elapsed
                percent = min(int((processed_size / total_size) * 100), 99)
                progress = BackupProgress(percent, archive_path, index, total_files, speed)
                _emit_progress(progress_callback, progress)
        os.replace(part_path, final_path)
        progress = BackupProgress(100, final_path, total_files, total_files, 0.0)
        _emit_progress(progress_callback, progress)
    except (libarchive.ArchiveError, OSError) as e:
        logger.error("Failed to create prefix backup %s: %s", prefix_name, e)
        try:
            os.remove(part_path)
        except FileNotFoundError:
            pass
        return 1
    return 0


def _safe_entry_path(target_dir: str, entry_path: str) -> str:
    if os.path.isabs(entry_path) or ".." in entry_path.split("/"):
        raise ValueError(f"Unsafe archive path: {entry_path}")
    destination = os.path.abspath(os.path.normpath(os.path.join(target_dir, entry_path)))
    target_root = os.path.abspath(os.path.normpath(target_dir))
    if destination != target_root and not destination.startswith(f"{target_root}/"):
        raise ValueError(f"Unsafe archive path: {entry_path}")
    return destination


def _apply_file_metadata(path: str, entry: libarchive.entry.ArchiveEntry) -> None:
    if entry.mode and not os.path.islink(path):
        try:
            os.chmod(path, entry.mode)
        except OSError as e:
            logger.warning("Failed to set permissions for %s: %s", path, e)
    if entry.mtime:
        try:
            os.utime(path, (entry.mtime, entry.mtime), follow_symlinks=False)
        except OSError as e:
            logger.warning("Failed to set mtime for %s: %s", path, e)


def _extract_entry(target_dir: str, entry: libarchive.entry.ArchiveEntry) -> None:
    entry_path = entry.pathname
    if entry_path is None:
        return
    destination = _safe_entry_path(target_dir, entry_path)
    parent_dir = os.path.dirname(destination)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    if entry.isdir:
        if os.path.islink(destination):
            os.remove(destination)
        os.makedirs(destination, exist_ok=True)
    elif entry.islnk:
        if os.path.lexists(destination):
            os.remove(destination)
        link_path = entry.linkpath
        if link_path is not None:
            os.symlink(link_path, destination)
    elif entry.isfile:
        if os.path.islink(destination):
            os.remove(destination)
        with open(destination, "wb") as file:
            for block in entry.get_blocks():
                file.write(block)
    else:
        logger.warning("Skipped unsupported archive entry: %s", entry_path)
        return
    _apply_file_metadata(destination, entry)


def _read_xdg_desktop_dir() -> str:
    config_path = os.path.join(os.path.expanduser("~"), ".config", "user-dirs.dirs")
    try:
        with open(config_path, encoding="utf-8") as file:
            for line in file:
                if line.startswith("XDG_DESKTOP_DIR="):
                    value = line.split("=", 1)[1].strip().strip('"')
                    return value.replace("$HOME", os.path.expanduser("~"))
    except OSError:
        pass
    return ""


def _desktop_target_dir() -> str:
    for path in (
        os.path.join(os.path.expanduser("~"), "Desktop"),
        os.path.join(os.path.expanduser("~"), "Рабочий стол"),
        _read_xdg_desktop_dir(),
    ):
        if path and os.path.isdir(path):
            return path
    return ""


def _copy_shortcut(desktop_path: str, target_dir: str) -> None:
    if not target_dir:
        return
    os.makedirs(target_dir, exist_ok=True)
    target_path = os.path.join(target_dir, os.path.basename(desktop_path))
    shutil.copyfile(desktop_path, target_path)
    os.chmod(target_path, 0o755)


def _create_restore_shortcuts(port_data_path: str, prefix_name: str) -> None:
    from portprotonqt.scripts_utils.shortcut_tools import create_shortcut

    manifest_path = os.path.join(_prefix_path(port_data_path, prefix_name), ".create_shortcut")
    if not os.path.isfile(manifest_path):
        return

    menu_dir = os.path.join(os.path.expanduser("~"), ".local", "share", "applications")
    desktop_dir = _desktop_target_dir()
    with open(manifest_path, encoding="utf-8") as file:
        for raw_line in file:
            rel_path = raw_line.strip()
            exe_path = os.path.join(_prefix_path(port_data_path, prefix_name), rel_path)
            game_name = os.path.splitext(os.path.basename(exe_path))[0]
            if not rel_path or not os.path.exists(exe_path):
                continue
            if not create_shortcut(exe_path, game_name):
                continue
            try:
                desktop_path = os.path.join(port_data_path, f"{game_name}.desktop")
                _copy_shortcut(desktop_path, menu_dir)
                _copy_shortcut(desktop_path, desktop_dir)
            except OSError as e:
                logger.warning("Failed to create restored shortcut for %s: %s", exe_path, e)


def restore_backup(
    port_data_path: str,
    backup_file: str,
    progress_callback: ProgressCallback | None = None,
) -> int:
    prefix_name = os.path.basename(backup_file)[:-len(BACKUP_EXTENSION)]
    target_dir = _prefix_path(port_data_path, prefix_name)
    os.makedirs(target_dir, exist_ok=True)

    try:
        archive_size = os.path.getsize(backup_file) or 1
        start_time = time.monotonic()
        files_done = 0
        with libarchive.file_reader(backup_file) as archive:
            for entry in archive:
                entry_path = entry.pathname
                if entry_path is None:
                    continue
                _extract_entry(target_dir, entry)
                files_done += 1
                bytes_read = archive.bytes_read
                elapsed = max(time.monotonic() - start_time, 0.001)
                speed = bytes_read / (1024 * 1024) / elapsed
                percent = min(int((bytes_read / archive_size) * 100), 99)
                progress = BackupProgress(percent, entry_path, files_done, 0, speed)
                _emit_progress(progress_callback, progress)
        _create_restore_shortcuts(port_data_path, prefix_name)
        progress = BackupProgress(100, target_dir, files_done, files_done, 0.0)
        _emit_progress(progress_callback, progress)
    except (libarchive.ArchiveError, OSError, ValueError) as e:
        logger.error("Failed to restore prefix backup %s: %s", backup_file, e)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="PortProton prefix backup helper")
    parser.add_argument("--port-data-path", required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("prefix_name")
    backup_parser.add_argument("backup_dir")
    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("backup_file")
    args = parser.parse_args()

    if args.command == "backup":
        return create_backup(args.port_data_path, args.prefix_name, args.backup_dir)
    return restore_backup(args.port_data_path, args.backup_file)


if __name__ == "__main__":
    sys.exit(main())
