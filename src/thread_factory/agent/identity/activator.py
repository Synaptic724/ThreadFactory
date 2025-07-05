import threading
from typing import Any, List
from thread_factory.utils.interfaces.disposable import IDisposable


class AgentActivator(IDisposable):
    """
    AgentActivator
    ----------------
    Dynamically upgrades an object (usually a thread) by patching it with
    methods and attributes provided by a profile. Unpatches cleanly on disposal.

    This enables agentic behavior to be dynamically added to standard objects
    like threads, allowing them to access custom profile methods, attributes,
    and behavior mappings at runtime.
    """

    def __init__(self, profile: Any, target: threading.Thread):
        """
        Initialize an AgentActivator by injecting profile functionality into a target.

        Args:
            profile (Any): A class or callable that returns a profile instance.
                           The profile may implement `dispose()`.
            target (Any): The object to upgrade (e.g., a thread instance).
        """
        super().__init__()
        self._lock = threading.RLock()
        self._target: threading.Thread = target
        self._profile = profile
        self._patched_fields: List[str] = []

    def dispose(self):
        """
        Reverses all patches and disposes the profile if needed.

        This method is idempotent and ensures that the target object is
        returned to its original state by removing dynamically added fields.
        """
        if self._disposed:
            return
        with self._lock:
            if self._profile and hasattr(self._profile, "dispose"):
                try:
                    self._profile.dispose()
                except Exception:
                    pass
            self._profile = None
            self._unpatch()
            self._target = None
            self._patched_fields.clear()
            self._disposed = True

    @staticmethod
    def is_agent(thread: threading.Thread) -> bool:
        """
        Checks if a thread has already been activated as an agent.

        Args:
            thread (threading.Thread): The thread to check.

        Returns:
            bool: True if the thread is an agent, False otherwise.
        """
        return getattr(thread, '_worker_type', None) == 'agentic'

    def _patch(self):
        """
        Automatically patches public methods and fields from the profile
        into the target object.
        """
        for attr_name in dir(self._profile):
            if attr_name.startswith("_"):
                continue
            if hasattr(self._target, attr_name):
                continue

            attr = getattr(self._profile, attr_name)
            setattr(self._target, attr_name, attr)
            self._patched_fields.append(attr_name)

        setattr(self._target, "profile", self._profile)
        self._patched_fields.append("profile")

    def _unpatch(self):
        """
        Removes all attributes that were dynamically patched onto the target.
        """
        for name in self._patched_fields:
            if hasattr(self._target, name):
                try:
                    delattr(self._target, name)
                except AttributeError:
                    pass

    def __call__(self) -> "AgentActivator":
        return self

    def run(self) -> Any:
        """
        Executes the wrapped target’s `run()` method if it has one.

        Returns:
            Any: Result from the target’s `run()` method.

        Raises:
            RuntimeError: If the agent is disposed or the target is invalid.
        """
        if self._disposed or self._target is None:
            raise RuntimeError("Agent is disposed or invalid.")
        return self._target.run()
