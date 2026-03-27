# approvals.py -- shared approval state helpers used by pipeline_api.py and main.py
# Backed by Google Sheets "approvals" worksheet so state is shared across Railway services

from sheets import load_approvals_for_date, save_approvals_for_date, load_all_approvals


def load_approvals():
    """Load all approvals. Returns dict keyed by date."""
    return load_all_approvals()


def save_approvals(data):
    """Save full approvals dict. Writes each date's data to the approvals worksheet."""
    for date, day_data in data.items():
        save_approvals_for_date(date, day_data)
