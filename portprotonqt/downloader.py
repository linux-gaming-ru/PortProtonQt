from PySide6.QtCore import QObject, Signal, QThread, Qt, QCoreApplication
import threading
from tempfile import NamedTemporaryFile
import os
import time
import requests
from pathlib import Path
from tqdm import tqdm
from collections.abc import Callable
from portprotonqt.config import proxy_config
from portprotonqt.logger import get_logger

logger = get_logger(__name__)

FAILURE_RETRY_SECONDS = 30
MAX_CACHED_FAILURES = 1024


def get_default_user_agent() -> str:
    from portprotonqt.app import __app_version__

    return f"PortProtonQt/{__app_version__}"

def get_requests_session():
    session = requests.Session()
    proxy = proxy_config.get_proxy() or {}
    if proxy:
        session.proxies.update(proxy)
    session.headers.update({"User-Agent": get_default_user_agent()})
    session.verify = True
    return session

def is_complete_download(path: str | Path) -> bool:
    """Check for a cached file, rejecting JPEGs without an end marker."""
    jpeg_start = b"\xff\xd8"
    jpeg_end = b"\xff\xd9"
    try:
        with open(path, "rb") as stream:
            header = stream.read(len(jpeg_start))
            if header != jpeg_start:
                return bool(header)
            stream.seek(-len(jpeg_end), os.SEEK_END)
            return stream.read() == jpeg_end
    except OSError:
        return False


def _save_download(response: requests.Response, local_path: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    total_size = int(response.headers.get('Content-Length', 0))
    destination = Path(local_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            with tqdm(total=total_size or None, unit='B', unit_scale=True,
                      unit_divisor=1024, desc=f"Downloading {destination.name}", ascii=True) as pbar:
                for chunk in response.iter_content(chunk_size=8192):
                    if time.monotonic() > deadline:
                        raise requests.exceptions.ReadTimeout(f"Download exceeded {timeout}s total timeout")
                    if chunk:
                        stream.write(chunk)
                        pbar.update(len(chunk))
            stream.close()
            if not is_complete_download(temporary):
                raise OSError("Incomplete JPEG download")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)


def download_with_cache(url, local_path, timeout=5, downloader_instance=None):
    if is_complete_download(local_path):
        return local_path
    session = get_requests_session()
    try:
        with session.get(url, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            _save_download(response, local_path, timeout)
        return local_path
    except Exception as e:
        logger.error(f"Download error {url}: {e}")
        if downloader_instance is not None:
            downloader_instance._record_failure(url)
        return None

class Downloader(QObject):
    download_completed = Signal(str, str, bool)  # url, local_path, success
    callback_requested = Signal(object, object)

    def __init__(self, max_workers=4):
        super().__init__()
        self.max_workers = max_workers
        self._cache = {}
        self._last_error: dict[str, float] = {}
        self._locks = {}
        self._active_threads: list[QThread] = []
        self._global_lock = threading.Lock()
        self.callback_requested.connect(self._run_callback, Qt.ConnectionType.QueuedConnection)

    def _run_callback(self, callback, result):
        if callback:
            callback(result)

    def _record_failure(self, url: str) -> None:
        with self._global_lock:
            self._last_error.pop(url, None)
            self._last_error[url] = time.monotonic() + FAILURE_RETRY_SECONDS
            if len(self._last_error) > MAX_CACHED_FAILURES:
                del self._last_error[next(iter(self._last_error))]

    def _has_recent_failure(self, url: str) -> bool:
        # Call with the global lock held.
        expires = self._last_error.get(url)
        if expires is None:
            return False
        if time.monotonic() < expires:
            return True
        del self._last_error[url]
        return False

    def _get_url_lock(self, url):
        with self._global_lock:
            if url not in self._locks:
                self._locks[url] = threading.Lock()
            return self._locks[url]

    def _download_with_parallel(
        self,
        urls,
        local_paths,
        timeout=5,
        throttle_delay=0.2,
        max_workers=4,
        on_result: Callable[[str, str | None], None] | None = None,
    ):
        """Internal parallel download with rate limiting and 429 retry."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import time

        results = {}
        session = get_requests_session()
        rate_limit_lock = threading.Lock()
        last_request_time = [0.0]

        def _download_one(url, local_path):
            if is_complete_download(local_path):
                return local_path
            try:
                with rate_limit_lock:
                    elapsed = time.time() - last_request_time[0]
                    if elapsed < throttle_delay:
                        time.sleep(throttle_delay - elapsed)
                    last_request_time[0] = time.time()

                with session.get(url, stream=True, timeout=timeout) as response:
                    response.raise_for_status()
                    _save_download(response, local_path, timeout)
                return local_path
            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code == 429:
                    logger.warning(f"Rate limited (429) for {url}, retrying after delay")
                    time.sleep(2.0)
                    try:
                        with session.get(url, stream=True, timeout=timeout) as response:
                            response.raise_for_status()
                            _save_download(response, local_path, timeout)
                        return local_path
                    except Exception as retry_e:
                        logger.error(f"Retry download error {url}: {retry_e}")
                        self._record_failure(url)
                        return None
                else:
                    logger.error(f"Download error {url}: {e}")
                    self._record_failure(url)
                    return None
            except Exception as e:
                logger.error(f"Download error {url}: {e}")
                self._record_failure(url)
                return None

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_url = {executor.submit(_download_one, url, local_path): url for url, local_path in zip(urls, local_paths, strict=False)}
            for future in tqdm(as_completed(future_to_url), total=len(urls), desc="Downloading in parallel", ascii=True):
                url = future_to_url[future]
                try:
                    res = future.result()
                    results[url] = res
                    if on_result:
                        on_result(url, res)
                except Exception as e:
                    logger.error(f"Download error {url}: {e}")
                    results[url] = None
                    if on_result:
                        on_result(url, None)
        return results

    def download(self, url, local_path, timeout=5):
        with self._global_lock:
            if self._has_recent_failure(url):
                logger.warning(f"Previous download error for {url}, skipping")
                return None
            if url in self._cache:
                cached_path = self._cache[url]
                if is_complete_download(cached_path):
                    if os.path.abspath(cached_path) == os.path.abspath(local_path):
                        return cached_path
                else:
                    del self._cache[url]
        url_lock = self._get_url_lock(url)
        with url_lock:
            with self._global_lock:
                if self._has_recent_failure(url):
                    return None
                if url in self._cache:
                    cached_path = self._cache[url]
                    if is_complete_download(cached_path) and os.path.abspath(cached_path) == os.path.abspath(local_path):
                        return cached_path
            result = download_with_cache(url, local_path, timeout, self)
            with self._global_lock:
                if result:
                    self._cache[url] = result
                if url in self._locks:
                    del self._locks[url]
            return result

    def download_parallel(
        self,
        urls,
        local_paths,
        timeout=5,
        throttle_delay=0.2,
        max_workers=None,
        on_result: Callable[[str, str | None], None] | None = None,
    ):
        filtered_urls = []
        filtered_paths = []
        emitted_urls = set()
        with self._global_lock:
            for url, path in zip(urls, local_paths, strict=False):
                if self._has_recent_failure(url):
                    logger.warning(f"Previous download error for {url}, skipping")
                    if on_result and url not in emitted_urls:
                        on_result(url, None)
                        emitted_urls.add(url)
                    continue
                cached_path = self._cache.get(url)
                if (cached_path and is_complete_download(cached_path)
                        and os.path.abspath(cached_path) == os.path.abspath(path)):
                    if on_result and url not in emitted_urls:
                        on_result(url, cached_path)
                        emitted_urls.add(url)
                    continue
                self._cache.pop(url, None)
                filtered_urls.append(url)
                filtered_paths.append(path)

        def emit_result(url: str, result: str | None):
            if on_result:
                on_result(url, result)
            emitted_urls.add(url)

        workers = max_workers if max_workers is not None else self.max_workers
        results = self._download_with_parallel(
            filtered_urls,
            filtered_paths,
            timeout,
            throttle_delay,
            workers,
            on_result=emit_result,
        ) if filtered_urls else {}

        with self._global_lock:
            for url, path in results.items():
                if path:
                    self._cache[url] = path
        final_results = {}
        with self._global_lock:
            for url in urls:
                if self._has_recent_failure(url):
                    final_results[url] = None
                elif url in self._cache:
                    final_results[url] = self._cache[url]
                else:
                    final_results[url] = None
        if on_result:
            for url in urls:
                if url not in emitted_urls:
                    on_result(url, final_results[url])
        return final_results


    def download_async(self, url: str, local_path: str, timeout: int = 5, callback: Callable[[str | None], None] | None = None, parallel: bool = False) -> QThread | None:
        with self._global_lock:
            previous_error = self._has_recent_failure(url)
        cached = not previous_error and is_complete_download(local_path)
        if cached:
            with self._global_lock:
                self._cache[url] = local_path
        if previous_error or cached:
            result = local_path if cached else None
            self.download_completed.emit(url, result or "", cached)
            self.callback_requested.emit(callback, result)
            return None

        class DownloadThread(QThread):
            def __init__(self, downloader: 'Downloader', url: str, local_path: str, timeout: int, parallel: bool):
                super().__init__()
                self.downloader = downloader
                self.url = url
                self.local_path = local_path
                self.timeout = timeout
                self.parallel = parallel

            def run(self):
                try:
                    if self.parallel:
                        results = self.downloader.download_parallel([self.url], [self.local_path], timeout=self.timeout)
                        result = results.get(self.url, None)
                    else:
                        result = self.downloader.download(self.url, self.local_path, self.timeout)
                    success = result is not None
                    logger.debug(f"Async download completed {self.url}: success={success}, path={result or ''}")
                    self.downloader.download_completed.emit(self.url, result or "", success)
                    self.downloader.callback_requested.emit(callback, result)
                except Exception as e:
                    logger.error(f"Async download error {self.url}: {e}")
                    self.downloader.download_completed.emit(self.url, "", False)
                    self.downloader.callback_requested.emit(callback, None)

        thread = DownloadThread(self, url, local_path, timeout, parallel)
        thread.moveToThread(self.thread())
        thread.finished.connect(thread.deleteLater)
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(thread.wait)

        # Remove from list after completion
        def cleanup():
            self._active_threads.remove(thread)

        thread.finished.connect(cleanup)

        self._active_threads.append(thread)  # Keep thread to prevent premature destruction
        logger.debug(f"Starting thread for async download {url}")
        thread.start()
        return thread

    def cache_config(self):
        with self._global_lock:
            self._cache.clear()
