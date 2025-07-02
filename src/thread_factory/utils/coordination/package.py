from __future__ import annotations

import inspect
import types
from collections import OrderedDict
from functools import update_wrapper
from threading import RLock
from typing import Any, Callable, Dict, Tuple


class Package:
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
    Coroutine functions are rejected. This class is strictly for sync callables.
    """

    __slots__ = ["_func", "_args", "_kwargs", "_signature_cache", "_frozen", "_lock"]

    def __init__(self, func: Callable[..., Any], *args: Any, **kwargs: Any):
        """
        Create a new Package wrapping the given function and initial arguments.

        Args:
            func: The target callable to wrap.
            *args: Positional arguments to pre-bind.
            **kwargs: Keyword arguments to pre-bind.

        Raises:
            TypeError: If func is not a callable or is a coroutine function.
        """
        if not callable(func):
            raise TypeError(f"Expected a callable, got {type(func).__name__}")
        if inspect.iscoroutinefunction(func):
            raise TypeError("Coroutine functions are not supported in Pack.")
        self._func: Callable[..., Any] = update_wrapper(lambda *a, **kw: func(*a, **kw), func)
        self._args: Tuple[Any, ...] = args
        self._kwargs: Dict[str, Any] = kwargs
        self._signature_cache: types.SimpleNamespace | None = None
        self._frozen: bool = False
        self._lock: RLock = RLock()

    @property
    def is_async(self) -> bool:
        """
        Check if the underlying function is async (coroutine). This is for info only.

        Returns:
            True if the original function was a coroutine function.
        """
        target = getattr(self._func, '__wrapped__', self._func)
        return inspect.iscoroutinefunction(target)

    def __call__(self, *extra_args: Any, **extra_kwargs: Any) -> Any:
        """
        Call the wrapped function with all stored and extra arguments.

        Args:
            *extra_args: Additional positional arguments.
            **extra_kwargs: Additional keyword arguments.

        Returns:
            The result of calling the function with combined arguments.

        Raises:
            TypeError: If required positional args are missing. In some cases,
                       missing positional args are filled with `0` as fallback.
        """
        with self._lock:
            all_args = self._args + extra_args
            all_kwargs = {**self._kwargs, **extra_kwargs}
            try:
                return self._func(*all_args, **all_kwargs)
            except TypeError as e:
                if "missing" in str(e) and "positional argument" in str(e):
                    sig = inspect.signature(self._func.__wrapped__)
                    required = [
                        p for p in sig.parameters.values()
                        if p.default is p.empty and p.kind in (
                            p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD
                        )
                    ]
                    if len(all_args) < len(required):
                        all_args += (0,) * (len(required) - len(all_args))
                        return self._func(*all_args, **all_kwargs)
                raise

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
            return Package(func, *(self._args + args), **{**self._kwargs, **kwargs})

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
            return self._args

    @property
    def kwargs(self) -> Dict[str, Any]:
        """Return a copy of the stored keyword arguments."""
        with self._lock:
            return dict(self._kwargs)

    @property
    def signature(self):
        """
        Return a pseudo-signature object representing bound args.

        Returns:
            SimpleNamespace with `arguments` dict containing arg0, arg1... and kwarg names.
        """
        with self._lock:
            if self._signature_cache is None:
                sig = inspect.signature(self._func.__wrapped__)
                arg_map = OrderedDict()
                for i, value in enumerate(self._args):
                    arg_map[f"arg{i}"] = value
                arg_map.update(self._kwargs)
                self._signature_cache = types.SimpleNamespace(arguments=arg_map)
            return self._signature_cache

    def __eq__(self, other: object) -> bool:
        """
        Compare Packages by identity of function and equality of args/kwargs.

        Returns:
            True if equal, False otherwise.
        """
        if not isinstance(other, Package):
            return False
        with self._lock, other._lock:
            return (
                self._func.__wrapped__ is other._func.__wrapped__ and
                self._args == other._args and
                self._kwargs == other._kwargs
            )

    def __hash__(self) -> int:
        """
        Hash based on function identity and arguments.
        """
        with self._lock:
            return hash((
                id(self._func.__wrapped__),
                self._args,
                frozenset(self._kwargs.items()),
            ))

    def __or__(self, other: Package) -> Package:
        """
        Pipe operator: output of this Package becomes input to the next.

        Example:
            (Pack(f) | Pack(g))(...) == g(f(...))

        Returns:
            A new composed Package.
        """
        if not isinstance(other, Package):
            raise TypeError("| expects another Package")
        return Package(lambda *a, **kw: other(self(*a, **kw)))

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
        return f"Package({self._func.__name__}, args={self._args}, kwargs={self._kwargs})"


# Short alias
Pack = Package
