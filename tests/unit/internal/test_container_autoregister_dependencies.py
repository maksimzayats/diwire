from __future__ import annotations

import importlib
import pathlib
import uuid
import warnings
from abc import ABC, abstractmethod
from types import ModuleType
from typing import Annotated, Any, Generic, NamedTuple, TypeVar, cast

import msgspec
import pytest

from diwire import (
    AsyncProvider,
    Container,
    DependencyRegistrationPolicy,
    Lifetime,
    MissingPolicy,
    Provider,
    Scope,
)
from diwire._internal.autoregistration import ConcreteTypeAutoregistrationPolicy
from diwire.exceptions import DIWireDependencyNotRegisteredError

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


def _load_pydantic_settings_base() -> type[Any] | None:
    try:
        module = importlib.import_module("pydantic_settings")
    except ImportError:
        return None
    base_settings = getattr(module, "BaseSettings", None)
    if isinstance(base_settings, type):
        return cast("type[Any]", base_settings)
    return None


pydantic_settings_base = _load_pydantic_settings_base()

_PydanticSettingsBase: type[Any]
if pydantic_settings_base is None:

    class _MissingPydanticSettingsBase:
        pass

    _PydanticSettingsBase = _MissingPydanticSettingsBase
else:
    _PydanticSettingsBase = pydantic_settings_base


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


class PydanticSettingsDependency(_PydanticSettingsBase):
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


class _AutoProviderDependency:
    pass


_OpenT = TypeVar("_OpenT")


class _OpenAutoregDependency(Generic[_OpenT]):
    pass


def _build_open_autoreg_dependency(type_arg: type[_OpenT]) -> _OpenAutoregDependency[_OpenT]:
    return _OpenAutoregDependency()


class _TestMetaclass(type):
    pass


def test_container_default_autoregisters_dependencies_during_registration() -> None:
    container = Container()

    container.add(RootWithDirectDependency)

    assert container._providers_registrations.find_by_type(DirectDependency) is not None


def test_registration_override_can_disable_dependency_autoregistration() -> None:
    container = Container(missing_policy=MissingPolicy.REGISTER_ROOT)

    container.add(
        RootWithDirectDependency,
        dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
    )

    assert container._providers_registrations.find_by_type(DirectDependency) is None


def test_registration_override_can_enable_dependency_autoregistration() -> None:
    container = Container(dependency_registration_policy=DependencyRegistrationPolicy.IGNORE)

    container.add(
        RootWithDirectDependency,
        dependency_registration_policy=DependencyRegistrationPolicy.REGISTER_RECURSIVE,
    )

    assert container._providers_registrations.find_by_type(DirectDependency) is not None


def test_dependency_autoregistration_is_recursive() -> None:
    container = Container(
        dependency_registration_policy=DependencyRegistrationPolicy.REGISTER_RECURSIVE
    )

    container.add(RootWithNestedDependencies)

    assert container._providers_registrations.find_by_type(IntermediateDependency) is not None
    assert container._providers_registrations.find_by_type(NestedDependency) is not None


def test_dependency_autoregistration_skips_already_registered_dependency() -> None:
    container = Container(
        dependency_registration_policy=DependencyRegistrationPolicy.REGISTER_RECURSIVE
    )
    container.add(ExistingDependency)
    existing_spec = container._providers_registrations.get_by_type(ExistingDependency)

    container.add(RootWithExistingDependency)

    assert container._providers_registrations.get_by_type(ExistingDependency) is existing_spec


def test_dependency_registration_policy_recursive_autoregisters_dependencies() -> None:
    container = Container(
        dependency_registration_policy=DependencyRegistrationPolicy.REGISTER_RECURSIVE,
    )

    container.add(RootWithDirectDependency)

    assert container._providers_registrations.find_by_type(DirectDependency) is not None


def test_dependency_autoregistration_uses_parent_scope_and_lifetime() -> None:
    container = Container(
        dependency_registration_policy=DependencyRegistrationPolicy.REGISTER_RECURSIVE
    )

    container.add(
        RootWithScopedDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
        dependency_registration_policy=DependencyRegistrationPolicy.REGISTER_RECURSIVE,
    )

    dependency_spec = container._providers_registrations.get_by_type(ScopedDependency)
    assert dependency_spec.scope is Scope.REQUEST
    assert dependency_spec.lifetime is Lifetime.SCOPED


def test_dependency_autoregistration_ignores_registration_failures_and_continues() -> None:
    container = Container(
        dependency_registration_policy=DependencyRegistrationPolicy.REGISTER_RECURSIVE
    )

    container.add(RootWithMixedDependencies)

    assert container._providers_registrations.find_by_type(AbstractDependency) is None
    assert container._providers_registrations.find_by_type(ValidDependency) is not None


def test_resolve_autoregistration_skips_builtin_dependency_types() -> None:
    container = Container(missing_policy=MissingPolicy.REGISTER_ROOT)

    with pytest.raises(DIWireDependencyNotRegisteredError) as exc_info:
        container.resolve(RootWithBuiltinDep)

    message = str(exc_info.value)
    assert repr(str) in message
    assert repr(RootWithBuiltinDep) in message
    assert container._providers_registrations.find_by_type(str) is None


def test_resolve_autoregistration_skips_pathlib_path_dependency() -> None:
    container = Container(missing_policy=MissingPolicy.REGISTER_ROOT)

    with pytest.raises(DIWireDependencyNotRegisteredError):
        container.resolve(RootWithPathDep)

    assert container._providers_registrations.find_by_type(pathlib.Path) is None
    expected_path = pathlib.Path("x")
    container.add_instance(
        expected_path,
        provides=pathlib.Path,
    )

    resolved = container.resolve(RootWithPathDep)
    assert resolved.path is expected_path


def test_resolve_autoregistration_skips_uuid_dependency() -> None:
    container = Container(missing_policy=MissingPolicy.REGISTER_ROOT)

    with pytest.raises(DIWireDependencyNotRegisteredError):
        container.resolve(RootWithUuidDep)

    assert container._providers_registrations.find_by_type(uuid.UUID) is None
    expected_uuid = uuid.UUID(int=0)
    container.add_instance(expected_uuid)

    resolved = container.resolve(RootWithUuidDep)
    assert resolved.request_id is expected_uuid


def test_autoregistration_policy_skips_metaclasses() -> None:
    policy = ConcreteTypeAutoregistrationPolicy()

    assert policy.is_eligible_concrete(_TestMetaclass) is False


def test_autoregistration_policy_skips_non_runtime_class_candidates() -> None:
    policy = ConcreteTypeAutoregistrationPolicy()

    assert policy.is_eligible_concrete("not-a-class") is False


def test_factory_registration_can_set_dependency_registration_policy() -> None:
    container = Container(
        dependency_registration_policy=DependencyRegistrationPolicy.REGISTER_RECURSIVE
    )

    def build_service(dependency: DecoratorDependency) -> DecoratorService:
        return DecoratorService(dependency=dependency)

    container.add_factory(
        build_service,
        provides=DecoratorService,
        dependency_registration_policy=DependencyRegistrationPolicy.REGISTER_RECURSIVE,
    )
    dependency_spec = container._providers_registrations.find_by_type(DecoratorDependency)
    assert dependency_spec is not None
    assert dependency_spec.concrete_type is DecoratorDependency


def test_resolve_autoregistration_integration_registers_dependency_chain() -> None:
    container = Container(
        missing_policy=MissingPolicy.REGISTER_RECURSIVE,
        dependency_registration_policy=DependencyRegistrationPolicy.REGISTER_RECURSIVE,
    )

    resolved = container.resolve(ResolveRoot)

    assert isinstance(resolved, ResolveRoot)
    assert isinstance(resolved.dependency, ResolveDependency)
    assert container._providers_registrations.find_by_type(ResolveDependency) is not None


def test_resolve_on_missing_false_keeps_missing_missing() -> None:
    container = Container(missing_policy=MissingPolicy.REGISTER_ROOT)

    with pytest.raises(DIWireDependencyNotRegisteredError):
        container.resolve(
            ResolveRoot,
            on_missing=MissingPolicy.ERROR,
        )

    assert container._providers_registrations.find_by_type(ResolveRoot) is None
    assert container._providers_registrations.find_by_type(ResolveDependency) is None


def test_resolve_on_missing_register_root_registers_only_root() -> None:
    container = Container()

    with pytest.raises(DIWireDependencyNotRegisteredError):
        container.resolve(
            ResolveRoot,
            on_missing=MissingPolicy.REGISTER_ROOT,
        )

    assert container._providers_registrations.find_by_type(ResolveRoot) is not None
    assert container._providers_registrations.find_by_type(ResolveDependency) is None


def test_resolve_on_missing_register_recursive_registers_chain() -> None:
    container = Container()

    resolved = container.resolve(
        ResolveRoot,
        on_missing=MissingPolicy.REGISTER_RECURSIVE,
    )

    assert isinstance(resolved, ResolveRoot)
    assert isinstance(resolved.dependency, ResolveDependency)
    assert container._providers_registrations.find_by_type(ResolveRoot) is not None
    assert container._providers_registrations.find_by_type(ResolveDependency) is not None


def test_resolve_from_container_uses_container_default_on_missing() -> None:
    container = Container(missing_policy=MissingPolicy.REGISTER_ROOT)

    with pytest.raises(DIWireDependencyNotRegisteredError):
        container.resolve(
            ResolveRoot,
            on_missing="from_container",
        )

    assert container._providers_registrations.find_by_type(ResolveRoot) is not None
    assert container._providers_registrations.find_by_type(ResolveDependency) is None


def test_resolve_provider_dependency_key_autoregisters_inner_dependency() -> None:
    container = Container(
        default_lifetime=Lifetime.TRANSIENT, missing_policy=MissingPolicy.REGISTER_ROOT
    )

    provider = container.resolve(Provider[_AutoProviderDependency])
    first = provider()
    second = provider()

    assert isinstance(first, _AutoProviderDependency)
    assert isinstance(second, _AutoProviderDependency)
    assert first is not second


@pytest.mark.asyncio
async def test_resolve_async_provider_dependency_key_autoregisters_inner_dependency() -> None:
    container = Container(
        default_lifetime=Lifetime.TRANSIENT, missing_policy=MissingPolicy.REGISTER_ROOT
    )

    provider = container.resolve(AsyncProvider[_AutoProviderDependency])
    first = await provider()
    second = await provider()

    assert isinstance(first, _AutoProviderDependency)
    assert isinstance(second, _AutoProviderDependency)
    assert first is not second


def test_resolve_provider_dependency_key_uses_existing_registration_without_recompile() -> None:
    container = Container(
        default_lifetime=Lifetime.TRANSIENT, missing_policy=MissingPolicy.REGISTER_ROOT
    )
    container.add(_AutoProviderDependency)
    container.compile()
    graph_revision_before = container._graph_revision

    provider = container.resolve(Provider[_AutoProviderDependency])
    resolved = provider()

    assert isinstance(resolved, _AutoProviderDependency)
    assert container._graph_revision == graph_revision_before


def test_resolve_provider_dependency_key_recompiles_when_inner_dependency_is_autoregistered() -> (
    None
):
    container = Container(
        default_lifetime=Lifetime.TRANSIENT, missing_policy=MissingPolicy.REGISTER_ROOT
    )
    previous_resolver = container.compile()

    provider = container.resolve(Provider[_AutoProviderDependency])
    resolved = provider()

    assert isinstance(resolved, _AutoProviderDependency)
    assert container._root_resolver is not None
    assert container._root_resolver is not previous_resolver


def test_resolve_reraises_when_missing_dependency_cannot_be_autoregistered() -> None:
    container = Container(missing_policy=MissingPolicy.REGISTER_ROOT)

    with pytest.raises(DIWireDependencyNotRegisteredError):
        container.resolve(str)


@pytest.mark.asyncio
async def test_aresolve_provider_dependency_key_autoregisters_then_reuses_compilation() -> None:
    container = Container(
        default_lifetime=Lifetime.TRANSIENT, missing_policy=MissingPolicy.REGISTER_ROOT
    )

    first_provider = await container.aresolve(Provider[_AutoProviderDependency])
    second_provider = await container.aresolve(Provider[_AutoProviderDependency])
    first = first_provider()
    second = second_provider()

    assert isinstance(first, _AutoProviderDependency)
    assert isinstance(second, _AutoProviderDependency)
    assert first is not second


@pytest.mark.asyncio
async def test_aresolve_autoregisters_on_miss_and_reraises_when_graph_unchanged() -> None:
    container = Container(
        missing_policy=MissingPolicy.REGISTER_RECURSIVE,
        dependency_registration_policy=DependencyRegistrationPolicy.REGISTER_RECURSIVE,
    )

    resolved = await container.aresolve(ResolveRoot)

    assert isinstance(resolved, ResolveRoot)
    with pytest.raises(DIWireDependencyNotRegisteredError):
        await container.aresolve(str)


def test_ensure_autoregistration_short_circuits_for_disabled_and_open_generic() -> None:
    strict_container = Container(
        missing_policy=MissingPolicy.ERROR,
        dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
    )

    strict_container._ensure_autoregistration(DirectDependency)

    assert strict_container._providers_registrations.find_by_type(DirectDependency) is None

    container = Container(missing_policy=MissingPolicy.REGISTER_ROOT)
    container.add_factory(_build_open_autoreg_dependency, provides=_OpenAutoregDependency)

    container._ensure_autoregistration(_OpenAutoregDependency[int])

    assert container._providers_registrations.find_by_type(_OpenAutoregDependency[int]) is None


def test_ensure_autoregistration_normalizes_non_component_annotated_dependency_key() -> None:
    container = Container(missing_policy=MissingPolicy.REGISTER_ROOT)

    container._ensure_autoregistration(Annotated[DirectDependency, "plain-metadata"])

    assert container._providers_registrations.find_by_type(DirectDependency) is not None


def test_infer_dependency_scope_level_reuses_normalized_cache_entry() -> None:
    container = Container()
    cache: dict[Any, int] = {DirectDependency: Scope.APP.level}

    inferred = container._infer_dependency_scope_level(
        dependency=Annotated[DirectDependency, "plain-metadata"],
        cache=cache,
        in_progress=set(),
    )

    assert inferred == Scope.APP.level
    assert cache[Annotated[DirectDependency, "plain-metadata"]] == Scope.APP.level


def test_is_registered_in_resolver_uses_normalized_dependency_fallbacks() -> None:
    container = Container()
    container.add(DirectDependency)

    class _ResolverWithChecker:
        def _is_registered_dependency(self, dependency: Any) -> bool:
            return dependency is DirectDependency

    class _ResolverWithoutChecker:
        pass

    dependency = Annotated[DirectDependency, "plain-metadata"]

    assert container._is_registered_in_resolver(
        resolver=cast("Any", _ResolverWithChecker()),
        dependency=dependency,
    )
    assert container._is_registered_in_resolver(
        resolver=cast("Any", _ResolverWithoutChecker()),
        dependency=dependency,
    )


def test_is_registered_in_resolver_uses_normalized_open_generic_match_fallback() -> None:
    container = Container()
    container.add_factory(_build_open_autoreg_dependency, provides=_OpenAutoregDependency)

    assert container._is_registered_in_resolver(
        resolver=cast("Any", object()),
        dependency=Annotated[_OpenAutoregDependency[int], "plain-metadata"],
    )


def test_extract_provider_inner_dependency_fast_ignores_non_provider_metadata() -> None:
    container = Container()
    dependency = Annotated[DirectDependency, "plain-metadata"]

    assert container._extract_provider_inner_dependency_fast(dependency) is None


def test_resolve_autoregisters_settings_like_dependency_as_root_singleton(monkeypatch: Any) -> None:
    class _SettingsLikeDependency:
        value: str = "settings"

    monkeypatch.setattr(
        "diwire._internal.container.is_pydantic_settings_subclass",
        lambda candidate: candidate is _SettingsLikeDependency,
    )

    container = Container(missing_policy=MissingPolicy.REGISTER_ROOT)

    first = container.resolve(_SettingsLikeDependency)
    second = container.resolve(_SettingsLikeDependency)

    settings_spec = container._providers_registrations.get_by_type(_SettingsLikeDependency)
    assert first is second
    assert settings_spec.factory is not None
    assert settings_spec.concrete_type is None
    assert settings_spec.lifetime is Lifetime.SCOPED
    assert settings_spec.scope is Scope.APP


def test_resolve_autoregisters_pydantic_settings_as_singleton_factory() -> None:
    if pydantic_settings_base is None:
        pytest.skip("pydantic_settings is unavailable")

    container = Container(missing_policy=MissingPolicy.REGISTER_ROOT)

    first = container.resolve(PydanticSettingsDependency)
    second = container.resolve(PydanticSettingsDependency)

    settings_spec = container._providers_registrations.get_by_type(PydanticSettingsDependency)
    assert first is second
    assert settings_spec.factory is not None
    assert settings_spec.concrete_type is None
    assert settings_spec.lifetime is Lifetime.SCOPED
    assert settings_spec.scope is Scope.APP


def test_dependency_autoregistration_registers_pydantic_settings_as_root_singleton() -> None:
    if pydantic_settings_base is None:
        pytest.skip("pydantic_settings is unavailable")

    container = Container(
        dependency_registration_policy=DependencyRegistrationPolicy.REGISTER_RECURSIVE
    )

    container.add(
        RootWithPydanticSettingsDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    settings_spec = container._providers_registrations.get_by_type(PydanticSettingsDependency)
    assert settings_spec.factory is not None
    assert settings_spec.concrete_type is None
    assert settings_spec.lifetime is Lifetime.SCOPED
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

        container = Container(missing_policy=MissingPolicy.REGISTER_ROOT)
        first = container.resolve(PydanticV1SettingsDependency)
        second = container.resolve(PydanticV1SettingsDependency)

    settings_spec = container._providers_registrations.get_by_type(PydanticV1SettingsDependency)
    assert first is second
    assert settings_spec.factory is not None
    assert settings_spec.concrete_type is None
    assert settings_spec.lifetime is Lifetime.SCOPED
    assert settings_spec.scope is Scope.APP


def test_concrete_registration_autoregisters_namedtuple_class_dependencies() -> None:
    class NamedTupleRoot(NamedTuple):
        dependency: NamedTupleFrameworkDependency

    container = Container()

    container.add(
        NamedTupleRoot,
        dependency_registration_policy=DependencyRegistrationPolicy.REGISTER_RECURSIVE,
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

    container.add(
        MsgspecRoot,
        dependency_registration_policy=DependencyRegistrationPolicy.REGISTER_RECURSIVE,
    )

    dependency_spec = container._providers_registrations.find_by_type(
        MsgspecFrameworkDependency,
    )
    assert dependency_spec is not None
    assert dependency_spec.concrete_type is MsgspecFrameworkDependency


def test_concrete_registration_autoregisters_pydantic_basemodel_v2_dependencies() -> None:
    pydantic_module = pytest.importorskip("pydantic")
    base_model_type = cast("type[Any]", pydantic_module.BaseModel)
    config_dict = cast("Any", pydantic_module.ConfigDict)

    class PydanticRoot(base_model_type):
        model_config = config_dict(arbitrary_types_allowed=True)
        dependency: PydanticFrameworkDependency

    container = Container()

    container.add(
        PydanticRoot,
        dependency_registration_policy=DependencyRegistrationPolicy.REGISTER_RECURSIVE,
    )

    dependency_spec = container._providers_registrations.find_by_type(
        PydanticFrameworkDependency,
    )
    assert dependency_spec is not None
    assert dependency_spec.concrete_type is PydanticFrameworkDependency
