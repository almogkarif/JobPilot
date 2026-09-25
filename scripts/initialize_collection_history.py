#!/usr/bin/env python3
"""Explicit additive local history initialization; never connects to production."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.models import CollectionObservation
from app.services.collection_metrics import seed_retained_history, seed_verified_blocked_urls, collection_metrics


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--blocked-audit', type=Path)
    args=parser.parse_args()
    if not args.database.is_file():
        parser.error('Expected an existing local SQLite file')
    with args.database.open('rb') as stream:
        if stream.read(16)!=b'SQLite format 3\x00':
            parser.error('Only a local SQLite database is supported')
    urls=[]
    if args.blocked_audit:
        if args.blocked_audit.stat().st_size>1_000_000:
            parser.error('Audit exceeds 1 MB')
        payload=json.loads(args.blocked_audit.read_text())
        urls=[r['url'] for r in payload['rows'] if str(r.get('status','')).startswith('blocked')]
        if len(urls)>1000:
            parser.error('Audit exceeds 1000 URLs')
    engine=create_engine('sqlite:///'+str(args.database.resolve()))
    CollectionObservation.__table__.create(engine,checkfirst=True)
    with Session(engine) as db:
        seed_retained_history(db)
        seed_verified_blocked_urls(db,urls)
        db.commit()
        print(json.dumps(collection_metrics(db),ensure_ascii=False,default=str))


if __name__=='__main__':
    main()
