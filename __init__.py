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
            "AtomicThreading is designed for Python 3.13+ (ideally no-GIL). "
            f"You are running Python {sys.version_info.major}.{sys.version_info.minor}.",
            UserWarning
        )
        return

    # A rough check: many custom no-GIL builds include '-nogil' or 'nogil' in sys.version
    # or might be invoked with '-Xgil=0'
    version_str = sys.version.lower()
    if "nogil" not in version_str:
        # We can't be absolutely certain, but let's warn anyway:
        warnings.warn(
            "It doesn't look like you're running a no-GIL build of Python 3.13+. "
            "For best concurrency, compile a no-GIL build or run with `-Xgil=0` if available. "
            "Proceeding with standard GIL mode.",
            UserWarning
        )

_detect_nogil_mode()

# Now import the classes you want to expose at package level
from .Threading.Bag import ConcurrentBag
from .Threading.Dict import ConcurrentDict
from .Threading.List import ConcurrentList
from .Threading.Queue import ConcurrentQueue
from .Threading.Parallel import Parallel

__all__ = [
    "ConcurrentBag",
    "ConcurrentDict",
    "ConcurrentList",
    "ConcurrentQueue",
    "Parallel"
]
