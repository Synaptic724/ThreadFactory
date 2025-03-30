import itertools
import os
import threading
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from typing import (
    Any,
    Callable,
    Iterable,
    List,
    Optional,
    TypeVar
)

_T = TypeVar("_T")
_R = TypeVar("_R")

def _default_max_workers() -> int:
    """
    Return an explicit default for max_workers, typically the CPU count
    or 1 if that's unavailable.
    """
    return os.cpu_count() or 1

def _chunked_iter(input_iter: Iterable[_T], sz: int):
    """
    Yield successive chunks (lists) of size sz from input_iter.
    """
    while True:
        batch = list(itertools.islice(input_iter, sz))
        if not batch:
            break
        yield batch

class Concurrent:
    """
    A Python class that mimics .NET's Task Parallel Library (TPL)-style operations:
      - for_loop
      - for_each
      - invoke
      - map

    Optional features include:
      - Local state management for parallel_for (via local_init/local_finalize)
      - Streaming mode in parallel_foreach to avoid loading the entire iterable into memory
      - stop_on_exception to cancel remaining chunks if an exception occurs in one chunk
      - Explicit default for max_workers using os.cpu_count()
      - chunk_size logic that tries to create roughly 4 chunks per worker by default

    NOTICE:
      This class accepts user-defined functions and runs them concurrently.
      It does not enforce thread safety.
      If your functions modify shared state or access shared resources,
      you are responsible for implementing your own thread-safety mechanisms
      (e.g., locks, thread-local storage, or other synchronization primitives).
    """
    @staticmethod
    def for_loop(
        start: int,
        stop: int,
        body: Callable[[int], None],
        *,
        max_workers: Optional[int] = None,
        chunk_size: Optional[int] = None,
        stop_on_exception: bool = False,
        local_init: Optional[Callable[[], Any]] = None,
        local_body: Optional[Callable[[int, Any], None]] = None,
        local_finalize: Optional[Callable[[Any], None]] = None
    ) -> None:
        """
        Execute the given 'body' (or 'local_body') for each integer in [start, stop)
        in parallel, optionally with local state initialization/finalization.
        """
        if start >= stop:
            return  # No work to do

        mw = max_workers or _default_max_workers()
        total = stop - start

        # Decide if we use local state:
        use_local_state = (local_init is not None) and (local_body is not None)

        # Heuristic for chunk size: ~4 chunks per worker if not explicitly given
        if chunk_size is None:
            chunk_size = max(1, total // (mw * 4) or 1)

        stop_event = threading.Event() if stop_on_exception else None

        # Prepare tasks
        futures: List[Future] = []
        with ThreadPoolExecutor(max_workers=mw) as executor:
            for chunk_start in range(start, stop, chunk_size):
                chunk_end = min(chunk_start + chunk_size, stop)
                future = executor.submit(
                    Concurrent._for_loop_worker_chunk,
                    chunk_start,
                    chunk_end,
                    body,
                    local_init,
                    local_body,
                    local_finalize,
                    stop_event,
                    use_local_state
                )
                futures.append(future)

            # Wait for tasks to complete and handle exceptions
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception:
                    if stop_event and not stop_event.is_set():
                        stop_event.set()
                    raise

    @staticmethod
    def _for_loop_worker_chunk(
        chunk_start: int,
        chunk_end: int,
        body: Callable[[int], None],
        local_init: Optional[Callable[[], Any]],
        local_body: Optional[Callable[[int, Any], None]],
        local_finalize: Optional[Callable[[Any], None]],
        stop_event: Optional[threading.Event],
        use_local_state: bool
    ) -> None:
        """
        Worker function for for_loop that processes a chunk of indices [chunk_start, chunk_end).
        """
        if stop_event and stop_event.is_set():
            return

        try:
            if use_local_state:
                assert local_init is not None
                assert local_body is not None
                state = local_init()
                try:
                    for i in range(chunk_start, chunk_end):
                        if stop_event and stop_event.is_set():
                            return
                        local_body(i, state)
                finally:
                    if local_finalize:
                        local_finalize(state)
            else:
                for i in range(chunk_start, chunk_end):
                    if stop_event and stop_event.is_set():
                        return
                    body(i)
        except Exception as e:
            # We capture the exception to allow the main method to handle it
            raise e

    @staticmethod
    def for_each(
        iterable: Iterable[_T],
        action: Callable[[_T], None],
        *,
        max_workers: Optional[int] = None,
        chunk_size: Optional[int] = None,
        stop_on_exception: bool = False,
        streaming: bool = False
    ) -> None:
        """
        Execute the given action for each item in the iterable in parallel.
        """
        mw = max_workers or _default_max_workers()
        stop_event = threading.Event() if stop_on_exception else None

        if streaming:
            # We don't know total length, so pick a default chunk_size if not provided
            if chunk_size is None:
                chunk_size = 256

            futures: List[Future] = []
            with ThreadPoolExecutor(max_workers=mw) as executor:
                for sublist in _chunked_iter(iterable, chunk_size):
                    if stop_event and stop_event.is_set():
                        break
                    future = executor.submit(
                        Concurrent._foreach_worker_chunk,
                        sublist,
                        action,
                        stop_event
                    )
                    futures.append(future)

                for f in as_completed(futures):
                    try:
                        f.result()
                    except Exception:
                        if stop_event and not stop_event.is_set():
                            stop_event.set()
                        raise
        else:
            # Non-streaming: convert to list if not already one
            if isinstance(iterable, list):
                items = iterable
            else:
                items = list(iterable)

            total = len(items)
            if total == 0:
                return

            if chunk_size is None:
                chunk_size = max(1, total // (mw * 4) or 1)

            futures: List[Future] = []
            with ThreadPoolExecutor(max_workers=mw) as executor:
                for start_index in range(0, total, chunk_size):
                    end_index = min(start_index + chunk_size, total)
                    sublist = items[start_index:end_index]
                    future = executor.submit(
                        Concurrent._foreach_worker_chunk,
                        sublist,
                        action,
                        stop_event
                    )
                    futures.append(future)

                for f in as_completed(futures):
                    try:
                        f.result()
                    except Exception:
                        if stop_event and not stop_event.is_set():
                            stop_event.set()
                        raise

    @staticmethod
    def _foreach_worker_chunk(
        sublist: List[_T],
        action: Callable[[_T], None],
        stop_event: Optional[threading.Event]
    ) -> None:
        """
        Helper method: apply 'action' to each item in 'sublist', respecting stop_event if set.
        """
        if stop_event and stop_event.is_set():
            return

        try:
            for x in sublist:
                if stop_event and stop_event.is_set():
                    return
                action(x)
        except Exception as e:
            raise e

    @staticmethod
    def invoke(
        *functions: Callable[[], Any],
        wait: bool = True,
        max_workers: Optional[int] = None
    ) -> List[Future]:
        """
        Execute multiple functions in parallel. Optionally wait for all
        functions to complete before returning.
        """
        if not functions:
            return []

        mw = max_workers or _default_max_workers()

        futures: List[Future] = []
        with ThreadPoolExecutor(max_workers=mw) as executor:
            for fn in functions:
                futures.append(executor.submit(Concurrent._invoke_wrapper, fn))

            if wait:
                for f in as_completed(futures):
                    # Raises any exceptions from the worker
                    f.result()

        return futures

    @staticmethod
    def _invoke_wrapper(fn: Callable[[], Any]) -> Any:
        """
        Wrapper for invoke() tasks to handle exceptions explicitly.
        """
        try:
            return fn()
        except Exception as e:
            raise e

    @staticmethod
    def map(
        iterable: Iterable[_T],
        transform: Callable[[_T], _R],
        *,
        max_workers: Optional[int] = None,
        chunk_size: Optional[int] = None
    ) -> List[_R]:
        """
        Transform each element of 'iterable' in parallel and return the results
        in the original order. Similar to built-in map, but parallelized.
        """
        items = list(iterable)  # We need random access by index to preserve order
        total = len(items)
        if total == 0:
            return []

        mw = max_workers or _default_max_workers()
        if chunk_size is None:
            # same default chunking logic
            chunk_size = max(1, total // (mw * 4) or 1)

        results: List[Optional[_R]] = [None] * total

        futures: List[Future] = []
        with ThreadPoolExecutor(max_workers=mw) as executor:
            for start_index in range(0, total, chunk_size):
                end_index = min(start_index + chunk_size, total)
                futures.append(
                    executor.submit(
                        Concurrent._map_worker_chunk,
                        items,
                        results,
                        transform,
                        start_index,
                        end_index
                    )
                )

            for f in as_completed(futures):
                f.result()  # Raise any exceptions

        # If no "None" left, just return results directly
        return [r for r in results if r is not None] if None in results else results

    @staticmethod
    def _map_worker_chunk(
        items: List[_T],
        results: List[Optional[_R]],
        transform: Callable[[_T], _R],
        start_index: int,
        end_index: int
    ) -> None:
        """
        Worker function for map(), transforms items in-place into results within [start_index, end_index).
        """
        try:
            for i in range(start_index, end_index):
                results[i] = transform(items[i])
        except Exception as e:
            raise e
