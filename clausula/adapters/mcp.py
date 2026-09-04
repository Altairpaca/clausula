from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from clausula.application import CoreRepository
from clausula.capabilities import (
    CapabilityPermissionError,
    CapabilityRegistry,
    build_core_registry,
)


class McpProfile(StrEnum):
    RESEARCH_READ = "research-read"
    PORTFOLIO_READ = "portfolio-read"
    ADVISOR = "advisor"
    ADMIN = "admin"


@dataclass(frozen=True, slots=True)
class McpTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    permissions: tuple[str, ...]
    confirmation_required: bool


PROFILE_PERMISSIONS: dict[McpProfile, frozenset[str]] = {
    McpProfile.RESEARCH_READ: frozenset({"research:read"}),
    McpProfile.PORTFOLIO_READ: frozenset(
        {
            "portfolio:read",
            "ledger:read",
            "market:read",
            "policy:read",
            "planning:read",
            "decision:read",
            "execution:read",
            "recommendation:read",
        }
    ),
    McpProfile.ADVISOR: frozenset(
        {
            "portfolio:read",
            "ledger:read",
            "market:read",
            "policy:read",
            "planning:read",
            "decision:read",
            "execution:read",
            "research:read",
            "research:write",
            "recommendation:create",
            "recommendation:read",
        }
    ),
    McpProfile.ADMIN: frozenset(
        {
            "ledger:read",
            "ledger:write",
            "portfolio:read",
            "portfolio:write",
            "market:read",
            "market:write",
            "policy:read",
            "policy:write",
            "planning:read",
            "planning:write",
            "decision:read",
            "decision:write",
            "execution:read",
            "execution:write",
            "research:read",
            "research:write",
            "network:read",
            "recommendation:create",
            "recommendation:read",
            "recommendation:write",
            "system:read",
            "system:export",
            "system:backup",
        }
    ),
}


class McpAdapter:
    """Project registry capabilities into profile-scoped structured tools."""

    def __init__(self, repository: CoreRepository):
        self.repository = repository
        self.registry = build_core_registry(repository)

    def list_tools(self, profile: McpProfile) -> list[McpTool]:
        allowed = PROFILE_PERMISSIONS[profile]
        tools = []
        for description in self.registry.describe():
            permissions = tuple(description["permissions"])
            if set(permissions) <= allowed:
                tools.append(
                    McpTool(
                        description["name"],
                        description["description"],
                        dict(description["input_schema"]),
                        dict(description["output_schema"]),
                        permissions,
                        description["confirmation_required"],
                    )
                )
        return tools

    def call(
        self,
        profile: McpProfile,
        name: str,
        arguments: dict[str, Any],
        *,
        agent_id: str = "anonymous-agent",
        confirmed: bool = False,
        dry_run: bool = False,
    ) -> Any:
        allowed = PROFILE_PERMISSIONS[profile]
        spec = self.registry.get(name)
        if not set(spec.permissions) <= allowed:
            raise CapabilityPermissionError(
                f"capability is not available to profile: {profile.value}"
            )
        try:
            result = self.registry.execute(
                name,
                arguments,
                permissions=allowed,
                confirmed=confirmed,
                dry_run=dry_run,
            )
        except Exception:
            self.repository.record_adapter_invocation(
                adapter="mcp",
                actor_type="agent",
                actor_id=agent_id,
                capability=name,
                side_effect=spec.side_effect.value,
                confirmed=confirmed,
                succeeded=False,
            )
            raise
        self.repository.record_adapter_invocation(
            adapter="mcp",
            actor_type="agent",
            actor_id=agent_id,
            capability=name,
            side_effect=spec.side_effect.value,
            confirmed=confirmed,
            succeeded=True,
        )
        return result
