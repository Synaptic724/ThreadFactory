import threading, ulid, logging, time
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

    def dispose(self):
        """
        Cleans up the activity's resources and marks it as disposed.

        This method implements the `IDisposable` contract. It ensures that
        the activity's resources are properly released, preventing resource leaks.
        Specifically, it:
        1. Sets the `_disposed` flag to True to prevent multiple disposal calls.
        2. Unregisters the activity from the `SignalController` if one is attached.
           The `dispose_object=False` argument indicates that the SignalController
           should not attempt to dispose of *this* object again.
        3. Clears the internal `_registered_agents` and `_metadata` collections.
        4. Nullifies the reference to the `_signal_controller`.

        This operation is thread-safe and idempotent. After disposal, the activity
        should not be used.
        """
        if self._disposed:
            self._logger.debug(f"Activity '{self.id}' is already disposed.")
            return
        with self._lock:
            # Re-check _disposed flag inside the lock in case of race condition
            if self._disposed:
                return

            self._disposed = True
            self._logger.info(f"Disposing Activity '{self.id}'.")

            if self._signal_controller:
                try:
                    # Unregister from controller without causing a recursive dispose call
                    self._signal_controller.unregister(self.id, dispose_object=False)
                    self._logger.debug(f"Activity '{self.id}' unregistered from SignalController.")
                except Exception as e:
                    self._logger.warning(
                        f"Error unregistering Activity '{self.id}' from SignalController during disposal: {e}",
                        exc_info=True)

            # Clear internal collections
            self._registered_agents.clear()
            self._metadata.clear()

            # Nullify references to external objects to aid garbage collection
            self._signal_controller = None
            self._logger.debug(f"Activity '{self.id}' disposal complete.")

    # --- SignalController Contract ---

    @property
    def id(self) -> str:
        """
        The unique identifier for this Activity instance.

        This property provides read-only access to the ULID (Universally Unique Lexicographically Sortable Identifier)
        assigned to the activity upon its creation. This ID is used by the `SignalController`
        and other components to uniquely reference this specific activity.

        Returns:
            str: The unique identifier string for this activity.
        """
        return self._id

    def _get_object_details(self) -> ConcurrentDict[str, Any]:
        """
        Returns this activity's essential metadata and a list of callable commands.

        This method is a core part of the `BaseActivity` contract with the `SignalController`
        or any introspection mechanism. It provides a structured way to expose the
        activity's name and its primary interaction points (commands).

        The base implementation provides the class name and commands for
        `Youtube` and `get_assigned_agents`. Subclasses are expected to
        extend this dictionary to include their own specific commands and details,
        as demonstrated in `JobActivity`.

        Returns:
            ConcurrentDict[str, Any]: A thread-safe dictionary containing:
                                      - "name" (str): The name of the activity's class.
                                      - "commands" (ConcurrentDict[str, Callable]): A dictionary
                                        mapping command names to their corresponding callable methods.
            """
        return ConcurrentDict({
            "name": self.__class__.__name__,
            "commands": ConcurrentDict({
                "get_metadata": self.get_metadata,
                "get_assigned_agents": self.get_assigned_agents
            })
        })
    # --- Agent Management ---

    def _get_agent_details(self) -> Optional[Agent]:
        """
        Retrieves the Agent instance currently registered and associated with the calling thread.

        This internal method checks if the current thread has a `factory_id` attribute
        (implying it's an agent-managed thread) and, if so, attempts to find the
        corresponding `Agent` object that has been registered with this activity.
        It's useful for the activity to determine which specific agent is currently
        interacting with it.

        Returns:
            Optional[Agent]: The `Agent` instance if one is found for the current
                             thread and is registered with this activity, otherwise `None`.
        """
        current_id = getattr(threading.current_thread(), "factory_id", None)
        return self._registered_agents.get(current_id, None)

    def _get_agent_id(self) -> Optional[str]:
        """
        Retrieves the unique factory ID of the Agent currently associated with the calling thread.

        This method acts as a convenient way for the activity to identify which agent
        is performing an action. It looks for a `factory_id` on the current thread
        and confirms if that agent is registered with this activity. If no such agent
        is found or registered, it returns `None`.

        Returns:
            Optional[str]: The `factory_id` (string) of the currently associated and
                           registered agent, or `None` if no agent is found or registered.
        """
        current_id = getattr(threading.current_thread(), "factory_id", None)
        if current_id in self._registered_agents:
            return current_id
        else:
            self._logger.debug(f"No agent registered for Activity '{self.id}' with factory ID '{current_id}'.")
            return None

    def register_agent(self, agent: Agent):
        """
        Assigns an agent to this activity, making it aware of the agent.

        This method is typically called by a controlling entity (e.g., a CommandCenter)
        to associate a specific `Agent` instance with this activity. The agent is
        registered using its `factory_id`. If the agent is already registered,
        this operation has no effect. A "AGENT_ASSIGNED" notification is emitted.

        Args:
            agent (Agent): The Agent instance to be registered with this activity.
                           Must have a unique `factory_id`.
        """
        if agent and agent.factory_id not in self._registered_agents:
            self._registered_agents[agent.factory_id] = agent
            self._logger.debug(f"Agent '{agent.factory_id}' registered to Activity '{self.id}'.")
            self._notify("AGENT_ASSIGNED", {"agent_id": agent.factory_id})
        elif agent:
            self._logger.debug(f"Agent '{agent.factory_id}' is already registered to Activity '{self.id}'.")

    def unregister_agent(self, agent: Agent):
        """
        Unassigns an agent from this activity.

        This method removes the association of a specific `Agent` instance from
        this activity. If the agent was successfully unregistered, a
        "AGENT_UNASSIGNED" notification is emitted. This operation is idempotent;
        if the agent is not registered, nothing happens.

        Args:
            agent (Agent): The Agent instance to be unregistered from this activity.
        """
        if agent and self._registered_agents.pop(agent.factory_id, None):
            self._logger.debug(f"Agent '{agent.factory_id}' unregistered from Activity '{self.id}'.")
            self._notify("AGENT_UNASSIGNED", {"agent_id": agent.factory_id})
        elif agent:
            self._logger.debug(f"Agent '{agent.factory_id}' was not registered to Activity '{self.id}'.")

    def get_assigned_agents(self) -> ConcurrentList[str]:
        """
        Returns a thread-safe list of the IDs of all agents currently assigned to this activity.

        This provides a snapshot of the agents actively associated with this activity,
        useful for monitoring or dispatching tasks to assigned agents.

        Returns:
            ConcurrentList[str]: A thread-safe list containing the `factory_id`s of
                                 all currently assigned agents.
        """
        return ConcurrentList(self._registered_agents.keys())

    def get_metadata(self) -> ConcurrentDict[str, Any]:
        """
        Returns a thread-safe copy of the activity's associated metadata.

        The metadata can include any custom key-value pairs passed during
        the activity's initialization. This method ensures that the returned
        dictionary is a copy, preventing external modifications from affecting
        the activity's internal state.

        Returns:
            ConcurrentDict[str, Any]: A thread-safe copy of the activity's metadata dictionary.
        """
        return self._metadata.copy()

    # --- Private Helpers ---

    def _notify(self, event_type: str, data: Optional[Dict[str, Any]] = None):
        """
        Helper method to safely send notifications to the attached SignalController.

        This internal method acts as the primary communication channel from the activity
        to the broader system via the `SignalController`. It checks if a controller
        is present and not disposed before attempting to send the notification.
        Errors during notification are logged.

        Args:
            event_type (str): A string identifying the type of event (e.g., "STATUS_CHANGED", "PROGRESS_UPDATE").
            data (Optional[Dict[str, Any]]): An optional dictionary containing any
                                            additional context or data relevant to the event.
        """
        if self._signal_controller and not self._signal_controller._disposed:
            try:
                # The SignalController's notify method is expected to handle its own locking
                # for thread-safe dispatch of notifications.
                self._signal_controller.notify(self.id, event_type, data)
            except Exception as e:
                # Log the error if notification fails, but don't prevent the activity from functioning.
                self._logger.error(f"Activity '{self.id}' failed to notify controller for event '{event_type}': {e}",
                                   exc_info=True)
        # If signal_controller is None or disposed, notification is silently skipped.