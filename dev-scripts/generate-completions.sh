#!/usr/bin/env bash
# Generate shell completion files for bash, zsh, and fish
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="$PROJECT_ROOT/completions"

mkdir -p "$OUTPUT_DIR"

# Bash completion
cat > "$OUTPUT_DIR/portprotonqt" << 'EOF'
_portprotonqt_completions() {
    local cur prev opts long_opts flags
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    # All available options
    opts="--fullscreen --resolution --debug-level --add-steam-compat-tool --reinstall-steam-compat-tool --remove-steam-compat-tool --clear-cache --reset-settings --ppqtos --silent --log --restore-prefix --create-backup --help -h"
    long_opts="--fullscreen --resolution --debug-level --add-steam-compat-tool --reinstall-steam-compat-tool --remove-steam-compat-tool --clear-cache --reset-settings --ppqtos --silent --log --restore-prefix --create-backup --help"
    
    # Values for options with arguments
    local debug_levels="ALL DEBUG INFO WARNING ERROR CRITICAL"
    local resolutions="1920x1080 1280x720 2560x1440 3840x2160"

    # Handle option arguments
    case "${prev}" in
        --debug-level)
            COMPREPLY=( $(compgen -W "${debug_levels}" -- "${cur}") )
            return 0
            ;;
        --resolution)
            COMPREPLY=( $(compgen -W "${resolutions}" -- "${cur}") )
            return 0
            ;;
        --restore-prefix)
            COMPREPLY=( $(compgen -f -X '!*.ppack' -- "${cur}") )
            return 0
            ;;
    esac

    # At command start, complete only long options to allow "--" prefix completion
    if [[ -z "${cur}" ]]; then
        COMPREPLY=( $(compgen -W "${long_opts}" -- "${cur}") )
        return 0
    fi

    # Complete flags when option prefix is used
    if [[ "${cur}" == -* ]]; then
        COMPREPLY=( $(compgen -W "${opts}" -- "${cur}") )
        return 0
    fi

    return 0
}

complete -F _portprotonqt_completions portprotonqt
EOF

# Zsh completion
cat > "$OUTPUT_DIR/_portprotonqt" << 'EOF'
#compdef portprotonqt

_portprotonqt() {
    local -a opts

    opts=(
        '--fullscreen[Launch in fullscreen mode]'
        '--resolution[Launch with specific resolution]:WIDTHxHEIGHT:(1920x1080 1280x720 2560x1440 3840x2160)'
        '--debug-level[Set logging level]:LEVEL:(ALL DEBUG INFO WARNING ERROR CRITICAL)'
        '--add-steam-compat-tool[Add as Steam compatibility tool]'
        '--reinstall-steam-compat-tool[Reinstall Steam compatibility tool]'
        '--remove-steam-compat-tool[Remove Steam compatibility tool]'
        '--clear-cache[Clear PortProtonQt cache and exit]'
        '--reset-settings[Reset PortProtonQt settings and exit]'
        '--ppqtos[Show the system tab]'
        '--silent[Launch .exe file without GUI]'
        '--log[Enable PortProton logging]'
        '--restore-prefix[Restore prefix from .ppack backup]:PPACK file:_files -g "*.ppack"'
        '--create-backup[Create prefix backup]:PREFIX: :BACKUP_DIR:_files -/'
        '(-h --help)'{-h,--help}'[Show help message]'
    )

    _arguments -s "${opts[@]}" && return 0
    _files -g "*.(exe|ppack)"
}

EOF

# Fish completion
cat > "$OUTPUT_DIR/portprotonqt.fish" << 'EOF'
# Fish completion for portprotonqt

complete -c portprotonqt -f
complete -c portprotonqt -n "test -z (commandline -ct)" -a "--fullscreen --resolution --debug-level --add-steam-compat-tool --reinstall-steam-compat-tool --remove-steam-compat-tool --clear-cache --reset-settings --ppqtos --silent --log --restore-prefix --create-backup --help"
complete -c portprotonqt -l fullscreen -d "Launch in fullscreen mode"
complete -c portprotonqt -l resolution -d "Launch with specific resolution" -r -f -a "1920x1080 1280x720 2560x1440 3840x2160"
complete -c portprotonqt -l debug-level -d "Set logging level" -r -f -a "ALL DEBUG INFO WARNING ERROR CRITICAL"
complete -c portprotonqt -l add-steam-compat-tool -d "Add as Steam compatibility tool"
complete -c portprotonqt -l reinstall-steam-compat-tool -d "Reinstall Steam compatibility tool"
complete -c portprotonqt -l remove-steam-compat-tool -d "Remove Steam compatibility tool"
complete -c portprotonqt -l clear-cache -d "Clear PortProtonQt cache and exit"
complete -c portprotonqt -l reset-settings -d "Reset PortProtonQt settings and exit"
complete -c portprotonqt -l ppqtos -d "Show the system tab"
complete -c portprotonqt -l silent -d "Launch .exe file without GUI"
complete -c portprotonqt -l log -d "Enable PortProton logging"
complete -c portprotonqt -l restore-prefix -d "Restore prefix from .ppack backup" -r -a "(__fish_complete_suffix .ppack)"
complete -c portprotonqt -l create-backup -d "Create prefix backup" -r
complete -c portprotonqt -s h -l help -d "Show help message"
complete -c portprotonqt -n "test -n (commandline -ct)" -a "(__fish_complete_suffix .exe) (__fish_complete_suffix .ppack)" -d "Executable file or URL"
EOF

echo "Generated completions in $OUTPUT_DIR"

PKGDIR="${PKGDIR:-${DESTDIR:-}}"
if [[ -n "$PKGDIR" ]]; then
    # Shell completions
    install -d "$PKGDIR/usr/share/bash-completion/completions"
    install -d "$PKGDIR/usr/share/zsh/site-functions"
    install -d "$PKGDIR/usr/share/fish/vendor_completions.d"

    install -m 644 "$OUTPUT_DIR/portprotonqt.bash" \
        "$PKGDIR/usr/share/bash-completion/completions/portprotonqt" || :
    install -m 644 "$OUTPUT_DIR/_portprotonqt" \
        "$PKGDIR/usr/share/zsh/site-functions/_portprotonqt" || :
    install -m 644 "$OUTPUT_DIR/portprotonqt.fish" \
        "$PKGDIR/usr/share/fish/vendor_completions.d/portprotonqt.fish" || :

    echo "Installed completions into $PKGDIR"
fi
