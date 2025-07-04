import threading
from typing import Callable, Union, List, Type, Set
from thread_factory.agent import ActivatedAgent
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.utils.coordination.package import Pack
from thread_factory.utils.interfaces.disposable import IDisposable
from thread_factory.agent.identity.profiles.general import General  # Your default Profile class
from thread_factory.agent.identity.profiles.base import BaseProfile  # Your default Profile class
from thread_factory.utils.interfaces.iprofile import IProfile



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
        self._collision_check = set()
        self._create_colision_checker()
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

        self.register_profile("default", lambda: General())
        self._registered = True

    def register_profile(self, name: str, fn: Callable[[], IProfile]) -> None:
        """
        Register a profile constructor under a symbolic name.

        Args:
            name (str): Profile name (e.g. 'scout', 'guardian').
            fn (Callable): Callable that returns a fresh General instance.

        Raises:
            ValueError: If name is empty or function is not callable.
        """
        if not name or not callable(fn):
            raise ValueError("Profile name must be a non-empty string and fn must be callable.")
        if name not in self._registry:
            self._check_for_collision(fn)
        else:
            raise ValueError(f"Profile '{name}' is already registered.")
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

    def get_profile(self, name: str) -> IProfile:
        """
        Returns a fresh profile instance based on the registered factory.

        Args:
            name (str): Profile name.

        Returns:
            IProfile: A newly created profile instance.

        Raises:
            KeyError: If the profile is not registered.
        """
        fn = self._registry.get(name)
        if not fn:
            raise KeyError(f"No profile registered under '{name}'")
        profile = fn()
        if not isinstance(profile, IProfile):
            raise TypeError(f"Profile '{name}' did not return an IProfile instance.")
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

    def _check_for_collision(self, fn: Callable[[], IProfile]) -> None:
        """
        Verifies that the class returned by the factory does not expose any
        public methods or attributes that conflict with reserved names.

        Args:
            fn (Callable[[], IProfile]): Profile constructor.

        Raises:
            ValueError: If any method or attribute name collides.
        """
        try:
            profile_class = fn().__class__
        except Exception as e:
            raise ValueError(f"Unable to instantiate profile for collision check: {e}")

        class_members = ProfileBuilder.get_public_class_members(profile_class)
        conflicts = class_members.intersection(self._collision_check)

        if conflicts:
            raise ValueError(
                f"Profile '{profile_class.__name__}' has name collisions with reserved agent attributes: "
                f"{', '.join(sorted(conflicts))}"
            )

    def _create_colision_checker(self) -> None:
        """
        Initializes a collision checker to ensure unique profile names.
        """
        thread_class_data = ProfileBuilder.get_public_class_members(threading.Thread)
        activator_class_data = ProfileBuilder.get_public_class_members(ActivatedAgent)
        base_profile_class_data = ProfileBuilder.get_public_class_members(BaseProfile)
        self._collision_check = thread_class_data.union(activator_class_data).union(base_profile_class_data)

    @staticmethod
    def get_public_class_members(cls: Type) -> Set[str]:
        """
        Scans a given class reference to pull out the names of its public
        (non-dunder) fields and methods.

        Args:
            cls (Type): The class object to inspect.

        Returns:
            Set[str]: A sorted list of public member names.
        """
        public_members = set()

        # Inspect the provided class
        for name in dir(cls):
            # Filter out dunder methods unless they are explicitly considered public interfaces
            # (like __call__, __repr__, __str__).
            if not name.startswith('__') or \
               (name.startswith('__') and name.endswith('__') and name in ['__call__', '__repr__', '__str__']):
                public_members.add(name)

        return public_members
