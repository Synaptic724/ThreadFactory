"""
factory
High-performance concurrency collections and parallel operations for Python 3.13+.
"""
DEBUG_MODE = True
import sys
import warnings
from thread_factory.__version__ import __version__ as version
from thread_factory.__author__ import __author__ as author

# 🚫 Exit if Python version is less than 3.13
if sys.version_info < (3, 13):
    sys.exit("factory requires Python 3.13 or higher.")

# ✅ Exit with warning if Python version is less than 3.13 (soft requirement)
if sys.version_info < (3, 13):
    warnings.warn(
        f"factory is optimized for Python 3.13+ (no-GIL). "
        f"You are running Python {sys.version_info.major}.{sys.version_info.minor}.",
        UserWarning
    )

if DEBUG_MODE:
    version += "-dev"
__version__ = version

# Import Concurrency Collections
from thread_factory.concurrency.concurrent_buffer import ConcurrentBuffer
from thread_factory.concurrency.concurrent_bag import ConcurrentBag
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.concurrency.concurrent_queue import ConcurrentQueue
from thread_factory.concurrency.concurrent_set import ConcurrentSet
from thread_factory.concurrency.concurrent_stack import ConcurrentStack
from thread_factory.concurrency.concurrent_collection import ConcurrentCollection

# ---- Utilities ----
from thread_factory.utils.exceptions.empty import Empty
from thread_factory.utils.timing_tools.auto_reset_timer import AutoResetTimer
from thread_factory.utils.timing_tools.stopwatch import Stopwatch
from thread_factory.utils.concurrent_tools.concurrent_tools import ConcurrentTools

from thread_factory.synchronization.primitives import (
    Dynaphore,
    SmartCondition,
    FlowRegulator,
    TransitCondition,
)
# ---- Runtime Primitives ----
from thread_factory.synchronization.primitives import __all__ as primatives_all

__all__ = primatives_all + [
    # Concurrency Collections
    "ConcurrentBuffer",
    "ConcurrentBag",
    "ConcurrentDict",
    "ConcurrentList",
    "ConcurrentQueue",
    "ConcurrentSet",
    "ConcurrentStack",
    "ConcurrentCollection",
    # Utilities
    "ConcurrentTools",
    "Empty",
    "Stopwatch",
    "AutoResetTimer",
    "__version__",
    "__author__",
]

def _detect_nogil_mode() -> None:
    """
    Warn if we're not on a Python 3.13+ no-GIL build.
    This is a heuristic: there's no guaranteed official way to detect no-GIL.
    """
    if sys.version_info < (3, 13):
        warnings.warn(
            "factory is designed for Python 3.13+. "
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
