"""Interface registration pattern using the 'concrete_class' parameter.

This example demonstrates how to program to interfaces/abstractions
rather than concrete implementations using diwire's 'concrete_class' parameter.
"""

from abc import ABC, abstractmethod
from typing import Protocol

from diwire import Container, Lifetime


# Define interfaces/abstractions
class ILogger(Protocol):
    """Protocol for logging services."""

    def log(self, message: str) -> None: ...


class IRepository(ABC):
    """Abstract base class for data repositories."""

    @abstractmethod
    def save(self, data: str) -> None: ...

    @abstractmethod
    def load(self) -> str: ...


class IEmailService(ABC):
    """Abstract base class for email services."""

    @abstractmethod
    def send(self, to: str, subject: str, body: str) -> None: ...


# Concrete implementations
class ConsoleLogger:
    """Console-based logger implementation."""

    def log(self, message: str) -> None:
        print(f"[LOG] {message}")


class FileRepository(IRepository):
    """File-based repository implementation."""

    def __init__(self, logger: ILogger) -> None:
        self.logger = logger
        self._data = ""

    def save(self, data: str) -> None:
        self.logger.log(f"Saving data: {data}")
        self._data = data

    def load(self) -> str:
        self.logger.log("Loading data")
        return self._data


class SmtpEmailService(IEmailService):
    """SMTP-based email service implementation."""

    def __init__(self, logger: ILogger) -> None:
        self.logger = logger

    def send(self, to: str, subject: str, body: str) -> None:
        self.logger.log(f"Sending email to {to}: {subject}")


# Application service that depends on interfaces
class UserService:
    """User service that depends on abstract interfaces."""

    def __init__(
        self,
        repository: IRepository,
        email_service: IEmailService,
        logger: ILogger,
    ) -> None:
        self.repository = repository
        self.email_service = email_service
        self.logger = logger

    def create_user(self, username: str, email: str) -> None:
        self.logger.log(f"Creating user: {username}")
        self.repository.save(f"user:{username}")
        self.email_service.send(email, "Welcome!", f"Hello {username}!")


def main() -> None:
    # Create container
    container = Container()

    # Register concrete implementations for interfaces
    # The key is the interface, 'concrete_class' specifies the implementation
    container.register(
        ILogger,
        concrete_class=ConsoleLogger,
        lifetime=Lifetime.SINGLETON,
    )

    container.register(
        IRepository,
        concrete_class=FileRepository,
        lifetime=Lifetime.SINGLETON,
    )

    container.register(
        IEmailService,
        concrete_class=SmtpEmailService,
        lifetime=Lifetime.SINGLETON,
    )

    # UserService can be auto-registered since its dependencies
    # are all registered as interfaces

    # Resolve by interface type
    logger = container.resolve(ILogger)
    logger.log("Application starting...")

    # Resolve services that depend on interfaces
    user_service = container.resolve(UserService)
    user_service.create_user("john_doe", "john@example.com")

    # Verify the dependencies are properly injected
    repository = container.resolve(IRepository)
    print(f"Stored data: {repository.load()}")


if __name__ == "__main__":
    main()
