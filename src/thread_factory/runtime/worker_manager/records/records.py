import datetime
from enum import auto, Enum
import ulid


class Record:
    """
    Represents a single ULID record of completed work.

    This object is intended to store history of executed tasks for audit/logging.
    """

    class WorkStatus(Enum):
        """
        Enum describing the type or lifecycle state of a Work item.

        This combines both 'what the task is' and 'what stage it's in',
        similar to `concurrent.futures.Future._state`.
        """
        # Lifecycle states (for execution tracking)
        PENDING = auto()
        RUNNING = auto()
        COMPLETED = auto()
        CANCELLED = auto()
        FAILED = auto()

    def __init__(self, task_id: ulid.ULID, work_status: WorkStatus):
        self.task_id = task_id
        self.timestamp = datetime.datetime.now()
        self.status = work_status

    def __repr__(self):
        return f"<Record task_id={self.task_id} timestamp={self.timestamp}>"


class Records:
    """
    Tracks ULID records of completed work.

    This object is intended to store history of executed tasks for audit/logging.
    """

    def __init__(self):
        self.records: list[Record] = []

    def add(self, record: Record):
        """Appends a ULID for a completed task."""
        self.records.append(record)

    def __repr__(self):
        return f"<Records count={len(self.records)}>"

    def __len__(self):
        return len(self.records)