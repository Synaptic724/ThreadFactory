# This object is primarily to set up the configuration context for the runtime.
from enum import Enum


# It can be prod, or development


class Env(Enum):
    DEV = "dev"
    DEBUG = "debug"
    PROD = "prod"