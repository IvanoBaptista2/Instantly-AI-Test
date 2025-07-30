#!/usr/bin/env python3
import os
import json
import requests
from datetime import datetime, timedelta
from test import fetch_email_thread

# ─── CONFIG FROM ENV ────────────────────────────────────────────────────────────
M_TOKEN   = os.getenv("MONDAY_API_TOKEN")
BOARD_ID  = int(os.getenv("MONDAY_BOARD_ID", "0"))       # cast to int!
EMAIL_COL = os.getenv("MONDAY_EMAIL_COL")                # e.g. "lead_email"
LAST_COL  = os.getenv("MONDAY_LAST_CONTACT")              # e.g. "date_mksfxnwb"
THREAD_COL = "long_text_mkspw74e"

HEADERS = {
    "Authorization": M_TOKEN,
    "Content-Type":  "application/json",
}

# ─── GRAPHQL TEMPLATES ──────────────────────────────────────────────────────────
GET_ITEMS = f'''
query GetStaleItems($boardId: Int!) {{
  boards(ids: [$boardId]) {{
    items {{
      id
      column_values(ids: ["{EMAIL_COL}", "{THREAD_COL}", "{LAST_COL}"]) {{
        id
        text
      }}
    }}
  }}
}}
'''

UPDATE_MUTATION = '''
mutation UpdateThread($boardId: Int!, $itemId: Int!, $cols: JSON!) {
  change_multiple_column_values(
    board_id: $boardId,
    item_id: $itemId,
    column_values: $cols
  ) { id }
}
'''

def sync_threads():
    print(f"\n🔄 sync_threads started at {datetime.utcnow().isoformat()}Z")

    # 1) Fetch items
    resp = requests.post(
        "https://api.monday.com/v2",
        headers=HEADERS,
        json={
            "query":     GET_ITEMS,
            "variables": {"boardId": BOARD_ID}
        }
    )
    data = resp.json()
    if errors := data.get("errors"):
        print("❌ GraphQL errors fetching items:", errors)
        return

    items = data["data"]["boards"][0]["items"]
    cutoff = datetime.utcnow() - timedelta(days=2)

    for it in items:
        # build a map of column_id -> text
        cvs = { cv["id"]: cv["text"] or "" for cv in it["column_values"] }
        email = cvs.get(EMAIL_COL, "").strip()
        last_str = cvs.get(LAST_COL, "").strip()

        # parse last contact
        try:
            last_dt = datetime.fromisoformat(last_str.replace("Z", "+00:00"))
        except Exception:
            # if missing or unparseable, treat as stale
            last_dt = cutoff - timedelta(days=1)

        # skip if updated within 2 days
        if last_dt > cutoff:
            continue

        if not email:
            print(f"⚠️  Skipping item {it['id']} (no email)")
            continue

        stored_thread = cvs.get(THREAD_COL, "")
        print(f"🔄 Checking {email} (item {it['id']}), last update {last_dt.date()}")

        # fetch new thread
        try:
            new_thread = fetch_email_thread(email) or ""
        except Exception as e:
            print(f"❌ Error fetching thread for {email}:", e)
            continue

        # if unchanged, skip
        if new_thread.strip() == stored_thread.strip():
            print("   ↳ no changes")
            continue

        # otherwise update both thread and date
        updated_cols = {
            THREAD_COL: {"text": new_thread},
            LAST_COL:   {"date": datetime.utcnow().date().isoformat()}
        }
        vars = {
            "boardId": BOARD_ID,
            "itemId":  int(it["id"]),
            "cols":    json.dumps(updated_cols)
        }

        up = requests.post(
            "https://api.monday.com/v2",
            headers=HEADERS,
            json={"query": UPDATE_MUTATION, "variables": vars}
        )
        up.raise_for_status()
        result = up.json()
        if result.get("errors"):
            print("❌ GraphQL error updating:", result["errors"])
        else:
            print(f"✅ Updated item {it['id']}")

if __name__ == "__main__":
    sync_threads()
