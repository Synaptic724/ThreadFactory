from enum import auto, Enum


class RouterMode(Enum):
    ONE_SHOT = auto()    # Threads exit after task
    LOOP = auto()        # Threads return to router after task
    STRICT = auto()      # Exit if routing conditions not met