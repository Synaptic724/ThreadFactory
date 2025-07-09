from __future__ import annotations
import inspect
import types
from collections import OrderedDict
from functools import update_wrapper
from threading import RLock
from typing import Any, Callable, Dict, Tuple, Iterable, Union, Optional
from types import SimpleNamespace
from thread_factory import ConcurrentList
from thread_factory.utilities.interfaces.disposable import IDisposable
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.concurrency.concurrent_list import ConcurrentList


class Package(IDisposable):
    """
    A thread-safe, delegate-style callable wrapper that supports argument memory,
    currying, composition, introspection, and function-style combination.

    This is useful when storing parameterized callables for deferred or threaded execution,
    such as in orchestration systems like `Conductor`.

    Features:
    ---------
    - Thread-safe mutations and calls
    - Stores args and kwargs to act like a pre-bound function
    - Can curry (return a new Package with additional args)
    - Can bind (mutate kwargs of current instance)
    - Can freeze to prevent future mutation
    - Supports composition via | and addition via +
    - Has hash, equality, signature, and repr support

    Example:
    --------
    >>> def greet(name, punctuation="!"): return f"Hello, {name}{punctuation}"
    >>> p = Package(greet, "Alice").bind(punctuation=".")
    >>> p()
    'Hello, Alice.'

    >>> q = p.curry("Bob")  # Adds another positional arg (ignored here)
    >>> q()
    'Hello, Alice.'

    >>> composed = p | Package(str.upper)
    >>> composed()
    'HELLO, ALICE.'

    Note:
    -----
    Coroutine and generator functions are rejected. This class is strictly for sync callables.
    """

    __slots__ = IDisposable.__slots__ + ["_func", "_args", "_kwargs", "_signature_cache", "_frozen", "_lock"]

    def __init__(self, func: Callable[..., Any], *args: Any, **kwargs: Any):
        """
        Create a new Package wrapping the given function and initial arguments.

        Args:
            func: The target callable to wrap.
            *args: Positional arguments to pre-bind.
            **kwargs: Keyword arguments to pre-bind.

        Raises:
            TypeError: If func is not a callable or is a coroutine/generator function.
        """
        super().__init__()
        if isinstance(func, Package):
            raise TypeError("Cannot create a Package from an existing Package instance directly. "
                            "Use .curry() or .bind() on the existing instance if you want to extend it, "
                            "or Pack.many() for collections.")

        normalized = self._normalize_task(func)  # Use helper for validation
        self._func: Callable[..., Any] = update_wrapper(lambda *a, **kw: normalized(*a, **kw), normalized)
        self._args: ConcurrentList = ConcurrentList(args)
        self._kwargs: ConcurrentDict = ConcurrentDict(kwargs)
        self._signature_cache: SimpleNamespace | None = None
        self._frozen: bool = False
        self._lock: RLock = RLock()

    def dispose(self) -> None:
        """
        Dispose of the Package, releasing any resources.
        This is a no-op for Package since it does not hold resources.
        """
        if self.disposed:
            return
        with self._lock:
            self._func = None
            self._args.dispose()
            self._args = None
            self._kwargs.dispose()
            self._kwargs = None
            self._signature_cache = None
            self._disposed = True

    @property
    def __doc__(self):
        """Returns the docstring of the wrapped function."""
        return getattr(self._func, '__doc__')

    @property
    def is_async(self) -> bool:
        """
        Check if the underlying function is async (coroutine). This is for info only.

        Returns:
            True if the original function was a coroutine function.
        """
        target = getattr(self._func, '__wrapped__', self._func)
        return inspect.iscoroutinefunction(target)

    def __or__(self, other: Package) -> Package:
        """
        Pipe operator: output of this Package becomes input to the next.
        """
        if not isinstance(other, Package):
            raise TypeError("| expects another Package")

        # This correctly calls the underlying function of `other` to bypass
        # its stored arguments, creating a true pipeline.
        def composed_callable(*a, **kw):
            result_of_first = self(*a, **kw)
            return other._func(result_of_first)

        return Package(composed_callable)

    @staticmethod
    def bundle(
            item: Optional[Union[Callable[..., Any], Package, Iterable[Union[Callable[..., Any], Package]]]]
    ) -> Union[Package, ConcurrentList[Package]]:
        """
        Converts the input into a single Pack instance or a ConcurrentList of Pack instances.
        Handles None, single callables, single Pack instances, and iterables of mixed types.

        Args:
            item: The input to "packify". Can be None, a single callable, a single Pack instance,
                  or an iterable containing callables and/or Pack instances.

        Returns:
            A single Package instance if the input was a single callable or Pack.
            A ConcurrentList of Package instances if the input was an iterable.

        Raises:
            TypeError: If the input is None or contains invalid callable types (e.g., async/generator).
        """
        if item is None:
            raise TypeError("Cannot Packify None input.")

        # If it's already a single Pack instance, return it directly
        if isinstance(item, Package):
            return item

        # If it's an iterable (list, tuple, etc.), use Pack.many to process it
        # Note: `Pack.many` already handles if elements within the iterable are already Packs
        if isinstance(item, Iterable):
            return Pack._pack_many(item)

        # If it's a single callable (and not already a Package), wrap it in a new Pack
        if callable(item):
            # The Pack constructor itself will validate the callable (sync/async/generator checks)
            return Pack(item)

        # If none of the above, it's an invalid type
        raise TypeError(
            f"Cannot Packify input of type {type(item).__name__}. Expected callable, Package, or iterable thereof.")

    # ───────────────────────── helper for deterministic dual lock ────────────
    @staticmethod
    def _acquire_two(a: "Package", b: "Package"):
        """
        Deterministic ordering helper for dual-lock acquisition.
        Always returns the two Package instances in ascending id() order, so
        every thread grabs multiple Package locks in the same sequence.
        """
        return (a, b) if id(a) <= id(b) else (b, a)


    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Package):
            return False

        first, second = Package._acquire_two(self, other)
        with first._lock, second._lock:
            return (
                    self._func.__wrapped__ is other._func.__wrapped__ and
                    tuple(self._args) == tuple(other._args) and
                    dict(self._kwargs) == dict(other._kwargs)
            )


    def __hash__(self) -> int:
        # copy under lock, then compute hash lock-free
        with self._lock:
            f = self._func.__wrapped__
            a = tuple(self._args)
            k = frozenset(self._kwargs.items())
        return hash((id(f), a, k))

    def __call__(self, *extra_args: Any, **extra_kwargs: Any) -> Any:
        """
        Calls the wrapped function with all stored and extra arguments.
        Gathers the arguments under the lock, then releases the lock
        before invoking the underlying function to avoid cross-thread
        contention when nested calls occur.
        """
        # ── gather args/kwargs atomically ────────────────────────────────
        with self._lock:
            all_args = tuple(self._args) + extra_args
            all_kwargs = {**dict(self._kwargs), **extra_kwargs}

        # ── invoke outside the lock for dead-lock freedom ───────────────
        return self._func(*all_args, **all_kwargs)

    @staticmethod
    def merge_many(packs: Iterable["Package"]) -> "Package":
        """
        Pipe a sequence of Packages left-to-right into a single composite Package.

        Example:
            combo = Package.merge_many([p1, p2, p3])
            result = combo(x)   # ≈ p3(p2(p1(x)))
        """
        packs_iter = list(packs)
        if not packs_iter:
            raise ValueError("merge_many() requires at least one Package")
        for i, p in enumerate(packs_iter):
            if not isinstance(p, Package):
                raise TypeError(f"Item at index {i} is not a Package: {p!r}")

        def _composed(*a: Any, **kw: Any) -> Any:
            val = packs_iter[0](*a, **kw)
            for p in packs_iter[1:]:
                val = p(val)
            return val

        return Package(_composed)


    @staticmethod
    def _normalize_task(task: Union[Callable, Package]) -> Callable:
        """
        Validate a callable or Package. If it's a Package, return its inner function.
        If it's a callable, validate it. No wrapping is done here to avoid recursion.

        Args:
            task: A raw callable or Package.

        Returns:
            A validated callable (either unwrapped or raw).

        Raises:
            TypeError: If task is invalid.
        """
        if task is None:
            raise TypeError("Cannot normalize None as a task.")
        if isinstance(task, Package):
            return task._func.__wrapped__  # allow deeper introspection for equality, etc.
        if not callable(task):
            raise TypeError(f"Expected callable, got {type(task).__name__}")
        if inspect.iscoroutinefunction(task):
            raise TypeError(f"Coroutine functions are not supported: {getattr(task, '__name__', repr(task))}")
        if inspect.isgeneratorfunction(task):
            raise TypeError(f"Generator functions are not supported: {getattr(task, '__name__', repr(task))}")
        return task

    @staticmethod
    def _normalize_many(
        tasks: Union[Callable, Package, Iterable[Union[Callable, Package]]]
    ) -> ConcurrentList[Package]:
        """
        Normalize a single callable, Package, or an iterable of them into a ConcurrentList of Package instances.

        This is used to ensure all tasks are safe, wrapped, and concurrency-ready before use in
        thread-based systems like Group or Conductor.

        Args:
            tasks: A single task or a collection of tasks.

        Returns:
            A ConcurrentList of validated, thread-safe Package instances.

        Raises:
            TypeError: If any task is invalid, None, or an async/coroutine/generator.
        """
        if tasks is None:
            raise TypeError("Tasks input cannot be None.")

        # Handle single callable or Package
        if isinstance(tasks, (Callable, Package)):
            return ConcurrentList([Package(Package._normalize_task(tasks))])

        if not isinstance(tasks, Iterable):
            raise TypeError(f"Expected a callable or iterable of callables, got {type(tasks).__name__}")

        result = ConcurrentList()
        for i, task in enumerate(tasks):
            try:
                if task is None:
                    raise TypeError("Task is None.")
                if not callable(task):
                    raise TypeError(f"Expected callable, got {type(task).__name__}")
                if inspect.iscoroutinefunction(task):
                    raise TypeError(f"Coroutine functions are not supported: {getattr(task, '__name__', repr(task))}")
                if inspect.isgeneratorfunction(task):
                    raise TypeError(f"Generator functions are not supported: {getattr(task, '__name__', repr(task))}")
                result.append(task if isinstance(task, Package) else Package(task))
            except Exception as e:
                raise TypeError(f"Invalid task at index {i}: {e}") from e

        return result

    # inside class Package …

    # ───────────────────────────── single item ───────────────────────────── #
    @staticmethod
    def _pack(task: Union[Callable, Package]) -> Package:
        """
        Internal mirror of `Pack()`. Ensures any callable or Package becomes a Package safely.
        Preserves identity and avoids double wrapping.
        """
        if isinstance(task, Package):
            return task
        return Pack(task)

    # ──────────────────────────── many items ─────────────────────────────── #
    @staticmethod
    def _pack_many(
            tasks: Union[Callable, Package, Iterable[Union[Callable, Package]]]
    ) -> ConcurrentList[Package]:
        """
        Internal mirror of `Pack()` for batch input. Always returns valid Packages.

        Args:
            tasks: A single task or iterable of tasks.

        Returns:
            ConcurrentList of Package objects.

        Raises:
            TypeError: On invalid input.
        """
        if tasks is None:
            raise TypeError("Tasks input cannot be None.")

        if isinstance(tasks, (Callable, Package)):
            return ConcurrentList([Package._pack(tasks)])

        if not isinstance(tasks, Iterable):
            raise TypeError(f"Expected a callable or iterable of callables, got {type(tasks).__name__}")

        result = ConcurrentList()
        for i, task in enumerate(tasks):
            try:
                result.append(Package._pack(task))
            except Exception as e:
                raise TypeError(f"Invalid task at index {i}: {e}") from e

        return result

    def bind_args(self, *new_args: Any) -> Package:
        """
        Mutably replace the positional arguments of this Package.

        Args:
            *new_args: New positional arguments to replace the current ones.

        Returns:
            self

        Raises:
            RuntimeError: If the package is frozen.
        """
        with self._lock:
            if self._frozen:
                raise RuntimeError("Package is frozen.")
            self._args.clear()
            self._args.extend(new_args)
            self._signature_cache = None
            return self

    def bind(self, **new_kwargs: Any) -> Package:
        """
        Mutably add or update keyword arguments.

        Args:
            **new_kwargs: Keyword arguments to merge into the package.

        Returns:
            self

        Raises:
            RuntimeError: If the package is frozen.
        """
        with self._lock:
            if new_kwargs:
                if self._frozen:
                    raise RuntimeError("Package is frozen.")
                self._kwargs.update(new_kwargs)
                self._signature_cache = None
            return self

    def override(self, *args: Any, **kwargs: Any) -> Package:
        """
        Mutably override both args and kwargs.
        WARNING: This modifies the original Package!

        Args:
            *args: Positional arguments to set.
            **kwargs: Keyword arguments to merge.

        Returns:
            self

        Raises:
            RuntimeError: If the package is frozen.
        """
        with self._lock:
            if self._frozen:
                raise RuntimeError("Package is frozen.")
            self._args.clear()
            self._args.extend(args)
            self._kwargs.clear()
            self._kwargs.update(kwargs)
            self._signature_cache = None
            return self

    def curry(self, *args: Any, **kwargs: Any) -> Package:
        """
        Create a new Package with additional positional and keyword arguments.

        Args:
            *args: Extra args to append.
            **kwargs: Extra kwargs to merge.

        Returns:
            A new Package with combined arguments.
        """
        with self._lock:
            func = self._func.__wrapped__ if (args or kwargs) else self._func
            return Package(func, *(tuple(self._args) + args), **{**dict(self._kwargs), **kwargs})

    def freeze(self) -> None:
        """
        Prevent any future mutation (via `bind()`).
        """
        with self._lock:
            self._frozen = True

    @property
    def args(self) -> Tuple[Any, ...]:
        """Return the stored positional arguments."""
        with self._lock:
            return tuple(self._args)

    @property
    def kwargs(self) -> ConcurrentDict:
        """Return a thread-safe copy of the stored keyword arguments."""
        with self._lock:
            return ConcurrentDict(self._kwargs)

    @property
    def signature(self):
        """
        Return a pseudo-signature object representing bound args.

        Returns:
            SimpleNamespace with `arguments` ConcurrentDict containing arg0, arg1... and kwarg names.
        """
        with self._lock:
            if self._signature_cache is None:
                sig = inspect.signature(self._func.__wrapped__)
                arg_map = ConcurrentDict()
                for i, value in enumerate(self._args):
                    arg_map[f"arg{i}"] = value
                arg_map.update(self._kwargs)
                self._signature_cache = types.SimpleNamespace(arguments=arg_map)
            return self._signature_cache


    def __add__(self, other: Package) -> Package:
        """
        Add operator: sum results of both packages.

        Example:
            (Pack(f) + Pack(g))(...) == f(...) + g(...)

        Returns:
            A new Package that adds both results.
        """
        if not isinstance(other, Package):
            raise TypeError("+ expects another Package")
        return Package(lambda *a, **kw: self(*a, **kw) + other(*a, **kw))

    def __getattr__(self, item: str):
        """
        Delegate attribute access to the wrapped function.
        """
        try:
            return getattr(self._func, item)
        except AttributeError:
            raise AttributeError(item) from None

    def __dir__(self):
        """
        Merge function attributes with class attributes for autocompletion.
        """
        return sorted(
            set(super().__dir__())
            | set(dir(self._func))
            | set(dir(self._func.__wrapped__))
        )

    def __repr__(self) -> str:
        return f"Package({self._func.__name__}, args={tuple(self._args)}, kwargs={dict(self._kwargs)})"


# Short alias
Pack = Package
