📘 This documentation is also available in [English](README.md)

---

<div align="center">
  <img src="build-aux/share/icons/hicolor/scalable/apps/ru.linux_gaming.PortProtonQt.svg" width="128">

  <p align="center">Приложение для управления игровой библиотекой и запуска игр на Linux. Объединяет игры из разных источников в одном месте.</p>

  <p>
    <a href="https://git.linux-gaming.ru/Linux-Gaming/PortProtonQt/releases"><img src="https://img.shields.io/github/v/release/linux-gaming-ru/PortProtonQt?style=flat-square&amp;label=Релиз" alt="Релизы"></a>
    <a href="https://git.linux-gaming.ru/Linux-Gaming/PortProtonQt/releases"><img src="https://img.shields.io/badge/Загрузки-14.1k-green?style=flat-square" alt="Всего загрузок"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/Лицензия-GPL--3.0-blue?style=flat-square" alt="Лицензия: GPL-3.0"></a>
    <a href="pyproject.toml"><img src="https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&amp;logo=python" alt="Python 3.11+"></a>
    <a href="https://git.linux-gaming.ru/Linux-Gaming/PortProtonQt"><img src="https://img.shields.io/badge/Платформа-Linux-blue?style=flat-square&amp;logo=linux" alt="Платформа: Linux"></a>
    <a href="https://translate.codeberg.org/engage/portprotonqt/"><img src="https://img.shields.io/badge/Переводы-Weblate-2eccaa?style=flat-square&amp;logo=weblate" alt="Перевести на Weblate"></a>
    <a href="https://repology.org/project/portprotonqt/versions"><img src="https://repology.org/badge/tiny-repos/portprotonqt.svg?header=Репозитории" alt="Пакеты в Repology"></a>
  </p>

  <p><a href="https://git.linux-gaming.ru/Linux-Gaming/PortProtonQt/releases">Релизы</a> · <a href="https://git.linux-gaming.ru/Linux-Gaming/PortProtonQt/issues">Сообщить о проблеме</a> · <a href="https://translate.codeberg.org/engage/portprotonqt/">Переводы</a> · <a href="https://repology.org/project/portprotonqt/versions">Пакеты</a></p>
</div>

### Установка (devel)

```sh
uv python install 3.11
uv sync
source .venv/bin/activate  # For bash/zsh
# or
source .venv/bin/activate.fish  # For fish
```

Запуск производится по команде portprotonqt

### Установка (release)

Выберите подходящий пакет для вашей системы или AppImage.

Запуск производится по команде portprotonqt или по ярлыку в меню

### Разработка

Для автоматической подготовки окружения (установка Python 3.11, зависимостей, pre-commit хуков и генерация переводов) выполните скрипт:

```sh
./dev-scripts/prepare_env.sh
```

Затем активируйте виртуальное окружение. Команда активации для вашей оболочки будет выведена в конце работы скрипта. Обычно это:

```sh
source .venv/bin/activate  # Для bash/zsh
# или
source .venv/bin/activate.fish  # Для fish
```

pre-commit сам запустится при коммите, если вы хотите запустить его вручную введите команду:

```sh
pre-commit run --all-files
```

## Авторы

* [Boria138](https://git.linux-gaming.ru/Boria138) - Основной разработчик
* [BlackSnaker](https://git.linux-gaming.ru/BlackSnaker) - Автор идеи, а так же начальной реализации проекта
* [Mikhail Tergoev (Castro-Fidel)](https://git.linux-gaming.ru/CastroFidel) - Автор оригинального проекта PortProton

### Контрибьюторы

Мы благодарим всех, кто внёс вклад в развитие PortProtonQt, включая тех, кто участвует через коммиты, а также тех, кто помогает другими способами (тестирование, идеи, переводы, документация и т.д.). Полный список участников, можно найти в [списке активности репозитория](https://git.linux-gaming.ru/Linux-Gaming/PortProtonQt/activity/contributors). Дополнительные участники также перечислены в файле [CHANGELOG.md](CHANGELOG.md). Если вы внесли вклад, но не указаны, свяжитесь с основными разработчиками, чтобы мы могли вас отметить!

## Зависимости и лицензии

PortProtonQt использует код и зависимости от следующих проектов:

- [Icoextract](https://github.com/jlu5/icoextract) — библиотека для извлечения иконок, лицензия [MIT](https://github.com/jlu5/icoextract/blob/master/LICENSE).
- [HowLongToBeat Python API](https://github.com/ScrappyCocco/HowLongToBeat-PythonAPI) — библиотека для взаимодействия с HowLongToBeat, лицензия [MIT](https://github.com/ScrappyCocco/HowLongToBeat-PythonAPI/blob/master/LICENSE.md).
- [Iso9660 Analyzer Tool (IAT)](https://sourceforge.net/projects/iat.berlios/) — библиотека для конвертации mdf и nrg в iso, лицензия GPLv2
- [heroic-gogdl](https://github.com/Heroic-Games-Launcher/heroic-gogdl) — модуль загрузки игр GOG, лицензия [GPLv3](https://github.com/Heroic-Games-Launcher/heroic-gogdl/blob/main/LICENSE).
- [Legendary](https://github.com/Heroic-Games-Launcher/legendary) — альтернатива Epic Games Launcher, лицензия [GPLv3](https://github.com/Heroic-Games-Launcher/legendary/blob/master/LICENSE).
- [pyte](https://github.com/selectel/pyte) — разбор ANSI escape-кодов, лицензия [LGPLv3](https://github.com/selectel/pyte?tab=LGPL-3.0-1-ov-file)
- [gjs-osk](https://github.com/Vishram1123/gjs-osk) — основа данных раскладок виртуальной клавиатуры, лицензия GPLv3.
- [omikuji](https://github.com/omikuji-launcher/omikuji) — источник вдохновения и материалов для процедурных фонов детальной страницы, лицензия [GPLv3](https://github.com/omikuji-launcher/omikuji/blob/master/LICENSE).
- [Bottles](https://github.com/bottlesdevs/Bottles) — источник правил анализа совместимости, лицензия GPL-3.0-only.

Условия лицензии PortProtonQt приведены в файле [LICENSE](LICENSE). Лицензии
сторонних проектов приведены в файле [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES).

> [!WARNING]
> **Будьте осторожны!** Если вы берёте тему не из официального репозитория или надёжного источника, убедитесь, что в её файле `styles.py` нет вредоносного или нежелательного кода. Поскольку `styles.py` — это обычный Python-файл, он может содержать любые инструкции. Всегда проверяйте содержимое чужих тем перед использованием.
