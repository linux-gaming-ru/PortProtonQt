"""Tests for migration logic — desktop shortcuts, launcher commands, legacy paths.

Covers all migration scenarios:
- Legacy Flatpak exec → portprotonqt (parsing old shortcuts)
- Legacy home path (~/PortProton) → current (~/PortProtonQt)
- Legacy flatpak data path → current portproton_path
- env start.sh → portprotonqt
- Steam scripts migration
- Exec line rewriting
- Prefix backup helpers
- Legacy squashfs detection
"""
import os
import shlex
from pathlib import Path
from unittest.mock import Mock

from libarchive.flags import READDISK_NO_XATTR
import pytest

from portprotonqt.config.portproton import (
    _extract_launcher_tail,
    _migrate_launcher_line,
    _get_current_launcher_command,
    _get_desktop_paths,
    migrate_legacy_shortcut,
)
from portprotonqt.scripts_utils.prefix_backup import (
    is_legacy_squashfs_backup,
    _archive_entry,
    _prefix_path,
    _backup_path,
    _safe_entry_path,
    SQUASHFS_MAGIC,
    BACKUP_EXTENSION,
)


def _mock_get_desktop_paths(desktop_dir):
    if desktop_dir:
        return (desktop_dir,)
    return ()


# ── Launcher command detection ───────────────────────────────────────────────

class TestGetCurrentLauncherCommand:
    def test_appimage(self, tmp_path, monkeypatch):
        appimage = tmp_path / "PortProtonQt.AppImage"
        appimage.touch()
        monkeypatch.setenv("APPIMAGE", str(appimage))
        monkeypatch.delenv("FLATPAK_ID", raising=False)
        monkeypatch.setattr(
            "portprotonqt.config.portproton.get_portproton_scripts_path",
            lambda: None,
        )
        result = _get_current_launcher_command()
        assert result is not None
        assert result[0].endswith(".AppImage")
        assert "--silent" in result

    def test_portprotonqt_in_path(self, monkeypatch, tmp_path):
        monkeypatch.delenv("APPIMAGE", raising=False)
        monkeypatch.delenv("FLATPAK_ID", raising=False)
        monkeypatch.setattr(
            "portprotonqt.config.portproton.get_portproton_scripts_path",
            lambda: None,
        )
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/portprotonqt" if name == "portprotonqt" else None)
        result = _get_current_launcher_command()
        assert result is not None
        assert result == ["portprotonqt", "--silent"]

    def test_scripts_path(self, monkeypatch, tmp_path):
        monkeypatch.delenv("APPIMAGE", raising=False)
        monkeypatch.delenv("FLATPAK_ID", raising=False)
        monkeypatch.setattr(
            "portprotonqt.config.portproton.get_portproton_scripts_path",
            lambda: str(tmp_path / "scripts"),
        )
        result = _get_current_launcher_command()
        assert result is not None
        assert result[0].endswith("start.sh")

    def test_nothing_found(self, monkeypatch):
        monkeypatch.delenv("APPIMAGE", raising=False)
        monkeypatch.delenv("FLATPAK_ID", raising=False)
        monkeypatch.setattr("shutil.which", lambda name: None)
        monkeypatch.setattr(
            "portprotonqt.config.portproton.get_portproton_scripts_path",
            lambda: None,
        )
        result = _get_current_launcher_command()
        assert result is None


# ── Launcher tail extraction ─────────────────────────────────────────────────

class TestExtractLauncherTail:
    def test_appimage_with_silent(self):
        parts = ["/path/PortProtonQt.AppImage", "--silent", "/game.exe"]
        assert _extract_launcher_tail(parts) == ["/game.exe"]

    def test_appimage_without_silent(self):
        parts = ["/path/PortProtonQt.AppImage", "/game.exe"]
        assert _extract_launcher_tail(parts) == ["/game.exe"]

    def test_portprotonqt_with_silent(self):
        parts = ["portprotonqt", "--silent", "/game.exe"]
        assert _extract_launcher_tail(parts) == ["/game.exe"]

    def test_start_sh_with_silent(self):
        parts = ["start.sh", "--silent", "/game.exe"]
        assert _extract_launcher_tail(parts) == ["/game.exe"]

    def test_unknown_command(self):
        parts = ["/usr/bin/wine64", "/game.exe"]
        assert _extract_launcher_tail(parts) is None

    def test_empty(self):
        assert _extract_launcher_tail([]) is None


# ── Launcher line migration ──────────────────────────────────────────────────

class TestMigrateLauncherLine:
    def test_flatpak_legacy_to_portprotonqt(self, monkeypatch):
        monkeypatch.setattr(
            "portprotonqt.config.portproton._get_current_launcher_command",
            lambda: ["portprotonqt", "--silent"],
        )
        old = 'Exec=flatpak run ru.linux_gaming.PortProton --silent "/tmp/game.exe"'
        result = _migrate_launcher_line(old, ["portprotonqt", "--silent"])
        assert result.startswith("Exec=portprotonqt")
        assert "/tmp/game.exe" in result

    def test_preserves_exe_path_with_spaces(self, monkeypatch):
        monkeypatch.setattr(
            "portprotonqt.config.portproton._get_current_launcher_command",
            lambda: ["portprotonqt", "--silent"],
        )
        old = 'Exec=flatpak run ru.linux_gaming.PortProton --silent "/path/my game.exe"'
        result = _migrate_launcher_line(old, ["portprotonqt", "--silent"])
        assert "my game.exe" in result

    def test_shell_script_with_dollar_at(self, monkeypatch):
        monkeypatch.setattr(
            "portprotonqt.config.portproton._get_current_launcher_command",
            lambda: ["portprotonqt", "--silent"],
        )
        old = 'portprotonqt --silent "/game.exe" "$@"'
        result = _migrate_launcher_line(old, ["portprotonqt", "--silent"])
        assert '"$@"' in result

    def test_no_launcher_command(self):
        old = 'Exec=flatpak run old.App --silent "/game.exe"'
        result = _migrate_launcher_line(old, None)
        assert result == old

    def test_comment_line(self):
        old = "#Exec=flatpak run old.App"
        result = _migrate_launcher_line(old, ["new"])
        assert result == old

    def test_empty_command(self):
        old = "Exec="
        result = _migrate_launcher_line(old, ["new"])
        assert result == old

    def test_invalid_shlex(self):
        old = 'Exec=broken "unclosed'
        result = _migrate_launcher_line(old, ["new"])
        assert result == old

    def test_exec_prefix_preserved(self, monkeypatch):
        monkeypatch.setattr(
            "portprotonqt.config.portproton._get_current_launcher_command",
            lambda: ["portprotonqt", "--silent"],
        )
        old = 'Exec=flatpak run ru.linux_gaming.PortProton --silent "/game.exe"'
        result = _migrate_launcher_line(old, ["portprotonqt", "--silent"])
        assert result.startswith("Exec=")


# ── Desktop shortcut migration ───────────────────────────────────────────────

class TestMigrateLegacyShortcut:
    def _setup_migration_dirs(self, tmp_path):
        desktop_dir = tmp_path / "desktop"
        desktop_dir.mkdir()
        pp_dir = tmp_path / "PortProtonQt"
        pp_dir.mkdir()
        return desktop_dir, pp_dir

    def _write_desktop(self, desktop_dir, content):
        f = desktop_dir / "Game.desktop"
        f.write_text(content)
        return f

    def test_migrates_legacy_flatpak_exec(self, tmp_path, monkeypatch):
        desktop_dir, pp_dir = self._setup_migration_dirs(tmp_path)
        desktop_file = self._write_desktop(
            desktop_dir,
            "[Desktop Entry]\n"
            "Name=Game\n"
            'Exec=flatpak run ru.linux_gaming.PortProton --silent "/tmp/game.exe"\n',
        )

        monkeypatch.setattr(
            "portprotonqt.config.portproton._get_current_launcher_command",
            lambda: ["portprotonqt", "--silent"],
        )
        monkeypatch.setattr(
            "portprotonqt.config.portproton._get_desktop_paths",
            _mock_get_desktop_paths,
        )

        migrated = migrate_legacy_shortcut(str(pp_dir), str(desktop_dir))
        assert migrated >= 1

        content = desktop_file.read_text()
        assert "portprotonqt" in content
        assert "flatpak" not in content

    def test_removes_path_line(self, tmp_path, monkeypatch):
        desktop_dir, pp_dir = self._setup_migration_dirs(tmp_path)
        desktop_file = self._write_desktop(
            desktop_dir,
            "[Desktop Entry]\n"
            "Name=Game\n"
            "Path=/old/path\n"
            'Exec=portprotonqt --silent "/game.exe"\n',
        )

        monkeypatch.setattr(
            "portprotonqt.config.portproton._get_current_launcher_command",
            lambda: ["portprotonqt", "--silent"],
        )
        monkeypatch.setattr(
            "portprotonqt.config.portproton._get_desktop_paths",
            _mock_get_desktop_paths,
        )

        migrate_legacy_shortcut(str(pp_dir), str(desktop_dir))
        content = desktop_file.read_text()
        assert "Path=" not in content

    def test_migrates_steam_scripts(self, tmp_path, monkeypatch):
        pp_dir = tmp_path / "PortProtonQt"
        steam_scripts = pp_dir / "steam_scripts"
        steam_scripts.mkdir(parents=True)

        script = steam_scripts / "game.sh"
        script.write_text(
            '#!/bin/bash\n'
            'portprotonqt "/game.exe" "$@"\n',
        )

        monkeypatch.setattr(
            "portprotonqt.config.portproton._get_current_launcher_command",
            lambda: ["portprotonqt", "--silent"],
        )
        monkeypatch.setattr(
            "portprotonqt.config.portproton._get_desktop_paths",
            _mock_get_desktop_paths,
        )

        migrated = migrate_legacy_shortcut(str(pp_dir), "/nonexistent")
        assert migrated >= 1

        content = script.read_text()
        assert "--silent" in content

    def test_legacy_flatpak_exec_replaced_with_portprotonqt(self, tmp_path, monkeypatch):
        desktop_dir, pp_dir = self._setup_migration_dirs(tmp_path)

        legacy_data = os.path.expanduser("~/.var/app/ru.linux_gaming.PortProton")

        desktop_file = self._write_desktop(
            desktop_dir,
            "[Desktop Entry]\n"
            f'Exec=flatpak run ru.linux_gaming.PortProton --silent "{legacy_data}/data/game.exe"\n',
        )

        monkeypatch.setattr(
            "portprotonqt.config.portproton._get_current_launcher_command",
            lambda: ["portprotonqt", "--silent"],
        )
        monkeypatch.setattr(
            "portprotonqt.config.portproton._get_desktop_paths",
            _mock_get_desktop_paths,
        )

        migrate_legacy_shortcut(str(pp_dir), str(desktop_dir))
        content = desktop_file.read_text()
        assert "flatpak" not in content
        assert "portprotonqt" in content

    def test_no_portproton_path_returns_zero(self, tmp_path, monkeypatch):
        nonexistent = str(tmp_path / "nonexistent")
        monkeypatch.setattr(
            "portprotonqt.config.portproton._get_current_launcher_command",
            lambda: ["portprotonqt", "--silent"],
        )
        monkeypatch.setattr(
            "portprotonqt.config.portproton._get_desktop_paths",
            _mock_get_desktop_paths,
        )
        migrated = migrate_legacy_shortcut(nonexistent)
        assert migrated == 0

    def test_non_desktop_files_skipped(self, tmp_path, monkeypatch):
        desktop_dir, pp_dir = self._setup_migration_dirs(tmp_path)

        (desktop_dir / "readme.txt").write_text("not a desktop file")
        self._write_desktop(
            desktop_dir,
            "[Desktop Entry]\n"
            'Exec=/usr/bin/wine64 "/game.exe"\n',
        )

        monkeypatch.setattr(
            "portprotonqt.config.portproton._get_current_launcher_command",
            lambda: ["portprotonqt", "--silent"],
        )
        monkeypatch.setattr(
            "portprotonqt.config.portproton._get_desktop_paths",
            _mock_get_desktop_paths,
        )

        migrated = migrate_legacy_shortcut(str(pp_dir), str(desktop_dir))
        assert migrated == 0


# ── Desktop paths ────────────────────────────────────────────────────────────

class TestGetDesktopPaths:
    def test_custom_dir(self):
        assert _get_desktop_paths("/my/desktop") == ("/my/desktop",)

    def test_none_returns_default(self):
        result = _get_desktop_paths(None)
        assert len(result) >= 1


# ── Legacy squashfs backup detection ─────────────────────────────────────────

class TestIsLegacySquashfsBackup:
    def test_squashfs_magic(self, tmp_path):
        f = tmp_path / "backup.ppack"
        f.write_bytes(SQUASHFS_MAGIC + b"\x00\x00\x00\x00")
        assert is_legacy_squashfs_backup(str(f)) is True

    def test_non_squashfs(self, tmp_path):
        f = tmp_path / "backup.ppack"
        f.write_bytes(b"\x50\x4b\x03\x04")
        assert is_legacy_squashfs_backup(str(f)) is False

    def test_empty_file(self, tmp_path):
        f = tmp_path / "backup.ppack"
        f.write_bytes(b"")
        assert is_legacy_squashfs_backup(str(f)) is False

    def test_nonexistent_file(self):
        assert is_legacy_squashfs_backup("/nonexistent/backup.ppack") is False

    def test_short_file(self, tmp_path):
        f = tmp_path / "backup.ppack"
        f.write_bytes(b"hs")
        assert is_legacy_squashfs_backup(str(f)) is False

    def test_exact_magic(self):
        assert SQUASHFS_MAGIC == b"hsqs"


# ── Prefix backup helpers ────────────────────────────────────────────────────

class TestPrefixPath:
    def test_basic(self):
        result = _prefix_path("/data", "MYPREFIX")
        assert result.endswith("prefixes/MYPREFIX")
        assert "data" in result

    def test_safe_name(self):
        result = _prefix_path("/data", "../../etc/passwd")
        assert "passwd" not in result or result.endswith("prefixes/passwd")

    def test_empty_name(self):
        result = _prefix_path("/data", "")
        assert result.endswith("prefixes/")


class TestBackupPath:
    def test_basic(self):
        final, part = _backup_path("/backups", "MYPREFIX")
        assert final.endswith("MYPREFIX.ppack")
        assert part.endswith("MYPREFIX.ppack.part")

    def test_safe_name(self):
        final, part = _backup_path("/backups", "../../etc/passwd")
        assert "passwd" in final
        assert final.endswith(BACKUP_EXTENSION)


class TestArchiveEntry:
    def test_add_files_compatible_with_libarchive_5_1(self, tmp_path: Path) -> None:
        source = tmp_path / "file.txt"
        source.write_text("content")
        archive = Mock()

        assert _archive_entry(archive, str(source), "file.txt") is True
        archive.add_files.assert_called_once_with(
            str(source),
            flags=READDISK_NO_XATTR,
            pathname="file.txt",
            recursive=False,
        )


class TestSafeEntryPath:
    def test_valid_relative(self):
        result = _safe_entry_path("/target", "file.txt")
        assert result == "/target/file.txt"

    def test_nested_relative(self):
        result = _safe_entry_path("/target", "dir/file.txt")
        assert result == "/target/dir/file.txt"

    def test_absolute_blocked(self):
        with pytest.raises(ValueError, match="Unsafe"):
            _safe_entry_path("/target", "/etc/passwd")

    def test_traversal_blocked(self):
        with pytest.raises(ValueError, match="Unsafe"):
            _safe_entry_path("/target", "../etc/passwd")

    def test_double_traversal_blocked(self):
        with pytest.raises(ValueError, match="Unsafe"):
            _safe_entry_path("/target", "foo/../../etc/passwd")


# ── exec_line migration integration ──────────────────────────────────────────

class TestExecLineMigrationIntegration:
    def test_portprotonqt_exec_extracted(self):
        exec_line = 'portprotonqt --silent "/home/user/PortProtonQt/data/game.exe"'
        parts = shlex.split(exec_line)
        tail = _extract_launcher_tail(parts)
        assert tail == ["/home/user/PortProtonQt/data/game.exe"]

    def test_env_start_sh_exec_extracted(self):
        exec_line = 'env WINEPREFIX="/p" start.sh --silent "/game.exe"'
        parts = shlex.split(exec_line)
        tail = _extract_launcher_tail(parts)
        assert tail is None

    def test_appimage_exec_extracted(self):
        exec_line = '/opt/PortProtonQt.AppImage --silent "/game.exe"'
        parts = shlex.split(exec_line)
        tail = _extract_launcher_tail(parts)
        assert tail == ["/game.exe"]

    def test_versioned_appimage_exec_extracted(self):
        parts = shlex.split(
            '/opt/PortProtonQt-1.3.2-anylinux-x86_64.AppImage "/game.exe"'
        )
        assert _extract_launcher_tail(parts) == ["/game.exe"]

    def test_unrelated_appimage_exec_ignored(self):
        parts = shlex.split('/opt/OtherGame.AppImage "/game.exe"')
        assert _extract_launcher_tail(parts) is None

    def test_migrate_to_appimage(self, monkeypatch):
        monkeypatch.setattr(
            "portprotonqt.config.portproton._get_current_launcher_command",
            lambda: ["/opt/PortProtonQt.AppImage", "--silent"],
        )
        old = 'Exec=flatpak run ru.linux_gaming.PortProton --silent "/game.exe"'
        result = _migrate_launcher_line(old, ["/opt/PortProtonQt.AppImage", "--silent"])
        assert ".AppImage" in result
        assert "/game.exe" in result
