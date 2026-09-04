from __future__ import annotations

from decimal import Decimal
from typing import Any

from clausula.analytics import replay_fifo
from clausula.domain import canonical_decimal, canonical_timestamp, dec, now

from .ledger import LedgerService as _BaseLedgerService


class LedgerService(_BaseLedgerService):
    """Ledger service with bounded read queries and multi-cutoff replay.

    Write behavior is inherited unchanged. Read behavior prefers the public
    Store batch projections when available and falls back to the scalar
    repository contract for third-party/in-memory repositories.
    """

    def _transactions_with_legs(
        self,
        account_id: str,
        as_of: str | None = None,
        *,
        known_as_of: str | None = None,
    ) -> list[dict[str, Any]]:
        batch = getattr(self.repository, "transactions_with_legs", None)
        if batch is not None:
            return [
                dict(item) | {"legs": [dict(leg) for leg in item.get("legs", ())]}
                for item in batch(account_id, as_of, known_as_of)
            ]
        return [
            dict(row)
            | {"legs": [dict(leg) for leg in self.repository.legs(row["id"])]}
            for row in self.repository.transactions(account_id, as_of, known_as_of)
        ]

    def transactions(
        self,
        account_id: str,
        as_of: str | None = None,
        *,
        known_as_of: str | None = None,
    ) -> list[dict]:
        return self._transactions_with_legs(
            account_id, as_of, known_as_of=known_as_of
        )

    @staticmethod
    def _state_payload(
        account_id: str,
        as_of: str,
        positions: dict[str, Decimal],
        cash_by_currency: dict[str, Decimal],
    ) -> dict[str, Any]:
        cash_output = {
            currency: canonical_decimal(amount)
            for currency, amount in sorted(cash_by_currency.items())
            if amount != 0
        }
        if not cash_output:
            legacy_cash, cash_currency = "0", None
        elif len(cash_output) == 1:
            cash_currency, legacy_cash = next(iter(cash_output.items()))
        else:
            legacy_cash, cash_currency = None, None
        return {
            "account_id": account_id,
            "as_of": canonical_timestamp(as_of),
            "cash": legacy_cash,
            "cash_currency": cash_currency,
            "cash_by_currency": cash_output,
            "positions": {
                instrument_id: canonical_decimal(quantity)
                for instrument_id, quantity in sorted(positions.items())
                if quantity != 0
            },
        }

    @staticmethod
    def _apply_transaction(
        transaction: dict[str, Any],
        positions: dict[str, Decimal],
        cash_by_currency: dict[str, Decimal],
    ) -> None:
        for leg in transaction.get("legs", ()):
            if leg["leg_type"] == "cash":
                currency = leg["currency"]
                cash_by_currency[currency] = cash_by_currency.get(
                    currency, Decimal(0)
                ) + dec(leg["amount"])
            if leg["instrument_id"] and leg["leg_type"] == "position":
                instrument_id = leg["instrument_id"]
                positions[instrument_id] = positions.get(
                    instrument_id, Decimal(0)
                ) + dec(leg["quantity"])

    def state(
        self,
        account_id: str,
        as_of: str | None = None,
        *,
        known_as_of: str | None = None,
    ) -> dict:
        cutoff = canonical_timestamp(as_of) if as_of else now()
        positions: dict[str, Decimal] = {}
        cash_by_currency: dict[str, Decimal] = {}
        for transaction in self._transactions_with_legs(
            account_id, cutoff, known_as_of=known_as_of
        ):
            self._apply_transaction(transaction, positions, cash_by_currency)
        return self._state_payload(
            account_id, cutoff, positions, cash_by_currency
        )

    def states(
        self,
        account_id: str,
        cutoffs: list[str] | tuple[str, ...],
        *,
        known_as_of: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Replay one account once across monotonically increasing cutoffs."""

        normalized = sorted({canonical_timestamp(value) for value in cutoffs})
        if not normalized:
            return {}
        fixed_knowledge = (
            canonical_timestamp(known_as_of) if known_as_of is not None else None
        )
        max_cutoff = normalized[-1]
        stream = self._transactions_with_legs(
            account_id,
            max_cutoff,
            known_as_of=fixed_knowledge or max_cutoff,
        )
        indexed = list(enumerate(stream))
        if fixed_knowledge is None:
            indexed.sort(
                key=lambda pair: (
                    max(pair[1]["effective_at"], pair[1]["known_at"]),
                    pair[0],
                )
            )
        else:
            indexed.sort(key=lambda pair: (pair[1]["effective_at"], pair[0]))

        positions: dict[str, Decimal] = {}
        cash_by_currency: dict[str, Decimal] = {}
        cursor = 0
        result: dict[str, dict[str, Any]] = {}
        for cutoff in normalized:
            while cursor < len(indexed):
                transaction = indexed[cursor][1]
                activation = (
                    transaction["effective_at"]
                    if fixed_knowledge is not None
                    else max(transaction["effective_at"], transaction["known_at"])
                )
                if activation > cutoff:
                    break
                self._apply_transaction(transaction, positions, cash_by_currency)
                cursor += 1
            result[cutoff] = self._state_payload(
                account_id, cutoff, positions, cash_by_currency
            )
        return result

    def external_flows(
        self,
        account_id: str,
        through: str,
        *,
        known_as_of: str | None = None,
    ) -> dict[str, str]:
        flows: dict[str, Decimal] = {}
        for transaction in self._transactions_with_legs(
            account_id, through, known_as_of=known_as_of
        ):
            day = transaction["effective_at"][:10]
            for leg in transaction["legs"]:
                if leg["leg_type"] == "external":
                    flows[day] = flows.get(day, Decimal(0)) - dec(leg["amount"])
        return {
            day: canonical_decimal(amount) for day, amount in sorted(flows.items())
        }

    def external_flows_for_cutoffs(
        self,
        account_id: str,
        cutoffs: list[str] | tuple[str, ...],
        *,
        known_as_of: str | None = None,
    ) -> dict[str, str]:
        """Return the same per-day flow semantics without replaying per date."""

        normalized = sorted({canonical_timestamp(value) for value in cutoffs})
        if not normalized:
            return {}
        fixed_knowledge = (
            canonical_timestamp(known_as_of) if known_as_of is not None else None
        )
        max_cutoff = normalized[-1]
        stream = self._transactions_with_legs(
            account_id,
            max_cutoff,
            known_as_of=fixed_knowledge or max_cutoff,
        )
        by_day: dict[str, list[tuple[str, str, Decimal]]] = {}
        for transaction in stream:
            amount = sum(
                (
                    -dec(leg["amount"])
                    for leg in transaction["legs"]
                    if leg["leg_type"] == "external"
                ),
                Decimal(0),
            )
            if amount:
                by_day.setdefault(transaction["effective_at"][:10], []).append(
                    (
                        transaction["effective_at"],
                        transaction["known_at"],
                        amount,
                    )
                )
        result: dict[str, str] = {}
        for cutoff in normalized:
            point_knowledge = fixed_knowledge or cutoff
            amount = sum(
                (
                    value
                    for effective_at, knowledge_at, value in by_day.get(
                        cutoff[:10], ()
                    )
                    if effective_at <= cutoff and knowledge_at <= point_knowledge
                ),
                Decimal(0),
            )
            result[cutoff] = canonical_decimal(amount)
        return result

    def cost_basis(
        self,
        account_id: str,
        as_of: str | None = None,
        *,
        known_as_of: str | None = None,
    ) -> dict:
        transactions = self._transactions_with_legs(
            account_id, as_of, known_as_of=known_as_of
        )
        ids = [transaction["id"] for transaction in transactions]
        batch = getattr(self.repository, "transaction_metadata_many", None)
        if batch is not None:
            loaded = batch(ids)
            metadata = {
                transaction_id: dict(loaded.get(transaction_id, {}))
                for transaction_id in ids
            }
        else:
            metadata = {
                transaction_id: dict(
                    self.repository.transaction_metadata(transaction_id)
                )
                for transaction_id in ids
            }
        report = replay_fifo(transactions, metadata)
        return {
            "account_id": account_id,
            "as_of": canonical_timestamp(as_of) if as_of else now(),
            **report,
        }
