"""
thread_factory
High-performance concurrency collections and parallel operations for Python 3.13+.
"""

import sys
import warnings

# 🚫 Exit if Python version is less than 3.13
if sys.version_info < (3, 13):
    sys.exit("thread_factory requires Python 3.13 or higher.")

# ✅ Exit with warning if Python version is less than 3.13 (soft requirement)
if sys.version_info < (3, 13):
    warnings.warn(
        f"thread_factory is optimized for Python 3.13+ (no-GIL). "
        f"You are running Python {sys.version_info.major}.{sys.version_info.minor}.",
        UserWarning
    )

try:
    from importlib.metadata import version as get_version
    __version__ = get_version("thread_factory")
except Exception:
    __version__ = "1.0.2-dev"


def _detect_nogil_mode() -> None:
    """
    Warn if we're not on a Python 3.13+ no-GIL build.
    This is a heuristic: there's no guaranteed official way to detect no-GIL.
    """
    if sys.version_info < (3, 13):
        warnings.warn(
            "thread_factory is designed for Python 3.13+. "
            f"You are running Python {sys.version_info.major}.{sys.version_info.minor}.",
            UserWarning
        )
        return
    try:
        GIL_ENABLED = sys._is_gil_enabled()
    except AttributeError:
        GIL_ENABLED = True

    if GIL_ENABLED:
        warnings.warn(
            "You are using a Python version that allows no-GIL mode, "
            "but are not running in no-GIL mode. "
            "This package is designed for optimal performance with no-GIL.",
            UserWarning
        )

_detect_nogil_mode()

from src.thread_factory.concurrency.concurrent_bag import ConcurrentBag
from src.thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from src.thread_factory.concurrency.concurrent_list import ConcurrentList
from src.thread_factory.concurrency.concurrent_queue import ConcurrentQueue
from src.thread_factory.concurrency.concurrent_stack import ConcurrentStack
from src.thread_factory.concurrency.concurrent_core import Concurrent
from src.thread_factory.utils.exceptions import Empty
from src.thread_factory.threads import Worker, Dynaphore

__all__ = [
    "ConcurrentBag",
    "ConcurrentDict",
    "ConcurrentList",
    "ConcurrentQueue",
    "Concurrent",
    "ConcurrentStack",
    "Empty",
    "Worker",
    "Dynaphore",
    "__version__"
]