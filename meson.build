project('portprotonqt', 'c',
  version: '1.4.1',
  meson_version: '>= 0.61.2',
  license: 'GPL-3.0',
)


# Python installation
python3 = import('python').find_installation('python3')

# Configuration
conf = configuration_data()
conf.set('PYTHON', python3.full_path())

version_conf = configuration_data()
version_conf.set('APP_VERSION', meson.project_version())
version_conf.set('APP_COMMIT', '')

if get_option('nightly')
  git = find_program('git', required: false)
  if git.found()
    git_commit = run_command(git, 'rev-parse', '--short', 'HEAD', check: false)
    if git_commit.returncode() == 0
      version_conf.set('APP_COMMIT', git_commit.stdout().strip())
    endif
  endif
endif

# Directories
prefix = get_option('prefix')
datadir = prefix / get_option('datadir')
bindir = prefix / get_option('bindir')

# Use custom purelibdir if specified, otherwise use default
purelibdir_opt = get_option('python_purelibdir')
pythondir = purelibdir_opt != '' ? purelibdir_opt: python3.get_install_dir(pure: true)
pkgdatadir = pythondir / meson.project_name()

# Native C build dependencies and sources
gui_enabled = get_option('gui')
if gui_enabled
  cc = meson.get_compiler('c')
  sdl3_dep = dependency('sdl3', required: true)
  gamepad_sources = files('build-aux/src/gamepad_backend.c')
endif

subdir('portproton')

server_bundle_dependencies = files(
  'portproton/__init__.py',
  'portproton/library.py',
  'portproton/operations.py',
  'portproton/server.py',
  'build-aux/share/portproton/scripts/start.sh',
  'build-aux/share/portproton/scripts/functions_helper',
  'build-aux/share/portproton/scripts/var',
)

# Install Python package
if gui_enabled
  subdir('portprotonqt')
endif

configured_portproton_server = configure_file(
  input: 'build-aux/portproton-server',
  output: 'portproton-server-script',
  configuration: conf,
)

install_data(configured_portproton_server,
  install_dir: bindir,
  install_mode: 'rwxr-xr-x',
  rename: 'portproton-server',
  install_tag: 'headless',
)

server_service_conf = configuration_data()
server_service_conf.set('SERVER_EXEC', bindir / 'portproton-server')
configured_dbus_service = configure_file(
  input: 'build-aux/share/dbus-1/services/ru.linux_gaming.PortProton1.service.in',
  output: 'ru.linux_gaming.PortProton1.service',
  configuration: server_service_conf,
)
install_data(configured_dbus_service,
  install_dir: datadir / 'dbus-1' / 'services',
  install_tag: 'headless',
)
install_data(
  'build-aux/share/dbus-1/interfaces/ru.linux_gaming.PortProton1.xml',
  install_dir: datadir / 'dbus-1' / 'interfaces',
  install_tag: 'headless',
)

# Install entry point script
if gui_enabled
configured_portprotonqt = configure_file(
  input: 'build-aux/portprotonqt',
  output: 'portprotonqt-script',
  configuration: conf,
)

install_data(configured_portprotonqt,
  install_dir: bindir,
  install_mode: 'rwxr-xr-x',
  rename: 'portprotonqt',
)

# Build and install vk_gpu_info executable
vk_gpu_info_sources = files('build-aux/src/vk_gpu_info.c')
vk_gpu_info_deps = [dependency('vulkan', required: true)]

executable('vk_gpu_info',
  sources: vk_gpu_info_sources,
  dependencies: vk_gpu_info_deps,
  install: true,
  install_dir: bindir,
  c_args: ['-std=c99'],
)

# Install desktop file
install_data(
  'build-aux/share/applications/ru.linux_gaming.PortProtonQt.desktop',
  install_dir: datadir / 'applications',
)

install_data(
  'build-aux/share/applications/ru.linux_gaming.PortProtonQt.log.desktop',
  'build-aux/share/applications/ru.linux_gaming.PortProtonQt.silent.desktop',
  install_dir: datadir / 'applications',
)

# Install MIME type
install_data(
  'build-aux/share/mime/packages/ru.linux_gaming.PortProtonQt.xml',
  install_dir: datadir / 'mime/packages',
)

# Install icon
install_data(
  'build-aux/share/icons/hicolor/scalable/apps/ru.linux_gaming.PortProtonQt.svg',
  install_dir: datadir / 'icons/hicolor/scalable/apps',
)

# Install metainfo
install_data(
  'build-aux/share/metainfo/ru.linux_gaming.PortProtonQt.metainfo.xml',
  install_dir: datadir / 'metainfo',
)

# Install PortProton scripts
install_subdir(
  'build-aux/share/portproton/scripts',
  install_dir: datadir / 'portproton',
  install_mode: 'rwxr-xr-x',
)

install_subdir(
  'build-aux/share/portproton/conf',
  install_dir: datadir / 'portproton',
)

install_subdir(
  'build-aux/share/portproton/scripts/portwine_db',
  install_dir: datadir / 'portproton' / 'scripts',
  install_mode: 'rwxr-xr-x',
)

# Install udev rules
udev_rulesdir_opt = get_option('udev_rulesdir')
udevdir = udev_rulesdir_opt != '' ? udev_rulesdir_opt: prefix / 'lib' / 'udev' / 'rules.d'

install_data(
  'build-aux/lib/udev/rules.d/60-portprotonqt.rules',
  install_dir: udevdir,
)

# Install polkit rules
install_data(
  'build-aux/share/polkit-1/rules.d/ru.linux_gaming.PortProtonQt.rules',
  install_dir: prefix / 'share' / 'polkit-1' / 'rules.d',
)

install_data(
  'build-aux/lib/sysusers.d/portprotonqt.conf',
  install_dir: prefix / 'lib' / 'sysusers.d',
)
endif
