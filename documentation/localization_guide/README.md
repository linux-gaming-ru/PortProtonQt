 Эта документация также доступна на [русском.](README.ru.md)

---

## Contents
- [Overview](#-overview)
- [Translate Online](#-translate-online)
- [Adding a New Translation](#-adding-a-new-translation)
- [Updating Existing Translations](#-updating-existing-translations)

---

## Overview

Localization in `PortProtonQT` is powered by `Babel` using `.po` files stored under `LC_MESSAGES/portprotonqt.po` for each language.
To see updated translations in the app, you must generate `.mo` files after editing `.po`.

Current translation status:

<a href="https://translate.codeberg.org/engage/portprotonqt/">
<img src="https://translate.codeberg.org/widget/portprotonqt/multi-auto.svg" alt="Translation status" />
</a>

---

## Translate Online

You can help translate PortProtonQt using our web-based translation platform:

**[translate.codeberg.org/engage/portprotonqt](https://translate.codeberg.org/engage/portprotonqt)**

Benefits of using the web platform:
- No need to set up a development environment
- Work directly in your browser
- See context and suggestions from other translators
- Collaborate with the community

Translations submitted online are periodically reviewed and merged into the main repository.

---

## Adding a New Translation

1. Run:

```bash
uv python install 3.11
uv sync --all-extras --dev
source .venv/bin/activate
python dev-scripts/l10n.py --create-new <locale_code>
```

2. Edit the file `portprotonqt/locales/<locale>/LC_MESSAGES/portprotonqt.po` in Poedit or GTranslator.
3. Generate `.mo` files:

```bash
python dev-scripts/l10n.py
```

---

## Updating Existing Translations

If you’ve added new strings to the code:

```bash
uv python install 3.11
uv sync --all-extras --dev
source .venv/bin/activate
python dev-scripts/l10n.py --update-all
```

After editing `.po` files, generate `.mo`; otherwise new translations will not be visible in the UI:

```bash
python dev-scripts/l10n.py
```

---
