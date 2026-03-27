"""
Direct parser for Chase Spending Report PDFs.
These are annual spending summaries organized by category with pre-structured transaction rows.
No Claude API needed — instant parsing, handles 25+ page reports in <1 second.

Format detected by: "Spending Report" + "4730"/"3072" in first page + category headers like FOOD_AND_DRINK.
"""

import re
from collections import defaultdict
from datetime import datetime
from typing import Optional

import pdfplumber
import io


# Chase spending report categories → app categories
CHASE_TO_APP = {
    "FOOD_AND_DRINK": "Dining Out",
    "GROCERIES": "Groceries",
    "SHOPPING": "Other Shopping",
    "GAS": "Gas",
    "BILLS_AND_UTILITIES": "Housing & Utilities",
    "HEALTH_AND_WELLNESS": "Healthcare & Medical",
    "ENTERTAINMENT": "Kids & Baby",
    "GIFTS_AND_DONATIONS": "Giving & Church",
    "HOME": "Home Improvement",
    "AUTOMOTIVE": "Transportation",
    "TRAVEL": "Travel",
    "PERSONAL": "Personal Care",
    "EDUCATION": "Education",
    "FEES_AND_ADJUSTMENTS": "Fees & Interest",
}

# All known category headers (for section detection)
CATEGORY_HEADERS = set(CHASE_TO_APP.keys())


def is_spending_report(text: str) -> bool:
    """Check if a PDF's text is a Chase Spending Report (vs a monthly statement)."""
    header = text[:1000].upper()
    return "SPENDING REPORT" in header or "SPENDING BY CATEGORY" in header


def refine_category(desc: str, chase_cat: str) -> str:
    """Merchant-level category refinement. Much more accurate than Chase's broad categories."""
    d = desc.upper()

    # Costco (split from Shopping/Groceries)
    if re.search(r"COSTCO|WWW COSTCO", d):
        return "Costco"

    # Amazon (split from Shopping)
    if re.search(r"AMAZON|AMZN", d):
        return "Amazon"

    # Groceries — even if Chase says Shopping or Food & Drink
    if re.search(r"SAFEWAY|HMART|H MART|FRED.MEYER|TRADER JOE|WHOLEFDS|QFC|WAL.MART|NESPRESSO|"
                 r"LYNNWOOD MEDITER|BYBLOS MEDITER|HOLLYWOOD BAKED|T&T SUPERMARKET|"
                 r"SMART AND FINAL|STATERBROS|TINY.S ORGANIC|203 FAHRENHEIT COFFE", d):
        return "Groceries"

    # Clothing & Fashion
    if re.search(r"NORDSTROM|ZARA|GAP\b|CARTER|VINEYARD|TUCKERNUCK|OLD NAVY|RALPH LAUREN|"
                 r"ARITZIA|MADEWELL|UNIQLO|LACOSTE|TOMMY HILF|PUMA|TORY BURCH|EVERLANE|"
                 r"FJALLRAVEN|OAK AND FORT|TED ?BAKER|KYTE BABY|ECCO |CROCS|JANIE AND JACK|"
                 r"TNF TULALIP|SEATTLE ?PREMIUM|POLO FACTORY|HM\.COM|SUR LA TABLE", d):
        return "Clothing & Fashion"

    # Home Improvement
    if re.search(r"HOME DEPOT|TERMINIX|TMX.TERMINIX|MCLENDONS|IKEA|WAYFAIR|EV GUYS|MALLORY PAINT", d):
        return "Home Improvement"

    # Subscriptions & Streaming
    if re.search(r"APPLE\.COM/BILL|APPLE\.COM/US|GOOGLE.*ONE|OPENAI|ANTHROPIC|CLAUDE\.AI|NETFLIX|HULU|DISNEY", d):
        return "Subscriptions & Streaming"

    # Daycare / Education
    if re.search(r"KIDDIE ACADEMY|KIRKLAND ACADEMY|SEG INC|NOBEL LEARN|UNITY FI SOLUTION|SEGTUITION", d):
        return "Daycare"
    if re.search(r"GOLDFISH SWIM|HERITAGE CHRISTIAN|KIDSMAGIC", d):
        return "Kids & Baby"

    # Dining Out — restaurants, coffee, fast food, work cafeteria
    if re.search(r"STARBUCKS|PANDA EXPRESS|MCDONALD|CHICK.FIL|SHAKE SHACK|CHIPOTLE|"
                 r"DOMINO|FIVE GUYS|IN.N.OUT|OLIVE GARDEN|POTBELLY|WINGSTOP|DOORDASH|"
                 r"PAPA MURPHY|BIRRIERIA|DAIRY QUEEN|SWEETGREEN|PAGLIACCI|DAVESHOTCHICKEN|"
                 r"COLD STONE|JAMBA|HANGRY JOE|DICKS DRIVE|DUE. CUCINA|STONE KOREAN|"
                 r"85C BAKERY|TOUS LES JOURS|FRENCH BAKERY|BEECHER.S|SEMICOLON CAFE|"
                 r"ANTHONY.S|FISHERMAN|SALMON COOKER|OTO SUSHI|COMO\b|TIPSY COW|"
                 r"ARIRANG|TANOOR|ARAYA.S|MOSS BAY|GILBERT|WING DOME|GYRO GUYS|"
                 r"BJS RESTAURANT|SUSHI TAISHO|VON.S 1000|GIP.S DOWN|PORT OF PERI|"
                 r"ASCEND PRIME|MERCURYS COFFEE|CAFFE.D.ARTE|URBAN CITY COFFEE|"
                 r"WOODS COFFEE|THRULINE COFFEE|WHIDBEY COFFEE|YEZI COCONUT|DABOBA|"
                 r"SWANKY SCOOP|MCMENAMINS|KANISHKA|CALOZZI|520 BAR AND GRILL|"
                 r"AXUM FOODS|SKINNY D|MOLLY MOON|ZOKA COFFEE|JOECOFFEE|SIRENA GELATO|"
                 r"BEN.*JERRY|GELATOLOVE|TOMMY V.S|BLAZING BAGEL|SEOUL BOWL|RAYS BOAT|"
                 r"HIGH FLYING|BEACH WOLF|LANCER|WINGSTOP|IKEA.*REST|CHOPS\b|"
                 r"BOEING 4[05]|BOEING 2-|BOEING PNT|AMK BOEING|PREMERA ML|CTLP.WOLFGANG|"
                 r"365 MARKET|LADERACH", d):
        return "Dining Out"

    # Gas stations
    if re.search(r"SHELL|76 - JUANITA|CHEVRON|ARCO|SAFEWAY FUEL", d):
        return "Gas"

    # Church / Giving
    if re.search(r"ST\.? GEORGE|ARCHANGELS|SAINT MARY|SAINT MARK|COPTIC|CAIRO STREET|"
                 r"PAYPAL.*GIVEFUND|KIDSQUEST", d):
        return "Giving & Church"

    # Personal Care
    if re.search(r"GREAT CLIPS|BROW.*BEAUTY|SKINLUXE|SHARKEY|PAMPER NAIL|LILY.S NAIL|"
                 r"SUGAR PLUM|BROW ARC", d):
        return "Personal Care"

    # Healthcare
    if re.search(r"ALLEGRO.?PEDIATRIC|EVERGREENHEALTH|WALGREENS|KIRKLAND FAMILY DENT|"
                 r"VISIONWORKS|NATERA|ELEVATE.PT|DR BRIAN", d):
        return "Healthcare & Medical"

    # Insurance
    if re.search(r"CCS COUNTRY|AGI.RENTERS", d):
        return "Car Insurance"

    # Utilities (even if in BILLS category)
    if re.search(r"PUGET SOUND|NORTHSHORE UTIL|COMCAST|XFINITY|CITY OF KIRKLAND|"
                 r"KC SOLID|MINT MOBILE|ATT.\s*BILL|T-MOBILE", d):
        return "Housing & Utilities"

    # Target, Ross, Goodwill etc
    if re.search(r"TARGET|ROSS|GOODWILL|MICHAELS|DOLLAR.?TREE|BATH.*BODY|PARTY FOR LESS|"
                 r"BARNES.*NOBLE|REI\b|LEGO\b|BESTBUY|BEYOND|TEMU|HOMEGOODS|"
                 r"SQ.*KIDS MAGIC|UPS STORE|PRESCHOOL SMILES", d):
        return "Other Shopping"

    # Kids / Entertainment
    if re.search(r"RIDGE ACTIVITY|IMAGINE CHILD|TWINKLE|LEGOLAND|POINT DEFIANCE|PDZA|"
                 r"SWANS TRAIL|AQUARIUM|BOEING.*FLIGHT", d):
        return "Kids & Baby"

    # Travel
    if re.search(r"DELTA AIR|EDGEWATER|PARKWHIZ|DIAMOND PARKING|HANGTAG|QATAR AIR|"
                 r"WSDOT|PIKE PLACE|OVERLAKE HOSPITAL", d):
        return "Travel"

    # Automotive
    if re.search(r"TESLA|TOYOTA OF KIRKLAND", d):
        return "Transportation"

    # Interest charges
    if re.search(r"INTEREST CHARGE", d):
        return "Fees & Interest"

    # Fallback to Chase's category
    return CHASE_TO_APP.get(chase_cat, "Other")


def parse_spending_report(file_bytes: bytes, filename: str = "", raw_text: str = "") -> dict:
    """Parse a Chase Spending Report PDF.

    Args:
        file_bytes: Raw PDF bytes
        filename: Original filename
        raw_text: Pre-extracted text (if available from analyze_upload, avoids re-parsing)

    Returns same structure as other parsers for consistency with the upload flow.
    """
    if raw_text:
        text = raw_text
    else:
        text = ""
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                text += (page.extract_text() or "") + "\n"

    # Detect account
    header = text[:500]
    account_id = None
    if "4730" in header:
        account_id = "chase_4730"
    elif "3072" in header:
        account_id = "chase_3072"

    # Detect period — handle both "January 01, 2025 to December 31, 2025" and "Jan 01, 2025 to Dec 31, 2025"
    period_start = period_end = None
    period_match = re.search(r'(\w+\s+\d{1,2},?\s+\d{4})\s+to\s+(\w+\s+\d{1,2},?\s+\d{4})', text[:2000])
    if period_match:
        for fmt in ("%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y"):
            try:
                period_start = datetime.strptime(period_match.group(1).strip(), fmt).strftime("%Y-%m-%d")
                period_end = datetime.strptime(period_match.group(2).strip(), fmt).strftime("%Y-%m-%d")
                break
            except ValueError:
                continue

    # Parse transactions
    transactions = []
    current_category = None

    # Transaction row pattern: "Mon DD, YYYY  Mon DD, YYYY  DESCRIPTION  $Amount"
    TXN_PATTERN = re.compile(
        r'([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})\s+'  # Transaction date
        r'[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}\s+'     # Posted date (ignored)
        r'(.+?)\s+'                                   # Description
        r'\$(-?[\d,]+\.\d{2})$'                       # Amount
    )

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        # Category header?
        if line in CATEGORY_HEADERS:
            current_category = line
            continue

        # Skip the "Transaction Date Posted Date Description Amount" header row
        if line.startswith("Transaction Date"):
            continue
        # Skip total lines
        if line.startswith("Total "):
            continue

        # Try to match transaction
        m = TXN_PATTERN.match(line)
        if m and current_category:
            date_str = m.group(1)
            desc = m.group(2).strip()
            amount_str = m.group(3).replace(",", "")
            amount = float(amount_str)

            try:
                txn_date = datetime.strptime(date_str, "%b %d, %Y").strftime("%Y-%m-%d")
            except ValueError:
                continue

            category = refine_category(desc, current_category)

            # In spending reports: positive = charge, negative = refund/credit
            # Our DB convention: negative = charge, positive = credit
            transactions.append({
                "date": txn_date,
                "description": desc,
                "raw_description": desc,
                "amount": -amount,  # flip sign: charges become negative
                "category": category,
                "confidence": 0.92,
                "notes": f"Chase: {current_category}",
            })

    # Build analysis notes
    cat_totals = defaultdict(float)
    for t in transactions:
        cat_totals[t["category"]] += abs(t["amount"])
    top_cats = sorted(cat_totals.items(), key=lambda x: -x[1])[:5]
    analysis = f"Parsed {len(transactions)} transactions from Chase Spending Report. "
    analysis += "Top categories: " + ", ".join(f"{c} ${v:,.0f}" for c, v in top_cats)

    return {
        "account_id": account_id,
        "period_start": period_start,
        "period_end": period_end,
        "status": "new",
        "transactions": transactions,
        "statement_summary": {
            "total_charges": sum(t["amount"] for t in transactions if t["amount"] < 0),
            "total_credits": sum(t["amount"] for t in transactions if t["amount"] > 0),
            "transaction_count": len(transactions),
        },
        "analysis_notes": analysis,
        "source": "chase_spending_report",
    }


# ── Chase Checking Statement Parser ──────────────────────────────────────

# Transaction line: "MM/DD [optional MM/DD] description amount balance"
_CHECKING_TXN = re.compile(
    r'^(\d{2}/\d{2})\s+'           # Transaction date MM/DD
    r'(?:\d{2}/\d{2}\s+)?'         # Optional posting/second date
    r'(.+?)\s+'                     # Description (lazy match)
    r'(-?[\d,]+\.\d{2})\s+'        # Amount
    r'-?[\d,]+\.\d{2}'             # Balance (captured but ignored)
)

# Lines that signal end of transaction detail
_SECTION_ENDS = (
    "A Monthly Service Fee",
    "IN CASE OF ERRORS",
    "Overdraft and Overdraft Fee",
    "CHECKS PAID",
    "This Page Intentionally",
)


def _infer_year(txn_month: int, period_start: str, period_end: str) -> int:
    """Infer the correct year for a MM/DD date given the statement period.

    For same-year periods (e.g., Sep 28 - Oct 27, 2022), returns that year.
    For cross-year periods (e.g., Dec 28, 2022 - Jan 27, 2023):
      - months >= start month → start year
      - months < start month  → end year
    """
    from datetime import date as _date
    start = _date.fromisoformat(period_start)
    end = _date.fromisoformat(period_end)

    if start.year == end.year:
        return start.year

    # Cross-year: Dec-Jan boundary
    if txn_month >= start.month:
        return start.year
    return end.year


def _preprocess_checking_lines(text: str) -> list[str]:
    """Extract transaction lines from checking statement text, joining multi-line entries."""
    lines = text.split('\n')
    in_txn_section = False
    txn_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Detect start of transaction detail (may appear multiple times for continued sections)
        if 'TRANSACTION DETAIL' in stripped:
            in_txn_section = True
            continue

        if not in_txn_section:
            continue

        # Skip headers
        if stripped.startswith('DATE') and 'DESCRIPTION' in stripped:
            continue
        if 'Beginning Balance' in stripped or 'Ending Balance' in stripped:
            continue
        if stripped.startswith('Page ') or 'JPMorgan' in stripped:
            continue

        # End of transaction section?
        if any(stripped.startswith(end) for end in _SECTION_ENDS):
            in_txn_section = False
            continue

        # New transaction line?
        if re.match(r'\d{2}/\d{2}\s', stripped):
            txn_lines.append(stripped)
        elif txn_lines:
            # Continuation of previous line (multi-line description)
            txn_lines[-1] += ' ' + stripped

    return txn_lines


def refine_checking_category(desc: str) -> str:
    """Categorize checking account transactions by merchant/description."""
    d = desc.upper()

    # Income / Paychecks
    if re.search(r'BOEING.*(?:DIR DEP|PAYROLL)|PREMERA.*PAYROLL|TRINET.*PAYROLL|FLAGSHIPR.*DIR DEP|'
                 r'PAID LEAVE WA|CASH REDEMPTION|IRS\s*TREAS.*TAX REF|NORTH LANE.*NL ACH|'
                 r'REMOTE ONLINE DEPOSIT', d):
        return "Income & Refunds"

    # Housing (rent / mortgage)
    if re.search(r'AVENUE5|MR\.?\s*COOPER|MORTGAGE', d):
        return "Housing & Utilities"

    # Utilities
    if re.search(r'PUGET SOUND|CITY ELMHURST|NORTHSHORE', d):
        return "Housing & Utilities"

    # Car payment / Auto loan
    if re.search(r'TOYOTA FINANCIAL|TOYOTA ACH|ONLINE PAYMENT.*AUTO LOAN', d):
        return "Car Payment"

    # Credit card payments
    if re.search(r'PAYMENT TO CHASE CARD|CHASE CREDIT CRD|CHASE CREDIT CRD AUTOPAY|'
                 r'CAPITAL ONE|DISCOVER BANK|DISCOVER.*NET/MOBILE|APPLECARD|MACYS PAYMENT|'
                 r'FID BKG SVC|AFFIRM.*PAY', d):
        return "Transfers & Payments"

    # Church / Giving (Zelle)
    if re.search(r'ZELLE.*(?:ST\.?\s*GEORGE|CHURCH|COPTIC)', d):
        return "Giving & Church"

    # Family support (Zelle)
    if re.search(r'ZELLE.*(?:MAMA|NERMEEN|MAGED|GEORGE|DODO)', d):
        return "Family Support"

    # Student loans
    if re.search(r'DEPT EDUCATION|STUDENT LN|EDUCATIONAL COMP', d):
        return "Debt Payments"

    # Savings transfers
    if re.search(r'ONLINE TRANSFER TO SAV|ONLINE TRANSFER FROM SAV', d):
        return "Transfers & Payments"

    # Zelle (other)
    if re.search(r'ZELLE PAYMENT', d):
        return "Transfers & Payments"

    # Debit card purchases at stores
    if re.search(r'COSTCO|SAFEWAY|HMART', d):
        return "Groceries"
    if re.search(r'AMAZON|AMZN', d):
        return "Amazon"

    # ATM
    if re.search(r'ATM\s*(CASH|WITHDRAW)', d):
        return "Transfers & Payments"

    # Fees
    if re.search(r'COUNTER CHECK|NON-CHASE ATM FEE', d):
        return "Fees & Interest"

    # State relief / refunds / deposits
    if re.search(r'STATE OF ILL|ILSTRELIEF|DEPOSIT\s+\d|IRS\s+USATAXPYMT', d):
        return "Income & Refunds"

    # Daycare
    if re.search(r'KIDDIE ACADEMY|SEGTUITION', d):
        return "Daycare"

    # Utilities (from checking)
    if re.search(r'COMCAST.*XFINITY|T-MOBILE.*PCS|T-MOBILE.*HANDSET', d):
        return "Housing & Utilities"

    # Wire transfers
    if re.search(r'WIRE TRANSFER|DOMESTIC WIRE', d):
        return "Transfers & Payments"

    # 529 / education savings
    if re.search(r'UGIFT529|529GIFT|FIDELITY.*529', d):
        return "Education"

    # Venmo
    if re.search(r'VENMO', d):
        return "Transfers & Payments"

    return "Other"


def parse_checking_statement(file_bytes: bytes, filename: str = "", raw_text: str = "",
                              period_start: str = "", period_end: str = "") -> dict:
    """Parse a Chase Checking Account statement PDF.

    Args:
        file_bytes: Raw PDF bytes
        filename: Original filename
        raw_text: Pre-extracted text (avoids re-parsing)
        period_start: Statement period start (YYYY-MM-DD), from pdf_parser
        period_end: Statement period end (YYYY-MM-DD), from pdf_parser

    Returns same structure as other parsers.
    """
    if not raw_text:
        text = ""
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                text += (page.extract_text() or "") + "\n"
        raw_text = text

    # ── Period detection: multiple strategies ──────────────────────────
    if not period_start or not period_end:
        from pdf_parser import extract_statement_period
        period = extract_statement_period(raw_text)
        if period:
            period_start, period_end = period

    # Fallback 1: Search raw text with broader patterns (handles pdfplumber quirks)
    if not period_start or not period_end:
        # Try matching "Month DD, YYYY through Month DD, YYYY" across entire text
        # with very relaxed whitespace (pdfplumber may insert odd spacing)
        # Note: pdfplumber often joins "2025through" with no whitespace, so use \s*
        m = re.search(
            r'([A-Z][a-z]+\s+\d{1,2}\s*,?\s*\d{4})\s*through\s*([A-Z][a-z]+\s+\d{1,2}\s*,?\s*\d{4})',
            raw_text[:10000],
        )
        if m:
            for fmt in ("%B %d, %Y", "%B %d %Y"):
                try:
                    period_start = datetime.strptime(m.group(1).replace("  ", " ").strip(), fmt).strftime("%Y-%m-%d")
                    period_end = datetime.strptime(m.group(2).replace("  ", " ").strip(), fmt).strftime("%Y-%m-%d")
                    break
                except ValueError:
                    continue

    # Fallback 2: Extract from filename (YYYYMMDD-statements-3829-.pdf)
    if not period_start or not period_end:
        fn_match = re.search(r'(\d{4})(\d{2})(\d{2})-statements', filename)
        if fn_match:
            end_year, end_month, end_day = fn_match.group(1), fn_match.group(2), fn_match.group(3)
            period_end = f"{end_year}-{end_month}-{end_day}"
            # Estimate start: ~30 days before end
            from datetime import date as _date, timedelta
            end_dt = _date(int(end_year), int(end_month), int(end_day))
            start_dt = end_dt - timedelta(days=31)
            period_start = start_dt.strftime("%Y-%m-%d")

    # Fallback 3: Parse transactions first with filename year, then derive period
    if not period_start or not period_end:
        # Last resort: use current year or filename year
        fn_year_match = re.search(r'(\d{4})\d{4}', filename)
        if fn_year_match:
            fallback_year = fn_year_match.group(1)
            txn_lines = _preprocess_checking_lines(raw_text)
            dates_found = []
            for line in txn_lines:
                m = _CHECKING_TXN.match(line)
                if m:
                    parts = m.group(1).split('/')
                    dates_found.append(f"{fallback_year}-{parts[0]}-{parts[1]}")
            if dates_found:
                period_start = min(dates_found)
                period_end = max(dates_found)

    if not period_start or not period_end:
        return {
            "account_id": "joint_checking",
            "period_start": None,
            "period_end": None,
            "status": "new",
            "transactions": [],
            "statement_summary": {},
            "analysis_notes": "Could not detect statement period — cannot infer transaction years.",
            "source": "chase_checking_parser",
        }

    # Preprocess: join multi-line transactions
    txn_lines = _preprocess_checking_lines(raw_text)

    transactions = []
    for line in txn_lines:
        m = _CHECKING_TXN.match(line)
        if not m:
            continue

        date_str = m.group(1)  # MM/DD
        desc = m.group(2).strip()
        amount_str = m.group(3).replace(",", "")
        amount = float(amount_str)

        # Parse month/day and infer year
        parts = date_str.split('/')
        month = int(parts[0])
        day = int(parts[1])
        year = _infer_year(month, period_start, period_end)
        txn_date = f"{year}-{month:02d}-{day:02d}"

        category = refine_checking_category(desc)

        transactions.append({
            "date": txn_date,
            "description": desc,
            "raw_description": desc,
            "amount": amount,  # Already signed correctly (negative = debit, positive = deposit)
            "category": category,
            "confidence": 0.90,
            "notes": "",
        })

    # Build analysis notes
    cat_totals = defaultdict(float)
    for t in transactions:
        cat_totals[t["category"]] += abs(t["amount"])
    top_cats = sorted(cat_totals.items(), key=lambda x: -x[1])[:5]
    analysis = f"Parsed {len(transactions)} transactions from Chase Checking Statement. "
    if top_cats:
        analysis += "Top categories: " + ", ".join(f"{c} ${v:,.0f}" for c, v in top_cats)

    return {
        "account_id": "joint_checking",
        "period_start": period_start,
        "period_end": period_end,
        "status": "new",
        "transactions": transactions,
        "statement_summary": {
            "total_deposits": sum(t["amount"] for t in transactions if t["amount"] > 0),
            "total_withdrawals": sum(t["amount"] for t in transactions if t["amount"] < 0),
            "transaction_count": len(transactions),
        },
        "analysis_notes": analysis,
        "source": "chase_checking_parser",
    }
