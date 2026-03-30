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
FAMILY_DISPLAY_NAME = "Your Family"

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

FIXED_MONTHLY_EXPENSES = {
    "Mortgage": 2_000,
    "Utilities": 200,
    "Car Payment": 400,
    "Insurance": 200,
}
MONTHLY_EXPENSES = 10_000
CC_MONTHLY_AVERAGE = 3_000

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

# Maps Monarch category names to fixed bill labels (excluded from spending cards)
MONARCH_FIXED_MAP = {}

# Categories hidden from spending breakdown (not real spending)
MUTED_CATEGORIES = []

# Display labels for income sources (keeps names out of views/)
INCOME_LABELS = {}

# Groups for the fixed bills table in the breakdown expander
FIXED_BILL_GROUPS = {}

# Auto-recategorize interval (days, 0=disabled)
AUTO_RECATEGORIZE_DAYS = 0

# Names that appear in Zelle transfers to identify family payments (for statement parsing)
FAMILY_ZELLE_NAMES = ["PERSON_A", "PERSON_B"]

# Family member names for regex matching in statement parsers
FAMILY_MEMBER_NAMES = ["Person1", "Person2"]

# Family context injected into Claude extraction prompts (for categorization accuracy)
EXTRACTION_CONTEXT = """
- Person1 (Company A) and Person2 (Company B)
- Children: Child1, Child2
- Address: 123 Main St, City ST 00000
- Daycare: Example Daycare
- Church: Example Church (Zelle $X/mo)
- Family support: Zelle to Person_A ~$X/mo
- Primary shopping area: Local Area
"""

# Context for savings lever advice (merchant-specific tips)
SAVINGS_LEVER_CONTEXT = ""

# Annual expense inflation rate (3% default)
EXPENSE_GROWTH_RATE = 0.03
