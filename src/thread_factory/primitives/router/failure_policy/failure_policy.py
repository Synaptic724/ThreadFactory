from enum import Enum, auto


class FailurePolicy(Enum):
    IGNORE = auto()
    LOG_ONLY = auto()
    CANCEL_NODE = auto()
    CANCEL_ROUTER = auto()
    RETRY = auto()
