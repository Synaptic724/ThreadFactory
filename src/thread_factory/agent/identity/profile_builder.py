from typing import Callable, Union, List
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.utils.coordination.package import Pack
from thread_factory.utils.interfaces.disposable import IDisposable
from thread_factory.agent.identity.profiles.general import General  # Your default Profile class

class ProfileBuilder(IDisposable):
    """
    ProfileBuilder
    ----------------
    A manifest builder for agent identity and execution context.

    Provides a flexible registry for managing identity profiles that
    define values such as name, job, group, and routing maps.

    This builder allows users to:
        - Register their own profile templates
        - Remove profiles
        - List available profiles
        - Create a configured General profile using any named template
        - Bind and unbind profiles to agents
    """

    __slots__ = IDisposable.__slots__ + ["_registry", "_registered"]

    def __init__(self):
        """
        Initializes a fresh profile builder and registers the default profile template.
        """
        super().__init__()
        self._registry: ConcurrentDict[str, Union[Callable[..., None], Pack]] = ConcurrentDict()
        self._registered = False
        self._register_defaults()

    def dispose(self) -> None:
        """
        Disposes the builder and clears all registered profiles.
        """
        if self._disposed:
            return
        self._registry.dispose()
        self._registry = None
        self._registered = False

    def _register_defaults(self) -> None:
        """
        Registers the symbolic 'default' profile.
        Users can override it later if desired.
        """
        if self._registered:
            return

        def default_profile(profile: General):
            profile.name = "UnnamedAgent"
            profile.job = "generic"
            profile.group = "default"
            profile.data_transfer.clear()
            profile.save_points.clear()
            profile.locations.clear()

        self.register_profile("default", default_profile)
        self._registered = True

    def register_profile(self, name: str, fn: Callable[[General], None]) -> None:
        """
        Register a profile initializer under a symbolic name.

        Args:
            name (str): Profile name (e.g. 'scout', 'guardian').
            fn (Callable): Callable that configures a General profile.

        Raises:
            ValueError: If name is empty or function is not callable.
        """
        if not name or not callable(fn):
            raise ValueError("Profile name must be a non-empty string and fn must be callable.")
        self._registry[name] = Pack.bundle(fn)

    def unregister_profile(self, name: str) -> bool:
        """
        Remove a registered profile by name.

        Returns:
            bool: True if the profile was removed, False if not found.
        """
        return self._registry.pop(name, None) is not None

    def list_profiles(self) -> List[str]:
        """
        Return all registered profile names.
        """
        return list(self._registry.keys())

    def has_profile(self, name: str) -> bool:
        """
        Check if a given profile name is registered.
        """
        return name in self._registry

    def apply_profile(self, name: str, profile: General) -> None:
        """
        Apply a registered profile to a General object.

        Raises:
            KeyError: If the profile is not registered.
        """
        fn = self._registry.get(name)
        if not fn:
            raise KeyError(f"No profile registered under '{name}'")
        fn(profile)

    def apply_defaults(self, profile: General) -> None:
        """
        Apply the symbolic 'default' profile.
        """
        self.apply_profile("default", profile)

    def create_profile(self, profile_type: str = "default") -> General:
        """
        Create a new General profile and apply the selected type.

        Returns:
            General: A fully configured profile.
        """
        profile = General()
        self.apply_profile(profile_type, profile)
        return profile

    def attach_profile(self, profile: General, target: Union["ActivatedAgent", "Agent"]) -> None:
        """
        Bind a profile to an agent.

        Raises:
            TypeError or RuntimeError if invalid or already bound.
        """
        profile.bind_to(target)

    def detach_profile(self, profile: General) -> None:
        """
        Unbind a profile from any agent.
        """
        profile.unbind()
