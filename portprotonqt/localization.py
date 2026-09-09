import gettext
import configparser
from pathlib import Path
import locale
import os
from babel import Locale
from portprotonqt.logger import get_logger

logger = get_logger(__name__)

_translation_sources: dict[str, str] = {}

LOCALE_MAP = {
    'ru': 'russian',
    'en': 'english',
    'fr': 'french',
    'de': 'german',
    'es': 'spanish',
    'it': 'italian',
    'zh': 'schinese',
    'zh_Hant': 'tchinese',
    'ja': 'japanese',
    'ko': 'koreana',
    'pt': 'brazilian',
    'pl': 'polish',
    'nl': 'dutch',
    'sv': 'swedish',
    'no': 'norwegian',
    'da': 'danish',
    'fi': 'finnish',
    'cs': 'czech',
    'hu': 'hungarian',
    'tr': 'turkish',
    'ro': 'romanian',
    'th': 'thai',
    'uk': 'ukrainian',
    'bg': 'bulgarian',
    'el': 'greek',
}

STORE_CONTENT_LOCALES = {'es': 'es-ES', 'pt': 'pt-BR', 'zh': 'zh-CN'}

# Try local locale directory first, fallback to system for development
_local_localedir = Path(__file__).parent / "locales"
_locale_dirs = [_local_localedir]
if os.getenv("SHARUN_DIR"):
    _locale_dirs.append(Path(os.environ["SHARUN_DIR"]) / "share" / "locale")
_locale_dirs.extend(
    Path(data_dir) / "locale"
    for data_dir in os.getenv(
        "XDG_DATA_DIRS", "/usr/local/share:/usr/share"
    ).split(os.pathsep)
    if data_dir
)

translate = gettext.NullTranslations()
for _locale_dir in _locale_dirs:
    try:
        translate = gettext.translation("portprotonqt", localedir=_locale_dir)
        break
    except FileNotFoundError:
        continue


def _(message: str) -> str:
    from portprotonqt.config import ui_config

    translated = translate.gettext(message)
    _translation_sources[message] = message
    _translation_sources[translated] = message
    return message if ui_config.get_force_english() else translated


def retranslate(message: str) -> str:
    """Translate text previously passed through gettext."""
    source = _translation_sources.get(message)
    if source is None:
        return message
    return _(source)


def get_system_locale():
    """Return system locale, e.g., 'ru_RU'. Returns 'en' if detection fails."""
    from portprotonqt.config import ui_config

    if ui_config.get_force_english():
        return 'en'
    loc = locale.getdefaultlocale()[0]
    return loc if loc else 'en'

def get_steam_language():
    try:
        # Babel automatically parses complex locales, e.g., 'zh_Hant_HK' → 'zh_Hant'
        system_locale = get_system_locale()
        if system_locale:
            locale = Locale.parse(system_locale)
            # Use only the language code ('ru', 'en', etc.)
            language_code = locale.language
            os.environ["FULL_LN"] = LOCALE_MAP.get(language_code, 'english')
            return LOCALE_MAP.get(language_code, 'english')
    except Exception as e:
        logger.warning("Failed to detect locale: %s", e)

    # Fallback to English by default
    return 'english'

def get_metadata_language() -> str:
    try:
        # Babel automatically parses complex locales, e.g., 'zh_Hant_HK' → 'zh_Hant'
        system_locale = get_system_locale()
        if system_locale:
            parsed_locale = Locale.parse(system_locale)
            return parsed_locale.language
    except Exception as e:
        logger.warning("Failed to detect locale: %s", e)

    return 'en'

def get_store_content_languages() -> tuple[str, ...]:
    """Return preferred store content locales with English fallback."""
    language = get_metadata_language().lower().split('_', 1)[0] or 'en'
    system_locale = get_system_locale().lower().replace('-', '_')
    if language == 'zh' and any(
        variant in system_locale for variant in ('hant', '_tw', '_hk', '_mo')
    ):
        preferred = 'zh-TW'
    else:
        preferred = STORE_CONTENT_LOCALES.get(language, language)
    languages = [preferred]
    if language not in languages:
        languages.append(language)
    if 'en-US' not in languages:
        languages.append('en-US')
    return tuple(languages)

def read_metadata_translations(metadata_file, language_code):
    """
    Read translations from metadata.txt for the specified language.
    Returns a dictionary with name and description fields.
    For name: uses name_<language_code>, then name_en, then name, and finally _('Unknown Game').
    For description: uses description_<language_code>, then description_en, then description.
    """
    translations = {'name': _('Unknown Game'), 'description': ''}
    if not os.path.exists(metadata_file):
        return translations

    with open(metadata_file, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line.startswith(f'name_{language_code}='):
                translations['name'] = line[len(f'name_{language_code}='):].strip()
            elif line.startswith('name_en=') and translations['name'] == _('Unknown Game'):
                translations['name'] = line[len('name_en='):].strip()
            elif line.startswith('name=') and translations['name'] == _('Unknown Game'):
                translations['name'] = line[len('name='):].strip()
            elif line.startswith(f'description_{language_code}='):
                translations['description'] = line[len(f'description_{language_code}='):].strip()
            elif line.startswith('description_en=') and not translations['description']:
                translations['description'] = line[len('description_en='):].strip()
            elif line.startswith('description=') and not translations['description']:
                translations['description'] = line[len('description='):].strip()

    return translations

def get_theme_translations(metainfo_file, language_code=None):
    """
    Return translated theme name and description based on user's language.

    Args:
        metainfo_file: Path to metainfo.ini file
        language_code: Language code (if None, will be auto-detected)

    Returns:
        Dictionary with 'name' and 'description' fields containing translated values
    """
    if language_code is None:
        system_locale = get_system_locale()
        language_code = system_locale.split('_')[0] if '_' in system_locale else system_locale

    # Load translations from metainfo.ini
    translations = {'name': '', 'description': ''}

    if metainfo_file and os.path.exists(metainfo_file):
        cp = configparser.ConfigParser()
        cp.read(metainfo_file, encoding="utf-8")

        if "Metainfo" in cp:
            # Try translation for specific language (e.g., "name_ru")
            lang_specific_name_key = f"name_{language_code}"
            # Try English translation (e.g., "name_en")
            english_name_key = "name_en"

            # Look for name translation
            if cp.has_option("Metainfo", lang_specific_name_key):
                translations['name'] = cp.get("Metainfo", lang_specific_name_key)
            elif cp.has_option("Metainfo", english_name_key):
                translations['name'] = cp.get("Metainfo", english_name_key)
            elif cp.has_option("Metainfo", "name"):
                translations['name'] = cp.get("Metainfo", "name")

            # Try translation for specific language (e.g., "description_ru")
            lang_specific_desc_key = f"description_{language_code}"
            # Try English translation (e.g., "description_en")
            english_desc_key = "description_en"

            # Look for description translation
            if cp.has_option("Metainfo", lang_specific_desc_key):
                translations['description'] = cp.get("Metainfo", lang_specific_desc_key)
            elif cp.has_option("Metainfo", english_desc_key):
                translations['description'] = cp.get("Metainfo", english_desc_key)
            elif cp.has_option("Metainfo", "description"):
                translations['description'] = cp.get("Metainfo", "description")

    return translations


def format_setting_name_for_display(key):
    """
    Format setting names for display by removing the 'PW_' prefix and replacing underscores with spaces.

    Args:
        key (str): The original setting key (e.g., 'PW_MANGOHUD', 'PW_WINE_FULLSCREEN_FSR')

    Returns:
        str: The formatted setting name for display (e.g., 'MANGOHUD', 'WINE FULLSCREEN FSR')
    """
    if key.startswith('PW_'):
        # Remove the 'PW_' prefix and replace underscores with spaces
        display_name = key[3:]  # Remove 'PW_' prefix
        display_name = display_name.replace('_', ' ')  # Replace underscores with spaces
        return display_name
    else:
        # For non-PW settings, just replace underscores with spaces
        return key.replace('_', ' ')
