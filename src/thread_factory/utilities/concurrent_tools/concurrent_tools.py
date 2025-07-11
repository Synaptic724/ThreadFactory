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

# Type variables for generic typing
_T = TypeVar("_T")
_R = TypeVar("_R")


def _default_max_workers() -> int:
    """
    Return an explicit default for max_workers, typically the CPU count
    or 1 if that's unavailable.

    By using os.cpu_count(), we try to maximize concurrency by default.
    If os.cpu_count() returns None for some reason, we default to 1.
    """
    return os.cpu_count() or 1


def _chunked_iter(input_iter: Iterable[_T], sz: int):
    """
    Yield successive chunks (lists) of size `sz` from `input_iter`.

    This function uses `itertools.islice` to grab portions of the input iterable
    in fixed-size batches. Once it cannot retrieve more items, it stops.
    """
    while True:
        batch = list(itertools.islice(input_iter, sz))
        if not batch:
            break
        yield batch


class ConcurrentTools:
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
      - chunk_size logic that tries to create roughly 4 chunks per executor by default

    NOTICE:
      This class accepts user-defined functions and runs them concurrently.
      It does not enforce thread safety.
      If your functions modify shared state or access shared resources,
      you are responsible for implementing your own thread-safety mechanisms
      (e.g., locks, thread-local storage, or other synchronization primitives).
    """
    __slots__ = []
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

        :param start: The first integer index (inclusive).
        :param stop: The stopping integer index (exclusive).
        :param body: The function to apply to each integer (if no local state is used).
        :param max_workers: The maximum number of threads to use. Defaults to CPU count.
        :param chunk_size: Size of each chunk of indices to process. Defaults to ~1/4 of total work per thread.
        :param stop_on_exception: If True, once an exception occurs in one chunk, remaining chunks will be canceled.
        :param local_init: Optional function that initializes a local state object for each thread.
        :param local_body: Optional function that uses the local state object. Called for each index if local state is used.
        :param local_finalize: Optional function to finalize the local state for each thread after all items in the chunk are processed.
        """
        if start >= stop:
            # If there is no work to do (e.g., start >= stop), exit early.
            return

        # Determine the actual number of workers to use.
        mw = max_workers or _default_max_workers()
        total = stop - start

        # Check if local state is being used (i.e., local_init + local_body).
        use_local_state = (local_init is not None) and (local_body is not None)

        # Heuristic for chunk size: ~4 chunks per executor if not explicitly given by the caller.
        # This attempts to balance load between threads and reduce overhead.
        if chunk_size is None:
            chunk_size = max(1, total // (mw * 4) or 1)

        # If we want to stop on exception, create a threading.Event to signal early cancellation.
        stop_event = threading.Event() if stop_on_exception else None

        # We'll keep a list of Future objects to wait on them (and catch exceptions).
        futures: List[Future] = []
        with ThreadPoolExecutor(max_workers=mw) as executor:
            # Create a worker chunk for each segment of the index range.
            for chunk_start in range(start, stop, chunk_size):
                chunk_end = min(chunk_start + chunk_size, stop)
                future = executor.submit(
                    ConcurrentTools._for_loop_worker_chunk,
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

            # Wait for each Future to complete. If an exception is raised,
            # optionally signal the stop_event and re-raise the exception to the caller.
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

        :param chunk_start: The beginning of the index range (inclusive).
        :param chunk_end: The end of the index range (exclusive).
        :param body: The function to apply if no local state is used.
        :param local_init: Function that initializes a thread-local state, if used.
        :param local_body: Function that applies to each index with the thread-local state, if used.
        :param local_finalize: Function that finalizes the thread-local state, if provided.
        :param stop_event: Optional event to signal that we should stop processing (due to an exception in another thread).
        :param use_local_state: Whether we should use local state or not.
        """
        # If we've already been asked to stop, return immediately.
        if stop_event and stop_event.is_set():
            return

        try:
            if use_local_state:
                # If local state is in use, initialize it once per thread, then iterate over the chunk.
                assert local_init is not None
                assert local_body is not None
                state = local_init()
                try:
                    for i in range(chunk_start, chunk_end):
                        if stop_event and stop_event.is_set():
                            return
                        local_body(i, state)
                finally:
                    # Optionally finalize the local state once we're done with the chunk.
                    if local_finalize:
                        local_finalize(state)
            else:
                # If no local state is used, just call 'body' for each index.
                for i in range(chunk_start, chunk_end):
                    if stop_event and stop_event.is_set():
                        return
                    body(i)
        except Exception as e:
            # Raise the exception so the parent method can handle it (and possibly signal stop_event).
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

        :param iterable: The data to process. Can be any iterable.
        :param action: The function to apply to each item.
        :param max_workers: Maximum number of threads. Defaults to CPU count.
        :param chunk_size: Number of items per chunk. Defaults to ~1/4 of total items per thread (unless streaming).
        :param stop_on_exception: If True, once an exception occurs on one chunk, remaining chunks are canceled.
        :param streaming: If True, process the iterable in a streaming manner (avoid loading the entire list into memory).
        """
        mw = max_workers or _default_max_workers()
        stop_event = threading.Event() if stop_on_exception else None

        if streaming:
            # In streaming mode, we do not convert the entire iterable to a list.
            # Instead, we consume it in chunks (via _chunked_iter).
            if chunk_size is None:
                # If user didn't specify chunk_size, we use a default (e.g., 256).
                chunk_size = 256

            futures: List[Future] = []
            with ThreadPoolExecutor(max_workers=mw) as executor:
                # We read the iterable in chunks and submit each chunk to the thread pool.
                for sublist in _chunked_iter(iterable, chunk_size):
                    if stop_event and stop_event.is_set():
                        break
                    future = executor.submit(
                        ConcurrentTools._foreach_worker_chunk,
                        sublist,
                        action,
                        stop_event
                    )
                    futures.append(future)

                # Wait on all futures; if an exception occurs, optionally signal stop_event.
                for f in as_completed(futures):
                    try:
                        f.result()
                    except Exception:
                        if stop_event and not stop_event.is_set():
                            stop_event.set()
                        raise
        else:
            # Non-streaming mode: we convert the entire iterable to a list first.
            if isinstance(iterable, list):
                items = iterable
            else:
                items = list(iterable)

            total = len(items)
            if total == 0:
                return

            # Default chunk size if none provided: ~1/4 of total items per thread.
            if chunk_size is None:
                chunk_size = max(1, total // (mw * 4) or 1)

            futures: List[Future] = []
            with ThreadPoolExecutor(max_workers=mw) as executor:
                # Create tasks for each chunk of the list.
                for start_index in range(0, total, chunk_size):
                    end_index = min(start_index + chunk_size, total)
                    sublist = items[start_index:end_index]
                    future = executor.submit(
                        ConcurrentTools._foreach_worker_chunk,
                        sublist,
                        action,
                        stop_event
                    )
                    futures.append(future)

                # Wait for completion, handle exceptions.
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

        :param sublist: The chunk of items to process.
        :param action: The function to apply to each item.
        :param stop_event: Optional event to signal early cancellation.
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

        :param functions: Any number of callable objects (no arguments).
        :param wait: If True (default), block until all functions finish.
        :param max_workers: The maximum number of threads to use. Defaults to CPU count.
        :return: A list of Future objects. If wait=True, the futures will already be complete.
        """
        if not functions:
            return []

        mw = max_workers or _default_max_workers()

        futures: List[Future] = []
        with ThreadPoolExecutor(max_workers=mw) as executor:
            # Submit each function to the pool. _invoke_wrapper is a helper to handle exceptions uniformly.
            for fn in functions:
                futures.append(executor.submit(ConcurrentTools._invoke_wrapper, fn))

            if wait:
                # If the user wants to wait, we use as_completed to raise any exceptions.
                for f in as_completed(futures):
                    f.result()

        return futures

    @staticmethod
    def _invoke_wrapper(fn: Callable[[], Any]) -> Any:
        """
        Wrapper for invoke() tasks to handle exceptions explicitly.

        :param fn: A function with no arguments.
        :return: The return value of the function.
        :raises Exception: Propagates any exception that occurs within 'fn'.
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

        :param iterable: The data to process in parallel.
        :param transform: The function that transforms each item.
        :param max_workers: The maximum number of threads to use. Defaults to CPU count.
        :param chunk_size: Chunk size (defaults to ~1/4 of the total items per thread).
        :return: A list of transformed items in the same order as the original iterable.
        """
        # Convert the iterable to a list so we can index it.
        # We need random access to preserve original order in the result.
        items = list(iterable)
        total = len(items)
        if total == 0:
            return []

        mw = max_workers or _default_max_workers()
        if chunk_size is None:
            # Same chunking heuristic as for_loop and for_each.
            chunk_size = max(1, total // (mw * 4) or 1)

        # We create a results list and fill it in place.
        results: List[Optional[_R]] = [None] * total

        futures: List[Future] = []
        with ThreadPoolExecutor(max_workers=mw) as executor:
            # Submit each chunk to the executor.
            for start_index in range(0, total, chunk_size):
                end_index = min(start_index + chunk_size, total)
                futures.append(
                    executor.submit(
                        ConcurrentTools._map_worker_chunk,
                        items,
                        results,
                        transform,
                        start_index,
                        end_index
                    )
                )

            # Wait for all futures to complete and raise any exceptions.
            for f in as_completed(futures):
                f.result()

        # If there are no Nones in results, just return results directly.
        # Otherwise, filter out any None items. (Normally, you shouldn't see None
        # unless there's an unexpected condition, but this is just a safeguard.)
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
        Worker function for map(). Transforms items in-place into results
        within [start_index, end_index).

        :param items: The original items to transform.
        :param results: The shared results list to fill.
        :param transform: The user-defined transform function.
        :param start_index: Chunk start position in the list.
        :param end_index: Chunk end position in the list (exclusive).
        """
        try:
            # For each item in this chunk, apply the transform and store it in the results list.
            for i in range(start_index, end_index):
                results[i] = transform(items[i])
        except Exception as e:
            # Propagate any errors to be handled by the main method.
            raise e
