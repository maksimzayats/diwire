"""Async function injection with FromDI.

Demonstrates how to use FromDI with async functions.
The resolved function becomes an AsyncInjected wrapper that
automatically resolves dependencies on each call.
"""

import asyncio
from typing import Annotated

from diwire import Container, FromDI, Lifetime


# Services
class UserRepository:
    async def get_user(self, user_id: int) -> dict:
        await asyncio.sleep(0.01)
        return {"id": user_id, "name": f"User {user_id}"}


class EmailService:
    async def send_email(self, to: str, subject: str) -> bool:
        await asyncio.sleep(0.01)
        print(f"    Sent email to {to}: {subject}")
        return True


class Logger:
    def log(self, message: str) -> None:
        print(f"    [LOG] {message}")


# Async handler function with injected dependencies
async def get_user_handler(
    user_repo: Annotated[UserRepository, FromDI()],
    logger: Annotated[Logger, FromDI()],
    user_id: int,  # Regular parameter - not injected
) -> dict:
    """Async handler with mixed injected and regular parameters."""
    logger.log(f"Fetching user {user_id}")
    user = await user_repo.get_user(user_id)
    logger.log(f"Found user: {user['name']}")
    return user


async def send_welcome_email(
    user_repo: Annotated[UserRepository, FromDI()],
    email_service: Annotated[EmailService, FromDI()],
    user_id: int,
) -> bool:
    """Another async handler demonstrating multiple async deps."""
    user = await user_repo.get_user(user_id)
    return await email_service.send_email(
        to=f"{user['name'].lower().replace(' ', '.')}@example.com",
        subject="Welcome!",
    )


async def main() -> None:
    container = Container()

    # Register services
    container.register(UserRepository, lifetime=Lifetime.SINGLETON)
    container.register(EmailService, lifetime=Lifetime.SINGLETON)
    container.register(Logger, lifetime=Lifetime.SINGLETON)

    # Resolve async function - returns AsyncInjected wrapper
    get_user = await container.aresolve(get_user_handler)
    print(f"Resolved handler type: {type(get_user)}")

    # Call the injected function - dependencies resolved automatically
    print("\nCalling get_user_handler(user_id=42):")
    user = await get_user(user_id=42)
    print(f"  Result: {user}")

    # Resolve and call another handler
    send_email = await container.aresolve(send_welcome_email)
    print("\nCalling send_welcome_email(user_id=42):")
    success = await send_email(user_id=42)
    print(f"  Success: {success}")

    # The injected function's signature excludes FromDI params
    import inspect

    sig = inspect.signature(get_user)
    print(f"\nInjected function signature: {sig}")
    print("  (FromDI parameters are hidden from the signature)")


if __name__ == "__main__":
    asyncio.run(main())
