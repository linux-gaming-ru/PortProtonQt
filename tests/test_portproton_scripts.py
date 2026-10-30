"""Tests for the bundled PortProton shell scripts."""
import os
import subprocess
from pathlib import Path

from pytest import mark


@mark.parametrize("case", [
    ("0", "0", "", ""),
    ("1", "1", "", ""),
    ("1", "0", "", 'export MANGOHUD_CONFIG="cpu_stats,font_size=24"\n'),
    ("1", "0", "gpu_stats", ""),
])
def test_gui_edit_db_only_creates_enabled_mangohud_config(
    tmp_path: Path, case: tuple[str, str, str, str],
) -> None:
    enabled, user_conf, existing, expected = case
    helper = Path("build-aux/share/portproton/scripts/functions_helper").read_text()
    gui_body = helper.split("gui_edit_db () {", 1)[1].split(
        "# Gamescope configuration and processing", 1,
    )[0]
    block = gui_body.split('    edit_db_from_gui "${PW_EDIT_DB_FINAL_LIST[@]}"', 1)[1]
    ppdb = tmp_path / "game.exe.ppdb"
    ppdb.touch()
    script = '''
edit_db_from_gui () {
    printf 'export MANGOHUD_CONFIG="%s"\\n' "$MANGOHUD_CONFIG" >> "$PORTWINE_DB_FILE"
}
gui_config () {
''' + block + '\ngui_config\n'

    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=False,
        env={"PATH": os.defpath, "PORTWINE_DB_FILE": str(ppdb), "MANGOHUD": "1",
             "PW_MANGOHUD": enabled, "PW_MANGOHUD_USER_CONF": user_conf,
             "MANGOHUD_CONFIG": existing, "DEFAULT_MANGOHUD_CONFIG": "cpu_stats",
             "PW_SCREEN_RESOLUTION": "1920x1080"},
    )

    assert result.returncode == 0, result.stderr
    assert ppdb.read_text() == expected


@mark.parametrize("second_name", ["Game.exe", "Trainer.exe"])
@mark.parametrize("copies", [1, 3])
def test_run_after_accepts_same_exe(tmp_path: Path, second_name: str, copies: int) -> None:
    helper = Path("build-aux/share/portproton/scripts/functions_helper").read_text()
    condition = helper.split('        local -a run_after_exes=', 1)[1].split(
        "        then", 1,
    )[0]
    condition = '        local -a run_after_exes=' + condition
    main_exe = tmp_path / "Game.exe"
    second_exe = tmp_path / second_name
    main_exe.touch()
    second_exe.touch()
    result = subprocess.run(
        ["bash", "-c", 'check_run_after() {\n' + condition
         + "then return 0; else return 1; fi; }; check_run_after"],
        env={**os.environ, "PW_EXE_FILE": str(main_exe),
             "PW_RUN_AFTER_EXE": ",".join([str(second_exe)] * copies)},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_run_after_batch_is_created_next_to_exe() -> None:
    helper = Path("build-aux/share/portproton/scripts/functions_helper").read_text(
        encoding="utf-8",
    )

    assert 'run_after_dir="$(dirname "${PW_EXE_FILE}")"' in helper
    assert 'pw_exe_file_win="$("${WINELOADER}" winepath -w "${PW_EXE_FILE}"' in helper
    assert "chcp 65001 >nul" in helper
    assert 'start "" "%PW_RUN_AFTER_MAIN_PATH%" ${LAUNCH_PARAMETERS}' in helper
    assert 'start "" "%PW_RUN_AFTER_SECOND_PATH%"' in helper
    assert 'LAUNCH_PARAMETERS="" proxy_launch_parameters="" \\' in helper
    assert 'pw_run "${PW_VD_TMP[@]}" "${run_after_bat}"' in helper


@mark.parametrize("mapped_path", [
    "D:\\Загрузки\\Trainer.exe",
    "E:\\Тестовые файлы\\Утилиты\\Папка 123 @тест\\Test Trainer.exe",
    "",
])
def test_run_after_exe_windows_path(tmp_path: Path, mapped_path: str) -> None:
    helper = Path("build-aux/share/portproton/scripts/functions_helper").read_text()
    conversion = helper.split('            run_after_exe_win="$(', 1)[1].split(
        '\n\n            cat >', 1,
    )[0]
    exe_path = (
        tmp_path / "mnt" / "test-drive" / "Тестовые файлы" / "Утилиты"
        / "Папка 123 @тест" / "Test Trainer.exe"
    )
    result = subprocess.run(
        ["bash", "-c", 'loader() { printf "%s\\r\\n" "$MAPPED_PATH"; }\n'
         'WINELOADER=loader\nwine_drive_c="$WINEPREFIX/drive_c"\n'
         'run_after_exe_win="$(' + conversion + '\nprintf "%s" "$run_after_exe_win"'],
        env={**os.environ, "PW_RUN_AFTER_EXE": str(exe_path),
             "WINEPREFIX": str(tmp_path / "prefix"), "MAPPED_PATH": mapped_path},
        capture_output=True, text=True, check=True,
    )
    assert result.stdout == (mapped_path or "z:" + str(exe_path).replace("/", "\\"))


@mark.parametrize("trainer_path", [
    "H:\\Загрузки\\Trainer.exe",
    "E:\\Тестовые файлы\\Утилиты\\Папка 123 @тест\\Test Trainer.exe",
])
def test_run_after_paths_are_passed_in_environment(tmp_path: Path, trainer_path: str) -> None:
    helper = Path("build-aux/share/portproton/scripts/functions_helper").read_text()
    block = helper.split('            cat > "${run_after_bat}" <<EOF\n', 1)[1].split(
        '            try_remove_file "${run_after_bat}"', 1,
    )[0]
    main_path = "D:\\Games\\Test Game\\Test Game.exe"
    result = subprocess.run(
        ["bash", "-c", 'pw_run() { env; }\nlaunch() {\n'
         'local -a run_after_exes=(unused) run_after_environment=()\n'
         'cat > "$run_after_bat" <<EOF\n' + block + '\n}; launch'],
        env={**os.environ, "run_after_bat": str(tmp_path / "launch.bat"),
             "pw_exe_file_win": main_path, "run_after_exe_win": trainer_path,
             "wait_delay_int": "3", "LAUNCH_PARAMETERS": ""},
        capture_output=True, text=True, check=True,
    )
    assert f"PW_RUN_AFTER_MAIN_PATH={main_path}" in result.stdout
    assert f"PW_RUN_AFTER_SECOND_PATH={trainer_path}" in result.stdout
    assert "PW_RUN_AFTER_EXE=\n" in result.stdout
    batch = (tmp_path / "launch.bat").read_text(encoding="ascii")
    assert 'start "" "%PW_RUN_AFTER_SECOND_PATH%"' in batch


def test_game_launch_marker_is_emitted_for_wine_and_proton() -> None:
    helper = Path("build-aux/share/portproton/scripts/functions_helper").read_text(
        encoding="utf-8",
    )

    marker = "printf '%s\\n' 'PORTPROTONQT_GAME_LAUNCH_STARTED'"
    assert helper.count(marker) == 2


def test_user_conf_get_without_name_lists_active_values(tmp_path: Path) -> None:
    helper = Path("build-aux/share/portproton/scripts/functions_helper").read_text()
    definition = helper.split("manage_user_conf_value () {", 1)[1].split(
        "use_exiftool () {", 1
    )[0]
    user_conf = tmp_path / "user.conf"
    user_conf.write_text(
        '# comment\nexport PW_USE_ESYNC="1"\n# export PW_USE_FSYNC="1"\n',
        encoding="utf-8",
    )
    script = "manage_user_conf_value () {" + definition + '\nmanage_user_conf_value get\n'

    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True,
        env={"PATH": os.defpath, "USER_CONF": str(user_conf)}, check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == 'PW_USE_ESYNC="1"\n'


@mark.parametrize("runtime,logging", [("0", "0"), ("0", "1"), ("1", "0"), ("1", "1")])
def test_wine_exit_code_survives_log_output_and_wineserver_wait(
    tmp_path: Path, runtime: str, logging: str,
) -> None:
    helper = Path("build-aux/share/portproton/scripts/functions_helper").read_text()
    definition = helper.split("pw_run () {", 1)[1].split("export -f pw_run", 1)[0]
    script = "pw_run () {" + definition + '''
check_variables () { :; }
pw_launch_wrapper () { return 37; }
wait_wineserver () { return 0; }
print_info () { :; }
PATH_TO_GAME="$1"
PW_TMPFS_PATH="$1"
PW_LOG_FILE="$1/wine.log"
PW_EXE_FILE="$1/game.exe"
PW_USE_RUNTIME="$2"
PW_LOG="$3"
pw_run "$PW_EXE_FILE"
exit $?
'''
    (tmp_path / "game.exe").touch()

    result = subprocess.run(
        ["bash", "-c", script, "bash", str(tmp_path), runtime, logging],
        capture_output=True, text=True, env={"PATH": os.defpath}, check=False,
    )

    assert result.returncode == 37, result.stderr
    assert result.stdout.count("PORTPROTONQT_GAME_EXIT_CODE=37") == 1


def test_vk_gpu_info_uses_build_aux_binary() -> None:
    helper = Path("build-aux/share/portproton/scripts/functions_helper").read_text(
        encoding="utf-8",
    )

    assert '/../../../bin/vk_gpu_info"' in helper
    assert "dev-scripts/vk_gpu_info" not in helper


@mark.parametrize("filename,pe_status,expected_calls", [
    ("Game [one].EXE", "0", ["pe"]),
    ("Game [one].exe", "1", ["pe", "exiftool"]),
    ("Game [one].lnk", "0", ["exiftool"]),
])
def test_executable_metadata_uses_pefile_and_preserves_lnk_fallback(
    tmp_path: Path, filename: str, pe_status: str, expected_calls: list[str],
) -> None:
    helper = Path("build-aux/share/portproton/scripts/functions_helper").read_text()
    definition = helper.split("use_exiftool () {", 1)[1].split("\npw_create_gui_png () {", 1)[0]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exiftool = bin_dir / "exiftool"
    exiftool.write_text('#!/bin/sh\nprintf "exiftool\\n" >> "$CALLS"\nprintf "Product Name: Fallback\\n"\n')
    exiftool.chmod(0o755)
    calls = tmp_path / "calls"
    script = '''python_module () {
    printf 'pe\\n' >> "$CALLS"
    if [[ "$PE_STATUS" == 0 ]]; then
        printf 'Product Name: Game\\nFile Description: Description\\nCompany Name: Sony\\n'
    fi
    return "$PE_STATUS"
}
'''
    script += 'use_exiftool () {' + definition + '\nuse_exiftool "$TARGET"\nuse_exiftool "$TARGET"\n'
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=False,
        env={**os.environ, "PATH": f"{bin_dir}:{os.defpath}", "PW_TMPFS_PATH": str(tmp_path),
             "CALLS": str(calls), "PE_STATUS": pe_status, "TARGET": str(tmp_path / filename)},
    )
    assert result.returncode == 0, result.stderr
    assert calls.read_text().splitlines() == expected_calls
    metadata = (tmp_path / "exiftool.tmp").read_text()
    assert metadata.splitlines()[0] == str(tmp_path / filename)
    assert "Product Name:" in metadata
    if expected_calls == ["pe"]:
        assert "File Description: Description" in metadata
        assert "Company Name: Sony" in metadata


def test_run_after_batch_preserves_duplicate_entries(tmp_path: Path) -> None:
    helper = Path("build-aux/share/portproton/scripts/functions_helper").read_text()
    block = helper.split('            cat > "${run_after_bat}" <<EOF\n', 1)[1].split(
        '            try_remove_file "${run_after_bat}"', 1,
    )[0]
    exe = tmp_path / "EVE online.exe"
    exe.touch()
    script = '''
loader() { printf 'Z:%s' "$3"; }
pw_run() { env; }
launch() {
local -a run_after_exes=("$EXE" "$EXE" "$EXE") run_after_environment=()
local run_after_index run_after_entry
WINELOADER=loader
cat > "$run_after_bat" <<EOF
''' + block + '\n}; launch'
    batch_path = tmp_path / "launch.bat"
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=True,
        env={**os.environ, "EXE": str(exe), "run_after_bat": str(batch_path),
             "pw_exe_file_win": "Z:\\EVE online.exe",
             "run_after_exe_win": "Z:\\EVE online.exe", "wait_delay_int": "3"},
    )
    batch = batch_path.read_text()
    assert batch.count('start ""') == 4
    assert '%PW_RUN_AFTER_PATH_1%' in batch
    assert '%PW_RUN_AFTER_PATH_2%' in batch
    expected = "Z:" + str(exe).replace("/", "\\")
    assert f"PW_RUN_AFTER_PATH_1={expected}" in result.stdout
    assert f"PW_RUN_AFTER_PATH_2={expected}" in result.stdout


def test_run_after_wrapper_runs_script_list_with_duplicates(tmp_path: Path) -> None:
    helper = Path("build-aux/share/portproton/scripts/functions_helper").read_text()
    wrapper = helper.split("pw_launch_wrapper () {", 1)[1].split(
        "export -f pw_launch_wrapper", 1,
    )[0]
    first = tmp_path / "first script.sh"
    second = tmp_path / "second.sh"
    for script, message in [(first, "first"), (second, "second")]:
        script.write_text(f"#!/bin/bash\nprintf '{message}\\n'\n")
        script.chmod(0o700)
    result = subprocess.run(
        ["bash", "-c", "pw_launch_wrapper () {" + wrapper
         + "\npw_launch_wrapper printf 'game\\n'"],
        env={**os.environ, "PW_RUN_AFTER_EXE": f"{first},{second},{first}"},
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.splitlines() == ["first", "second", "first", "game"]


def test_run_after_wrapper_preserves_command_with_comma(tmp_path: Path) -> None:
    helper = Path("build-aux/share/portproton/scripts/functions_helper").read_text()
    wrapper = helper.split("pw_launch_wrapper () {", 1)[1].split(
        "export -f pw_launch_wrapper", 1,
    )[0]
    result = subprocess.run(
        ["bash", "-c", "pw_launch_wrapper () {" + wrapper
         + "\npw_launch_wrapper printf 'game\\n'"],
        cwd=tmp_path,
        env={**os.environ, "PW_RUN_AFTER_EXE": "printf '%s\\n' first,second"},
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.splitlines() == ["first,second", "game"]
