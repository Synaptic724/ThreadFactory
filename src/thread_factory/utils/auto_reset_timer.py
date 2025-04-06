import threading
from thread_factory.utils import Disposable

class AutoResetTimer(Disposable):
    """
    AutoResetTimer
    --------------
    A repeating timer that behaves like .NET's System.Timers.Timer with AutoReset enabled.
    - Executes a callback repeatedly at a fixed interval.
    - Automatically restarts after each invocation.
    - Thread-safe and supports graceful shutdown.
    """

    def __init__(self, interval_sec, callback):
        """
        Initializes the timer.

        Args:
            interval_sec (float): Time in seconds between each callback execution.
            callback (Callable): The function to call on each interval.
        """
        self.interval = interval_sec
        self.callback = callback
        self._timer = None
        self._lock = threading.RLock()
        self._running = False

    def _run(self):
        """
        Internal runner that wraps the user callback.
        Ensures the timer is restarted after each callback.
        """
        if not self._running:
            return
        try:
            self.callback()
        finally:
            self._start_timer()  # restart the timer automatically

    def _start_timer(self):
        """
        Internal helper to initialize and start the internal threading.Timer.
        """
        self._timer = threading.Timer(self.interval, self._run)
        self._timer.start()

    def start(self):
        """
        Starts the timer. If it's already running, this does nothing.
        """
        with self._lock:
            if not self._running:
                self._running = True
                self._start_timer()

    def stop(self):
        """
        Stops the timer. The callback will no longer be invoked.
        If the timer is already stopped, this is a no-op.
        """
        with self._lock:
            self._running = False
            if self._timer:
                self._timer.cancel()

    def is_running(self):
        """
        Check if the timer is currently active.

        Returns:
            bool: True if running, False otherwise.
        """
        return self._running

    def dispose(self):
        """
        Dispose of the timer and stop any scheduled execution.
        This should be called to clean up the timer when no longer needed.
        """
        self.stop()
        self._timer = None
