import threading
from thread_factory.utils import IDisposable

class Dynaphore(threading.Semaphore, IDisposable):
    """
    A dynamic semaphore that can increase or decrease the number of permits at runtime.
    Exposes the internal Condition for wait/notify and provides dynamic scaling.
    """

    def __init__(self, value: int = 1, re_entrant: bool = True):
        super().__init__(value)
        if re_entrant:
            self._cond = threading.Condition() #This defaults to RLock instead of Lock
        else:
            self._cond = threading.Condition(threading.Lock())

    @property
    def condition(self) -> threading.Condition:
        """
        Expose the internal Condition object.
        Allows external runtime to wait on complex conditions.
        """
        return self._cond

    def increase_permits(self, n: int = 1) -> None:
        """
        Dynamically increase available permits and notify waiting runtime.
        """
        if n < 0:
            raise ValueError("Cannot increase permits by a negative value")

        with self._cond:
            self._value += n
            print(f"[Dynaphore] Increased permits by {n}, total permits: {self._value}")
            for _ in range(n):
                self._cond.notify()

    def decrease_permits(self, n: int = 1) -> None:
        """
        Dynamically decrease available permits.
        """
        if n < 0:
            raise ValueError("Cannot decrease permits by a negative value")

        with self._cond:
            if n > self._value:
                raise ValueError("Cannot decrease more permits than available")
            self._value -= n
            print(f"[Dynaphore] Decreased permits by {n}, total permits: {self._value}")

    def wait_for_permit(self, timeout: float = None) -> bool:
        """
        Wait until a permit is available, using the internal condition.
        """
        with self._cond:
            result = self._cond.wait_for(lambda: self._value > 0, timeout=timeout)
            if result:
                self._value -= 1  # Reserve the permit
                print(f"[Dynaphore] Permit acquired! Remaining permits: {self._value}")
            else:
                print(f"[Dynaphore] Timed out waiting for permit.")
            return result

    def release_permit(self, n: int = 1):
        """
        Release a permit (same as release, but more explicit).
        """
        self.release(n)
        print(f"[Dynaphore] Permit released! Total permits: {self._value}")

    def dispose(self):
        """
        Dispose of the Dynaphore, releasing any resources.
        """
        if self.disposed:
            return
        with self._cond:
            self._cond.notify_all()
        self.disposed = True
        self._cond = None
