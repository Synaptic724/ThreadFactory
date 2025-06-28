import datetime
import threading
from dataclasses import dataclass
from enum import auto, Enum
import ulid

from thread_factory import ConcurrentDict
from thread_factory.concurrency import ConcurrentSet
from thread_factory.utils.interfaces.disposable import IDisposable


class WorkStatus(Enum):
    """
    Enum describing the type or lifecycle state of a Work item.

    This combines both 'what the task is' and 'what stage it's in',
    similar to `concurrent.futures.Future._state`.
    """
    # Lifecycle states (for execution tracking)
    PENDING = auto()
    IN_PROGRESS = auto()
    COMPLETED = auto()
    CANCELLED = auto()
    FAILED = auto()

@dataclass
class Record:
    """
    Represents a single ULID record of completed work.

    This object is intended to store history of executed tasks for audit/logging.
    """
    task_id: ulid.ULID
    status: WorkStatus
    timestamp_creation_time: datetime.datetime
    factory_id: ConcurrentSet[ulid.ULID] | ulid.ULID = None
    timestamp_execution_time: datetime.datetime = None
    timestamp_completion_time: datetime.datetime = None

    def __repr__(self):
        return f"<Record task_id={self.task_id} timestamp={self.timestamp_completion_time}>"

    def add_factory_id(self, factory_id: ulid.ULID):
        """
        Registers the factory ID of a thread that worked on this task.
        Promotes the field to a ConcurrentSet if needed.
        """
        if self.factory_id is None:
            self.factory_id = factory_id
            return

        if isinstance(self.factory_id, ConcurrentSet):
            self.factory_id.add(factory_id)
        elif isinstance(self.factory_id, ulid.ULID):
            if factory_id != self.factory_id:
                self.factory_id = ConcurrentSet([self.factory_id, factory_id])
        else:
            raise TypeError("factory_id must be a ULID or a ConcurrentSet of ULIDs")


class Records(IDisposable):
    """
    Tracks ULID records of completed work.

    This object is intended to store history of executed tasks for audit/logging.
    """

    def __init__(self):
        super().__init__()
        self._lock = threading.RLock()
        self.records: ConcurrentDict[ulid.ULID, Record] = ConcurrentDict()

    def dispose(self):
        """Cleans up the records."""
        if self._disposed:
            return
        with self._lock:
            if self._disposed:
                return
            self._disposed = True
            self.records.dispose()
            self.records = None

    def add(self, record: Record):
        """Appends a ULID for a completed task."""
        self.records[record.task_id] = record

    def __repr__(self):
        return f"<Records count={len(self.records)}>"

    def __len__(self):
        return len(self.records)