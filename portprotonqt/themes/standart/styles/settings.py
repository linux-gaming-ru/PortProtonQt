from .constants import *

SETTINGS_DESCRIPTION_HTML = (
    f'<span style="color: {color_disabled_text}; font-size: {font_size_value};">'
    '{description}</span>'
)

SETTINGS_FRAME_STYLE = f"""
    QFrame {{
        background: {color_bg};
        border:  {border_none} transparent;
        border-radius: {border_radius_large};
    }}
"""

SETTINGS_FRAME_TITLE_STYLE = f"""
    QLabel {{
        font-family: '{font_family}';
        font-size: {font_size_normal};
        font-weight: bold;
        color: {color_accent};
    }}
"""

SETTINGS_TITLE_STYLE = f"""
    QLabel {{
        color: {color_text};
        height: 34px;
        font-family: '{font_family}';
        font-size: {font_size_normal};
        font-weight: bold;
        padding: 7px;
        background: {color_surface_elevated};
        border-radius: {border_radius_small};
        min-width: 320px;
    }}
"""

SETTINGS_TITLE_CHECKBOX_STYLE = f"""
    QLabel {{
        color: {color_text};
        height: 34px;
        font-family: '{font_family}';
        font-size: {font_size_normal};
        font-weight: bold;
        padding: 7px;
        background: {color_transparent};
        border-radius: {border_radius_small};
        min-width: 180px;
    }}
"""

# Disabled line edit style
SETTINGS_DISABLED_INPUT_STYLE = f"background-color: {color_disabled_bg};"
