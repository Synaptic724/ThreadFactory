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
        self.register_default_templates()


    def register_default_templates(self) -> None:
        """
        Registers the default agent templates.

        This method is called to ensure that the builder has at least one
        callable agent factory registered. It sets up a basic `General` agent
        template that can be used if no specific template name is provided.
        """
        self._register_general_template()
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

        if self._registry:
            self._registry.dispose()
            # Setting to None after dispose is good practice for explicit cleanup
            self._registry = None

    def _register_general_template(self) -> None:
        """
        Registers a symbolic 'general' agent template.

        This internal helper method sets up a basic `General` agent template
        that can be used for general-purpose agent creation. It ensures that
        the builder has a callable agent factory that can be used for creating
        agents that do not require specific configurations or parameters.
        This is useful for creating agents that can handle a wide range of tasks
        without needing to define a specialized template for each use case.
        """
        self.register_template(
            "general",
            Pack(
                lambda command_center, *args, **kwargs: General(
                    command_center=command_center,
                    *args,
                    **kwargs  # Allows for additional keyword arguments to be passed
                )
            )
        )

    def _register_default_template(self) -> None:
        """
        Registers a symbolic 'default' agent template.

        This internal helper method sets up a basic `agent` agent template
        that can be used if no specific template name is provided. It ensures
        that the builder always has at least one callable agent factory.
        """
        self.register_template(
            "default",
            Pack(
                lambda command_center, *args, **kwargs: Agent(
                    command_center=command_center,
                    *args,
                    **kwargs  # Allows for additional keyword arguments to be passed
                )
            )
        )

    def register_template(self, template_name: str, factory_fn: Pack) -> None:
        """
        Registers an agent factory function under a symbolic name.

        This method associates a unique string `name` with a `Pack` instance
        that encapsulates the logic for creating an agent. The `factory_fn`
        should be a callable that, when executed, returns an `Agent` instance.
        `Pack.bundle()` is used to ensure the factory function is correctly
        wrapped for deferred execution and argument management.

        Args:
            template_name (str): The unique symbolic name for this agent template.
            factory_fn (Pack): A `Pack` instance containing the callable
                               function that will create an agent.

        Raises:
            ValueError: If `name` is empty or `factory_fn` is not callable,
                        or if a template with the given `name` is already registered.
        """
        if not template_name or not callable(factory_fn):  # Check if factory_fn is actually callable (Pack is callable)
            raise ValueError("Template name must be a non-empty string and factory_fn must be callable.")

        # If Pack.bundle(factory_fn) is always applied below, then factory_fn passed here could be raw callable
        # However, if factory_fn is *expected* to be a Pack, then the callable() check is for Pack itself.
        # Assuming factory_fn is a Pack instance based on the type hint.
        if template_name in self._registry:
            raise ValueError(f"An agent template with the name '{template_name}' is already registered.")

        # Ensure the factory_fn is correctly bundled as a Pack for consistent storage
        self._registry[template_name] = Pack.bundle(
            factory_fn)  # This might bundle an already bundled Pack, depends on Pack.bundle logic

    def unregister_template(self, template_name: str) -> bool:
        """
        Removes a registered agent template by name.

        This effectively makes the template unavailable for creating new agents.

        Args:
            template_name (str): The name of the template to remove.

        Returns:
            bool: True if the template was successfully removed, False if it was not found.
        """
        return self._registry.pop(template_name, None) is not None

    def list_templates(self) -> List[str]:
        """
        Returns a list of all registered agent template names.

        This provides a snapshot of the currently available agent templates.

        Returns:
            List[str]: A list of strings, where each string is the name of a registered template.
        """
        return list(self._registry.keys())

    def has_template(self, template_name: str) -> bool:
        """
        Checks if a given template name is registered in the builder.

        Args:
            template_name (str): The name of the template to check for.

        Returns:
            bool: True if a template with the given `name` is registered, False otherwise.
        """
        return template_name in self._registry

    def create_agent(self, template_name: str, *args: Any, **kwargs: Any) -> Agent:
        """
        Creates a fresh agent instance from a registered template, allowing for argument overrides.

        This method retrieves the specified agent template (a `Pack` instance),
        applies any additional positional or keyword arguments, and executes it
        to create a new agent.

        Args:
            template_name (str): The symbolic name of the template to use.
            *args: Positional overrides passed to the agent factory.
            **kwargs: Keyword overrides passed to the agent factory.

        Returns:
            Agent: A newly created agent instance.

        Raises:
            KeyError: If the template name is not registered.
            TypeError: If the resulting object is not an Agent and a Thread.
            RuntimeError: If agent creation fails for any other reason.
        """
        factory_pack = self._registry.get(template_name)
        if not factory_pack:
            raise KeyError(f"No agent template registered under the name '{template_name}'")

        try:
            # Directly invoke with overrides — no need to curry unless you're caching
            agent_instance = factory_pack(*args, **kwargs)
        except Exception as e:
            raise RuntimeError(f"Agent creation failed for template '{template_name}': {e}") from e

        if not isinstance(agent_instance, threading.Thread) or not isinstance(agent_instance, Agent):
            raise TypeError(
                f"Factory for template '{template_name}' did not return a valid Agent instance. "
                f"Expected an instance of threading.Thread and Agent, but got {type(agent_instance).__name__}."
            )

        return agent_instance
