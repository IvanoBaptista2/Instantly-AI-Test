# webhook.py

import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ─── CONFIG FROM ENV ────────────────────────────────────────────────────────────
M_TOKEN      = os.getenv("MONDAY_API_TOKEN")
BOARD_ID     = os.getenv("MONDAY_BOARD_ID")         # e.g. "2032211365"
EMAIL_COL    = os.getenv("MONDAY_EMAIL_COL")        # e.g. "name"
LAST_COL     = os.getenv("MONDAY_LAST_CONTACT")     # e.g. "date_mksfxnwb"

HEADERS = {
    "Authorization": M_TOKEN,
    "Content-Type":  "application/json",
}

# ─── WEBHOOK ───────────────────────────────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def instantly_webhook():
    payload = request.get_json(force=True)

    if payload.get("event_type") != "email.sent":
        return jsonify(status="ignored"), 200

    lead_email = payload["lead_email"]
    date_str   = payload["timestamp"].split("T")[0]

    # ─── 1) FETCH ALL ITEMS + THEIR EMAIL COLUMN ────────────────────────────────
    query = """
    query($boardIds: [ID!]!, $colIds: [String!]!) {
      boards(ids: $boardIds) {
        items {
          id
          column_values(ids: $colIds) {
            text
          }
        }
      }
    }
    """
    vars_ = {
      "boardIds": [BOARD_ID],
      "colIds":   [EMAIL_COL]
    }
    resp = requests.post(
      "https://api.monday.com/v2",
      json={"query": query, "variables": vars_},
      headers=HEADERS
    )
    if not resp.ok:
        print("❌ Monday items lookup failed:", resp.status_code, resp.text)
        resp.raise_for_status()

    items = resp.json()["data"]["boards"][0]["items"]
    match = next((it for it in items
                  if it["column_values"][0]["text"] == lead_email),
                 None)
    if not match:
        return jsonify(status="no-item"), 200

    # ─── 2) UPDATE THAT ROW’S “Last Contact” COLUMN ──────────────────────────────
    mutation = """
    mutation($boardId: ID!, $itemId: Int!, $colId: String!, $value: JSON!) {
      change_simple_column_value(
        board_id:  $boardId,
        item_id:   $itemId,
        column_id: $colId,
        value:     $value
      ) {
        id
      }
    }
    """
    vars2 = {
      "boardId": BOARD_ID,
      "itemId":  int(match["id"]),
      "colId":   LAST_COL,
      "value":   date_str
    }
    upd = requests.post(
      "https://api.monday.com/v2",
      json={"query": mutation, "variables": vars2},
      headers=HEADERS
    )
    if not upd.ok:
        print("❌ Monday update failed:", upd.status_code, upd.text)
        upd.raise_for_status()

    return jsonify(status="updated", item=match["id"], date=date_str), 200

# ─── RUN ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5001"))
    print(f"🚀 Listening on http://0.0.0.0:{port}/webhook")
    app.run(host="0.0.0.0", port=port)
