"""
factory
High-performance concurrency collections and parallel operations for Python 3.13+.
"""
DEBUG_MODE = True
import sys
import warnings
from thread_factory.__version__ import __version__ as version

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

# ---- Core Concurrency Primitives ----
from thread_factory.concurrency import __all__ as concurrency_all
# ---- Utilities ----
from thread_factory.utils import Empty, Stopwatch, AutoResetTimer

# ---- Runtime Primitives ----
from thread_factory.primatives import __all__ as primatives_all

# ---- Operations ----
from thread_factory.runtime.factory.operations import (
    Work # this will be implemented in the future
)

__all__ = primatives_all + concurrency_all + [
    "__version__"
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
