from typing import Callable, Any
from thread_factory import ConcurrentDict
from thread_factory.agent.activity.job import JobActivity
from thread_factory.utils.coordination.package import Pack
from thread_factory.utils.interfaces.disposable import IDisposable


class ActivityBuilder(IDisposable):
    """
    Profile registry and builder for behavior injection. Now includes a profile
    for the concrete JobActivity class.
    """
    __slots__ = IDisposable.__slots__ + ["_registry", "_registered"]

    def __init__(self):
        """Initialize a fresh profile builder with built-in defaults."""
        super().__init__()
        self._registry: ConcurrentDict[str, Callable[[Any], None]] = ConcurrentDict()
        self._registered = False
        self._register_defaults()

    def dispose(self) -> None:
        """Dispose of the activity builder, clearing the registry."""
        if self._disposed:
            return
        if self._registry:
            self._registry.dispose()
            self._registry = None
        self._registered = False

    def _register_defaults(self) -> None:
        """Internal helper to register built-in profiles. Only runs once."""
        if self._registered:
            return
        # This profile is now deprecated in favor of the more specific one.
        # self.register_profile("cancellation", self._cancellation_profile)
        self.register_profile("job_cancellation", self._job_cancellation_profile)
        self._registered = True

    def register_profile(self, name: str, fn: Callable[[Any], None]) -> None:
        """
        Register a new profile builder function.
        Args:
            name (str): The profile name.
            fn (Callable): A function that wires up activity behavior.
        """
        if fn:
            fn = Pack.bundle(fn)
        self._registry[name] = fn

    def apply_profile(self, name: str, activity: Any) -> None:
        """
        Apply a registered profile to a given activity.
        Args:
            name (str): The profile to apply.
            activity (Any): The target activity instance.
        """
        fn = self._registry.get(name)
        if fn:
            fn(activity)

    def _job_cancellation_profile(self, activity: JobActivity) -> None:
        """
        A profile specifically for JobActivity that wires up its cancel method.
        Note: This is now redundant since the cancel logic is built into the
        JobActivity itself, but is kept to show how a builder would configure
        a concrete activity. In a real system, a profile might add more
        complex behaviors or metadata.
        """
        # In this improved design, the JobActivity already has a `cancel` method.
        # A builder's role would be to *configure* it or add *additional* callbacks.
        # For this example, we'll just log that the profile was applied.
        activity._logger.info(f"Job cancellation profile applied to '{activity.id}'.")
