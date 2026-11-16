# macOS support (source installation)

The native macOS path uses macOS Wine builds, not the Linux PortProton runtime.
Linux continues to use the existing PortProton scripts. This is an unsigned source
installation, **not** a signed/notarized `.app` or a claim of macOS hardware testing.

## Build and run

Install Python 3.11 or newer, Xcode Command Line Tools, Meson, Ninja, pkg-config,
SDL3 and libarchive. With Homebrew, the native libraries/build tools are available
as `sdl3`, `libarchive`, `meson`, `ninja`, and `pkgconf`. Install the project's Python
dependencies in a virtual environment using the existing project workflow. Ensure
libarchive and SDL3 are discoverable by the dynamic loader/pkg-config; Homebrew's
Apple Silicon prefix is usually `/opt/homebrew`, Intel's is usually `/usr/local`.

Build/install with the virtual environment's Python, for example:

```sh
meson setup builddir --prefix="$VIRTUAL_ENV"
meson compile -C builddir
meson install -C builddir
portprotonqt
```

Meson builds `libportprotonqt_gamepad.dylib` against SDL3 and installs it beside the
Python modules. The Linux Vulkan GPU inspection executable is not built on macOS.
Running directly from an unbuilt checkout still requires the native gamepad
library; do not rename a Linux `.so` to `.dylib`. A distributor must separately
bundle Python/Qt/SDL3/libarchive, set appropriate install names/rpaths, handle
architecture-specific dependencies, and sign/notarize the completed application.
No `.app` packaging, signing identity, or Gatekeeper bypass is supplied here.

## Supported workflow

* Start the application without installing or running the Linux bootstrap.
* Use the existing Wine manager to browse the macOS catalog directly from
  <https://git.linux-gaming.ru/Boria138/PortProton-Wine-Metadata/raw/branch/main/macos_wine_metadata.json>.
  The catalog groups include Wine Crossover, macOS Wine builds, Sikarugir engines,
  and Game Porting Toolkit engines. Catalog inclusion is not a compatibility
  guarantee; review each upstream project's license and macOS/CPU requirements.
* Install each catalog version in its own managed directory. Archive extraction
  retains the existing traversal/link checks. Plain `bin/wine[64]`, common Wine
  `.app` layouts, and `wswine.bundle/bin/wine[64]` are recognized. Entries whose
  archive layout does not expose one of those binaries cannot be launched.
* Select installed Wine versions and prefixes in the existing game settings.
  Wine/prefix settings are the supported macOS game settings. Linux graphics,
  synchronization and anticheat overrides are not silently applied.
* Launch Windows EXEs through the existing game/EXE UI and its owned process
  tracking, or directly through the native adapter:

  ```sh
  python -m portprotonqt.macos '/path/to/Game.exe' 'argument with spaces'
  ```

  The adapter preserves arguments without a shell and replaces its own process
  with Wine, allowing the normal launcher stop/shutdown path to own the process.
  Wine configuration, registry editor, file manager, command prompt and uninstaller
  use the selected engine and prefix through the Wine tab. Tool processes are
  retained and terminated/waited during application shutdown.
* Remove installed engines through the existing installed-versions manager.

The default data directory is
`~/Library/Application Support/PortProtonQt`; an explicit `PORT_DATA_PATH` overrides
it. Engines live under `data/dist/<catalog name>`, prefixes under
`data/prefixes/<prefix name>`, and global Wine settings in `data/user.conf`.
Per-EXE settings remain `<executable>.ppdb`. Configuration values are parsed as
assignments, never sourced as shell code. If no engine is selected, the adapter
uses the first usable managed engine or `wine` on PATH; an explicitly selected
missing engine fails rather than launching another engine unexpectedly. For
managed engines, the adapter uses an executable `wineserver` next to the selected
Wine binary when present, without changing the parent process environment.

On Apple Silicon, x86_64 Wine builds generally require Rosetta 2 and a compatible
macOS release. Install Rosetta using Apple's documented workflow if required.
This project does not install it, choose a CPU architecture automatically, or
make incompatible Wine distributions compatible. No private, machine-specific
application bundle is used. NTLM-enabled applications may additionally need an
upstream-supported `ntlm_auth` installation (for example Samba).

## Limits and verification

Linux D-Bus/system management is disabled on macOS; system power, audio, Bluetooth,
network and storage controls are not ported. SDL gamepad navigation remains available,
but Linux `/dev/uinput` virtual-mouse emulation is disabled. Linux PortProton autoinstall scripts,
runtime downloads, Gamescope, MangoHud, vkBasalt, Linux Steam compatibility-tool
registration, Linux XDG autostart, ISO mounting and store-specific Wine wrappers
are not supported macOS workflows. Use local EXEs and macOS Wine engines. Basic
Wine tools are supported, but prefix reset/default-prefix copying and Linux
runtime-specific tools are not. Unsupported native-adapter CLI operations fail
with an error rather than executing Linux scripts.

The current macOS catalog supplies URLs and human-readable sizes, **not SHA256
checksums**. Downloads use HTTPS and existing extraction checks; this is not
cryptographic artifact verification. Failed/partial extractions may remain for
inspection and can be retried or removed; they count as installed only if a usable
Wine executable is present.

Regression tests mock the host, catalog network, executable handoff, settings and
shutdown. Linux CI cannot validate Mach-O loading, Rosetta, Wine runtime behavior,
Qt appearance, signing or actual macOS gameplay. Those require a real macOS
installation and remain release validation work.

Assisted-by: pz:gpt-6.1-sol
Assisted-by: pz:gpt-6.2-sol
