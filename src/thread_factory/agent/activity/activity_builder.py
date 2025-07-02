from typing import Callable, Dict
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.utils.interfaces.disposable import IDisposable


class ActivityBuilder(IDisposable):
    """
    Profile registry and builder for behavior injection.

    Each instance manages its own profile registry, allowing multiple builders
    in different contexts (e.g., per-thread or per-agent strategies).

    Built-in profiles:
        - "cancellation": Adds cancel flag, cancel() callback, and token access.
    """

    __slots__ = IDisposable.__slots__ + ["_registry", "_registered"]

    def __init__(self):
        """
        Initialize a fresh profile builder with built-in defaults.
        """
        super().__init__()
        self._registry: ConcurrentDict[str, Callable[["ActivityController"], None]] = ConcurrentDict()
        self._registered = False
        self._register_defaults()

    def dispose(self) -> None:
        """
        Dispose of the activity builder, clearing the registry.
        """
        if self._disposed:
            return
        self._registry.dispose()
        self._registry = None
        self._registered = False

    def _register_defaults(self) -> None:
        """
        Internal helper to register built-in profiles. Only runs once.
        """
        if self._registered:
            return
        self.register_profile("cancellation", self._cancellation_profile)
        self._registered = True

    def register_profile(self, name: str, fn: Callable[["ActivityController"], None]) -> None:
        """
        Register a new profile builder function.

        Args:
            name (str): The profile name.
            fn (Callable): A function that wires up controller+token behavior.
        """
        self._registry[name] = fn

    def apply_profile(self, name: str, controller: "ActivityController") -> None:
        """
        Apply a registered profile to a given controller.

        Args:
            name (str): The profile to apply.
            controller (ActivityController): The target controller.
        """
        fn = self._registry.get(name)
        if fn:
            fn(controller)

    def apply_defaults(self, controller: "ActivityController") -> None:
        """
        Apply all default built-in profiles.

        Args:
            controller (ActivityController): The controller to enhance.
        """
        self.apply_profile("cancellation", controller)

    def _cancellation_profile(self, controller: "ActivityController") -> None:
        """
        Injects cancellation capability into the controller and activity.

        Adds:
            • metadata["cancel_requested"] = False
            • controller.cancel() callback
            • token["cancel_requested"] lambda to reflect state
        """
        controller._metadata["cancel_requested"] = False

        def cancel() -> None:
            controller._metadata["cancel_requested"] = True

        controller.register_callback("cancel", cancel)
        controller.bind("cancel_requested", lambda: controller._metadata["cancel_requested"])
