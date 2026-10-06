%global pypi_name portprotonqt
%global pypi_version 1.4.1
%global oname PortProtonQt
%global build_timestamp %(date +"%Y%m%d")
%global _python_no_extras_requires 1

%global rel_build 1.git.%{build_timestamp}%{?dist}

Name:           %{pypi_name}-git
Version:        %{pypi_version}
Release:        %{rel_build}
Summary:        Game library manager and launcher for Linux (development build)

License:        GPL-3.0
URL:            https://git.linux-gaming.ru/Linux-Gaming/PortProtonQt
ExclusiveArch:  x86_64

BuildRequires:  meson >= 0.61.2
BuildRequires:  ninja-build
BuildRequires:  python3-devel
BuildRequires:  git
BuildRequires:  gettext
BuildRequires:  systemd-rpm-macros
BuildRequires:  vulkan-loader-devel
BuildRequires:  pkgconfig(sdl3)
BuildRequires:  gcc

Obsoletes:      python3-%{pypi_name}-git < %{version}-%{release}
Provides:       python3-%{pypi_name}-git = %{version}-%{release}

Requires:       python3-babel
Requires:       python3-evdev
Requires:       python3-websocket-client
Requires:       python3-orjson
Requires:       python3-psutil
Requires:       python3-pyside6
Requires:       python3-requests
Requires:       python3-tqdm
Requires:       python3-vdf
Requires:       python3-pefile
Requires:       python3-pillow
Requires:       python3-pillow-qt
Requires:       python3-rapidfuzz
Requires:       python3-libarchive-c
Requires:       perl-Image-ExifTool
Requires:       qt6-qtsvg
Requires:       qt6-qtimageformats
Requires:       qt6-qtmultimedia
Requires:       cabextract
Requires:       gzip
Requires:       unzip
Requires:       curl
Requires:       file
Requires:       findutils
Requires:       gawk
Requires:       grep
Requires:       tar
Requires:       xz
Requires:       zstd
Requires:       unrar
Requires:       glx-utils
Requires:       pciutils
Requires:       vulkan-loader
Requires:       procps-ng
Requires:       psmisc
Requires:       7zip
Requires:       python3-dbus-fast
Requires:       desktop-file-utils

# System Tab
Recommends:     NetworkManager
Recommends:     bluez
Recommends:     upower
Recommends:     pulseaudio-utils
Recommends:     python3-qrcode

# For legacy PortProton prefix backup support
Recommends:     squashfs-tools

Obsoletes:      %{pypi_name}-steam-compat < %{?epoch:%{epoch}:}%{version}-%{release}
Provides:       %{pypi_name}-steam-compat = %{?epoch:%{epoch}:}%{version}-%{release}

%description
An application for managing a game library and launching games on Linux. It brings games from different sources together in one place.

%{?python_disable_dependency_generator}

%prep
git clone https://git.linux-gaming.ru/Linux-Gaming/PortProtonQt.git

%build
cd %{oname}
%meson \
    -Dnightly=true \
    -Dpython_purelibdir=%{python3_sitelib} \
    -Dudev_rulesdir=%{_udevrulesdir}
%meson_build

%install
cd %{oname}
%meson_install
bash ./dev-scripts/generate-completions.sh
install -Dpm 0644 ./completions/portprotonqt -t %{buildroot}%{bash_completions_dir}
install -Dpm 0644 ./completions/portprotonqt.fish -t %{buildroot}%{fish_completions_dir}
install -Dpm 0644 ./completions/_portprotonqt -t %{buildroot}%{zsh_completions_dir}
%find_lang %{pypi_name}

%files -f %{oname}/%{pypi_name}.lang
%{_bindir}/%{pypi_name}
%{_bindir}/vk_gpu_info
%{python3_sitelib}/%{pypi_name}/
%{_datadir}/icons/hicolor/scalable/apps/ru.linux_gaming.PortProtonQt.svg
%{_metainfodir}/ru.linux_gaming.PortProtonQt.metainfo.xml
%{_udevrulesdir}/60-portprotonqt.rules
%{_sysusersdir}/portprotonqt.conf
%{_datadir}/polkit-1/rules.d/ru.linux_gaming.PortProtonQt.rules
%{_datadir}/applications/ru.linux_gaming.PortProtonQt.desktop
%{_datadir}/applications/ru.linux_gaming.PortProtonQt.log.desktop
%{_datadir}/applications/ru.linux_gaming.PortProtonQt.silent.desktop
%{_datadir}/mime/packages/ru.linux_gaming.PortProtonQt.xml
%{_datadir}/portproton/scripts/
%{_datadir}/portproton/conf/
%{bash_completions_dir}/portprotonqt
%{fish_completions_dir}/portprotonqt.fish
%{zsh_completions_dir}/_portprotonqt

%changelog
