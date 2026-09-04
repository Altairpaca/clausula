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
            "equity:read",
            "accounting:read",
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
            "equity:read",
            "equity:write",
            "accounting:read",
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
            "equity:read",
            "equity:write",
            "accounting:read",
            "accounting:write",
            "system:read",
            "system:export",
            "system:backup",
        }
    ),
}


class McpAdapter:
    """Profile-bound invocation adapter plus optional read-only tool discovery.

    Invocation authority is constructor-bound: a transport creates an adapter only
    after binding an authenticated client to a profile and actor identity. For
    compatibility, an unbound adapter may describe the tools visible to an
    explicitly requested profile; discovery is read-only and cannot be used to
    invoke anything. Confirmation remains host-controlled in all cases.
    """

    def __init__(
        self,
        repository: CoreRepository,
        *,
        profile: McpProfile | None = None,
        agent_id: str | None = None,
    ) -> None:
        self.repository = repository
        self.registry: CapabilityRegistry = build_core_registry(repository)
        if profile is None:
            if agent_id is not None and str(agent_id).strip():
                raise ValueError("agent_id requires a bound MCP profile")
            self.profile: McpProfile | None = None
            self.agent_id: str | None = None
            self.permissions = frozenset()
            return
        normalized_agent = str(agent_id or "").strip()
        if not normalized_agent:
            raise ValueError("agent_id cannot be empty")
        self.profile = McpProfile(profile)
        self.agent_id = normalized_agent
        self.permissions = PROFILE_PERMISSIONS[self.profile]

    def list_tools(self, profile: McpProfile | None = None) -> list[McpTool]:
        selected = self.profile if profile is None else McpProfile(profile)
        if selected is None:
            raise ValueError("profile is required for unbound MCP tool discovery")
        allowed = PROFILE_PERMISSIONS[selected]
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
        name: str,
        arguments: dict[str, Any],
        *,
        dry_run: bool = False,
    ) -> Any:
        if self.profile is None or self.agent_id is None:
            raise RuntimeError(
                "MCP invocation requires a constructor-bound profile and agent_id"
            )
        spec = self.registry.get(name)
        if not set(spec.permissions) <= self.permissions:
            raise CapabilityPermissionError(
                f"capability is not available to profile: {self.profile.value}"
            )
        confirmed = False
        try:
            result = self.registry.execute(
                name,
                arguments,
                permissions=self.permissions,
                confirmed=confirmed,
                dry_run=dry_run,
            )
        except Exception:
            self.repository.record_adapter_invocation(
                adapter="mcp",
                actor_type="agent",
                actor_id=self.agent_id,
                capability=name,
                side_effect=spec.side_effect.value,
                confirmed=confirmed,
                succeeded=False,
            )
            raise
        self.repository.record_adapter_invocation(
            adapter="mcp",
            actor_type="agent",
            actor_id=self.agent_id,
            capability=name,
            side_effect=spec.side_effect.value,
            confirmed=confirmed,
            succeeded=True,
        )
        return result
