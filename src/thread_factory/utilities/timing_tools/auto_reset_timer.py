import threading
import traceback
from thread_factory.utilities.interfaces.disposable import IDisposable

class AutoResetTimer(IDisposable):
    """
    AutoResetTimer
    --------------
    A repeating timer that behaves like .NET's System.Timers.Timer with AutoReset enabled.
    - Executes a callback repeatedly at a fixed interval.
    - Automatically restarts after each invocation.
    - Thread-safe and supports graceful shutdown.
    - Exceptions in the callback are caught and logged.
    - Timer runs as a daemon by default.
    """

    def __init__(self, interval_sec, callback, daemon=True):
        """
        Initializes the timer.

        Args:
            interval_sec (float): Time in seconds between each callback execution.
            callback (Callable): The function to call on each interval.
            daemon (bool): Whether the internal timer thread should run as a daemon. Default is True.
        """
        super().__init__()
        self.interval = interval_sec
        self.callback = callback
        self.daemon = daemon
        self._timer = None
        self._lock = threading.RLock()
        self._running = False

    def dispose(self):
        """
        Dispose of the timer and stop any scheduled execution.
        This should be called to clean up the timer when no longer needed.
        """
        if self._disposed:
            return
        with self._lock:
            self._disposed = True
            self.stop()
            self._timer = None

    def _run(self):
        """
        Internal runner that wraps the user callback.
        Ensures the timer is restarted after each callback.
        """
        if not self._running:
            return
        try:
            self.callback()
        except Exception as e:
            print("[AutoResetTimer] Exception in callback:", e)
            traceback.print_exc()
        finally:
            self._start_timer()  # restart the timer automatically

    def _start_timer(self):
        """
        Internal helper to initialize and start the internal threading.Timer.
        """
        self._timer = threading.Timer(self.interval, self._run)
        self._timer.daemon = self.daemon
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

    def restart(self):
        """
        Stops and restarts the timer. Useful if you want to rearm it manually.
        """
        with self._lock:
            self.stop()
            self._running = True
            self._start_timer()

    def is_running(self):
        """
        Check if the timer is currently active.

        Returns:
            bool: True if running, False otherwise.
        """
        return self._running

