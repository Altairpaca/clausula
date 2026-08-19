import argparse, json
from .services import LedgerService
from .store import Store

def main(argv=None):
    p=argparse.ArgumentParser(prog="clausula"); sub=p.add_subparsers(dest="command",required=True)
    a=sub.add_parser("account"); asub=a.add_subparsers(dest="action",required=True); c=asub.add_parser("create"); c.add_argument("institution"); c.add_argument("name")
    l=sub.add_parser("ledger"); ls=l.add_subparsers(dest="action",required=True); i=ls.add_parser("import"); i.add_argument("account"); i.add_argument("path"); s=ls.add_parser("state"); s.add_argument("account"); s.add_argument("--as-of")
    sy=sub.add_parser("system"); sy.add_subparsers(dest="action",required=True).add_parser("check")
    args=p.parse_args(argv); svc=LedgerService(Store())
    if args.command=="account": out={"account_id":svc.create_account(args.institution,args.name)}
    elif args.action=="import": out=svc.import_csv(args.account,args.path)
    elif args.action=="state": out=svc.state(args.account,args.as_of)
    else: out={"integrity":svc.store.integrity_check()}
    print(json.dumps(out,default=str)); return 0

if __name__ == "__main__":
    main()
