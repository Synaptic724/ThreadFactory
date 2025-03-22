# __init__.py
import sys
import warnings

# Try to check Python version and build to see if it looks like no-GIL
def _detect_nogil_mode() -> None:
    """
    Warn if we're not on a Python 3.13+ no-GIL build.
    This is a heuristic: there's no guaranteed official way to detect no-GIL.
    """
    if sys.version_info < (3, 13):
        warnings.warn(
            "AtomicThreading is designed for Python 3.13+. "
            f"You are running Python {sys.version_info.major}.{sys.version_info.minor}.",
            UserWarning
        )
        return
    try:
        GIL_ENABLED = sys._is_gil_enabled()
    except AttributeError:
        GIL_ENABLED = True

    if not GIL_ENABLED:
        # We can't be absolutely certain, but let's warn anyway:
        warnings.warn(
            "You are using a version of python that allows for no-GIL mode. "
            "However you are not running in no-GIL mode. This package is designed for no-GIL mode.",
            UserWarning
        )

_detect_nogil_mode()

# Now import the classes you want to expose at package level
from Threading.Bag import ConcurrentBag
from Threading.Dict import ConcurrentDict
from Threading.List import ConcurrentList
from Threading.Queue import ConcurrentQueue
from Threading.Stack import ConcurrentStack
from Threading.Parallel import Parallel

__all__ = [
    "ConcurrentBag",
    "ConcurrentDict",
    "ConcurrentList",
    "ConcurrentQueue",
    "Parallel",
    "ConcurrentStack"
]
