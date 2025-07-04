import ulid
from typing import Callable, Dict, Any, Optional
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.agent.activity.activity import Activity
from thread_factory.agent.activity.activity_builder import ActivityBuilder
from thread_factory.utils.interfaces.disposable import IDisposable


class ActivityController(IDisposable):
    """
    Central behavior controller for an agent, worker, or long-running operation.

    This controller manages:
        • A persistent `Activity` token shared with downstream consumers.
        • Live, mutable metadata describing the operation.
        • Action bindings injected into the activity for runtime control.
        • Named callbacks triggered by external systems (e.g., 'cancel').

    Profiles can be applied at creation to automatically wire common behaviors
    like cancellation. This is done using `ActivityBuilder`.

    Example:
        >>> controller = ActivityController(task="FetchJob")
        >>> controller.activity["cancel_requested"]  # Exposed via profile
        False
        >>> controller.run_callback("cancel")
        True
    """

    def __init__(self,
                 *,
                 task: Optional[str] = None,
                 job: Optional[str] = None,
                 group: Optional[str] = None,
                 use_default_profiles: bool = True,
                 **user_metadata: Any) -> None:
        """
        Creates a new controller and initializes its activity token and metadata.

        Args:
            task (str, optional): High-level operation name (e.g., "index_files").
            job (str, optional): Execution job identifier (e.g., batch_id).
            group (str, optional): Grouping key for worker sets.
            use_default_profiles (bool): Whether to apply default behavior profiles.
            **user_metadata: Arbitrary metadata added under a "user_metadata" key.
        """
        super().__init__()
        self._ulid = str(ulid.ULID())

        self._metadata = ConcurrentDict({
            "task": task,
            "job": job,
            "group": group,
            "user_metadata": ConcurrentDict(user_metadata)
        })

        self._actions   = ConcurrentDict[str, Any]()
        self._callbacks = ConcurrentDict[str, Callable[[], None]]()
        self._activity  = Activity(self._metadata)

        if use_default_profiles:
            ActivityBuilder().apply_defaults(self)

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    def dispose(self) -> None:
        """
        Disposes of all internal data structures and disconnects the activity.
        This controller is no longer usable after this call.
        """
        if self._disposed:
            return
        self._callbacks.dispose()
        self._actions.dispose()
        self._metadata.dispose()
        self._activity.dispose()
        self._callbacks = self._actions = self._metadata = self._activity = None  # type: ignore
        self._disposed = True

    # ─────────────────────────────────────────────────────────────────────────
    # Accessors
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def activity(self) -> Activity:
        """
        Returns:
            Activity: The shared activity token representing this controller's state.
        """
        return self._activity

    @property
    def metadata(self) -> Dict[str, Any]:
        """
        Returns:
            Dict[str, Any]: A shallow copy of all controller metadata.
        """
        return self._metadata.copy()

    @property
    def user_metadata(self) -> ConcurrentDict[str, Any]:
        """
        Returns:
            ConcurrentDict[str, Any]: Mutable metadata passed by user during creation.
        """
        return self._metadata["user_metadata"]

    @property
    def task(self) -> Optional[str]:
        """Gets or sets the high-level task identifier."""
        return self._metadata["task"]

    @task.setter
    def task(self, value: str) -> None:
        self._metadata["task"] = value

    @property
    def job(self) -> Optional[str]:
        """Gets or sets the job-level execution identifier."""
        return self._metadata["job"]

    @job.setter
    def job(self, value: str) -> None:
        self._metadata["job"] = value

    @property
    def group(self) -> Optional[str]:
        """Gets or sets the group this controller belongs to."""
        return self._metadata["group"]

    @group.setter
    def group(self, value: str) -> None:
        self._metadata["group"] = value

    # ─────────────────────────────────────────────────────────────────────────
    # Behavior Binding
    # ─────────────────────────────────────────────────────────────────────────

    def bind(self, name: str, value: Any) -> None:
        """
        Binds or updates a named *action* into the live action map.
        This becomes visible in the associated `Activity` token.

        Args:
            name (str): Action name (e.g., "cancel_requested").
            value (Any): Boolean, callable, or static value.
        """
        self._actions[name] = value
        self._activity.add_activity(name, value)

    def register_callback(self, name: str, callback: Callable[[], None]) -> None:
        """
        Registers a named callback function that can be triggered externally.

        Args:
            name (str): The identifier (e.g., 'cancel', 'pause').
            callback (Callable[[], None]): The function to call.
        """
        self._callbacks[name] = callback

    def run_callback(self, name: str) -> bool:
        """
        Triggers a named callback if it exists.

        Args:
            name (str): Name of the callback to trigger.

        Returns:
            bool: True if the callback was found and executed, False otherwise.
        """
        callback = self._callbacks.get(name)
        if callback:
            try:
                callback()
                return True
            except Exception:
                return False
        return False