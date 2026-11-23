"""Download cache completion and worker lifecycle regressions."""

from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
import threading
from typing import Any, cast
from unittest.mock import MagicMock

from PIL import Image
import pytest
from requests.exceptions import ConnectionError, ReadTimeout
from PySide6.QtCore import QCoreApplication, QThread
from PySide6.QtWidgets import QApplication

from portprotonqt.downloader import Downloader
from portprotonqt.tabs.workers import MainWindowWorkersMixin

THREAD_TIMEOUT_MS = 30000
SYNC_TIMEOUT_SECONDS = 30


@pytest.fixture(autouse=True)
def application() -> QCoreApplication:
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("parallel", [False, True])
@pytest.mark.parametrize("complete", [False, True])
def test_truncated_cached_cover_is_redownloaded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, parallel: bool, complete: bool,
) -> None:
    url = "https://example.com/cover.jpg"
    target = tmp_path / "cover.jpg"
    buffer = BytesIO()
    Image.new("RGB", (32, 32)).save(buffer, format="JPEG")
    jpeg = buffer.getvalue()
    truncated = jpeg[:-30]
    target.write_bytes(truncated)
    response = MagicMock()
    response.headers = {}

    def chunks(chunk_size: int) -> Iterator[bytes]:
        yield jpeg[:100]
        assert target.read_bytes() == truncated
        yield (jpeg if complete else truncated)[100:]

    response.iter_content.side_effect = chunks
    session = MagicMock()
    session.get.return_value.__enter__.return_value = response
    monkeypatch.setattr("portprotonqt.downloader.get_requests_session", lambda: session)
    downloader = Downloader()
    downloader._cache[url] = str(target)
    results: list[str | None] = []

    worker = downloader.download_async(url, str(target), parallel=parallel, callback=results.append)

    assert worker is not None
    assert worker.wait(THREAD_TIMEOUT_MS)
    QApplication.processEvents()
    assert results == [str(target) if complete else None]
    assert target.read_bytes() == (jpeg if complete else truncated)
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("error", [ConnectionError, ReadTimeout, PermissionError])
def test_failed_download_can_recover(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error: type[Exception],
) -> None:
    from portprotonqt import downloader as module

    now = 100.0
    from types import SimpleNamespace

    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: now))
    session = MagicMock()
    response = session.get.return_value.__enter__.return_value
    response.headers = {}
    monkeypatch.setattr(module, "get_requests_session", lambda: session)

    def interrupted() -> Iterator[bytes]:
        yield b"partial"
        if error is not PermissionError:
            raise error("simulated connection failure")

    if error is PermissionError:
        replace = Path.replace

        def replace_after_recovery(path: Path, destination: Path) -> Path:
            if now == 100.0:
                raise PermissionError("simulated write failure")
            return replace(path, destination)

        monkeypatch.setattr(Path, "replace", replace_after_recovery)
    response.iter_content.side_effect = [interrupted(), iter([b"complete"])]
    downloader = Downloader()
    url = "https://example.com/data.json"
    target = tmp_path / "data.json"
    assert downloader.download(url, str(target)) is None
    assert not list(tmp_path.iterdir())
    assert downloader.download(url, str(target)) is None
    assert session.get.call_count == 1

    now += module.FAILURE_RETRY_SECONDS
    assert downloader.download(url, str(target)) == str(target)
    assert target.read_bytes() == b"complete"
    assert session.get.call_count == 2


@pytest.mark.parametrize("parallel", [False, True])
@pytest.mark.parametrize("failed", [False, True])
def test_resolved_download_completes_without_a_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, parallel: bool, failed: bool,
) -> None:
    downloader = Downloader()
    url = "https://example.com/data.json"
    path = str(tmp_path / "data.json")
    if failed:
        downloader._record_failure(url)
    else:
        Path(path).write_text("{}")
    start = MagicMock()
    monkeypatch.setattr(QThread, "start", start)
    results: list[tuple[str | None, QThread]] = []
    completed = MagicMock()
    downloader.download_completed.connect(completed)

    worker = downloader.download_async(
        url, path, parallel=parallel,
        callback=lambda result: results.append((result, QThread.currentThread())),
    )

    assert worker is None
    start.assert_not_called()
    assert results == []
    assert downloader._active_threads == []
    QApplication.processEvents()
    expected = None if failed else path
    assert results == [(expected, QThread.currentThread())]
    completed.assert_called_once_with(url, expected or "", not failed)
    if not failed:
        assert downloader._cache[url] == path


@pytest.mark.parametrize("parallel", [False, True])
@pytest.mark.parametrize("cached_file_exists", [False, True])
def test_missing_destination_still_downloads_with_a_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    parallel: bool, cached_file_exists: bool,
) -> None:
    downloader = Downloader()
    url = "https://example.com/data.json"
    cached_path = tmp_path / "old.json"
    target = tmp_path / "new.json"
    if cached_file_exists:
        cached_path.write_text("{}")
    downloader._cache[url] = str(cached_path)
    download = MagicMock(return_value=str(target))
    parallel_download = MagicMock(return_value={url: str(target)})
    monkeypatch.setattr("portprotonqt.downloader.download_with_cache", download)
    monkeypatch.setattr(downloader, "_download_with_parallel", parallel_download)
    results: list[str | None] = []

    worker = downloader.download_async(url, str(target), parallel=parallel, callback=results.append)

    assert worker is not None
    assert worker in downloader._active_threads
    assert worker.wait(THREAD_TIMEOUT_MS)
    assert results == []
    QApplication.processEvents()
    assert results == [str(target)]
    assert downloader._active_threads == []
    if parallel:
        assert parallel_download.call_args.args[:2] == ([url], [str(target)])
    else:
        download.assert_called_once_with(url, str(target), 5, downloader)


def test_parallel_known_failure_does_not_create_an_executor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    downloader = Downloader()
    url = "https://example.com/data.json"
    path = str(tmp_path / "data.json")
    downloader._record_failure(url)
    downloader._cache[url] = path
    download = MagicMock()
    monkeypatch.setattr(downloader, "_download_with_parallel", download)
    completed = MagicMock()

    result = downloader.download_parallel([url], [path], on_result=completed)

    download.assert_not_called()
    assert result == {url: None}
    completed.assert_called_once_with(url, None)


def test_download_started_from_a_worker_cleans_up_on_the_owner_thread(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    downloader = Downloader()
    path = str(tmp_path / "data.json")
    monkeypatch.setattr("portprotonqt.downloader.download_with_cache",
                        lambda *_args: path)
    workers: list[QThread | None] = []
    results: list[tuple[str | None, QThread]] = []

    def start_download() -> None:
        workers.append(downloader.download_async(
            "https://example.com/data.json", path,
            callback=lambda result: results.append((result, QThread.currentThread())),
        ))

    caller = threading.Thread(target=start_download)
    caller.start()
    caller.join(timeout=SYNC_TIMEOUT_SECONDS)
    assert not caller.is_alive()
    worker = workers[0]
    assert worker is not None
    assert worker.wait(THREAD_TIMEOUT_MS)
    QApplication.processEvents()

    assert results == [(path, QThread.currentThread())]
    assert downloader._active_threads == []


@pytest.mark.parametrize("shutdown", ["owner", "application"])
def test_shutdown_waits_for_an_active_download(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, shutdown: str,
) -> None:
    downloader = Downloader()
    entered = threading.Event()
    release = threading.Event()
    path = str(tmp_path / "data.json")

    def download(*_args: Any) -> str:
        entered.set()
        assert release.wait(SYNC_TIMEOUT_SECONDS)
        return path

    monkeypatch.setattr("portprotonqt.downloader.download_with_cache", download)
    worker = downloader.download_async("https://example.com/data.json", path)
    assert worker is not None
    assert entered.wait(SYNC_TIMEOUT_SECONDS)
    owner = cast(Any, MainWindowWorkersMixin())
    owner.downloader = downloader
    owner.compatibility_workers = []
    release_timer = threading.Timer(0.05, release.set)
    release_timer.start()
    try:
        if shutdown == "owner":
            owner._stopBackgroundWorkers()
        else:
            app = QApplication.instance()
            assert app is not None
            app.aboutToQuit.emit()
        assert not worker.isRunning()
        QApplication.processEvents()
        assert downloader._active_threads == []
    finally:
        release.set()
        release_timer.join()
        worker.wait(THREAD_TIMEOUT_MS)


def test_shutdown_waits_for_active_artwork_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    from portprotonqt.steam_api import api

    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def lookup(_game_name: str, _image_type: str) -> str:
        entered.set()
        assert release.wait(SYNC_TIMEOUT_SECONDS)
        finished.set()
        return ""

    monkeypatch.setattr(api, "_read_sgdb_cover", lookup)
    api.fetch_sgdb_cover_async("Game", lambda _cover: None)
    release_timer = threading.Timer(0.05, release.set)
    try:
        assert entered.wait(SYNC_TIMEOUT_SECONDS)
        release_timer.start()
        MainWindowWorkersMixin()._stopBackgroundWorkers()
        assert finished.is_set()
    finally:
        release.set()
        if release_timer.ident is not None:
            release_timer.join()
        assert api._METADATA_LOOKUPS.waitForDone(THREAD_TIMEOUT_MS)
