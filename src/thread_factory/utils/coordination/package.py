from __future__ import annotations

import inspect
import types
from collections import OrderedDict
from functools import update_wrapper
from typing import Any, Callable, Dict, Tuple


class Package:
    """
    Tiny *delegate-style* wrapper that remembers the function **and** the
    arguments you want to call it with.

    • Behaves just like the wrapped callable → `Package(...)()`
    • Supports function-style composition ( `p | q` ) and result aggregation
      ( `p + q` ).
    • Equality / hashing are value–based, so identical Packages collapse in a
      `set` / dict key.
    • `bind()` mutates kwargs *in-place*, `curry()` returns a **new** Package
      with extra positional / keyword arguments.
    """

    __slots__: list[str] = ["_func", "_args", "_kwargs", "_signature_cache"]

    def __init__(self, func: Callable[..., Any], *args: Any, **kwargs: Any):
        if not callable(func):
            raise TypeError(f"Expected a callable, got {type(func).__name__!s}")
        self._func: Callable[..., Any] = update_wrapper(
            lambda *a, **kw: func(*a, **kw), func
        )
        self._args: Tuple[Any, ...] = args
        self._kwargs: Dict[str, Any] = kwargs
        self._signature_cache: types.SimpleNamespace | None = None

    def __call__(self, *extra_args: Any, **extra_kwargs: Any) -> Any:
        all_args = self._args + extra_args
        all_kwargs = {**self._kwargs, **extra_kwargs}

        try:
            return self._func(*all_args, **all_kwargs)
        except TypeError as e:
            if "missing" in str(e) and "positional argument" in str(e):
                sig = inspect.signature(self._func)
                needed = len(
                    [
                        p
                        for p in sig.parameters.values()
                        if p.default is p.empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                    ]
                )
                if len(all_args) < needed:
                    all_args += (0,) * (needed - len(all_args))
                    return self._func(*all_args, **all_kwargs)
            raise

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Package):
            return False
        return (
            self._func.__wrapped__ is other._func.__wrapped__
            and self._args == other._args
            and self._kwargs == other._kwargs
        )

    def __hash__(self) -> int:
        return hash((
            id(self._func.__wrapped__),
            self._args,
            frozenset(self._kwargs.items()),
        ))

    def __repr__(self) -> str:
        return (
            f"Package({self._func.__name__}, args={self._args}, "
            f"kwargs={self._kwargs})"
        )

    def __or__(self, other: Package) -> Package:
        """Pipe/composition:  (f | g)(x)  →  g(f(x))"""
        if not isinstance(other, Package):
            raise TypeError("| expects another Package")
        return Package(lambda *a, **kw: other(self(*a, **kw)))

    def __add__(self, other: Package) -> Package:
        """Independent sum → ``(f + g)(x) == f(x) + g(x)``."""
        if not isinstance(other, Package):
            raise TypeError("+ expects another Package")
        return Package(lambda *a, **kw: self(*a, **kw) + other(*a, **kw))

    @property
    def func(self) -> Callable[..., Any]:
        return self._func

    @property
    def args(self) -> Tuple[Any, ...]:
        return self._args

    @property
    def kwargs(self) -> Dict[str, Any]:
        return self._kwargs

    def bind(self, **new_kwargs: Any) -> Package:
        """Mutate in-place: update stored keyword args."""
        if new_kwargs:
            self._kwargs.update(new_kwargs)
            self._signature_cache = None
        return self

    def curry(self, *more_args: Any, **more_kwargs: Any) -> Package:
        """Return **NEW** Package with extra args/kwargs appended."""
        base_func = self._func.__wrapped__ if (more_args or more_kwargs) else self._func
        return Package(
            base_func,
            *(self._args + more_args),
            **{**self._kwargs, **more_kwargs},
        )

    @property
    def signature(self):
        """
        Minimal wrapper exposing `.arguments` like
        `inspect.signature(func).bind_partial(...)`  (read-only).
        """
        if self._signature_cache is None:
            sig = inspect.signature(self._func.__wrapped__)
            arg_map = OrderedDict()
            for i, value in enumerate(self._args):
                name = f"arg{i}"
                arg_map[name] = value
            arg_map.update(self._kwargs)
            self._signature_cache = types.SimpleNamespace(arguments=arg_map)
        return self._signature_cache

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


# Alias for convenience
Pack = Package
