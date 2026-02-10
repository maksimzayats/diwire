from typing import NamedTuple


class Component(NamedTuple):
    """A marker used to distinguish different components for the same type.

    Usage:
        class Database: ...

        Replica: TypeAlias = Annotated[Database, Component("replica")]
        Primary: TypeAlias = Annotated[Database, Component("primary")]
    """

    value: str
