 This documentation is also available in [English](README.md)

---

## Содержание
- [Обзор](#-обзор)
- [Перевод онлайн](#-перевод-онлайн)
- [Добавление нового перевода](#-добавление-нового-перевода)
- [Обновление существующих переводов](#-обновление-существующих-переводов)

---

## Обзор

Локализация в `PortProtonQT` осуществляется через систему `.po` файлов и управляется утилитой `Babel`. Все переводы находятся в подкаталогах вида `LC_MESSAGES/portprotonqt.po` для каждой поддерживаемой локали.
Для отображения изменений в приложении необходимо сгенерировать `.mo` файлы после правок в `.po`.

Текущий статус перевода:

<a href="https://translate.codeberg.org/engage/portprotonqt/">
<img src="https://translate.codeberg.org/widget/portprotonqt/multi-auto.svg" alt="Состояние перевода" />
</a>

---

## Перевод онлайн

Вы можете помочь перевести PortProtonQt через нашу веб-платформу:

**[translate.codeberg.org/engage/portprotonqt](https://translate.codeberg.org/engage/portprotonqt)**

Преимущества веб-платформы:
- Не нужно настраивать окружение разработки
- Работа прямо в браузере
- Видно контекст и варианты от других переводчиков
- Совместная работа с сообществом

Переводы, отправленные через веб-платформу, периодически проверяются и объединяются с основным репозиторием.

---

## Добавление нового перевода

1. Выполните:

```bash
uv python install 3.11
uv sync --all-extras --dev
source .venv/bin/activate
python dev-scripts/l10n.py --create-new <код_локали>
```

2. Отредактируйте файл `portprotonqt/locales/<локаль>/LC_MESSAGES/portprotonqt.po` в Poedit или GTranslator.
3. Сгенерируйте `.mo` файлы:

```bash
python dev-scripts/l10n.py
```

---

## Обновление существующих переводов

Если вы добавили новые строки в код:

```bash
uv python install 3.11
uv sync --all-extras --dev
source .venv/bin/activate
python dev-scripts/l10n.py --update-all
```

После изменения `.po` файлов сгенерируйте `.mo`, иначе новые переводы не появятся в интерфейсе:

```bash
python dev-scripts/l10n.py
```

---
