# Examples

Each topic lives in a grouped folder named `ex_XX_<topic>/`.

- Main module (executed by harness): `01_<topic>.py`
- Focused modules (not executed by harness): `02_*.py`, `03_*.py`, etc.
  - These split concrete use-cases into small, runnable files.

- `ex_01_quickstart`: basic auto-wiring chain resolution
- `ex_02_registration_methods`: instance/concrete/factory/generator/context-manager/explicit deps
  - focused: `02_register_instance.py` ... `06_explicit_dependencies.py`
- `ex_03_lifetimes`: transient, singleton, scoped identity behavior
- `ex_04_scopes_and_cleanup`: scope transitions, mismatch, cleanup timing
  - focused: `02_scope_transitions.py` ... `05_singleton_cleanup.py`
- `ex_05_compilation`: compile cache and invalidation after mutation
- `ex_06_function_injection`: `Injected[T]`, signature filtering, overrides, scope auto-open, nested wrappers
  - focused: `02_function_injection_async_details.py` ... `06_nested_wrappers.py`
- `ex_07_named_components`: `Annotated[..., Component("...")]` resolution and injection
- `ex_08_open_generics`: open generics, overrides, specificity, validation, scoped mismatch
  - focused: `02_open_generics_constraints_details.py` ... `06_scoped_open_generics.py`
- `ex_09_autoregistration`: resolve-time and registration-time autoregistration behavior
  - focused: `02_resolve_chain.py` ... `05_uuid_special_type.py`
- `ex_10_container_context`: unbound errors, deferred replay, inject wrappers, rebinding
  - focused: `02_unbound_error.py` ... `05_rebind.py`
- `ex_11_lock_modes`: container lock mode defaults and provider overrides
- `ex_12_supported_frameworks`: dataclasses, NamedTuple, attrs, pydantic, msgspec
  - focused: `02_dataclass.py` ... `06_msgspec.py`
- `ex_13_pydantic_settings`: `BaseSettings` singleton auto-registration
- `ex_14_pytest_plugin`: subprocess pytest plugin check (with local `test_demo.py`)
- `ex_15_fastapi`: FastAPI request-scope injection via `TestClient`
- `ex_16_errors_and_troubleshooting`: representative error type examples
  - focused: `02_missing_dependency_error.py` ... `07_invalid_registration_error.py`

Run one example:

```bash
uv run python examples/ex_XX_<topic>/01_<topic>.py
```

Validate expected output markers for all examples:

```bash
uv run pytest tests/examples/test_examples_expected_output.py
```

Or run the full suite:

```bash
make test
```
