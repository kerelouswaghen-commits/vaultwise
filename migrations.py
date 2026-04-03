"""
Database migration runner — applies schema changes incrementally.
Each migration runs once and is tracked in the _migrations table.
Called from database.init_db() after the base schema is created.
"""

import sqlite3
from datetime import datetime



MIGRATIONS = [
    {
        "id": "001_category_analytics",
        "sql": """
            CREATE TABLE IF NOT EXISTS category_analytics (
                category    TEXT NOT NULL,
                scope       TEXT NOT NULL DEFAULT 'monthly',
                analysis_json TEXT NOT NULL,
                updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (category, scope)
            );
        """,
    },
    {
        "id": "002_transaction_tags",
        "sql": None,  # handled in code (ALTER TABLE may fail if column exists)
    },
    {
        "id": "003_savings_target",
        "sql": """
            INSERT OR IGNORE INTO settings (key, value) VALUES ('monthly_savings_target', '1000');
        """,
    },
    {
        "id": "004_category_definitions",
        "sql": """
            CREATE TABLE IF NOT EXISTS category_definitions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT UNIQUE NOT NULL,
                parent      TEXT,
                description TEXT,
                color       TEXT,
                sort_order  INTEGER DEFAULT 50,
                is_active   INTEGER DEFAULT 1,
                created_ts  TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """,
    },
    {
        "id": "005_savings_snapshots",
        "sql": """
            CREATE TABLE IF NOT EXISTS savings_snapshots (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                month       TEXT NOT NULL UNIQUE,
                actual_net  REAL,
                target      REAL,
                cumulative  REAL,
                created_ts  TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """,
    },
    {
        "id": "006_monarch_settings",
        "sql": """
            INSERT OR IGNORE INTO settings (key, value) VALUES ('monarch_enabled', '0');
            INSERT OR IGNORE INTO settings (key, value) VALUES ('monarch_last_sync', '');
            INSERT OR IGNORE INTO settings (key, value) VALUES ('monarch_account_map', '{}');
            INSERT OR IGNORE INTO settings (key, value) VALUES ('monarch_category_map', '{}');
        """,
    },
    {
        "id": "007_category_config",
        "sql": """
            CREATE TABLE IF NOT EXISTS category_config (
                name           TEXT PRIMARY KEY,
                type           TEXT NOT NULL DEFAULT 'flex',
                monthly_budget REAL,
                sort_order     INTEGER DEFAULT 50,
                updated_ts     TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """,
    },
    {
        "id": "008_seed_fixed_categories",
        "sql": None,  # Handled in run_pending with Python logic
    },
    {
        "id": "009_fix_fixed_category_types",
        "sql": None,  # Retroactively fix categories wrongly registered as flex
    },
]


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    """Create the migrations tracking table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            id          TEXT PRIMARY KEY,
            applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    conn.commit()


def _get_applied(conn: sqlite3.Connection) -> set:
    """Return set of migration IDs already applied."""
    rows = conn.execute("SELECT id FROM _migrations").fetchall()
    return {r[0] if isinstance(r, tuple) else r["id"] for r in rows}


def run_pending(conn: sqlite3.Connection) -> list[str]:
    """Apply all pending migrations. Returns list of applied migration IDs."""
    _ensure_migrations_table(conn)
    applied = _get_applied(conn)
    newly_applied = []

    for migration in MIGRATIONS:
        mid = migration["id"]
        if mid in applied:
            continue

        # Special handling for ALTER TABLE (can't use IF NOT EXISTS)
        if mid == "002_transaction_tags":
            try:
                conn.execute("ALTER TABLE transactions ADD COLUMN tags TEXT DEFAULT NULL")
            except (sqlite3.OperationalError, Exception):
                pass  # Column already exists

        elif mid == "008_seed_fixed_categories":
            # Seed category_config with fixed categories from config
            # Uses upsert to override any wrongly-registered flex entries
            try:
                import config as _cfg
                if hasattr(_cfg, "FIXED_MONTHLY_EXPENSES"):
                    _sort = 10
                    for _name, _budget in _cfg.FIXED_MONTHLY_EXPENSES.items():
                        conn.execute(
                            "INSERT INTO category_config (name, type, monthly_budget, sort_order) VALUES (?, 'fix', ?, ?) "
                            "ON CONFLICT(name) DO UPDATE SET type='fix', monthly_budget=excluded.monthly_budget, sort_order=excluded.sort_order",
                            (_name, _budget, _sort),
                        )
                        _sort += 1
                    for _muted in getattr(_cfg, "MUTED_CATEGORIES", []):
                        conn.execute(
                            "INSERT INTO category_config (name, type) VALUES (?, 'exclude') "
                            "ON CONFLICT(name) DO UPDATE SET type='exclude'",
                            (_muted,),
                        )
                    conn.commit()
            except Exception:
                pass

        elif mid == "009_fix_fixed_category_types":
            # Retroactive fix: any category in FIXED_MONTHLY_EXPENSES that was
            # wrongly auto-registered as 'flex' by ensure_category_config gets
            # corrected to 'fix' with proper budget
            try:
                import config as _cfg
                if hasattr(_cfg, "FIXED_MONTHLY_EXPENSES"):
                    _sort = 10
                    for _name, _budget in _cfg.FIXED_MONTHLY_EXPENSES.items():
                        conn.execute(
                            "UPDATE category_config SET type='fix', monthly_budget=? WHERE name=? AND type != 'fix'",
                            (_budget, _name),
                        )
                        _sort += 1
                    for _muted in getattr(_cfg, "MUTED_CATEGORIES", []):
                        conn.execute(
                            "UPDATE category_config SET type='exclude' WHERE name=? AND type != 'exclude'",
                            (_muted,),
                        )
                    conn.commit()
            except Exception:
                pass

        elif migration["sql"]:
            conn.executescript(migration["sql"])

        conn.execute("INSERT INTO _migrations (id) VALUES (?)", (mid,))
        conn.commit()
        newly_applied.append(mid)

    return newly_applied
