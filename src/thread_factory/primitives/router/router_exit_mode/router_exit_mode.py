from enum import auto, Enum


class RouterExitMode(Enum):
    NON_BLOCKING = auto()  # Return immediately after dispatch
    BLOCKING = auto()      # Wait until all work is finished before returning