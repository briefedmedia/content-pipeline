# approvals.py -- shared approval state helpers used by pipeline_api.py and main.py
import json, os
from config import TMP

APPROVALS_FILE = os.path.join(TMP, "approvals.json")


def load_approvals():
    if os.path.exists(APPROVALS_FILE):
        with open(APPROVALS_FILE) as f:
            return json.load(f)
    return {}


def save_approvals(data):
    with open(APPROVALS_FILE, "w") as f:
        json.dump(data, f, indent=2)
