# Install Python source files
install_data(
  ['__init__.py',
   'appimage_integration.py',
   'appimage_updater.py',
   'cli.py',
   'context_menu_manager.py',
   'custom_widgets.py',
   'dialogs.py',
   'disc_image_utils.py',
   'downloader.py',
  'compatibility_report.py',
  'game_card.py',
  'game_library_manager.py',
  'gog_api.py',
  'egs_api.py',
  'howlongtobeat_api.py',
  'image_utils.py',
  'icon_extractor.py',
  'keyboard_layouts.py',
  'localization.py',
  'logger.py',
  'main_window.py',
  'port_data_path_selector.py',
  'portproton_api.py',
  'preloader.py',
  'qt_utils.py',
  'search_utils.py',
   'settings_manager.py',
   'sound_manager.py',
   'theme_manager.py',
  'theme_security.py',
  'time_utils.py',
  'tray_manager.py',
  'version_utils.py',
  'virtual_keyboard.py'],
  install_dir: pythondir / meson.project_name(),
)

install_data(
  configure_file(
    input: 'app.py',
    output: 'app.py',
    configuration: version_conf,
  ),
  install_dir: pythondir / meson.project_name(),
)

install_data(
  'native_gamepad.py',
  install_dir: pythondir / meson.project_name(),
)

install_data(
  ['input_manager/__init__.py',
   'input_manager/buttons.py',
   'input_manager/constants.py',
   'input_manager/dialog_modes.py',
   'input_manager/dpad.py',
   'input_manager/file_explorer.py',
   'input_manager/keyboard.py',
   'input_manager/mixin.py',
   'input_manager/runtime.py',
   'input_manager/settings.py',
   'input_manager/settings_visual.py',
  ],
  install_dir: pythondir / meson.project_name() / 'input_manager',
)

shared_library(
  'portprotonqt_gamepad',
  gamepad_sources,
  dependencies: sdl3_dep,
  install: true,
  install_dir: pkgdatadir,
)

install_data(
  ['compatibility_rules.json',
   'keyboard_layouts.json',
  ],
  install_dir: pythondir / meson.project_name(),
)

# Install animations package
install_data(
  ['animations/__init__.py',
   'animations/detail_background.py',
   'animations/detail_page.py',
   'animations/game_card.py',
   'animations/library_controls.py',
   'animations/virtual_keyboard.py',
  ],
  install_dir: pythondir / meson.project_name() / 'animations',
)

# Install steam_api package
install_data(
  ['steam_api/__init__.py',
   'steam_api/utils.py',
   'steam_api/cache.py',
   'steam_api/api.py',
   'steam_api/shortcuts.py',
  ],
  install_dir: pythondir / meson.project_name() / 'steam_api',
)

# Install dialogs package
install_data(
  ['dialogs/__init__.py',
   'dialogs/appimage_update.py',
   'dialogs/base.py',
   'dialogs/dialog_utils.py',
   'dialogs/compatibility_report.py',
   'dialogs/file_explorer.py',
   'dialogs/winetricks_dialog.py',
   'dialogs/settings_dialog.py',
   'dialogs/settings_mangohud.py',
   'dialogs/settings_gamescope.py',
   'dialogs/settings_reshade.py',
   'dialogs/settings_vkbasalt.py',
   'dialogs/proton_manager.py',
   'dialogs/prefix_backup.py',
   'dialogs/wine_loader.py',
   'dialogs/wine_downloader.py',
   'dialogs/wine_extractor.py',
  ],
  install_dir: pythondir / meson.project_name() / 'dialogs',
)

# Install detail_pages package
install_data(
  ['detail_pages/__init__.py',
   'detail_pages/widgets.py',
   'detail_pages/utils.py',
  ],
  install_dir: pythondir / meson.project_name() / 'detail_pages',
)

# Install system_manager package
install_data(
  ['system_manager/__init__.py',
   'system_manager/audio.py',
   'system_manager/bluetooth.py',
   'system_manager/common.py',
   'system_manager/network.py',
   'system_manager/storage.py',
  ],
  install_dir: pythondir / meson.project_name() / 'system_manager',
)

# Install tabs package
install_data(
  ['tabs/__init__.py',
   'tabs/autoinstall_tab.py',
   'tabs/control_hints.py',
   'tabs/download_tab.py',
   'tabs/library_tab.py',
   'tabs/settings_tab.py',
   'tabs/system_tab.py',
   'tabs/theme_store.py',
   'tabs/theme_store_workers.py',
   'tabs/theme_tab.py',
   'tabs/wine_tab.py',
   'tabs/workers.py',
  ],
  install_dir: pythondir / meson.project_name() / 'tabs',
)

# Install debug_utils package
install_data(
  ['debug_utils/__init__.py',
   'debug_utils/debug_log_manager.py',
   'debug_utils/env_utils.py',
   'debug_utils/game_debug.py',
   'debug_utils/gpu_info.py',
   'debug_utils/log_processor.py',
   'debug_utils/system_info.py',
   'debug_utils/xorg_utils.py',
  ],
  install_dir: pythondir / meson.project_name() / 'debug_utils',
)

# Install scripts_utils package
install_data(
  ['scripts_utils/__init__.py',
   'scripts_utils/dbus_tools.py',
   'scripts_utils/easyterm.py',
   'scripts_utils/graphics_detector.py',
   'scripts_utils/idle_inhibit.py',
   'scripts_utils/json_tools.py',
   'scripts_utils/mount_points.py',
   'scripts_utils/prefix_backup.py',
   'scripts_utils/power_profiles.py',
   'scripts_utils/shortcut_tools.py',
  ],
  install_dir: pythondir / meson.project_name() / 'scripts_utils',
)

# Install config package
install_data(
  ['config/__init__.py',
   'config/base.py',
   'config/ui.py',
   'config/game.py',
   'config/cache.py',
   'config/gamepad.py',
   'config/proxy.py',
   'config/display.py',
   'config/window.py',
   'config/favorites.py',
   'config/portproton.py',
   'config/validators.py',
  ],
  install_dir: pythondir / meson.project_name() / 'config',
)

# Install themes
install_subdir(
  'themes',
  install_dir: pythondir / meson.project_name(),
  exclude_directories: ['__pycache__'],
  exclude_files: ['*.pyc'],
)

# Install terminal schemes
install_subdir(
  'terminal_schemes',
  install_dir: pythondir / meson.project_name(),
)

# Compile and install locales from .po files
msgfmt = find_program('msgfmt', required: true)
foreach lang : ['be', 'de', 'ru', 'es', 'pt_BR', 'zh_CN']
  mo_target = configure_file(
    input: 'locales' / lang / 'LC_MESSAGES' / 'portprotonqt.po',
    output: lang + '_portprotonqt.mo',
    command: [msgfmt, '@INPUT@', '-o', '@OUTPUT@'],
  )
  install_data(
    mo_target,
    rename: 'portprotonqt.mo',
    install_dir: get_option('localedir') / lang / 'LC_MESSAGES',
    install_tag: 'i18n'
  )
endforeach
