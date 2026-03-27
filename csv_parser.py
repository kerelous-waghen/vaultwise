"""
CSV parser for Chase bank statement exports.
Chase CSV format: Transaction Date, Post Date, Description, Category, Type, Amount, Memo
No Claude API needed for structured data — only for ambiguous categorization.
"""

import io
import re
from typing import Optional

import pandas as pd

import config


# ---------------------------------------------------------------------------
# Chase category → app category mapping
# ---------------------------------------------------------------------------
CHASE_CATEGORY_MAP = {
    "Food & Drink": {
        "default": "Dining Out",
        "keywords": {
            r"COSTCO": "Costco",
            r"SAFEWAY|HMART|FRED MEYER|QFC|TRADER JOE|GROCERY|WHOLE FOODS|KROGER|SPROUTS": "Groceries",
            r"NESPRESSO": "Groceries",
        },
    },
    "Groceries": {"default": "Groceries", "keywords": {r"COSTCO": "Costco"}},
    "Shopping": {
        "default": "Other Shopping",
        "keywords": {
            r"AMAZON|AMZN": "Amazon",
            r"NORDSTROM|GAP|ZARA|CARTER|VINEYARD|TUCKERNUCK|OLD NAVY": "Clothing & Fashion",
            r"TARGET": "Other Shopping",
            r"HOME DEPOT|LOWES|TERMINIX": "Home Improvement",
        },
    },
    "Merchandise": {
        "default": "Other Shopping",
        "keywords": {
            r"AMAZON|AMZN": "Amazon",
            r"NORDSTROM|GAP|ZARA|CARTER": "Clothing & Fashion",
        },
    },
    "Gas": {"default": "Gas", "keywords": {}},
    "Automotive": {"default": "Transportation", "keywords": {r"SHELL|76|CHEVRON|ARCO": "Gas"}},
    "Travel": {"default": "Travel", "keywords": {}},
    "Entertainment": {"default": "Entertainment", "keywords": {}},
    "Health & Wellness": {"default": "Healthcare & Medical", "keywords": {}},
    "Medical": {"default": "Healthcare & Medical", "keywords": {}},
    "Personal": {
        "default": "Personal Care",
        "keywords": {
            r"GREAT CLIPS|BROW|BEAUTY|SKINLUXE|SHARKEY": "Personal Care",
            r"GOLDFISH|SWIM|MUSEUM": "Kids & Baby",
        },
    },
    "Education": {"default": "Education", "keywords": {r"KIDDIE|KIRKLAND ACADEMY|MONTESSORI": "Daycare"}},
    "Bills & Utilities": {"default": "Housing & Utilities", "keywords": {r"T-MOBILE|TMOBILE": "Phone & Internet", r"COMCAST|XFINITY": "Phone & Internet"}},
    "Home": {"default": "Housing & Utilities", "keywords": {r"HOME DEPOT|LOWES": "Home Improvement"}},
    "Professional Services": {"default": "Other", "keywords": {}},
    "Gifts & Donations": {"default": "Giving & Church", "keywords": {}},
    "Fees & Adjustments": {"default": "Fees & Interest", "keywords": {}},
    "Payment": {"default": "Transfers & Payments", "keywords": {}},
}

# Known merchants for high-confidence mapping
MERCHANT_OVERRIDES = {
    r"KIDDIE ACADEMY|KIRKLAND ACADEMY MONTESSORI": "Daycare",
    r"COSTCO WHSE|COSTCO\.COM": "Costco",
    r"AMAZON\.COM|AMZN MKTP|AMAZON PRIME": "Amazon",
    r"SAFEWAY": "Groceries",
    r"HMART|H MART": "Groceries",
    r"FRED MEYER": "Groceries",
    r"TRADER JOE": "Groceries",
    r"ALLEGRO PEDIATRICS": "Healthcare & Medical",
    r"GOLDFISH SWIM": "Kids & Baby",
    r"APPLE\.COM/BILL": "Subscriptions & Streaming",
    r"GOOGLE \*": "Subscriptions & Streaming",
    r"NETFLIX|HULU|DISNEY|SPOTIFY|YOUTUBE": "Subscriptions & Streaming",
    r"DOORDASH|UBER EATS|GRUBHUB": "Dining Out",
    r"STARBUCKS|DUTCH BROS|PEET": "Dining Out",
    r"SHELL|CHEVRON|76|ARCO": "Gas",
    r"TERMINIX": "Home Improvement",
    r"MR COOPER": "Housing & Utilities",
    r"PUGET SOUND ENERGY|PSE": "Housing & Utilities",
    r"T-MOBILE": "Phone & Internet",
    r"AFFIRM": "Debt Payments",
    r"GREAT CLIPS|SHARKEY": "Personal Care",
    r"NORDSTROM|ZARA|GAP|CARTER": "Clothing & Fashion",
}


def categorize_transaction(description: str, chase_category: str = "") -> tuple[str, float]:
    """Map a transaction to an app category.
    Returns (category, confidence) where confidence is 0.0-1.0.
    """
    desc_upper = description.upper()

    # First: check merchant overrides (highest confidence)
    for pattern, category in MERCHANT_OVERRIDES.items():
        if re.search(pattern, desc_upper):
            return category, 0.95

    # Second: use Chase category + keyword refinement
    chase_cat = chase_category.strip()
    if chase_cat in CHASE_CATEGORY_MAP:
        mapping = CHASE_CATEGORY_MAP[chase_cat]
        for pattern, category in mapping.get("keywords", {}).items():
            if re.search(pattern, desc_upper):
                return category, 0.85
        return mapping["default"], 0.70

    # Fallback
    return "Other", 0.30


def parse_chase_csv(file_bytes: bytes, account_hint: Optional[str] = None) -> dict:
    """Parse a Chase CSV export into the standard transaction format.

    Returns the same structure as claude_advisor.extract_transactions() for consistency.
    """
    text = file_bytes.decode("utf-8-sig")  # Chase CSVs may have BOM
    df = pd.read_csv(io.StringIO(text))

    # Normalize column names
    df.columns = [c.strip() for c in df.columns]

    # Detect format
    if "Transaction Date" not in df.columns:
        raise ValueError(f"Not a Chase CSV format. Found columns: {list(df.columns)}")

    # Parse dates
    df["Transaction Date"] = pd.to_datetime(df["Transaction Date"], format="mixed")

    # Determine account from content
    account_id = account_hint or "unknown"

    # Extract period
    period_start = df["Transaction Date"].min().strftime("%Y-%m-%d")
    period_end = df["Transaction Date"].max().strftime("%Y-%m-%d")

    # Categorize each transaction
    transactions = []
    ambiguous = []

    for _, row in df.iterrows():
        desc = str(row.get("Description", "")).strip()
        chase_cat = str(row.get("Category", "")).strip()
        amount = float(row.get("Amount", 0))
        txn_date = row["Transaction Date"].strftime("%Y-%m-%d")

        category, confidence = categorize_transaction(desc, chase_cat)

        txn = {
            "date": txn_date,
            "description": clean_description(desc),
            "raw_description": desc,
            "amount": amount,
            "category": category,
            "confidence": confidence,
            "notes": f"Chase category: {chase_cat}" if chase_cat else "",
        }

        transactions.append(txn)

        if confidence < 0.50:
            ambiguous.append(txn)

    return {
        "account_id": account_id,
        "period_start": period_start,
        "period_end": period_end,
        "status": "new",
        "transactions": transactions,
        "ambiguous_count": len(ambiguous),
        "ambiguous_transactions": ambiguous,
        "statement_summary": {
            "total_charges": sum(t["amount"] for t in transactions if t["amount"] < 0),
            "total_credits": sum(t["amount"] for t in transactions if t["amount"] > 0),
            "transaction_count": len(transactions),
        },
        "source": "csv",
    }


def clean_description(desc: str) -> str:
    """Clean up a Chase transaction description into a readable merchant name."""
    # Remove common suffixes
    desc = re.sub(r"\s+(WA|CA|NY|TX|FL|OR)\s*\d*$", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\s+\d{5,}$", "", desc)  # trailing zip/reference codes
    desc = re.sub(r"\s+#\d+", "", desc)
    desc = re.sub(r"\s{2,}", " ", desc).strip()
    # Title case for readability
    if desc.isupper() and len(desc) > 3:
        desc = desc.title()
    return desc


def detect_csv_format(file_bytes: bytes) -> str:
    """Detect which bank's CSV format this is."""
    text = file_bytes.decode("utf-8-sig")
    first_line = text.split("\n")[0].lower()

    if "transaction date" in first_line and "post date" in first_line:
        return "chase"
    if "transaction date" in first_line and "card no" in first_line:
        return "capital_one"
    if "daily cash" in first_line:
        return "apple_card"
    return "unknown"


def identify_account_from_csv(file_bytes: bytes, filename: str = "") -> Optional[str]:
    """Smart account detection from CSV content + filename.
    Chase CSVs don't include card numbers, so we use transaction patterns.
    """
    text = file_bytes.decode("utf-8-sig")
    text_upper = text.upper()
    header = text_upper[:500]

    # 1. Check if card number appears anywhere (some exports include it)
    if "4730" in header:
        return "chase_4730"
    if "3072" in header:
        return "chase_3072"

    # 2. Check filename for hints
    fname = filename.upper()
    if "4730" in fname:
        return "chase_4730"
    if "3072" in fname:
        return "chase_3072"
    if "CHECKING" in fname:
        return "joint_checking"
    if re.search(r"\bKERO\b", fname):
        return "chase_4730"
    if re.search(r"\bMAGGIE\b|\bMARGARET\b", fname):
        return "chase_3072"

    # 3. Non-Chase banks
    if "CAPITAL ONE" in header or "CAPITAL ONE" in fname:
        return "capital_one"
    if "APPLE" in fname or "DAILY CASH" in header:
        return "apple_card"

    # 4. Transaction pattern analysis — which card is this likely?
    # Parse transactions and look for known merchant patterns
    try:
        result = parse_chase_csv(file_bytes, account_hint="unknown")
        txns = result.get("transactions", [])
    except Exception:
        return None

    kero_signals = 0  # chase_4730
    maggie_signals = 0  # chase_3072
    checking_signals = 0

    for txn in txns:
        desc = txn.get("raw_description", "").upper()
        cat = txn.get("category", "")

        # Kero's card markers: Costco, daycare, gas, Amazon
        if re.search(r"KIDDIE\s*ACADEMY|KIRKLAND\s*ACADEMY", desc):
            kero_signals += 5  # Daycare is very strong signal
        if re.search(r"COSTCO", desc):
            kero_signals += 2
        if cat == "Gas":
            kero_signals += 1
        if re.search(r"AMAZON|AMZN", desc):
            kero_signals += 1

        # Maggie's card markers: Nordstrom, fashion, Tuckernuck
        if re.search(r"NORDSTROM|TUCKERNUCK|VINEYARD|ZARA|GAP\b", desc):
            maggie_signals += 3
        if cat == "Clothing & Fashion":
            maggie_signals += 2

        # Checking markers: payroll, mortgage, Zelle, loan payments
        if re.search(r"PREMERA|BOEING|PAYROLL|PPD", desc):
            checking_signals += 5
        if re.search(r"MR\.?\s*COOPER|MORTGAGE", desc):
            checking_signals += 5
        if re.search(r"ZELLE", desc):
            checking_signals += 3

    scores = {
        "chase_4730": kero_signals,
        "chase_3072": maggie_signals,
        "joint_checking": checking_signals,
    }

    best = max(scores, key=scores.get)
    if scores[best] >= 3:
        return best

    return None
