"""Tests for config/portproton.py — exec_line parsing, icon sanitization, launcher tail extraction."""
import os
from pathlib import Path

from pytest import MonkeyPatch

from portprotonqt.config.portproton import (
    extract_exec_target_path,
    _sanitize_icon_name,
    _extract_launcher_tail,
    LAUNCH_FILE_EXTENSIONS,
    WINDOWS_LAUNCH_EXTENSIONS,
    DISC_IMAGE_EXTENSIONS,
    THEMED_LAUNCH_ICON_NAMES,
    get_portproton_scripts_path,
)


def test_scripts_path_uses_xdg_data_dirs(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    data_dir = tmp_path / "share"
    scripts_dir = data_dir / "portproton" / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "start.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_DATA_DIRS", str(data_dir))
    monkeypatch.delenv("APPDIR", raising=False)
    monkeypatch.delenv("SHARUN_DIR", raising=False)

    assert get_portproton_scripts_path() == str(scripts_dir)


class TestExtractExecTargetPath:
    def test_simple_exe_path(self):
        assert extract_exec_target_path("/tmp/game.exe") == "/tmp/game.exe"

    def test_with_silent_flag(self):
        result = extract_exec_target_path("/usr/bin/app --silent /tmp/game.exe")
        assert result == "/tmp/game.exe"

    def test_with_silent_at_end(self):
        result = extract_exec_target_path("/usr/bin/app --silent")
        assert result is None

    def test_exe_reversed_search(self):
        result = extract_exec_target_path("/usr/bin/portprotonqt --silent /tmp/game.exe")
        assert result == "/tmp/game.exe"

    def test_bat_file(self):
        result = extract_exec_target_path("flatpak run com.app --silent /tmp/setup.bat")
        assert result == "/tmp/setup.bat"

    def test_iso_file(self):
        result = extract_exec_target_path("/usr/bin/portprotonqt --silent /tmp/game.iso")
        assert result == "/tmp/game.iso"

    def test_env_prefix(self):
        result = extract_exec_target_path("env WINEPREFIX=/p /usr/bin/wine /tmp/game.exe")
        assert result == "/tmp/game.exe"

    def test_flatpak_prefix(self):
        result = extract_exec_target_path("flatpak run com.app --silent /tmp/game.exe")
        assert result == "/tmp/game.exe"

    def test_list_input(self):
        parts = ["/usr/bin/portprotonqt", "--silent", "/tmp/game.exe"]
        result = extract_exec_target_path(parts)
        assert result == "/tmp/game.exe"

    def test_empty_string(self):
        assert extract_exec_target_path("") is None

    def test_empty_list(self):
        assert extract_exec_target_path([]) is None

    def test_no_extension_returns_first_part(self):
        result = extract_exec_target_path("/usr/bin/wine64")
        assert result == "/usr/bin/wine64"

    def test_tilde_expansion(self):
        result = extract_exec_target_path("~/game.exe")
        assert result is not None
        assert os.path.expanduser("~") in result

    def test_msi_file_via_reversed_search(self):
        result = extract_exec_target_path("/usr/bin/portprotonqt /tmp/installer.msi")
        assert result == "/tmp/installer.msi"


class TestSanitizeIconName:
    def test_simple_name(self):
        assert _sanitize_icon_name("My Game") == "My_Game"

    def test_removes_special_chars(self):
        result = _sanitize_icon_name("Game! % $ & < Title")
        assert "!" not in result
        assert "%" not in result
        assert "$" not in result
        assert "&" not in result
        assert "<" not in result
        assert result == "Game_____Title"

    def test_preserves_normal_chars(self):
        assert _sanitize_icon_name("Game-2077") == "Game-2077"

    def test_empty_string(self):
        assert _sanitize_icon_name("") == ""

    def test_only_special_chars(self):
        result = _sanitize_icon_name("!%$&")
        assert result == ""


class TestExtractLauncherTail:
    def test_appimage_silent(self):
        parts = ["/path/to/PortProtonQt.AppImage", "--silent", "/tmp/game.exe"]
        result = _extract_launcher_tail(parts)
        assert result == ["/tmp/game.exe"]

    def test_appimage_no_silent(self):
        parts = ["/path/to/PortProtonQt.AppImage", "/tmp/game.exe"]
        result = _extract_launcher_tail(parts)
        assert result == ["/tmp/game.exe"]

    def test_portprotonqt_silent(self):
        parts = ["portprotonqt", "--silent", "/tmp/game.exe"]
        result = _extract_launcher_tail(parts)
        assert result == ["/tmp/game.exe"]

    def test_portprotonqt_no_silent(self):
        parts = ["portprotonqt", "/tmp/game.exe"]
        result = _extract_launcher_tail(parts)
        assert result == ["/tmp/game.exe"]

    def test_start_sh_silent(self):
        parts = ["start.sh", "--silent", "/tmp/game.exe"]
        result = _extract_launcher_tail(parts)
        assert result == ["/tmp/game.exe"]

    def test_flatpak_run_silent(self):
        parts = ["flatpak", "run", "com.app", "--silent", "/tmp/game.exe"]
        result = _extract_launcher_tail(parts)
        assert result == ["/tmp/game.exe"]

    def test_flatpak_run_no_silent(self):
        parts = ["flatpak", "run", "com.app", "/tmp/game.exe"]
        result = _extract_launcher_tail(parts)
        assert result == ["/tmp/game.exe"]

    def test_unknown_command(self):
        parts = ["/usr/bin/wine64", "/tmp/game.exe"]
        assert _extract_launcher_tail(parts) is None

    def test_empty_parts(self):
        assert _extract_launcher_tail([]) is None

    def test_flatpak_too_few_args(self):
        parts = ["flatpak", "run"]
        assert _extract_launcher_tail(parts) is None


class TestLaunchExtensions:
    def test_windows_extensions(self):
        assert ".exe" in WINDOWS_LAUNCH_EXTENSIONS
        assert ".bat" in WINDOWS_LAUNCH_EXTENSIONS
        assert ".cmd" in WINDOWS_LAUNCH_EXTENSIONS
        assert ".msi" in WINDOWS_LAUNCH_EXTENSIONS
        assert ".reg" in WINDOWS_LAUNCH_EXTENSIONS

    def test_disc_extensions(self):
        assert ".iso" in DISC_IMAGE_EXTENSIONS
        assert ".mdf" in DISC_IMAGE_EXTENSIONS
        assert ".nrg" in DISC_IMAGE_EXTENSIONS

    def test_launch_is_combined(self):
        assert LAUNCH_FILE_EXTENSIONS == WINDOWS_LAUNCH_EXTENSIONS + DISC_IMAGE_EXTENSIONS


class TestThemedLaunchIconNames:
    def test_bat_and_cmd_share_icon(self):
        assert THEMED_LAUNCH_ICON_NAMES[".bat"] == THEMED_LAUNCH_ICON_NAMES[".cmd"]

    def test_msi_has_icon(self):
        assert "msi" in THEMED_LAUNCH_ICON_NAMES[".msi"]

    def test_reg_has_icon(self):
        assert "reg" in THEMED_LAUNCH_ICON_NAMES[".reg"]


def test_run_after_batch_is_created_next_to_exe() -> None:
    helper = Path("build-aux/share/portproton/scripts/functions_helper").read_text(
        encoding="utf-8",
    )

    assert 'run_after_dir="$(dirname "${PW_EXE_FILE}")"' in helper
    assert 'pw_exe_file_win="$("${WINELOADER}" winepath -w "${PW_EXE_FILE}"' in helper
    assert "chcp 65001 >nul" in helper
    assert 'start "" "${pw_exe_file_win}" ${LAUNCH_PARAMETERS}' in helper
    assert 'start "" /unix "${PW_RUN_AFTER_EXE}"' in helper
    assert 'LAUNCH_PARAMETERS="" proxy_launch_parameters="" \\' in helper
    assert 'pw_run "${PW_VD_TMP[@]}" "${run_after_bat}"' in helper


def test_game_launch_marker_is_emitted_for_wine_and_proton() -> None:
    helper = Path("build-aux/share/portproton/scripts/functions_helper").read_text(
        encoding="utf-8",
    )

    marker = "printf '%s\\n' 'PORTPROTONQT_GAME_LAUNCH_STARTED'"
    assert helper.count(marker) == 1


def test_vk_gpu_info_uses_build_aux_binary() -> None:
    helper = Path("build-aux/share/portproton/scripts/functions_helper").read_text(
        encoding="utf-8",
    )

    assert '/../../../bin/vk_gpu_info"' in helper
    assert "dev-scripts/vk_gpu_info" not in helper


def test_steam_uses_common_portwine_launch() -> None:
    helper = Path("build-aux/share/portproton/scripts/functions_helper").read_text(
        encoding="utf-8",
    )
    start = Path("build-aux/share/portproton/scripts/start.sh").read_text(
        encoding="utf-8",
    )

    assert "steamplay_launch ()" not in helper
    assert 'export PW_STEAMPLAY="1"' in start
    assert '"${PROTON_RUNNER}" waitforexitandrun "${PW_EXE_FILE}" "$@"' in helper


def test_steam_skips_database_initialization() -> None:
    helper = Path("build-aux/share/portproton/scripts/functions_helper").read_text(
        encoding="utf-8",
    )
    start = Path("build-aux/share/portproton/scripts/start.sh").read_text(
        encoding="utf-8",
    )
    db_init = helper.index("pw_init_db ()")
    steam_db_return = helper.index("return 0", db_init)
    normal_db = helper.index('[[ -n "${PW_DEFAULT_WINE_USE:-}" ]]', steam_db_return)
    portproton_start = helper.index("start_portproton ()")
    steam_db = helper.index(
        'export PORTWINE_DB_FILE="${PW_EXE_FILE}.ppdb"',
        portproton_start,
    )
    steam_block_end = helper.index("\n    fi\n\n    pw_check_and_download_plugins", steam_db)
    steam_block = helper[steam_db:steam_block_end]
    prefix_guard = helper.index('if [[ "${PW_STEAMPLAY:-}" != "1" ]] ; then')
    normal_prefix = helper.index(
        'data/prefixes/${PW_PREFIX_NAME}"/drive_c/windows',
        prefix_guard,
    )
    api_guard = helper.index('if [[ "${PW_STEAMPLAY:-}" != "1" ]] ; then', normal_prefix)
    api_symlink = helper.index('print_info "Try create symlink DXVK files..."', api_guard)
    winetricks_guard = helper.index('if [[ "${PW_STEAMPLAY:-}" != "1" ]] ; then', api_symlink)
    winetricks_update = helper.index("update_winetricks", winetricks_guard)

    assert steam_db_return < normal_db
    assert portproton_start < steam_db
    assert "unset PW_PREFIX_NAME" in steam_block
    assert 'export WINEPREFIX="${STEAM_COMPAT_DATA_PATH}/pfx"' in steam_block
    assert "PW_PREFIX_NAME=" not in steam_block
    assert prefix_guard < normal_prefix
    assert api_guard < api_symlink
    assert winetricks_guard < winetricks_update
    assert "pw_init_db" in start
