import threading
from enum import Enum, auto

class TaskState(Enum):
    """
    Enum representing the states of a task during its lifecycle.
    This will help manage and track the work's status.
    """
    PENDING = auto()       # Work is pending and hasn't started yet.
    IN_PROGRESS = auto()   # Work is currently being executed.
    COMPLETED = auto()     # Work has been completed successfully.
    FAILED = auto()        # Work has failed to complete successfully.
    CANCELLED = auto()     # Work has been cancelled before completion.


class WorkState:
    """
    A thread-safe state object representing the current state of a task or unit of work.
    This object is used to track and manage the lifecycle of a task being executed in the system.
    """

    def __init__(self, task_id: str):
        """
        Initializes the WorkState object.

        Args:
            task_id (str): Unique identifier for the task. Used to track the work.
        """
        self.task_id = task_id
        self._state = TaskState.PENDING  # Initial state is pending
        self._lock = threading.RLock()

    def set_state(self, new_state: TaskState):
        """
        Set a new state for the task. Ensures thread-safe state changes.

        Args:
            new_state (TaskState): The new state of the task.
        """
        with self._lock:
            self._state = new_state
            print(f"Task {self.task_id} state updated to: {self._state.name}")

    def get_state(self) -> TaskState:
        """
        Get the current state of the task.

        Returns:
            TaskState: The current state of the task.
        """
        with self._lock:
            return self._state

    def is_state(self, state: TaskState) -> bool:
        """
        Check if the task is in the specified state.

        Args:
            state (TaskState): The state to check against.

        Returns:
            bool: True if the task is in the specified state, False otherwise.
        """
        with self._lock:
            return self._state == state

    def mark_in_progress(self):
        """
        Mark the task as being in progress.
        """
        self.set_state(TaskState.IN_PROGRESS)

    def mark_completed(self):
        """
        Mark the task as completed.
        """
        self.set_state(TaskState.COMPLETED)

    def mark_failed(self):
        """
        Mark the task as failed.
        """
        self.set_state(TaskState.FAILED)

    def mark_cancelled(self):
        """
        Mark the task as cancelled.
        """
        self.set_state(TaskState.CANCELLED)

    def reset(self):
        """
        Reset the task's state back to PENDING.
        """
        with self._lock:
            self._state = TaskState.PENDING
            print(f"Task {self.task_id} reset to PENDING.")

    def __repr__(self):
        """
        String representation of the task's state for debugging/logging purposes.
        """
        return f"<WorkState task_id={self.task_id}, state={self._state.name}>"
