# thread_sync.py

import os, json, requests
from datetime import datetime, timedelta
from test import fetch_email_thread

# ─── CONFIG ─────────────────────────────────────────────────────────────────────
M_TOKEN  = os.getenv("MONDAY_API_TOKEN")
BOARD_ID = int(os.getenv("MONDAY_BOARD_ID", "0"))  # cast to int!
HEADERS  = {
    "Authorization": M_TOKEN,
    "Content-Type":  "application/json",
}

# ─── GRAPHQL TEMPLATES ──────────────────────────────────────────────────────────
GET_ITEMS = """
query GetStaleItems($boardId: Int!) {
  boards(ids: [$boardId]) {
    items {
      id
      column_values(ids: ["long_text_mkspw74e","date"]) {
        id
        text
      }
    }
  }
}
"""

UPDATE_MUTATION = """
mutation UpdateThread($boardId: Int!, $itemId: Int!, $cols: JSON!) {
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

    # 1) Fetch all items
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
        cvs = { cv["id"]: cv["text"] or "" for cv in it["column_values"] }
        try:
            last = datetime.fromisoformat(cvs["date"])
        except Exception:
            # if parsing fails, treat as stale
            last = cutoff - timedelta(days=1)

        if last > cutoff:
            continue  # fresh enough

        stored_thread = cvs["long_text_mkspw74e"]
        # TODO: you need the lead_email somewhere on the item too,
        # so that you can call fetch_email_thread(email) here.
        new_thread = fetch_email_thread(/* lead_email for this item */)

        if new_thread.strip() == stored_thread.strip():
            continue  # no change

        updated_cols = {
            "long_text_mkspw74e": {"text": new_thread},
            "date":               {"date": datetime.utcnow().date().isoformat()}
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
        print(f"🔄 Updated item {it['id']}")

if __name__ == "__main__":
    sync_threads()
