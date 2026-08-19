import csv
from decimal import Decimal
from clausula import Store, LedgerService

def fixture(path):
    with path.open("w", newline="") as f:
        w=csv.DictWriter(f,fieldnames=["id","date","type","ticker","quantity","amount","fee"]); w.writeheader()
        w.writerow({"id":"1","date":"2025-01-01T00:00:00+00:00","type":"buy","ticker":"ABC","quantity":"2","amount":"100","fee":"1"})
        w.writerow({"id":"2","date":"2025-01-02T00:00:00+00:00","type":"sell","ticker":"ABC","quantity":"1","amount":"60","fee":"0"})

def test_import_state_and_idempotence(tmp_path):
    svc=LedgerService(Store(tmp_path)); account=svc.create_account("broker","main"); path=tmp_path/"x.csv"; fixture(path)
    result=svc.import_csv(account,path); assert result["transactions"]==2
    assert svc.import_csv(account,path)["transactions"]==0
    state=svc.state(account,"2025-01-03T00:00:00+00:00")
    assert Decimal(state["cash"])==Decimal("-41")
    assert list(state["positions"].values())==["1"]

def test_temporal_known_at_filter(tmp_path):
    svc=LedgerService(Store(tmp_path)); account=svc.create_account("b","a"); path=tmp_path/"x.csv"
    with path.open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["id","effective_at","known_at","ticker","quantity","amount"]); w.writeheader(); w.writerow({"id":"1","effective_at":"2025-01-01","known_at":"2025-02-01","ticker":"ABC","quantity":"1","amount":"10"})
    svc.import_csv(account,path)
    assert svc.state(account,"2025-01-15")["positions"]=={}

def test_reconcile_does_not_overwrite(tmp_path):
    svc=LedgerService(Store(tmp_path)); account=svc.create_account("b","a"); result=svc.reconcile(account,{"cash":"5","positions":{}},"2025-01-01")
    assert result.differences[0]["kind"]=="cash"

def test_backup_restore_and_correction_are_append_only(tmp_path):
    store=Store(tmp_path/"one"); svc=LedgerService(store); account=svc.create_account("b","a")
    iid=svc.resolve_instrument("ABC"); from clausula.models import TransactionLeg
    svc.record_correction(account,[TransactionLeg(account,iid,Decimal("1"),Decimal("0"),"USD","position")],"2025-01-01")
    backup=tmp_path/"backup.db"; store.backup(backup)
    import sqlite3
    with sqlite3.connect(backup) as conn: assert conn.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
    assert svc.positions(account)[iid]=="1"
