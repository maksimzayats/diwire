"""Focused example: nested scopes inherit context and child scopes can override keys."""

from __future__ import annotations

from diwire import Container, FromContext, Scope


def main() -> None:
    container = Container(autoregister_concrete_types=False)

    with (
        container.enter_scope(Scope.REQUEST, context={int: 1, str: "parent"}) as request_scope,
        request_scope.enter_scope(Scope.ACTION) as action_scope,
        action_scope.enter_scope(Scope.STEP, context={int: 2}) as step_scope,
    ):
        inherited_value = action_scope.resolve(FromContext[int])
        overridden_value = step_scope.resolve(FromContext[int])
        inherited_parent_key = step_scope.resolve(FromContext[str])

    print(f"action_inherits_parent={inherited_value}")  # => action_inherits_parent=1
    print(f"step_overrides_parent={overridden_value}")  # => step_overrides_parent=2
    print(
        f"step_inherits_other_parent_key={inherited_parent_key}"
    )  # => step_inherits_other_parent_key=parent


if __name__ == "__main__":
    main()
