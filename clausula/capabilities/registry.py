from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Callable, Iterable, Mapping


class CapabilityError(RuntimeError):
    pass


class CapabilityPermissionError(CapabilityError):
    pass


class ConfirmationRequired(CapabilityError):
    pass


class SideEffect(str, Enum):
    NONE = "none"
    LOCAL_READ = "local_read"
    LOCAL_WRITE = "local_write"
    EXTERNAL_READ = "external_read"
    EXTERNAL_WRITE = "external_write"


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    mode: str
    deterministic: bool
    side_effect: SideEffect
    permissions: tuple[str, ...]
    confirmation_required: bool
    provenance: str
    version: str = "1.0.0"

    def __post_init__(self) -> None:
        if self.mode not in {"read", "write"}:
            raise ValueError("capability mode must be read or write")
        namespace, separator, operation = self.name.partition(".")
        if not separator or not namespace or not operation:
            raise ValueError("capability name must use namespace.operation")
        if self.mode == "read" and self.side_effect in {
            SideEffect.LOCAL_WRITE,
            SideEffect.EXTERNAL_WRITE,
        }:
            raise ValueError("read capability cannot declare a write side effect")

    def describe(self) -> dict[str, Any]:
        result = asdict(self)
        result["side_effect"] = self.side_effect.value
        return result


@dataclass(frozen=True)
class _RegisteredCapability:
    spec: CapabilitySpec
    handler: Callable[..., Any]


def object_schema(
    properties: Mapping[str, Any] | None = None,
    *,
    required: Iterable[str] = (),
    additional_properties: bool = False,
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": dict(properties or {}),
        "required": list(required),
        "additionalProperties": additional_properties,
    }


def _matches_type(value: Any, expected: str) -> bool:
    return {
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "object": isinstance(value, Mapping),
        "array": isinstance(value, list),
        "null": value is None,
    }.get(expected, True)


def validate_schema(value: Any, schema: Mapping[str, Any], path: str = "input") -> None:
    expected = schema.get("type")
    if isinstance(expected, list):
        if not any(_matches_type(value, candidate) for candidate in expected):
            raise CapabilityError(f"{path} must have type {' or '.join(expected)}")
    elif expected and not _matches_type(value, expected):
        raise CapabilityError(f"{path} must have type {expected}")
    if "enum" in schema and value not in schema["enum"]:
        raise CapabilityError(f"{path} must be one of {schema['enum']}")
    if isinstance(value, Mapping):
        properties = schema.get("properties", {})
        missing = set(schema.get("required", ())) - set(value)
        if missing:
            raise CapabilityError(f"{path} missing required fields: {', '.join(sorted(missing))}")
        if schema.get("additionalProperties") is False:
            unexpected = set(value) - set(properties)
            if unexpected:
                raise CapabilityError(
                    f"{path} contains unknown fields: {', '.join(sorted(unexpected))}"
                )
        for key, item in value.items():
            if key in properties:
                validate_schema(item, properties[key], f"{path}.{key}")
            elif isinstance(schema.get("additionalProperties"), Mapping):
                validate_schema(item, schema["additionalProperties"], f"{path}.{key}")
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            validate_schema(item, schema["items"], f"{path}[{index}]")


class CapabilityRegistry:
    def __init__(self) -> None:
        self._capabilities: dict[str, _RegisteredCapability] = {}

    def register(self, spec: CapabilitySpec, handler: Callable[..., Any]) -> None:
        if spec.name in self._capabilities:
            raise ValueError(f"capability already registered: {spec.name}")
        self._capabilities[spec.name] = _RegisteredCapability(spec, handler)

    def get(self, name: str) -> CapabilitySpec:
        try:
            return self._capabilities[name].spec
        except KeyError as exc:
            raise CapabilityError(f"unknown capability: {name}") from exc

    def describe(self, name: str | None = None) -> dict[str, Any] | list[dict[str, Any]]:
        if name is not None:
            return self.get(name).describe()
        return [self._capabilities[key].spec.describe() for key in sorted(self._capabilities)]

    def execute(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        permissions: Iterable[str] = (),
        confirmed: bool = False,
        dry_run: bool = False,
    ) -> Any:
        try:
            registered = self._capabilities[name]
        except KeyError as exc:
            raise CapabilityError(f"unknown capability: {name}") from exc
        provided = set(permissions)
        missing = set(registered.spec.permissions) - provided
        if missing:
            raise CapabilityPermissionError(
                f"{name} requires permissions: {', '.join(sorted(missing))}"
            )
        if registered.spec.confirmation_required and not confirmed and not dry_run:
            raise ConfirmationRequired(f"{name} requires explicit confirmation")
        payload = dict(arguments or {})
        validate_schema(payload, registered.spec.input_schema)
        if dry_run:
            return {
                "capability": name,
                "would_execute": True,
                "side_effect": registered.spec.side_effect.value,
                "arguments": payload,
            }
        result = registered.handler(**payload)
        validate_schema(result, registered.spec.output_schema, "output")
        return result
