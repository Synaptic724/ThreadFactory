import datetime
from enum import auto, Enum
import ulid


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


class Record:
    """
    Represents a single ULID record of completed work.

    This object is intended to store history of executed tasks for audit/logging.
    """
    def __init__(self, task_id: ulid.ULID, work_status: WorkStatus, creation_time: datetime.datetime,
                 execution_time: datetime.datetime, completion_time: datetime.datetime):

        self.task_id = task_id
        self.timestamp_creation_time =  creation_time
        self.timestamp_execution_time =  execution_time
        self.timestamp_completion_time =  completion_time
        self.status = work_status

    def __repr__(self):
        return f"<Record task_id={self.task_id} timestamp={self.timestamp_completion_time}>"


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