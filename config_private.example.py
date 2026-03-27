"""
Template for config_private.py — copy this file and fill in your real values.

    cp config_private.example.py config_private.py

This file is committed to git as a reference. config_private.py is NOT.
"""

from datetime import date

FAMILY = {
    "adults": [
        {"name": "Person1", "salary": 100_000, "employer": "Company A", "role": "primary"},
        {"name": "Person2", "salary": 80_000, "employer": "Company B", "role": "secondary"},
    ],
    "children": [
        {"name": "Child1", "dob": "2023-01-01", "school_district": "District"},
    ],
    "address": "123 Main St, City ST 00000",
}

ACCOUNTS = {
    "bank_1234": {"type": "credit", "label": "Card ...1234", "owner": "Person1", "last4": "1234"},
    "joint_checking": {"type": "checking", "label": "Joint Checking", "owner": "joint", "last4": "5678"},
}

INCOME = {
    "person1": {
        "base_salary": 100_000,
        "biweekly_net": 3_000,
        "monthly_net": 6_500,
        "annual_raise": 3_000,
        "raise_month": 3,
        "bonus_annual_after_tax": 10_000,
        "bonus_month": 3,
        "bonus_spread_monthly": 833,
    },
    "person2": {
        "base_salary": 80_000,
        "biweekly_net": 2_500,
        "monthly_net": 5_417,
        "annual_raise": 2_000,
        "raise_month": 1,
        "bonus_annual_after_tax": 5_000,
        "bonus_month": 1,
        "bonus_spread_monthly": 417,
    },
    "combined_monthly_take_home": 13_167,
}

DAYCARE_PROVIDER = "Daycare Name"
DAYCARE_ADDRESS = "456 School Rd, City ST 00000"
DAYCARE_PHONE = "555-555-5555"

GEO_DAYCARE = [
    {"period": ("2026-01-01", "2026-12-31"), "program": "Preschool", "monthly": 2_500},
]
GEO_KINDERGARTEN = date(2028, 9, 1)

PERLA_DAYCARE = [
    {"period": ("2027-01-01", "2027-12-31"), "program": "Toddler", "monthly": 3_000},
]
PERLA_KINDERGARTEN = date(2031, 9, 1)

DAYCARE_OVERLAP_START = date(2027, 8, 1)
DAYCARE_OVERLAP_END = date(2028, 8, 31)
PEAK_DAYCARE_MONTHLY = 5_500

FIXED_MONTHLY_EXPENSES = {
    "Mortgage": 2_000,
    "Utilities": 200,
    "Car Payment": 400,
    "Insurance": 200,
}
NON_DAYCARE_MONTHLY = 10_000
CC_MONTHLY_AVERAGE_EXCL_DAYCARE = 3_000

OBJECTIVES = [
    {
        "id": "example_goal",
        "label": "Example Savings Goal",
        "description": "Save $10,000 by end of year.",
        "target": 10_000,
        "deadline": "2027-12-31",
        "priority": 1,
    },
]

SAVINGS_LEVERS = [
    {"lever": "Reduce dining out", "current": 500, "target": 300, "monthly_savings": 200, "difficulty": "MEDIUM"},
]
TOTAL_POTENTIAL_MONTHLY_SAVINGS = sum(l["monthly_savings"] for l in SAVINGS_LEVERS)

TELEGRAM_USERS = {
    "person1": {
        "setting_key": "telegram_chat_id",
        "accounts": ["bank_1234", "joint_checking"],
    },
}
