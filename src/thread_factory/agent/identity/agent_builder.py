import threading
from typing import Callable, Union, List, Any, Type, Optional
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.utils.coordination.package import Pack
from thread_factory.utils.interfaces.disposable import IDisposable
from thread_factory.agent.identity.types.agent import Agent  # Assuming this is a base class for agents
from thread_factory.agent.identity.types.general import General  # Assuming this is a concrete Agent subclass


class AgentBuilder(IDisposable):
    """
    AgentBuilder
    ----------------
    A factory for creating and managing agent templates.

    This class serves as a central registry for different types of agent
    configurations (templates). It allows for the symbolic registration of
    functions (factories) that can produce `Agent` instances. When creating
    an agent, it facilitates overriding default arguments specified in the
    template, providing a flexible and extensible way to provision agents
    within the ThreadFactory system.

    It implements the `IDisposable` interface for proper resource cleanup.
    """

    __slots__ = IDisposable.__slots__ + ["_registry", "_disposed"]  # Removed _registered as it's not used consistently

    def __init__(self):
        """
        Initializes the AgentBuilder and registers a default agent template.

        Upon instantiation, the builder creates an empty concurrent dictionary
        (`_registry`) to store agent templates and then automatically registers
        a basic 'default' agent template, making it immediately available for use.
        """
        super().__init__()
        self._registry: ConcurrentDict[str, Pack] = ConcurrentDict()
        # _disposed is handled by IDisposable base
        self._register_default_template()

    def dispose(self) -> None:
        """
        Disposes of the AgentBuilder, releasing its managed resources.

        This method implements the `IDisposable` contract. It ensures that
        the internal `_registry` (a `ConcurrentDict` containing `Pack` instances)
        is properly disposed of, clearing any references to registered agent templates.
        This prevents resource leaks, especially if `Pack` or the factories
        themselves hold onto resources.

        This operation is idempotent; calling it multiple times will have no
        further effect after the first call.
        """
        if self._disposed:
            return
        # The base IDisposable dispose method will set _disposed = True
        super().dispose()

        if self._registry:
            self._registry.dispose()
            # Setting to None after dispose is good practice for explicit cleanup
            self._registry = None

    def _register_default_template(self) -> None:
        """
        Registers a symbolic 'default' agent template.

        This internal helper method sets up a basic `General` agent template
        that can be used if no specific template name is provided. It ensures
        that the builder always has at least one callable agent factory.
        """
        self.register_template(
            "default",
            Pack(
                lambda command_center: General(
                    command_center=command_center,
                    public_name="Default Agent",
                    job_title="General Purpose"
                )
            )
        )

    def register_template(self, name: str, factory_fn: Pack) -> None:
        """
        Registers an agent factory function under a symbolic name.

        This method associates a unique string `name` with a `Pack` instance
        that encapsulates the logic for creating an agent. The `factory_fn`
        should be a callable that, when executed, returns an `Agent` instance.
        `Pack.bundle()` is used to ensure the factory function is correctly
        wrapped for deferred execution and argument management.

        Args:
            name (str): The unique symbolic name for this agent template.
            factory_fn (Pack): A `Pack` instance containing the callable
                               function that will create an agent.

        Raises:
            ValueError: If `name` is empty or `factory_fn` is not callable,
                        or if a template with the given `name` is already registered.
        """
        if not name or not callable(factory_fn):  # Check if factory_fn is actually callable (Pack is callable)
            raise ValueError("Template name must be a non-empty string and factory_fn must be callable.")

        # If Pack.bundle(factory_fn) is always applied below, then factory_fn passed here could be raw callable
        # However, if factory_fn is *expected* to be a Pack, then the callable() check is for Pack itself.
        # Assuming factory_fn is a Pack instance based on the type hint.
        if name in self._registry:
            raise ValueError(f"An agent template with the name '{name}' is already registered.")

        # Ensure the factory_fn is correctly bundled as a Pack for consistent storage
        self._registry[name] = Pack.bundle(
            factory_fn)  # This might bundle an already bundled Pack, depends on Pack.bundle logic

    def unregister_template(self, name: str) -> bool:
        """
        Removes a registered agent template by name.

        This effectively makes the template unavailable for creating new agents.

        Args:
            name (str): The name of the template to remove.

        Returns:
            bool: True if the template was successfully removed, False if it was not found.
        """
        return self._registry.pop(name, None) is not None

    def list_templates(self) -> List[str]:
        """
        Returns a list of all registered agent template names.

        This provides a snapshot of the currently available agent templates.

        Returns:
            List[str]: A list of strings, where each string is the name of a registered template.
        """
        return list(self._registry.keys())

    def has_template(self, name: str) -> bool:
        """
        Checks if a given template name is registered in the builder.

        Args:
            name (str): The name of the template to check for.

        Returns:
            bool: True if a template with the given `name` is registered, False otherwise.
        """
        return name in self._registry

    def create_agent(self, name: str, *args: Any, **kwargs: Any) -> Agent:
        """
        Creates a fresh agent instance from a registered template, allowing for argument overrides.

        This method retrieves the specified agent template (a `Pack` instance)
        and then applies any additional positional (`*args`) or keyword (`**kwargs`)
        arguments provided at runtime. These new arguments will override or augment
        those already bound within the template's `Pack`, facilitating flexible
        agent creation. The method then executes the configured factory function
        to produce the agent instance.

        Args:
            name (str): The name of the registered template to use for creating the agent.
            *args: Positional arguments to override or pass to the agent factory.
            **kwargs: Keyword arguments to override or pass to the agent factory.

        Returns:
            Agent: A new agent instance, which must be a subclass of `threading.Thread`
                   and an instance of `Agent`.

        Raises:
            KeyError: If the template name is not registered.
            TypeError: If the factory function for the template does not return a
                       valid `Agent` instance (i.e., it's not a `threading.Thread`
                       and an `Agent` subclass).
            Exception: Any other exception raised by the underlying agent factory function.
        """
        factory_pack = self._registry.get(name)
        if not factory_pack:
            raise KeyError(f"No agent template registered under the name '{name}'")

        # Apply argument overrides — Pack's curry method handles merging
        # This creates a new Pack instance with the combined arguments
        override_pack = factory_pack.curry(*args, **kwargs)

        # Execute the final factory function to get the agent instance
        agent_instance = override_pack()

        # Type checking to ensure the factory produces a valid Agent and Thread
        # An Agent should typically be a Thread or manage a Thread for execution.
        if not isinstance(agent_instance, threading.Thread) or not isinstance(agent_instance, Agent):
            raise TypeError(
                f"Factory for template '{name}' did not return a valid Agent instance. "
                f"Expected an instance of threading.Thread and Agent, but got {type(agent_instance).__name__}."
            )

        return agent_instance