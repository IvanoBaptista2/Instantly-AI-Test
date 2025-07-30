# thread_sync.py
import os
import json
import time
import requests
from datetime import datetime, timedelta
from test import fetch_email_thread

# ─── CONFIG ──────────────────────────────────────────────────────────────────
M_TOKEN  = os.getenv("MONDAY_API_TOKEN")
BOARD_ID = os.getenv("MONDAY_BOARD_ID")
HEADERS  = {
    "Authorization": M_TOKEN,
    "Content-Type": "application/json",
}

# ─── GRAPHQL TEMPLATES ───────────────────────────────────────────────────────
GET_ITEMS = """
query ($boardId: ID!) {
  boards(ids: [$boardId]) {
    items {
      id
      column_values(ids: [
        "lead_email",          # must exist on your board
        "long_text_mkspw74e",  # your thread column
        "date"                 # your last‐synced date column
      ]) {
        id
        text
      }
    }
  }
}
"""

UPDATE_MUTATION = """
mutation ($boardId: ID!, $itemId: Int!, $cols: JSON!) {
  change_multiple_column_values(
    board_id: $boardId,
    item_id: $itemId,
    column_values: $cols
  ) {
    id
  }
}
"""

def sync_threads():
    print(f"\n🔄 sync_threads started at {datetime.utcnow().isoformat()}Z")
    # 1) fetch all items
    resp = requests.post(
        "https://api.monday.com/v2",
        headers=HEADERS,
        json={"query": GET_ITEMS, "variables": {"boardId": BOARD_ID}}
    )

    # 2) parse JSON, bail out if malformed or error
    try:
        data = resp.json()
    except ValueError:
        print("❌ Failed to parse JSON from Monday:", resp.text)
        return

    if "errors" in data:
        print("❌ GraphQL errors fetching items:", data["errors"])
        return

    boards = data.get("data", {}).get("boards")
    if not boards:
        print("❌ No boards returned:", data)
        return

    items = boards[0].get("items", [])
    cutoff = datetime.utcnow() - timedelta(days=2)

    for it in items:
        cvs = { cv["id"]: cv.get("text", "") for cv in it["column_values"] }
        item_id   = it["id"]
        last_date = cvs.get("date", "").strip()
        email     = cvs.get("lead_email", "").strip()
        stored    = cvs.get("long_text_mkspw74e", "")

        # skip if missing date or email
        if not last_date or not email:
            print(f"⚠️  Skipping item {item_id}: missing date or email")
            continue

        # skip if last_date is less than cutoff
        try:
            last = datetime.fromisoformat(last_date)
        except Exception as e:
            print(f"⚠️  Item {item_id} has bad date `{last_date}`:", e)
            continue
        if last > cutoff:
            print(f"✅  Item {item_id} synced {last_date}, still fresh")
            continue

        # 3) fetch new thread and compare
        print(f"✨  Fetching thread for {email} (item {item_id}) …")
        new_thread = fetch_email_thread(email).strip()
        if new_thread == stored.strip():
            print(f"✅  No changes for item {item_id}")
            continue

        # 4) update board
        updated_cols = {
            "long_text_mkspw74e": { "text": new_thread },
            "date":               { "date": datetime.utcnow().date().isoformat() }
        }
        vars_ = {
            "boardId": BOARD_ID,
            "itemId":  int(item_id),
            "cols":    json.dumps(updated_cols)
        }
        up = requests.post(
            "https://api.monday.com/v2",
            headers=HEADERS,
            json={"query": UPDATE_MUTATION, "variables": vars_}
        )

        if not up.ok:
            print(f"❌ Failed to update item {item_id}:", up.status_code, up.text)
        else:
            print(f"🔄 Updated item {item_id}")

if __name__ == "__main__":
    # run once immediately, then every hour
    while True:
        try:
            sync_threads()
        except Exception as e:
            print("❌ sync_threads unhandled exception:", e)
        # sleep 1h (3600s)
        time.sleep(3600)
