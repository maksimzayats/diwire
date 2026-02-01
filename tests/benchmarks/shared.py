from __future__ import annotations

from dataclasses import dataclass


class SingletonService:
    def __init__(self) -> None:
        self.value = 1


class WideDep1:
    pass


class WideDep2:
    pass


class WideDep3:
    pass


class WideDep4:
    pass


class WideDep5:
    pass


class WideDep6:
    pass


class WideDep7:
    pass


class WideDep8:
    pass


class WideDep9:
    pass


class WideDep10:
    pass


class WideDep11:
    pass


class WideDep12:
    pass


class WideDep13:
    pass


class WideDep14:
    pass


class WideDep15:
    pass


class WideDep16:
    pass


class WideDep17:
    pass


class WideDep18:
    pass


class WideDep19:
    pass


class WideDep20:
    pass


@dataclass(slots=True)
class WideGraphRoot:
    dep1: WideDep1
    dep2: WideDep2
    dep3: WideDep3
    dep4: WideDep4
    dep5: WideDep5
    dep6: WideDep6
    dep7: WideDep7
    dep8: WideDep8
    dep9: WideDep9
    dep10: WideDep10
    dep11: WideDep11
    dep12: WideDep12
    dep13: WideDep13
    dep14: WideDep14
    dep15: WideDep15
    dep16: WideDep16
    dep17: WideDep17
    dep18: WideDep18
    dep19: WideDep19
    dep20: WideDep20


@dataclass(slots=True)
class ScopedService:
    pass


@dataclass(slots=True)
class ScopedGraphRoot:
    singleton: SingletonService
    scoped: ScopedService


@dataclass(slots=True)
class ChainDep1:
    pass


@dataclass(slots=True)
class ChainDep2:
    dep1: ChainDep1


@dataclass(slots=True)
class ChainDep3:
    dep2: ChainDep2


@dataclass(slots=True)
class ChainDep4:
    dep3: ChainDep3


@dataclass(slots=True)
class ChainDep5:
    dep4: ChainDep4


@dataclass(slots=True)
class ChainDep6:
    dep5: ChainDep5


@dataclass(slots=True)
class ChainDep7:
    dep6: ChainDep6


@dataclass(slots=True)
class ChainDep8:
    dep7: ChainDep7


@dataclass(slots=True)
class ChainDep9:
    dep8: ChainDep8


@dataclass(slots=True)
class ChainDep10:
    dep9: ChainDep9


@dataclass(slots=True)
class ChainGraphRoot:
    dep10: ChainDep10
