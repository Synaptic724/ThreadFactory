"""
AtomicThreading
===============

A No-GIL concurrency framework for Python 3.13+.
"""

from Parallel.parallel import parallel_for, parallel_foreach, parallel_invoke
from Concurrent.concurrent_dict import ConcurrentDictionary
from Concurrent.concurrent_queue import ConcurrentQueue
from Concurrent.concurrent_bag import ConcurrentBag
from Concurrent.concurrent_list import ConcurrentList

__all__ = [
    "parallel_for",
    "parallel_foreach",
    "parallel_invoke",
    "ConcurrentDictionary",
    "ConcurrentQueue",
    "ConcurrentBag",
    "CancellationToken",
    "TaskCompletionSource"
]