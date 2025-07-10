from enum import Enum, auto


class AgentPoolType(Enum):
    """
    Enum representing the type of agent.
    """
    NOTSET = auto()  # Represents an agent that has not been set to a specific type
    DISMISS = auto()  # Represents a worker that is set to be dismissed
    DISPATCHER = auto()  # Represents a worker focused on dispatching tasks
    RESERVED_DISPATCHER = auto()  # Represents a worker focused on dispatching tasks where they can be claimed
    THROUGHPUT = auto()   # Represents a worker focused on high throughput
    SLEEP = auto()  # Represents a worker focused on high throughput with sleep behavior