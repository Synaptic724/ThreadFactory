"""
ThreadFactory
High-performance concurrent collections and parallel operations for Python 3.13+.
"""

import sys
import warnings

# 🚫 Exit if Python version is less than 3.13
if sys.version_info < (3, 13):
    sys.exit("ThreadFactory requires Python 3.13 or higher.")

# ✅ Exit with warning if Python version is less than 3.13 (soft requirement)
if sys.version_info < (3, 13):
    warnings.warn(
        f"ThreadFactory is optimized for Python 3.13+ (no-GIL). "
        f"You are running Python {sys.version_info.major}.{sys.version_info.minor}.",
        UserWarning
    )

try:
    from importlib.metadata import version as get_version
    __version__ = get_version("ThreadFactory")
except Exception:
    __version__ = "1.0.0-dev"


def _detect_nogil_mode() -> None:
    """
    Warn if we're not on a Python 3.13+ no-GIL build.
    This is a heuristic: there's no guaranteed official way to detect no-GIL.
    """
    if sys.version_info < (3, 13):
        warnings.warn(
            "ThreadFactory is designed for Python 3.13+. "
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

<<<<<<<< HEAD:src/ThreadFactory/__init__.py
from .Threading.Bag import ConcurrentBag
from .Threading.Dict import ConcurrentDict
from .Threading.List import ConcurrentList
from .Threading.Queue import ConcurrentQueue
from .Threading.Stack import ConcurrentStack
from .Threading.Concurrent import Concurrent
from .utils.exceptions import Empty
========
from src.ThreadFactory.Threading.Bag import ConcurrentBag
from src.ThreadFactory.Threading.Dict import ConcurrentDict
from src.ThreadFactory.Threading.List import ConcurrentList
from src.ThreadFactory.Threading.Queue import ConcurrentQueue
from src.ThreadFactory.Threading.Stack import ConcurrentStack
from src.ThreadFactory.Threading.Concurrent import Concurrent
>>>>>>>> 65d817d (refactor: update import paths and rename Threading to ThreadFactory):__init__.py

__all__ = [
    "ConcurrentBag",
    "ConcurrentDict",
    "ConcurrentList",
    "ConcurrentQueue",
    "Concurrent",
    "ConcurrentStack",
    "Empty",
    "__version__"
]