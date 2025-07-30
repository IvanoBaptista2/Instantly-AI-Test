#!/usr/bin/env python3
import os
import json
import requests
from datetime import datetime, timedelta
from test import fetch_email_thread

# ─── CONFIG FROM ENV ────────────────────────────────────────────────────────────
M_TOKEN    = os.getenv("MONDAY_API_TOKEN")
BOARD_ID   = int(os.getenv("MONDAY_BOARD_ID"))   # cast to int
EMAIL_COL  = os.getenv("MONDAY_EMAIL_COL")       # e.g. "lead_email"
LAST_COL   = os.getenv("MONDAY_LAST_CONTACT")    # e.g. "date_mkspx1234"
THREAD_COL = os.getenv("MONDAY_THREAD_COL", "long_text_mkspw74e")

HEADERS = {
    "Authorization": M_TOKEN,
    "Content-Type":  "application/json",
}

# ─── GRAPHQL QUERIES ────────────────────────────────────────────────────────────
GET_ITEMS = '''
query GetStaleItems($boardId: ID!) {
  boards(ids: [$boardId]) {
    items {
      id
      column_values(ids: ["%s","%s","%s"]) {
        id
        value
        text
      }
    }
  }
}
''' % (EMAIL_COL, THREAD_COL, LAST_COL)

UPDATE_MUTATION = '''
mutation UpdateThread($boardId: Int!, $itemId: Int!, $columnValues: JSON!) {
  change_multiple_column_values(
    board_id: $boardId,
    item_id: $itemId,
    column_values: $columnValues
  ) {
    id
  }
}
'''

def sync_threads():
    print(f"\n🔄 sync_threads started at {datetime.utcnow().isoformat()}Z")

    # 1) fetch all items (only required columns)
    resp = requests.post(
        "https://api.monday.com/v2",
        headers=HEADERS,
        json={"query": GET_ITEMS, "variables": {"boardId": BOARD_ID}}
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        print("❌ GraphQL errors fetching items:", data["errors"])
        return

    items = data["data"]["boards"][0]["items"]
    cutoff = datetime.utcnow() - timedelta(days=2)

    for item in items:
        cvs = {cv["id"]: cv for cv in item["column_values"]}

        # ── extract email ─────────────────────────────────────────────────────
        raw = cvs.get(EMAIL_COL, {})
        if raw.get("value"):
            try:
                email = json.loads(raw["value"]).get("email", "")
            except json.JSONDecodeError:
                email = raw.get("text", "")
        else:
            email = raw.get("text", "")

        # ── extract last contact date ─────────────────────────────────────────
        last_raw = cvs.get(LAST_COL, {}).get("text", "")
        try:
            last_dt = datetime.fromisoformat(last_raw.replace("Z", "+00:00"))
        except ValueError:
            last_dt = cutoff - timedelta(days=1)

        # skip if recently updated
        if last_dt > cutoff:
            continue

        if not email:
            print(f"⚠️  item {item['id']} missing email, skipping")
            continue

        stored = cvs.get(THREAD_COL, {}).get("text", "")
        print(f"🔄 refetching thread for {email} (item {item['id']}), last update {last_dt.date()}")

        try:
            new_thread = fetch_email_thread(email) or ""
        except Exception as e:
            print(f"❌ failed to fetch thread for {email}: {e}")
            continue

        if new_thread.strip() == stored.strip():
            print("   ↳ no changes detected")
            continue

        # ── prepare update payload ────────────────────────────────────────────
        updated_cols = {
            THREAD_COL: {"text": new_thread},
            LAST
