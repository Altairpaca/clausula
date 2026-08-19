from pathlib import Path

from .services import LedgerService
from .capabilities import build_core_registry

class ClausulaClient:
    """Small Python SDK facade; CLI and SDK share LedgerService semantics."""
    def __init__(self, home=None):
        from .store import Store
        self.store = Store(home)
        self.service = LedgerService(self.store)
        self.capabilities = build_core_registry(self.store)
    def create_account(self, institution, name): return self.service.create_account(institution, name)
    def import_csv(self, account_id, path): return self.service.import_csv(account_id, path)
    def get_state(self, account_id, as_of=None): return self.service.state(account_id, as_of)
    def get_transactions(self, account_id, as_of=None): return self.service.transactions(account_id, as_of)
    def get_cost_basis(self, account_id, as_of=None): return self.service.cost_basis(account_id, as_of)
    def reconcile(self, account_id, observed, as_of): return self.service.reconcile(account_id, observed, as_of)
    def transfer_cash(self, source_account_id, destination_account_id, amount, currency, effective_at, **kwargs):
        return self.service.record_cash_transfer(
            source_account_id, destination_account_id, amount, currency, effective_at, **kwargs
        )
    def record_fx_conversion(self, account_id, from_currency, to_currency, from_amount, to_amount, effective_at, **kwargs):
        return self.service.record_fx_conversion(
            account_id, from_currency, to_currency, from_amount, to_amount, effective_at, **kwargs
        )
    def list_capabilities(self): return self.capabilities.describe()
    def import_market_prices(self, path, *, dataset_name="daily_prices", version=None, provider="local"):
        arguments = {
            "path": str(Path(path)),
            "dataset_name": dataset_name,
            "provider": provider,
        }
        if version is not None:
            arguments["version"] = version
        return self.invoke(
            "market.import_prices_csv",
            arguments,
            permissions={"market:write"},
            confirmed=True,
        )
    def import_market_fx(self, path, *, dataset_name="daily_fx", version=None, provider="local"):
        arguments = {
            "path": str(Path(path)),
            "dataset_name": dataset_name,
            "provider": provider,
        }
        if version is not None:
            arguments["version"] = version
        return self.invoke(
            "market.import_fx_csv",
            arguments,
            permissions={"market:write"},
            confirmed=True,
        )
    def market_datasets(self, dataset_name=None):
        arguments = {} if dataset_name is None else {"dataset_name": dataset_name}
        return self.invoke("market.list_datasets", arguments, permissions={"market:read"})
    def create_portfolio(self, name, base_currency="USD"):
        return self.invoke(
            "portfolio.create",
            {"name": name, "base_currency": base_currency},
            permissions={"portfolio:write"},
            confirmed=True,
        )["portfolio_id"]
    def set_portfolio_membership(self, portfolio_id, account_id, action, effective_at, *, known_at=None):
        arguments = {
            "portfolio_id": portfolio_id,
            "account_id": account_id,
            "action": action,
            "effective_at": effective_at,
        }
        if known_at is not None:
            arguments["known_at"] = known_at
        return self.invoke(
            "portfolio.set_membership",
            arguments,
            permissions={"portfolio:write"},
            confirmed=True,
        )["membership_event_id"]
    def portfolio_valuation(self, portfolio_id, as_of, **options):
        return self.invoke(
            "portfolio.get_valuation",
            {"portfolio_id": portfolio_id, "as_of": as_of, **options},
            permissions={"portfolio:read", "market:read"},
        )
    def portfolio_performance(self, portfolio_id, dates, **options):
        return self.invoke(
            "portfolio.get_performance",
            {"portfolio_id": portfolio_id, "dates": list(dates), **options},
            permissions={"portfolio:read", "market:read"},
        )
    def create_policy(self, portfolio_id, name, effective_from, rules, **options):
        return self.invoke(
            "policy.create",
            {
                "portfolio_id": portfolio_id,
                "name": name,
                "effective_from": effective_from,
                "rules": list(rules),
                **options,
            },
            permissions={"policy:write"},
            confirmed=True,
        )
    def add_policy_version(self, policy_id, effective_from, rules, **options):
        return self.invoke(
            "policy.add_version",
            {
                "policy_id": policy_id,
                "effective_from": effective_from,
                "rules": list(rules),
                **options,
            },
            permissions={"policy:write"},
            confirmed=True,
        )
    def list_policies(self, portfolio_id=None):
        arguments = {} if portfolio_id is None else {"portfolio_id": portfolio_id}
        return self.invoke("policy.list", arguments, permissions={"policy:read"})
    def evaluate_policy(self, policy_id, as_of, **options):
        return self.invoke(
            "policy.evaluate",
            {"policy_id": policy_id, "as_of": as_of, **options},
            permissions={"policy:read", "portfolio:read", "market:read"},
        )
    def simulate_policy(self, policy_id, as_of, actions, **options):
        return self.invoke(
            "policy.simulate",
            {
                "policy_id": policy_id,
                "as_of": as_of,
                "actions": list(actions),
                **options,
            },
            permissions={"policy:read", "portfolio:read", "market:read"},
        )
    def compare_plan_scenarios(self, policy_id, as_of, scenarios, **options):
        return self.invoke(
            "planning.compare",
            {
                "policy_id": policy_id,
                "as_of": as_of,
                "scenarios": list(scenarios),
                **options,
            },
            permissions={"planning:read", "policy:read", "portfolio:read", "market:read"},
        )
    def create_plan(self, policy_id, name, as_of, scenarios, **options):
        return self.invoke(
            "planning.create",
            {
                "policy_id": policy_id,
                "name": name,
                "as_of": as_of,
                "scenarios": list(scenarios),
                **options,
            },
            permissions={"planning:write", "policy:read", "portfolio:read", "market:read"},
            confirmed=True,
        )
    def list_plans(self, portfolio_id=None):
        arguments = {} if portfolio_id is None else {"portfolio_id": portfolio_id}
        return self.invoke("planning.list", arguments, permissions={"planning:read"})
    def get_plan(self, plan_id):
        return self.invoke(
            "planning.get", {"plan_id": plan_id}, permissions={"planning:read"}
        )
    def invoke(self, name, arguments=None, *, permissions=(), confirmed=False, dry_run=False):
        return self.capabilities.execute(
            name,
            arguments,
            permissions=permissions,
            confirmed=confirmed,
            dry_run=dry_run,
        )
