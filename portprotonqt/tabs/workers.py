from portprotonqt.logger import get_logger

logger = get_logger(__name__)


class MainWindowWorkersMixin:
    def _stopBackgroundWorkers(self) -> None:
        worker_timeouts = {
            "networkWorker": 3000,
            "bluetoothWorker": 12000,
            "storageWorker": 3000,
            "audioWorker": 3000,
            "autoInstallLoadThread": None,
            "autoInstallScriptLoadThread": None,
            "autoInstallCustomDataThread": None,
            "appimageUpdateWorker": 3000,
            "appImageIntegrationWorker": None,
            "gogdlUpdateWorker": None,
            "initialCommandWorker": None,
            "egs_library_worker": None,
            "egs_auth_worker": None,
            "gog_library_worker": None,
            "gog_metadata_worker": None,
            "gog_repair_worker": None,
            "gog_auth_worker": None,
            "gog_account_worker": None,
            "themeStoreListWorker": None,
            "themeStoreImageWorker": None,
            "themeStoreDetailImageWorker": None,
            "themeStoreDownloadWorker": None,
        }
        for worker_name, timeout_ms in worker_timeouts.items():
            self._stopWorkerThread(worker_name, timeout_ms)
        for workers_name in (
            "gog_support_workers",
            "_listWorkerPool",
            "_imageWorkerPool",
            "_detailImageWorkerPool",
        ):
            self._stopWorkerThreads(workers_name)
        downloader = getattr(self, "downloader", None)
        for worker in list(getattr(downloader, "_active_threads", [])):
            self._stopWorker(worker, "downloader", None)
        input_manager = getattr(self, "input_manager", None)
        if input_manager is not None:
            input_manager.cleanup()

    def _stopWorkerThread(
        self, worker_name: str, timeout_ms: int | None = 3000
    ) -> None:
        worker = getattr(self, worker_name, None)
        if worker is None:
            return
        self._stopWorker(worker, worker_name, timeout_ms)
        setattr(self, worker_name, None)

    def _stopWorkerThreads(self, workers_name: str) -> None:
        workers = getattr(self, workers_name, []) or []
        for worker in workers:
            self._stopWorker(worker, workers_name, None)
        setattr(self, workers_name, [])

    def _stopWorker(
        self, worker: object, worker_name: str, timeout_ms: int | None
    ) -> None:
        request_interruption = getattr(worker, "requestInterruption", None)
        cancel = getattr(worker, "cancel", None)
        try:
            if callable(request_interruption):
                request_interruption()
            if callable(cancel):
                cancel()

            is_running = getattr(worker, "isRunning", None)
            wait_method = getattr(worker, "wait", None)
            if callable(is_running) and is_running() and callable(wait_method):
                if timeout_ms is None:
                    wait_method()
                else:
                    wait_method(timeout_ms)

            if callable(is_running) and is_running():
                logger.warning("%s is still running during shutdown", worker_name)
        except RuntimeError as error:
            logger.debug("%s already deleted during shutdown: %s", worker_name, error)
