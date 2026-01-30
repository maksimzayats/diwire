"""Missing Dependency Detection.

Demonstrates DIWireMissingDependenciesError when a required dependency
cannot be resolved.
"""

from dataclasses import dataclass

from diwire import Container
from diwire.exceptions import DIWireMissingDependenciesError


class ExternalAPI:
    """An external API client that requires configuration."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key


@dataclass
class UserService:
    """Service that depends on ExternalAPI."""

    api: ExternalAPI


def main() -> None:
    # Disable auto-registration to see DIWireMissingDependenciesError
    container = Container(autoregister=False)

    # Only register UserService, not ExternalAPI
    container.register(UserService)

    print("Attempting to resolve service with missing dependency:")
    print("  UserService requires ExternalAPI, but ExternalAPI is not registered")
    print()

    try:
        container.resolve(UserService)
    except DIWireMissingDependenciesError as e:
        print("DIWireMissingDependenciesError caught!")
        print(f"  Service key: {e.service_key}")
        print(f"  Missing dependencies: {e.missing}")

    # With autoregister=True (default), simple classes would be auto-registered
    print("\nWith autoregister=True (default):")
    container_auto = Container(autoregister=True)
    container_auto.register(UserService)

    # Note: ExternalAPI still fails because it has a non-injectable 'api_key' param
    try:
        container_auto.resolve(UserService)
    except DIWireMissingDependenciesError as e:
        print(f"  Still fails: {e.missing}")
        print("  (ExternalAPI has 'api_key: str' which cannot be auto-resolved)")


if __name__ == "__main__":
    main()
