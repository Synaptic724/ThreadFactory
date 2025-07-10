import logging, ulid, ctypes, threading
from typing import Optional, Callable, Union, Any, List
from thread_factory.utilities.exceptions.empty import Empty
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.utilities.coordination.package import Pack
from thread_factory.utilities.interfaces.disposable import IDisposable
from thread_factory.concurrency.concurrent_stack import ConcurrentStack
from thread_factory.concurrency.concurrent_list import ConcurrentList


class LocationMap(IDisposable):
    """
    LocationMap
    -----------
    A centralized routing and execution manager for agent locations.

    This object replaces the flat `locations` dict and raw call stack logic
    with a unified, traceable execution map.

    Key Features:
    - Register user-defined and system-level locations.
    - Transit into locations with automatic stack tracking.
    - Full call stack visibility, depth, and tracing.
    - Safe for concurrent inspection and debugging.
    """

    def __init__(self, agent: Any, logger: Optional[logging.Logger] = None):
        super().__init__()
        self._logger = logger or logging.getLogger(__name__)
        self._lock = threading.RLock()
        self._agent = agent
        self._locations = ConcurrentDict[str, Pack]()
        self._stack = ConcurrentStack[str]()

    def dispose(self):
        """
        Disposes of the LocationMap, clearing all registered locations and the call stack.
        """
        if self._disposed:
            return
        with self._lock:
            self._disposed = True
            self._logger.debug("Disposing LocationMap and clearing all locations.")
            self._locations.dispose()
            self._locations = None
            self._stack.dispose()
            self._stack = None
            self._logger = None

    def register_location(self, name: str, fn: Union[Callable[..., None], Pack]):
        """
        Registers a named callable as a distinct "location" or execution zone.
        This allows the agent to dynamically switch between different behaviors.

        Args:
            name (str): The unique name for the location.
            fn (Union[Callable[..., None], Pack]): The callable function or `Pack`
                defining the location's behavior.
        """
        if self._disposed:
            raise RuntimeError("Cannot register location on a disposed agent.")
        if self._locations.get(name) is not None:
            self._logger.warning(f"Overwriting existing location '{name}' with new function.")
        self._locations[name] = Pack.bundle(fn) if fn else None

    def register_locations(self, mappings: dict[str, Union[Callable[..., Any], Pack]]) -> None:
        """
        Registers multiple named callables or `Pack` instances into the location map.

        This method simplifies batch registration of agent behaviors. Each key in the
        dictionary becomes a named location accessible via the `LocationMap`.

        Args:
            mappings (dict[str, Union[Callable[..., Any], Pack]]): A mapping of names to callables or `Pack`s.

        Raises:
            TypeError: If any value is not a callable or `Pack`.
            RuntimeError: If the LocationMap has been disposed.
        """
        if self._disposed:
            raise RuntimeError("Cannot register locations on a disposed LocationMap.")

        for name, fn in mappings.items():
            self.register_location(name, fn)

    def get(self, name: str) -> Optional[Pack]:
        """
        Retrieves a registered location by name.

        Args:
            name (str): The name of the location.

        Returns:
            Optional[Pack]: The registered location function, or None.
        """
        return self._locations.get(name)

    def transit_to(self, name: str, should_raise: bool = False) -> Any:
        """
        Enters a user-defined location and pushes it to the call stack.

        Args:
            name (str): Name of the registered location to enter.
            should_raise (bool): If True, exceptions will propagate; otherwise, they are logged.

        Returns:
            Any: Result of executing the location's function.
        """
        self._stack.push(name)
        try:
            fn = self.get(name)
            if fn is None:
                raise KeyError(f"Location '{name}' is not registered.")
            return fn()
        except Exception as e:
            self._logger.exception(f"Error while executing location '{name}'. Exception: {e}")
            if should_raise:
                raise e
            pass
        finally:
            self._stack.pop()

    def transit_internal(self, name: str, fn: Callable, should_rase: bool= False) -> Any:
        """
        Executes an internal system function with call stack tagging.

        Args:
            name (str): System tag for this transition.
            fn (Callable): Function to execute.
            should_rase (bool): If True, exceptions will propagate; otherwise, they are logged.

        Returns:
            Any: The result of the internal function's execution.
        """
        tag = f"[system:{name}]"
        self._stack.push(tag)
        try:
            return fn()
        except Exception as e:
            self._logger.exception(f"Error while executing internal function '{name}'. Exception: {e}")
            if should_rase:
                raise
            pass
        finally:
            self._stack.pop()

    def get_locations(self) -> ConcurrentDict[str, Pack]:
        """
        Returns a shallow copy of all registered locations.

        Returns:
            ConcurrentDict[str, Pack]: Copy of location map.
        """
        return self._locations.copy()

    def trace_stack(self) -> str:
        """
        Returns a human-readable trace of the agent's current call stack.

        Returns:
            str: A string like: `[home] → process_data → [system:save]`
        """
        return " → ".join(self._stack.to_concurrent_list())

    def peek_stack(self) -> Optional[str]:
        """
        Peeks at the top of the stack without modifying it.

        Returns:
            Optional[str]: Top-most location or None if the stack is empty.
        """
        try:
            return self._stack.peek()
        except Empty:
            return None

    def get_stack(self) -> ConcurrentList[str]:
        """
        Returns a snapshot of the current call stack.

        Returns:
            ConcurrentList[str]: A copy of the stack.
        """
        return self._stack.to_concurrent_list()

    def stack_depth(self) -> int:
        """
        Returns the number of active location layers.

        Returns:
            int: Current depth of the stack.
        """
        return len(self._stack)


def get_stack(self) -> ConcurrentList[str]:
    """
    Returns a snapshot of the current call stack as a list.

    This is useful for structured inspection, logging, or exporting.

    Returns:
        List[str]: A list of location names from base to current.
    """
    return self._call_stack.to_concurrent_list()
