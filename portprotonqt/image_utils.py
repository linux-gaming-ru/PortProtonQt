import os
import re
from weakref import WeakKeyDictionary
from PySide6.QtGui import QPen, QColor, QPixmap, QPainter, QPainterPath, QImageReader, QMovie, QBitmap
from PySide6.QtCore import (
    Qt, QFile, QEvent, QByteArray, QEasingCurve, QPropertyAnimation, QSize, QObject, QTimer
)
from PySide6.QtWidgets import QGraphicsItem, QToolButton, QFrame, QLabel, QGraphicsScene, QHBoxLayout, QWidget, QGraphicsView, QVBoxLayout, QSizePolicy
from PySide6.QtWidgets import QSpacerItem, QGraphicsPixmapItem, QDialog, QApplication
from PIL import Image, ImageQt, ImageSequence
from portprotonqt.config import CACHE_DIR, ui_config
from portprotonqt.theme_manager import ThemeManager, load_theme
from portprotonqt.downloader import Downloader
from portprotonqt.icon_extractor import generate_thumbnail
from portprotonqt.logger import get_logger
from portprotonqt.qt_utils import get_device_pixel_ratio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
import threading

downloader = Downloader()
logger = get_logger(__name__)
COVER_IMAGE_EXTENSIONS = (".png", ".apng", ".jpg", ".jpeg", ".gif", ".webp", ".jxl", ".svg")
DEFAULT_ANIMATION_DELAY_MS = 100
REMOTE_COVER_DOWNLOAD_TIMEOUT = 15

# Global queue and thread pool for image loading
image_load_queue = Queue()
image_executor = ThreadPoolExecutor(max_workers=4)
queue_lock = threading.Lock()

def is_animated_cover(path: str) -> bool:
    """Return True when path points to an animated cover image."""
    ext = os.path.splitext(path)[1].lower()
    if not path or ext not in COVER_IMAGE_EXTENSIONS:
        return False
    if not QFile.exists(path):
        return False
    reader = QImageReader(path)
    return reader.supportsAnimation() and reader.imageCount() != 1


def _is_png_cover(path: str) -> bool:
    reader = QImageReader(path)
    return bytes(reader.format().data()).decode("ascii", "ignore").lower() == "png"


def _set_cover_mask(label: QLabel, width: int, height: int, radius: int) -> None:
    if radius <= 0:
        label.clearMask()
        return
    mask = QBitmap(max(width, 1), max(height, 1))
    mask.fill(Qt.GlobalColor.color0)
    painter = QPainter(mask)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(Qt.GlobalColor.color1)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(0, 0, mask.width(), mask.height(), radius, radius)
    painter.end()
    label.setMask(mask)


class _PillowAnimatedCover(QObject):
    def __init__(self, label: QLabel, path: str, width: int, height: int, radius: int) -> None:
        super().__init__(label)
        self.label = label
        self.path = path
        self.width = width
        self.height = height
        self.radius = radius
        self.image: Image.Image | None = None
        self.image_iterator = None
        self.current_frame: Image.Image | None = None
        self.paused = False
        self.suspended = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._show_next_frame)
        self.destroyed.connect(self._close_image)
        self.label.installEventFilter(self)

    def start(self) -> bool:
        if not self._open_image():
            return False
        delay = self._apply_next_frame()
        self.set_paused(not self.label.isVisible())
        if not self.paused:
            self.timer.start(delay)
        return True

    def set_scaled_size(self, width: int, height: int) -> None:
        if self.width == width and self.height == height:
            _set_cover_mask(self.label, width, height, self.radius)
            return
        self.width = width
        self.height = height
        _set_cover_mask(self.label, width, height, self.radius)
        if self.current_frame is not None:
            pixmap, _delay = self._convert_frame(self.current_frame)
            if not pixmap.isNull():
                self.label.setPixmap(pixmap)

    def stop(self) -> None:
        self.timer.stop()
        self._close_image()

    def set_paused(self, paused: bool) -> None:
        if self.paused == paused:
            return
        self.paused = paused
        if paused:
            self.timer.stop()
            return
        if self.suspended:
            return
        if self.image_iterator is None and not self._open_image():
            return
        self.timer.start(self._apply_next_frame())

    def set_suspended(self, suspended: bool) -> None:
        if self.suspended == suspended:
            return
        self.suspended = suspended
        if suspended:
            self.timer.stop()
            self._close_image()
            return
        if self.paused or not self.label.isVisible():
            return
        if not self._open_image():
            return
        self.timer.start(self._apply_next_frame())

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched != self.label:
            return super().eventFilter(watched, event)
        if event.type() == QEvent.Type.Hide:
            self.set_paused(True)
        elif event.type() == QEvent.Type.Show:
            QTimer.singleShot(0, self._resume_if_visible)
        return super().eventFilter(watched, event)

    def _resume_if_visible(self) -> None:
        try:
            if self.suspended:
                return
            self.set_paused(not self.label.isVisible())
        except RuntimeError:
            self.stop()

    def _open_image(self) -> bool:
        self._close_image()
        try:
            image = Image.open(self.path)
            if not getattr(image, "is_animated", False) or getattr(image, "n_frames", 1) == 1:
                image.close()
                return False
            self.image = image
            self.image_iterator = ImageSequence.Iterator(image)
            return True
        except OSError as e:
            logger.warning("Failed to load animated cover from %s: %s", self.path, e)
            return False

    def _close_image(self) -> None:
        if self.current_frame is not None:
            self.current_frame.close()
            self.current_frame = None
        if self.image is not None:
            self.image.close()
            self.image = None
        self.image_iterator = None

    def _convert_frame(self, frame: Image.Image) -> tuple[QPixmap, int]:
        duration = int(frame.info.get("duration", DEFAULT_ANIMATION_DELAY_MS))
        image = frame.convert("RGBA").resize(
            (max(self.width, 1), max(self.height, 1)),
            Image.Resampling.BILINEAR,
        )
        pixmap = QPixmap.fromImage(ImageQt.toqimage(image))
        image.close()
        return pixmap, duration

    def _show_next_frame(self) -> None:
        if self.suspended:
            return
        if self.paused or not self.label.isVisible():
            self.set_paused(True)
            return
        if self.image_iterator is None:
            return
        delay = self._apply_next_frame()
        self.timer.start(delay)

    def _apply_next_frame(self) -> int:
        if self.image_iterator is None:
            return DEFAULT_ANIMATION_DELAY_MS
        try:
            frame = next(self.image_iterator)
        except StopIteration:
            if not self._open_image() or self.image_iterator is None:
                return DEFAULT_ANIMATION_DELAY_MS
            frame = next(self.image_iterator)
        if self.current_frame is not None:
            self.current_frame.close()
        self.current_frame = frame.copy()
        pixmap, delay = self._convert_frame(self.current_frame)
        if not pixmap.isNull():
            self.label.setPixmap(pixmap)
        return delay


_animated_cover_movies: WeakKeyDictionary[QLabel, QMovie | _PillowAnimatedCover] = WeakKeyDictionary()
_animated_cover_radii: WeakKeyDictionary[QLabel, int] = WeakKeyDictionary()


def set_animated_cover(label: QLabel, path: str, width: int, height: int, radius: int = 0) -> bool:
    """Set animated cover movie on QLabel."""
    cleanup_animated_cover(label)
    ext = os.path.splitext(path)[1].lower()
    if not path or ext not in COVER_IMAGE_EXTENSIONS:
        return False
    if not QFile.exists(path):
        return False
    if ext in (".png", ".apng") and _is_png_cover(path):
        _set_cover_mask(label, width, height, radius)
        animation = _PillowAnimatedCover(label, path, width, height, radius)
        if not animation.start():
            return False
        _animated_cover_movies[label] = animation
        _animated_cover_radii[label] = radius
        return True
    if not is_animated_cover(path):
        return False
    movie = QMovie(path, QByteArray(), label)
    if not movie.isValid():
        logger.warning("Failed to load animated cover from %s", path)
        return False
    movie.setCacheMode(QMovie.CacheMode.CacheNone)
    movie.setScaledSize(QSize(width, height))
    _set_cover_mask(label, width, height, radius)
    _animated_cover_movies[label] = movie
    _animated_cover_radii[label] = radius
    label.setMovie(movie)
    movie.start()
    return True


def cleanup_animated_cover(label: QLabel) -> None:
    """Stop and remove animated cover from QLabel."""
    movie = _animated_cover_movies.pop(label, None)
    _animated_cover_radii.pop(label, None)
    if movie is None:
        return
    try:
        if isinstance(movie, _PillowAnimatedCover):
            movie.stop()
        else:
            movie.stop()
        label.clear()
        label.clearMask()
        movie.deleteLater()
    except RuntimeError:
        pass


def set_animated_cover_paused(label: QLabel, paused: bool) -> None:
    """Pause or resume animated cover playback."""
    movie = _animated_cover_movies.get(label)
    if movie is None:
        return
    try:
        if isinstance(movie, _PillowAnimatedCover):
            movie.set_paused(paused)
            return
        if paused:
            movie.setPaused(True)
        elif movie.state() == QMovie.MovieState.NotRunning:
            movie.start()
        else:
            movie.setPaused(False)
    except RuntimeError:
        pass


def set_animated_cover_suspended(label: QLabel, suspended: bool) -> None:
    """Suspend animated cover playback and release decoder resources."""
    movie = _animated_cover_movies.get(label)
    if movie is None:
        return
    try:
        if isinstance(movie, _PillowAnimatedCover):
            movie.set_suspended(suspended)
            return
        if suspended:
            movie.stop()
            return
        if label.isVisible():
            label.setMovie(movie)
            movie.start()
    except RuntimeError:
        pass


def set_all_animated_covers_suspended(suspended: bool) -> None:
    """Suspend or resume all animated covers."""
    for label in list(_animated_cover_movies.keys()):
        set_animated_cover_suspended(label, suspended)


def cleanup_widget_animated_covers(widget: QWidget) -> None:
    """Stop animated covers under widget."""
    if isinstance(widget, QLabel):
        cleanup_animated_cover(widget)
    for label in widget.findChildren(QLabel):
        cleanup_animated_cover(label)


def update_animated_cover_size(label: QLabel, width: int, height: int, radius: int = 0) -> None:
    """Update animated cover movie size for QLabel."""
    movie = _animated_cover_movies.get(label)
    if movie is not None:
        _animated_cover_radii[label] = radius
        if isinstance(movie, _PillowAnimatedCover):
            movie.radius = radius
            movie.set_scaled_size(width, height)
            return
        movie.setScaledSize(QSize(width, height))
        _set_cover_mask(label, width, height, radius)


def get_animated_cover_pixmap(label: QLabel) -> QPixmap | None:
    """Return current animated cover frame for palette extraction."""
    movie = _animated_cover_movies.get(label)
    if movie is None:
        return label.pixmap()
    if isinstance(movie, _PillowAnimatedCover):
        return label.pixmap()
    pixmap = movie.currentPixmap()
    if pixmap.isNull() and movie.jumpToFrame(0):
        pixmap = movie.currentPixmap()
    return None if pixmap.isNull() else pixmap


def get_animated_cover_movie(label: QLabel) -> QMovie | _PillowAnimatedCover | None:
    """Return animated cover movie for QLabel."""
    return _animated_cover_movies.get(label)


def _get_cover_url_suffix(cover: str) -> str:
    """Return supported image suffix from URL path."""
    suffix = os.path.splitext(cover.split("?", 1)[0])[1].lower()
    if suffix in COVER_IMAGE_EXTENSIONS:
        return suffix
    return ".jpg"


def _get_ppdb_autoinstall_image_name(cover: str) -> str:
    match = re.search(r"/game_(\d+)_(icon|library)_", cover)
    if not match:
        return ""
    game_id, image_type = match.groups()
    suffix = _get_cover_url_suffix(cover)
    if image_type == "icon":
        return f"{game_id}_compat{suffix}"
    return f"{game_id}{suffix}"


def clear_ppdb_autoinstall_image_cache(cover_urls: list[str]) -> None:
    image_folder = str(CACHE_DIR / "images")
    for cover in cover_urls:
        filename = _get_ppdb_autoinstall_image_name(cover)
        if not filename:
            continue
        local_path = os.path.join(image_folder, filename)
        try:
            if os.path.exists(local_path):
                os.remove(local_path)
        except OSError as e:
            logger.warning("Failed to remove cached PPDB image %s: %s", local_path, e)


def load_pixmap_async(
    cover: str,
    width: int,
    height: int,
    callback: Callable[[QPixmap], None],
    app_name: str = "",
    fallback_cover: str = "",
    fallback_exe: str = "",
    fallback_icon_path: str = "",
):
    """
    Asynchronously load cover through task queue.
    """
    def process_image():
        theme_manager = ThemeManager()
        current_theme_name = ui_config.get_theme()
        theme = theme_manager.current_theme_module or load_theme(current_theme_name)

        def finish_with(pixmap: QPixmap):
            # Check if pixmap is valid before attempting to scale it
            if pixmap.isNull():
                # Create a default placeholder pixmap instead of trying to scale a null pixmap
                placeholder_pixmap = QPixmap(width, height)
                placeholder_pixmap.fill(QColor(theme.color_placeholder_bg))
                painter = QPainter(placeholder_pixmap)
                painter.setPen(QPen(QColor(theme.color_white)))
                painter.drawText(placeholder_pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "No Image")
                painter.end()
                callback(placeholder_pixmap)
            else:
                scaled = pixmap.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                x = (scaled.width() - width) // 2
                y = (scaled.height() - height) // 2
                cropped = scaled.copy(x, y, width, height)
                callback(cropped)

        def load_fallback_pixmap() -> QPixmap:
            pixmap = QPixmap()
            if fallback_cover and QFile.exists(fallback_cover):
                pixmap.load(fallback_cover)
                if not pixmap.isNull():
                    return pixmap
                logger.warning(f"Failed to load fallback image from {fallback_cover}")
            exe_icon = load_exe_icon_pixmap()
            if not exe_icon.isNull():
                return exe_icon
            placeholder_path = theme_manager.get_theme_image("placeholder", current_theme_name)
            if placeholder_path and QFile.exists(placeholder_path):
                pixmap.load(placeholder_path)
                if pixmap.isNull():
                    logger.warning(f"Failed to load placeholder image from {placeholder_path}")
                return pixmap
            pixmap = QPixmap(width, height)
            pixmap.fill(QColor(theme.color_placeholder_bg))
            painter = QPainter(pixmap)
            painter.setPen(QPen(QColor(theme.color_white)))
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "No Image")
            painter.end()
            return pixmap

        def load_exe_icon_pixmap() -> QPixmap:
            pixmap = QPixmap()
            if not fallback_exe or not os.path.isfile(fallback_exe):
                return pixmap
            if not fallback_exe.lower().endswith(".exe"):
                return pixmap
            icon_path = fallback_icon_path
            if not icon_path:
                return pixmap
            if not os.path.exists(icon_path):
                os.makedirs(os.path.dirname(icon_path), exist_ok=True)
                if not generate_thumbnail(fallback_exe, icon_path, size=128):
                    return pixmap
            pixmap.load(icon_path)
            return pixmap

        image_folder = str(CACHE_DIR / "images")
        os.makedirs(image_folder, exist_ok=True)

        if cover and cover.startswith("https://steamcdn-a.akamaihd.net/steam/apps/"):
            try:
                parts = cover.split("/")
                appid = None
                if "apps" in parts:
                    idx = parts.index("apps")
                    if idx + 1 < len(parts):
                        appid = parts[idx + 1]
                if appid:
                    local_path = os.path.join(image_folder, f"{appid}.jpg")
                    if os.path.exists(local_path):
                        pixmap = QPixmap(local_path)
                        # Check if the pixmap loaded successfully
                        if pixmap.isNull():
                            logger.warning(f"Failed to load image from {local_path}, removing corrupted file")
                            os.remove(local_path)
                        else:
                            finish_with(pixmap)
                            return

                    def on_downloaded(result: str | None):
                        pixmap = QPixmap()
                        if result and os.path.exists(result):
                            pixmap.load(result)
                        if pixmap.isNull():
                            return
                        finish_with(pixmap)

                    finish_with(load_fallback_pixmap())
                    downloader.download_async(
                        cover, local_path,
                        timeout=REMOTE_COVER_DOWNLOAD_TIMEOUT,
                        callback=on_downloaded,
                    )
                    return
            except Exception as e:
                logger.error(f"URL processing error {cover}: {e}")

        # SteamGridDB (SGDB)
        if cover and cover.startswith("https://cdn2.steamgriddb.com"):
            try:
                parts = cover.split("/")
                filename = parts[-1] if parts else "sgdb_cover.png"
                # SGDB links contain unique hash in name - use as filename
                local_path = os.path.join(image_folder, filename)

                logger.debug("SGDB cover check: %s exists=%s", local_path, os.path.exists(local_path))
                if os.path.exists(local_path):
                    pixmap = QPixmap(local_path)
                    # Check if the pixmap loaded successfully
                    if pixmap.isNull():
                        logger.warning(f"Failed to load image from {local_path}, removing corrupted file")
                        os.remove(local_path)
                    else:
                        logger.debug("SGDB cover loaded from cache: %s", filename)
                        finish_with(pixmap)
                        return

                def on_downloaded(result: str | None):
                    pixmap = QPixmap()
                    if result and os.path.exists(result):
                        pixmap.load(result)
                    if pixmap.isNull():
                        return
                    finish_with(pixmap)

                logger.info("Downloading SGDB cover for %s -> %s", app_name or "unknown", filename)
                finish_with(load_fallback_pixmap())
                downloader.download_async(
                    cover, local_path,
                    timeout=REMOTE_COVER_DOWNLOAD_TIMEOUT,
                    callback=on_downloaded,
                )
                return

            except Exception as e:
                logger.error(f"SGDB URL processing error {cover}: {e}")

        if cover and cover.startswith(("http://", "https://")):
            try:
                filename = _get_ppdb_autoinstall_image_name(cover)
                if not filename:
                    filename = f"{app_name}{_get_cover_url_suffix(cover)}"
                local_path = os.path.join(image_folder, filename)
                if os.path.exists(local_path):
                    pixmap = QPixmap(local_path)
                    # Check if the pixmap loaded successfully
                    if pixmap.isNull():
                        logger.warning(f"Failed to load image from {local_path}, removing corrupted file")
                        os.remove(local_path)
                    else:
                        finish_with(pixmap)
                        return

                def on_downloaded(result: str | None):
                    pixmap = QPixmap()
                    if result and os.path.exists(result):
                        pixmap.load(result)
                    if pixmap.isNull():
                        return
                    finish_with(pixmap)

                finish_with(load_fallback_pixmap())
                downloader.download_async(
                    cover, local_path,
                    timeout=REMOTE_COVER_DOWNLOAD_TIMEOUT,
                    callback=on_downloaded,
                )
                return
            except Exception as e:
                logger.error("Error processing remote image URL %s: %s", cover, str(e))

        if cover and QFile.exists(cover):
            pixmap = QPixmap(cover)
            # Check if the pixmap loaded successfully
            if pixmap.isNull():
                logger.warning(f"Failed to load image from {cover}")
                # Remove corrupted file only if it's in the cache directory
                if cover.startswith(image_folder):
                    logger.warning(f"Removing corrupted cached file {cover}")
                    os.remove(cover)
            else:
                finish_with(pixmap)
                return

        pixmap = load_fallback_pixmap()
        finish_with(pixmap)

    # Submit the process_image function directly to the executor
    # This avoids the potential blocking issue with queue.get() in PySide 6.10.1
    image_executor.submit(process_image)

def round_corners(pixmap, radius):
    """
    Return QPixmap with rounded corners.
    """
    if pixmap.isNull():
        return pixmap

    # Check if radius is valid to prevent issues
    if radius <= 0:
        return pixmap

    size = pixmap.size()
    if size.width() <= 0 or size.height() <= 0:
        return pixmap

    rounded = QPixmap(size)
    rounded.fill(QColor(0, 0, 0, 0))
    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, size.width(), size.height(), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return rounded


class FullscreenDialog(QDialog):
    """
    Dialog for viewing images without standard controls.
    Image displayed in fixed-size area.
    Window has arrow buttons for flipping through images.
    Dialog closes on click on image.
    """
    FIXED_WIDTH = 800
    FIXED_HEIGHT = 400

    def __init__(self, images, current_index=0, parent=None, theme=None):
        """
        :param images: List of tuples (QPixmap, str)
        :param current_index: Index of current image
        :param theme: Theme object for styling (if None, default_styles used)
        """
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFocus()

        self.images = images
        self.current_index = current_index
        self.theme_manager = ThemeManager()
        self.theme = theme if theme is not None else self.theme_manager.apply_theme(ui_config.get_theme())

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.init_ui()
        self.update_display()

        self.imageLabel.installEventFilter(self)

    def init_ui(self):
        self.mainLayout = QVBoxLayout(self)
        self.setLayout(self.mainLayout)
        self.mainLayout.setContentsMargins(0, 0, 0, 0)
        self.mainLayout.setSpacing(0)

        self.imageContainer = QWidget()
        self.imageContainer.setFixedSize(self.FIXED_WIDTH, self.FIXED_HEIGHT)
        self.imageContainerLayout = QHBoxLayout(self.imageContainer)
        self.imageContainerLayout.setContentsMargins(0, 0, 0, 0)
        self.imageContainerLayout.setSpacing(0)

        self.prevButton = QToolButton()
        self.prevButton.setArrowType(Qt.ArrowType.LeftArrow)
        self.prevButton.setStyleSheet(getattr(self.theme, "PREV_BUTTON_STYLE", ""))
        self.prevButton.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prevButton.setFixedSize(40, 40)
        self.prevButton.clicked.connect(self.show_prev)
        self.imageContainerLayout.addWidget(self.prevButton)

        self.imageLabel = QLabel()
        self.imageLabel.setFixedSize(self.FIXED_WIDTH - 80, self.FIXED_HEIGHT)
        self.imageLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.imageContainerLayout.addWidget(self.imageLabel, stretch=1)

        self.nextButton = QToolButton()
        self.nextButton.setArrowType(Qt.ArrowType.RightArrow)
        self.nextButton.setStyleSheet(getattr(self.theme, "NEXT_BUTTON_STYLE", ""))
        self.nextButton.setCursor(Qt.CursorShape.PointingHandCursor)
        self.nextButton.setFixedSize(40, 40)
        self.nextButton.clicked.connect(self.show_next)
        self.imageContainerLayout.addWidget(self.nextButton)

        self.mainLayout.addWidget(self.imageContainer)

        spacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.mainLayout.addItem(spacer)

    def update_display(self):
        """Update image according to current index."""
        if not self.images:
            return

        self.imageLabel.clear()
        QApplication.processEvents()

        pixmap, _ = self.images[self.current_index]
        # Check if pixmap is valid before attempting to scale it
        if pixmap.isNull():
            # Create a default placeholder pixmap instead of trying to scale a null pixmap
            placeholder_pixmap = QPixmap(self.FIXED_WIDTH - 80, self.FIXED_HEIGHT)
            placeholder_pixmap.fill(QColor(self.theme.color_placeholder_bg))
            painter = QPainter(placeholder_pixmap)
            painter.setPen(QPen(QColor(self.theme.color_white)))
            painter.drawText(placeholder_pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "No Image")
            painter.end()
            self.imageLabel.setPixmap(placeholder_pixmap)
        else:
            # Account for devicePixelRatio for high-quality scaling
            device_pixel_ratio = get_device_pixel_ratio()
            target_width = int((self.FIXED_WIDTH - 80) * device_pixel_ratio)
            target_height = int(self.FIXED_HEIGHT * device_pixel_ratio)

            # Scale image from original pixmap
            scaled_pixmap = pixmap.scaled(
                target_width,
                target_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            scaled_pixmap.setDevicePixelRatio(device_pixel_ratio)
            self.imageLabel.setPixmap(scaled_pixmap)

        self.imageLabel.repaint()
        self.repaint()

    def resizeEvent(self, event):
        """Update image on window resize."""
        super().resizeEvent(event)
        self.update_display()  # Redraw image with new size

    def show_prev(self):
        """Show previous image."""
        if self.images:
            self.current_index = (self.current_index - 1) % len(self.images)
            self.update_display()

    def show_next(self):
        """Show next image."""
        if self.images:
            self.current_index = (self.current_index + 1) % len(self.images)
            self.update_display()

    def eventFilter(self, obj, event):
        """Close dialog on click on image."""
        if event.type() == QEvent.Type.MouseButtonPress and obj == self.imageLabel:
            self.close()
            return True
        return super().eventFilter(obj, event)

    def changeEvent(self, event):
        """Close dialog on focus loss."""
        if event.type() == QEvent.Type.ActivationChange:
            if not self.isActiveWindow():
                self.close()
        super().changeEvent(event)

    def mousePressEvent(self, event):
        """Close dialog on click on empty area."""
        pos = event.pos()
        if not self.imageContainer.geometry().contains(pos):
            self.close()
        super().mousePressEvent(event)

class ClickablePixmapItem(QGraphicsPixmapItem):
    """
    Carousel element that responds to clicks.
    On click, opens FullscreenDialog with ability to flip through images.
    """
    def __init__(self, pixmap, images_list=None, index=0, carousel=None):
        """
        :param pixmap: QPixmap for display in carousel (original, high resolution)
        :param images_list: List of all images (tuples (QPixmap, str))
        :param index: Index of current image in images_list
        :param carousel: Reference to parent carousel (ImageCarousel)
        """
        super().__init__()
        self.original_pixmap = pixmap  # Store original high-resolution pixmap
        self.images_list = images_list if images_list is not None else [(pixmap, "")]
        self.index = index
        self.carousel = carousel
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._click_start_position = None
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.update_pixmap()  # Set initial pixmap

    def update_pixmap(self, height=300):
        """Update the displayed pixmap by scaling from the original high-resolution pixmap."""
        if self.original_pixmap.isNull():
            return
        # Scale pixmap to desired height, considering device pixel ratio
        device_pixel_ratio = get_device_pixel_ratio()
        scaled_pixmap = self.original_pixmap.scaledToHeight(
            int(height * device_pixel_ratio),
            Qt.TransformationMode.SmoothTransformation
        )
        scaled_pixmap.setDevicePixelRatio(device_pixel_ratio)
        self.setPixmap(scaled_pixmap)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._click_start_position = event.scenePos()
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._click_start_position is not None:
            distance = (event.scenePos() - self._click_start_position).manhattanLength()
            if distance < 2:
                self.show_fullscreen()
                event.accept()
                return
        event.accept()

    def show_fullscreen(self):
        if self.carousel:
            self.carousel.prevArrow.hide()
            self.carousel.nextArrow.hide()
        dialog = FullscreenDialog(self.images_list, current_index=self.index)
        dialog.exec()
        if self.carousel:
            self.carousel.update_arrows_visibility()

class ImageCarousel(QGraphicsView):
    """
    Image carousel with adaptivity, click-to-zoom capability
    and mouse dragging.
    """
    def __init__(self, images: list[tuple], parent: QWidget | None = None, theme: object | None = None):
        super().__init__(parent)
        self.carousel_scene: QGraphicsScene = QGraphicsScene(self)
        self.setScene(self.carousel_scene)
        self.images = images  # List of tuples: (QPixmap, str)
        self.image_items = []
        self._animation = None
        self.theme_manager = ThemeManager()
        self.theme = theme if theme is not None else self.theme_manager.apply_theme(ui_config.get_theme())
        self.max_height = 300  # Default height for images
        self.init_ui()
        self.create_arrows()

        self._drag_active = False
        self._drag_start_position = None
        self._scroll_start_value = None

    def init_ui(self):
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)

        self.update_scene()

    def update_scene(self):
        """Update the scene with scaled images based on current size and scale."""
        self.carousel_scene.clear()
        self.image_items.clear()

        x_offset = 10
        x = 0
        device_pixel_ratio = get_device_pixel_ratio()

        for i, (pixmap, _caption) in enumerate(self.images):
            item = ClickablePixmapItem(
                pixmap,  # Pass original pixmap
                images_list=self.images,
                index=i,
                carousel=self
            )
            item.update_pixmap(self.max_height)  # Scale to current height
            item.setPos(x, 0)
            self.carousel_scene.addItem(item)
            self.image_items.append(item)
            x += item.pixmap().width() / device_pixel_ratio + x_offset

        self.setSceneRect(0, 0, x, self.max_height)

    def create_arrows(self):
        """Create arrow buttons and bind them to scroll functions."""
        self.prevArrow = QToolButton(self)
        self.prevArrow.setArrowType(Qt.ArrowType.LeftArrow)
        self.prevArrow.setStyleSheet(getattr(self.theme, "PREV_BUTTON_STYLE", ""))
        self.prevArrow.setFixedSize(40, 40)
        self.prevArrow.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prevArrow.setAutoRepeat(True)
        self.prevArrow.setAutoRepeatDelay(300)
        self.prevArrow.setAutoRepeatInterval(100)
        self.prevArrow.clicked.connect(self.scroll_left)
        self.prevArrow.raise_()

        self.nextArrow = QToolButton(self)
        self.nextArrow.setArrowType(Qt.ArrowType.RightArrow)
        self.nextArrow.setStyleSheet(getattr(self.theme, "NEXT_BUTTON_STYLE", ""))
        self.nextArrow.setFixedSize(40, 40)
        self.nextArrow.setCursor(Qt.CursorShape.PointingHandCursor)
        self.nextArrow.setAutoRepeat(True)
        self.nextArrow.setAutoRepeatDelay(300)
        self.nextArrow.setAutoRepeatInterval(100)
        self.nextArrow.clicked.connect(self.scroll_right)
        self.nextArrow.raise_()

        self.update_arrows_visibility()

    def update_arrows_visibility(self):
        if hasattr(self, "prevArrow") and hasattr(self, "nextArrow"):
            if self.horizontalScrollBar().maximum() == 0:
                self.prevArrow.hide()
                self.nextArrow.hide()
            else:
                self.prevArrow.show()
                self.nextArrow.show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        margin = 10
        self.prevArrow.move(margin, (self.height() - self.prevArrow.height()) // 2)
        self.nextArrow.move(self.width() - self.nextArrow.width() - margin,
                            (self.height() - self.nextArrow.height()) // 2)
        self.update_scene()  # Re-scale images on resize
        self.update_arrows_visibility()

    def animate_scroll(self, end_value):
        scrollbar = self.horizontalScrollBar()
        start_value = scrollbar.value()
        animation = QPropertyAnimation(scrollbar, QByteArray(b"value"), self)
        animation.setDuration(300)
        animation.setStartValue(start_value)
        animation.setEndValue(end_value)
        animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._animation = animation
        animation.start()

    def scroll_left(self):
        scrollbar = self.horizontalScrollBar()
        new_value = scrollbar.value() - 100
        self.animate_scroll(new_value)

    def scroll_right(self):
        scrollbar = self.horizontalScrollBar()
        new_value = scrollbar.value() + 100
        self.animate_scroll(new_value)

    def update_images(self, new_images):
        self.images = new_images
        self.update_scene()
        self.update_arrows_visibility()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_active = True
            self._drag_start_position = event.pos()
            self._scroll_start_value = self.horizontalScrollBar().value()
            if hasattr(self, "prevArrow"):
                self.prevArrow.hide()
            if hasattr(self, "nextArrow"):
                self.nextArrow.hide()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_active and self._drag_start_position is not None:
            delta = event.pos().x() - self._drag_start_position.x()
            new_value = self._scroll_start_value - delta
            self.horizontalScrollBar().setValue(new_value)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_active = False
        self.update_arrows_visibility()
        super().mouseReleaseEvent(event)
