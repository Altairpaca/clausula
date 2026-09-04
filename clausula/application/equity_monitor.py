from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from clausula.domain import canonical_decimal, canonical_timestamp, dec, new_id, now


CASE_FORMAT = "clausula-equity-case-v1"
COMPANY_STATUSES = {
    "strengthening", "intact", "watch", "impaired", "broken", "changed", "untested", "retired"
}
SECURITY_READINESS = {"ready", "conditional", "re_underwrite", "not_decision_grade"}
ACTIONS = {"add", "press", "hold", "trim", "exit", "hedge", "wait_for_proof", "re_underwrite"}
PILLAR_STATUSES = {"confirming", "intact", "watch", "impaired", "broken", "untested"}
PILLAR_PRIORITIES = {"core", "secondary", "monitor"}
THRESHOLD_ORIGINS = {"inherited", "draft", "approved"}
OPERATORS = {"gt", "gte", "lt", "lte", "eq", "neq"}
TIMING_KINDS = {"exact", "window", "unscheduled"}
TIMING_CONFIDENCE = {"confirmed", "high", "medium", "low", "unknown"}


class EquityCaseError(ValueError):
    pass


def _text(value: Any, field: str, *, optional: bool = False) -> str | None:
    result = str(value or "").strip()
    if not result:
        if optional:
            return None
        raise EquityCaseError(f"{field} cannot be empty")
    return result


def _enum(value: Any, field: str, allowed: set[str]) -> str:
    result = str(value or "").strip().lower()
    if result not in allowed:
        raise EquityCaseError(f"{field} must be one of {', '.join(sorted(allowed))}")
    return result


def _conditions(value: Mapping[str, Any] | None) -> dict[str, str | None]:
    raw = dict(value or {})
    return {
        "confirm": _text(raw.get("confirm"), "confirm condition", optional=True),
        "warning": _text(raw.get("warning"), "warning condition", optional=True),
        "break": _text(raw.get("break"), "break condition", optional=True),
    }


def normalize_pillars(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    keys: set[str] = set()
    for index, row in enumerate(rows):
        key = _text(row.get("key"), f"pillar {index} key")
        assert key is not None
        if key in keys:
            raise EquityCaseError(f"duplicate pillar key: {key}")
        keys.add(key)
        result.append(
            {
                "key": key,
                "statement": _text(row.get("statement"), f"pillar {key} statement"),
                "status": _enum(row.get("status", "untested"), f"pillar {key} status", PILLAR_STATUSES),
                "priority": _enum(row.get("priority", "secondary"), f"pillar {key} priority", PILLAR_PRIORITIES),
                "baseline": _text(row.get("baseline"), f"pillar {key} baseline", optional=True),
                "expected_path": _text(row.get("expected_path"), f"pillar {key} expected_path", optional=True),
                "conditions": _conditions(row.get("conditions")),
                "kpi_links": sorted({str(item).strip() for item in row.get("kpi_links", ()) if str(item).strip()}),
                "model_links": sorted({str(item).strip() for item in row.get("model_links", ()) if str(item).strip()}),
                "next_proof_point": _text(row.get("next_proof_point"), f"pillar {key} next proof point", optional=True),
            }
        )
    return result


def _normalize_threshold(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    return {
        "key": _text(row.get("key"), f"{field} key"),
        "metric": _text(row.get("metric"), f"{field} metric"),
        "operator": _enum(row.get("operator"), f"{field} operator", OPERATORS),
        "value": canonical_decimal(row.get("value")),
        "action": _enum(row.get("action"), f"{field} action", ACTIONS),
        "origin": _enum(row.get("origin"), f"{field} origin", THRESHOLD_ORIGINS),
        "source_ref": _text(row.get("source_ref"), f"{field} source_ref", optional=True),
    }


def normalize_kpis(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    keys: set[str] = set()
    for index, row in enumerate(rows):
        key = _text(row.get("key"), f"KPI {index} key")
        assert key is not None
        if key in keys:
            raise EquityCaseError(f"duplicate KPI key: {key}")
        keys.add(key)
        value = row.get("value")
        normalized_value = None if value is None else canonical_decimal(value)
        thresholds = []
        for threshold in row.get("thresholds", ()):
            normalized = _normalize_threshold(
                {**dict(threshold), "metric": threshold.get("metric") or key, "action": threshold.get("action") or "re_underwrite"},
                field=f"KPI {key} threshold",
            )
            thresholds.append(normalized)
        result.append(
            {
                "key": key,
                "label": _text(row.get("label") or key, f"KPI {key} label"),
                "value": normalized_value,
                "unit": _text(row.get("unit"), f"KPI {key} unit", optional=True),
                "as_of": None if row.get("as_of") is None else canonical_timestamp(row["as_of"]),
                "known_at": None if row.get("known_at") is None else canonical_timestamp(row["known_at"]),
                "source_ref": _text(row.get("source_ref"), f"KPI {key} source_ref", optional=True),
                "thresholds": thresholds,
            }
        )
    return result


def normalize_catalysts(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    keys: set[str] = set()
    for index, row in enumerate(rows):
        key = _text(row.get("key"), f"catalyst {index} key")
        assert key is not None
        if key in keys:
            raise EquityCaseError(f"duplicate catalyst key: {key}")
        keys.add(key)
        timing_kind = _enum(row.get("timing_kind"), f"catalyst {key} timing_kind", TIMING_KINDS)
        date = row.get("date")
        start = row.get("start")
        end = row.get("end")
        if timing_kind == "exact":
            if date is None or start is not None or end is not None:
                raise EquityCaseError("exact catalyst requires date and no window")
            date = canonical_timestamp(date)
        elif timing_kind == "window":
            if start is None or end is None or date is not None:
                raise EquityCaseError("window catalyst requires start/end and no exact date")
            start = canonical_timestamp(start)
            end = canonical_timestamp(end)
            if start > end:
                raise EquityCaseError("catalyst window start cannot exceed end")
        else:
            if any(item is not None for item in (date, start, end)):
                raise EquityCaseError("unscheduled catalyst cannot carry an exact/window date")
        result.append(
            {
                "key": key,
                "event_type": _text(row.get("event_type"), f"catalyst {key} event_type"),
                "timing_kind": timing_kind,
                "timing_confidence": _enum(row.get("timing_confidence", "unknown"), f"catalyst {key} timing_confidence", TIMING_CONFIDENCE),
                "date": date,
                "start": start,
                "end": end,
                "thesis_link": _text(row.get("thesis_link"), f"catalyst {key} thesis_link", optional=True),
                "kpi_links": sorted({str(item).strip() for item in row.get("kpi_links", ()) if str(item).strip()}),
                "prep_action": _text(row.get("prep_action"), f"catalyst {key} prep action", optional=True),
                "decision_implication": _text(row.get("decision_implication"), f"catalyst {key} decision implication", optional=True),
                "source_ref": _text(row.get("source_ref"), f"catalyst {key} source_ref", optional=True),
            }
        )
    return result


def normalize_action_thresholds(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result = [_normalize_threshold(row, field="action threshold") for row in rows]
    keys = [row["key"] for row in result]
    if len(set(keys)) != len(keys):
        raise EquityCaseError("action threshold keys must be unique")
    return result


class EquityCaseService:
    def __init__(self, repository):
        self.repository = repository

    def _versions(self, **filters):
        loader = getattr(self.repository, "versions", None)
        if loader is None:
            raise EquityCaseError("repository does not support equity cases")
        return loader(**filters)

    def _validate_refs(self, instrument_id: str, portfolio_id: str | None, thesis_id: str | None) -> None:
        self.repository.instrument_details(instrument_id)
        if portfolio_id is not None:
            self.repository.portfolio(portfolio_id)
        if thesis_id is not None:
            self.repository.research_thesis(thesis_id)

    def create(
        self,
        instrument_id: str,
        name: str,
        effective_from: str,
        *,
        company_status: str,
        security_readiness: str,
        action: str,
        portfolio_id: str | None = None,
        thesis_id: str | None = None,
        portfolio_role: str | None = None,
        horizon: str | None = None,
        variant_view: str | None = None,
        valuation_anchor: str | None = None,
        pillars: Sequence[Mapping[str, Any]] = (),
        kpis: Sequence[Mapping[str, Any]] = (),
        catalysts: Sequence[Mapping[str, Any]] = (),
        action_thresholds: Sequence[Mapping[str, Any]] = (),
        missing_inputs: Sequence[str] = (),
        key_risks: Sequence[str] = (),
        override_rationale: str | None = None,
        known_at: str | None = None,
        recorded_at: str | None = None,
    ) -> dict[str, Any]:
        self._validate_refs(instrument_id, portfolio_id, thesis_id)
        normalized_name = _text(name, "case name")
        for row in self._versions(instrument_id=instrument_id, portfolio_id=portfolio_id):
            if row["name"] == normalized_name and row.get("portfolio_id") == portfolio_id:
                raise EquityCaseError("an equity case with this name already exists for the instrument/portfolio")
        return self._append(
            case_id=new_id(), version_number=1, instrument_id=instrument_id,
            portfolio_id=portfolio_id, thesis_id=thesis_id, name=normalized_name,
            effective_from=effective_from, company_status=company_status,
            security_readiness=security_readiness, action=action, portfolio_role=portfolio_role,
            horizon=horizon, variant_view=variant_view, valuation_anchor=valuation_anchor,
            pillars=pillars, kpis=kpis, catalysts=catalysts, action_thresholds=action_thresholds,
            missing_inputs=missing_inputs, key_risks=key_risks, override_rationale=override_rationale,
            known_at=known_at, recorded_at=recorded_at,
        )

    def add_version(self, case_id: str, effective_from: str, **changes) -> dict[str, Any]:
        versions = self._versions(case_id=case_id)
        if not versions:
            raise KeyError(f"unknown equity case: {case_id}")
        latest = max(versions, key=lambda row: int(row["version_number"]))
        fields = {
            key: changes[key] if key in changes else latest.get(key)
            for key in (
                "company_status", "security_readiness", "action", "portfolio_role", "horizon",
                "variant_view", "valuation_anchor", "pillars", "kpis", "catalysts", "action_thresholds",
                "missing_inputs", "key_risks", "override_rationale", "thesis_id"
            )
        }
        return self._append(
            case_id=case_id,
            version_number=int(latest["version_number"]) + 1,
            instrument_id=latest["instrument_id"], portfolio_id=latest.get("portfolio_id"),
            thesis_id=fields.pop("thesis_id"), name=latest["name"], effective_from=effective_from,
            known_at=changes.get("known_at"), recorded_at=changes.get("recorded_at"), **fields,
        )

    def _append(self, *, case_id: str, version_number: int, instrument_id: str,
                portfolio_id: str | None, thesis_id: str | None, name: str,
                effective_from: str, company_status: str, security_readiness: str, action: str,
                portfolio_role: str | None, horizon: str | None, variant_view: str | None,
                valuation_anchor: str | None, pillars: Sequence[Mapping[str, Any]],
                kpis: Sequence[Mapping[str, Any]], catalysts: Sequence[Mapping[str, Any]],
                action_thresholds: Sequence[Mapping[str, Any]], missing_inputs: Sequence[str],
                key_risks: Sequence[str], override_rationale: str | None,
                known_at: str | None, recorded_at: str | None) -> dict[str, Any]:
        self._validate_refs(instrument_id, portfolio_id, thesis_id)
        recorded = canonical_timestamp(recorded_at or now())
        knowledge = canonical_timestamp(known_at or recorded)
        effective = canonical_timestamp(effective_from)
        if knowledge > recorded:
            raise EquityCaseError("known_at cannot be after recorded_at")
        company = _enum(company_status, "company_status", COMPANY_STATUSES)
        readiness = _enum(security_readiness, "security_readiness", SECURITY_READINESS)
        posture = _enum(action, "action", ACTIONS)
        normalized_missing = sorted({str(item).strip() for item in missing_inputs if str(item).strip()})
        if readiness == "ready" and normalized_missing:
            raise EquityCaseError("security_readiness=ready cannot carry missing decision inputs")
        if posture in {"add", "press"} and readiness != "ready":
            raise EquityCaseError("add/press action requires security_readiness=ready")
        normalized_pillars = normalize_pillars(pillars or ())
        broken_core = any(row["priority"] == "core" and row["status"] == "broken" for row in normalized_pillars)
        impaired_core = sum(1 for row in normalized_pillars if row["priority"] == "core" and row["status"] == "impaired")
        override = _text(override_rationale, "override_rationale", optional=True)
        if company in {"strengthening", "intact"} and (broken_core or impaired_core >= 2) and not override:
            raise EquityCaseError(
                "aggregate company thesis conflicts with core pillar status; provide override_rationale"
            )
        payload = {
            "format": CASE_FORMAT,
            "case_id": case_id,
            "version_number": version_number,
            "instrument_id": instrument_id,
            "portfolio_id": portfolio_id,
            "thesis_id": thesis_id,
            "name": name,
            "effective_from": effective,
            "known_at": knowledge,
            "company_status": company,
            "security_readiness": readiness,
            "action": posture,
            "portfolio_role": _text(portfolio_role, "portfolio_role", optional=True),
            "horizon": _text(horizon, "horizon", optional=True),
            "variant_view": _text(variant_view, "variant_view", optional=True),
            "valuation_anchor": _text(valuation_anchor, "valuation_anchor", optional=True),
            "pillars": normalized_pillars,
            "kpis": normalize_kpis(kpis or ()),
            "catalysts": normalize_catalysts(catalysts or ()),
            "action_thresholds": normalize_action_thresholds(action_thresholds or ()),
            "missing_inputs": normalized_missing,
            "key_risks": [str(item).strip() for item in key_risks if str(item).strip()],
            "override_rationale": override,
        }
        artifact_id, _ = self.repository.virtual_artifact(
            "manual://equity-case", json.dumps(payload, sort_keys=True, separators=(",", ":"))
        )
        batch_id = self.repository.import_batch(
            artifact_id, adapter_name="manual-equity-case", adapter_version="1", schema_version="1"
        )
        payload["source_artifact_id"] = artifact_id
        payload["import_batch_id"] = batch_id
        writer = getattr(self.repository, "add_version", None)
        if writer is None:
            raise EquityCaseError("repository does not support equity cases")
        return dict(writer(case_id, payload))

    def list(self, *, portfolio_id: str | None = None, instrument_id: str | None = None) -> list[dict[str, Any]]:
        return [dict(row) for row in self._versions(portfolio_id=portfolio_id, instrument_id=instrument_id)]

    def active(self, case_id: str, as_of: str, *, known_as_of: str | None = None) -> dict[str, Any] | None:
        loader = getattr(self.repository, "active", None)
        if loader is None:
            raise EquityCaseError("repository does not support equity cases")
        row = loader(case_id, as_of, known_as_of)
        return None if row is None else dict(row)

    @staticmethod
    def summarize(case: Mapping[str, Any], as_of: str) -> dict[str, Any]:
        cutoff = canonical_timestamp(as_of)
        pressure = [row for row in case.get("pillars", ()) if row["status"] in {"watch", "impaired", "broken"}]
        priority_order = {"core": 0, "secondary": 1, "monitor": 2}
        pressure.sort(key=lambda row: (priority_order[row["priority"]], row["key"]))
        proof = next((row["next_proof_point"] for row in case.get("pillars", ()) if row.get("next_proof_point")), None)
        upcoming = []
        for row in case.get("catalysts", ()):
            if row["timing_kind"] == "exact" and row["date"] >= cutoff:
                key = (0, row["date"])
            elif row["timing_kind"] == "window" and row["end"] >= cutoff:
                key = (1, row["start"])
            elif row["timing_kind"] == "unscheduled":
                key = (2, "9999")
            else:
                continue
            upcoming.append((key, row))
        upcoming.sort(key=lambda item: item[0])
        return {
            "case_id": case["case_id"],
            "name": case["name"],
            "company_status": case["company_status"],
            "security_readiness": case["security_readiness"],
            "action": case["action"],
            "missing_inputs": list(case.get("missing_inputs", ())),
            "pressure_pillars": pressure,
            "next_proof_point": proof,
            "next_catalyst": None if not upcoming else upcoming[0][1],
        }

    def portfolio_snapshot(self, portfolio_id: str, as_of: str, *, known_as_of: str | None = None) -> dict[str, Any]:
        cases: dict[str, dict[str, Any]] = {}
        for row in self._versions(portfolio_id=portfolio_id):
            cases.setdefault(row["case_id"], row)
        active = []
        for case_id in cases:
            row = self.active(case_id, as_of, known_as_of=known_as_of)
            if row is not None:
                active.append({"case": row, "summary": self.summarize(row, as_of)})
        active.sort(
            key=lambda item: (
                {"broken": 0, "impaired": 1, "watch": 2}.get(item["case"]["company_status"], 3),
                item["case"]["name"],
            )
        )
        return {
            "portfolio_id": portfolio_id,
            "as_of": canonical_timestamp(as_of),
            "known_as_of": canonical_timestamp(known_as_of or as_of),
            "cases": active,
            "not_decision_grade": sum(1 for item in active if item["case"]["security_readiness"] == "not_decision_grade"),
            "re_underwrite": sum(1 for item in active if item["case"]["security_readiness"] == "re_underwrite"),
        }
