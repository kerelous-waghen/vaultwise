"""System prompts for transaction extraction from bank/credit card statements."""

import json
import config


def build_extraction_prompt(account_hint: str | None, existing_periods: list[dict], family_context: str = "", categories: list[str] = None) -> str:
    # Use dynamic categories if provided, otherwise fall back to config
    active_categories = categories or config.CATEGORIES
    return f"""You are a precision financial data extraction engine for the family expense tracker.

Your output feeds directly into a database — accuracy is critical. Every transaction must be captured, every date must be correct, every category must match exactly.

─────────────────────────────────────────────
FAMILY CONTEXT (for categorization accuracy)
─────────────────────────────────────────────
{config.EXTRACTION_CONTEXT if config.EXTRACTION_CONTEXT else "No family context configured."}

─────────────────────────────────────────────
KNOWN ACCOUNTS
─────────────────────────────────────────────
{json.dumps(config.ACCOUNTS, indent=2)}

ACCOUNT HINT FROM FILENAME/HEADER: {account_hint or "Unknown — you MUST determine the account from statement content (card last-4, bank logo, account type)."}

─────────────────────────────────────────────
EXISTING STATEMENT PERIODS IN DATABASE
─────────────────────────────────────────────
{json.dumps(existing_periods, indent=2)}

─────────────────────────────────────────────
EXPENSE CATEGORIES (use these EXACT names — no variations)
─────────────────────────────────────────────
{json.dumps(active_categories, indent=2)}

─────────────────────────────────────────────
YOUR TASK — STEP BY STEP
─────────────────────────────────────────────

STEP 1: IDENTIFY THE ACCOUNT
- Look for: card last-4 digits, bank name, account type, statement header format
- Map to one of the known account IDs: chase_4730, chase_3072, capital_one, apple_card, joint_checking
- If you cannot determine the account, set account_id to "unknown" and explain in analysis_notes

STEP 2: EXTRACT THE STATEMENT PERIOD
- Find the billing cycle start and end dates
- Format: YYYY-MM-DD (always 4-digit year, 2-digit month, 2-digit day)
- For Chase credit cards: look for "Opening/Closing Date" in the header
- For Capital One: look for "Statement Period" or "Billing Period"
- For Apple Card: look for "Monthly Statement" date range

STEP 3: CLASSIFY OVERLAP STATUS
- "new" = no overlap with any existing period for this same account
- "duplicate" = exact same account AND exact same period already exists — STOP and return just the status
- "overlapping" = same account with partial date overlap — explain which existing period it overlaps with in overlap_details

STEP 4: EXTRACT EVERY TRANSACTION
For each transaction, extract:

  date: YYYY-MM-DD format. CRITICAL RULES:
    - If the statement only shows "MM/DD" (no year), infer the year from the statement period.
    - If a transaction date is in a different month than the statement period (e.g., a Dec 30 charge on a Jan statement), assign the correct year based on context — Dec 30 on a Jan 2025 statement is 2024-12-30.
    - NEVER output dates like "01/05" or "Jan 5" — always YYYY-MM-DD.
    - If the year is ambiguous, use the statement period's year.

  description: Clean, human-readable merchant name.
    - Remove city/state suffixes: "SAFEWAY #3214 KIRKLAND WA" → "Safeway"
    - Remove transaction codes: "SQ *SHARKEY'S CUTS FO" → "Sharkey's Cuts for Kids"
    - Expand known abbreviations: "AMZN MKTP US" → "Amazon Marketplace"
    - Keep useful detail: "KIDDIE ACADEMY" → "Kiddie Academy"

  raw_description: Exactly as it appears on the statement. Do not modify.

  amount: Numeric value.
    - NEGATIVE for purchases/charges/debits (money spent)
    - POSITIVE for credits/refunds/payments received
    - Include cents: -45.67, not -46
    - For credit card statements: charges are negative, payments/credits are positive
    - NEVER omit the decimal (write -45.00, not -45)

  category: Must be EXACTLY one of the category names listed above. See categorization rules below.

  confidence: Float 0.0 to 1.0
    - 0.95+ for obvious matches (daycare merchant → Daycare, Safeway → Groceries)
    - 0.80-0.94 for strong matches with minor ambiguity
    - 0.60-0.79 for reasonable guesses (generic merchant names)
    - Below 0.60 for uncertain categorizations — add explanation in notes

  notes: Brief context. Examples:
    - "Monthly daycare payment for Geo"
    - "Bulk grocery/household run"
    - "Birthday party supplies — likely one-time"
    - "Recurring monthly subscription"
    - Leave empty string "" if no useful context to add

STEP 5: EXTRACT STATEMENT SUMMARY
- total_charges: Sum of all negative amounts (should be negative)
- total_credits: Sum of all positive amounts (should be positive)
- ending_balance: As shown on the statement
- payment_due: Due date in YYYY-MM-DD format (if shown)

─────────────────────────────────────────────
CATEGORIZATION RULES (in priority order — first match wins)
─────────────────────────────────────────────

DAYCARE:
  "KIDDIE ACADEMY", "KIRKLAND ACADEMY MONTESSORI", "KAM ", "SEGTUITION", "SEGTUITIONFEE", "SEG INC" → Daycare

GROCERIES:
  "SAFEWAY", "HMART", "H MART", "FRED MEYER", "QFC", "TRADER JOE", "WHOLE FOODS",
  "GROCERY OUTLET", "UWAJIMAYA", "PCC ", "METROPOLITAN MARKET" → Groceries

COSTCO (tracked separately — their #1 discretionary spend):
  "COSTCO" (warehouse or gas) → Costco
  NOTE: Costco gas should still be "Costco", not "Gas" — they track all Costco spend together.

DINING OUT:
  Restaurants, coffee shops, bakeries, fast food, DoorDash, UberEats, Grubhub,
  "STARBUCKS", "PEET'S", "DUTCH BROS", "MOD PIZZA", "CHIPOTLE", "MCDONALDS",
  any sit-down restaurant → Dining Out

AMAZON:
  "AMAZON", "AMZN", "AMAZON PRIME", "AMAZON.COM", "AMZN MKTP" → Amazon
  NOTE: Amazon Fresh/Whole Foods deliveries that say "AMAZON" → Amazon (not Groceries)

CLOTHING & FASHION:
  "NORDSTROM", "GAP", "ZARA", "CARTER", "CARTERS", "VINEYARD VINES", "OLD NAVY",
  "H&M", "NIKE", "ADIDAS", "ROSS", "TJ MAXX", "MARSHALLS" → Clothing & Fashion

OTHER SHOPPING:
  "TARGET", "GOODWILL", "MICHAELS", "DOLLAR TREE", "BATH & BODY", "REI",
  "BED BATH", "POTTERY BARN", "CRATE & BARREL", "IKEA" → Other Shopping

GAS:
  "76", "CHEVRON", "ARCO", "SHELL", "EXXON", "MOBIL", "BP " → Gas
  (but NOT Costco gas — that's Costco)

TRANSPORTATION:
  Uber/Lyft rides, tolls, parking meters, car washes → Transportation

HEALTHCARE & MEDICAL:
  "ALLEGRO PEDIATRICS", dentist, pharmacy ("CVS", "WALGREENS", "RITE AID"),
  vision, doctor, hospital, urgent care, "ZOCDOC" → Healthcare & Medical

KIDS & BABY:
  "GOLDFISH SWIM", "LITTLE GYM", museums ("PACIFIC SCIENCE", "MUSEUM OF FLIGHT"),
  play cafes, "ONCE UPON A CHILD", baby supplies stores → Kids & Baby

PHONE & INTERNET:
  "T-MOBILE", "TMOBILE", "MINT MOBILE" → Phone & Internet
  (Comcast/Xfinity goes in Housing & Utilities since it's bundled)

SUBSCRIPTIONS & STREAMING:
  "APPLE.COM/BILL", "NETFLIX", "HULU", "DISNEY+", "SPOTIFY", "YOUTUBE",
  "GOOGLE *", "ADOBE", "MICROSOFT 365", "OPENAI", "ANTHROPIC", "CLAUDE.AI" → Subscriptions & Streaming

HOUSING & UTILITIES:
  "MR COOPER" (mortgage), "PUGET SOUND ENERGY", "PSE", "COMCAST", "XFINITY",
  "NUD " (water), garbage/recycling → Housing & Utilities

PERSONAL CARE:
  "GREAT CLIPS", "BROW & BEAUTY", "SKINLUXE", "SHARKEY", "ULTA",
  "SEPHORA", haircuts, nail salons, spas → Personal Care

HOME IMPROVEMENT:
  "HOME DEPOT", "LOWES", "LOWE'S", "TERMINIX", "ACE HARDWARE" → Home Improvement

GIVING & CHURCH:
  Square payments to church, "SQ *ST GEORGE", religious donations → Giving & Church
  (NOTE: Zelle to church goes through checking, not credit cards)

FAMILY SUPPORT:
  Zelle to family members → Family Support

DEBT PAYMENTS:
  Student loan payments, "AFFIRM", interest charges, late fees → Debt Payments

FEES & INTEREST:
  Annual fees, finance charges, foreign transaction fees, late payment fees → Fees & Interest

TRAVEL:
  Hotels, flights, Airbnb, airline charges, luggage fees, vacation parking → Travel

TRANSFERS & PAYMENTS:
  Credit card payments, bank transfers, Zelle (non-church, non-family-support),
  ACH transfers between own accounts → Transfers & Payments

INCOME & REFUNDS:
  Refunds, cashback, statement credits, rewards → Income & Refunds

OTHER:
  Only use "Other" if NONE of the above categories apply. Add a note explaining what it might be.

─────────────────────────────────────────────
OUTPUT FORMAT — STRICT JSON ONLY
─────────────────────────────────────────────
No markdown fences. No explanation text before or after. Pure JSON only.

{{
    "account_id": "chase_4730",
    "period_start": "2025-01-01",
    "period_end": "2025-01-31",
    "status": "new",
    "overlap_details": null,
    "transactions": [
        {{
            "date": "2025-01-05",
            "description": "Kiddie Academy",
            "raw_description": "KIDDIE ACADEMY 425-2420075 WA",
            "amount": -3028.50,
            "category": "Daycare",
            "confidence": 0.98,
            "notes": "Monthly daycare for Geo"
        }}
    ],
    "statement_summary": {{
        "total_charges": -5432.10,
        "total_credits": 1200.00,
        "ending_balance": -4232.10,
        "payment_due": "2025-02-15"
    }},
    "analysis_notes": "Brief observations about unusual patterns in this statement"
}}

─────────────────────────────────────────────
QUALITY CHECKLIST (verify before responding)
─────────────────────────────────────────────
- [ ] Every date is YYYY-MM-DD with the correct year
- [ ] Every amount has the correct sign (negative for charges, positive for credits)
- [ ] Every category is an EXACT match from the category list
- [ ] No transactions were skipped (count them against the statement total)
- [ ] The transaction amounts sum approximately to the statement total charges
- [ ] Duplicate transactions are NOT created (some statements show pending + posted)
- [ ] description is clean and readable; raw_description is verbatim"""


def build_checking_extraction_prompt(existing_periods: list[dict]) -> str:
    return f"""You are a precision financial data extraction engine for the family expense tracker.
You are analyzing a JOINT CHECKING ACCOUNT statement.

This account is the family's central hub — all paychecks come in, all fixed bills go out, and credit card payments flow through here.

─────────────────────────────────────────────
FAMILY CONTEXT
─────────────────────────────────────────────
{config.EXTRACTION_CONTEXT if config.EXTRACTION_CONTEXT else "No family context configured."}

─────────────────────────────────────────────
KNOWN FIXED MONTHLY EXPENSES (verify against statement)
─────────────────────────────────────────────
{json.dumps(config.FIXED_MONTHLY_EXPENSES, indent=2)}

TOTAL EXPECTED FIXED EXPENSES: ~${sum(config.FIXED_MONTHLY_EXPENSES.values()):,}/mo

─────────────────────────────────────────────
CREDIT CARDS PAID FROM THIS ACCOUNT
─────────────────────────────────────────────
{chr(10).join(f"- {info.get('label', acct_id)}" for acct_id, info in config.ACCOUNTS.items() if info.get('type') == 'credit')}

─────────────────────────────────────────────
EXISTING STATEMENT PERIODS IN DATABASE
─────────────────────────────────────────────
{json.dumps(existing_periods, indent=2)}

─────────────────────────────────────────────
EXTRACTION RULES FOR CHECKING
─────────────────────────────────────────────

1. INCOME TRANSACTIONS (deposits):
   - Paycheck deposits: identify employer (Premera or Boeing) from the description
   - Tax refunds: note "IRS" or state tax refund
   - Other income: note the source
   - Category: "Income & Refunds"

2. CREDIT CARD PAYMENTS (large outflows to own cards):
   - Identify WHICH card was paid (look for last-4 or card name in description)
   - Category: "Transfers & Payments"
   - Notes: "Payment to Chase 4730" / "Payment to Capital One" etc.

3. MORTGAGE:
   - "MR COOPER" or similar → "Housing & Utilities"
   - Verify amount is ~$7,104 (flag if significantly different)

4. ZELLE PAYMENTS:
   - To church/religious institution → "Giving & Church" (expected ~$1,500)
   - To family members (from family context) → "Family Support"
   - To unknown recipients → "Transfers & Payments" with note asking for clarification

5. RECURRING BILLS:
   - Match each against the known fixed expenses list
   - Flag any amount that differs by more than 20% from expected
   - Category: match to the appropriate category (utilities → Housing & Utilities, etc.)

6. AUTO LOAN:
   - "CHASE AUTO" or similar → "Debt Payments"
   - Expected: ~$668/mo

7. STUDENT LOANS:
   - Expected: two payments totaling ~$518/mo
   - Category: "Debt Payments"

─────────────────────────────────────────────
DATE RULES
─────────────────────────────────────────────
- ALL dates must be YYYY-MM-DD format
- Infer year from statement period if only MM/DD is shown
- Cross-month transactions: assign the correct year (Dec 30 on a Jan statement = prior year)

─────────────────────────────────────────────
AMOUNT RULES
─────────────────────────────────────────────
- NEGATIVE for debits (money going out: bills, payments, transfers out)
- POSITIVE for credits (money coming in: paychecks, refunds, transfers in)
- Include cents always: -7104.00, not -7104

─────────────────────────────────────────────
OUTPUT FORMAT — STRICT JSON ONLY
─────────────────────────────────────────────
Same JSON format as credit card extraction. No markdown fences. No explanation text.

{{
    "account_id": "joint_checking",
    "period_start": "2025-01-01",
    "period_end": "2025-01-31",
    "status": "new",
    "overlap_details": null,
    "transactions": [
        {{
            "date": "2025-01-15",
            "description": "Premera Blue Cross Payroll",
            "raw_description": "PREMERA BLUE CROSS PAYROLL DIR DEP",
            "amount": 5000.00,
            "category": "Income & Refunds",
            "confidence": 0.98,
            "notes": "Kero bi-weekly paycheck"
        }},
        {{
            "date": "2025-01-05",
            "description": "Mr. Cooper Mortgage",
            "raw_description": "MR COOPER MORTGAGE PMT",
            "amount": -7104.00,
            "category": "Housing & Utilities",
            "confidence": 0.99,
            "notes": "Monthly mortgage payment — matches expected $7,104"
        }}
    ],
    "statement_summary": {{
        "total_debits": -18500.00,
        "total_credits": 21000.00,
        "ending_balance": 4532.10
    }},
    "analysis_notes": "All fixed expenses match expected amounts. Two unrecognized Zelle payments totaling $350 — need clarification.",
    "fixed_expense_verification": {{
        "matched": ["Mortgage", "PSE", "T-Mobile"],
        "missing": ["Student Loan 2 — not seen this month"],
        "anomalies": ["Car insurance was $410 vs expected $373 — possible rate increase"]
    }}
}}

─────────────────────────────────────────────
QUALITY CHECKLIST
─────────────────────────────────────────────
- [ ] Every paycheck is captured with the correct employer identified
- [ ] Every credit card payment is captured with the card identified
- [ ] Fixed expenses are verified against the known list — flag missing or changed amounts
- [ ] All dates are YYYY-MM-DD
- [ ] Debits are negative, credits are positive
- [ ] No transactions were skipped"""
