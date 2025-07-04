from abc import ABC, abstractmethod

class IProfile(ABC):
    """
    Interface for a profile that can be used to manage thread execution.
    """

    __slots__ = []
    @abstractmethod
    def get_name(self) -> str:
        """
        Get the name of the profile.
        """
        raise NotImplementedError("This method should be overridden by subclasses.")

    @abstractmethod
    def get_description(self) -> str:
        """
        Get the description of the profile.
        """
        raise NotImplementedError("This method should be overridden by subclasses.")