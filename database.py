"""
SQLite storage layer — schema creation, CRUD, deduplication, queries.
All data flows through this module.
Supports both local SQLite and Turso cloud SQLite via TURSO_DATABASE_URL.
"""

import os
import sqlite3
from datetime import date, datetime, timedelta
from typing import Optional

import config

DB_PATH = os.path.join(os.path.dirname(__file__), "data", config.DB_FILENAME)

# Turso cloud database support
TURSO_DATABASE_URL = os.environ.get("TURSO_DATABASE_URL", "")
TURSO_AUTH_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")
_USE_TURSO = bool(TURSO_DATABASE_URL)


def _is_valid_date(s: str) -> bool:
    """Check if a string is a valid ISO date (not 'unknown' or empty)."""
    if not s or s == "unknown":
        return False
    try:
        date.fromisoformat(s)
        return True
    except (ValueError, TypeError):
        return False


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    if _USE_TURSO:
        from turso_client import TursoConnection
        return TursoConnection(TURSO_DATABASE_URL, TURSO_AUTH_TOKEN)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str = DB_PATH) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS statements (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        filename        TEXT NOT NULL,
        account_id      TEXT NOT NULL,
        period_start    TEXT NOT NULL,
        period_end      TEXT NOT NULL,
        sha256          TEXT NOT NULL UNIQUE,
        upload_ts       TEXT NOT NULL DEFAULT (datetime('now')),
        status          TEXT NOT NULL DEFAULT 'processed',
        transaction_count INTEGER DEFAULT 0,
        notes           TEXT
    );

    CREATE TABLE IF NOT EXISTS transactions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        date            TEXT NOT NULL,
        description     TEXT NOT NULL,
        raw_description TEXT,
        amount          REAL NOT NULL,
        category        TEXT NOT NULL,
        account_id      TEXT NOT NULL,
        statement_id    INTEGER REFERENCES statements(id),
        confidence      REAL DEFAULT 1.0,
        notes           TEXT,
        created_ts      TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(date, amount, raw_description, account_id)
    );

    CREATE TABLE IF NOT EXISTS conversations (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id  TEXT NOT NULL,
        role        TEXT NOT NULL,
        content     TEXT NOT NULL,
        ts          TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS objectives (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        objective_id    TEXT NOT NULL,
        current_amount  REAL NOT NULL,
        snapshot_date   TEXT NOT NULL,
        notes           TEXT
    );

    CREATE TABLE IF NOT EXISTS alerts (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        alert_type  TEXT NOT NULL,
        severity    TEXT NOT NULL DEFAULT 'info',
        title       TEXT NOT NULL,
        body        TEXT,
        created_ts  TEXT NOT NULL DEFAULT (datetime('now')),
        dismissed   INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS weekly_reports (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        report_date TEXT NOT NULL,
        subject     TEXT,
        html_body   TEXT,
        plain_text  TEXT,
        sent        INTEGER DEFAULT 0,
        created_ts  TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS settings (
        key         TEXT PRIMARY KEY,
        value       TEXT,
        encrypted   INTEGER DEFAULT 0,
        updated_ts  TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS custom_objectives (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        objective_id    TEXT UNIQUE NOT NULL,
        label           TEXT NOT NULL,
        description     TEXT,
        target          REAL,
        target_rate     REAL,
        deadline        TEXT,
        priority        INTEGER DEFAULT 50,
        category_track  TEXT,
        is_active       INTEGER DEFAULT 1,
        created_ts      TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS weekly_upload_status (
        week_start   TEXT NOT NULL,
        account_id   TEXT NOT NULL,
        uploaded     INTEGER DEFAULT 0,
        uploaded_ts  TEXT,
        PRIMARY KEY (week_start, account_id)
    );

    CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(date);
    CREATE INDEX IF NOT EXISTS idx_txn_category ON transactions(category);
    CREATE INDEX IF NOT EXISTS idx_txn_account ON transactions(account_id);
    CREATE INDEX IF NOT EXISTS idx_stmt_account ON statements(account_id);
    CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations(session_id);
    """)
    conn.commit()

    # Run pending schema migrations
    import migrations
    applied = migrations.run_pending(conn)
    if applied:
        print(f"Applied migrations: {', '.join(applied)}")

    conn.close()


# ── Statements ────────────────────────────────────────────────────────────

def check_duplicate_statement(conn: sqlite3.Connection, sha256: str) -> bool:
    row = conn.execute("SELECT id FROM statements WHERE sha256 = ?", (sha256,)).fetchone()
    return row is not None


def check_overlapping_period(conn, account_id: str, period_start: str, period_end: str) -> list:
    """Find any existing statements whose period overlaps the given range."""
    rows = conn.execute("""
        SELECT * FROM statements
        WHERE account_id = ?
          AND period_start <= ? AND period_end >= ?
    """, (account_id, period_end, period_start)).fetchall()
    return rows


def classify_upload(conn, account_id: str, period_start: str, period_end: str, file_hash: str) -> dict:
    """Smart classification of an incoming upload.
    Checks for exact duplicate, period overlap, and coverage gaps.

    Returns:
        {
            "status": "new" | "duplicate_file" | "duplicate_period" | "overlapping" | "extends",
            "message": "Human-readable explanation",
            "overlapping_statements": [...],
            "action": "import" | "skip" | "ask_user",
            "coverage_before": {...},
            "new_transactions_likely": True/False
        }
    """
    # Check 1: Exact same file bytes (SHA-256 match)
    if check_duplicate_statement(conn, file_hash):
        existing = conn.execute("SELECT * FROM statements WHERE sha256 = ?", (file_hash,)).fetchone()
        return {
            "status": "duplicate_file",
            "message": f"This exact file was already uploaded on {existing['upload_ts'][:10]} as '{existing['filename']}'.",
            "overlapping_statements": [dict(existing)],
            "action": "skip",
            "new_transactions_likely": False,
        }

    # Check 2: Exact same period for this account
    exact_match = conn.execute("""
        SELECT * FROM statements
        WHERE account_id = ? AND period_start = ? AND period_end = ?
    """, (account_id, period_start, period_end)).fetchall()
    if exact_match:
        existing = exact_match[0]
        return {
            "status": "duplicate_period",
            "message": f"A statement for {account_id} covering {period_start} to {period_end} already exists "
                       f"('{existing['filename']}', {existing['transaction_count']} transactions). "
                       f"This may be a re-download of the same statement.",
            "overlapping_statements": [dict(s) for s in exact_match],
            "action": "ask_user",
            "new_transactions_likely": False,
        }

    # Check 3: Partial overlap
    overlapping = check_overlapping_period(conn, account_id, period_start, period_end)
    if overlapping:
        overlap_details = []
        for s in overlapping:
            overlap_details.append(f"'{s['filename']}' ({s['period_start']} to {s['period_end']}, {s['transaction_count']} txns)")

        # Determine if this extends coverage
        existing_starts = [s["period_start"] for s in overlapping]
        existing_ends = [s["period_end"] for s in overlapping]
        extends_earlier = period_start < min(existing_starts)
        extends_later = period_end > max(existing_ends)

        if extends_earlier or extends_later:
            direction = []
            if extends_earlier:
                direction.append(f"earlier (from {period_start} vs existing {min(existing_starts)})")
            if extends_later:
                direction.append(f"later (to {period_end} vs existing {max(existing_ends)})")

            return {
                "status": "extends",
                "message": f"This statement overlaps with existing data but EXTENDS coverage {' and '.join(direction)}. "
                           f"Overlaps with: {'; '.join(overlap_details)}. "
                           f"New transactions from the non-overlapping dates will be imported; duplicates will be skipped automatically.",
                "overlapping_statements": [dict(s) for s in overlapping],
                "action": "import",
                "new_transactions_likely": True,
            }
        else:
            return {
                "status": "overlapping",
                "message": f"This period ({period_start} to {period_end}) is fully contained within existing data. "
                           f"Overlaps with: {'; '.join(overlap_details)}. "
                           f"Any new transactions will still be imported (duplicates are skipped automatically).",
                "overlapping_statements": [dict(s) for s in overlapping],
                "action": "ask_user",
                "new_transactions_likely": False,
            }

    # Check 4: Brand new period — no overlap at all
    return {
        "status": "new",
        "message": f"New statement period for {account_id}: {period_start} to {period_end}. No overlap with existing data.",
        "overlapping_statements": [],
        "action": "import",
        "new_transactions_likely": True,
    }


def get_account_coverage(conn) -> dict:
    """Get a summary of what periods are covered for each account.

    Returns:
        {
            "chase_4730": {
                "statements": 3,
                "earliest": "2025-01-29",
                "latest": "2025-04-27",
                "total_transactions": 145,
                "gaps": [{"from": "2025-02-28", "to": "2025-03-28", "days": 28}],
                "months_covered": ["2025-01", "2025-02", "2025-03", "2025-04"],
            },
            ...
        }
    """
    accounts = {}
    stmts = conn.execute("SELECT * FROM statements ORDER BY account_id, period_start").fetchall()

    for s in stmts:
        acct = s["account_id"]
        p_start = s["period_start"]
        p_end = s["period_end"]

        if acct not in accounts:
            accounts[acct] = {
                "statements": 0,
                "earliest": p_start if _is_valid_date(p_start) else None,
                "latest": p_end if _is_valid_date(p_end) else None,
                "total_transactions": 0,
                "periods": [],
            }
        entry = accounts[acct]
        entry["statements"] += 1
        entry["total_transactions"] += (s["transaction_count"] or 0)
        entry["periods"].append({"start": p_start, "end": p_end, "filename": s["filename"]})
        if _is_valid_date(p_start):
            if entry["earliest"] is None or p_start < entry["earliest"]:
                entry["earliest"] = p_start
        if _is_valid_date(p_end):
            if entry["latest"] is None or p_end > entry["latest"]:
                entry["latest"] = p_end

    # Detect gaps between consecutive statements
    for acct, entry in accounts.items():
        # Filter out invalid dates before processing
        valid_periods = [p for p in entry["periods"] if _is_valid_date(p["start"]) and _is_valid_date(p["end"])]
        sorted_periods = sorted(valid_periods, key=lambda p: p["start"])
        gaps = []
        for i in range(1, len(sorted_periods)):
            prev_end = sorted_periods[i - 1]["end"]
            curr_start = sorted_periods[i]["start"]
            if curr_start > prev_end:
                gap_days = (date.fromisoformat(curr_start) - date.fromisoformat(prev_end)).days
                if gap_days > 1:
                    gaps.append({"from": prev_end, "to": curr_start, "days": gap_days})
        entry["gaps"] = gaps

        # Compute months covered
        months = set()
        for p in sorted_periods:
            try:
                start = date.fromisoformat(p["start"])
                end = date.fromisoformat(p["end"])
                current = start.replace(day=1)
                while current <= end:
                    months.add(current.strftime("%Y-%m"))
                    if current.month == 12:
                        current = current.replace(year=current.year + 1, month=1)
                    else:
                        current = current.replace(month=current.month + 1)
            except (ValueError, TypeError):
                continue
        entry["months_covered"] = sorted(months)
        del entry["periods"]

    return accounts


def insert_statement(conn, filename, account_id, period_start, period_end, sha256, status="processed", notes=None) -> int:
    cur = conn.execute("""
        INSERT INTO statements (filename, account_id, period_start, period_end, sha256, status, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (filename, account_id, period_start, period_end, sha256, status, notes))
    conn.commit()
    return cur.lastrowid


def get_all_statements(conn, account_id: Optional[str] = None) -> list:
    if account_id:
        return conn.execute(
            "SELECT * FROM statements WHERE account_id = ? ORDER BY period_start DESC", (account_id,)
        ).fetchall()
    return conn.execute("SELECT * FROM statements ORDER BY period_start DESC").fetchall()


def update_statement_txn_count(conn, statement_id: int, count: int) -> None:
    conn.execute("UPDATE statements SET transaction_count = ? WHERE id = ?", (count, statement_id))
    conn.commit()


# ── Transactions ──────────────────────────────────────────────────────────

def bulk_insert_transactions(conn, transactions: list[dict]) -> int:
    """Insert transactions with basic date validation.
    Rejects only invalid dates and dates more than 30 days in the future.
    All historical dates are accepted — more data = better forecasts.
    Returns count of successfully inserted transactions.
    """
    from datetime import date as _date
    today = _date.today()
    newest_allowed = today + timedelta(days=30)

    inserted = 0
    rejected = 0
    for txn in transactions:
        # Date validation — only reject invalid format or future dates
        txn_date_str = txn.get("date", "")
        try:
            txn_date = _date.fromisoformat(txn_date_str)
            if txn_date > newest_allowed:
                rejected += 1
                continue  # Future date — skip
        except (ValueError, TypeError):
            rejected += 1
            continue  # Invalid date format — skip

        try:
            conn.execute("""
                INSERT OR IGNORE INTO transactions
                    (date, description, raw_description, amount, category, account_id, statement_id, confidence, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                txn_date_str,
                txn["description"],
                txn.get("raw_description", txn["description"]),
                txn["amount"],
                txn["category"],
                txn["account_id"],
                txn.get("statement_id"),
                txn.get("confidence", 1.0),
                txn.get("notes", ""),
            ))
            inserted += 1
        except sqlite3.IntegrityError:
            pass  # duplicate, skip
    conn.commit()
    return inserted


def get_transactions(
    conn,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    account_id: Optional[str] = None,
    category: Optional[str] = None,
) -> list:
    query = "SELECT * FROM transactions WHERE 1=1"
    params = []
    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)
    if account_id:
        query += " AND account_id = ?"
        params.append(account_id)
    if category:
        query += " AND category = ?"
        params.append(category)
    query += " ORDER BY date DESC"
    return conn.execute(query, params).fetchall()


def get_monthly_summary(conn, year: int, month: int) -> dict:
    start = f"{year:04d}-{month:02d}-01"
    if month == 12:
        end = f"{year + 1:04d}-01-01"
    else:
        end = f"{year:04d}-{month + 1:02d}-01"

    rows = conn.execute("""
        SELECT category, SUM(amount) as total, COUNT(*) as count
        FROM transactions
        WHERE date >= ? AND date < ?
        GROUP BY category
        ORDER BY total ASC
    """, (start, end)).fetchall()

    result = {"year": year, "month": month, "categories": {}, "total": 0.0, "transaction_count": 0}
    for r in rows:
        result["categories"][r["category"]] = {"total": r["total"], "count": r["count"]}
        result["total"] += r["total"]
        result["transaction_count"] += r["count"]
    return result


def get_category_breakdown(conn, start_date: str, end_date: str) -> list[dict]:
    rows = conn.execute("""
        SELECT category, SUM(amount) as total, COUNT(*) as count, AVG(amount) as avg_amount
        FROM transactions
        WHERE date >= ? AND date <= ?
        GROUP BY category
        ORDER BY total ASC
    """, (start_date, end_date)).fetchall()
    return [dict(r) for r in rows]


def get_spending_trend(conn, months: int = 12) -> list[dict]:
    rows = conn.execute("""
        SELECT strftime('%Y-%m', date) as month,
               SUM(CASE WHEN amount < 0 THEN amount ELSE 0 END) as spending,
               SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) as income,
               COUNT(*) as txn_count
        FROM transactions
        GROUP BY strftime('%Y-%m', date)
        ORDER BY month DESC
        LIMIT ?
    """, (months,)).fetchall()
    return [dict(r) for r in rows]


def update_transaction_category(conn, txn_id: int, new_category: str) -> None:
    conn.execute("UPDATE transactions SET category = ? WHERE id = ?", (new_category, txn_id))
    conn.commit()


def get_monthly_category_breakdown(conn, year_month: str) -> list[dict]:
    """Get spending by category for a specific month (format: YYYY-MM).
    Returns sorted by total spend (most expensive first).
    """
    rows = conn.execute("""
        SELECT category,
               SUM(amount) as total,
               COUNT(*) as txn_count,
               AVG(amount) as avg_per_txn,
               MIN(amount) as largest_charge,
               GROUP_CONCAT(description, ' | ') as merchants
        FROM transactions
        WHERE strftime('%Y-%m', date) = ? AND amount < 0
        GROUP BY category
        ORDER BY total ASC
    """, (year_month,)).fetchall()
    return [dict(r) for r in rows]


def get_merchant_breakdown_for_month(conn, category: str, year_month: str, limit: int = 6) -> list[dict]:
    """Get top merchants by spend for a category in a given month."""
    rows = conn.execute("""
        SELECT description as name, SUM(amount) as total, COUNT(*) as visits
        FROM transactions
        WHERE strftime('%Y-%m', date) = ? AND category = ? AND amount < 0
        GROUP BY description
        ORDER BY total ASC
        LIMIT ?
    """, (year_month, category, limit)).fetchall()
    return [dict(r) for r in rows]


def get_category_monthly_history(conn, category: str, months: int = 6) -> list[dict]:
    """Get a specific category's spending per month for trend analysis."""
    rows = conn.execute("""
        SELECT strftime('%Y-%m', date) as month,
               SUM(amount) as total,
               COUNT(*) as txn_count
        FROM transactions
        WHERE category = ? AND amount < 0
        GROUP BY strftime('%Y-%m', date)
        ORDER BY month DESC
        LIMIT ?
    """, (category, months)).fetchall()
    return [dict(r) for r in rows]


def get_available_months(conn) -> list[str]:
    """Get all months that have transaction data, newest first."""
    rows = conn.execute("""
        SELECT DISTINCT strftime('%Y-%m', date) as month
        FROM transactions
        ORDER BY month DESC
    """).fetchall()
    return [r["month"] for r in rows]


def get_category_trend(conn, category: str, months: int = 4) -> dict:
    """Compute trend for a category: increasing, decreasing, or stable.
    Compares the most recent month to the average of prior months.

    Returns: {"direction": "increasing"|"decreasing"|"stable",
              "current": float, "prior_avg": float, "pct_change": float}
    """
    history = get_category_monthly_history(conn, category, months)
    if len(history) < 2:
        return {"direction": "stable", "current": abs(history[0]["total"]) if history else 0,
                "prior_avg": 0, "pct_change": 0}

    current = abs(history[0]["total"])
    prior = [abs(h["total"]) for h in history[1:]]
    prior_avg = sum(prior) / len(prior) if prior else 0

    if prior_avg == 0:
        return {"direction": "new", "current": current, "prior_avg": 0, "pct_change": 0}

    pct_change = ((current - prior_avg) / prior_avg) * 100

    if pct_change > 15:
        direction = "increasing"
    elif pct_change < -15:
        direction = "decreasing"
    else:
        direction = "stable"

    return {"direction": direction, "current": round(current, 2),
            "prior_avg": round(prior_avg, 2), "pct_change": round(pct_change, 1)}


def get_transaction_count(conn) -> int:
    row = conn.execute("SELECT COUNT(*) as c FROM transactions").fetchone()
    return row["c"]


def get_date_range(conn) -> tuple:
    row = conn.execute("SELECT MIN(date) as min_d, MAX(date) as max_d FROM transactions").fetchone()
    return row["min_d"], row["max_d"]


# ── Conversations ─────────────────────────────────────────────────────────

def save_conversation(conn, session_id: str, role: str, content: str) -> None:
    conn.execute(
        "INSERT INTO conversations (session_id, role, content) VALUES (?, ?, ?)",
        (session_id, role, content),
    )
    conn.commit()


def get_conversation(conn, session_id: str, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT role, content, ts FROM conversations WHERE session_id = ? ORDER BY ts ASC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


# ── Objectives ────────────────────────────────────────────────────────────

def snapshot_objective(conn, objective_id: str, current_amount: float, snapshot_date: str, notes: str = "") -> None:
    conn.execute(
        "INSERT INTO objectives (objective_id, current_amount, snapshot_date, notes) VALUES (?, ?, ?, ?)",
        (objective_id, current_amount, snapshot_date, notes),
    )
    conn.commit()


def get_objective_history(conn, objective_id: str) -> list:
    return conn.execute(
        "SELECT * FROM objectives WHERE objective_id = ? ORDER BY snapshot_date ASC",
        (objective_id,),
    ).fetchall()


def delete_monarch_duplicates(conn) -> int:
    """Remove Monarch-synced transactions that duplicate an existing PDF/CSV transaction.
    Match criteria: same date + same amount (within $0.01).
    Keeps the PDF/CSV version (higher confidence, established categories).
    Returns count of deleted rows.
    """
    dupes = conn.execute("""
        SELECT DISTINCT t1.id
        FROM transactions t1
        JOIN transactions t2
            ON t1.date = t2.date
            AND ABS(t1.amount - t2.amount) < 0.01
            AND t1.id != t2.id
        WHERE t1.notes = 'monarch_sync'
            AND (t2.notes != 'monarch_sync' OR t2.notes IS NULL)
    """).fetchall()
    ids = [d["id"] for d in dupes]
    if ids:
        placeholders = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM transactions WHERE id IN ({placeholders})", ids)
        conn.commit()
    return len(ids)


# ── Alerts ────────────────────────────────────────────────────────────────

def insert_alert(conn, alert_type: str, severity: str, title: str, body: str = "") -> int:
    cur = conn.execute(
        "INSERT INTO alerts (alert_type, severity, title, body) VALUES (?, ?, ?, ?)",
        (alert_type, severity, title, body),
    )
    conn.commit()
    return cur.lastrowid


def get_active_alerts(conn, limit: int = 20) -> list:
    return conn.execute(
        "SELECT * FROM alerts WHERE dismissed = 0 ORDER BY created_ts DESC LIMIT ?", (limit,)
    ).fetchall()


def dismiss_alert(conn, alert_id: int) -> None:
    conn.execute("UPDATE alerts SET dismissed = 1 WHERE id = ?", (alert_id,))
    conn.commit()


# ── Weekly Reports ────────────────────────────────────────────────────────

def save_weekly_report(conn, report_date: str, subject: str, html_body: str, plain_text: str) -> int:
    cur = conn.execute(
        "INSERT INTO weekly_reports (report_date, subject, html_body, plain_text) VALUES (?, ?, ?, ?)",
        (report_date, subject, html_body, plain_text),
    )
    conn.commit()
    return cur.lastrowid


def get_weekly_reports(conn, limit: int = 10) -> list:
    return conn.execute(
        "SELECT * FROM weekly_reports ORDER BY report_date DESC LIMIT ?", (limit,)
    ).fetchall()


# ── Utility ───────────────────────────────────────────────────────────────

def get_financial_context(conn) -> dict:
    """Build a summary dict for Claude's advisor context."""
    txn_count = get_transaction_count(conn)
    date_range = get_date_range(conn)
    statements = get_all_statements(conn)

    # Last 3 months breakdown
    today = date.today()
    three_months_ago = date(today.year, today.month - 3, 1) if today.month > 3 else date(today.year - 1, today.month + 9, 1)
    recent_breakdown = get_category_breakdown(conn, three_months_ago.isoformat(), today.isoformat())

    # Monthly trend
    trend = get_spending_trend(conn, months=12)

    # Active alerts
    alerts = [dict(a) for a in get_active_alerts(conn)]

    return {
        "transaction_count": txn_count,
        "date_range": {"start": date_range[0], "end": date_range[1]},
        "statements_uploaded": len(statements),
        "accounts_covered": list(set(s["account_id"] for s in statements)) if statements else [],
        "recent_category_breakdown": recent_breakdown,
        "monthly_trend": trend,
        "active_alerts": alerts,
    }


# ── Settings ──────────────────────────────────────────────────────────────

_SENSITIVE_KEYS = {
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
    "telegram_chat_id": "TELEGRAM_CHAT_ID",
    "telegram_chat_id_maggie": "TELEGRAM_CHAT_ID_MAGGIE",
}


def get_setting(conn, key: str, default: str = "") -> str:
    import os
    # Sensitive keys: check env vars first (st.secrets auto-populates os.environ on Cloud)
    env_name = _SENSITIVE_KEYS.get(key)
    if env_name:
        val = os.environ.get(env_name, "")
        if val:
            return val
        # Fallback: parse .env file directly (local dev without dotenv)
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                for line in f:
                    if line.startswith(env_name + "="):
                        val = line.strip().split("=", 1)[1]
                        if val:
                            return val
        return default
    # Non-sensitive keys: read from DB as before
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row and row["value"]:
        return row["value"]
    return default


def set_setting(conn, key: str, value: str) -> None:
    # Sensitive keys: persist to .env only, never to DB
    if key in _SENSITIVE_KEYS:
        _persist_to_env(key, value)
        return
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?, updated_ts = datetime('now')",
        (key, value, value),
    )
    conn.commit()
    _persist_to_env(key, value)


def _persist_to_env(key: str, value: str) -> None:
    """Save critical settings to .env file as backup."""
    import os
    env_name = _SENSITIVE_KEYS.get(key)
    if not env_name or not value:
        return
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    lines = []
    found = False
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                if line.startswith(env_name + "="):
                    lines.append(f"{env_name}={value}\n")
                    found = True
                else:
                    lines.append(line)
    if not found:
        lines.append(f"{env_name}={value}\n")
    with open(env_path, "w") as f:
        f.writelines(lines)


def get_all_settings(conn) -> dict:
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


def delete_setting(conn, key: str) -> None:
    conn.execute("DELETE FROM settings WHERE key = ?", (key,))
    conn.commit()


# ── Gap Closer Cache ─────────────────────────────────────────────────────

def get_gap_closer_cache(conn, month: str, gap_amount: float) -> dict | None:
    """Retrieve cached gap closer result from DB. Returns None if stale (>24h)."""
    import json
    key = f"gap_closer_{month}_{gap_amount:.0f}"
    raw = get_setting(conn, key, "")
    if not raw:
        return None
    try:
        data = json.loads(raw)
        cached_at = datetime.fromisoformat(data.get("_cached_at", ""))
        if (datetime.now() - cached_at).total_seconds() > 86400:
            return None
        return data
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def set_gap_closer_cache(conn, month: str, gap_amount: float, result: dict):
    """Persist gap closer result to DB with timestamp."""
    import json
    key = f"gap_closer_{month}_{gap_amount:.0f}"
    result["_cached_at"] = datetime.now().isoformat()
    set_setting(conn, key, json.dumps(result, default=str))


# ── Budget Coach Cache ───────────────────────────────────────────────

def get_coach_cache(conn, mode: str, month: str, data_hash: str) -> dict | None:
    """Retrieve cached coach result. Returns None if stale (>24h)."""
    import json
    key = f"coach_{mode}_{month}_{data_hash}"
    raw = get_setting(conn, key, "")
    if not raw:
        return None
    try:
        data = json.loads(raw)
        cached_at = datetime.fromisoformat(data.get("_cached_at", ""))
        if (datetime.now() - cached_at).total_seconds() > 86400:
            return None
        return data
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def set_coach_cache(conn, mode: str, month: str, data_hash: str, result: dict):
    """Persist coach result to DB with timestamp."""
    import json
    key = f"coach_{mode}_{month}_{data_hash}"
    result["_cached_at"] = datetime.now().isoformat()
    set_setting(conn, key, json.dumps(result, default=str))


# ── Weekly Upload Cycle ──────────────────────────────────────────────────

WEEKLY_ACCOUNTS = ["chase_4730", "chase_3072", "joint_checking"]


def get_current_week_start() -> str:
    """Return the most recent Tuesday as an ISO date string."""
    today = date.today()
    # weekday(): Monday=0 … Sunday=6.  Tuesday=1.
    days_since_tuesday = (today.weekday() - 1) % 7
    tuesday = today - timedelta(days=days_since_tuesday)
    return tuesday.isoformat()


def init_weekly_cycle(conn, week_start: str) -> None:
    """Create rows for each tracked account if they don't already exist."""
    for account_id in WEEKLY_ACCOUNTS:
        conn.execute(
            "INSERT OR IGNORE INTO weekly_upload_status (week_start, account_id, uploaded) VALUES (?, ?, 0)",
            (week_start, account_id),
        )
    conn.commit()


def mark_account_uploaded(conn, week_start: str, account_id: str) -> None:
    """Mark an account as uploaded for the given week."""
    conn.execute(
        "UPDATE weekly_upload_status SET uploaded = 1, uploaded_ts = datetime('now') "
        "WHERE week_start = ? AND account_id = ?",
        (week_start, account_id),
    )
    conn.commit()


def get_weekly_status(conn, week_start: str) -> dict:
    """Return dict {account_id: {'uploaded': bool, 'uploaded_ts': str|None}}."""
    rows = conn.execute(
        "SELECT account_id, uploaded, uploaded_ts FROM weekly_upload_status WHERE week_start = ?",
        (week_start,),
    ).fetchall()
    return {
        r["account_id"]: {"uploaded": bool(r["uploaded"]), "uploaded_ts": r["uploaded_ts"]}
        for r in rows
    }


def is_week_complete(conn, week_start: str) -> bool:
    """Return True if all tracked accounts have been uploaded for the week."""
    row = conn.execute(
        "SELECT COUNT(*) as pending FROM weekly_upload_status "
        "WHERE week_start = ? AND uploaded = 0",
        (week_start,),
    ).fetchone()
    # Also make sure cycle was initialised (rows exist)
    total = conn.execute(
        "SELECT COUNT(*) as total FROM weekly_upload_status WHERE week_start = ?",
        (week_start,),
    ).fetchone()
    if total["total"] == 0:
        return False
    return row["pending"] == 0


# ── Custom Objectives ─────────────────────────────────────────────────────

def seed_default_objectives(conn) -> None:
    """Insert default objectives from config if they don't exist yet."""
    for obj in config.OBJECTIVES:
        existing = conn.execute(
            "SELECT id FROM custom_objectives WHERE objective_id = ?", (obj["id"],)
        ).fetchone()
        if not existing:
            conn.execute("""
                INSERT INTO custom_objectives (objective_id, label, description, target, deadline, priority)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (obj["id"], obj["label"], obj.get("description", ""), obj.get("target"), obj.get("deadline"), obj.get("priority", 50)))
    conn.commit()


def create_objective(conn, objective_id: str, label: str, description: str = "",
                     target: float = None, target_rate: float = None,
                     deadline: str = None, priority: int = 50, category_track: str = None) -> int:
    cur = conn.execute("""
        INSERT INTO custom_objectives (objective_id, label, description, target, target_rate, deadline, priority, category_track)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (objective_id, label, description, target, target_rate, deadline, priority, category_track))
    conn.commit()
    return cur.lastrowid


def get_active_objectives(conn) -> list:
    return conn.execute(
        "SELECT * FROM custom_objectives WHERE is_active = 1 ORDER BY priority ASC"
    ).fetchall()


def update_objective(conn, objective_id: str, **kwargs) -> None:
    for key, value in kwargs.items():
        if key in ("label", "description", "target", "target_rate", "deadline", "priority", "category_track", "is_active"):
            conn.execute(f"UPDATE custom_objectives SET {key} = ? WHERE objective_id = ?", (value, objective_id))
    conn.commit()


def deactivate_objective(conn, objective_id: str) -> None:
    conn.execute("UPDATE custom_objectives SET is_active = 0 WHERE objective_id = ?", (objective_id,))
    conn.commit()


def get_merchant_spending(conn, months: int = 3) -> list[dict]:
    """Get top merchants by spend for the last N months."""
    today = date.today()
    start = date(today.year, today.month - months, 1) if today.month > months else date(today.year - 1, today.month + 12 - months, 1)
    rows = conn.execute("""
        SELECT description, COUNT(*) as visits, SUM(amount) as total_spent,
               AVG(amount) as avg_per_visit, category
        FROM transactions
        WHERE date >= ? AND amount < 0
        GROUP BY description
        ORDER BY total_spent ASC
        LIMIT 30
    """, (start.isoformat(),)).fetchall()
    return [dict(r) for r in rows]


def get_weekly_spending(conn, weeks_back: int = 0, exclude_categories=None) -> dict:
    """Get spending for a specific week (0=current, 1=last week, etc.).

    Args:
        exclude_categories: Category names to filter out (e.g. config.EXCLUDED_CATEGORIES).
    """
    today = date.today()
    week_end = today - timedelta(days=7 * weeks_back)
    week_start = week_end - timedelta(days=7)
    rows = conn.execute("""
        SELECT category, SUM(amount) as total, COUNT(*) as count
        FROM transactions
        WHERE date >= ? AND date <= ? AND amount < 0
        GROUP BY category
        ORDER BY total ASC
    """, (week_start.isoformat(), week_end.isoformat())).fetchall()
    excl = exclude_categories or set()
    filtered = [r for r in rows if r["category"] not in excl]
    return {
        "start": week_start.isoformat(),
        "end": week_end.isoformat(),
        "categories": {r["category"]: {"total": r["total"], "count": r["count"]} for r in filtered},
        "total": sum(r["total"] for r in filtered),
    }


def get_weekly_merchants(conn, start_date: str, end_date: str,
                         exclude_categories=None) -> list:
    """Get top merchants by spend for a specific date range."""
    rows = conn.execute("""
        SELECT description, COUNT(*) as visits, SUM(amount) as total_spent,
               category
        FROM transactions
        WHERE date >= ? AND date <= ? AND amount < 0
        GROUP BY description
        ORDER BY total_spent ASC
        LIMIT 20
    """, (start_date, end_date)).fetchall()
    excl = exclude_categories or set()
    return [dict(r) for r in rows if r["category"] not in excl]


def get_month_weekly_breakdown(conn, year: int, month: int,
                               exclude_categories=None,
                               fixed_categories=None) -> list:
    """Split a month's spending into calendar weeks (flex only).

    Args:
        exclude_categories: Internal transfers to ignore completely.
        fixed_categories: Fixed bills to exclude from flex tracking.

    Returns list of dicts: [{week_num, start, end, total, txn_count}, ...]
    """
    from calendar import monthrange
    days_in_month = monthrange(year, month)[1]
    month_start = date(year, month, 1)
    all_excl = (exclude_categories or set()) | (fixed_categories or set())

    weeks = []
    week_num = 1
    day = 1
    while day <= days_in_month:
        wk_start = date(year, month, day)
        wk_end_day = min(day + 6, days_in_month)
        wk_end = date(year, month, wk_end_day)

        rows = conn.execute("""
            SELECT SUM(amount) as total, COUNT(*) as count
            FROM transactions
            WHERE date >= ? AND date <= ? AND amount < 0
              AND category NOT IN ({})
        """.format(",".join("?" for _ in all_excl)),
            (wk_start.isoformat(), wk_end.isoformat(), *all_excl)
        ).fetchone()

        weeks.append({
            "week_num": week_num,
            "start": wk_start.isoformat(),
            "end": wk_end.isoformat(),
            "total": abs(rows["total"]) if rows["total"] else 0,
            "txn_count": rows["count"] if rows["count"] else 0,
        })
        week_num += 1
        day = wk_end_day + 1

    return weeks


# ── Category Analytics Cache ─────────────────────────────────────────────

def upsert_category_analytics(conn, category: str, scope: str, data_json: str) -> None:
    """Insert or update cached analytics for a category/scope."""
    conn.execute("""
        INSERT INTO category_analytics (category, scope, analysis_json, updated_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(category, scope) DO UPDATE SET
            analysis_json = excluded.analysis_json,
            updated_at = datetime('now')
    """, (category, scope, data_json))
    conn.commit()


def get_all_cached_analytics(conn) -> list:
    """Return all cached analytics rows."""
    return conn.execute(
        "SELECT category, scope, analysis_json, updated_at FROM category_analytics ORDER BY category"
    ).fetchall()


def get_cached_analytics_for(conn, category: str, scope: str = "monthly") -> Optional[str]:
    """Return cached analytics JSON for a specific category/scope, or None."""
    row = conn.execute(
        "SELECT analysis_json FROM category_analytics WHERE category = ? AND scope = ?",
        (category, scope),
    ).fetchone()
    return row["analysis_json"] if row else None


def get_analytics_last_refresh(conn) -> Optional[str]:
    """Return the oldest updated_at from the cache (tells when cache was last fully refreshed)."""
    row = conn.execute("SELECT MIN(updated_at) as oldest FROM category_analytics").fetchone()
    return row["oldest"] if row and row["oldest"] else None


def clear_analytics_cache(conn) -> None:
    """Delete all cached analytics (forces full recompute)."""
    conn.execute("DELETE FROM category_analytics")
    conn.commit()


# ── Data Completeness ────────────────────────────────────────────────────

def get_missing_months(conn) -> list[dict]:
    """Return months without transaction data between earliest and latest, per account.
    Returns list of {account_id, year_month, label} sorted by recency."""
    # Get the range of data per account
    accounts = conn.execute("""
        SELECT DISTINCT account_id,
               MIN(date) as earliest,
               MAX(date) as latest
        FROM transactions
        WHERE date LIKE '____-__-__'
        GROUP BY account_id
    """).fetchall()

    missing = []
    for acct in accounts:
        aid = acct["account_id"]
        try:
            start = date.fromisoformat(acct["earliest"])
            end = date.fromisoformat(acct["latest"])
        except (ValueError, TypeError):
            continue

        # Generate all months in range
        current = start.replace(day=1)
        end_month = end.replace(day=1)
        while current <= end_month:
            ym = current.strftime("%Y-%m")
            # Check if this month has transactions
            row = conn.execute(
                "SELECT COUNT(*) as c FROM transactions WHERE account_id = ? AND strftime('%Y-%m', date) = ?",
                (aid, ym),
            ).fetchone()
            if row["c"] == 0:
                missing.append({"account_id": aid, "year_month": ym})
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

    # Sort by recency (newest gaps first)
    return sorted(missing, key=lambda x: x["year_month"], reverse=True)


# ── Savings Snapshots ────────────────────────────────────────────────────

def upsert_savings_snapshot(conn, month: str, actual_net: float, target: float, cumulative: float) -> None:
    """Insert or update a monthly savings snapshot."""
    conn.execute("""
        INSERT INTO savings_snapshots (month, actual_net, target, cumulative)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(month) DO UPDATE SET
            actual_net = excluded.actual_net,
            target = excluded.target,
            cumulative = excluded.cumulative
    """, (month, actual_net, target, cumulative))
    conn.commit()


def get_savings_snapshots(conn, limit: int = 24) -> list:
    """Return recent savings snapshots for charting."""
    return conn.execute(
        "SELECT * FROM savings_snapshots ORDER BY month DESC LIMIT ?", (limit,)
    ).fetchall()


# ── Category Definitions ─────────────────────────────────────────────────

def get_category_definitions(conn) -> list:
    """Return all active category definitions, ordered by sort_order."""
    return conn.execute(
        "SELECT * FROM category_definitions WHERE is_active = 1 ORDER BY sort_order, name"
    ).fetchall()


def upsert_category_definition(conn, name: str, parent: str = None,
                                description: str = "", color: str = None,
                                sort_order: int = 50) -> None:
    """Insert or update a category definition."""
    conn.execute("""
        INSERT INTO category_definitions (name, parent, description, color, sort_order)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            parent = excluded.parent,
            description = excluded.description,
            color = COALESCE(excluded.color, category_definitions.color),
            sort_order = excluded.sort_order
    """, (name, parent, description, color, sort_order))
    conn.commit()
