import os
import threading
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from typing import (
    Any,
    Callable,
    Iterable,
    List,
    Optional,
    Tuple,
    TypeVar,
    Union
)
import itertools

_T = TypeVar("_T")
_R = TypeVar("_R")

def _default_max_workers() -> int:
    """
    Return an explicit default for max_workers, typically the CPU count
    or 1 if that's unavailable.
    """
    return os.cpu_count() or 1

class Parallel:
    """
    A Python class that mimics .NET's Task Parallel Library (TPL)-style operations:
      - parallel_for
      - parallel_foreach
      - parallel_invoke
      - parallel_map

    with optional features like:
      - local state for parallel_for (local_init/local_finalize)
      - streaming mode in parallel_foreach to avoid loading the entire iterable into memory
      - stop_on_exception to cancel remaining chunks if an exception occurs in one chunk
      - explicit default for max_workers using os.cpu_count()
      - chunk_size logic that tries to create roughly 4 chunks per worker by default
    """

    @staticmethod
    def parallel_for(
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
        Execute the given 'body' (or 'local_body') for each integer in the range [start, stop)
        in parallel, optionally with local state initialization/finalization.

        Args:
            start (int): The start of the range (inclusive).
            stop (int): The end of the range (exclusive).
            body (Callable[[int], None]): The function to call for each index
                if you don't use local_init/local_body. This is the "simple" usage.
            max_workers (int, optional): Maximum number of worker threads to spawn.
                Defaults to os.cpu_count(), or 1 if that is None.
            chunk_size (int, optional): How many loop iterations to group into one task.
                Defaults to roughly (stop - start) // (4 * max_workers) (never below 1).
            stop_on_exception (bool): If True, cancel remaining work as soon as
                one task fails.
            local_init (Callable[[], Any], optional):
                A function to initialize thread-local state. If provided, you should also
                provide local_body for processing each index with that local state.
            local_body (Callable[[int, Any], None], optional):
                A function that takes (index, local_state). If local_init is provided,
                parallel_for calls local_body instead of body, passing it the local_state.
            local_finalize (Callable[[Any], None], optional):
                A function that is called once per thread, after finishing that thread's chunk(s).
                Useful to combine partial results or free resources.

        Raises:
            Exception: Re-raises any exception from worker tasks.
        """
        if start >= stop:
            return  # No work to do

        mw = max_workers or _default_max_workers()
        total = stop - start

        # Decide if we use local state
        use_local_state = (local_init is not None) and (local_body is not None)

        if chunk_size is None:
            # Heuristic: create ~4 chunks per worker if possible
            chunk_size = max(1, total // (mw * 4) or 1)

        stop_event = threading.Event() if stop_on_exception else None

        def worker_chunk_for(chunk_start: int, chunk_end: int) -> None:
            """Worker function that processes [chunk_start, chunk_end)."""
            if stop_event and stop_event.is_set():
                return

            if use_local_state:
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

        futures: List[Future] = []
        with ThreadPoolExecutor(max_workers=mw) as executor:
            # Submit chunks
            for chunk_start in range(start, stop, chunk_size):
                chunk_end = min(chunk_start + chunk_size, stop)
                future = executor.submit(worker_chunk_for, chunk_start, chunk_end)
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
    def parallel_foreach(
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

        Args:
            iterable (Iterable[_T]): The sequence of items to process.
            action (Callable[[_T], None]): The function to call for each item.
            max_workers (int, optional): Maximum number of worker threads to spawn.
                Defaults to os.cpu_count() or 1 if that's None.
            chunk_size (int, optional): How many items to group into one task:
                - If streaming=False (the default): defaults to roughly len(iterable) // (4 * max_workers).
                - If streaming=True, defaults to 256 if not specified.
                  Keep in mind that a very small chunk_size (like 1) can lead to a high overhead of task submissions.
            stop_on_exception (bool): If True, cancel remaining work if any task fails.
            streaming (bool): If True, process the iterable in chunks without converting
                the entire input to a list. This saves memory for very large iterables, but
                chunk_size must be explicitly set or will default to 256. The total length
                is not computed in this mode.

        Raises:
            Exception: Re-raises any exception from worker tasks.
        """
        mw = max_workers or _default_max_workers()

        stop_event = threading.Event() if stop_on_exception else None

        if streaming:
            # We don't know total length, so we pick a default chunk_size if not provided
            if chunk_size is None:
                chunk_size = 256

            def chunked_iter(input_iter: Iterable[_T], sz: int):
                while True:
                    batch = list(itertools.islice(input_iter, sz))
                    if not batch:
                        break
                    yield batch

            futures: List[Future] = []
            with ThreadPoolExecutor(max_workers=mw) as executor:
                for sublist in chunked_iter(iterable, chunk_size):
                    if stop_event and stop_event.is_set():
                        break
                    future = executor.submit(
                        Parallel._foreach_worker_chunk,
                        sublist, action, stop_event
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
            # Non-streaming approach: check if iterable is already a list
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
                        Parallel._foreach_worker_chunk,
                        sublist, action, stop_event
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
        """Helper method: apply 'action' to each item in 'sublist', respecting stop_event if set."""
        for x in sublist:
            if stop_event and stop_event.is_set():
                return
            action(x)

    @staticmethod
    def parallel_invoke(
        *functions: Callable[[], Any],
        wait: bool = True,
        max_workers: Optional[int] = None
    ) -> List[Future]:
        """
        Execute multiple functions in parallel. Optionally wait for all
        functions to complete before returning.

        Args:
            *functions (Callable[[], Any]): A variable number of callables to run in parallel.
            wait (bool, optional): If True, wait for all tasks to complete. Default is True.
            max_workers (int, optional): Maximum number of worker threads to spawn.
                Defaults to os.cpu_count() or 1 if that's None.

        Returns:
            List[Future]: A list of futures representing the submitted tasks.
                          If wait=True, all tasks are completed before returning.
                          If wait=False, they're submitted but the executor is shut down
                          as soon as we exit this method's 'with' block, so they won't
                          keep running in background threads.
        """
        if not functions:
            return []

        mw = max_workers or _default_max_workers()

        futures: List[Future] = []
        with ThreadPoolExecutor(max_workers=mw) as executor:
            for fn in functions:
                futures.append(executor.submit(fn))

            if wait:
                for f in as_completed(futures):
                    f.result()

        return futures

    @staticmethod
    def parallel_map(
        iterable: Iterable[_T],
        transform: Callable[[_T], _R],
        *,
        max_workers: Optional[int] = None,
        chunk_size: Optional[int] = None
    ) -> List[_R]:
        """
        Transform each element of 'iterable' in parallel and return the results
        in the original order. Similar to built-in map, but parallelized.

        Args:
            iterable (Iterable[_T]): The input sequence.
            transform (Callable[[_T], _R]): The function to map each element.
            max_workers (int, optional): Maximum number of worker threads to spawn.
                Defaults to os.cpu_count() or 1 if that's None.
            chunk_size (int, optional): How many items to group into one task.
                Defaults to roughly (len(iterable) // (4 * max_workers)) (never below 1).

        Returns:
            List[_R]: The list of transformed items in the same order.

        Raises:
            Exception: Re-raises any exception from worker tasks.
        """
        items = list(iterable)  # For preserving order, we need random access by index
        total = len(items)
        if total == 0:
            return []

        mw = max_workers or _default_max_workers()
        if chunk_size is None:
            # same default chunking logic as parallel_for/foreach (non-streaming)
            chunk_size = max(1, total // (mw * 4) or 1)

        results: List[Optional[_R]] = [None] * total
        lock = threading.Lock()

        def worker_map_chunk(start_index: int, end_index: int) -> None:
            for i in range(start_index, end_index):
                out = transform(items[i])
                with lock:
                    results[i] = out

        futures: List[Future] = []
        with ThreadPoolExecutor(max_workers=mw) as executor:
            for start_index in range(0, total, chunk_size):
                end_index = min(start_index + chunk_size, total)
                futures.append(executor.submit(worker_map_chunk, start_index, end_index))

            for f in as_completed(futures):
                f.result()

        return [r for r in results if r is not None] if None in results else results
