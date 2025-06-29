import threading
import time
from typing import Optional, Callable
from thread_factory import Dynaphore


class SynchronizedDynaphore(Dynaphore):
    """
    SynchronizedDynaphore
    ---------------------
    An extension of Dynaphore that provides a strict, exception-based timeout
    mechanism for permit acquisition.

    While `Dynaphore.wait_for_permit()` returns False on timeout, this class
    introduces `wait_or_raise()`, which raises a `TimeoutError` instead. This
    is ideal for scenarios where a timeout is a critical failure that should
    interrupt execution.

    All other properties and methods of Dynaphore are inherited.

    Example:
        ```python
        sync_dyn = SynchronizedDynaphore(value=0)

        def critical_worker():
            try:
                # This will raise TimeoutError after 0.5 seconds
                sync_dyn.wait_or_raise(timeout=0.5)
                print("Permit acquired.")
            except TimeoutError as e:
                print(f"Failed to get permit: {e}")

        critical_worker()
        ```
    """
    # No new attributes are needed, so __slots__ is empty.
    # This prevents the creation of __dict__ and saves memory.
    __slots__ = ()

    def __init__(self, value: int = 1, re_entrant: bool = True):
        """
        Initializes the SynchronizedDynaphore.

        Parameters:
            value (int): Initial number of permits (must be >= 0).
            re_entrant (bool): If True (default), uses an RLock.
        """
        super().__init__(value, re_entrant)

    def wait_or_raise(self, timeout: float) -> None:
        """
        Waits for a permit and acquires it, raising an exception on timeout.

        This method provides a stricter alternative to `wait_for_permit()`.

        Parameters:
            timeout (float): The maximum time in seconds to wait for a permit.

        Raises:
            TimeoutError: If a permit cannot be acquired within the specified timeout.
        """
        # We reuse the parent's well-defined waiting logic.
        # This call already handles the condition check, waiting, and decrementing the value.
        acquired = self.wait_for_permit(timeout=timeout)

        # If the parent method returns False (signifying a timeout),
        # we raise the exception.
        if not acquired:
            raise TimeoutError(f"Failed to acquire permit within the {timeout}-second timeout.")