from enum import Enum


class MissingPolicy(str, Enum):
    ERROR = "error"
    REGISTER_ROOT = "register_root"
    REGISTER_RECURSIVE = "register_recursive"


class DependencyRegistrationPolicy(str, Enum):
    IGNORE = "ignore"
    REGISTER_RECURSIVE = "register_recursive"
