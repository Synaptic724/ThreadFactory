"""
factory
High-performance concurrency collections and parallel operations for Python 3.13+.
"""
DEBUG_MODE = False
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

# Import Synchronization Value Types
from thread_factory.concurrency.sync_types.sync_int import SyncInt
from thread_factory.concurrency.sync_types.sync_float import SyncFloat
from thread_factory.concurrency.sync_types.sync_bool import SyncBool
from thread_factory.concurrency.sync_types.sync_string import SyncString
from thread_factory.concurrency.sync_types.sync_ref import SyncRef
# ---- Synchronization Classes ----
# Controllers
from thread_factory.synchronization.controllers.signal_controller import SignalController
# Coordinators
from thread_factory.synchronization.coordinators.clock_barrier import ClockBarrier
from thread_factory.synchronization.coordinators.conductor import Conductor
from thread_factory.synchronization.coordinators.multi_conductor import MultiConductor
from thread_factory.synchronization.coordinators.scout import Scout
from thread_factory.synchronization.coordinators.transit_barrier import TransitBarrier
# Dispatchers
from thread_factory.synchronization.dispatchers.fork import Fork
from thread_factory.synchronization.dispatchers.signal_fork import SignalFork
from thread_factory.synchronization.dispatchers.sync_fork import SyncFork
from thread_factory.synchronization.dispatchers.sync_signal_fork import SyncSignalFork
# Execution
from thread_factory.synchronization.execution.bypass_conductor import BypassConductor
# Primitives
from thread_factory.synchronization.primitives.flow_regulator import FlowRegulator
from thread_factory.synchronization.primitives.dynaphore import Dynaphore
from thread_factory.synchronization.primitives.latch import Latch
from thread_factory.synchronization.primitives.signal_barrier import SignalBarrier
from thread_factory.synchronization.primitives.signal_latch import SignalLatch
from thread_factory.synchronization.primitives.smart_condition import SmartCondition, Waiter
from thread_factory.synchronization.primitives.transit_condition import TransitCondition

# ---- Utilities ----
from thread_factory.utilities.exceptions.empty import Empty
from thread_factory.utilities.coordination.group import Group
from thread_factory.utilities.coordination.outcome import Outcome
from thread_factory.utilities.coordination.package import Pack, Package
from thread_factory.utilities.timing_tools.auto_reset_timer import AutoResetTimer
from thread_factory.utilities.timing_tools.stopwatch import Stopwatch
from thread_factory.utilities.concurrent_tools.concurrent_tools import ConcurrentTools

__all__ = [
    # Concurrency Collections
    "ConcurrentBuffer",
    "ConcurrentBag",
    "ConcurrentDict",
    "ConcurrentList",
    "ConcurrentQueue",
    "ConcurrentSet",
    "ConcurrentStack",
    "ConcurrentCollection",
    # Synchronization Value Types
    "SyncInt",
    "SyncFloat",
    "SyncBool",
    "SyncString",
    "SyncRef",
    # Synchronization Classes
    # Controllers
    "SignalController",
    # Coordinators
    "ClockBarrier",
    "Conductor",
    "MultiConductor",
    "Scout",
    "TransitBarrier",
    # Dispatchers
    "Fork",
    "SignalFork",
    "SyncFork",
    "SyncSignalFork",
    # Execution
    "BypassConductor",
    # Primitives
    "FlowRegulator",
    "Dynaphore",
    "Latch",
    "SignalBarrier",
    "SignalLatch",
    "SmartCondition",
    "Waiter",
    "TransitCondition",
    # Utilities
    "ConcurrentTools",
    "Group",
    "Outcome",
    "Pack",
    "Package",
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
