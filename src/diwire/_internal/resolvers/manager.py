from diwire._internal.providers import ProvidersRegistrations
from diwire._internal.resolvers.assembly.compiler import ResolversAssemblyCompiler
from diwire._internal.resolvers.assembly.planner import validate_resolver_assembly_managed_scopes
from diwire._internal.resolvers.protocol import ResolverProtocol
from diwire._internal.scope import BaseScope


class ResolversManager:
    """Manager for dependency resolvers."""

    def __init__(self) -> None:
        self._assembly_compiler = ResolversAssemblyCompiler()

    def build_root_resolver(
        self,
        root_scope: BaseScope,
        registrations: ProvidersRegistrations,
    ) -> ResolverProtocol:
        """Get the root resolver for the given registrations.

        Generates the resolver code dynamically based on the provided registrations and root scope.

        Args:
            root_scope: Root scope used to initialize the resolver.
            registrations: Provider registrations used to build resolver instances or generated code.

        """
        validate_resolver_assembly_managed_scopes(root_scope=root_scope)
        return self._assembly_compiler.build_root_resolver(
            root_scope=root_scope,
            registrations=registrations,
        )
