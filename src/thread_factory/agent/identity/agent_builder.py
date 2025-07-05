import threading
from typing import Callable, Union, List, Any
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.utils.coordination.package import Pack
from thread_factory.utils.interfaces.disposable import IDisposable
from thread_factory.agent.identity.types.agent import Agent
from thread_factory.agent.identity.types.general import General

class AgentBuilder(IDisposable):
    """
    AgentBuilder
    ----------------
    A factory for creating and managing agent templates.
    ...
    """

    def __init__(self):
        """
        Initializes the agent builder and registers a default template.
        """
        super().__init__()
        self._registry: ConcurrentDict[str, Pack] = ConcurrentDict()
        self._register_default_template()

    def dispose(self) -> None:
        """
        Disposes the builder and clears all registered agent templates.
        """
        if self._disposed:
            return
        self._registry.dispose()
        self._registry = None

    def _register_default_template(self) -> None:
        """
        Registers a symbolic 'default' agent template using the General class.
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
        ...
        """
        if not name or not callable(factory_fn):
            raise ValueError("Template name must be a non-empty string and factory_fn must be callable.")

        if name in self._registry:
            raise ValueError(f"An agent template with the name '{name}' is already registered.")

        self._registry[name] = Pack.bundle(factory_fn)

    def unregister_template(self, name: str) -> bool:
        """
        Removes a registered agent template by name.
        ...
        """
        return self._registry.pop(name, None) is not None

    def list_templates(self) -> List[str]:
        """
        Returns a list of all registered agent template names.
        ...
        """
        return list(self._registry.keys())

    def has_template(self, name: str) -> bool:
        """
        Checks if a given template name is registered.
        ...
        """
        return name in self._registry

    def create_agent(self, name: str, *args, **kwargs) -> Agent:
        """
        Creates a fresh agent instance from a registered template.
        Allows override of arguments at runtime while respecting the original template.

        Args:
            name (str): The name of the registered template.
            *args: Positional arguments to override.
            **kwargs: Keyword arguments to override.

        Returns:
            Agent: A new agent instance.

        Raises:
            KeyError: If the template is not registered.
            TypeError: If the created object is not a valid Agent.
        """
        factory_pack = self._registry.get(name)
        if not factory_pack:
            raise KeyError(f"No agent template registered under the name '{name}'")

        # Apply argument overrides — Pack handles merging
        override_pack = factory_pack.override_args(*args, **kwargs)

        agent_instance = override_pack()

        if not isinstance(agent_instance, threading.Thread) or not isinstance(agent_instance, Agent):
            raise TypeError(
                f"Factory for template '{name}' did not return a valid Agent instance. "
                f"Got {type(agent_instance).__name__}."
            )

        return agent_instance
