import os
from PySide6.QtWidgets import QLabel, QPushButton, QStyle, QStyleOptionButton, QWidget, QLayout, QLayoutItem, QScrollArea, QGraphicsOpacityEffect, QComboBox
from PySide6.QtCore import Qt, Signal, QRect, QRectF, QSize, Property, QPropertyAnimation, QEasingCurve, QTimer, QEvent
from PySide6.QtGui import QFont, QFontMetrics, QIcon, QPainter, QPalette, QColor
from PySide6.QtSvg import QSvgRenderer
from portprotonqt.theme_manager import ThemeManager
from portprotonqt.config import ui_config
from portprotonqt.qt_utils import get_device_pixel_ratio


def _is_svg_icon(icon: object) -> bool:
    return isinstance(icon, str) and icon.lower().endswith(".svg")


class CustomComboBox(QComboBox):
    def __init__(self, parent=None, theme=None):
        super().__init__(parent)
        self.theme = theme

    def contextMenuEvent(self, event):
        line_edit = self.lineEdit()
        if line_edit is None:
            super().contextMenuEvent(event)
            return

        from portprotonqt.context_menu_manager import show_themed_line_edit_context_menu

        show_themed_line_edit_context_menu(line_edit, event.globalPos(), self.theme)


def compute_layout(nat_sizes, rect_width, spacing, max_scale, center_rows=True):
    """
    Compute layout for flow arrangement.
    nat_sizes: list of tuples [(width, height), ...]
    """
    N = len(nat_sizes)
    if N == 0:
        return [], 0

    result = [[0, 0, 0, 0] for _ in range(N)]
    min_margin = 20
    available_width = rect_width - 2 * min_margin

    # Fast search for max items per row
    max_items_per_row = 1
    global_scale = 1.0
    max_row_x_start = min_margin

    i = 0
    while i < N:
        # Binary search for max items count
        left, right = 1, N - i
        best_count = 1

        while left <= right:
            mid = (left + right) // 2
            end_idx = min(i + mid, N)
            sum_w = sum(nat_sizes[j][0] for j in range(i, end_idx))
            needed_width = sum_w + spacing * (mid - 1)

            if needed_width <= available_width:
                best_count = mid
                left = mid + 1
            else:
                right = mid - 1

        count = best_count
        sum_width = sum(nat_sizes[j][0] for j in range(i, i + count))

        if count > max_items_per_row:
            max_items_per_row = count
            desired_scale = available_width / (sum_width + spacing * (count - 1)) if sum_width > 0 else 1.0
            global_scale = min(desired_scale, max_scale)
            scaled_row_width = int(sum_width * global_scale) + spacing * (count - 1)
            if center_rows:
                max_row_x_start = max(min_margin, (rect_width - scaled_row_width) // 2)

        i += count

    # Second pass: place elements
    y = 0
    i = 0

    while i < N:
        # Binary search for current row
        left, right = 1, N - i
        best_count = 1

        while left <= right:
            mid = (left + right) // 2
            end_idx = min(i + mid, N)
            sum_w = sum(nat_sizes[j][0] for j in range(i, end_idx))
            needed_width = sum_w + spacing * (mid - 1)

            if needed_width <= available_width:
                best_count = mid
                left = mid + 1
            else:
                right = mid - 1

        count = best_count
        j = i + count

        # Calculate sizes for row
        sum_width = 0
        row_max_height = 0
        for k in range(i, j):
            w, h = nat_sizes[k]
            sum_width += w
            if h > row_max_height:
                row_max_height = h

        scaled_row_width = int(sum_width * global_scale) + spacing * (count - 1)

        # Determine starting position
        if center_rows:
            if count == max_items_per_row:
                x = max(min_margin, (rect_width - scaled_row_width) // 2)
            else:
                x = max_row_x_start
        else:
            x = min_margin

        # Place elements in row
        for k in range(i, j):
            w, h = nat_sizes[k]
            new_w = int(w * global_scale)
            new_h = int(h * global_scale)
            result[k][0] = x
            result[k][1] = y
            result[k][2] = new_w
            result[k][3] = new_h
            x += new_w + spacing

        y += int(row_max_height * global_scale) + spacing
        i = j

    return result, y - spacing


class FlowLayout(QLayout):
    def __init__(self, parent=None, center_rows=True):
        super().__init__(parent)
        self.itemList = []
        self.setContentsMargins(20, 20, 20, 20)
        self._spacing = 20
        self._max_scale = 1.0
        self._center_rows = center_rows

        # Simple cache
        self._cache_width = None
        self._cache_visible_hash = None
        self._cache_result = None

    def _get_visible_data(self):
        """Return list of visible items and their sizes"""
        visible_items = []
        visible_indices = []
        visible_sizes = []

        for i, item in enumerate(self.itemList):
            widget = item.widget()
            if widget and not widget.isHidden():
                visible_items.append(item)
                visible_indices.append(i)
                s = item.sizeHint()
                visible_sizes.append((s.width(), s.height()))

        return visible_items, visible_indices, visible_sizes

    def _make_visible_hash(self, visible_sizes):
        """Create hash for change detection"""
        return hash(tuple(visible_sizes))

    def addItem(self, item: QLayoutItem) -> None:
        self.itemList.append(item)
        self._invalidate_cache()

    def takeAt(self, index: int) -> QLayoutItem:
        if 0 <= index < len(self.itemList):
            self._invalidate_cache()
            return self.itemList.pop(index)
        raise IndexError("Index out of range")

    def _invalidate_cache(self):
        self._cache_width = None
        self._cache_visible_hash = None
        self._cache_result = None

    def invalidate(self) -> None:
        self._invalidate_cache()
        super().invalidate()

    def setSpacing(self, spacing: int) -> None:
        self._spacing = spacing
        self._invalidate_cache()
        super().setSpacing(spacing)

    def count(self) -> int:
        return len(self.itemList)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self.itemList):
            return self.itemList[index]
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        _, _, visible_sizes = self._get_visible_data()

        if not visible_sizes:
            return 0

        # Check cache
        visible_hash = self._make_visible_hash(visible_sizes)
        if (self._cache_width == width and
            self._cache_visible_hash == visible_hash and
            self._cache_result is not None):
            return self._cache_result[1]

        # Calculate
        geom_array, total_height = compute_layout(
            visible_sizes,
            width,
            self._spacing,
            self._max_scale,
            self._center_rows,
        )

        # Save to cache
        self._cache_width = width
        self._cache_visible_hash = visible_hash
        self._cache_result = (geom_array, total_height)

        return total_height

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.doLayout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self.itemList:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(),
                      margins.top() + margins.bottom())
        return size

    def doLayout(self, rect, testOnly):
        N_total = len(self.itemList)
        if N_total == 0:
            return 0

        visible_items, visible_indices, visible_sizes = self._get_visible_data()

        if not visible_sizes:
            if not testOnly:
                for item in self.itemList:
                    item.setGeometry(QRect())
            return 0

        # Check cache
        visible_hash = self._make_visible_hash(visible_sizes)
        if (self._cache_width == rect.width() and
            self._cache_visible_hash == visible_hash and
            self._cache_result is not None):
            geom_array, total_height = self._cache_result
        else:
            # Calculate layout
            geom_array, total_height = compute_layout(
                visible_sizes,
                rect.width(),
                self._spacing,
                self._max_scale,
                self._center_rows,
            )

            # Save to cache
            self._cache_width = rect.width()
            self._cache_visible_hash = visible_hash
            self._cache_result = (geom_array, total_height)

        if not testOnly:
            rx, ry = rect.x(), rect.y()

            # Set geometry for visible items
            for idx, item in enumerate(visible_items):
                x, y, w, h = geom_array[idx]
                item.setGeometry(QRect(x + rx, y + ry, w, h))

            # Hide invisible items
            visible_set = set(visible_indices)
            for i in range(N_total):
                if i not in visible_set:
                    self.itemList[i].setGeometry(QRect())

        return total_height

class ClickableLabel(QLabel):
    clicked = Signal()

    def __init__(self, *args, icon=None, icon_size=16, icon_space=5, change_cursor=True, font_scale_factor=0.06, **kwargs):
        if args and isinstance(args[0], str):
            text = args[0]
            parent = kwargs.get("parent", None)
            super().__init__(text, parent)
        elif args and isinstance(args[0], QWidget):
            parent = args[0]
            text = kwargs.get("text", "")
            super().__init__(parent)
            self.setText(text)
        else:
            text = ""
            parent = kwargs.get("parent", None)
            super().__init__(text, parent)

        self._icon = icon
        self._icon_size = icon_size
        self._icon_space = icon_space
        self._base_icon_size = icon_size
        self._base_icon_space = icon_space
        self._font_scale_factor = font_scale_factor
        self._card_width = 250
        self._compact_mode = False
        self._compact_collapsed_width = 0
        self._compact_expanded_width = 0
        self._compact_relayout_callback = None
        self._animated_width = 0
        self._width_animation = QPropertyAnimation(self, b"animatedWidth")
        self._width_animation.setDuration(160)
        self._width_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        if change_cursor:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.updateFontSize()

    def setIcon(self, icon):
        self._icon = icon
        self.update()

    def icon(self):
        return self._icon

    def setIconSize(self, icon_size: int, icon_space: int):
        self._base_icon_size = icon_size
        self._base_icon_space = icon_space
        if self._compact_mode:
            self._icon_size = max(1, int(self._base_icon_size * 1.5))
            self._icon_space = 0
        else:
            self._icon_size = self._base_icon_size
            self._icon_space = self._base_icon_space
        self.update()

    def setCardWidth(self, card_width: int):
        self._card_width = card_width
        self.updateFontSize()

    def _set_animated_width(self, width: int):
        width = max(1, int(width))
        if self.width() == width:
            return
        self.setFixedWidth(width)
        self._animated_width = width
        if self._compact_relayout_callback:
            self._compact_relayout_callback()

    def _get_animated_width(self) -> int:
        if self._animated_width > 0:
            return self._animated_width
        return self.width()

    animatedWidth = Property(int, _get_animated_width, _set_animated_width)

    def _animate_width_to(self, target_width: int):
        target_width = max(1, int(target_width))
        if self.width() == target_width:
            return
        self._width_animation.stop()
        self._width_animation.setStartValue(self.width())
        self._width_animation.setEndValue(target_width)
        self._width_animation.start()

    def setCompactMode(
        self,
        enabled: bool,
        collapsed_width: int,
        expanded_width: int,
        relayout_callback=None,
    ):
        self._compact_mode = bool(enabled)
        if self._compact_mode:
            self._icon_size = max(1, int(self._base_icon_size * 1.5))
            self._icon_space = 0
            compact_min_width = self._icon_size + 8
            self._compact_collapsed_width = max(1, int(collapsed_width), compact_min_width)
            self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            self._icon_size = self._base_icon_size
            self._icon_space = self._base_icon_space
            self._compact_collapsed_width = max(0, int(collapsed_width))
        self._compact_expanded_width = max(self._compact_collapsed_width, int(expanded_width))
        self._compact_relayout_callback = relayout_callback

        if self._compact_mode:
            target_width = self._compact_expanded_width if self.underMouse() else self._compact_collapsed_width
        else:
            target_width = self._compact_expanded_width
        self._set_animated_width(target_width)
        self.update()

    def setCompactRelayoutCallback(self, relayout_callback):
        self._compact_relayout_callback = relayout_callback

    def updateFontSize(self):
        font = self.font()
        font_size = int(self._card_width * self._font_scale_factor)
        font.setPointSize(max(8, font_size))
        self.setFont(font)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.contentsRect()
        alignment = self.alignment()
        icon_size = self._icon_size
        spacing = self._icon_space
        text = self.text()

        has_icon = bool(self._icon)
        if has_icon and not _is_svg_icon(self._icon):
            device_pixel_ratio = get_device_pixel_ratio()
            if isinstance(self._icon, str):
                pixmap = QIcon(self._icon).pixmap(
                    QSize(icon_size, icon_size),
                    device_pixel_ratio,
                )
            elif isinstance(self._icon, QIcon):
                pixmap = self._icon.pixmap(
                    QSize(icon_size, icon_size),
                    device_pixel_ratio,
                )
            else:
                pixmap = None
        else:
            pixmap = None

        fm = QFontMetrics(self.font())
        available_width = rect.width()
        if has_icon:
            available_width -= (icon_size + spacing)
        available_width = max(0, available_width - 4)
        display_text = fm.elidedText(text, Qt.TextElideMode.ElideRight, available_width)
        text_width = fm.horizontalAdvance(display_text)
        text_height = fm.height()
        if has_icon and not display_text:
            text_height = icon_size
        total_width = text_width + (icon_size + spacing if has_icon else 0)

        if alignment & Qt.AlignmentFlag.AlignHCenter:
            x = rect.left() + (rect.width() - total_width) // 2
        elif alignment & Qt.AlignmentFlag.AlignRight:
            x = rect.right() - total_width
        else:
            x = rect.left()
        y = rect.top() + (rect.height() - text_height) // 2

        if isinstance(self._icon, str) and _is_svg_icon(self._icon):
            icon_rect = QRect(x, y + (text_height - icon_size) // 2, icon_size, icon_size)
            QSvgRenderer(self._icon).render(painter, QRectF(icon_rect))
            text_x = x + icon_size + spacing
        elif pixmap:
            icon_rect = QRect(x, y + (text_height - icon_size) // 2, icon_size, icon_size)
            painter.drawPixmap(icon_rect, pixmap)
            text_x = x + icon_size + spacing
        else:
            text_x = x

        text_rect = QRect(text_x, y, text_width, text_height)
        self.style().drawItemText(
            painter,
            text_rect,
            alignment,
            self.palette(),
            self.isEnabled(),
            display_text,
            self.foregroundRole(),
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
        else:
            super().mousePressEvent(event)

    def enterEvent(self, event):
        if self._compact_mode:
            self._animate_width_to(self._compact_expanded_width)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._compact_mode:
            self._animate_width_to(self._compact_collapsed_width)
        super().leaveEvent(event)

class AutoSizeButton(QPushButton):
    def _normalize_padding(self, padding):
        if isinstance(padding, int):
            return (padding, padding, padding, padding)
        if isinstance(padding, (tuple, list)):
            if len(padding) == 2:
                v, h = padding
                return (v, v, h, h)   # top=bottom=v, left=right=h
            elif len(padding) == 4:
                return tuple(padding)
            else:
                raise ValueError("padding must be tuple of 2 or 4 values")
        raise TypeError("padding must be int or tuple/list")

    def __init__(self, *args, icon=None, icon_size=16,
                 min_font_size=6, max_font_size=14, padding=None, update_size=True, **kwargs):
        if args and isinstance(args[0], str):
            text = args[0]
            parent = kwargs.get("parent", None)
            super().__init__(text, parent)
        elif args and isinstance(args[0], QWidget):
            parent = args[0]
            text = kwargs.get("text", "")
            super().__init__(text, parent)
        else:
            text = ""
            parent = kwargs.get("parent", None)
            super().__init__(text, parent)

        self.theme_manager = ThemeManager()
        selected_theme = ui_config.get_theme()
        self.current_theme_name = selected_theme
        self.theme = self.theme_manager.apply_theme(selected_theme)

        self._uses_theme_padding = padding is None
        if self._uses_theme_padding:
            padding = getattr(self.theme, 'autoSizeButtonPadding', 20)

        self._pad_top, self._pad_bottom, self._pad_left, self._pad_right = self._normalize_padding(padding)

        self._icon = icon
        self._icon_size = icon_size
        self._alignment = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        self._min_font_size = min_font_size
        self._max_font_size = max_font_size
        self._update_size = update_size
        self._original_font = self.font()
        self._original_text = self.text()

        self._icon_name = self._extract_icon_name(icon)

        if self._icon:
            self.setIcon(self._icon)

        self.setMouseTracking(True)

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setMinimumWidth(50)

        self.adjustFontSize()

    def refresh_theme(self, theme: object) -> None:
        """Refresh sizing values supplied by the active theme."""
        self.theme = theme
        if not self._uses_theme_padding:
            return
        padding = getattr(theme, "autoSizeButtonPadding", 20)
        self._pad_top, self._pad_bottom, self._pad_left, self._pad_right = (
            self._normalize_padding(padding)
        )
        self.adjustFontSize()
        self.updateGeometry()

    def _extract_icon_name(self, icon_path):
        if isinstance(icon_path, str):
            base = os.path.basename(icon_path)
            name, _ = os.path.splitext(base)
            return name
        return None

    def _get_icon_color(self):
        state = None
        if not self.isEnabled():
            state = "disabled"
        elif self.isDown():
            state = "pressed"
        elif self.hasFocus():
            state = "focused"
        elif self.underMouse():
            state = "hover"

        colors_dict = getattr(self.theme, 'ICON_COLORS', {})

        keys = []
        if state:
            if self._icon_name:
                keys.append(f"{self._icon_name}_{state}")
            keys.append(f"*_{state}")
        if self._icon_name:
            keys.append(self._icon_name)

        for key in keys:
            color = colors_dict.get(key)
            if color is not None:
                return color

        return None

    def setAlignment(self, alignment):
        self._alignment = alignment
        self.update()

    def alignment(self):
        return self._alignment

    def rawIcon(self) -> object | None:
        return self._icon

    def setIcon(self, icon: object) -> None:
        self._icon = icon
        self._icon_name = self._extract_icon_name(icon)
        if _is_svg_icon(icon):
            super().setIcon(QIcon())
        elif isinstance(icon, str):
            super().setIcon(QIcon(icon))
        elif isinstance(icon, QIcon):
            super().setIcon(icon)
        else:
            super().setIcon(QIcon())
        self.setIconSize(QSize(self._icon_size, self._icon_size))
        self.update()

    def paintEvent(self, event):
        icon_color = self._get_icon_color()
        if not self._icon and icon_color:
            option = QStyleOptionButton()
            self.initStyleOption(option)
            text = option.text
            option.text = ""
            painter = QPainter(self)
            self.style().drawControl(QStyle.ControlElement.CE_PushButton, option, painter, self)
            rect = self.style().subElementRect(
                QStyle.SubElement.SE_PushButtonContents,
                option,
                self,
            )
            painter.setPen(QColor(icon_color))
            painter.drawText(rect, self._alignment, text)
            painter.end()
            return

        if not _is_svg_icon(self._icon):
            super().paintEvent(event)
            return

        icon_path = self._icon
        if not isinstance(icon_path, str):
            super().paintEvent(event)
            return

        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ""
        option.icon = QIcon()
        painter = QPainter(self)
        self.style().drawControl(QStyle.ControlElement.CE_PushButton, option, painter, self)

        rect = self.style().subElementRect(
            QStyle.SubElement.SE_PushButtonContents,
            option,
            self,
        )

        if icon_color and self._icon_name:
            colored_path = self.theme_manager.get_colored_icon_path(
                icon_path,
                icon_color,
                self.current_theme_name
            )
            if colored_path and os.path.exists(colored_path):
                icon_path = colored_path

        fm = QFontMetrics(self.font())
        text = self.text()
        text_width = fm.horizontalAdvance(text) if text else 0
        icon_spacing = self._icon_size // 2 if text else 0
        total_width = self._icon_size + icon_spacing + text_width
        x = rect.left() + (rect.width() - total_width) // 2
        icon_y = rect.top() + (rect.height() - self._icon_size) // 2
        icon_rect = QRect(x, icon_y, self._icon_size, self._icon_size)

        renderer = QSvgRenderer(icon_path)
        if renderer.isValid():
            renderer.render(painter, QRectF(icon_rect))

        text_rect = QRect(x + self._icon_size + icon_spacing, rect.top(), text_width, rect.height())

        if icon_color:
            painter.setPen(QColor(icon_color))
        else:
            painter.setPen(self.palette().color(QPalette.ColorRole.ButtonText))
        painter.drawText(text_rect, self._alignment, text)

        painter.end()

    def setText(self, text):
        self._original_text = text
        if not self._update_size:
            super().setText(text)
        else:
            super().setText(text)
            self.adjustFontSize()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._update_size:
            self.adjustFontSize()

    def adjustFontSize(self):
        if not self._original_text:
            return

        if not self._update_size:
            return

        available_width = self.width()
        if self._icon:
            available_width -= self._icon_size

        margins = self.contentsMargins()
        available_width -= (margins.left() + margins.right() + self._pad_left + self._pad_right)

        font = QFont(self._original_font)
        text = self._original_text

        chosen_size = self._max_font_size
        for font_size in range(self._max_font_size, self._min_font_size - 1, -1):
            font.setPointSize(font_size)
            fm = QFontMetrics(font)
            text_width = fm.horizontalAdvance(text)
            if text_width <= available_width:
                chosen_size = font_size
                break

        font.setPointSize(chosen_size)
        self.setFont(font)

        fm = QFontMetrics(font)
        text_width = fm.horizontalAdvance(text)
        required_width = text_width + margins.left() + margins.right() + self._pad_left + self._pad_right
        if self._icon:
            required_width += self._icon_size

        if self.width() < required_width:
            self.setMinimumWidth(required_width)

        super().setText(text)

    def sizeHint(self):
        if not self._update_size:
            return super().sizeHint()
        else:
            font = self.font()
            fm = QFontMetrics(font)
            text_width = fm.horizontalAdvance(self._original_text)
            margins = self.contentsMargins()
            width = text_width + margins.left() + margins.right() + self._pad_left + self._pad_right
            if self._icon:
                width += self._icon_size
            height = fm.height() + margins.top() + margins.bottom() + self._pad_top + self._pad_bottom
            return QSize(width, height)

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

class NavLabel(QLabel):
    clicked = Signal()

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self._checkable = False
        self._isChecked = False
        self.setProperty("checked", self._isChecked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def setCheckable(self, checkable):
        self._checkable = checkable

    def setChecked(self, checked):
        if self._checkable:
            self._isChecked = checked
            self.setProperty("checked", checked)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()

    def isChecked(self):
        return self._isChecked

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            if self._checkable:
                self.setChecked(not self._isChecked)
            self.clicked.emit()
            event.accept()
        else:
            super().mousePressEvent(event)

class AutoHideScrollArea(QScrollArea):
    def __init__(
        self,
        theme,
        parent: QWidget | None = None,
        hide_delay_ms: int = 1000,
        fade_duration_ms: int = 200,
    ):
        self.theme = theme
        self.theme_manager = ThemeManager()

        super().__init__(parent)
        self.hide_delay_ms = hide_delay_ms
        self.fade_duration_ms = fade_duration_ms

        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setStyleSheet(self.theme.TRANSPARENT_BACKGROUND_STYLE)

        self._v_scrollbar = self.verticalScrollBar()
        self._h_scrollbar = self.horizontalScrollBar()
        self._v_scrollbar.installEventFilter(self)
        self._h_scrollbar.installEventFilter(self)

        self._opacity_effect = QGraphicsOpacityEffect(self._v_scrollbar)
        self._opacity_effect.setOpacity(0.0)
        self._v_scrollbar.setGraphicsEffect(self._opacity_effect)

        self._h_opacity_effect = QGraphicsOpacityEffect(self._h_scrollbar)
        self._h_opacity_effect.setOpacity(0.0)
        self._h_scrollbar.setGraphicsEffect(self._h_opacity_effect)

        self._fade_animation = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_animation.setDuration(self.fade_duration_ms)
        self._fade_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)

        self._h_fade_animation = QPropertyAnimation(self._h_opacity_effect, b"opacity")
        self._h_fade_animation.setDuration(self.fade_duration_ms)
        self._h_fade_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)

        self._is_visible = False
        self._scroll_needed = False
        self._h_is_visible = False
        self._h_scroll_needed = False

        self._apply_visible_style()

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._start_fade_out)

        self._h_hide_timer = QTimer(self)
        self._h_hide_timer.setSingleShot(True)
        self._h_hide_timer.timeout.connect(self._start_horizontal_fade_out)

        self._v_scrollbar.valueChanged.connect(self._on_scroll)
        self._h_scrollbar.valueChanged.connect(self._on_horizontal_scroll)

        self.viewport().installEventFilter(self)
        initial_widget = self.widget()
        if initial_widget is not None:
            initial_widget.installEventFilter(self)

        QTimer.singleShot(0, self._update_scroll_needed)

    def _apply_visible_style(self) -> None:
        self._v_scrollbar.setStyleSheet(self.theme.SCROLL_STYLE)
        self._h_scrollbar.setStyleSheet(self.theme.SCROLL_STYLE)

    def _start_horizontal_fade_in(self) -> None:
        if not self._h_scroll_needed:
            return
        self._h_fade_animation.stop()
        self._h_fade_animation.setStartValue(self._h_opacity_effect.opacity())
        self._h_fade_animation.setEndValue(1.0)
        self._h_fade_animation.start()
        self._h_is_visible = True

    def _start_horizontal_fade_out(self) -> None:
        if not self._h_scroll_needed:
            return
        self._h_fade_animation.stop()
        self._h_fade_animation.setStartValue(self._h_opacity_effect.opacity())
        self._h_fade_animation.setEndValue(0.0)
        self._h_fade_animation.start()
        self._h_is_visible = False

    def _start_fade_in(self) -> None:
        if not self._scroll_needed:
            return
        self._fade_animation.stop()
        self._fade_animation.setStartValue(self._opacity_effect.opacity())
        self._fade_animation.setEndValue(1.0)
        self._fade_animation.start()
        self._is_visible = True

    def _start_fade_out(self) -> None:
        if not self._scroll_needed:
            return
        self._fade_animation.stop()
        self._fade_animation.setStartValue(self._opacity_effect.opacity())
        self._fade_animation.setEndValue(0.0)
        self._fade_animation.start()
        self._is_visible = False

    def _set_opacity_immediately(self, opacity: float) -> None:
        self._fade_animation.stop()
        self._opacity_effect.setOpacity(opacity)
        self._is_visible = opacity == 1.0

    def _set_horizontal_opacity_immediately(self, opacity: float) -> None:
        self._h_fade_animation.stop()
        self._h_opacity_effect.setOpacity(opacity)
        self._h_is_visible = opacity == 1.0

    def _update_scroll_needed(self) -> None:
        widget = self.widget()
        if widget is None:
            self._scroll_needed = False
            self._h_scroll_needed = False
            self._set_opacity_immediately(0.0)
            self._set_horizontal_opacity_immediately(0.0)
            self._hide_timer.stop()
            self._h_hide_timer.stop()
            return

        content_height = widget.sizeHint().height()
        content_width = widget.sizeHint().width()
        viewport_height = self.viewport().height()
        viewport_width = self.viewport().width()
        self._scroll_needed = content_height > viewport_height
        self._h_scroll_needed = content_width > viewport_width

        if not self._scroll_needed:
            self._set_opacity_immediately(0.0)
            self._hide_timer.stop()
        else:
            if not self._is_visible:
                self._set_opacity_immediately(0.0)

        if not self._h_scroll_needed:
            self._set_horizontal_opacity_immediately(0.0)
            self._h_hide_timer.stop()
        elif not self._h_is_visible:
            self._set_horizontal_opacity_immediately(0.0)

    def _on_scroll(self, value: int) -> None:
        if not self._scroll_needed:
            return
        self._start_fade_in()
        self._hide_timer.start(self.hide_delay_ms)

    def _on_horizontal_scroll(self, value: int) -> None:
        if not self._h_scroll_needed:
            return
        self._start_horizontal_fade_in()
        self._h_hide_timer.start(self.hide_delay_ms)

    def enterEvent(self, event):
        if self._scroll_needed:
            self._start_fade_in()
            self._hide_timer.start(self.hide_delay_ms)
        if self._h_scroll_needed:
            self._start_horizontal_fade_in()
            self._h_hide_timer.start(self.hide_delay_ms)

    def leaveEvent(self, event):
        if self._scroll_needed and self._is_visible:
            self._hide_timer.start(self.hide_delay_ms)
        if self._h_scroll_needed and self._h_is_visible:
            self._h_hide_timer.start(self.hide_delay_ms)

    def eventFilter(self, obj, event):
        if not hasattr(self, "_v_scrollbar") or not hasattr(self, "_h_scrollbar"):
            return super().eventFilter(obj, event)

        if event.type() == QEvent.Type.Resize:
            self._update_scroll_needed()
        elif obj == self._v_scrollbar:
            if event.type() == QEvent.Type.Enter:
                if self._scroll_needed:
                    self._start_fade_in()
                    self._hide_timer.start(self.hide_delay_ms)
            elif event.type() == QEvent.Type.Leave:
                if self._scroll_needed and self._is_visible:
                    self._hide_timer.start(self.hide_delay_ms)
        elif obj == self._h_scrollbar:
            if event.type() == QEvent.Type.Enter:
                if self._h_scroll_needed:
                    self._start_horizontal_fade_in()
                    self._h_hide_timer.start(self.hide_delay_ms)
            elif event.type() == QEvent.Type.Leave:
                if self._h_scroll_needed and self._h_is_visible:
                    self._h_hide_timer.start(self.hide_delay_ms)
        return super().eventFilter(obj, event)

    def setWidget(self, widget: QWidget | None) -> None:
        old_widget = self.widget()
        if old_widget is not None:
            old_widget.removeEventFilter(self)

        if widget is None:
            super().setWidget(None)  # type: ignore
        else:
            super().setWidget(widget)
            widget.installEventFilter(self)

        self._update_scroll_needed()
