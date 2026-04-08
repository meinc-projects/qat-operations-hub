"""Check what the metrics DB recorded from previous runs."""
import sqlite3
import json

conn = sqlite3.connect("data/hub_metrics.db")
conn.row_factory = sqlite3.Row

runs = conn.execute("SELECT * FROM module_runs ORDER BY started_at").fetchall()
print(f"=== {len(runs)} run(s) recorded ===\n")
for r in runs:
    print(f"Run: {r['run_id']}")
    print(f"  Status: {r['status']}  |  Total: {r['total_items']}  |  Processed: {r['processed']}  |  Succeeded: {r['succeeded']}  |  Failed: {r['failed']}  |  Skipped: {r['skipped']}")
    print()

events = conn.execute("SELECT deal_id, deal_name, event_type, details FROM module_events ORDER BY created_at LIMIT 100").fetchall()
print(f"=== {len(events)} event(s) recorded ===\n")
for e in events:
    detail = e["details"] or ""
    if len(detail) > 100:
        detail = detail[:100] + "..."
    print(f"  [{e['event_type']:10s}]  Deal {e['deal_id']}  ({e['deal_name']})")
    if detail:
        print(f"              {detail}")
