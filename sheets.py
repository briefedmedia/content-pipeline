# sheets.py -- Google Sheets job tracker for the pipeline
# Uses Service Account credentials -- same service_account.json as drive.py
# Sheet schema: [timestamp, date, account_type, record_type, data]
# record_type values: script, clips, phase1_status, phase2_status, phase3_status, breaking_<id>, breaking_<id>_update

import gspread
from google.oauth2.service_account import Credentials
import datetime
import json
import os
import tempfile
from config import TMP

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def _get_service_account_file():
    json_content = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if json_content:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write(json_content)
        tmp.close()
        return tmp.name
    return "service_account.json"

SERVICE_ACCOUNT_FILE = _get_service_account_file()

_sheet       = None
_spreadsheet = None

def _get_spreadsheet():
    """Lazy-initialize gspread spreadsheet object (needed for multi-worksheet access)."""
    global _spreadsheet
    if _spreadsheet is None:
        sheet_id = os.getenv("GOOGLE_SHEET_ID")
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        gc = gspread.authorize(creds)
        _spreadsheet = gc.open_by_key(sheet_id) if sheet_id else gc.open("pipeline_log")
    return _spreadsheet

def _get_sheet():
    """Lazy-initialize gspread connection to avoid import-time failures."""
    global _sheet
    if _sheet is None:
        _sheet = _get_spreadsheet().sheet1
    return _sheet

# =========================
# JOB LOGGING
# =========================

def log_job(account_type, phase=None, status="success", note=""):
    try:
        sheet = _get_sheet()
        now   = datetime.datetime.now()
        row   = [
            now.strftime("%Y-%m-%d"),
            now.strftime("%I:%M %p"),
            str(account_type).upper(),
            f"Phase {phase}",
            str(status).upper(),
            note[:200] if note else "",
        ]
        sheet.append_row(row, value_input_option="RAW")
        print(f"  [Sheets] {row[0]} {row[1]} | {row[2]} {row[3]} | {row[4]}")
    except Exception as e:
        print(f"  [Sheets] log_job failed (non-fatal): {e}")

# =========================
# SCRIPT SAVE / LOAD
# =========================

def save_todays_script(script_data, account_type):
    """Save full script_data JSON so Phase 2 and Phase 3 can reload it."""
    sheet = _get_sheet()
    now = datetime.datetime.now().isoformat()
    today = datetime.date.today().isoformat()
    sheet.append_row([now, today, account_type, "script", json.dumps(script_data)])
    print(f"[Sheets] Saved script for {account_type}: {script_data.get('title','')}")
    return True

def load_todays_script(account_type, slug=None):
    """Load today's script_data dict (title, script, scenes, etc.).
    If slug is provided, matches the specific story by slug (supports multiple
    stories of the same account_type on the same day).
    """
    sheet = _get_sheet()
    today = datetime.date.today().isoformat()
    rows  = sheet.get_all_values()
    for row in reversed(rows):
        if len(row) >= 5 and row[1] == today and row[2] == account_type and row[3] == "script":
            data = json.loads(row[4])
            if slug is None or data.get("slug") == slug:
                return data
    raise ValueError(f"No script found for {account_type} on {today}" + (f" slug={slug}" if slug else ""))

# =========================
# CLIPS SAVE / LOAD
# =========================

def save_todays_clips(clip_paths, account_type):
    """Save clip Drive IDs so Phase 3 can download and reassemble them.

    Stores the slug subdir alongside each clip name so load_todays_clips
    can reconstruct the full TMP/<slug>/filename path on any platform.
    """
    sheet = _get_sheet()
    now   = datetime.datetime.now().isoformat()
    today = datetime.date.today().isoformat()
    clip_records = []
    for c in clip_paths:
        path   = c.get("path", "")
        name   = os.path.basename(path)
        # subdir is the immediate parent directory name (the slug)
        subdir = os.path.basename(os.path.dirname(path)) if path else ""
        clip_records.append({
            "drive_id": c["drive_id"],
            "name":     name,
            "subdir":   subdir,   # e.g. "2026-03-24_trump-greenland"
        })
    sheet.append_row([now, today, account_type, "clips", json.dumps(clip_records)])
    print(f"[Sheets] Saved {len(clip_records)} clip IDs for {account_type}")

def load_todays_clips(account_type, slug=None):
    """Load today's clips, downloading from Drive into TMP/<slug>/ as needed.
    If slug is provided, matches the specific story by slug subdir (supports
    multiple stories of the same account_type on the same day).
    """
    from drive import download_file
    sheet = _get_sheet()
    today = datetime.date.today().isoformat()
    rows  = sheet.get_all_values()
    clip_records = None
    for row in reversed(rows):
        if len(row) >= 5 and row[1] == today and row[2] == account_type and row[3] == "clips":
            records = json.loads(row[4])
            if slug is None or (records and records[0].get("subdir", "").startswith(slug)):
                clip_records = records
                break
    if not clip_records:
        raise ValueError(f"No clips found for {account_type} on {today}" + (f" slug={slug}" if slug else ""))
    clip_paths = []
    for c in clip_records:
        subdir = c.get("subdir", "")
        if subdir:
            local_dir  = os.path.join(TMP, subdir)
            os.makedirs(local_dir, exist_ok=True)
            local_path = os.path.join(local_dir, c["name"])
        else:
            # Legacy records (no subdir stored) — fall back to TMP root
            local_path = os.path.join(TMP, c["name"])
        if not os.path.exists(local_path):
            print(f"Downloading clip from Drive: {c['name']}")
            download_file(c["drive_id"], local_path)
        clip_paths.append({"path": local_path, "drive_id": c["drive_id"]})
    return clip_paths

# =========================
# JOB STATUS QUERIES
# =========================

def get_todays_job(account_type):
    """Return a dict with phase statuses for today's job (used by watcher.py and /status)."""
    sheet = _get_sheet()
    today = datetime.date.today().isoformat()
    rows = sheet.get_all_values()
    job = {}
    for row in rows:
        if len(row) >= 5 and row[1] == today and row[2] == account_type:
            key = row[3]
            if "Phase 1" in key or "phase1" in key:
                job["phase1_status"] = row[4].lower()
                job["phase1_time"]   = row[0]
            elif "Phase 2" in key or "phase2" in key:
                job["phase2_status"] = row[4].lower()
                job["phase2_time"]   = row[0]
            elif "Phase 3" in key or "phase3" in key:
                job["phase3_status"] = row[4].lower()
                job["phase3_time"]   = row[0]
                job["phase3_note"]   = row[5] if len(row) > 5 else ""
    return job if job else None

def get_weeks_jobs():
    """Return scripts from the past 7 days for the weekly recap."""
    sheet = _get_sheet()
    today = datetime.date.today()
    week_ago = (today - datetime.timedelta(days=7)).isoformat()
    today_str = today.isoformat()
    rows = sheet.get_all_values()
    jobs = []
    for row in rows:
        if len(row) >= 5 and row[3] == "script":
            date = row[1]
            if week_ago <= date <= today_str:
                try:
                    script_data = json.loads(row[4])
                    script_data["date"] = date
                    script_data["account_type"] = row[2]
                    jobs.append(script_data)
                except Exception:
                    pass
    return jobs

# =========================
# BREAKING NEWS
# =========================

def create_breaking_job(story, script, account_type):
    """Create a breaking news job entry; returns a job_id string."""
    sheet = _get_sheet()
    now = datetime.datetime.now().isoformat()
    today = datetime.date.today().isoformat()
    ts = int(datetime.datetime.now().timestamp())
    job_id = f"{today}_{account_type}_{ts}"
    data = json.dumps({"story": story, "script": script, "status": "created"})
    sheet.append_row([now, today, account_type, f"breaking_{job_id}", data])
    print(f"[Sheets] Created breaking job: {job_id}")
    return job_id

def update_breaking_job(job_id, updates):
    """Append an update row for a breaking news job."""
    sheet = _get_sheet()
    now = datetime.datetime.now().isoformat()
    today = datetime.date.today().isoformat()
    sheet.append_row([now, today, "", f"breaking_{job_id}_update", json.dumps(updates)])
    print(f"[Sheets] Updated breaking job: {job_id}")


# =========================
# COST TRACKING
# =========================

def log_cost(tracker_summary):
    """Log a per-story cost breakdown to the 'costs' worksheet."""
    try:
        spreadsheet = _get_spreadsheet()
        try:
            ws = spreadsheet.worksheet("costs")
        except Exception:
            ws = spreadsheet.add_worksheet(title="costs", rows="1000", cols="10")
            ws.append_row(
                ["timestamp", "date", "slug", "account_type", "total",
                 "by_service", "entries"],
                value_input_option="RAW"
            )
        now = datetime.datetime.now().isoformat()
        ws.append_row([
            now,
            tracker_summary.get("date", ""),
            tracker_summary.get("slug", ""),
            tracker_summary.get("account_type", ""),
            tracker_summary.get("total", 0),
            json.dumps(tracker_summary.get("by_service", {})),
            json.dumps(tracker_summary.get("entries", [])),
        ], value_input_option="RAW")
        print(f"  [Sheets] Cost logged: ${tracker_summary.get('total', 0):.4f}")
    except Exception as e:
        print(f"  [Sheets] log_cost failed (non-fatal): {e}")


def get_cost_summary(n_days=30):
    """Return cost rows from the 'costs' worksheet for the past n_days."""
    try:
        spreadsheet = _get_spreadsheet()
        try:
            ws = spreadsheet.worksheet("costs")
        except Exception:
            return {"rows": [], "total": 0.0, "by_service": {}}
        rows = ws.get_all_values()
        if len(rows) < 2:
            return {"rows": [], "total": 0.0, "by_service": {}}
        cutoff     = (datetime.date.today() - datetime.timedelta(days=n_days)).isoformat()
        result_rows = []
        total       = 0.0
        by_service  = {}
        for row in rows[1:]:
            if len(row) < 5:
                continue
            date = row[1] if len(row) > 1 else ""
            if date < cutoff:
                continue
            try:
                row_total = float(row[4])
                total    += row_total
                svc_data  = json.loads(row[5]) if len(row) > 5 and row[5] else {}
                for svc, cost in svc_data.items():
                    by_service[svc] = round(by_service.get(svc, 0.0) + cost, 6)
                result_rows.append({
                    "date":         date,
                    "slug":         row[2] if len(row) > 2 else "",
                    "account_type": row[3] if len(row) > 3 else "",
                    "total":        row_total,
                    "by_service":   svc_data,
                })
            except Exception:
                continue
        return {"rows": result_rows, "total": round(total, 4), "by_service": by_service}
    except Exception as e:
        print(f"  [Sheets] get_cost_summary failed: {e}")
        return {"rows": [], "total": 0.0, "by_service": {}}


# =========================
# JOB QUEUE (shared between pipeline-api and pipeline-cron)
# =========================

_job_queue_ws = None

def _get_job_queue_ws():
    """Get or create the job_queue worksheet."""
    global _job_queue_ws
    if _job_queue_ws is None:
        spreadsheet = _get_spreadsheet()
        try:
            _job_queue_ws = spreadsheet.worksheet("job_queue")
        except Exception:
            _job_queue_ws = spreadsheet.add_worksheet(title="job_queue", rows="500", cols="7")
            _job_queue_ws.append_row(
                ["timestamp", "job_type", "status", "params", "error", "updated_at", "row_id"],
                value_input_option="RAW"
            )
    return _job_queue_ws


def enqueue_job(job_type, **params):
    """Write a pending job row. Returns the job dict."""
    try:
        ws = _get_job_queue_ws()
        now = datetime.datetime.now().isoformat()
        row_id = f"{job_type}_{int(datetime.datetime.now().timestamp())}"
        ws.append_row([
            now,                        # timestamp
            job_type,                   # job_type
            "pending",                  # status
            json.dumps(params),         # params
            "",                         # error
            now,                        # updated_at
            row_id,                     # row_id
        ], value_input_option="RAW")
        print(f"  [Sheets] Job enqueued: {job_type} ({row_id})")
        return {"row_id": row_id, "type": job_type, "status": "pending", **params}
    except Exception as e:
        print(f"  [Sheets] enqueue_job failed: {e}")
        return None


def poll_pending_jobs():
    """Read all pending jobs from the job_queue worksheet. Returns list of dicts with sheet row numbers."""
    try:
        ws = _get_job_queue_ws()
        rows = ws.get_all_values()
        pending = []
        for i, row in enumerate(rows):
            if i == 0:
                continue  # skip header
            if len(row) < 4:
                continue
            if row[2] == "pending":
                params = {}
                try:
                    params = json.loads(row[3])
                except Exception:
                    pass
                pending.append({
                    "sheet_row": i + 1,  # 1-based for gspread
                    "timestamp": row[0],
                    "type":      row[1],
                    "status":    row[2],
                    "params":    params,
                    "row_id":    row[6] if len(row) > 6 else "",
                })
        return pending
    except Exception as e:
        print(f"  [Sheets] poll_pending_jobs failed: {e}")
        return []


def update_job_status(sheet_row, status, error=None):
    """Update a job row's status. sheet_row is 1-based."""
    try:
        ws = _get_job_queue_ws()
        now = datetime.datetime.now().isoformat()
        ws.update_cell(sheet_row, 3, status)        # column C = status
        ws.update_cell(sheet_row, 6, now)            # column F = updated_at
        if error:
            ws.update_cell(sheet_row, 5, str(error)[:200])  # column E = error
        print(f"  [Sheets] Job row {sheet_row} → {status}")
    except Exception as e:
        print(f"  [Sheets] update_job_status failed: {e}")


def prune_old_jobs(hours=48):
    """Delete completed/error jobs older than N hours."""
    try:
        ws = _get_job_queue_ws()
        rows = ws.get_all_values()
        cutoff = (datetime.datetime.now() - datetime.timedelta(hours=hours)).isoformat()
        rows_to_delete = []
        for i, row in enumerate(rows):
            if i == 0:
                continue
            if len(row) < 3:
                continue
            if row[2] in ("complete", "error") and row[0] < cutoff:
                rows_to_delete.append(i + 1)
        # Delete in reverse order so indices stay valid
        for row_num in reversed(rows_to_delete):
            ws.delete_rows(row_num)
        if rows_to_delete:
            print(f"  [Sheets] Pruned {len(rows_to_delete)} old jobs")
    except Exception as e:
        print(f"  [Sheets] prune_old_jobs failed: {e}")


# =========================
# APPROVALS (shared state between pipeline-api and pipeline-cron)
# =========================

_approvals_ws = None

def _get_approvals_ws():
    """Get or create the approvals worksheet."""
    global _approvals_ws
    if _approvals_ws is None:
        spreadsheet = _get_spreadsheet()
        try:
            _approvals_ws = spreadsheet.worksheet("approvals")
        except Exception:
            _approvals_ws = spreadsheet.add_worksheet(title="approvals", rows="400", cols="3")
            _approvals_ws.append_row(
                ["date", "data", "updated_at"],
                value_input_option="RAW"
            )
    return _approvals_ws


def load_approvals_for_date(date):
    """Load approval data for a specific date. Returns dict."""
    try:
        ws = _get_approvals_ws()
        rows = ws.get_all_values()
        for row in reversed(rows):
            if len(row) >= 2 and row[0] == date:
                return json.loads(row[1])
        return {}
    except Exception as e:
        print(f"  [Sheets] load_approvals_for_date failed: {e}")
        return {}


def save_approvals_for_date(date, data):
    """Save approval data for a specific date. Upserts (updates existing row or appends new)."""
    try:
        ws = _get_approvals_ws()
        rows = ws.get_all_values()
        now = datetime.datetime.now().isoformat()
        for i, row in enumerate(rows):
            if len(row) >= 1 and row[0] == date:
                ws.update_cell(i + 1, 2, json.dumps(data))
                ws.update_cell(i + 1, 3, now)
                return
        ws.append_row([date, json.dumps(data), now], value_input_option="RAW")
    except Exception as e:
        print(f"  [Sheets] save_approvals_for_date failed: {e}")


def load_all_approvals():
    """Load all approval data. Returns dict keyed by date."""
    try:
        ws = _get_approvals_ws()
        rows = ws.get_all_values()
        result = {}
        for row in rows[1:]:
            if len(row) >= 2 and row[0]:
                try:
                    result[row[0]] = json.loads(row[1])
                except Exception:
                    continue
        return result
    except Exception as e:
        print(f"  [Sheets] load_all_approvals failed: {e}")
        return {}


# =========================
# GRANULAR PROGRESS
# =========================

def get_phase_progress(account_type, date=None):
    """Read the latest progress notes for each phase today. Returns dict."""
    try:
        if date is None:
            date = datetime.date.today().isoformat()
        sheet = _get_sheet()
        rows = sheet.get_all_values()
        progress = {}
        for row in rows:
            if len(row) < 6:
                continue
            if row[0] == date and row[2].upper() == account_type.upper():
                key = row[3]
                status = row[4].lower()
                note = row[5] if len(row) > 5 else ""
                phase_key = None
                if "Phase 1" in key or "phase1" in key:
                    phase_key = "phase1"
                elif "Phase 2" in key or "phase2" in key:
                    phase_key = "phase2"
                elif "Phase 3" in key or "phase3" in key:
                    phase_key = "phase3"
                if phase_key:
                    if phase_key not in progress:
                        progress[phase_key] = {"status": status, "notes": []}
                    progress[phase_key]["status"] = status
                    if note:
                        progress[phase_key]["notes"].append(note)
        return progress
    except Exception as e:
        print(f"  [Sheets] get_phase_progress failed: {e}")
        return {}
