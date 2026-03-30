"""
PDF text extraction, account identification, and statement period detection.
Extracts raw text faithfully — Claude does the intelligent transaction parsing.
This module handles the "what file is this?" question before Claude ever sees it.
"""

import hashlib
import io
import re
from datetime import datetime
from typing import Optional

import pdfplumber

import config


# ── Hashing ───────────────────────────────────────────────────────────────

def compute_file_hash(file_path: str) -> str:
    """SHA-256 hash of raw file bytes for deduplication."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


def compute_bytes_hash(file_bytes: bytes) -> str:
    """SHA-256 hash from in-memory bytes."""
    return hashlib.sha256(file_bytes).hexdigest()


# ── Text & table extraction ───────────────────────────────────────────────

def extract_text_from_pdf(file_path: str) -> str:
    pages = []
    with pdfplumber.open(file_path) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            pages.append(f"--- PAGE {i} ---\n{text}")
    return "\n\n".join(pages)


def extract_text_from_bytes(file_bytes: bytes) -> str:
    pages = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            pages.append(f"--- PAGE {i} ---\n{text}")
    return "\n\n".join(pages)


def extract_tables_from_pdf(file_path: str) -> list:
    all_tables = []
    with pdfplumber.open(file_path) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            tables = page.extract_tables() or []
            for table in tables:
                all_tables.append({"page": i, "data": table})
    return all_tables


def extract_tables_from_bytes(file_bytes: bytes) -> list:
    all_tables = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            tables = page.extract_tables() or []
            for table in tables:
                all_tables.append({"page": i, "data": table})
    return all_tables


def get_page_count(file_bytes: bytes) -> int:
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        return len(pdf.pages)


# ── Smart account identification ──────────────────────────────────────────

def identify_account_from_text(text: str) -> Optional[str]:
    """Multi-signal account detection. Uses card numbers, cardholder names,
    statement type markers, known merchants, and payment amounts to determine
    which account a statement belongs to.

    Returns: account_id string or None if uncertain.
    """
    text_upper = text.upper()
    text_lower = text.lower()
    # We'll scan just the first ~3000 chars (header area) for account markers,
    # and the full text for transaction-pattern signals.
    header = text_upper[:3000]

    signals = {}  # account_id -> confidence score

    # ── Signal 1: Last-4 card digits (strongest for Chase) ────────────────
    # Chase CC statements: "Account number ending in: 4730" or "Spending Report 4730"
    # BUT in checking statements, "4730" appears in "Payment To Chase Card Ending IN 4730"
    # — that means THIS account PAYS the 4730 card, not that this IS the 4730 card.
    is_checking_doc = bool(re.search(r"CHECKING\s*(SUMMARY|ACCOUNT|STATEMENT)", header))

    if re.search(r"(?:SPENDING\s*REPORT|ACCOUNT\s*(?:NUMBER|ENDING))\s*\S{0,5}\s*4730", header):
        signals["chase_4730"] = signals.get("chase_4730", 0) + 50
    elif not is_checking_doc and re.search(r"4730", header):
        signals["chase_4730"] = signals.get("chase_4730", 0) + 30

    if re.search(r"(?:SPENDING\s*REPORT|ACCOUNT\s*(?:NUMBER|ENDING))\s*\S{0,5}\s*3072", header):
        signals["chase_3072"] = signals.get("chase_3072", 0) + 50
    elif not is_checking_doc and re.search(r"3072", header):
        signals["chase_3072"] = signals.get("chase_3072", 0) + 30

    # Check for joint checking account number (3829)
    if re.search(r"3829", header) and is_checking_doc:
        signals["joint_checking"] = signals.get("joint_checking", 0) + 50

    # ── Signal 2: Cardholder / account holder names ───────────────────────
    # Chase CC statements say "KERELOUSWAGHEN" or "MARGARET" or "MAGGIE"
    # Checking statements say both names together
    has_kero = bool(re.search(r"KERELOUS|KERO(?:LOUS)?|WAGHEN,?\s*K", header))
    has_maggie = bool(re.search(r"MAGGIE|MARGARET|MAGI\s*M|WAGHEN,?\s*M|ELIAS", header))

    if has_kero and not has_maggie:
        # Primary cardholder only → likely primary credit card
        signals["chase_4730"] = signals.get("chase_4730", 0) + 20
    elif has_maggie and not has_kero:
        # Secondary cardholder only → likely secondary credit card
        signals["chase_3072"] = signals.get("chase_3072", 0) + 20
    elif has_kero and has_maggie:
        # Both names → joint checking
        signals["joint_checking"] = signals.get("joint_checking", 0) + 25

    # ── Signal 3: Statement type markers ──────────────────────────────────
    # Chase checking says "CHECKING SUMMARY" or "CHECKING ACCOUNT"
    if re.search(r"CHECKING\s*(SUMMARY|ACCOUNT|STATEMENT)", header):
        signals["joint_checking"] = signals.get("joint_checking", 0) + 40

    # Chase credit cards say "CREDIT CARD STATEMENT" or "ACCOUNT SUMMARY"
    if re.search(r"CREDIT\s*CARD\s*STATEMENT", header):
        # It's a Chase CC, but which one? Boost whichever has more signals
        signals["chase_4730"] = signals.get("chase_4730", 0) + 5
        signals["chase_3072"] = signals.get("chase_3072", 0) + 5

    # "FREEDOM" or "SAPPHIRE" → primary card (Freedom/Sapphire are Chase product names)
    if re.search(r"FREEDOM|SAPPHIRE", header):
        signals["chase_4730"] = signals.get("chase_4730", 0) + 25

    # Capital One markers
    if re.search(r"CAPITAL\s*ONE", header):
        signals["capital_one"] = signals.get("capital_one", 0) + 50

    # Apple Card markers
    if re.search(r"APPLE\s*CARD|APPLE\s*CASH|GOLDMAN\s*SACHS", header):
        signals["apple_card"] = signals.get("apple_card", 0) + 50

    # ── Signal 4: Transaction pattern signals (scan full text) ────────────
    # Checking accounts have paychecks (PREMERA, BOEING, PPD) and Zelle
    if re.search(r"PREMERA|BOEING|PPD\s*\d+|PAYROLL", text_upper):
        signals["joint_checking"] = signals.get("joint_checking", 0) + 20

    # Zelle transfers to family members → checking
    _family_names = "|".join(re.escape(n) for n in config.FAMILY_ZELLE_NAMES) if config.FAMILY_ZELLE_NAMES else "NOMATCH"
    if re.search(rf"ZELLE.*(?:{_family_names})|ZELLE.*1[,.]?500", text_upper):
        signals["joint_checking"] = signals.get("joint_checking", 0) + 15

    # MR COOPER mortgage → checking
    if re.search(r"MR\.?\s*COOPER|MORTGAGE", text_upper):
        signals["joint_checking"] = signals.get("joint_checking", 0) + 15

    # Chase auto loan from checking
    if re.search(r"CHASE\s*AUTO|AUTO\s*LOAN|ACH.*2102", text_upper):
        signals["joint_checking"] = signals.get("joint_checking", 0) + 10

    # ── Signal 5: Known merchants that appear on specific cards ───────────
    # Secondary card tends to have: Nordstrom, Tuckernuck, fashion
    if re.search(r"NORDSTROM|TUCKERNUCK|VINEYARD\s*VINES", text_upper):
        signals["chase_3072"] = signals.get("chase_3072", 0) + 8

    # Primary card tends to have: Costco, Amazon, gas stations, daycare
    if re.search(r"KIDDIE\s*ACADEMY|KIRKLAND\s*ACADEMY\s*MONTES", text_upper):
        signals["chase_4730"] = signals.get("chase_4730", 0) + 10

    # ── Signal 6: Payment amount ranges (checking CC payments) ────────────
    # In checking statements, credit card payments appear as debits:
    # 4730 payments are typically $4,000-$7,000, 3072 is $1,000-$4,000
    cc_payment_matches = re.findall(
        r"(?:CHASE\s*CARD|CREDIT\s*CARD|CARD\s*ENDING)\s*(?:IN\s*)?(\d{4})\b",
        text_upper,
    )
    for last4 in cc_payment_matches:
        if last4 == "4730":
            signals["joint_checking"] = signals.get("joint_checking", 0) + 10
        elif last4 == "3072":
            signals["joint_checking"] = signals.get("joint_checking", 0) + 10

    # ── Signal 7: Filename hints (if embedded in PDF metadata) ────────────
    # Sometimes Chase PDFs have "eStatement" + account type in metadata
    if re.search(r"JPMORGAN\s*CHASE", header):
        # It's definitely Chase, boost any Chase account slightly
        for acct in ["chase_4730", "chase_3072", "joint_checking"]:
            signals[acct] = signals.get(acct, 0) + 3

    # ── Pick the winner ───────────────────────────────────────────────────
    if not signals:
        return None

    best_account = max(signals, key=signals.get)
    best_score = signals[best_account]

    # Need at least some confidence
    if best_score < 10:
        return None

    return best_account


def identify_account_from_filename(filename: str) -> Optional[str]:
    """Try to detect account from the filename alone.
    Users often name files like 'Chase4730_Jan2025.pdf' or 'Maggie_CC_statement.pdf'.
    """
    name = filename.upper()

    if "4730" in name:
        return "chase_4730"
    if "3072" in name:
        return "chase_3072"
    if "CHECKING" in name:
        return "joint_checking"
    if "CAPITAL" in name:
        return "capital_one"
    if "APPLE" in name:
        return "apple_card"

    # Name-based hints (allow underscores/hyphens as word boundaries)
    if re.search(r"KERO", name):
        return "chase_4730"
    if re.search(r"MAGGIE|MARGARET", name):
        return "chase_3072"

    return None


def get_detection_confidence(text: str) -> dict:
    """Return confidence scores for ALL accounts — useful for UI display
    when the user needs to confirm which account.

    Returns: dict like {"chase_4730": 75, "chase_3072": 10, "joint_checking": 5}
    """
    text_upper = text.upper()
    header = text_upper[:3000]
    scores = {}

    # Run the same signal logic as identify_account_from_text but collect all scores
    is_checking_doc = bool(re.search(r"CHECKING\s*(SUMMARY|ACCOUNT|STATEMENT)", header))

    # Last-4 (only count if this doc IS that card, not if it references it in payments)
    if re.search(r"(?:SPENDING\s*REPORT|ACCOUNT\s*(?:NUMBER|ENDING))\s*\S{0,5}\s*4730", header):
        scores["chase_4730"] = scores.get("chase_4730", 0) + 50
    elif not is_checking_doc and "4730" in header:
        scores["chase_4730"] = scores.get("chase_4730", 0) + 30

    if re.search(r"(?:SPENDING\s*REPORT|ACCOUNT\s*(?:NUMBER|ENDING))\s*\S{0,5}\s*3072", header):
        scores["chase_3072"] = scores.get("chase_3072", 0) + 50
    elif not is_checking_doc and "3072" in header:
        scores["chase_3072"] = scores.get("chase_3072", 0) + 30

    # Names
    has_kero = bool(re.search(r"KERO|WAGHEN,?\s*K", header))
    has_maggie = bool(re.search(r"MAGGIE|MARGARET|WAGHEN,?\s*M", header))
    if has_kero and not has_maggie:
        scores["chase_4730"] = scores.get("chase_4730", 0) + 20
    elif has_maggie and not has_kero:
        scores["chase_3072"] = scores.get("chase_3072", 0) + 20
    elif has_kero and has_maggie:
        scores["joint_checking"] = scores.get("joint_checking", 0) + 25

    # Statement type
    if re.search(r"CHECKING\s*(SUMMARY|ACCOUNT|STATEMENT)", header):
        scores["joint_checking"] = scores.get("joint_checking", 0) + 40
    if re.search(r"FREEDOM|SAPPHIRE", header):
        scores["chase_4730"] = scores.get("chase_4730", 0) + 25
    if re.search(r"CAPITAL\s*ONE", header):
        scores["capital_one"] = scores.get("capital_one", 0) + 50
    if re.search(r"APPLE\s*CARD|GOLDMAN\s*SACHS", header):
        scores["apple_card"] = scores.get("apple_card", 0) + 50

    # Transaction patterns (full text)
    if re.search(r"PREMERA|BOEING|PPD\s*\d+|PAYROLL", text_upper):
        scores["joint_checking"] = scores.get("joint_checking", 0) + 20
    if re.search(r"MR\.?\s*COOPER|MORTGAGE", text_upper):
        scores["joint_checking"] = scores.get("joint_checking", 0) + 15

    return scores


# ── Statement period extraction ───────────────────────────────────────────

def extract_statement_period(text: str) -> Optional[tuple[str, str]]:
    """Extract statement period as (start_date, end_date) in YYYY-MM-DD format.
    Handles multiple common formats from Chase, Capital One, Apple Card.
    """
    text_block = text[:8000]  # Expanded range — checking PDFs have long boilerplate

    # Pattern 0: "November 29, 2025 through December 24, 2025" (Chase checking)
    # Note: pdfplumber often joins "2025through" with no whitespace, so use \s*
    m = re.search(
        r"(\w+\s+\d{1,2},?\s+\d{4})\s*(?:through|thru|to)\s*(\w+\s+\d{1,2},?\s+\d{4})",
        text_block, re.IGNORECASE,
    )
    if m:
        d1 = _normalize_date(m.group(1))
        d2 = _normalize_date(m.group(2))
        if d1 and d2 and d1[0].isdigit():  # Successfully parsed
            return d1, d2

    # Pattern 1: "Opening/Closing Date 01/29/2025 through 02/27/2025"
    m = re.search(
        r"(\d{1,2}/\d{1,2}/\d{4})\s*(?:through|thru|to|[-–])\s*(\d{1,2}/\d{1,2}/\d{4})",
        text_block, re.IGNORECASE,
    )  # Already uses \s* on both sides
    if m:
        return _normalize_date(m.group(1)), _normalize_date(m.group(2))

    # Pattern 2: "Statement Period: January 1, 2025 - January 31, 2025"
    m = re.search(
        r"(?:statement|billing)\s*(?:period|cycle)[:\s]*(\w+\s+\d{1,2},?\s+\d{4})\s*(?:to|[-–]|through)\s*(\w+\s+\d{1,2},?\s+\d{4})",
        text_block, re.IGNORECASE,
    )  # Already uses \s* on both sides
    if m:
        return _normalize_date(m.group(1)), _normalize_date(m.group(2))

    # Pattern 3: Short year "01/29/25 - 02/27/25"
    m = re.search(
        r"(\d{1,2}/\d{1,2}/\d{2})\s*(?:through|thru|to|[-–])\s*(\d{1,2}/\d{1,2}/\d{2})",
        text_block, re.IGNORECASE,
    )  # Already uses \s* on both sides
    if m:
        return _normalize_date(m.group(1)), _normalize_date(m.group(2))

    # Pattern 4: Chase "Opening Date 01/29/25" and "Closing Date 02/27/25" on separate lines
    opening = re.search(r"OPENING\s*DATE[:\s]*(\d{1,2}/\d{1,2}/\d{2,4})", text_block, re.IGNORECASE)
    closing = re.search(r"CLOSING\s*DATE[:\s]*(\d{1,2}/\d{1,2}/\d{2,4})", text_block, re.IGNORECASE)
    if opening and closing:
        return _normalize_date(opening.group(1)), _normalize_date(closing.group(1))

    # Pattern 5: Relaxed whitespace — handles pdfplumber splitting dates across words/lines
    # Matches "Month DD , YYYY through Month DD , YYYY" with any whitespace between parts
    # Note: pdfplumber often joins "2025through" with no whitespace, so use \s*
    m = re.search(
        r"(\w+\s+\d{1,2}\s*,?\s*\d{4})\s*(?:through|thru|to)\s*(\w+\s+\d{1,2}\s*,?\s*\d{4})",
        text_block, re.IGNORECASE,
    )
    if m:
        d1 = _normalize_date(m.group(1))
        d2 = _normalize_date(m.group(2))
        if d1 and d2 and d1[0].isdigit():
            return d1, d2

    return None


def _normalize_date(date_str: str) -> str:
    """Convert various date formats to YYYY-MM-DD."""
    date_str = date_str.strip().rstrip(",")

    # Try MM/DD/YYYY
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%B %d %Y", "%B %d, %Y", "%b %d %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str  # Return as-is if we can't parse


# ── Pre-upload analysis (combines everything) ─────────────────────────────

def analyze_upload(file_bytes: bytes, filename: str) -> dict:
    """Full pre-upload analysis of a PDF file.
    Returns everything the upload UI needs to show the user before importing.

    Returns:
        {
            "filename": "Chase4730_Jan2025.pdf",
            "file_hash": "abc123...",
            "page_count": 5,
            "detected_account": "chase_4730",
            "account_confidence": {"chase_4730": 75, "chase_3072": 5},
            "detection_method": "Card number 4730 found in header + cardholder KERO",
            "period_start": "2025-01-29",
            "period_end": "2025-02-27",
            "is_checking": False,
            "raw_text": "...",
            "tables": [...],
        }
    """
    raw_text = extract_text_from_bytes(file_bytes)
    tables = extract_tables_from_bytes(file_bytes)
    page_count = get_page_count(file_bytes)
    file_hash = compute_bytes_hash(file_bytes)

    # Account detection: filename first, then content
    filename_hint = identify_account_from_filename(filename)
    content_account = identify_account_from_text(raw_text)
    confidence_scores = get_detection_confidence(raw_text)

    # Build detection explanation
    detection_reasons = []
    detected_account = None

    if filename_hint and content_account and filename_hint == content_account:
        detected_account = content_account
        detection_reasons.append(f"Filename and content both point to {content_account}")
    elif content_account:
        detected_account = content_account
        # Explain why — only show relevant signals for the detected account
        text_upper = raw_text[:3000].upper()
        is_checking_detected = content_account == "joint_checking"
        if re.search(r"CHECKING\s*(SUMMARY|ACCOUNT)", text_upper):
            detection_reasons.append("Statement type: Checking Account")
        if re.search(r"SPENDING\s*REPORT", text_upper):
            detection_reasons.append("Chase Spending Report (annual)")
        if not is_checking_detected:
            if re.search(r"(?:SPENDING\s*REPORT|ACCOUNT)\s*\S{0,5}\s*4730", text_upper):
                detection_reasons.append("Card number ...4730")
            if re.search(r"(?:SPENDING\s*REPORT|ACCOUNT)\s*\S{0,5}\s*3072", text_upper):
                detection_reasons.append("Card number ...3072")
        if re.search(r"KERO", text_upper):
            detection_reasons.append("Cardholder: Kero")
        if re.search(r"MAGGIE|MARGARET", text_upper):
            detection_reasons.append("Cardholder: Maggie")
        if re.search(r"FREEDOM|SAPPHIRE", text_upper):
            detection_reasons.append("Card: Freedom/Sapphire")
        if re.search(r"CAPITAL\s*ONE", text_upper):
            detection_reasons.append("Bank: Capital One")
        if re.search(r"APPLE\s*CARD|GOLDMAN", text_upper):
            detection_reasons.append("Apple Card")
    elif filename_hint:
        detected_account = filename_hint
        detection_reasons.append(f"Detected from filename: {filename}")

    # Period detection
    period = extract_statement_period(raw_text)
    period_start = period[0] if period else None
    period_end = period[1] if period else None

    is_checking = detected_account == "joint_checking"

    return {
        "filename": filename,
        "file_hash": file_hash,
        "page_count": page_count,
        "detected_account": detected_account,
        "account_confidence": confidence_scores,
        "detection_reasons": detection_reasons,
        "period_start": period_start,
        "period_end": period_end,
        "is_checking": is_checking,
        "raw_text": raw_text,
        "tables": tables,
    }
