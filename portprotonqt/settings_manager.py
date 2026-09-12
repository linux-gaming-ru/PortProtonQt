import os
import shutil
import subprocess
from pathlib import Path

from portprotonqt.logger import get_logger
from portprotonqt.version_utils import include_pinned_prefixes
from portprotonqt.version_utils import version_sort_key

logger = get_logger(__name__)
LG_WINE_ALIASES = (
    ("PROTON_LG", "PW_PROTON_LG_VER"),
    ("WINE_LG", "PW_WINE_LG_VER"),
)


def read_lg_dist_versions_from_var(var_path: str) -> dict[str, str]:
    """Read Proton/Wine LG dist versions from scripts/var."""
    if not os.path.exists(var_path):
        return {}

    versions: dict[str, str] = {}
    try:
        with open(var_path, encoding="utf-8") as var_file:
            for line in var_file:
                line_stripped = line.strip()
                for wine_alias, version_key in LG_WINE_ALIASES:
                    prefix = f"export {version_key}="
                    if line_stripped.startswith(prefix):
                        value = line_stripped[len(prefix):].strip().strip('"\'')
                        if value:
                            versions[wine_alias] = value
    except OSError as exc:
        logger.warning("Failed to read LG versions from %s: %s", var_path, exc)

    return versions


def resolve_lg_wine_alias(wine_version: str, env_vars: dict[str, str]) -> str:
    for wine_alias, version_key in LG_WINE_ALIASES:
        if wine_version == wine_alias:
            return env_vars.get(version_key, wine_version)

    return wine_version


def get_available_wine_options(
    portproton_path: str,
    system_wine_label: str = "",
    steam_only: bool = False,
    include_lg_aliases: bool = False
) -> list[str]:
    dist_dir = os.path.join(portproton_path, "data", "dist")
    options = []
    if os.path.exists(dist_dir):
        options = sorted(
            [f for f in os.listdir(dist_dir) if os.path.isdir(os.path.join(dist_dir, f))],
            key=version_sort_key
        )

    from portprotonqt.config import get_portproton_scripts_path
    scripts_path = get_portproton_scripts_path()
    if scripts_path:
        var_path = os.path.join(scripts_path, "var")
        for wine_alias, version in read_lg_dist_versions_from_var(var_path).items():
            if include_lg_aliases and wine_alias not in options:
                options.append(wine_alias)
            if version not in options:
                options.append(version)

    from portprotonqt.steam_api import get_steam_proton_versions
    from portprotonqt.steam_api.utils import _is_steam_proton_dir
    for version in get_steam_proton_versions():
        if version not in options:
            options.append(version)

    if steam_only:
        options = [
            version for version in options
            if _is_steam_proton_dir(
                Path(version) if os.path.isabs(version) else Path(dist_dir, version)
            )
        ]
    elif system_wine_label and shutil.which('wine') and system_wine_label not in options:
        options.append(system_wine_label)

    options.sort(key=version_sort_key)
    return options


def get_available_prefix_options(portproton_path: str) -> list[str]:
    prefixes_dir = os.path.join(portproton_path, "data", "prefixes")
    prefixes = []
    if os.path.exists(prefixes_dir):
        prefixes = [
            name for name in os.listdir(prefixes_dir)
            if os.path.isdir(os.path.join(prefixes_dir, name))
        ]
    return include_pinned_prefixes(prefixes)


def get_available_locale_options() -> list[str]:
    """Get locale options based on locales available in the system."""
    target_locales = ("ru_RU", "en_US", "zh_CN", "ja_JP", "ko_KR")
    try:
        result = subprocess.run(
            ["locale", "-a"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            return []
    except (subprocess.TimeoutExpired, OSError):
        return []

    installed = {line.strip().lower() for line in result.stdout.splitlines() if line.strip()}
    selected = []
    for base in target_locales:
        variants = (
            f"{base}.utf8".lower(),
            f"{base}.utf-8".lower(),
            f"{base}.utf".lower(),
        )
        if any(variant in installed for variant in variants):
            selected.append(f"{base}.utf8")
    return selected


def get_available_logical_core_options() -> list[str]:
    """Get logical core options based on available CPU cores in the system."""
    logical_cores = os.cpu_count() or 1
    if logical_cores <= 4:
        return [str(core) for core in range(1, logical_cores)]

    options = ["1", "2"]
    options.extend(str(core) for core in range(4, logical_cores, 4))
    return options


def get_toggle_settings():
    """Get predefined toggle settings with descriptions."""
    from portprotonqt.localization import _

    return {
        # Graphics enhancements
        'PW_DGVOODOO2': _("Enable dgVoodoo2. Forced use all dgVoodoo2 libs (Glide 2.11-3.1, DirectDraw 1-7, Direct3D 2-9) on all 3D API."),
        'PW_USE_SPECIALK': _("Enable SpecialK (injection library for fixing graphics, latency and more)"),
        # Upscalers and Frame Generation
        'PW_USE_OPTISCALER': _("Enable OptiScaler (replacement upscaler / frame generator)"),
        'PW_USE_RESHADE': _("Enable ReShade post-processing"),
        'PW_USE_LS_FRAME_GEN': _("Enable Lossless Scaling frame generation (experimental)"),
        'PW_WINE_FULLSCREEN_FSR': _("FSR upscaling in fullscreen with ProtonGE below native resolution"),
        # Ray Tracing
        'PW_USE_RAY_TRACING': _("Enable vkd3d support - Ray Tracing"),
        # NVIDIA
        'PW_USE_NVAPI_AND_DLSS': _("Enable DLSS on supported NVIDIA graphics cards"),
        'PW_HIDE_NVIDIA_GPU': _("Disguise all NVIDIA GPU features"),
        # Synchronization
        'PW_USE_ESYNC': _("Enable in-process synchronization primitives based on eventfd."),
        'PW_USE_FSYNC': _("Enable futex-based in-process synchronization primitives."),
        'PW_USE_NTSYNC': _("Enable in-process synchronization via the Linux ntsync driver."),
        # DirectX / Graphics
        'PW_USE_D3D_EXTRAS': _("Enable forced use of third-party DirectX libraries"),
        'PW_USE_D7VK': _("Enable D7VK for DirectDraw 1-7"),
        'PW_USE_WINE_DXGI': _("Force use of built-in DXGI library"),
        # Performance
        'PW_USE_GAMEMODE': _("Use system GameMode for performance optimization"),
        'PW_DISABLE_COMPOSITING': _("Disable desktop compositing for performance"),
        # Video / Audio fixes
        'PW_FIX_VIDEO_IN_GAME': _("Fix pink-tinted video playback in some games"),
        'PW_REDUCE_PULSE_LATENCY': _("Reduce PulseAudio latency to fix intermittent sound"),
        # Launch options
        'PW_VIRTUAL_DESKTOP': _("Run the application in WINE virtual desktop"),
        'PW_USE_TERMINAL': _("Run the application in a terminal"),
        # Input / Locale
        'PW_USE_US_LAYOUT': _("Force US keyboard layout"),
        'PW_DINPUT_PROTOCOL': _("Force DirectInput protocol instead of XInput"),
        # Media
        'PW_USE_GSTREAMER': _("Use GStreamer for in-game clips (WMF support)"),
        # Shader caching
        'PW_USE_SHADER_CACHE': _("Use WINE shader caching"),
        # Anti-cheat
        'PW_USE_EAC_AND_BE': _("Enable Easy Anti-Cheat and BattlEye runtimes"),
        # Vulkan layers
        'PW_USE_SYSTEM_VK_LAYERS': _("Use system Vulkan layers (MangoHud, vkBasalt, OBS, etc.)"),
        'PW_USE_OBS_VKCAPTURE': _("Enable OBS Studio capture via obs-vkcapture"),
        # Wayland
        'PW_USE_NATIVE_WAYLAND': _("Enable experimental native Wayland support"),
        'PW_USE_DXVK_HDR': _("Enable HDR settings under native Wayland"),
        # Gallium
        'PW_USE_GALLIUM_ZINK': _("Use Gallium Zink (OpenGL via Vulkan)"),
        'PW_USE_GALLIUM_NINE': _("Use Gallium Nine (native DirectX 9 for Mesa)"),
        'PW_USE_WINED3D_VULKAN': _("Use WineD3D Vulkan backend (Damavand)"),
        # Proton
        'PW_USE_SUPPLIED_DXVK_VKD3D': _("Use bundled dxvk/vkd3d from Wine/Proton"),
        # Power management
        'PW_USE_INHIBIT_SLEEP': _("Prevent the system from going to sleep and disable the screensaver while the game is running"),
        # Runtime
        'PW_USE_RUNTIME': _("Use container launch mode (recommended default)"),
    }


def get_advanced_settings(disabled_text, logical_core_options=None, locale_options=None,
                          numa_nodes=None, dist_options=None, prefix_options=None):
    """Get advanced settings configuration."""
    from portprotonqt.localization import _

    advanced_settings = []
    if dist_options is None:
        dist_options = []
    if prefix_options is None:
        prefix_options = []
    if numa_nodes is None:
        numa_nodes = {}
    if not logical_core_options:
        logical_core_options = get_available_logical_core_options()
    if locale_options is None:
        locale_options = get_available_locale_options()

    # 1. Wine Version
    wine_options = []
    wine_value_map = {}
    for option in dist_options:
        if os.path.isabs(option):
            display_name = os.path.basename(option.rstrip(os.sep)) or option
            if display_name in wine_options:
                display_name = option
            wine_value_map[display_name] = option
            wine_options.append(display_name)
        else:
            wine_options.append(option)

    wine_setting = {
        'key': 'PW_WINE_USE',
        'name': _("Wine Version"),
        'description': _("Select the Wine or Proton version to use for this executable."),
        'type': 'combo',
        'options': wine_options,
        'default': ''
    }
    if wine_value_map:
        wine_setting['_value_map'] = wine_value_map
    advanced_settings.append(wine_setting)

    # 2. Prefix Name
    advanced_settings.append({
        'key': 'PW_PREFIX_NAME',
        'name': _("Prefix Name"),
        'description': _("Specify the Wine prefix to run this game with"),
        'type': 'combo',
        'options': prefix_options,
        'default': 'DEFAULT'
    })

    # 3. Vulkan Backend
    vulkan_options = [
        _("Newest"),        # → 6
        _("Stable"),                    # → 2
        ("Sarek"),   # → 1
        ("WINED3D – OpenGL")                 # → 0
    ]

    vulkan_value_map = {
        vulkan_options[0]: "6",
        vulkan_options[1]: "2",
        vulkan_options[2]: "1",
        vulkan_options[3]: "0",
    }

    advanced_settings.append({
        'key': 'PW_VULKAN_USE',
        'name': _("Vulkan Backend"),
        'description': _(
            "Select the DirectX → Vulkan/OpenGL backend:\n\n"
            "• Newest – latest DXVK + VKD3D (best compatibility/performance, requires modern drivers: AMD Mesa 25+, NVIDIA 550.54.14+, Intel Mesa 24.2+)\n"
            "• Stable – older, well-tested DXVK + VKD3D (works on any Vulkan 1.3+ driver)\n"
            "• Sarek – experimental DXVK-Sarek + VKD3D-Sarek (supports older drivers, Vulkan 1.1+)\n"
            "• WINED3D – OpenGL fallback (lowest performance, use only if others fail)"
        ),
        'type': 'combo',
        'options': vulkan_options,
        'default': '6',
        '_value_map': vulkan_value_map
    })

    # 4. Windows version
    advanced_settings.append({
        'key': 'PW_WINDOWS_VER',
        'name': _("Windows version"),
        'description': _("Changing the WINDOWS emulation version may be required to run older games. WINDOWS versions below 10 do not support new games with DirectX 12"),
        'type': 'combo',
        'options': ['11', '10', '7', 'XP'],
        'default': '11'
    })

    # 5. DLL Overrides
    advanced_settings.append({
        'key': 'WINEDLLOVERRIDES',
        'name': _("DLL Overrides"),
        'description': _("Forced to use/disable the library only for the given application.\n\nA brief instruction:\n* libraries are written WITHOUT the .dll file extension\n* libraries are separated by semicolons - ;\n* library=n - use the WINDOWS (third-party) library\n* library=b - use WINE (built-in) library\n* library=n,b - use WINDOWS library and then WINE\n* library=b,n - use WINE library and then WINDOWS\n* library= - disable the use of this library\n\nExample: libglesv2=;d3dx9_36,d3dx9_42=n,b;mfc120=b,n"),
        'type': 'text',
        'default': ''
    })

    # 6. Launch arguments
    advanced_settings.append({
        'key': 'LAUNCH_PARAMETERS',
        'name': _("Launch Arguments"),
        'description': _("Adding an argument after the .exe file, just like you would add an argument in a shortcut on a WINDOWS system.\n\nExample: -dx11 -skipintro 1"),
        'type': 'text',
        'default': ''
    })

    # 7. Run second executable or wrapper command
    advanced_settings.append({
        'key': 'PW_RUN_AFTER_EXE',
        'name': _("Run After / Wrapper"),
        'description': _("Path to a second .exe, script, or wrapper command. Example: systemd-run --user --scope --slice=app.slice"),
        'type': 'text',
        'default': ''
    })

    # 8. CPU cores limit
    advanced_settings.append({
        'key': 'PW_WINE_CPU_TOPOLOGY',
        'name': _("CPU Cores Limit"),
        'description': _("Limiting the number of CPU cores is useful for Unity games (It is recommended to set the value equal to 8)"),
        'type': 'combo',
        'options': [disabled_text] + logical_core_options,
        'default': disabled_text
    })

    # 9. OpenGL version
    advanced_settings.append({
        'key': 'PW_MESA_GL_VERSION_OVERRIDE',
        'name': _("OpenGL Version"),
        'description': _("You can select the required OpenGL version, some games require a forced Compatibility Profile (COMP)."),
        'type': 'combo',
        'options': [disabled_text, '4.6COMPAT', '4.5COMPAT', '4.3COMPAT', '4.1COMPAT', '3.3COMPAT', '3.2COMPAT'],
        'default': disabled_text
    })

    # 10. VKD3D feature level
    advanced_settings.append({
        'key': 'PW_VKD3D_FEATURE_LEVEL',
        'name': _("VKD3D Feature Level"),
        'description': _("You can set a forced feature level VKD3D for games on DirectX12"),
        'type': 'combo',
        'options': [disabled_text, '12_2', '12_1', '12_0', '11_1', '11_0'],
        'default': disabled_text
    })

    # 11. Locale
    advanced_settings.append({
        'key': 'PW_LOCALE_SELECT',
        'name': _("Locale"),
        'description': _("Force certain locale for an app. Fixes encoding issues in legacy software"),
        'type': 'combo',
        'options': [disabled_text] + locale_options,
        'default': disabled_text
    })

    # 12. Present mode
    advanced_settings.append({
        'key': 'PW_MESA_VK_WSI_PRESENT_MODE',
        'name': _("Window Mode"),
        'description': _("Window mode (for Vulkan and OpenGL):\nfifo - First in, first out. Limits the frame rate + no tearing. (VSync)\nimmediate - Unlimited frame rate + tearing.\nmailbox - Triple buffering. Unlimited frame rate + no tearing.\nrelaxed - Same as fifo but allows tearing when below the monitors refresh rate."),
        'type': 'combo',
        'options': [disabled_text, 'fifo', 'immediate', 'mailbox', 'relaxed'],
        'default': disabled_text
    })


    # 13. NUMA node
    numa_ids = sorted(numa_nodes.keys())
    numa_options = [disabled_text] + numa_ids if len(numa_ids) > 1 else [disabled_text]
    advanced_settings.append({
        'key': 'PW_CPU_NUMA_NODE_INDEX',
        'name': _("NUMA Node"),
        'description': _("NUMA node for CPU affinity. In multi-core systems, CPUs are split into NUMA nodes, each with its own local memory and cores. Binding a game to a single node reduces memory-access latency and limits costly core-to-core switches."),
        'type': 'combo',
        'options': numa_options,
        'default': disabled_text
    })

    # 14. Sound driver
    advanced_settings.append({
        'key': 'PW_SOUND_DRIVER_USE',
        'name': _("Sound Driver"),
        'description': _("Force the Wine sound driver for this executable."),
        'type': 'combo',
        'options': [disabled_text, 'oss', 'pulse', 'alsa'],
        'default': disabled_text
    })

    return advanced_settings

# Keys that should be recognized as advanced settings
ADVANCED_SETTING_KEYS = [
    'PW_WINE_USE',
    'PW_PREFIX_NAME',
    'PW_VULKAN_USE',
    'PW_WINDOWS_VER',
    'WINEDLLOVERRIDES',
    'LAUNCH_PARAMETERS',
    'PW_RUN_AFTER_EXE',
    'PW_WINE_CPU_TOPOLOGY',
    'PW_MESA_GL_VERSION_OVERRIDE',
    'PW_VKD3D_FEATURE_LEVEL',
    'PW_LOCALE_SELECT',
    'PW_MESA_VK_WSI_PRESENT_MODE',
    'PW_CPU_NUMA_NODE_INDEX',
    'PW_SOUND_DRIVER_USE',
]
