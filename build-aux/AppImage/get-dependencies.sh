#!/bin/sh

set -eu

# Initialize variables
LOCAL_MODE=false
BRANCH="main"
USE_BRANCH=false
TAG=""
REPO_URL="https://git.linux-gaming.ru/Linux-Gaming/PortProtonQt.git"

# Parse arguments
while [ $# -gt 0 ]; do
    case "$1" in
        --local|-l)
            LOCAL_MODE=true
            ;;
        --branch)
            if [ -n "${2:-}" ] && [ "${2#-}" = "$2" ]; then
                BRANCH="$2"
                USE_BRANCH=true
                shift
            else
                echo "Error: --branch requires an argument"
                exit 1
            fi
            ;;
        --tag)
            if [ -n "${2:-}" ] && [ "${2#-}" = "$2" ]; then
                TAG="$2"
                shift
            else
                echo "Error: --tag requires an argument"
                exit 1
            fi
            ;;
        --repo)
            if [ -n "${2:-}" ] && [ "${2#-}" = "$2" ]; then
                REPO_URL="$2"
                shift
            else
                echo "Error: --repo requires an argument"
                exit 1
            fi
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
    shift
done

ARCH="$(uname -m)"

if [ "$LOCAL_MODE" = true ]; then
    echo "Using local PKGBUILD-git from repository..."
    PPQT_PKGBUILD=""
elif [ -n "$TAG" ]; then
    echo "Using stable version of PortProtonQt from $TAG tag..."
    PPQT_PKGBUILD="https://git.linux-gaming.ru/Linux-Gaming/PortProtonQt/raw/tag/$TAG/build-aux/PKGBUILD"
else
    echo "Using stable version of PortProtonQt from $BRANCH branch..."
    PPQT_PKGBUILD="https://git.linux-gaming.ru/Linux-Gaming/PortProtonQt/raw/branch/$BRANCH/build-aux/PKGBUILD"
fi

echo "Tweak makepkg..."
echo "---------------------------------------------------------------"
# Disable creating debug packages
sed -i 's/OPTIONS=(.*)/OPTIONS=(strip docs !libtool !staticlibs emptydirs zipman purge lto)/g' /etc/makepkg.conf
# Setup packager name
sed -i 's/#PACKAGER=".*"/PACKAGER="Linux Gaming Team"/g' /etc/makepkg.conf
# Use all threads for building
sed -i 's/#MAKEFLAGS="-j2"/MAKEFLAGS="-j$(nproc) -l$(nproc)"/g' /etc/makepkg.conf
# makepkg cannot not as root by default
sed -i -e 's|EUID == 0|EUID == 69|g' /usr/bin/makepkg
# always disable this nonsense that was recently added to makepkg
sed -i -e 's/(( ${#arch\[@\]} != $(printf "%s\\n" ${arch\[@\]} | sort -u | wc -l) ))/false/' /usr/share/makepkg/lint_pkgbuild/arch.sh 2>/dev/null || :

echo "Tweak pacman..."
echo "---------------------------------------------------------------"
pacman-key --init
pacman -S --noconfirm archlinux-keyring

# Disable locale noextract
sed -i -E 's@[[:space:]]*usr/share/locale/\*@@g; s@[[:space:]]+@ @g; s@[[:space:]]+$@@' /etc/pacman.conf

pacman -Syyu --noconfirm --disable-download-timeout

echo "Building PortProtonQt from PKGBUILD..."
echo "---------------------------------------------------------------"
if [ "$LOCAL_MODE" = true ]; then
    cp ../PKGBUILD-git ./PKGBUILD
else
    wget --retry-connrefused --tries=30 "$PPQT_PKGBUILD" -O ./PKGBUILD
fi
if [ "$USE_BRANCH" = true ]; then
    sed -i "s|^source=.*|source=(\"git+${REPO_URL}#branch=$BRANCH\")|" PKGBUILD
elif [ -n "$TAG" ]; then
    sed -i "s|^source=.*|source=(\"git+${REPO_URL}#tag=$TAG\")|" PKGBUILD
fi
makepkg -si --noconfirm

echo "Installing debloated packages..."
echo "---------------------------------------------------------------"
get-debloated-pkgs --add-common --prefer-nano

if [ "$LOCAL_MODE" = true ]; then
    # For git version, we use portprotonqt-git
    pacman -Q portprotonqt-git | awk '{print $2}' | cut -d- -f1 > ~/version
else
    # For stable version, we use portprotonqt
    pacman -Q portprotonqt | awk '{print $2}' | cut -d- -f1 > ~/version
fi
