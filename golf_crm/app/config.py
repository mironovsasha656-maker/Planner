"""Application settings and demo constants.

All values here are demo values for the presentation prototype.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("GOLF_CRM_DB", BASE_DIR / "golf_crm.db"))
LOG_DIR = BASE_DIR / "logs"

HOST = "127.0.0.1"
PORT = 8000

# Annual membership fee in rubles (demo values).
MEMBERSHIP_FEES = {
    "adult": 5000,
    "junior": 2500,
    "senior": 2500,
}
# Days a member has to pay an issued membership invoice.
MEMBERSHIP_PAYMENT_TERM_DAYS = 30

# Age category boundaries.
JUNIOR_MAX_AGE = 17  # under 18
SENIOR_MIN_AGE = 50

# Warn about official certifications expiring within this many days.
CERT_WARNING_DAYS = 60

PAGE_SIZE = 25

# Request body limit for forms (bytes).
MAX_FORM_BYTES = 64 * 1024

# Fixed random seed for reproducible demo data.
SEED = 20260930
