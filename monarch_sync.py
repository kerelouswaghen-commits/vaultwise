"""
Monarch Money integration — authentication, account/category mapping, transaction sync.
All Monarch API interaction flows through this module.

Uses curl_cffi instead of the monarchmoney library's aiohttp transport to bypass
Cloudflare's TLS fingerprinting (aiohttp gets blocked with 403/525 errors).
"""

import json
import os
import pickle
from datetime import datetime, timedelta

from curl_cffi import requests as curl_requests

import config
import database

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_URL = "https://api.monarch.com"
LOGIN_URL = f"{BASE_URL}/auth/login/"
GRAPHQL_URL = f"{BASE_URL}/graphql"

SESSION_DIR = os.path.join(os.path.dirname(__file__), "data")
SESSION_FILE = os.path.join(SESSION_DIR, "monarch_session.json")

FETCH_LIMIT = 500


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------
class MonarchMFARequired(Exception):
    """Raised when Monarch login requires MFA/TOTP code from user."""
    pass


class MonarchEmailOTPRequired(Exception):
    """Raised when Monarch sends an email OTP code for device verification."""
    pass


class MonarchNotConfigured(Exception):
    """Raised when credentials are missing."""
    pass


class MonarchAuthFailed(Exception):
    """Raised when login fails (bad credentials or expired session)."""
    pass


# ---------------------------------------------------------------------------
# HTTP helpers (curl_cffi with Chrome TLS fingerprint)
# ---------------------------------------------------------------------------
def _base_headers(token: str = "", device_uuid: str = "") -> dict:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Client-Platform": "web",
    }
    if token:
        headers["Authorization"] = f"Token {token}"
    if device_uuid:
        headers["Device-UUID"] = device_uuid
    return headers


def _post(url: str, data: dict, headers: dict) -> curl_requests.Response:
    return curl_requests.post(url, json=data, headers=headers, impersonate="chrome", timeout=30)


# ---------------------------------------------------------------------------
# Session persistence (simple JSON token store)
# ---------------------------------------------------------------------------
def _save_session(token: str) -> None:
    os.makedirs(SESSION_DIR, exist_ok=True)
    with open(SESSION_FILE, "w") as f:
        json.dump({"token": token, "saved_at": datetime.now().isoformat()}, f)


def _load_session() -> str | None:
    if not os.path.exists(SESSION_FILE):
        return None
    try:
        with open(SESSION_FILE) as f:
            data = json.load(f)
        return data.get("token", None)
    except (json.JSONDecodeError, OSError):
        return None


def _delete_session() -> None:
    for path in [SESSION_FILE, os.path.join(SESSION_DIR, "monarch_session.pickle")]:
        try:
            os.remove(path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
def _login(email: str, password: str, device_uuid: str = "",
           mfa_code: str = "", email_otp: str = "") -> str:
    """
    Login to Monarch Money and return the auth token.
    Raises MonarchMFARequired, MonarchEmailOTPRequired, or MonarchAuthFailed.
    """
    payload = {
        "username": email,
        "password": password,
        "supports_mfa": True,
        "supports_email_otp": True,
        "trusted_device": True,
    }
    if mfa_code:
        payload["totp"] = mfa_code
    if email_otp:
        payload["email_otp"] = email_otp

    headers = _base_headers(device_uuid=device_uuid)
    resp = _post(LOGIN_URL, payload, headers)

    # Parse response body
    try:
        body = resp.json()
    except (json.JSONDecodeError, ValueError):
        body = {}

    error_code = body.get("error_code", "")
    detail = body.get("detail", "")

    if resp.status_code == 403 or error_code:
        if error_code == "EMAIL_OTP_REQUIRED" or "update" in detail.lower():
            # Monarch sent an OTP code to the user's email
            raise MonarchEmailOTPRequired(
                "Monarch sent a verification code to your email. Enter it below."
            )
        if error_code == "CAPTCHA_REQUIRED":
            raise MonarchAuthFailed(
                "Too many login attempts. Wait a few minutes, then try again."
            )
        if "Shall Not Pass" in str(body):
            raise MonarchAuthFailed(
                "Account temporarily locked from too many attempts. Wait 5-10 minutes and try again."
            )
        if "MFA" in detail or error_code == "MFA_REQUIRED":
            raise MonarchMFARequired(detail or "Multi-Factor Auth Required")
        if detail:
            raise MonarchAuthFailed(f"Login failed: {detail}")
        raise MonarchAuthFailed(f"Login failed: HTTP {resp.status_code}")

    if resp.status_code not in (200, 201):
        raise MonarchAuthFailed(f"Login failed: {detail or f'HTTP {resp.status_code}'}")

    token = body.get("token", "")
    if not token:
        raise MonarchAuthFailed("Login succeeded but no token received.")
    return token


def _validate_token(token: str, device_uuid: str = "") -> bool:
    """Check if a saved token is still valid."""
    headers = _base_headers(token=token, device_uuid=device_uuid)
    query = {
        "operationName": "GetSubscriptionDetails",
        "query": "query GetSubscriptionDetails { subscription { id __typename } }",
        "variables": {},
    }
    try:
        resp = _post(GRAPHQL_URL, query, headers)
        return resp.status_code == 200 and "errors" not in resp.json()
    except Exception:
        return False


def get_client(conn) -> dict:
    """
    Return auth context dict {"token": str, "device_uuid": str, "headers": dict}.
    Tries saved session first, then fresh login.
    """
    email = database.get_setting(conn, "monarch_email", "")
    password = database.get_setting(conn, "monarch_password", "")
    if not email or not password:
        raise MonarchNotConfigured("Monarch email/password not set in Settings.")

    device_uuid = database.get_setting(conn, "monarch_device_uuid", "")

    # Try saved session
    saved_token = _load_session()
    if saved_token and _validate_token(saved_token, device_uuid):
        return {
            "token": saved_token,
            "device_uuid": device_uuid,
            "headers": _base_headers(token=saved_token, device_uuid=device_uuid),
        }

    # Fresh login
    _delete_session()
    token = _login(email, password, device_uuid)
    _save_session(token)
    return {
        "token": token,
        "device_uuid": device_uuid,
        "headers": _base_headers(token=token, device_uuid=device_uuid),
    }


def complete_mfa(conn, code: str) -> dict:
    """Complete MFA login with the user-provided TOTP code."""
    email = database.get_setting(conn, "monarch_email", "")
    password = database.get_setting(conn, "monarch_password", "")
    device_uuid = database.get_setting(conn, "monarch_device_uuid", "")
    token = _login(email, password, device_uuid, mfa_code=code)
    _save_session(token)
    return {
        "token": token,
        "device_uuid": device_uuid,
        "headers": _base_headers(token=token, device_uuid=device_uuid),
    }


def complete_email_otp(conn, code: str) -> dict:
    """Complete login with the email OTP code Monarch sent."""
    email = database.get_setting(conn, "monarch_email", "")
    password = database.get_setting(conn, "monarch_password", "")
    device_uuid = database.get_setting(conn, "monarch_device_uuid", "")
    token = _login(email, password, device_uuid, email_otp=code)
    _save_session(token)
    return {
        "token": token,
        "device_uuid": device_uuid,
        "headers": _base_headers(token=token, device_uuid=device_uuid),
    }


def disconnect():
    """Remove saved session and clear Monarch state."""
    _delete_session()


# ---------------------------------------------------------------------------
# GraphQL helpers
# ---------------------------------------------------------------------------
def _gql(client: dict, operation: str, query: str, variables: dict = None) -> dict:
    """Execute a GraphQL query using curl_cffi."""
    payload = {
        "operationName": operation,
        "query": query,
        "variables": variables or {},
    }
    resp = _post(GRAPHQL_URL, payload, client["headers"])
    if resp.status_code == 401:
        raise MonarchAuthFailed("Session expired. Reconnect in Settings.")
    if resp.status_code != 200:
        raise MonarchAuthFailed(f"GraphQL error: HTTP {resp.status_code}")
    data = resp.json()
    if "errors" in data:
        raise MonarchAuthFailed(f"GraphQL error: {data['errors'][0].get('message', 'Unknown')}")
    return data.get("data", {})


# ---------------------------------------------------------------------------
# Account mapping
# ---------------------------------------------------------------------------
_GET_ACCOUNTS_QUERY = """
query GetAccounts {
    accounts {
        id
        displayName
        mask
        currentBalance
        isAsset
        isHidden
        type { name display }
        subtype { name display }
        institution { id name }
    }
}
"""


def fetch_accounts(client: dict) -> list[dict]:
    """Fetch accounts from Monarch and return simplified list."""
    data = _gql(client, "GetAccounts", _GET_ACCOUNTS_QUERY)
    accounts = []
    for acct in data.get("accounts", []):
        if acct.get("isHidden"):
            continue
        accounts.append({
            "id": str(acct["id"]),
            "name": acct.get("displayName", "Unknown"),
            "mask": acct.get("mask", ""),
            "type": acct.get("type", {}).get("name", "") if acct.get("type") else "",
            "subtype": acct.get("subtype", {}).get("name", "") if acct.get("subtype") else "",
            "institution": acct.get("institution", {}).get("name", "") if acct.get("institution") else "",
            "balance": acct.get("currentBalance", 0),
            "is_asset": acct.get("isAsset", True),
        })
    return accounts


def auto_suggest_mapping(monarch_accounts: list[dict]) -> dict:
    """Auto-match Monarch accounts to config.ACCOUNTS by last-4 digits."""
    mapping = {}
    vw_by_last4 = {}
    for acct_id, info in config.ACCOUNTS.items():
        if info.get("last4"):
            vw_by_last4[info["last4"]] = acct_id

    for macct in monarch_accounts:
        mask = macct.get("mask", "")
        if mask and mask in vw_by_last4:
            mapping[macct["id"]] = vw_by_last4[mask]
    return mapping


def get_account_mapping(conn) -> dict:
    raw = database.get_setting(conn, "monarch_account_map", "{}")
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def set_account_mapping(conn, mapping: dict) -> None:
    database.set_setting(conn, "monarch_account_map", json.dumps(mapping))


# ---------------------------------------------------------------------------
# Category mapping
# ---------------------------------------------------------------------------
_CATEGORY_KEYWORDS = {
    "food & drink": "Dining Out",
    "restaurants": "Dining Out",
    "dining": "Dining Out",
    "coffee": "Dining Out",
    "fast food": "Dining Out",
    "groceries": "Groceries",
    "grocery": "Groceries",
    "supermarket": "Groceries",
    "gas": "Gas",
    "fuel": "Gas",
    "auto": "Transportation",
    "transport": "Transportation",
    "ride share": "Transportation",
    "parking": "Transportation",
    "public transit": "Transportation",
    "insurance": "Car Insurance",
    "auto insurance": "Car Insurance",
    "home": "Housing & Utilities",
    "rent": "Housing & Utilities",
    "mortgage": "Housing & Utilities",
    "utilities": "Housing & Utilities",
    "electric": "Housing & Utilities",
    "water": "Housing & Utilities",
    "internet": "Phone & Internet",
    "phone": "Phone & Internet",
    "mobile phone": "Phone & Internet",
    "television": "Subscriptions & Streaming",
    "streaming": "Subscriptions & Streaming",
    "subscription": "Subscriptions & Streaming",
    "entertainment": "Entertainment",
    "movies": "Entertainment",
    "music": "Entertainment",
    "health": "Healthcare & Medical",
    "medical": "Healthcare & Medical",
    "pharmacy": "Healthcare & Medical",
    "doctor": "Healthcare & Medical",
    "dental": "Healthcare & Medical",
    "clothing": "Clothing & Fashion",
    "apparel": "Clothing & Fashion",
    "shopping": "Other Shopping",
    "general merchandise": "Other Shopping",
    "electronics": "Other Shopping",
    "books": "Other Shopping",
    "personal care": "Personal Care",
    "beauty": "Personal Care",
    "haircut": "Personal Care",
    "baby": "Kids & Baby",
    "kids": "Kids & Baby",
    "childcare": "Daycare",
    "daycare": "Daycare",
    "education": "Education",
    "tuition": "Education",
    "travel": "Travel",
    "hotel": "Travel",
    "airline": "Travel",
    "vacation": "Travel",
    "lodging": "Travel",
    "flights": "Travel",
    "charity": "Giving & Church",
    "donation": "Giving & Church",
    "giving": "Giving & Church",
    "gift": "Giving & Church",
    "gifts": "Giving & Church",
    "fees": "Fees & Interest",
    "interest": "Fees & Interest",
    "bank fee": "Fees & Interest",
    "late fee": "Fees & Interest",
    "transfer": "Transfers & Payments",
    "payment": "Transfers & Payments",
    "credit card payment": "Transfers & Payments",
    "income": "Income & Refunds",
    "paycheck": "Income & Refunds",
    "salary": "Income & Refunds",
    "refund": "Income & Refunds",
    "loan": "Debt Payments",
    "student loan": "Debt Payments",
    "home improvement": "Home Improvement",
    "hardware": "Home Improvement",
    "lawn": "Home Improvement",
}

_GET_CATEGORIES_QUERY = """
query GetTransactionCategories {
    categories {
        id
        name
    }
}
"""


def build_default_category_mapping(monarch_categories: list[str]) -> dict:
    """Map Monarch category names to Vaultwise categories by keyword matching."""
    mapping = {}
    for mcat in monarch_categories:
        lower = mcat.lower().strip()
        matched = None
        if lower in _CATEGORY_KEYWORDS:
            matched = _CATEGORY_KEYWORDS[lower]
        else:
            for keyword, vw_cat in _CATEGORY_KEYWORDS.items():
                if keyword in lower or lower in keyword:
                    matched = vw_cat
                    break
        mapping[mcat] = matched or "Other"
    return mapping


def fetch_categories(client: dict) -> list[str]:
    """Fetch category names from Monarch."""
    data = _gql(client, "GetTransactionCategories", _GET_CATEGORIES_QUERY)
    categories = []
    for cat in data.get("categories", []):
        name = cat.get("name", "")
        if name:
            categories.append(name)
    return sorted(set(categories))


def get_category_mapping(conn) -> dict:
    raw = database.get_setting(conn, "monarch_category_map", "{}")
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def set_category_mapping(conn, mapping: dict) -> None:
    database.set_setting(conn, "monarch_category_map", json.dumps(mapping))


# ---------------------------------------------------------------------------
# Transaction sync
# ---------------------------------------------------------------------------
_GET_TRANSACTIONS_QUERY = """
query GetTransactionsList($offset: Int, $limit: Int, $filters: TransactionFilterInput, $orderBy: TransactionOrdering) {
    allTransactions(filters: $filters) {
        totalCount
        results(offset: $offset, limit: $limit, orderBy: $orderBy) {
            id
            amount
            pending
            date
            plaidName
            notes
            isRecurring
            category { id name }
            merchant { name id }
            account { id displayName }
            tags { id name }
        }
    }
}
"""


def _transform_transaction(txn: dict, acct_mapping: dict, cat_mapping: dict) -> dict | None:
    """Transform a Monarch transaction into Vaultwise format. Returns None to skip."""
    if txn.get("pending", False):
        return None

    monarch_acct_id = str(txn.get("account", {}).get("id", ""))
    vw_account = acct_mapping.get(monarch_acct_id)
    if not vw_account:
        return None

    txn_date = txn.get("date", "")
    if not txn_date:
        return None

    amount = txn.get("amount", 0)
    if amount == 0:
        return None

    merchant_name = txn.get("merchant", {}).get("name", "") if txn.get("merchant") else ""
    plaid_name = txn.get("plaidName", "") or ""
    description = merchant_name or plaid_name or "Unknown"
    raw_description = plaid_name or merchant_name or "Unknown"

    monarch_cat = txn.get("category", {}).get("name", "Other") if txn.get("category") else "Other"
    vw_category = cat_mapping.get(monarch_cat, "Other")

    return {
        "date": txn_date,
        "description": description,
        "raw_description": raw_description,
        "amount": round(amount, 2),
        "category": vw_category,
        "account_id": vw_account,
        "statement_id": None,
        "confidence": 0.9,
        "notes": "monarch_sync",
    }


def _fetch_all_transactions(client: dict, account_ids: list[str], start_date: str | None) -> list[dict]:
    """Fetch all transactions with pagination."""
    all_txns = []
    offset = 0
    while True:
        variables = {
            "offset": offset,
            "limit": FETCH_LIMIT,
            "orderBy": "date",
            "filters": {
                "search": "",
                "accounts": account_ids,
            },
        }
        if start_date:
            variables["filters"]["startDate"] = start_date
            variables["filters"]["endDate"] = datetime.now().strftime("%Y-%m-%d")

        data = _gql(client, "GetTransactionsList", _GET_TRANSACTIONS_QUERY, variables)
        results = data.get("allTransactions", {}).get("results", [])
        total_count = data.get("allTransactions", {}).get("totalCount", 0)
        all_txns.extend(results)

        if len(all_txns) >= total_count or len(results) < FETCH_LIMIT:
            break
        offset += FETCH_LIMIT
    return all_txns


def sync_transactions(conn, force_full: bool = False) -> dict:
    """
    Fetch new transactions from Monarch and insert into the DB.
    Returns {"new": int, "skipped": int, "errors": list, "accounts_synced": list}.
    """
    result = {"new": 0, "skipped": 0, "errors": [], "accounts_synced": []}

    try:
        client = get_client(conn)
    except MonarchNotConfigured:
        result["errors"].append("Monarch not configured")
        return result
    except MonarchAuthFailed as e:
        result["errors"].append(str(e))
        return result
    except MonarchMFARequired as e:
        result["errors"].append(str(e))
        return result

    acct_mapping = get_account_mapping(conn)
    cat_mapping = get_category_mapping(conn)

    if not acct_mapping:
        result["errors"].append("No accounts mapped — configure in Settings")
        return result

    # Determine start date
    last_sync = database.get_setting(conn, "monarch_last_sync", "")
    if force_full or not last_sync:
        start_date = None
    else:
        try:
            sync_dt = datetime.fromisoformat(last_sync)
            start_date = (sync_dt - timedelta(days=3)).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            start_date = None

    monarch_account_ids = list(acct_mapping.keys())

    try:
        all_transactions = _fetch_all_transactions(client, monarch_account_ids, start_date)
    except Exception as e:
        result["errors"].append(f"API fetch error: {str(e)[:100]}")
        return result

    # Transform and deduplicate against existing DB transactions
    vw_transactions = []
    for txn in all_transactions:
        transformed = _transform_transaction(txn, acct_mapping, cat_mapping)
        if not transformed:
            result["skipped"] += 1
            continue

        # Smart dedup: skip if a transaction with same (date, amount, account_id)
        # already exists from any source (PDF/CSV or prior Monarch sync).
        # This prevents duplicates even when raw_description differs between sources.
        existing = conn.execute(
            "SELECT id FROM transactions WHERE date = ? AND ABS(amount - ?) < 0.01 AND account_id = ? LIMIT 1",
            (transformed["date"], transformed["amount"], transformed["account_id"]),
        ).fetchone()
        if existing:
            result["skipped"] += 1
            continue

        vw_transactions.append(transformed)

    if vw_transactions:
        inserted = database.bulk_insert_transactions(conn, vw_transactions)
        result["new"] = inserted
        result["skipped"] += len(vw_transactions) - inserted

    # Track synced accounts
    synced_ids = set()
    for txn in all_transactions:
        aid = str(txn.get("account", {}).get("id", ""))
        if aid in acct_mapping:
            synced_ids.add(acct_mapping[aid])
    result["accounts_synced"] = list(synced_ids)

    database.set_setting(conn, "monarch_last_sync", datetime.now().isoformat())
    return result


def get_sync_stats(conn) -> dict:
    """Return stats about Monarch-sourced data."""
    last_sync = database.get_setting(conn, "monarch_last_sync", "")
    try:
        count = conn.execute(
            "SELECT COUNT(*) as c FROM transactions WHERE notes = 'monarch_sync'"
        ).fetchone()["c"]
    except Exception:
        count = 0
    return {"last_sync": last_sync, "transaction_count": count}
