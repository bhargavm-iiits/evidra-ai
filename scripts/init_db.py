"""Create claimbridge.db with the full schema and load policy chunks. Safe to re-run."""
import json

from core.config import POLICIES_PATH
from core.db import init_db, connect, upsert_policy_chunk

if __name__ == "__main__":
    init_db()
    conn = connect()
    for chunk in json.loads(POLICIES_PATH.read_text()):
        upsert_policy_chunk(conn, chunk)
    conn.close()
    print("Database initialized and policy chunks loaded.")
