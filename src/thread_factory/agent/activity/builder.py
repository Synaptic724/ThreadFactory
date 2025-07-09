from typing import Callable, Any, Type, Optional
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.agent.activity.base import BaseActivity
from thread_factory.agent.activity.job import JobActivity # Ensure this import is correct based on your structure
from thread_factory.utilities.interfaces.disposable import IDisposable

class ActivityBuilder(IDisposable):
    """
    A central registry and builder for creating instances of various controllable
    activity classes within the ThreadFactory framework.

    This class allows for the dynamic registration and instantiation of
    `BaseActivity` subclasses by a symbolic name, promoting a decoupled
    and extensible architecture. It manages a collection of registered activity
    types, enabling users to request the creation of a specific activity
    without directly importing and instantiating its class.

    It implements `IDisposable` to ensure proper cleanup of its internal registry.
    """
    __slots__ = IDisposable.__slots__ + ["_registry", "_registered"]

    def __init__(self):
        """
        Initializes a new instance of the ActivityBuilder.

        A fresh builder is created with an empty internal registry for activity
        classes. It then automatically registers any built-in default activity
        types (e.g., `JobActivity`) to make them readily available.
        """
        super().__init__()
        # Registry now stores activity classes (constructors)
        self._registry: ConcurrentDict[str, Type[BaseActivity]] = ConcurrentDict()
        self._registered = False
        self._register_defaults()

    def dispose(self) -> None:
        """
        Disposes of the ActivityBuilder, releasing its managed resources.

        This method implements the `IDisposable` contract. It ensures that
        the internal `_registry` (a `ConcurrentDict`) is properly disposed of,
        clearing any references to registered activity classes. It also resets
        the internal state of the builder.

        This operation is idempotent; calling it multiple times will have no
        further effect after the first call.
        """
        if self._disposed:
            return
        if self._registry:
            self._disposed = True  # Set disposed state before disposing resources
            # Dispose the ConcurrentDict to ensure its resources are also freed
            self._registry.dispose()
            # The _registry reference itself doesn't strictly need to be set to None
            # as it's already disposed and will be garbage collected when the builder is.
        self._registered = False

    def _register_defaults(self) -> None:
        """
        Internal helper method to register the default, built-in activity classes.

        This method is called during the `ActivityBuilder`'s initialization to
        populate its registry with commonly used activity types (e.g., `JobActivity`).
        It is designed to run only once to prevent redundant registrations.
        """
        if self._registered:
            return
        self.register_activity("job_activity", JobActivity)  # Register the class directly
        self._registered = True

    def register_activity(self, name: str, activity_class: Type[BaseActivity]) -> None:
        """
        Registers a new activity class (its constructor) under a given name.

        This allows the `build_activity` method to instantiate activities
        of this type by name.

        Args:
            name (str): The unique name or alias for this activity type.
            activity_class (Type[BaseActivity]): The concrete `BaseActivity` subclass
                                                 (its constructor) to register.
        Raises:
            TypeError: If the provided `activity_class` is not a subclass of BaseActivity.
        """
        if not issubclass(activity_class, BaseActivity):
            raise TypeError(f"Registered class '{activity_class.__name__}' must be a subclass of BaseActivity.")
        self._registry[name] = activity_class

    def unregister_activity(self, name: str) -> None:
        """
        Registers a new activity class (its constructor) under a given name.

        This allows the `build_activity` method to instantiate activities
        of this type by name.

        Args:
            name (str): The unique name or alias for this activity type.
            activity_class (Type[BaseActivity]): The concrete `BaseActivity` subclass
                                                 (its constructor) to register.
        Raises:
            TypeError: If the provided `activity_class` is not a subclass of BaseActivity.
        """
        if not isinstance(name, str):
            raise TypeError(f"Activity name must be a string, got {type(name).__name__}.")
        if name in self._registry:
            del self._registry[name]
        else:
            raise KeyError(f"No activity registered with name '{name}'.")


    def build_activity(self, name: str, **kwargs: Any) -> Optional[BaseActivity]:
        """
        Builds and returns a new activity instance based on a registered activity class.

        The `kwargs` provided to this method will be directly passed to the
        constructor of the registered activity class.

        Args:
            name (str): The name or alias of the activity type to build.
            **kwargs: Arbitrary keyword arguments to be passed to the
                      constructor of the activity class.

        Returns:
            Optional[BaseActivity]: An instantiated activity object if the
                                    `name` is registered; otherwise, `None`.
        Raises:
            TypeError: If the registered class cannot be instantiated with the
                       provided keyword arguments.
        """
        self._check_disposed()  # Ensure the builder is not disposed before proceeding
        activity_class = self._registry.get(name)
        if activity_class:
            try:
                # Instantiate the activity directly with provided kwargs
                return activity_class(**kwargs)
            except TypeError as e:
                raise TypeError(f"Failed to build activity '{name}'. "
                                f"Constructor of '{activity_class.__name__}' received invalid arguments: {e}")
        return None

    def list_activities(self) -> list[str]:
        """
        Returns a list of all registered activity names.

        This provides a snapshot of the currently available activity types
        that can be instantiated using the `build_activity` method.

        Returns:
            list[str]: A list of strings, where each string is the name of a registered activity.
        """
        self._check_disposed()
        return list(self._registry.keys())


    def _check_disposed(self):
        """
        Internal helper to raise a RuntimeError if the instance is disposed.
        """
        if self._disposed:
            raise RuntimeError(f"Activity Builder has been disposed.")