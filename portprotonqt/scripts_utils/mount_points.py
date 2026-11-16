"""Print mounted drive paths for PortProton scripts."""

import os
import re
import sys

from portprotonqt.logger import get_logger


logger = get_logger(__name__)

MOUNT_PARENT_PATHS = ("/run/media/", "/media/", "/mnt/")
MOUNT_ROOT_PATHS = {"/media", "/mnt", "/run/media"}
NETWORK_MOUNT_TYPES = {"cifs", "nfs", "nfs4", "smb3", "smbfs"}
VIRTUAL_MOUNT_TYPES = {"autofs"}
MOUNT_ESCAPE_PATTERN = re.compile(r"\\([0-7]{3})")


def list_mounted_drive_paths(mounts_path: str = "/proc/mounts") -> list[str]:
    """Return local mounted drive paths available to the user."""
    if sys.platform == "darwin":
        from pathlib import Path
        volumes = Path("/Volumes")
        return sorted(str(path) for path in volumes.iterdir()
                      if path.is_dir() and os.access(path, os.R_OK)) if volumes.is_dir() else []
    try:
        mounts = _read_mounts(mounts_path)
        mounted_drives = set()
        for source, mount_point, fs_type in mounts:
            if fs_type in VIRTUAL_MOUNT_TYPES:
                continue
            if _is_network_mount(source, fs_type):
                continue
            if not _is_block_device_source(source):
                continue
            if not _is_local_drive_mount(mount_point):
                continue
            if os.path.isdir(mount_point) and os.access(mount_point, os.R_OK):
                mounted_drives.add(mount_point)
    except OSError as error:
        logger.error("Error retrieving mounted drives: %s", error)
        return []
    return sorted(mounted_drives)


def _read_mounts(mounts_path: str) -> list[tuple[str, str, str]]:
    mounts = []
    with open(mounts_path) as mounts_file:
        for line in mounts_file:
            parts = line.strip().split()
            if len(parts) < 3:
                continue
            mounts.append((
                _decode_mount_field(parts[0]),
                _decode_mount_field(parts[1]),
                parts[2],
            ))
    return mounts


def _decode_mount_field(value: str) -> str:
    return MOUNT_ESCAPE_PATTERN.sub(
        lambda match: chr(int(match.group(1), 8)),
        value,
    )


def _is_network_mount(source: str, fs_type: str) -> bool:
    return (
        fs_type in NETWORK_MOUNT_TYPES
        or source.startswith(("//", "\\\\"))
        or (":/" in source and not source.startswith("/"))
    )


def _is_block_device_source(source: str) -> bool:
    return source.startswith("/dev/")


def _is_local_drive_mount(mount_point: str) -> bool:
    if mount_point == "/" or mount_point in MOUNT_ROOT_PATHS:
        return False
    return mount_point.startswith(MOUNT_PARENT_PATHS)


def main() -> int:
    paths = list_mounted_drive_paths()
    if paths:
        sys.stdout.write("\n".join(paths) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
