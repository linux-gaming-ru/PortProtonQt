📖 This documentation is also available in [English](README.md)

---

<div align="center">
  <img src="build-aux/share/icons/hicolor/scalable/apps/ru.linux_gaming.PortProtonQt.svg" width="64">
  <h1 align="center">PortProtonQt</h1>
  <a href="https://git.linux-gaming.ru/Linux-Gaming/PortProtonQt/releases"><img src="https://img.shields.io/badge/%D0%97%D0%B0%D0%B3%D1%80%D1%83%D0%B7%D0%BA%D0%B8-10488-green?style=flat-square" alt="Всего загрузок"></a>
  <p align="center">Современный и удобный интерфейс для управления и запуска игр из PortProton, Steam, Epic Games Store и GOG. Объединяет библиотеки в одном месте и упрощает запуск Windows-игр на Linux.</p>
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
- [iat](https://sourceforge.net/projects/iat.berlios) — библиотека для конвертации mdf и nrg в iso, лицензия GPLv3
- [pyte](https://github.com/selectel/pyte) — разбор ANSI escape-кодов, лицензия [LGPLv3](https://github.com/selectel/pyte?tab=LGPL-3.0-1-ov-file)
- [gjs-osk](https://github.com/Vishram1123/gjs-osk) — основа данных раскладок виртуальной клавиатуры, лицензия GPLv3.
- [omikuji](https://github.com/omikuji-launcher/omikuji) — источник вдохновения и материалов для процедурных фонов детальной страницы, лицензия [GPLv3](https://github.com/omikuji-launcher/omikuji/blob/master/LICENSE).
- [Bottles](https://github.com/bottlesdevs/Bottles) — источник правил анализа совместимости, лицензия GPL-3.0-only.

Полный текст лицензий см. в файле [LICENSE](LICENSE).

> [!WARNING]
> **Будьте осторожны!** Если вы берёте тему не из официального репозитория или надёжного источника, убедитесь, что в её файле `styles.py` нет вредоносного или нежелательного кода. Поскольку `styles.py` — это обычный Python-файл, он может содержать любые инструкции. Всегда проверяйте содержимое чужих тем перед использованием.
