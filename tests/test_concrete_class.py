"""Tests for the 'concrete_class' parameter in Container.register()."""

from abc import ABC, abstractmethod
from typing import Annotated, Protocol

import pytest

from diwire.container import Container
from diwire.exceptions import DIWireConcreteClassRequiresClassError
from diwire.service_key import Component
from diwire.types import Lifetime


class TestConcreteClassBasic:
    """Test basic 'concrete_class' functionality."""

    def test_register_interface_with_concrete_class(self, container: Container) -> None:
        """Register an interface with a concrete implementation class."""

        class IRepository(ABC):
            @abstractmethod
            def get(self) -> str: ...

        class ConcreteRepository(IRepository):
            def get(self) -> str:
                return "data"

        container.register(IRepository, concrete_class=ConcreteRepository)
        result = container.resolve(IRepository)

        assert isinstance(result, ConcreteRepository)
        assert result.get() == "data"

    def test_register_protocol_with_concrete_class(self, container: Container) -> None:
        """Register a Protocol with a concrete implementation class."""

        class IService(Protocol):
            def execute(self) -> str: ...

        class ConcreteService:
            def execute(self) -> str:
                return "executed"

        container.register(IService, concrete_class=ConcreteService)
        result = container.resolve(IService)

        assert isinstance(result, ConcreteService)
        assert result.execute() == "executed"

    def test_resolve_by_interface_not_concrete(self, container: Container) -> None:
        """Resolving by interface returns the concrete implementation."""

        class ILogger(ABC):
            @abstractmethod
            def log(self, msg: str) -> None: ...

        class FileLogger(ILogger):
            def log(self, msg: str) -> None:
                pass

        container.register(ILogger, concrete_class=FileLogger)

        # Should be able to resolve by interface
        logger = container.resolve(ILogger)
        assert isinstance(logger, FileLogger)


class TestConcreteClassWithFactory:
    """Test 'concrete_class' with factory functions."""

    def test_factory_with_interface_key(self, container: Container) -> None:
        """Factory can be registered under an interface key."""

        class IDatabase(ABC):
            @abstractmethod
            def connect(self) -> str: ...

        class PostgresDatabase(IDatabase):
            def connect(self) -> str:
                return "postgres"

        def create_database() -> PostgresDatabase:
            return PostgresDatabase()

        container.register(
            IDatabase,
            factory=create_database,
        )

        result = container.resolve(IDatabase)
        assert isinstance(result, PostgresDatabase)
        assert result.connect() == "postgres"

    def test_factory_class_with_interface_key(self, container: Container) -> None:
        """Factory class can be registered under an interface key."""

        class ICache(ABC):
            @abstractmethod
            def get(self, key: str) -> str | None: ...

        class RedisCache(ICache):
            def get(self, key: str) -> str | None:
                return None

        class RedisCacheFactory:
            def __call__(self) -> RedisCache:
                return RedisCache()

        container.register(
            ICache,
            factory=RedisCacheFactory,
        )

        result = container.resolve(ICache)
        assert isinstance(result, RedisCache)


class TestConcreteClassWithInstance:
    """Test 'concrete_class' with pre-created instances."""

    def test_instance_registered_under_interface(self, container: Container) -> None:
        """Pre-created instance can be registered under an interface."""

        class IConfig(ABC):
            @abstractmethod
            def get_value(self) -> str: ...

        class AppConfig(IConfig):
            def __init__(self, value: str) -> None:
                self._value = value

            def get_value(self) -> str:
                return self._value

        config = AppConfig("production")
        container.register(IConfig, instance=config)

        result = container.resolve(IConfig)
        assert result is config  # type: ignore[comparison-overlap]
        assert result.get_value() == "production"  # type: ignore[attr-defined]


class TestConcreteClassWithLifetime:
    """Test 'concrete_class' with different lifetimes."""

    def test_concrete_class_transient_lifetime(self, container: Container) -> None:
        """Transient lifetime creates new instance each time."""

        class IService(Protocol):
            pass

        class TransientService(IService):
            pass

        container.register(
            IService,
            concrete_class=TransientService,
            lifetime=Lifetime.TRANSIENT,
        )

        result1 = container.resolve(IService)
        result2 = container.resolve(IService)

        assert isinstance(result1, TransientService)
        assert isinstance(result2, TransientService)
        assert result1 is not result2

    def test_concrete_class_singleton_lifetime(self, container: Container) -> None:
        """Singleton lifetime returns same instance."""

        class IService(Protocol):
            pass

        class SingletonService(IService):
            pass

        container.register(
            IService,
            concrete_class=SingletonService,
            lifetime=Lifetime.SINGLETON,
        )

        result1 = container.resolve(IService)
        result2 = container.resolve(IService)

        assert isinstance(result1, SingletonService)
        assert result1 is result2

    def test_concrete_class_scoped_singleton_lifetime(self, container: Container) -> None:
        """Scoped singleton lifetime returns same instance within scope."""

        class IService(Protocol):
            pass

        class ScopedService(IService):
            pass

        container.register(
            IService,
            concrete_class=ScopedService,
            lifetime=Lifetime.SCOPED,
            scope="request",
        )

        with container.enter_scope("request") as scope:
            result1 = scope.resolve(IService)
            result2 = scope.resolve(IService)

            assert isinstance(result1, ScopedService)
            assert result1 is result2

        # New scope creates new instance
        with container.enter_scope("request") as scope:
            result3 = scope.resolve(IService)
            assert result3 is not result1


class TestConcreteClassWithDependencies:
    """Test 'concrete_class' with dependencies in concrete class."""

    def test_concrete_with_dependencies(self, container: Container) -> None:
        """Concrete class dependencies are resolved correctly."""

        class ILogger(ABC):
            @abstractmethod
            def log(self, msg: str) -> None: ...

        class IRepository(ABC):
            @abstractmethod
            def save(self, data: str) -> None: ...

        class ConsoleLogger(ILogger):
            def log(self, msg: str) -> None:
                pass

        class DatabaseRepository(IRepository):
            def __init__(self, logger: ILogger) -> None:
                self.logger = logger

            def save(self, data: str) -> None:
                self.logger.log(f"Saving: {data}")

        container.register(ILogger, concrete_class=ConsoleLogger, lifetime=Lifetime.SINGLETON)
        container.register(IRepository, concrete_class=DatabaseRepository)

        repo = container.resolve(IRepository)

        assert isinstance(repo, DatabaseRepository)
        assert isinstance(repo.logger, ConsoleLogger)

    def test_concrete_with_mixed_dependencies(self, container: Container) -> None:
        """Concrete class with both interface and concrete dependencies."""

        class ILogger(ABC):
            @abstractmethod
            def log(self, msg: str) -> None: ...

        class ConsoleLogger(ILogger):
            def log(self, msg: str) -> None:
                pass

        class Config:
            def __init__(self) -> None:
                self.debug = True

        class Service:
            def __init__(self, logger: ILogger, config: Config) -> None:
                self.logger = logger
                self.config = config

        class IService(Protocol):
            logger: ILogger
            config: Config

        container.register(ILogger, concrete_class=ConsoleLogger, lifetime=Lifetime.SINGLETON)
        container.register(Config, lifetime=Lifetime.SINGLETON)
        container.register(IService, concrete_class=Service)

        service = container.resolve(IService)

        assert isinstance(service, Service)
        assert isinstance(service.logger, ConsoleLogger)
        assert isinstance(service.config, Config)


class TestConcreteClassWithComponent:
    """Test 'concrete_class' with named components."""

    def test_multiple_implementations_with_component(self, container: Container) -> None:
        """Register multiple implementations of same interface with different components."""

        class ICache(ABC):
            @abstractmethod
            def get(self, key: str) -> str | None: ...

        class MemoryCache(ICache):
            def get(self, key: str) -> str | None:
                return "memory"

        class RedisCache(ICache):
            def get(self, key: str) -> str | None:
                return "redis"

        # Use Annotated with Component for named registrations
        memory_cache_type = Annotated[ICache, Component("memory")]
        redis_cache_type = Annotated[ICache, Component("redis")]

        container.register(memory_cache_type, concrete_class=MemoryCache)
        container.register(redis_cache_type, concrete_class=RedisCache)

        memory_cache = container.resolve(memory_cache_type)
        redis_cache = container.resolve(redis_cache_type)

        assert isinstance(memory_cache, MemoryCache)
        assert isinstance(redis_cache, RedisCache)
        assert memory_cache.get("key") == "memory"
        assert redis_cache.get("key") == "redis"


class TestConcreteClassErrors:
    """Test error handling for 'concrete_class' parameter."""

    def test_concrete_class_requires_class_type(
        self,
        container: Container,
    ) -> None:
        """Error when 'concrete_class' is not a class type."""

        class IService(Protocol):
            pass

        with pytest.raises(DIWireConcreteClassRequiresClassError) as exc_info:
            container.register(IService, concrete_class="not_a_class")  # type: ignore[call-overload]

        assert exc_info.value.concrete_class == "not_a_class"
        assert "must be a class" in str(exc_info.value)


class TestConcreteClassAsync:
    """Test 'concrete_class' with async resolution."""

    @pytest.mark.anyio
    async def test_async_resolve_with_concrete_class(self, container: Container) -> None:
        """Async resolution works with concrete_class parameter."""

        class IService(ABC):
            @abstractmethod
            def get_data(self) -> str: ...

        class AsyncService(IService):
            def get_data(self) -> str:
                return "async_data"

        container.register(IService, concrete_class=AsyncService, lifetime=Lifetime.SINGLETON)

        result = await container.aresolve(IService)

        assert isinstance(result, AsyncService)
        assert result.get_data() == "async_data"

    @pytest.mark.anyio
    async def test_async_factory_with_interface_key(self, container: Container) -> None:
        """Async factory can be registered under an interface key."""

        class IDatabase(ABC):
            @abstractmethod
            def query(self) -> str: ...

        class AsyncDatabase(IDatabase):
            def query(self) -> str:
                return "result"

        async def create_database() -> AsyncDatabase:
            return AsyncDatabase()

        container.register(
            IDatabase,
            factory=create_database,
        )

        result = await container.aresolve(IDatabase)

        assert isinstance(result, AsyncDatabase)
        assert result.query() == "result"


class TestConcreteClassCompilation:
    """Test 'concrete_class' with container compilation."""

    def test_compiled_container_resolves_interface(self, container: Container) -> None:
        """Compiled container correctly resolves interfaces."""

        class IService(ABC):
            @abstractmethod
            def execute(self) -> str: ...

        class CompiledService(IService):
            def execute(self) -> str:
                return "compiled"

        container.register(IService, concrete_class=CompiledService, lifetime=Lifetime.SINGLETON)
        container.compile()

        result = container.resolve(IService)

        assert isinstance(result, CompiledService)
        assert result.execute() == "compiled"

    def test_compiled_container_with_dependencies(self, container: Container) -> None:
        """Compiled container resolves interface dependencies correctly."""

        class ILogger(Protocol):
            pass

        class IService(Protocol):
            pass

        class Logger(ILogger):
            pass

        class Service(IService):
            def __init__(self, logger: ILogger) -> None:
                self.logger = logger

        container.register(ILogger, concrete_class=Logger, lifetime=Lifetime.SINGLETON)
        container.register(IService, concrete_class=Service)
        container.compile()

        result = container.resolve(IService)

        assert isinstance(result, Service)
        assert isinstance(result.logger, Logger)
