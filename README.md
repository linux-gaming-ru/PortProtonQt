📘 Эта документация также доступна на [русском](README.ru.md)

---

<div align="center">
  <img src="build-aux/share/icons/hicolor/scalable/apps/ru.linux_gaming.PortProtonQt.svg" width="64">
  <h1 align="center">PortProtonQt</h1>
  <a href="https://git.linux-gaming.ru/Linux-Gaming/PortProtonQt/releases"><img src="https://img.shields.io/badge/Downloads-10488-green?style=flat-square" alt="Total Downloads"></a>
  <p align="center">A modern and convenient interface for managing and launching games from PortProton, Steam, Epic Games Store, and GOG. It brings libraries together in one place and simplifies launching Windows games on Linux.</p>
</div>

### Installation (devel)

```sh
uv python install 3.11
uv sync
source .venv/bin/activate  # For bash/zsh
# or
source .venv/bin/activate.fish  # For fish
```

Launch the application using the `portprotonqt` command.

### Installation (release)

Choose the appropriate package for your system or the AppImage.

Launch using the `portprotonqt` command or via the shortcut in your application menu.

### Development

To automatically prepare the environment (install Python 3.11, dependencies, pre-commit hooks, and generate translations), run the following script:

```sh
./dev-scripts/prepare_env.sh
```

Then activate the virtual environment. The activation command for your shell will be displayed at the end of the script execution. Usually, it is:

```sh
source .venv/bin/activate  # For bash/zsh
# or
source .venv/bin/activate.fish  # For fish
```

`pre-commit` will automatically run on every commit. If you want to run it manually, use:

```sh
pre-commit run --all-files
```

## Authors

* [Boria138](https://git.linux-gaming.ru/Boria138) - Lead Developer
* [BlackSnaker](https://git.linux-gaming.ru/BlackSnaker) - Author of the idea and initial implementation
* [Mikhail Tergoev (Castro-Fidel)](https://git.linux-gaming.ru/CastroFidel) - Author of the original PortProton project

### Contributors

We thank everyone who has contributed to the development of PortProtonQt, including those who participate through commits as well as those who help in other ways (testing, ideas, translations, documentation, etc.). A full list of participants can be found in the [repository activity list](https://git.linux-gaming.ru/Linux-Gaming/PortProtonQt/activity/contributors). Additional participants are also listed in the [CHANGELOG.md](CHANGELOG.md) file. If you have contributed but are not listed, please contact the lead developers so we can acknowledge you!

## Dependencies and Licenses

PortProtonQt uses code and dependencies from the following projects:

- [Icoextract](https://github.com/jlu5/icoextract) — icon extraction library, [MIT](https://github.com/jlu5/icoextract/blob/master/LICENSE) license.
- [HowLongToBeat Python API](https://github.com/ScrappyCocco/HowLongToBeat-PythonAPI) — library for interacting with HowLongToBeat, [MIT](https://github.com/ScrappyCocco/HowLongToBeat-PythonAPI/blob/master/LICENSE.md) license.
- [iat](https://sourceforge.net/projects/iat.berlios) — library for converting mdf and nrg to iso, GPLv3 license.
- [pyte](https://github.com/selectel/pyte) — ANSI escape code parser, [LGPLv3](https://github.com/selectel/pyte?tab=LGPL-3.0-1-ov-file) license.
- [gjs-osk](https://github.com/Vishram1123/gjs-osk) — base for virtual keyboard layout data, GPLv3 license.
- [omikuji](https://github.com/omikuji-launcher/omikuji) — inspiration and source material for the procedural detail page backgrounds, [GPLv3](https://github.com/omikuji-launcher/omikuji/blob/master/LICENSE) license.
- [Bottles](https://github.com/bottlesdevs/Bottles) — source of the compatibility analysis rules, GPL-3.0-only license.

See the [LICENSE](LICENSE) file for the full text of the licenses.

> [!WARNING]
> **Be careful!** If you are using a theme not from the official repository or a trusted source, make sure its `styles.py` file does not contain malicious or unwanted code. Since `styles.py` is a regular Python file, it can contain any instructions. Always check the contents of third-party themes before use.
