from __future__ import annotations

import inspect
import types
from collections import OrderedDict
from functools import update_wrapper
from threading import RLock
from typing import Any, Callable, Dict, Tuple


class Package:
    """
    Thread-safe delegate-style callable wrapper with built-in argument memory,
    hashing, composition, and introspection support.

    - Acts like the wrapped function
    - Thread-safe with mutation lock
    - Supports curry, bind, pipe (|), and addition (+)
    """

    __slots__ = ["_func", "_args", "_kwargs", "_signature_cache", "_frozen", "_lock"]

    def __init__(self, func: Callable[..., Any], *args: Any, **kwargs: Any):
        if not callable(func):
            raise TypeError(f"Expected a callable, got {type(func).__name__}")
        self._func: Callable[..., Any] = update_wrapper(lambda *a, **kw: func(*a, **kw), func)
        self._args: Tuple[Any, ...] = args
        self._kwargs: Dict[str, Any] = kwargs
        self._signature_cache: types.SimpleNamespace | None = None
        self._frozen: bool = False
        self._lock: RLock = RLock()

    def __call__(self, *extra_args: Any, **extra_kwargs: Any) -> Any:
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
        with self._lock:
            if new_kwargs:
                if self._frozen:
                    raise RuntimeError("Package is frozen.")
                self._kwargs.update(new_kwargs)
                self._signature_cache = None
            return self

    def curry(self, *args: Any, **kwargs: Any) -> Package:
        with self._lock:
            func = self._func.__wrapped__ if (args or kwargs) else self._func
            return Package(func, *(self._args + args), **{**self._kwargs, **kwargs})

    def freeze(self) -> None:
        with self._lock:
            self._frozen = True

    @property
    def args(self) -> Tuple[Any, ...]:
        with self._lock:
            return self._args

    @property
    def kwargs(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._kwargs)

    @property
    def signature(self):
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
        if not isinstance(other, Package):
            return False
        with self._lock, other._lock:
            return (
                self._func.__wrapped__ is other._func.__wrapped__ and
                self._args == other._args and
                self._kwargs == other._kwargs
            )

    def __hash__(self) -> int:
        with self._lock:
            return hash((
                id(self._func.__wrapped__),
                self._args,
                frozenset(self._kwargs.items()),
            ))

    def __or__(self, other: Package) -> Package:
        if not isinstance(other, Package):
            raise TypeError("| expects another Package")
        return Package(lambda *a, **kw: other(self(*a, **kw)))

    def __add__(self, other: Package) -> Package:
        if not isinstance(other, Package):
            raise TypeError("+ expects another Package")
        return Package(lambda *a, **kw: self(*a, **kw) + other(*a, **kw))

    def __getattr__(self, item: str):
        try:
            return getattr(self._func, item)
        except AttributeError:
            raise AttributeError(item) from None

    def __dir__(self):
        return sorted(
            set(super().__dir__())
            | set(dir(self._func))
            | set(dir(self._func.__wrapped__))
        )

    def __repr__(self) -> str:
        return f"Package({self._func.__name__}, args={self._args}, kwargs={self._kwargs})"


# Short alias
Pack = Package
