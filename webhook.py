# webhook.py

import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Monday.com settings from environment
M_TOKEN       = os.getenv("MONDAY_API_TOKEN")
BOARD_ID      = os.getenv("MONDAY_BOARD_ID")       # as string, e.g. "2032211365"
EMAIL_COL     = os.getenv("MONDAY_EMAIL_COL")      # e.g. "name"
LAST_COL      = os.getenv("MONDAY_LAST_CONTACT")   # e.g. "date_mksfxnwb"

headers = {
    "Authorization": M_TOKEN,
    "Content-Type":  "application/json",
}

@app.route("/webhook", methods=["POST"])
def instantly_webhook():
    payload = request.get_json()
    if payload.get("event_type") != "email.sent":
        return jsonify(status="ignored"), 200

    email = payload["lead_email"]
    date  = payload["timestamp"].split("T")[0]

    # 1) lookup item by email
    query_items = """
    query ($boardIds: [ID!]!, $colIds: [String!]!) {
      boards(ids: $boardIds) {
        items {
          id
          column_values(ids: $colIds) { text }
        }
      }
    }
    """
    vars_items = {
      "boardIds": [BOARD_ID],
      "colIds":   [EMAIL_COL]
    }

    r = requests.post(
        "https://api.monday.com/v2",
        json={"query": query_items, "variables": vars_items},
        headers=headers
    )
    if not r.ok:
        print("❌ Monday items lookup failed:", r.status_code, r.text)
        r.raise_for_status()

    items = r.json()["data"]["boards"][0]["items"]
    item = next((i for i in items
                 if i["column_values"][0]["text"] == email), None)
    if not item:
        return jsonify(status="no-item"), 200

    # 2) update Last Contacted
    mutation = """
    mutation ($boardId: ID!, $itemId: Int!, $colId: String!, $val: JSON!) {
      change_simple_column_value(
        board_id: $boardId,
        item_id:  $itemId,
        column_id: $colId,
        value:    $val
      ) { id }
    }
    """
    vars_mut = {
      "boardId": BOARD_ID,
      "itemId":  int(item["id"]),
      "colId":   LAST_COL,
      "val":     date
    }

    u = requests.post(
        "https://api.monday.com/v2",
        json={"query": mutation, "variables": vars_mut},
        headers=headers
    )
    if not u.ok:
        print("❌ Monday update failed:", u.status_code, u.text)
        u.raise_for_status()

    return jsonify(status="updated", item=item["id"], date=date), 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    print(f"🚀 Listening on http://0.0.0.0:{port}/webhook")
    app.run(host="0.0.0.0", port=port)
