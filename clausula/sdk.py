from .services import LedgerService

class ClausulaClient:
    """Small Python SDK facade; CLI and SDK share LedgerService semantics."""
    def __init__(self, home=None):
        from .store import Store
        self.service = LedgerService(Store(home))
    def create_account(self, institution, name): return self.service.create_account(institution, name)
    def import_csv(self, account_id, path): return self.service.import_csv(account_id, path)
    def get_state(self, account_id, as_of=None): return self.service.state(account_id, as_of)
    def get_transactions(self, account_id, as_of=None): return self.service.transactions(account_id, as_of)
    def reconcile(self, account_id, observed, as_of): return self.service.reconcile(account_id, observed, as_of)
    def transfer_cash(self, source_account_id, destination_account_id, amount, currency, effective_at, **kwargs):
        return self.service.record_cash_transfer(
            source_account_id, destination_account_id, amount, currency, effective_at, **kwargs
        )
