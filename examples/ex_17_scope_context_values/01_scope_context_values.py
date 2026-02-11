"""Scope context values with FromContext[T].

This topic demonstrates:

1. Provider dependencies that read values from scope context.
2. Parent-to-child context visibility across nested scopes.
3. Child-scope override behavior for the same context key.
4. Direct resolver access via ``resolve(FromContext[T])``.
5. Missing context failure mode.
"""

from __future__ import annotations

from diwire import Container, FromContext, Lifetime, Scope
from diwire.exceptions import DIWireDependencyNotRegisteredError


class RequestValue:
    def __init__(self, value: int) -> None:
        self.value = value


class ActionValue:
    def __init__(self, value: int) -> None:
        self.value = value


class StepValue:
    def __init__(self, value: int) -> None:
        self.value = value


def build_request_value(value: FromContext[int]) -> RequestValue:
    return RequestValue(value=value)


def build_action_value(value: FromContext[int]) -> ActionValue:
    return ActionValue(value=value)


def build_step_value(value: FromContext[int]) -> StepValue:
    return StepValue(value=value)


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_factory(
        build_request_value,
        provides=RequestValue,
        scope=Scope.REQUEST,
        lifetime=Lifetime.TRANSIENT,
    )
    container.add_factory(
        build_action_value,
        provides=ActionValue,
        scope=Scope.ACTION,
        lifetime=Lifetime.TRANSIENT,
    )
    container.add_factory(
        build_step_value,
        provides=StepValue,
        scope=Scope.STEP,
        lifetime=Lifetime.TRANSIENT,
    )

    with container.enter_scope(Scope.REQUEST, context={int: 1}) as request_scope:
        request_value = request_scope.resolve(RequestValue).value
        with request_scope.enter_scope(Scope.ACTION) as action_scope:
            action_value = action_scope.resolve(ActionValue).value
            with action_scope.enter_scope(Scope.STEP, context={int: 2}) as step_scope:
                step_value = step_scope.resolve(StepValue).value
                request_value_from_step = step_scope.resolve(RequestValue).value
                direct_context = step_scope.resolve(FromContext[int])

    with container.enter_scope(Scope.REQUEST) as request_scope_without_context:
        try:
            request_scope_without_context.resolve(RequestValue)
        except DIWireDependencyNotRegisteredError as error:
            missing_context_error = type(error).__name__

    print(f"request_value={request_value}")  # => request_value=1
    print(f"action_inherits_parent={action_value}")  # => action_inherits_parent=1
    print(f"step_overrides_parent={step_value}")  # => step_overrides_parent=2
    print(f"request_stays_parent={request_value_from_step}")  # => request_stays_parent=1
    print(f"direct_from_context={direct_context}")  # => direct_from_context=2
    print(
        f"missing_context_error={missing_context_error}",
    )  # => missing_context_error=DIWireDependencyNotRegisteredError


if __name__ == "__main__":
    main()
