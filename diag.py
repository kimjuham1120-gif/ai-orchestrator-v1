import sqlite3
con = sqlite3.connect("orchestrator_v1.db")
row = con.execute(
    "SELECT run_id, run_status, phase, bridge_decision, target_doc IS NOT NULL "
    "FROM artifacts WHERE project_id = 'proj-d2d33c74'"
).fetchone()
if row:
    rid, status, phase, decision, has_doc = row
    print(f"run_id:        {rid}")
    print(f"run_status:    {status}")
    print(f"phase:         {phase}")
    print(f"bridge_decision: {decision}")
    print(f"target_doc 존재: {bool(has_doc)}")

# projects 테이블도
prow = con.execute(
    "SELECT current_phase, status FROM projects WHERE project_id = 'proj-d2d33c74'"
).fetchone()
if prow:
    print(f"\n[projects 테이블]")
    print(f"current_phase: {prow[0]}")
    print(f"status:        {prow[1]}")
