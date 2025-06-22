import datetime
from dataclasses import dataclass
from enum import auto, Enum
import ulid
from thread_factory.concurrency import ConcurrentList


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
    timestamp_execution_time: datetime.datetime = None
    timestamp_completion_time: datetime.datetime = None

    def __repr__(self):
        return f"<Record task_id={self.task_id} timestamp={self.timestamp_completion_time}>"


class Records:
    """
    Tracks ULID records of completed work.

    This object is intended to store history of executed tasks for audit/logging.
    """

    def __init__(self):
        self.records: ConcurrentList[Record] = ConcurrentList()

    def add(self, record: Record):
        """Appends a ULID for a completed task."""
        self.records.append(record)

    def __repr__(self):
        return f"<Records count={len(self.records)}>"

    def __len__(self):
        return len(self.records)