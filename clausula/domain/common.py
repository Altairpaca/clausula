from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
import uuid


class DomainValidationError(ValueError):
    """A value violates a canonical domain contract."""


def new_id() -> str:
    return str(uuid.uuid4())


def require_uuid(value: str, field: str = "id") -> str:
    try:
        parsed = uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise DomainValidationError(f"{field} must be a UUID") from exc
    if str(parsed) != str(value).lower():
        raise DomainValidationError(f"{field} must use canonical UUID syntax")
    return str(parsed)


def dec(value: Decimal | str | int) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise DomainValidationError("binary floating point is forbidden for financial values")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, (str, int)):
        try:
            result = Decimal(value)
        except (InvalidOperation, ValueError) as exc:
            raise DomainValidationError(f"invalid decimal value: {value!r}") from exc
    else:
        raise DomainValidationError(f"unsupported decimal value: {type(value).__name__}")
    if not result.is_finite():
        raise DomainValidationError("financial values must be finite")
    return result


def canonical_decimal(value: Decimal | str | int) -> str:
    number = dec(value)
    if number == 0:
        return "0"
    rendered = format(number, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def canonical_timestamp(value: str | date | datetime) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min, tzinfo=timezone.utc)
    elif isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            raise DomainValidationError("timestamp cannot be empty")
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise DomainValidationError(f"invalid ISO-8601 timestamp: {value!r}") from exc
        if parsed.tzinfo is None and len(candidate) == 10:
            parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        raise DomainValidationError("timestamp must be an ISO-8601 string, date, or datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DomainValidationError("timestamps with a time component require an explicit offset")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


def now() -> str:
    return canonical_timestamp(datetime.now(timezone.utc))
