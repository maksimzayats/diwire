"""Injected Marker for Function Injection.

Demonstrates how to mark function parameters for dependency injection
using Annotated[T, Injected()].
"""

from dataclasses import dataclass
from typing import Annotated

from diwire import Container, Injected


@dataclass
class EmailService:
    """Service for sending emails."""

    smtp_host: str = "smtp.example.com"

    def send(self, to: str, subject: str) -> str:
        return f"Email sent to {to}: {subject} (via {self.smtp_host})"


@dataclass
class Logger:
    """Simple logger service."""

    def log(self, message: str) -> None:
        print(f"[LOG] {message}")


def send_welcome_email(
    email_service: Annotated[EmailService, Injected()],
    logger: Annotated[Logger, Injected()],
    user_email: str,
    user_name: str,
) -> str:
    """Send a welcome email to a new user.

    Parameters marked with Injected() are injected by the container.
    Regular parameters (user_email, user_name) must be provided by caller.
    """
    logger.log(f"Sending welcome email to {user_name}")
    return email_service.send(user_email, f"Welcome, {user_name}!")


def main() -> None:
    container = Container()

    # Register services
    container.register(EmailService, instance=EmailService(smtp_host="mail.company.com"))
    container.register(Logger)

    # Resolve the function - returns an InjectedFunction wrapper
    send_email = container.resolve(send_welcome_email)

    print(f"Resolved function type: {type(send_email)}")
    print(f"Function name preserved: {send_email}")
    print()

    # Call the function - only provide non-injected parameters
    result = send_email(user_email="alice@example.com", user_name="Alice")
    print(f"\nResult: {result}")

    # Keyword arguments are recommended for clarity
    result2 = send_email(user_email="bob@example.com", user_name="Bob")
    print(f"Result: {result2}")


if __name__ == "__main__":
    main()
