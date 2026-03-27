"""
Family financial constants — single source of truth for the entire application.
Covers: family members, accounts, income model, daycare schedule, expense categories,
objectives, and Claude API settings.
"""

from datetime import date

# ---------------------------------------------------------------------------
# Family members
# ---------------------------------------------------------------------------
FAMILY = {
    "adults": [
        {"name": "Kero", "salary": 190_000, "employer": "Premera Blue Cross", "role": "primary"},
        {"name": "Maggie", "salary": 130_000, "employer": "Boeing", "role": "secondary"},
    ],
    "children": [
        {"name": "Geo", "dob": "2023-06-16", "school_district": "LWSD"},
        {"name": "Perla", "dob": "2026-01-30", "school_district": "LWSD"},
    ],
    "address": "13842 92nd Pl NE, Kirkland WA 98034",
}

# ---------------------------------------------------------------------------
# Bank / credit-card accounts  (last-4 used by Claude to match statement headers)
# ---------------------------------------------------------------------------
ACCOUNTS = {
    "chase_4730": {"type": "credit", "label": "Chase Freedom/Sapphire ...4730", "owner": "Kero", "last4": "4730"},
    "chase_3072": {"type": "credit", "label": "Chase ...3072", "owner": "Maggie", "last4": "3072"},
    "capital_one": {"type": "credit", "label": "Capital One", "owner": "shared", "last4": None},
    "apple_card": {"type": "credit", "label": "Apple Card", "owner": "Kero", "last4": None},
    "joint_checking": {"type": "checking", "label": "Chase Joint Checking", "owner": "joint", "last4": "3829"},
}

# ---------------------------------------------------------------------------
# Income model
# ---------------------------------------------------------------------------
INCOME = {
    "kero": {
        "base_salary": 190_000,
        "biweekly_net": 4_900,
        "monthly_net": 10_617,          # $4,900 × 26/12
        "annual_raise": 5_000,          # added in March each year
        "raise_month": 3,               # March
        "bonus_annual_after_tax": 18_000,
        "bonus_month": 3,
        "bonus_spread_monthly": 1_500,  # $18K / 12
    },
    "maggie": {
        "base_salary": 130_000,
        "biweekly_net": 3_575,
        "monthly_net": 7_746,           # $3,575 × 26/12 (verified Jul-Aug 2025)
        "annual_raise": 4_000,          # added in January each year
        "raise_month": 1,               # January
        "bonus_annual_after_tax": 5_000,
        "bonus_month": 1,
        "bonus_spread_monthly": 417,    # $5K / 12
    },
    "combined_monthly_take_home": 20_280,  # $10,617+$1,500+$7,746+$417
}

# ---------------------------------------------------------------------------
# Daycare schedule  (Kiddie Academy of Kirkland)
# ---------------------------------------------------------------------------
DAYCARE_PROVIDER = "Kiddie Academy of Kirkland"
DAYCARE_ADDRESS = "12620 NE 85th St, Kirkland WA 98033"
DAYCARE_PHONE = "425-242-0075"
ANNUAL_RATE_INCREASE = 0.04  # 4 %

# Geo timeline (4% annual rate increase each January)
GEO_DAYCARE = [
    {"period": ("2026-04-01", "2026-05-31"), "program": "Early Preschool", "monthly": 3_120},
    {"period": ("2026-06-01", "2026-12-31"), "program": "Preschool",       "monthly": 2_496},
    {"period": ("2027-01-01", "2027-05-31"), "program": "Preschool",       "monthly": 2_596},  # 4% bump Jan 2027
    {"period": ("2027-06-01", "2027-12-31"), "program": "Pre-K",           "monthly": 2_380},
    {"period": ("2028-01-01", "2028-08-31"), "program": "Pre-K",           "monthly": 2_475},  # 4% bump Jan 2028
]
GEO_KINDERGARTEN = date(2028, 9, 1)

# Perla timeline
PERLA_DAYCARE = [
    {"period": ("2027-08-01", "2027-12-31"), "program": "Toddler",          "monthly": 3_677},
    {"period": ("2028-01-01", "2028-12-31"), "program": "Early Preschool",  "monthly": 3_375},
    {"period": ("2029-01-01", "2029-12-31"), "program": "Preschool",        "monthly": 2_808},
    {"period": ("2030-01-01", "2030-12-31"), "program": "Pre-K",            "monthly": 2_677},
    {"period": ("2031-01-01", "2031-08-31"), "program": "Pre-K",            "monthly": 2_784},  # 4% bump Jan 2031
]
PERLA_KINDERGARTEN = date(2031, 9, 1)

DAYCARE_OVERLAP_START = date(2027, 8, 1)
DAYCARE_OVERLAP_END = date(2028, 8, 31)
PEAK_DAYCARE_MONTHLY = 6_057

# ---------------------------------------------------------------------------
# Verified monthly expenses paid from checking (NOT credit cards)
# ---------------------------------------------------------------------------
FIXED_MONTHLY_EXPENSES = {
    "Mortgage (Mr. Cooper 6.49%)":      7_104,
    "PSE Electric & Gas":                 219,
    "Water/Sewer (NUD)":                  138,
    "Internet (Comcast/Xfinity)":          65,
    "Garbage & Recycling":                 84,
    "Home Improvement (normalized)":      285,
    "Renters Insurance (AGI)":             11,
    "Auto Loan (Chase #2102)":            660,
    "Car Insurance (CCS Country)":        373,
    "Gas (fuel)":                         113,
    "Auto Maintenance (normalized)":       42,
    "T-Mobile":                           140,
    "Mint Mobile (normalized)":            30,
    "Digital Subscriptions":               55,
    "Student Loan 1":                     250,
    "Student Loan 2":                     268,
    "Affirm":                              83,
    "CC Interest (card 3072)":             63,
    "Church (Zelle)":                   1_500,
    "Church (CC small donations)":         63,
    "Family Support (Nermeen)":           150,
    "Travel (normalized)":                 67,
}
# The PDF specifies $16,319/mo total non-daycare expenses (checking + credit card combined).
# FIXED_MONTHLY_EXPENSES above covers checking-account debits only.
# The remainder is discretionary credit-card spend (groceries, dining, shopping, etc.)
_CHECKING_SUBTOTAL = sum(FIXED_MONTHLY_EXPENSES.values())
NON_DAYCARE_MONTHLY = 16_319  # Verified from 12 months of Chase statements (Jan-Dec 2025)

# Credit-card spend verified total (excl. daycare)
CC_MONTHLY_AVERAGE_EXCL_DAYCARE = 5_894

# ---------------------------------------------------------------------------
# Expense categories for Claude to use
# ---------------------------------------------------------------------------
CATEGORIES = [
    "Housing & Utilities",
    "Daycare",
    "Groceries",
    "Costco",
    "Dining Out",
    "Transportation",
    "Gas",
    "Car Insurance",
    "Healthcare & Medical",
    "Kids & Baby",
    "Personal Care",
    "Clothing & Fashion",
    "Amazon",
    "Other Shopping",
    "Subscriptions & Streaming",
    "Phone & Internet",
    "Debt Payments",
    "Giving & Church",
    "Family Support",
    "Travel",
    "Education",
    "Entertainment",
    "Home Improvement",
    "Fees & Interest",
    "Transfers & Payments",
    "Income & Refunds",
    "Other",
]

# Categories to exclude from all analysis, charts, and cards
# These are internal movements, not actual spending
EXCLUDED_CATEGORIES = {
    "Transfers & Payments",
    "Transfers & Savings",
    "Credit Card Payments",
    "Income & Refunds",
    "Debt & Loan Payments",
    "Debt Payments",
}

# ---------------------------------------------------------------------------
# Financial objectives
# ---------------------------------------------------------------------------
OBJECTIVES = [
    {
        "id": "daycare_overlap",
        "label": "Survive Daycare Overlap (Aug 2027 – Aug 2028)",
        "description": "Build $20,536 in savings before Aug 2027 to cover 13 months of double daycare deficits.",
        "target": 20_536,
        "deadline": "2027-08-01",
        "priority": 1,
    },
    {
        "id": "break_even_buffer",
        "label": "Build $3K Safety Buffer",
        "description": "Cut $300/mo ($111/mo minimum) to create a $3K buffer through the overlap.",
        "target": 3_000,
        "deadline": "2027-08-01",
        "priority": 2,
    },
    {
        "id": "general_savings",
        "label": "General Monthly Savings",
        "description": "Maintain a positive monthly net after all expenses and daycare.",
        "target_rate_monthly": 1_000,
        "deadline": None,
        "priority": 3,
    },
    {
        "id": "emergency_fund",
        "label": "Emergency Fund (6 months expenses)",
        "description": "Build an emergency fund covering 6 months of total expenses (~$100K).",
        "target": 100_000,
        "deadline": None,
        "priority": 4,
    },
    {
        "id": "post_daycare_freedom",
        "label": "Post-Daycare Wealth Building (Sep 2031+)",
        "description": "After all daycare ends, projected cumulative surplus reaches $90,391 by Aug 2031.",
        "target": 90_391,
        "deadline": "2031-08-31",
        "priority": 5,
    },
]

# ---------------------------------------------------------------------------
# Savings levers identified from 2025 spending analysis
# ---------------------------------------------------------------------------
SAVINGS_LEVERS = [
    {"lever": "Costco spending audit",          "current": 1100, "target": 900,  "monthly_savings": 200, "difficulty": "HIGH"},
    {"lever": "Dining out reduction",           "current": 642,  "target": 550,  "monthly_savings": 92,  "difficulty": "MEDIUM"},
    {"lever": "Pay off card 3072",              "current": 63,   "target": 0,    "monthly_savings": 63,  "difficulty": "EASY"},
    {"lever": "Amazon review",                  "current": 890,  "target": 830,  "monthly_savings": 60,  "difficulty": "MEDIUM"},
    {"lever": "Clothing pause during overlap",  "current": 467,  "target": 300,  "monthly_savings": 167, "difficulty": "MEDIUM"},
    {"lever": "Home improvement pause",         "current": 285,  "target": 150,  "monthly_savings": 135, "difficulty": "EASY"},
    {"lever": "Streaming audit",                "current": 55,   "target": 40,   "monthly_savings": 15,  "difficulty": "EASY"},
]
TOTAL_POTENTIAL_MONTHLY_SAVINGS = sum(l["monthly_savings"] for l in SAVINGS_LEVERS)  # $732

# ---------------------------------------------------------------------------
# Telegram users — maps people to their chat-ID setting key and accounts
# ---------------------------------------------------------------------------
TELEGRAM_USERS = {
    "kero": {
        "setting_key": "telegram_chat_id",
        "accounts": ["chase_4730", "joint_checking"],
    },
    "maggie": {
        "setting_key": "telegram_chat_id_maggie",
        "accounts": ["chase_3072"],
    },
}

# ---------------------------------------------------------------------------
# Claude API settings
# ---------------------------------------------------------------------------
ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS_EXTRACTION = 8192
MAX_TOKENS_ADVISOR = 4096
MAX_TOKENS_FORECAST = 4096
MAX_TOKENS_REPORT = 4096

# ---------------------------------------------------------------------------
# App settings
# ---------------------------------------------------------------------------
APP_TITLE = "Family Budget Tracker"
DB_FILENAME = "expenses.db"
UPLOAD_DIR = "data/uploads"
