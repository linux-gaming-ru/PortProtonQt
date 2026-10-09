"""Tests for the bundled PortProton shell scripts."""
import os
import subprocess
from pathlib import Path

from pytest import mark


@mark.parametrize("second_name", ["Game.exe", "Trainer.exe"])
def test_run_after_accepts_same_exe(tmp_path: Path, second_name: str) -> None:
    helper = Path("build-aux/share/portproton/scripts/functions_helper").read_text()
    condition = helper.split('        if [[ -n "${PW_RUN_AFTER_EXE:-}" ]]', 1)[1].split(
        "        then", 1,
    )[0]
    main_exe = tmp_path / "Game.exe"
    second_exe = tmp_path / second_name
    main_exe.touch()
    second_exe.touch()
    result = subprocess.run(
        ["bash", "-c", 'if [[ -n "${PW_RUN_AFTER_EXE:-}" ]]' + condition
         + "then exit 0; else exit 1; fi"],
        env={**os.environ, "PW_EXE_FILE": str(main_exe),
             "PW_RUN_AFTER_EXE": str(second_exe)},
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
        ["bash", "-c", 'pw_run() { env; }\ncat > "$run_after_bat" <<EOF\n' + block],
        env={**os.environ, "run_after_bat": str(tmp_path / "launch.bat"),
             "pw_exe_file_win": main_path, "run_after_exe_win": trainer_path,
             "wait_delay_int": "3", "LAUNCH_PARAMETERS": ""},
        capture_output=True, text=True, check=True,
    )
    assert f"PW_RUN_AFTER_MAIN_PATH={main_path}" in result.stdout
    assert f"PW_RUN_AFTER_SECOND_PATH={trainer_path}" in result.stdout
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


@mark.parametrize("tool", ["winefile", "taskmgr", "winecfg", "regedit", "cmd", "uninstaller"])
def test_wine_session_tools_reuse_prefix_without_game_options(tmp_path: Path, tool: str) -> None:
    helper = Path("build-aux/share/portproton/scripts/functions_helper").read_text()
    definitions = helper.split("pw_save_session_env () {", 1)[1].split("pw_launch_wrapper () {", 1)[0]
    script = "pw_save_session_env () {" + definitions + '''
print_error () { echo "$@" >&2; }
pw_run () {
    printf '%s\\n' "$1" "$WINEPREFIX" "${PW_USE_TERMINAL:-0}" "${LAUNCH_PARAMETERS:-}" \\
        "${PW_RUN_AFTER_EXE:-}" "${PW_RUN_GAMESCOPE:-}" "$PW_TMPFS_PATH"
}
PW_TERM="test-terminal"
export PW_START_PID="$$" WINEPREFIX="$PORT_DATA_PATH/prefix with spaces"
export LAUNCH_PARAMETERS="--game-only" PW_RUN_AFTER_EXE=trainer.exe PW_RUN_GAMESCOPE=gamescope
pw_save_session_env || exit 2
pw_session_tool "$1"
'''
    (tmp_path / "prefix with spaces/drive_c").mkdir(parents=True)
    result = subprocess.run(
        ["bash", "-c", script, "bash", tool], capture_output=True, text=True,
        env={"PATH": os.defpath, "PORT_DATA_PATH": str(tmp_path)}, check=False,
    )

    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[:6] == [tool, str(tmp_path / "prefix with spaces"), "1" if tool == "cmd" else "0", "", "", ""]
    assert Path(lines[6]).is_dir()
    assert Path(lines[6]).stat().st_mode & 0o777 == 0o700
    session = next((tmp_path / "data/tmp").glob("wine-session-*/session.env"))
    assert session.stat().st_mode & 0o777 == 0o600
    assert 'declare -x PW_TERM="test-terminal"' in session.read_text()


@mark.parametrize("unsafe_directory", [False, True])
def test_wine_session_save_does_not_follow_symlinks(tmp_path: Path, unsafe_directory: bool) -> None:
    helper = Path("build-aux/share/portproton/scripts/functions_helper").read_text()
    definition = helper.split("pw_save_session_env () {", 1)[1].split("pw_remove_session_env () {", 1)[0]
    session_dir = tmp_path / "data/tmp" / f"wine-session-{os.getuid()}"
    session_dir.parent.mkdir(parents=True)
    victim = tmp_path / "victim"
    victim.write_text("keep this")
    if unsafe_directory:
        target = tmp_path / "other-directory"
        target.mkdir(mode=0o700)
        session_dir.symlink_to(target, target_is_directory=True)
    else:
        session_dir.mkdir(mode=0o700)
        (session_dir / "session.env").symlink_to(victim)
    result = subprocess.run(
        ["bash", "-c", "pw_save_session_env () {" + definition + "\npw_save_session_env"],
        capture_output=True, text=True,
        env={"PATH": os.defpath, "PORT_DATA_PATH": str(tmp_path)}, check=False,
    )

    assert victim.read_text() == "keep this"
    assert result.returncode == (1 if unsafe_directory else 0), result.stderr
    if not unsafe_directory:
        assert not (session_dir / "session.env").is_symlink()


def test_wine_session_tool_rejects_unknown_tool_before_reading_environment(tmp_path: Path) -> None:
    helper = Path("build-aux/share/portproton/scripts/functions_helper").read_text()
    definition = helper.split("pw_session_tool () {", 1)[1].split("pw_launch_wrapper () {", 1)[0]
    script = "pw_session_tool () {" + definition + '''
print_error () { echo "$@" >&2; }
sleep () { exit 99; }
pw_session_tool '../../other-command'
'''
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True,
        env={"PATH": os.defpath, "PORT_DATA_PATH": str(tmp_path)}, check=False,
    )

    assert result.returncode == 1
    assert "Unsupported Wine tool" in result.stderr


def test_wine_session_cleanup_preserves_newer_session(tmp_path: Path) -> None:
    helper = Path("build-aux/share/portproton/scripts/functions_helper").read_text()
    definitions = helper.split("pw_save_session_env () {", 1)[1].split("pw_session_tool () {", 1)[0]
    script = "pw_save_session_env () {" + definitions + '''
export PW_START_PID="$$"
pw_save_session_env || exit 2
PW_START_PID=99999999
pw_remove_session_env
[[ -f "$PORT_DATA_PATH/data/tmp/wine-session-$(id -u)/session.env" ]] || exit 3
PW_START_PID="$$"
pw_remove_session_env
[[ ! -e "$PORT_DATA_PATH/data/tmp/wine-session-$(id -u)/session.env" ]]
'''
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True,
        env={"PATH": os.defpath, "PORT_DATA_PATH": str(tmp_path)}, check=False,
    )

    assert result.returncode == 0, result.stderr
