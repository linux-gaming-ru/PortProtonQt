from .constants import *

CONTEXT_MENU_STYLE = f"""
    QMenu {{
        background: {color_bg};
        color: {color_text};
        font-family: '{font_family}';
        font-size: {font_size_normal};
        padding: 5px;
        min-width: 150px;
        border: {border_thin} {color_accent};
        border-radius: {border_radius_small};
    }}
    QMenu::icon {{
        margin-left: 15px;
    }}
    QMenu::item {{
        padding: 10px 20px 10px 10px;
        background: {color_transparent};
        border-radius: {border_radius_small};
        color: {color_text};
    }}
    QMenu::item:selected {{
        background: {color_accent};
        color: {color_text_accent_hover};
    }}
    QMenu::item:disabled {{
            color: {color_separator};
        }}
    QMenu::item:hover {{
        background: {color_accent};
        color: {color_text_accent_hover};
    }}
    QMenu::item:focus {{
        background: {color_accent};
        color: {color_text_accent_hover};
        border: {border_thin} {color_border_focus};
        border-radius: {border_radius_small};
    }}
    QMenu::separator {{
        height: 1px;
        background-color: {color_separator};
        margin: 3px 6px;
    }}
"""

SYSTEM_KEYBOARD_BACKGROUND_STYLE = f"""
QFrame#systemKeyboard {{
    background: {color_bg};
    border-radius: {border_radius_small};
}}
QWidget#systemKeyboardContainer {{
    background: {color_transparent};
}}
QFrame#systemKeyboard QPushButton {{
    min-width: 0;
    min-height: 0;
    padding: 0;
}}
"""

VIRTUAL_KEYBOARD_STYLE = f"""
QWidget {{
    background: {color_overlay};
}}
QPushButton {{
    font-size: {font_size_keyboard};
    border: {border_none} {color_transparent};
    border-radius: {border_radius_small};
    min-width: 30px;
    min-height: 30px;
    padding: 5px;
    background-color: {color_surface};
    color: {color_text};
}}
QPushButton:hover {{
    background-color: {color_accent};
    border: {border_thin} {color_accent};
    color: {color_text_accent_hover};
}}
QPushButton:focus {{
    border: {border_thin} {color_accent};
    background-color: {color_accent};
    color: {color_text_accent_hover};
}}
QPushButton[vk_selected="true"] {{
    border: {border_thin} {color_accent};
    background-color: {color_accent};
    color: {color_text_accent_hover};
}}
QPushButton:pressed {{
    background-color: {color_surface};
    border: {border_none} {color_transparent};
}}
QPushButton:checked {{
    background-color: {color_accent};
    color: {color_text_accent_hover};
    border: {border_none} {color_transparent};
}}
QPushButton:checked:focus {{
    border: {border_thin} {color_text};
}}
"""

# FULLSCREEN THEME SCREENSHOT PREVIEW STYLES
PREV_BUTTON_STYLE = f"background-color: {color_preview_btn_bg}; color: {color_preview_btn_text}; border: none;"
NEXT_BUTTON_STYLE = f"background-color: {color_preview_btn_bg}; color: {color_preview_btn_text}; border: none;"
