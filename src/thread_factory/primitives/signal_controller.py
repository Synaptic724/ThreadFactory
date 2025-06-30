import threading
from typing import Callable, Optional

import ulid


class SignalController:
    """
    SignalController
    ----------------
    Tracks labeled predicates. Each predicate returns a boolean.
    The controller polls them, and when ALL are True, it fires a callback.

    Allows introspection: who is ready, who is not.
    """
    def __init__(self, poll_interval: float = 0.05):
        self._predicates: dict[str, Callable[[], bool]] = {}
        self._last_status: dict[str, bool] = {}
        self._callback: Optional[Callable[[], None]] = None
        self._poll_interval = poll_interval
        self._id = str(ulid.ULID())
        self._running = threading.Event()
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._lock = threading.Lock()

    def register(self, label: str, predicate: Callable[[], bool]):
        """Register a labeled predicate."""
        with self._lock:
            self._predicates[label] = predicate

    def unregister(self, label: str):
        """Remove a predicate by label."""
        with self._lock:
            self._predicates.pop(label, None)
            self._last_status.pop(label, None)

    def set_on_ready(self, callback: Callable[[], None]):
        """Fires when all predicates return True."""
        self._callback = callback

    def start(self):
        """Starts polling loop."""
        self._running.set()
        self._thread.start()

    def stop(self):
        """Stops polling."""
        self._running.clear()
        self._thread.join(timeout=2)

    def get_status(self) -> dict[str, bool]:
        """Returns latest known status of each signaler."""
        with self._lock:
            return dict(self._last_status)

    def _watch_loop(self):
        while self._running.is_set():
            with self._lock:
                preds = dict(self._predicates)

            all_ready = True
            latest = {}

            for label, pred in preds.items():
                try:
                    result = bool(pred())
                    latest[label] = result
                    if not result:
                        all_ready = False
                except Exception:
                    latest[label] = False
                    all_ready = False

            with self._lock:
                self._last_status = latest

            if all_ready:
                if self._callback:
                    try:
                        self._callback()
                    except Exception:
                        pass
                self._running.clear()
                break

            time.sleep(self._poll_interval)
