"""
One-time migration script: copy local SQLite data to Turso cloud database.

Usage:
    export TURSO_DATABASE_URL="libsql://your-db-name.turso.io"
    export TURSO_AUTH_TOKEN="your-token"
    python migrate_to_turso.py

This will:
1. Read all data from local data/expenses.db
2. Create the schema in Turso
3. Copy all rows from every table
"""

import os
import sqlite3
import sys

# Ensure the Turso env vars are set before importing database module
TURSO_URL = os.environ.get("TURSO_DATABASE_URL", "")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")

if not TURSO_URL or not TURSO_TOKEN:
    print("Error: Set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN environment variables first.")
    print()
    print("  export TURSO_DATABASE_URL='libsql://your-db.turso.io'")
    print("  export TURSO_AUTH_TOKEN='your-token'")
    sys.exit(1)

import libsql_experimental as libsql

LOCAL_DB = os.path.join(os.path.dirname(__file__), "data", "expenses.db")

if not os.path.exists(LOCAL_DB):
    print(f"Error: Local database not found at {LOCAL_DB}")
    sys.exit(1)


def get_tables(conn):
    """Get all user tables (not sqlite internals)."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return [r[0] if isinstance(r, tuple) else r["name"] for r in rows]


def get_schema(conn):
    """Get full CREATE TABLE/INDEX statements from local DB."""
    rows = conn.execute(
        "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type DESC, name"
    ).fetchall()
    return [r[0] if isinstance(r, tuple) else r["sql"] for r in rows]


def migrate():
    print(f"Source: {LOCAL_DB}")
    print(f"Target: {TURSO_URL}")
    print()

    # Connect to both databases
    local = sqlite3.connect(LOCAL_DB)
    local.row_factory = sqlite3.Row
    remote = libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)

    # Step 1: Recreate schema in Turso
    print("Creating schema in Turso...")
    schemas = get_schema(local)
    for sql in schemas:
        # Add IF NOT EXISTS for safety
        safe_sql = sql.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ")
        safe_sql = safe_sql.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ")
        safe_sql = safe_sql.replace("CREATE UNIQUE INDEX ", "CREATE UNIQUE INDEX IF NOT EXISTS ")
        try:
            remote.execute(safe_sql)
        except Exception as e:
            print(f"  Warning: {e}")
    remote.commit()
    print("  Done.")

    # Step 2: Copy data table by table
    tables = get_tables(local)
    total_rows = 0

    for table in tables:
        rows = local.execute(f"SELECT * FROM [{table}]").fetchall()
        if not rows:
            print(f"  {table}: 0 rows (empty)")
            continue

        # Get column names
        cols = rows[0].keys()
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(f"[{c}]" for c in cols)
        insert_sql = f"INSERT OR IGNORE INTO [{table}] ({col_names}) VALUES ({placeholders})"

        count = 0
        # Insert in batches of 100
        for i in range(0, len(rows), 100):
            batch = rows[i : i + 100]
            for row in batch:
                try:
                    remote.execute(insert_sql, tuple(row))
                    count += 1
                except Exception as e:
                    pass  # Skip duplicates silently
            remote.commit()

        print(f"  {table}: {count}/{len(rows)} rows migrated")
        total_rows += count

    local.close()
    print()
    print(f"Migration complete! {total_rows} total rows copied to Turso.")
    print()
    print("Next steps:")
    print("  1. Verify data in Turso: turso db shell your-db-name")
    print("  2. Deploy to Streamlit Cloud with TURSO_DATABASE_URL set in secrets")


if __name__ == "__main__":
    migrate()
