import threading
import ulid
import logging
import time
from enum import Enum, auto
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional, List
from thread_factory.synchronization.controllers.signal_controller import SignalController
from thread_factory.agent.identity.types.agent import Agent
from thread_factory.utils.interfaces.disposable import IDisposable
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.concurrency.concurrent_list import ConcurrentList


class BaseActivity(IDisposable, ABC):
    """
    A minimal abstract base class for any controllable activity in the ThreadFactory.

    This class defines the absolute essential contract for an object to be
    managed by a SignalController and executed by an Agent. It is intentionally
    kept lean to allow for maximum flexibility in user implementations.
    """

    def __init__(self,
                 signal_controller: Optional[SignalController] = None,
                 logger: Optional[logging.Logger] = None,
                 **kwargs):
        """
        Initializes the BaseActivity.

        Args:
            signal_controller (Optional[SignalController]): The communication bus to register with.
            logger (Optional[logging.Logger]): A logger instance.
            **kwargs: Any user-defined metadata to associate with this activity.
        """
        super().__init__()
        self._id: str = str(ulid.ULID())
        self._logger = logger or logging.getLogger(__name__)
        self._lock = threading.RLock()
        self._metadata: ConcurrentDict[str, Any] = ConcurrentDict(kwargs)
        self._registered_agents: ConcurrentDict[str, Agent] = ConcurrentDict()

        self._signal_controller = signal_controller
        if self._signal_controller:
            try:
                self._signal_controller.register(self)
            except Exception as e:
                self._logger.warning(f"Failed to auto-register BaseActivity '{self.id}': {e}", exc_info=True)

    # --- SignalController Contract ---

    @property
    def id(self) -> str:
        """The unique identifier for this Activity instance."""
        return self._id

    def _get_object_details(self) -> ConcurrentDict[str, Any]:
        """
        Returns this activity's metadata and commands to the SignalController.
        Base implementation exposes only agent management. Subclasses should extend this.
        """
        return ConcurrentDict({
            "name": self.__class__.__name__,
            "commands": ConcurrentDict({
                "get_metadata": self.get_metadata,
                "get_assigned_agents": self.get_assigned_agents
            })
        })

    # --- Agent Management ---

    def register_agent(self, agent: Agent):
        """Assigns an agent to this activity. Called by the CommandCenter."""
        if agent and agent.factory_id not in self._registered_agents:
            self._registered_agents[agent.factory_id] = agent
            self._logger.debug(f"Agent '{agent.factory_id}' registered to Activity '{self.id}'.")
            self._notify("AGENT_ASSIGNED", {"agent_id": agent.factory_id})

    def unregister_agent(self, agent: Agent):
        """Unassigns an agent from this activity."""
        if agent and self._registered_agents.pop(agent.factory_id, None):
            self._logger.debug(f"Agent '{agent.factory_id}' unregistered from Activity '{self.id}'.")
            self._notify("AGENT_UNASSIGNED", {"agent_id": agent.factory_id})

    def get_assigned_agents(self) -> ConcurrentList[str]:
        """Returns a thread-safe list of IDs of all agents currently assigned."""
        return ConcurrentList(self._registered_agents.keys())

    def get_metadata(self) -> ConcurrentDict[str, Any]:
        """Returns a thread-safe copy of the activity's metadata."""
        return self._metadata.copy()

    # --- Private Helpers ---

    def _notify(self, event_type: str, data: Optional[Dict[str, Any]] = None):
        """Helper to safely send notifications to the attached signal controller."""
        if self._signal_controller and not self._signal_controller._disposed:
            try:
                self._signal_controller.notify(self.id, event_type, data)
            except Exception as e:
                self._logger.error(f"Activity '{self.id}' failed to notify controller: {e}", exc_info=True)

    def dispose(self):
        """Cleans up the activity's resources."""
        if self._disposed:
            return
        with self._lock:
            self._disposed = True
            if self._signal_controller:
                try:
                    self._signal_controller.unregister(self.id, dispose_object=False)
                except Exception:
                    pass
            self._registered_agents.clear()
            self._metadata.clear()
            self._signal_controller = None
