from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.utils.interfaces.disposable import IDisposable
from typing import Optional, Callable, Union

class General(IDisposable):
    """
    General Profile
    ---------
    A lightweight container for agent identity and execution structure.

    This object may only be bound to an ActivatedAgent or Agent instance.
    """

    __slots__ = IDisposable.__slots__ + [
        "id", "name", "job", "group",
        "save_points", "locations", "data_transfer",
        "_bound_target"
    ]

    def __init__(self):
        """
        Initializes a blank profile with default field values.
        """
        super().__init__()
        self.id: Optional[str] = None
        self.name: Optional[str] = None
        self.job: Optional[str] = None
        self.group: Optional[str] = None

        self.save_points: ConcurrentDict[str, Union[Callable[..., None], "Pack"]] = ConcurrentDict()
        self.locations: ConcurrentDict[str, Union[Callable[..., None], "Pack"]] = ConcurrentDict()
        self.data_transfer: ConcurrentDict[str, Union[Callable[..., any], "Pack"]] = ConcurrentDict()

        self._bound_target: Optional[Union["ActivatedAgent", "Agent"]] = None

    def bind_to(self, obj: Union["ActivatedAgent", "Agent"]):
        """
        Bind this profile to a supported agent.

        Args:
            obj: An ActivatedAgent or Agent instance.

        Raises:
            TypeError: If object is not a valid agent type.
            RuntimeError: If the profile is already bound.
        """
        if self._bound_target is not None:
            raise RuntimeError("Profile is already bound to an agent.")

        from thread_factory.agent.identity.activator import ActivatedAgent
        from thread_factory.agent.thread_pool.agent import Agent

        if not isinstance(obj, (ActivatedAgent, Agent)):
            raise TypeError("Profile can only be bound to ActivatedAgent or Agent.")

        self._bound_target = obj

    def unbind(self):
        """
        Unbind the profile from its current agent.
        """
        self._bound_target = None

    @property
    def is_bound(self) -> bool:
        """
        Indicates whether this profile is bound to a valid agent.
        """
        return self._bound_target is not None

    def dispose(self):
        """
        Dispose of internal state and clear all references.
        """
        if self._disposed:
            return
        self.save_points.dispose()
        self.locations.dispose()
        self.data_transfer.dispose()

        self.id = None
        self.name = None
        self.job = None
        self.group = None
        self._bound_target = None
        self._disposed = True

    def __repr__(self) -> str:
        return f"<Profile name={self.name} job={self.job} group={self.group} id={self.id} bound={self.is_bound}>"