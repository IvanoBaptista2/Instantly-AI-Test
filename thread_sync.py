#!/usr/bin/env python3
import os
import json
import requests
from datetime import datetime, timedelta
from test import fetch_email_thread

# ─── CONFIG FROM ENV ────────────────────────────────────────────────────────────
M_TOKEN    = os.getenv("MONDAY_API_TOKEN")
BOARD_ID   = os.getenv("MONDAY_BOARD_ID")    # keep as string so it maps to GraphQL ID!
EMAIL_COL  = os.getenv("MONDAY_EMAIL_COL")   # e.g. "lead_email"
LAST_COL   = os.getenv("MONDAY_LAST_CONTACT")# e.g. "date_mkspx1234"
THREAD_COL = "long_text_mkspw74e"            # hard‑coded column id for your thread

HEADERS = {
    "Authorization": M_TOKEN,
    "Content-Type":  "application/json",
}

# ─── GRAPHQL QUERIES ────────────────────────────────────────────────────────────
GET_ITEMS = '''
query GetStaleItems($boardId: ID!) {
  board(id: $boardId) {
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
mutation UpdateThread($boardId: ID!, $itemId: Int!, $cols: JSON!) {
  change_multiple_column_values(
    board_id: $boardId,
    item_id: $itemId,
    column_values: $cols
  ) {
    id
  }
}
'''

def sync_threads():
    print(f"\n🔄 sync_threads started at {datetime.utcnow().isoformat()}Z")

    # 1) fetch all items
    resp = requests.post(
        "https://api.monday.com/v2",
        headers=HEADERS,
        json={"query": GET_ITEMS, "variables": {"boardId": BOARD_ID}}
    )
    data = resp.json()
    if data.get("errors"):
        print("❌ GraphQL errors fetching items:", data["errors"])
        return

    items = data["data"]["board"]["items"]
    cutoff = datetime.utcnow() - timedelta(days=2)

    for it in items:
        # map column_id → (value,text)
        cvs = { cv["id"]: {"value": cv["value"], "text": cv["text"] or ""} for cv in it["column_values"] }
        email = ""
        # extract email from JSON value if possible
        if cvs.get(EMAIL_COL, {}).get("value"):
            try:
                email = json.loads(cvs[EMAIL_COL]["value"]).get("email","")
            except:
                email = cvs[EMAIL_COL]["text"]
        else:
            email = cvs[EMAIL_COL]["text"]

        last_str = cvs.get(LAST_COL,{}).get("text","") or ""
        try:
            last_dt = datetime.fromisoformat(last_str.replace("Z","+00:00"))
        except:
            # treat missing/unparseable as stale
            last_dt = cutoff - timedelta(days=1)

        # skip if within 2 days
        if last_dt > cutoff:
            continue

        if not email:
            print(f"⚠️  item {it['id']} has no email, skipping")
            continue

        stored = cvs.get(THREAD_COL,{}).get("text","")
        print(f"🔄 refetching {email} (item {it['id']}), last update {last_dt.date()}")

        try:
            new_thread = fetch_email_thread(email) or ""
        except Exception as e:
            print(f"❌ failed to fetch thread for {email}:", e)
            continue

        if new_thread.strip() == stored.strip():
            print("   ↳ no changes")
            continue

        # update both thread + date
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
