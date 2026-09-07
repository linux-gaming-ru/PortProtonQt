#!/usr/bin/env bash
########################################################################
export url_site="https://linux-gaming.ru/portproton/"
export url_cloud="https://cloud.linux-gaming.ru/portproton"
export url_git="https://git.linux-gaming.ru/CastroFidel/PortWINE"
########################################################################
$PW_DEBUG

if [[ $(id -u) = 0 ]] \
&& [[ ! -e "/userdata/system/batocera.conf" ]]
then
    echo "Do not run this script as root!"
    exit 1
fi

if [[ "$(realpath "$0")" == "/usr/share/portproton/scripts/start.sh" ]] ; then
    PORT_SCRIPTS_PATH="/usr/share/portproton/scripts/"
else
    PORT_SCRIPTS_PATH="$(dirname "$(realpath "$0")")"
fi

PORT_CONF_PATH="$(dirname "$PORT_SCRIPTS_PATH")/conf"

if [[ -z "$PORT_DATA_PATH" ]] ; then
    if [[ -n "${XDG_DATA_HOME:-}" ]] ; then
        PORT_DATA_PATH="$(dirname "${XDG_DATA_HOME}")"
    elif [[ -f "$HOME/.config/PortProtonQt.conf" ]] \
    && grep "portdata_path" "$HOME/.config/PortProtonQt.conf" ; then
        PORT_DATA_PATH="$(grep "portdata_path" "$HOME/.config/PortProtonQt.conf" | awk -F"= " '{print $2}')"
    elif [[ -f "$HOME/.config/PortProton.conf" ]] ; then
        PORT_DATA_PATH="$(head -n 1 "$HOME/.config/PortProton.conf")"
    else
        echo "FATAL ERROR: PortProton data path not found"
        exit 1
    fi
fi

if [[ -n "${XDG_CONFIG_HOME:-}" ]] \
&& grep -q "disable_runtime_download = True" "$XDG_CONFIG_HOME/PortProtonQt.conf" ; then
	export PW_DISABLE_RUNTIME_DOWNLOAD=1
elif [[ -f "$HOME/.config/PortProtonQt.conf" ]] \
&& grep -q "disable_runtime_download = True" "$HOME/.config/PortProtonQt.conf" ; then
    export PW_DISABLE_RUNTIME_DOWNLOAD=1
fi

if [[ -n "${XDG_CONFIG_HOME:-}" ]] \
&& [[ -f "$XDG_CONFIG_HOME/PortProtonQt.conf" ]] \
&& grep -q "auto_download_ppdb = False" "$XDG_CONFIG_HOME/PortProtonQt.conf" ; then
    export PW_FIND_PPDB=0
elif [[ -f "$HOME/.config/PortProtonQt.conf" ]] \
&& grep -q "auto_download_ppdb = False" "$HOME/.config/PortProtonQt.conf" ; then
    export PW_FIND_PPDB=0
else
    export PW_FIND_PPDB=1
fi

export PORT_SCRIPTS_PATH PORT_DATA_PATH PORT_CONF_PATH
export PW_LOG_FILE="${PORT_DATA_PATH}/PortProton.log"

# shellcheck source=/dev/null
source "$PORT_SCRIPTS_PATH/functions_helper"

export PORT_WINE_TMP_PATH="${PORT_DATA_PATH}/data/tmp"
create_new_dir "$PORT_WINE_TMP_PATH"
rm -f "$PORT_WINE_TMP_PATH"/*.{exe,msi,tar}*

if mkdir -p "/tmp/PortProton_$USER" ; then
    export PW_TMPFS_PATH="/tmp/PortProton_$USER"
else
    create_new_dir "${PORT_DATA_PATH}/data/tmp/PortProton_$USER"
    export PW_TMPFS_PATH="${PORT_DATA_PATH}/data/tmp/PortProton_$USER"
fi

export PW_START_PID="$$"

# shellcheck source=/dev/null
source "${PORT_SCRIPTS_PATH}/var"

read -r -a pw_full_command_line <<< "$0 $*"
export pw_full_command_line
export orig_IFS="$IFS"

unset PW_NO_RESTART_PPDB PW_DISABLED_CREATE_DB

# TODO:
# Setting IME to fcitx5 to fix input
# export GTK_IM_MODULE=fcitx5
# export QT_IM_MODULE=fcitx5
# export QT5_IM_MODULE=fcitx5
# export XMODIFIERS=@im=fcitx5

# Setting for emulator
# export PW_USE_WOW64="1"
# export DBUS_FATAL_WARNINGS="0"

if [[ ${1,,} == "cli" ]] ; then
    shift
fi

if [[ "${1:-}" == file://* ]] ; then
    pw_file_path="${1#file://}"
    pw_file_path="${pw_file_path//%20/ }"
    set -- "${pw_file_path}" "${@:2}"
fi

if [[ "${1,,}" =~ \.ppack$ ]] ; then
    export PW_NO_RESTART_PPDB="1"
    export PW_DISABLED_CREATE_DB="1"
    PW_EXE_FILE="$1"
elif [[ "${1,,}" =~ \.(exe|bat|cmd|msi|reg)$ ]] ; then
    if [[ -f "$1" ]] ; then
        PW_EXE_FILE="$(realpath -s "$1")"
    elif [[ -f "$OLDPWD/$1" ]] ; then
        PW_EXE_FILE="$(realpath -s "$OLDPWD/$1")"
    elif [[ ! -f "$1" ]] ; then
        PW_EXE_FILE="$1"
        MISSING_DESKTOP_FILE="1"
    fi
elif [[ "$1" =~ ^--(debug|launch|edit-db)$ && "${2,,}" =~ \.(exe|bat|cmd|msi|reg)$ ]] ; then
    if [[ -f "$2" ]] ; then
        PW_EXE_FILE="$(realpath -s "$2")"
    elif [[ -f "$OLDPWD/$2" ]] ; then
        PW_EXE_FILE="$(realpath -s "$OLDPWD/$2")"
    fi
elif [[ "$1" == "--epic-wrapper" && "${2,,}" =~ \.exe$ ]] ; then
    prepare_epic_wrapper || fatal "Failed to prepare Epic launcher wrapper"
    PW_EXE_FILE="$(realpath -s "$2")"
fi
export PW_EXE_FILE

# HOTFIX - ModernWarships
if echo "$PW_EXE_FILE" | grep ModernWarships &>/dev/null \
&& [[ -f "$(dirname "${PW_EXE_FILE}")/Modern Warships.exe" ]]
then
    PW_EXE_FILE="$(dirname "${PW_EXE_FILE}")/Modern Warships.exe"
    export PW_EXE_FILE
    MISSING_DESKTOP_FILE="0"
fi

create_new_dir "${HOME}/.local/share/applications"

create_new_dir "${PORT_DATA_PATH}/data/dist"
IFS=$'\n'
for dist_dir in $(lsbash "${PORT_DATA_PATH}/data/dist/") ; do
    dist_dir_new=$(echo "${dist_dir}" | awk '$1=$1' | sed -e 's/[[:blank:]]*-[[:blank:]]*/-/g' -e 's/[[:blank:]]/_/g')
    if [[ ! -d "${PORT_DATA_PATH}/data/dist/${dist_dir_new^^}" ]] ; then
        mv -- "${PORT_DATA_PATH}/data/dist/$dist_dir" "${PORT_DATA_PATH}/data/dist/${dist_dir_new^^}"
    fi
done
IFS="$orig_IFS"

create_new_dir "${PORT_DATA_PATH}/data/prefixes/DEFAULT"
create_new_dir "${PORT_DATA_PATH}/data/prefixes/DOTNET"
try_force_link_dir "${PORT_DATA_PATH}/data/prefixes" "${PORT_DATA_PATH}"

pushd "${PORT_DATA_PATH}/data/prefixes/" 1>/dev/null || fatal "Failed to enter prefixes directory"
for pfx_dir in ./* ; do
    [[ -d "$pfx_dir" ]] || continue
    pfx_dir_new="${pfx_dir//[[:blank:]]/_}"
    if [[ ! -d "${PORT_DATA_PATH}/data/prefixes/${pfx_dir_new^^}" ]] ; then
        mv -- "${PORT_DATA_PATH}/data/prefixes/$pfx_dir" "${PORT_DATA_PATH}/data/prefixes/${pfx_dir_new^^}"
    fi
done
popd 1>/dev/null || fatal "Failed to return from prefixes directory"

create_new_dir "${PORT_WINE_TMP_PATH}"/gecko
create_new_dir "${PORT_WINE_TMP_PATH}"/mono

export PW_VULKAN_DIR="${PORT_WINE_TMP_PATH}/VULKAN"
create_new_dir "${PW_VULKAN_DIR}"

cd "${PORT_SCRIPTS_PATH}" || fatal "Scripts directory not found: ${PORT_SCRIPTS_PATH}"
# HACK: Avoid inheriting a system scripts cwd in pressure-vessel.
cd "${XDG_DATA_HOME:-$HOME}" || fatal "Data directory not found: ${XDG_DATA_HOME:-$HOME}"

[[ ! -f "$VKBASALT_CONFIG_FILE" ]] && cp -f "${PORT_CONF_PATH}/vkBasalt.conf" "$VKBASALT_CONFIG_FILE"
[[ ! -f "$DXVK_CONFIG_FILE" ]] && cp -f "${PORT_CONF_PATH}/dxvk.conf" "$DXVK_CONFIG_FILE"

export STEAM_SCRIPTS="${PORT_DATA_PATH}/steam_scripts"
create_new_dir "$STEAM_SCRIPTS"

export PW_PLUGINS_PATH="${PORT_WINE_TMP_PATH}/plugins${PW_PLUGINS_VER}"

export PW_WINELIB="${PORT_WINE_TMP_PATH}/libs${PW_LIBS_VER}"
try_remove_dir "${PW_WINELIB}/var"

export WINETRICKS_DOWNLOADER="curl"

check_user_conf

check_variables PW_LOG "0"
try_remove_file "${PW_TMPFS_PATH}/update_pfx_log"

[[ ! -f "$PORT_WINE_TMP_PATH/statistics" ]] && touch "$PORT_WINE_TMP_PATH/statistics"

if [[ -n "${STEAM_COMPAT_DATA_PATH:-}" ]]; then
    steamplay_launch "${@:2}"
    exit
fi
unset WINEPREFIX

# choose mirror
if [[ -z "$MIRROR" ]] \
&& [[ "$FULL_LN" == "russian" ]]
then
    echo 'export MIRROR="CLOUD"' >> "$USER_CONF"
    export MIRROR="CLOUD"
elif [[ -z "$MIRROR" ]] ; then
    echo 'export MIRROR="GITHUB"' >> "$USER_CONF"
    export MIRROR="GITHUB"
fi

if [[ $USE_ONLY_LG_RU == "1" ]] ; then
    export MIRROR="CLOUD"
    edit_user_conf_from_gui MIRROR USE_ONLY_LG_RU
    print_info "Force used linux-gaming.ru for all updates."
fi
print_info "The first mirror in used: $MIRROR"

if check_gamescope_session
then PW_TERM="env LANG=C python3 -m portprotonqt.scripts_utils.easyterm --fullscreen -e"
else PW_TERM="env LANG=C python3 -m portprotonqt.scripts_utils.easyterm -e"
fi

pw_cleanup () {
    CURL_PID="$(pgrep -a curl | grep -i "portproton" | cut -d' ' -f1)"
    if [[ -n $CURL_PID ]] ; then
        for pid in $CURL_PID ; do
            kill "$pid" &>/dev/null
        done
    fi

    rm -fv "${PW_TMPFS_PATH}"/*.log
}
trap "pw_cleanup" EXIT

pw_init_db

if [[ ! -d "${HOME}/PortProtonQt" ]] \
&& check_flatpak
then
    ln -s "${PORT_DATA_PATH}" "${HOME}/PortProtonQt"
fi

# shellcheck source=/dev/null
source "${USER_CONF}"

# TODO: ?
kill_portwine

### CLI ###
get_wine_and_pfx () {
    [[ -n $1 ]] && export PW_WINE_USE="$1"
    [[ -n $2 ]] && export PW_PREFIX_NAME="$2"
    # drop create_new_dir "${PATH_TO_VKD3D_FILES}/vkd3d_cache" and create_new_dir "${PATH_TO_DXVK_FILES}/dxvk_cache"
    unset PW_USE_SUPPLIED_DXVK_VKD3D
}

case "$1" in
    --help)
        help_info () {
            echo -e "Usage: [--repair] [--reinstall] [--autoinstall]

--repair                                            Forces all scripts to be updated to a working state
                                                    (helps if PortProton is not working)
--reinstall                                         Reinstalls PortProton and resets all settings to default
--debug                                             Debug scripts for PortProton
                                                    (saved log in) $PORT_DATA_PATH/scripts-debug.log)
--launch                                            Launches the application immediately, requires the path to the .exe file
--edit-db                                           After the variable, the path to the .exe file is required and then the variables.
                                                    (List their variables and values for example PW_MANGOHUD=1 PW_VKBASALT=0, etc.)
--get-user-conf                                     Get a value from user.conf file, requires variable name
--set-user-conf                                     Set a value in user.conf file, requires variable name and value
--del-user-conf                                     Delete a value from user.conf file, requires variable name
--list-db                                           List all available database variables
--show-ppdb                                         Show the content of .ppdb file for specified .exe file
--backup-prefix                                     Backup specified prefix to a file
--restore-prefix                                    Restore prefix from backup file
--winefile                                          Open wine file explorer, requires WINE version and prefix name
--winecfg                                           Open wine configuration, requires WINE version and prefix name
--winecmd                                           Open wine command prompt, requires WINE version and prefix name
--winereg                                           Open wine registry editor, requires WINE version and prefix name
--wine_uninstaller                                  Open wine uninstaller, requires WINE version and prefix name
--winetricks-list-all                               List winetricks DLLs, fonts, and settings
--winetricks-install                                Install winetricks items, requires WINE version and prefix name
--clear_pfx                                         Clear specified prefix, requires WINE version and prefix name
--mangohud-preview                                  Starts MangoHud preview in vkcube (optional argument: inline MangoHud config)
--initial                                           Initial setup command
--autoinstall                                       Runs the specified .ppai autoinstall script

Usage examples:
  portproton cli --launch /path/to/game.exe
  portproton cli --edit-db /path/to/game.exe PW_MANGOHUD=1 PW_VKBASALT=0
  portproton cli --get-user-conf PW_MANGOHUD
  portproton cli --set-user-conf PW_MANGOHUD 1
  portproton cli --del-user-conf PW_MANGOHUD
  portproton cli --backup-prefix DEFAULT /path/to/backup/directory
  portproton cli --restore-prefix /path/to/backup/file.ppack
  portproton cli --winecfg WINE_LG DEFAULT
  portproton cli --winetricks-list-all WINE_LG DEFAULT
  portproton cli --winetricks-install WINE_LG DEFAULT --no-force corefonts
  portproton cli --mangohud-preview \"fps,frametime,cpu_temp,gpu_temp\"
  portproton cli --autoinstall /path/to/script.ppai
            "
        }
        help_info
        exit 0
        ;;
    --reinstall)
        stop_portproton
        pw_clear_pfx
        try_remove_dir "${PORT_DATA_PATH}/data/dist"
        create_new_dir "${PORT_DATA_PATH}/data/dist"
        try_remove_dir "${PORT_WINE_TMP_PATH}/VULKAN"
        try_remove_dir "${PORT_WINE_TMP_PATH}/gecko"
        try_remove_dir "${PORT_WINE_TMP_PATH}/mono"
        #TODO: что там в QT если try_remove_file "${PORT_DATA_PATH}/data/user.conf"
        exit 0
        ;;
    --remove)
        rm -fr "${PORT_DATA_PATH}"
        rm -fr "${PORT_WINE_TMP_PATH}"
        rm -f "$(grep -il PortProton "${HOME}/.local/share/applications"/*.desktop)"
        update-desktop-database -q "${HOME}/.local/share/applications"
        exit 0
        ;;
    --autoinstall)
        export PW_USE_GAMEMODE=0
        export PW_CHECK_AUTOINSTALL=1
        export PW_NO_WRITE_WATCH=0
        export PW_VULKAN_USE=1
        export PW_USE_EAC_AND_BE=0
        export PW_USE_FSYNC=0
        export PW_USE_ESYNC=0
        unset PORTWINE_CREATE_SHORTCUT_NAME
        export PW_DISABLED_CREATE_DB=1
        export PW_MANGOHUD=0
        export PW_VKBASALT=0
        export PW_USE_D3D_EXTRAS=1
        export WINE_LARGE_ADDRESS_AWARE=0
        trap "stop_portproton" SIGTERM SIGINT
        if [[ "$2" =~ ^https?://.*\.ppai($|\?) ]] ; then
            autoinstall_script="${PORT_WINE_TMP_PATH}/$(basename "${2%%\?*}")"
            if try_download "$2" "${autoinstall_script}" no_mirror ; then
                # shellcheck source=/dev/null
                . "${autoinstall_script}"
                try_remove_file "${autoinstall_script}"
            else
                fatal "Not found autoinstal script: $2"
            fi
        elif [[ -f "$2" ]] ; then
            # shellcheck source=/dev/null
            . "${2}"
        else
            fatal "Not found autoinstal script: $2"
        fi
        stop_portproton
        ;;
    --debug)
        clear
        export PW_DEBUG="set -x"
        /usr/bin/env bash -c "${pw_full_command_line[@]}" 2>&1 | tee "$PORT_DATA_PATH/scripts-debug.log" &
        exit 0
        ;;
    --edit-db)
        # --edit-db /полный/путь/до/файла.exe PW_MANGOHUD=1 PW_VKBASALT=0 (и т.д) для примера
        set_several_variables "${@:3}"
        edit_db_from_gui $keys_all
        exit 0
        ;;
    --get-user-conf)
        # --get-user-conf VARIABLE_NAME
        manage_user_conf_value get "$2"
        exit 0
        ;;
    --set-user-conf)
        # --set-user-conf VARIABLE_NAME VALUE
        manage_user_conf_value set "$2" "$3"
        exit 0
        ;;
    --delete-user-conf)
        # --delete-user-conf VARIABLE_NAME
        manage_user_conf_value delete "$2"
        exit 0
        ;;
    --show-ppdb)
        # --show-ppdb /полный/путь/до/файла.(exe|bat|cmd|msi|reg) ИЛИ /полный/путь/до/файла.ext.ppdb
        input_path="$2"

        case "$input_path" in
            *.ppdb) exe_path="${input_path%.ppdb}" ;;
            *.[bB][aA][tT]|*.[cC][mM][dD]|*.[eE][xX][eE]|*.[mM][sS][iI]|*.[rR][eE][gG]) exe_path="$input_path" ;;
        esac

        ppdb_path="${exe_path}.ppdb"
        export PW_EXE_FILE="$exe_path"
        pw_init_db
        gui_edit_db
        pw_skip_get_info
        for var in "${PW_EDIT_DB_FINAL_LIST[@]}"; do
            if echo "$DISABLE_EDIT_DB_LIST" | grep -qw "$var"; then
                echo "$var blocked"
            else
                echo "$var"
            fi
        done

        declare -A all_vars
        while IFS='=' read -r key val; do
            key="${key#export }"
            val="${val#\"}"
            val="${val%\"}"
            all_vars["$key"]="$val"
        done < <(grep -E '^export ' "$ppdb_path" | sed -E 's/[[:space:]]*#.*$//' | sed '/^[[:space:]]*$/d')

        check_user_conf
        if [[ -f "$USER_CONF" ]]; then
            while IFS='=' read -r key val; do
                key="${key#export }"
                val="${val#\"}"
                val="${val%\"}"
                all_vars["$key"]="$val"
            done < <(grep -E '^export ' "$USER_CONF" 2>/dev/null | sed -E 's/[[:space:]]*#.*$//' | sed '/^[[:space:]]*$/d')
        fi

        [[ -n "${PW_DEFAULT_WINE_USE:-}" && -z "${all_vars[PW_WINE_USE]+x}" ]] && all_vars["PW_WINE_USE"]="$PW_DEFAULT_WINE_USE"
        [[ -n "${PW_DEFAULT_PREFIX_NAME:-}" && -z "${all_vars[PW_PREFIX_NAME]+x}" ]] && all_vars["PW_PREFIX_NAME"]="$PW_DEFAULT_PREFIX_NAME"
        [[ -n "${PW_DEFAULT_VULKAN_USE:-}" && -z "${all_vars[PW_VULKAN_USE]+x}" ]] && all_vars["PW_VULKAN_USE"]="$PW_DEFAULT_VULKAN_USE"
        all_vars["PW_PLUGINS_VER"]="$PW_PLUGINS_VER"

        while IFS='=' read -r key val; do
            key="${key#export }"
            val="${val#\"}"
            val="${val%\"}"
            if [[ -z "${all_vars[$key]+x}" ]]; then
                all_vars["$key"]="$val"
            fi
        done < <(
            {
                grep -E '^export ' "$PORT_SCRIPTS_PATH/var"
                grep -E '^check_variables ' "$PORT_SCRIPTS_PATH/var" | sed -E 's/^check_variables ([^[:space:]]+) (.*)$/export \1=\2/'
            } | sed -E 's/[[:space:]]*#.*$//' | sed '/^[[:space:]]*$/d'
        )

        for key in "${!all_vars[@]}"; do
            echo "${key}=\"${all_vars[$key]}\""
        done

        exit 0
        ;;
    --backup-prefix)
        # portproton --backup-prefix <PREFIX_NAME> <BACKUP_DIR>
        pw_create_prefix_backup_cli "$2" "$3"
        exit $?
        ;;
    --restore-prefix)
        # portproton --restore-prefix <PREFIX_BACKUP_FILE.ppack>
        pw_unpack_prefix "$2"
        exit $?
        ;;
    --winefile)
        get_wine_and_pfx "$2" "$3"
        start_portproton
        pw_run winefile
        stop_portproton
        ;;
    --winecfg)
        get_wine_and_pfx "$2" "$3"
        start_portproton
        export GST_PLUGIN_SYSTEM_PATH_1_0=""
        pw_run winecfg
        stop_portproton
        ;;
    --winecmd)
        get_wine_and_pfx "$2" "$3"
        start_portproton
        cd "${PORT_DATA_PATH}/data/prefixes/${PW_PREFIX_NAME}/drive_c" || fatal "Prefix drive_c directory not found"
        PW_USE_TERMINAL=1 pw_run cmd
        stop_portproton
        ;;
    --winereg)
        get_wine_and_pfx "$2" "$3"
        start_portproton
        export GST_PLUGIN_SYSTEM_PATH_1_0=""
        pw_run regedit
        stop_portproton
        ;;
    --wine_uninstaller)
        get_wine_and_pfx "$2" "$3"
        start_portproton
        pw_run uninstaller
        stop_portproton
        ;;
    --winetricks-list-all)
        get_wine_and_pfx "$2" "$3"
        update_winetricks >&2
        sh -n "${PORT_WINE_TMP_PATH}/winetricks" >&2 || exit 1
        awk '
            function save_entry() {
                if (category == "") {
                    return
                }
                count[category]++
                entries[category, count[category]] = name " " title
                category = ""
                name = ""
                title = ""
            }
            /^w_metadata[[:space:]]+/ {
                save_entry()
                if ($3 == "dlls" || $3 == "fonts" || $3 == "settings") {
                    name = $2
                    category = $3
                }
                next
            }
            category != "" && /^[[:space:]]*title="/ {
                title = $0
                sub(/^[[:space:]]*title="/, "", title)
                sub(/[[:space:]]*\\$/, "", title)
                sub(/"$/, "", title)
            }
            END {
                save_entry()
                split("dlls fonts settings", categories, " ")
                for (i = 1; i <= 3; i++) {
                    category = categories[i]
                    print "__PORTPROTONQT_WINETRICKS_SECTION__:" category
                    for (j = 1; j <= count[category]; j++) {
                        print entries[category, j]
                    }
                }
            }
        ' "${PORT_WINE_TMP_PATH}/winetricks"
        winetricks_status="$?"
        exit "$winetricks_status"
        ;;
    --winetricks-install)
        get_wine_and_pfx "$2" "$3"
        winetricks_force="$4"
        shift 4
        start_portproton
        update_winetricks
        winetricks_args=("--unattended")
        [[ "$winetricks_force" == "--force" ]] && winetricks_args+=("--force")
        "${PORT_WINE_TMP_PATH}/winetricks" "${winetricks_args[@]}" "$@"
        winetricks_status=$?
        wait_wineserver
        stop_portproton
        exit "$winetricks_status"
        ;;
    --clear_pfx)
        get_wine_and_pfx "$2" "$3"
        pw_clear_pfx
        exit $?
        ;;
    --mangohud-preview)
        pw_mangohud_preview "${2:-}"
        exit $?
        ;;
    --xterm)
        cd "$HOME" || :
        unset PW_SANDBOX_HOME_PATH
        pw_init_runtime
        ${pw_runtime} \
        LD_PRELOAD="${PW_LD_PRELOAD}" \
        VK_ADD_IMPLICIT_LAYER_PATH="${PW_VK_LAYER_PATH}" \
        VK_ADD_LAYER_PATH="${PW_VK_LAYER_PATH}" \
        VK_INSTANCE_LAYERS="${PW_VK_INSTANCE_LAYERS}" \
        ${PW_GAMEMODERUN_SLR} \
        ${PW_ADD_VAR_SLR} \
        ${PW_TERM}
        stop_portproton
        ;;
    --initial)
        exit 0
        ;;
    --launch)
        portwine_launch
        stop_portproton
        ;;
    --epic-wrapper)
        portwine_launch "${@:3}"
        stop_portproton
        ;;
    --stop)
        start_path="$(realpath "$0")"
        pgrep -f -- "${start_path}.*--autoinstall" | while read -r autoinstall_pid ; do
            if [[ "${autoinstall_pid}" != "$PW_START_PID" ]] ; then
                kill -s SIGTERM "${autoinstall_pid}" &>/dev/null
            fi
        done
        stop_portproton
        ;;
    *)
        if [[ -f "$PW_EXE_FILE" ]] ; then
            portwine_launch
            stop_portproton
        else
            fatal "File not found: $PW_EXE_FILE"
        fi
        ;;
esac

# portwine_start_debug ;;

#TODO: move to QT
# update_ext_ppdb
# find_ext_ppdb

stop_portproton
