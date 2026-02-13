"""Focused example: strict-mode entrypoint rebind with use_resolver_context=False."""

from __future__ import annotations

from diwire import Container


def _bound_self(method: object) -> object | None:
    return getattr(method, "__self__", None)


def main() -> None:
    container = Container(
        autoregister_concrete_types=False,
        autoregister_dependencies=False,
        use_resolver_context=False,
    )
    container.add_instance("legacy", provides=str)

    compiled = container.compile()
    print(f"rebind_enabled={_bound_self(container.resolve) is compiled}")  # => rebind_enabled=True


if __name__ == "__main__":
    main()
