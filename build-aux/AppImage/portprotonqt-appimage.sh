#!/bin/sh

set -eu

ARCH="$(uname -m)"
VERSION="$(cat ~/version)"
export ARCH VERSION
export OUTPATH=./dist
export DESKTOP=/usr/share/applications/ru.linux_gaming.PortProtonQt.desktop
export ICON=/usr/share/icons/hicolor/scalable/apps/ru.linux_gaming.PortProtonQt.svg
export OUTNAME=PortProtonQt-"$VERSION"-anylinux-"$ARCH".AppImage
export UPINFO="gitea-releases-zsync|git.linux-gaming.ru|Linux-Gaming|PortProtonQt|latest|*$ARCH.AppImage.zsync"
export DEPLOY_OPENGL=1
export DEPLOY_SDL=1
export DEPLOY_PYTHON=1
export MAIN_BIN=portprotonqt
export OPTIMIZE_LAUNCH=1

# Adjust comp settings to bypass oom-killer
export DWARFS_COMP="zstd:level=15 -S22 -B5"

# Add udev rules
mkdir -p ./AppDir/etc/udev/rules.d
cp /usr/lib/udev/rules.d/60-portprotonqt.rules ./AppDir/etc/udev/rules.d

# Add PortProton scripts
# Copy manually to avoid tracing 208 .ppdb files with quick-sharun
mkdir -p ./AppDir/share
cp -r /usr/share/portproton ./AppDir/share

# QSoundEffect only needs PCM WAV and PulseAudio. Remove the optional native
# PipeWire path and FFmpeg media backend before quick-sharun scans Qt plugins.
pacman -Rdd --noconfirm libpipewire qt6-multimedia-ffmpeg

# Deploy dependencies
# Qt libs have to be passed manually due to the app being a python script
GAMEPAD_LIBRARY=$(find /usr/lib -type f \
	-path '*/site-packages/portprotonqt/libportprotonqt_gamepad.so' \
	-print -quit)
test -n "$GAMEPAD_LIBRARY"
quick-sharun \
	/usr/bin/portprotonqt* \
	/usr/bin/bash \
	/usr/bin/update-desktop-database \
	/usr/bin/update-mime-database \
	/usr/bin/vk_gpu_info \
	"$GAMEPAD_LIBRARY" \
	/usr/lib/libQt6Core.so* \
	/usr/lib/libQt6Gui.so* \
	/usr/lib/libQt6Multimedia.so* \
	/usr/lib/libQt6Network.so* \
	/usr/lib/qt6/plugins/imageformats/libqwebp.so \
	/usr/lib/7zip/7z*

# quick-sharun removes MIME package XML files during dependency deployment
mkdir -p ./AppDir/share/mime/packages
cp /usr/share/mime/packages/ru.linux_gaming.PortProtonQt.xml \
	./AppDir/share/mime/packages

# DEPLOY_PYTHON copies the distro's complete Python installation. Remove
# build/development content and PySide bindings not imported by PortProtonQt.
PYTHON_DIR=$(find ./AppDir/lib -maxdepth 1 -type d -name 'python3.*' -print -quit)
PYTHON_SITE=$PYTHON_DIR/site-packages
PYSIDE_DIR=$PYTHON_SITE/PySide6

rm -rf \
	"$PYTHON_DIR"/ensurepip \
	"$PYTHON_DIR"/idlelib \
	"$PYTHON_DIR"/pydoc_data \
	"$PYTHON_DIR"/tkinter \
	"$PYTHON_DIR"/turtledemo \
	"$PYTHON_DIR"/venv \
	"$PYTHON_SITE"/Cython \
	"$PYTHON_SITE"/cython.py \
	"$PYTHON_SITE"/mesonbuild \
	"$PYTHON_SITE"/pygments \
	"$PYTHON_SITE"/pyximport \
	"$PYTHON_SITE"/setuptools \
	"$PYTHON_SITE"/vapoursynth \
	"$PYTHON_SITE"/wheel \
	"$PYTHON_SITE"/cython-*.dist-info \
	"$PYTHON_SITE"/meson-*.dist-info \
	"$PYTHON_SITE"/pygments-*.dist-info \
	"$PYTHON_SITE"/setuptools-*.dist-info \
	"$PYTHON_SITE"/vapoursynth-*.dist-info \
	"$PYTHON_SITE"/wheel-*.dist-info

find "$PYTHON_DIR" -depth -type d \( -name test -o -name tests \) \
	-exec rm -rf {} +
find "$PYTHON_SITE" -type f -name '*.pyi' -delete

for module in "$PYSIDE_DIR"/Qt*.so; do
	case "${module##*/}" in
		QtCore.*|QtGui.*|QtMultimedia.*|QtNetwork.*|QtSvg.*|QtWidgets.*) continue ;;
	esac
	rm -f "$module"
done
rm -rf "$PYSIDE_DIR"/QtAsyncio

# Turn AppDir into AppImage
quick-sharun --make-appimage
