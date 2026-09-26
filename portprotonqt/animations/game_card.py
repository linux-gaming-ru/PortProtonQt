from math import radians, sin
from typing import Any
import warnings

from PySide6.QtCore import QPropertyAnimation, QByteArray, QEasingCurve, Qt
from PySide6.QtGui import QPainter, QPen, QColor, QConicalGradient, QBrush

from portprotonqt.logger import get_logger
from portprotonqt.config import ui_config
from portprotonqt.theme_manager import ThemeManager

logger = get_logger(__name__)


class GameCardAnimations:
    def __init__(self, game_card, theme=None):
        self.game_card = game_card
        self.theme_manager = ThemeManager()
        self.theme = theme if theme is not None else self.theme_manager.apply_theme(ui_config.get_theme())
        self.thickness_anim: QPropertyAnimation | None = None
        self.gradient_anim: QPropertyAnimation | None = None
        self.scale_anim: QPropertyAnimation | None = None
        self.pulse_anim: QPropertyAnimation | None = None
        self._isPulseAnimationConnected = False

    def _animation_type(self) -> str:
        layout_config = getattr(self.game_card, "card_layout_cfg", {})
        return layout_config.get("card_animation_type", "gradient")

    def _config_value(self, key: str) -> Any:
        layout_config = getattr(self.game_card, "card_layout_cfg", {})
        if key in layout_config:
            return layout_config[key]
        return self.theme.GAME_CARD_ANIMATION[key]

    def _optional_config_value(self, key: str, default: Any) -> Any:
        layout_config = getattr(self.game_card, "card_layout_cfg", {})
        if key in layout_config:
            return layout_config[key]
        return self.theme.GAME_CARD_ANIMATION.get(key, default)

    def _disconnect_pulse_animation(self) -> None:
        if not self._isPulseAnimationConnected or self.thickness_anim is None:
            return
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                self.thickness_anim.finished.disconnect(self.start_pulse_animation)
        except RuntimeError:
            pass
        self._isPulseAnimationConnected = False

    def _stop_animation(self, animation_name: str) -> None:
        animation = getattr(self, animation_name)
        if not animation:
            return
        try:
            animation.stop()
            if animation_name == "thickness_anim":
                self._disconnect_pulse_animation()
            animation.deleteLater()
        except RuntimeError:
            pass
        setattr(self, animation_name, None)

    def _restart_gradient_animation(self) -> None:
        self._stop_animation("gradient_anim")
        self.gradient_anim = QPropertyAnimation(self.game_card, QByteArray(b"gradientAngle"))
        self.gradient_anim.setDuration(self._config_value("gradient_anim_duration"))
        self.gradient_anim.setStartValue(self._config_value("gradient_start_angle"))
        self.gradient_anim.setEndValue(self._config_value("gradient_end_angle"))
        self.gradient_anim.setLoopCount(-1)
        self.gradient_anim.start()

    def _easing_curve(self, easing_key: str) -> QEasingCurve:
        easing_type = QEasingCurve.Type[self._config_value(easing_key)]
        return QEasingCurve(easing_type)

    def _restart_scale_animation(self, end_value: float, easing_key: str) -> None:
        self._stop_animation("scale_anim")
        self.scale_anim = QPropertyAnimation(self.game_card, QByteArray(b"scale"))
        self.scale_anim.setDuration(self._config_value("scale_anim_duration"))
        self.scale_anim.setEasingCurve(self._easing_curve(easing_key))
        self.scale_anim.setStartValue(self.game_card._scale)
        self.scale_anim.setEndValue(end_value)
        self.scale_anim.start()

    def _start_thickness_animation(self, end_value: float, easing_key: str, connect_pulse: bool) -> None:
        if not self.thickness_anim:
            return
        self.thickness_anim.stop()
        self._disconnect_pulse_animation()
        self.thickness_anim.setEasingCurve(self._easing_curve(easing_key))
        self.thickness_anim.setStartValue(self.game_card._borderWidth)
        self.thickness_anim.setEndValue(end_value)
        if connect_pulse:
            self.thickness_anim.finished.connect(self.start_pulse_animation)
            self._isPulseAnimationConnected = True
        self.thickness_anim.start()

    def cleanup(self):
        """Clean up all animation objects to prevent memory leaks."""
        self._stop_animation("thickness_anim")
        self._stop_animation("gradient_anim")
        self._stop_animation("scale_anim")
        self._stop_animation("pulse_anim")
        self._isPulseAnimationConnected = False

    def refresh_theme(self, theme: Any) -> None:
        """Recreate animation state for a live theme change."""
        self.cleanup()
        self.theme = theme
        animation_type = self._animation_type()
        self.game_card._gradientAngle = self._config_value("gradient_start_angle")
        if self.game_card._hovered:
            self.game_card._borderWidth = self._config_value("hover_border_width")
            active_scale = self._config_value("hover_scale")
        elif self.game_card._focused:
            self.game_card._borderWidth = self._config_value("focus_border_width")
            active_scale = self._config_value("focus_scale")
        else:
            self.game_card._borderWidth = self._config_value("default_border_width")
            active_scale = self._config_value("default_scale")
        self.game_card._scale = (
            active_scale
            if animation_type in {"scale", "scale_fill"}
            else self._config_value("default_scale")
        )
        self.setup_animations()
        if (self.game_card._hovered or self.game_card._focused) and animation_type in {
            "gradient", "glow",
        }:
            self._restart_gradient_animation()
        if self.game_card._hovered or self.game_card._focused:
            self.start_pulse_animation()
        self.game_card.update()

    def setup_animations(self):
        """Initialize animation properties based on theme."""
        self.thickness_anim = QPropertyAnimation(self.game_card, QByteArray(b"borderWidth"))
        self.thickness_anim.setDuration(self._config_value("thickness_anim_duration"))

        animation_type = self._animation_type()
        if animation_type in {"gradient", "glow"}:
            self.gradient_anim = QPropertyAnimation(self.game_card, QByteArray(b"gradientAngle"))
            self.gradient_anim.setDuration(self._config_value("gradient_anim_duration"))
        elif animation_type in {"scale", "scale_fill"}:
            self.scale_anim = QPropertyAnimation(self.game_card, QByteArray(b"scale"))
            self.scale_anim.setDuration(self._config_value("scale_anim_duration"))

    def start_pulse_animation(self):
        """Start pulse animation for border width when hovered or focused."""
        if not (self.game_card._hovered or self.game_card._focused):
            return

        self._stop_animation("pulse_anim")

        self.pulse_anim = QPropertyAnimation(self.game_card, QByteArray(b"borderWidth"))
        self.pulse_anim.setDuration(self._config_value("pulse_anim_duration"))
        self.pulse_anim.setLoopCount(0)
        self.pulse_anim.setKeyValueAt(0, self._config_value("pulse_min_border_width"))
        self.pulse_anim.setKeyValueAt(0.5, self._config_value("pulse_max_border_width"))
        self.pulse_anim.setKeyValueAt(1, self._config_value("pulse_min_border_width"))
        self.pulse_anim.start()

    def handle_enter_event(self):
        """Handle mouse enter event animations."""
        self.game_card._hovered = True
        self.game_card.hoverChanged.emit(self.game_card.name, True)
        self.game_card.setFocus(Qt.FocusReason.MouseFocusReason)

        if not self.thickness_anim:
            self.setup_animations()

        animation_type = self._animation_type()

        self._start_thickness_animation(
            self._config_value("hover_border_width"),
            "thickness_easing_curve",
            True,
        )

        if animation_type in {"gradient", "glow"}:
            self._restart_gradient_animation()
        elif animation_type in {"scale", "scale_fill"}:
            self._restart_scale_animation(self._config_value("hover_scale"), "scale_easing_curve")

    def handle_leave_event(self):
        """Handle mouse leave event animations."""
        self.game_card._hovered = False
        self.game_card.hoverChanged.emit(self.game_card.name, False)
        if not self.game_card._focused:
            animation_type = self._animation_type()
            if animation_type in {"gradient", "glow"}:
                self._stop_animation("gradient_anim")
            elif animation_type in {"scale", "scale_fill"}:
                self._restart_scale_animation(self._config_value("default_scale"), "scale_easing_curve_out")
            self._stop_animation("pulse_anim")
            self._start_thickness_animation(
                self._config_value("default_border_width"),
                "thickness_easing_curve_out",
                False,
            )

    def handle_focus_in_event(self):
        """Handle focus in event animations."""
        if not self.game_card._hovered:
            self.game_card._focused = True
            self.game_card.focusChanged.emit(self.game_card.name, True)

            if not self.thickness_anim:
                self.setup_animations()

            animation_type = self._animation_type()

            self._start_thickness_animation(
                self._config_value("focus_border_width"),
                "thickness_easing_curve",
                True,
            )

            if animation_type in {"gradient", "glow"}:
                self._restart_gradient_animation()
            elif animation_type in {"scale", "scale_fill"}:
                self._restart_scale_animation(self._config_value("focus_scale"), "scale_easing_curve")

    def handle_focus_out_event(self):
        """Handle focus out event animations."""
        self.game_card._focused = False
        self.game_card.focusChanged.emit(self.game_card.name, False)
        if not self.game_card._hovered:
            animation_type = self._animation_type()
            if animation_type in {"gradient", "glow"}:
                self._stop_animation("gradient_anim")
            elif animation_type in {"scale", "scale_fill"}:
                self._restart_scale_animation(self._config_value("default_scale"), "scale_easing_curve_out")
            self._stop_animation("pulse_anim")
            self._start_thickness_animation(
                self._config_value("default_border_width"),
                "thickness_easing_curve_out",
                False,
            )

    def paint_border(self, painter: QPainter):
        if not painter.isActive():
            logger.debug("Painter is not active; skipping border paint")
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen()
        pen.setWidth(self.game_card._borderWidth)
        fill_brush = QBrush(Qt.BrushStyle.NoBrush)
        animation_type = self._animation_type()
        if (self.game_card._hovered or self.game_card._focused) and animation_type == "gradient":
            center = self.game_card.rect().center()
            gradient = QConicalGradient(center, self.game_card._gradientAngle)
            for stop in self._config_value("gradient_colors"):
                gradient.setColorAt(stop["position"], QColor(stop["color"]))
            pen.setBrush(QBrush(gradient))
        elif (self.game_card._hovered or self.game_card._focused) and animation_type in {"fill", "scale_fill"}:
            fill_color_value = self._optional_config_value(
                "fill_color",
                getattr(self.theme, "color_accent", self.theme.color_text),
            )
            fill_alpha = int(self._optional_config_value("fill_alpha", 90))
            fill_color = QColor(fill_color_value)
            fill_color.setAlpha(max(0, min(255, fill_alpha)))
            fill_brush = QBrush(fill_color)
            pen.setColor(QColor(0, 0, 0, 0))
        elif (self.game_card._hovered or self.game_card._focused) and animation_type == "stripe":
            stripe_color_value = self._optional_config_value(
                "stripe_color",
                getattr(self.theme, "color_accent", self.theme.color_text),
            )
            stripe_alpha = int(self._optional_config_value("stripe_alpha", 255))
            stripe_color = QColor(stripe_color_value)
            stripe_color.setAlpha(max(0, min(255, stripe_alpha)))
            pen.setColor(stripe_color)
        elif (self.game_card._hovered or self.game_card._focused) and animation_type == "glow":
            glow_color_value = self._optional_config_value(
                "stripe_color",
                getattr(self.theme, "color_accent", self.theme.color_text),
            )
            glow_base_alpha = int(self._optional_config_value("glow_base_alpha", 120))
            glow_pulse_alpha = int(self._optional_config_value("glow_pulse_alpha", 80))
            glow_wave = 0.5 + 0.5 * sin(radians(self.game_card._gradientAngle))
            glow_alpha = max(0, min(255, glow_base_alpha + int(glow_pulse_alpha * glow_wave)))
            glow_color = QColor(glow_color_value)
            glow_color.setAlpha(glow_alpha)
            pen.setColor(glow_color)
        else:
            pen.setColor(QColor(0, 0, 0, 0))
        painter.setPen(pen)
        painter.setBrush(fill_brush)
        radius = self.game_card.card_layout_cfg.get("border_radius", 18)
        radius *= self.game_card._scale
        bw = round(self.game_card._borderWidth / 2)
        rect = self.game_card.rect().adjusted(bw, bw, -bw, -bw)
        if rect.isEmpty():
            return
        painter.drawRoundedRect(rect, radius, radius)
