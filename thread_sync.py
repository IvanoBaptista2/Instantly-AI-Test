
# thread_sync.py
#!/usr/bin/env python3
import os
import json
import requests
from datetime import datetime, timedelta
from test import fetch_email_thread

M_TOKEN  = os.getenv("MONDAY_API_TOKEN")
BOARD_ID = os.getenv("MONDAY_BOARD_ID")
HEADERS  = {"Authorization": M_TOKEN, "Content-Type": "application/json"}

GET_ITEMS = '''
query ($boardId: ID!) {
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
'''

UPDATE_MUTATION = '''
mutation ($boardId: ID!, $itemId: Int!, $cols: JSON!) {
  change_multiple_column_values(
    board_id: $boardId,
    item_id: $itemId,
    column_values: $cols
  ) { id }
}
'''

def sync_threads():
    resp = requests.post(
        "https://api.monday.com/v2",
        headers=HEADERS,
        json={"query": GET_ITEMS, "variables": {"boardId": BOARD_ID}}
    )
    data = resp.json()
    items = data["data"]["boards"][0]["items"]

    cutoff = datetime.utcnow() - timedelta(days=2)
    for it in items:
        cvs = {cv["id"]: cv["text"] for cv in it["column_values"]}
        try:
            last_dt = datetime.fromisoformat(cvs.get("date"))
        except:
            continue
        if last_dt > cutoff:
            continue

        stored = cvs.get("long_text_mkspw74e", "")
        lead_email = cvs.get("lead_email", "")
        new = fetch_email_thread(lead_email)
        if new.strip() == stored.strip():
            continue

        updated = {
          "long_text_mkspw74e": {"text": new},
          "date":              {"date": datetime.utcnow().date().isoformat()}
        }
        vars = {
          "boardId": BOARD_ID,
          "itemId":  int(it["id"]),
          "cols":    json.dumps(updated)
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
