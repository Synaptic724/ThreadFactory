import threading
import time
from thread_factory.utilities.interfaces.disposable import IDisposable


class Stopwatch(IDisposable):
    """
    Stopwatch
    ---------
    A high-precision, thread-safe stopwatch for measuring elapsed time.

    Features:
      - Start / Stop / Reset / Elapsed time
      - Thread-safe for use in concurrent applications
    """

    def __init__(self):
        """
        Initializes the stopwatch using a monotonic high-resolution clock.
        """
        super().__init__()
        self._clock = time.perf_counter
        self.start_time = None
        self.elapsed_time = 0.0
        self._lock = threading.RLock()

    def start(self):
        """
        Start or resume the stopwatch.
        Does nothing if already running.
        """
        with self._lock:
            if self.start_time is None:
                self.start_time = self._clock()

    def stop(self):
        """
        Stop the stopwatch and accumulate elapsed time.
        """
        with self._lock:
            if self.start_time is not None:
                self.elapsed_time += self._clock() - self.start_time
                self.start_time = None

    def reset(self):
        """
        Reset the stopwatch to zero.
        Stops the stopwatch if running.
        """
        with self._lock:
            self.start_time = None
            self.elapsed_time = 0.0

    def elapsed(self) -> float:
        """
        Returns the total elapsed time in seconds without stopping the stopwatch.

        Returns:
            float: The current elapsed time in seconds.
        """
        with self._lock:
            current = self.elapsed_time
            if self.start_time is not None:
                current += self._clock() - self.start_time
            return current

    def is_running(self) -> bool:
        """
        Returns whether the stopwatch is currently running.

        Returns:
            bool: True if running, False if stopped.
        """
        return self.start_time is not None

    def dispose(self):
        """
        Dispose of internal state. Frees stopwatch references.
        """
        if self._disposed:
            return
        with self._lock:
            self.start_time = None
            self.elapsed_time = 0.0
            self._clock = None
            self._disposed = True

    def __repr__(self):
        """
        String representation showing elapsed time and running state.
        """
        with self._lock:
            state = "running" if self.start_time is not None else "stopped"
            return f"<Stopwatch elapsed={self.elapsed():.6f}s state={state}>"
