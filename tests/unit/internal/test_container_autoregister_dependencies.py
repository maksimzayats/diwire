from __future__ import annotations

import importlib
import pathlib
import uuid
import warnings
from abc import ABC, abstractmethod
from types import ModuleType
from typing import Any, NamedTuple, cast

import msgspec
import pydantic
import pytest
from pydantic_settings import BaseSettings

from diwire.autoregistration import ConcreteTypeAutoregistrationPolicy
from diwire.container import Container
from diwire.exceptions import DIWireDependencyNotRegisteredError
from diwire.providers import Lifetime
from diwire.scope import Scope

_PYDANTIC_V1_WARNING_PATTERN = (
    r"Core Pydantic V1 functionality isn't compatible with Python 3\.14 or greater\."
)


def _load_pydantic_v1() -> ModuleType | None:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=_PYDANTIC_V1_WARNING_PATTERN,
            category=UserWarning,
        )
        try:
            return importlib.import_module("pydantic.v1")
        except ImportError:
            return None


pydantic_v1 = _load_pydantic_v1()


class DirectDependency:
    pass


class RootWithDirectDependency:
    def __init__(self, dependency: DirectDependency) -> None:
        self.dependency = dependency


class NestedDependency:
    pass


class IntermediateDependency:
    def __init__(self, dependency: NestedDependency) -> None:
        self.dependency = dependency


class RootWithNestedDependencies:
    def __init__(self, dependency: IntermediateDependency) -> None:
        self.dependency = dependency


class ScopedDependency:
    pass


class RootWithScopedDependency:
    def __init__(self, dependency: ScopedDependency) -> None:
        self.dependency = dependency


class AbstractDependency(ABC):
    @abstractmethod
    def run(self) -> None:
        """Run the dependency."""


class ValidDependency:
    pass


class RootWithMixedDependencies:
    def __init__(
        self,
        abstract_dependency: AbstractDependency,
        valid_dependency: ValidDependency,
    ) -> None:
        self.abstract_dependency = abstract_dependency
        self.valid_dependency = valid_dependency


class DecoratorDependency:
    pass


class DecoratorService:
    def __init__(self, dependency: DecoratorDependency) -> None:
        self.dependency = dependency


class ResolveDependency:
    pass


class ResolveRoot:
    def __init__(self, dependency: ResolveDependency) -> None:
        self.dependency = dependency


class ExistingDependency:
    pass


class RootWithExistingDependency:
    def __init__(self, dependency: ExistingDependency) -> None:
        self.dependency = dependency


class NamedTupleFrameworkDependency:
    pass


class MsgspecFrameworkDependency:
    pass


class PydanticFrameworkDependency:
    pass


class PydanticSettingsDependency(BaseSettings):
    value: str = "settings"


class RootWithPydanticSettingsDependency:
    def __init__(self, dependency: PydanticSettingsDependency) -> None:
        self.dependency = dependency


class RootWithBuiltinDep:
    def __init__(self, token: str) -> None:
        self.token = token


class RootWithPathDep:
    def __init__(self, path: pathlib.Path) -> None:
        self.path = path


class RootWithUuidDep:
    def __init__(self, request_id: uuid.UUID) -> None:
        self.request_id = request_id


class _TestMetaclass(type):
    pass


def test_container_default_autoregisters_dependencies_during_registration() -> None:
    container = Container()

    container.register_concrete(concrete_type=RootWithDirectDependency)

    dependency_spec = container._providers_registrations.find_by_type(DirectDependency)
    assert dependency_spec is not None
    assert dependency_spec.concrete_type is DirectDependency


def test_registration_override_can_disable_dependency_autoregistration() -> None:
    container = Container()

    container.register_concrete(
        concrete_type=RootWithDirectDependency,
        autoregister_dependencies=False,
    )

    assert container._providers_registrations.find_by_type(DirectDependency) is None


def test_registration_override_can_enable_dependency_autoregistration() -> None:
    container = Container(autoregister_dependencies=False)

    container.register_concrete(
        concrete_type=RootWithDirectDependency,
        autoregister_dependencies=True,
    )

    assert container._providers_registrations.find_by_type(DirectDependency) is not None


def test_dependency_autoregistration_is_recursive() -> None:
    container = Container()

    container.register_concrete(concrete_type=RootWithNestedDependencies)

    assert container._providers_registrations.find_by_type(IntermediateDependency) is not None
    assert container._providers_registrations.find_by_type(NestedDependency) is not None


def test_dependency_autoregistration_skips_already_registered_dependency() -> None:
    container = Container()
    container.register_concrete(concrete_type=ExistingDependency)
    existing_spec = container._providers_registrations.get_by_type(ExistingDependency)

    container.register_concrete(concrete_type=RootWithExistingDependency)

    assert container._providers_registrations.get_by_type(ExistingDependency) is existing_spec


def test_strict_container_skips_dependency_autoregistration_even_when_enabled() -> None:
    container = Container(
        autoregister_concrete_types=False,
        autoregister_dependencies=True,
    )

    container.register_concrete(concrete_type=RootWithDirectDependency)

    assert container._providers_registrations.find_by_type(DirectDependency) is None


def test_dependency_autoregistration_uses_parent_scope_and_lifetime() -> None:
    container = Container()

    container.register_concrete(
        concrete_type=RootWithScopedDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
        autoregister_dependencies=True,
    )

    dependency_spec = container._providers_registrations.get_by_type(ScopedDependency)
    assert dependency_spec.scope is Scope.REQUEST
    assert dependency_spec.lifetime is Lifetime.SCOPED


def test_dependency_autoregistration_ignores_registration_failures_and_continues() -> None:
    container = Container()

    container.register_concrete(concrete_type=RootWithMixedDependencies)

    assert container._providers_registrations.find_by_type(AbstractDependency) is None
    assert container._providers_registrations.find_by_type(ValidDependency) is not None


def test_resolve_autoregistration_skips_builtin_dependency_types() -> None:
    container = Container()

    with pytest.raises(DIWireDependencyNotRegisteredError) as exc_info:
        container.resolve(RootWithBuiltinDep)

    message = str(exc_info.value)
    assert repr(str) in message
    assert repr(RootWithBuiltinDep) in message
    assert container._providers_registrations.find_by_type(str) is None


def test_resolve_autoregistration_skips_pathlib_path_dependency() -> None:
    container = Container()

    with pytest.raises(DIWireDependencyNotRegisteredError):
        container.resolve(RootWithPathDep)

    assert container._providers_registrations.find_by_type(pathlib.Path) is None
    expected_path = pathlib.Path("x")
    container.register_instance(
        provides=pathlib.Path,
        instance=expected_path,
    )

    resolved = container.resolve(RootWithPathDep)
    assert resolved.path is expected_path


def test_resolve_autoregistration_skips_uuid_dependency() -> None:
    container = Container()

    with pytest.raises(DIWireDependencyNotRegisteredError):
        container.resolve(RootWithUuidDep)

    assert container._providers_registrations.find_by_type(uuid.UUID) is None
    expected_uuid = uuid.UUID(int=0)
    container.register_instance(instance=expected_uuid)

    resolved = container.resolve(RootWithUuidDep)
    assert resolved.request_id is expected_uuid


def test_autoregistration_policy_skips_metaclasses() -> None:
    policy = ConcreteTypeAutoregistrationPolicy()

    assert policy.is_eligible_concrete(_TestMetaclass) is False


def test_factory_decorator_can_autoregister_dependencies() -> None:
    container = Container()

    @container.register_factory(DecoratorService, autoregister_dependencies=True)
    def build_service(dependency: DecoratorDependency) -> DecoratorService:
        return DecoratorService(dependency=dependency)

    assert build_service is not None
    dependency_spec = container._providers_registrations.find_by_type(DecoratorDependency)
    assert dependency_spec is not None
    assert dependency_spec.concrete_type is DecoratorDependency


def test_resolve_autoregistration_integration_registers_dependency_chain() -> None:
    container = Container()

    resolved = container.resolve(ResolveRoot)

    assert isinstance(resolved, ResolveRoot)
    assert isinstance(resolved.dependency, ResolveDependency)
    assert container._providers_registrations.find_by_type(ResolveDependency) is not None


def test_resolve_autoregisters_pydantic_settings_as_singleton_factory() -> None:
    container = Container()

    first = container.resolve(PydanticSettingsDependency)
    second = container.resolve(PydanticSettingsDependency)

    settings_spec = container._providers_registrations.get_by_type(PydanticSettingsDependency)
    assert first is second
    assert settings_spec.factory is not None
    assert settings_spec.concrete_type is None
    assert settings_spec.lifetime is Lifetime.SINGLETON
    assert settings_spec.scope is Scope.APP


def test_dependency_autoregistration_registers_pydantic_settings_as_root_singleton() -> None:
    container = Container()

    container.register_concrete(
        concrete_type=RootWithPydanticSettingsDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    settings_spec = container._providers_registrations.get_by_type(PydanticSettingsDependency)
    assert settings_spec.factory is not None
    assert settings_spec.concrete_type is None
    assert settings_spec.lifetime is Lifetime.SINGLETON
    assert settings_spec.scope is Scope.APP


def test_resolve_autoregisters_pydantic_v1_settings_as_singleton_factory() -> None:
    if pydantic_v1 is None:
        pytest.skip("pydantic.v1 is unavailable")
    pydantic_v1_module = cast("Any", pydantic_v1)
    base_settings_type = cast("type[Any]", pydantic_v1_module.BaseSettings)

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=_PYDANTIC_V1_WARNING_PATTERN,
            category=UserWarning,
        )

        class PydanticV1SettingsDependency(base_settings_type):
            value: int = 7

        container = Container()
        first = container.resolve(PydanticV1SettingsDependency)
        second = container.resolve(PydanticV1SettingsDependency)

    settings_spec = container._providers_registrations.get_by_type(PydanticV1SettingsDependency)
    assert first is second
    assert settings_spec.factory is not None
    assert settings_spec.concrete_type is None
    assert settings_spec.lifetime is Lifetime.SINGLETON
    assert settings_spec.scope is Scope.APP


def test_concrete_registration_autoregisters_namedtuple_class_dependencies() -> None:
    class NamedTupleRoot(NamedTuple):
        dependency: NamedTupleFrameworkDependency

    container = Container()

    container.register_concrete(
        concrete_type=NamedTupleRoot,
        autoregister_dependencies=True,
    )

    dependency_spec = container._providers_registrations.find_by_type(
        NamedTupleFrameworkDependency,
    )
    assert dependency_spec is not None
    assert dependency_spec.concrete_type is NamedTupleFrameworkDependency


def test_concrete_registration_autoregisters_msgspec_struct_dependencies() -> None:
    class MsgspecRoot(msgspec.Struct):
        dependency: MsgspecFrameworkDependency

    container = Container()

    container.register_concrete(
        concrete_type=MsgspecRoot,
        autoregister_dependencies=True,
    )

    dependency_spec = container._providers_registrations.find_by_type(
        MsgspecFrameworkDependency,
    )
    assert dependency_spec is not None
    assert dependency_spec.concrete_type is MsgspecFrameworkDependency


def test_concrete_registration_autoregisters_pydantic_basemodel_v2_dependencies() -> None:
    class PydanticRoot(pydantic.BaseModel):
        model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)
        dependency: PydanticFrameworkDependency

    container = Container()

    container.register_concrete(
        concrete_type=PydanticRoot,
        autoregister_dependencies=True,
    )

    dependency_spec = container._providers_registrations.find_by_type(
        PydanticFrameworkDependency,
    )
    assert dependency_spec is not None
    assert dependency_spec.concrete_type is PydanticFrameworkDependency
