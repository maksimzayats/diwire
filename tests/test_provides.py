"""Tests for the 'provides' parameter in Container.register()."""

from abc import ABC, abstractmethod
from typing import Annotated, Protocol

import pytest

from diwire.container import Container
from diwire.exceptions import DIWireProvidesRequiresClassError
from diwire.service_key import Component
from diwire.types import Lifetime


class TestProvidesBasic:
    """Test basic 'provides' functionality."""

    def test_register_concrete_provides_interface(self, container: Container) -> None:
        """Register a concrete class that provides an interface."""

        class IRepository(ABC):
            @abstractmethod
            def get(self) -> str: ...

        class ConcreteRepository(IRepository):
            def get(self) -> str:
                return "data"

        container.register(ConcreteRepository, provides=IRepository)
        result = container.resolve(IRepository)

        assert isinstance(result, ConcreteRepository)
        assert result.get() == "data"

    def test_register_concrete_provides_protocol(self, container: Container) -> None:
        """Register a concrete class that provides a Protocol."""

        class IService(Protocol):
            def execute(self) -> str: ...

        class ConcreteService:
            def execute(self) -> str:
                return "executed"

        container.register(ConcreteService, provides=IService)
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

        container.register(FileLogger, provides=ILogger)

        # Should be able to resolve by interface
        logger = container.resolve(ILogger)
        assert isinstance(logger, FileLogger)


class TestProvidesWithFactory:
    """Test 'provides' with factory functions."""

    def test_factory_provides_interface(self, container: Container) -> None:
        """Factory can provide an interface implementation."""

        class IDatabase(ABC):
            @abstractmethod
            def connect(self) -> str: ...

        class PostgresDatabase(IDatabase):
            def connect(self) -> str:
                return "postgres"

        def create_database() -> PostgresDatabase:
            return PostgresDatabase()

        container.register(
            PostgresDatabase,
            factory=create_database,
            provides=IDatabase,
        )

        result = container.resolve(IDatabase)
        assert isinstance(result, PostgresDatabase)
        assert result.connect() == "postgres"

    def test_factory_class_provides_interface(self, container: Container) -> None:
        """Factory class can provide an interface implementation."""

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
            RedisCache,
            factory=RedisCacheFactory,
            provides=ICache,
        )

        result = container.resolve(ICache)
        assert isinstance(result, RedisCache)


class TestProvidesWithInstance:
    """Test 'provides' with pre-created instances."""

    def test_instance_provides_interface(self, container: Container) -> None:
        """Pre-created instance can provide an interface."""

        class IConfig(ABC):
            @abstractmethod
            def get_value(self) -> str: ...

        class AppConfig(IConfig):
            def __init__(self, value: str) -> None:
                self._value = value

            def get_value(self) -> str:
                return self._value

        config = AppConfig("production")
        container.register(AppConfig, instance=config, provides=IConfig)

        result = container.resolve(IConfig)
        assert result is config
        assert result.get_value() == "production"


class TestProvidesWithLifetime:
    """Test 'provides' with different lifetimes."""

    def test_provides_transient_lifetime(self, container: Container) -> None:
        """Transient lifetime creates new instance each time."""

        class IService(Protocol):
            pass

        class TransientService(IService):
            pass

        container.register(
            TransientService,
            provides=IService,
            lifetime=Lifetime.TRANSIENT,
        )

        result1 = container.resolve(IService)
        result2 = container.resolve(IService)

        assert isinstance(result1, TransientService)
        assert isinstance(result2, TransientService)
        assert result1 is not result2

    def test_provides_singleton_lifetime(self, container: Container) -> None:
        """Singleton lifetime returns same instance."""

        class IService(Protocol):
            pass

        class SingletonService(IService):
            pass

        container.register(
            SingletonService,
            provides=IService,
            lifetime=Lifetime.SINGLETON,
        )

        result1 = container.resolve(IService)
        result2 = container.resolve(IService)

        assert isinstance(result1, SingletonService)
        assert result1 is result2

    def test_provides_scoped_singleton_lifetime(self, container: Container) -> None:
        """Scoped singleton lifetime returns same instance within scope."""

        class IService(Protocol):
            pass

        class ScopedService(IService):
            pass

        container.register(
            ScopedService,
            provides=IService,
            lifetime=Lifetime.SCOPED_SINGLETON,
            scope="request",
        )

        with container.start_scope("request") as scope:
            result1 = scope.resolve(IService)
            result2 = scope.resolve(IService)

            assert isinstance(result1, ScopedService)
            assert result1 is result2

        # New scope creates new instance
        with container.start_scope("request") as scope:
            result3 = scope.resolve(IService)
            assert result3 is not result1


class TestProvidesWithDependencies:
    """Test 'provides' with dependencies in concrete class."""

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

        container.register(ConsoleLogger, provides=ILogger, lifetime=Lifetime.SINGLETON)
        container.register(DatabaseRepository, provides=IRepository)

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

        container.register(ConsoleLogger, provides=ILogger, lifetime=Lifetime.SINGLETON)
        container.register(Config, lifetime=Lifetime.SINGLETON)
        container.register(Service, provides=IService)

        service = container.resolve(IService)

        assert isinstance(service, Service)
        assert isinstance(service.logger, ConsoleLogger)
        assert isinstance(service.config, Config)


class TestProvidesWithComponent:
    """Test 'provides' with named components."""

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

        container.register(MemoryCache, provides=memory_cache_type)
        container.register(RedisCache, provides=redis_cache_type)

        memory_cache = container.resolve(memory_cache_type)
        redis_cache = container.resolve(redis_cache_type)

        assert isinstance(memory_cache, MemoryCache)
        assert isinstance(redis_cache, RedisCache)
        assert memory_cache.get("key") == "memory"
        assert redis_cache.get("key") == "redis"


class TestProvidesErrors:
    """Test error handling for 'provides' parameter."""

    def test_provides_requires_class_when_no_factory_or_instance(
        self,
        container: Container,
    ) -> None:
        """Error when 'provides' used with non-class key and no factory/instance."""

        class IService(Protocol):
            pass

        with pytest.raises(DIWireProvidesRequiresClassError) as exc_info:
            container.register("not_a_class", provides=IService)

        assert exc_info.value.key == "not_a_class"
        assert exc_info.value.provides is IService
        assert "must be a class" in str(exc_info.value)

    def test_provides_allows_non_class_with_factory(self, container: Container) -> None:
        """Non-class key is allowed when factory is provided."""

        class IService(ABC):
            @abstractmethod
            def run(self) -> str: ...

        class ConcreteService(IService):
            def run(self) -> str:
                return "running"

        def create_service() -> ConcreteService:
            return ConcreteService()

        # Should not raise - factory is provided
        container.register("my_service", factory=create_service, provides=IService)

        result = container.resolve(IService)
        assert isinstance(result, ConcreteService)

    def test_provides_allows_non_class_with_instance(self, container: Container) -> None:
        """Non-class key is allowed when instance is provided."""

        class IService(ABC):
            @abstractmethod
            def run(self) -> str: ...

        class ConcreteService(IService):
            def run(self) -> str:
                return "running"

        instance = ConcreteService()

        # Should not raise - instance is provided
        container.register("my_service", instance=instance, provides=IService)

        result = container.resolve(IService)
        assert result is instance


class TestProvidesAsync:
    """Test 'provides' with async resolution."""

    @pytest.mark.anyio
    async def test_async_resolve_provides_interface(self, container: Container) -> None:
        """Async resolution works with provides parameter."""

        class IService(ABC):
            @abstractmethod
            def get_data(self) -> str: ...

        class AsyncService(IService):
            def get_data(self) -> str:
                return "async_data"

        container.register(AsyncService, provides=IService, lifetime=Lifetime.SINGLETON)

        result = await container.aresolve(IService)

        assert isinstance(result, AsyncService)
        assert result.get_data() == "async_data"

    @pytest.mark.anyio
    async def test_async_factory_provides_interface(self, container: Container) -> None:
        """Async factory can provide an interface implementation."""

        class IDatabase(ABC):
            @abstractmethod
            def query(self) -> str: ...

        class AsyncDatabase(IDatabase):
            def query(self) -> str:
                return "result"

        async def create_database() -> AsyncDatabase:
            return AsyncDatabase()

        container.register(
            AsyncDatabase,
            factory=create_database,
            provides=IDatabase,
        )

        result = await container.aresolve(IDatabase)

        assert isinstance(result, AsyncDatabase)
        assert result.query() == "result"


class TestProvidesCompilation:
    """Test 'provides' with container compilation."""

    def test_compiled_container_resolves_interface(self, container: Container) -> None:
        """Compiled container correctly resolves interfaces."""

        class IService(ABC):
            @abstractmethod
            def execute(self) -> str: ...

        class CompiledService(IService):
            def execute(self) -> str:
                return "compiled"

        container.register(CompiledService, provides=IService, lifetime=Lifetime.SINGLETON)
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

        container.register(Logger, provides=ILogger, lifetime=Lifetime.SINGLETON)
        container.register(Service, provides=IService)
        container.compile()

        result = container.resolve(IService)

        assert isinstance(result, Service)
        assert isinstance(result.logger, Logger)
