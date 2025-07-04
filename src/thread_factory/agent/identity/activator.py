import threading
from typing import Any, Dict, List
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
                           The profile must implement `unpatch_thread(obj)` and optionally `dispose()`.
            target (Any): The object to upgrade (e.g., a thread instance).
        """
        super().__init__()
        self._lock = threading.RLock()
        self._target: threading.Thread = target  # The object being patched
        self._profile = profile  # Create profile instance
        self._patched_fields: List[str] = []  # Track what we add so we can clean it later

    def dispose(self):
        """
        Reverses all patches and disposes the profile if needed.

        This method is idempotent and ensures that the target object is
        returned to its original state by removing dynamically added fields.
        """
        if self._disposed:
            return
        with self._lock:
            if self._profile:
                self._profile.unpatch_thread(self._target)  # Profile-level cleanup
                self._profile.dispose()
                self._profile = None
            self._unpatch()
            self._target = None
            self._patched_fields.clear()
            self._disposed = True

    def _patch(self):
        """
        Automatically patches public methods and fields from the profile
        into the target object.

        This method skips private/dunder attributes and avoids overriding
        any pre-existing attributes on the target. All patched field names
        are recorded for safe removal during unpatching.
        """
        for attr_name in dir(self._profile):
            if attr_name.startswith("_"):
                continue  # Skip private or dunder methods/fields
            if hasattr(self._target, attr_name):
                continue  # Avoid overwriting existing attributes

            attr = getattr(self._profile, attr_name)
            setattr(self._target, attr_name, attr)
            self._patched_fields.append(attr_name)

        # Always patch 'profile' so the target can access its identity context
        setattr(self._target, "profile", self._profile)
        self._patched_fields.append("profile")

    def _unpatch(self):
        """
        Removes all attributes that were dynamically patched onto the target.

        Any AttributeError during removal is safely ignored to allow robust cleanup.
        """
        for name in self._patched_fields:
            if hasattr(self._target, name):
                try:
                    delattr(self._target, name)
                except AttributeError:
                    pass  # Already gone or wasn't allowed to be removed

    def __call__(self) -> "AgentActivator":
        """
        Allows the agent to be called like a function and return itself.

        This enables compatibility with factory or decorator patterns.
        """
        return self

    def run(self) -> Any:
        """
        Executes the wrapped target’s `run()` method if it has one.

        This allows direct access to the target’s run logic, which is
        especially useful for synchronous execution during testing.

        Returns:
            Any: Result from the target’s `run()` method.

        Raises:
            RuntimeError: If the agent is disposed or the target is invalid.
        """
        if self._disposed or self._target is None:
            raise RuntimeError("Agent is disposed or invalid.")
        return self._target.run()
