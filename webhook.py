# webhook.py

import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Instantly webhook auth
INSTANTLY_KEY = os.getenv("INSTANTLY_API_KEY")

# Monday.com settings
M_TOKEN       = os.getenv("MONDAY_API_TOKEN")
BOARD_ID      = int(os.getenv("MONDAY_BOARD_ID", "0"))
EMAIL_COL     = os.getenv("MONDAY_EMAIL_COL")       # e.g. "Lead"
LAST_COL      = os.getenv("MONDAY_LAST_CONTACT")    # e.g. "Last Contact"

headers = {
    "Authorization": M_TOKEN,
    "Content-Type":  "application/json",
}

def verify_inst_key(req):
    return req.headers.get("Authorization") == f"Bearer {INSTANTLY_KEY}"

@app.route("/webhook", methods=["POST"])
def instantly_webhook():
    if not verify_inst_key(request):
        return "Unauthorized", 401

    payload = request.get_json()
    if payload.get("event_type") != "email.sent":
        return jsonify(status="ignored"), 200

    email = payload["lead_email"]
    date  = payload["timestamp"].split("T")[0]

    # 1) lookup item by email
    query = """
    query ($board: Int!, $col: String!) {
      boards(ids: [$board]) {
        items {
          id
          column_values(ids: [$col]) { text }
        }
      }
    }
    """
    vars = {"board": BOARD_ID, "col": EMAIL_COL}
    r = requests.post(
        "https://api.monday.com/v2",
        json={"query": query, "variables": vars},
        headers=headers
    )
    r.raise_for_status()
    items = r.json()["data"]["boards"][0]["items"]
    item = next((i for i in items if i["column_values"][0]["text"] == email), None)
    if not item:
        return jsonify(status="no-item"), 200

    # 2) update Last Contacted
    mutation = f"""
    mutation ($item: Int!, $col: String!, $val: JSON!) {{
      change_simple_column_value(
        board_id: {BOARD_ID},
        item_id: $item,
        column_id: $col,
        value: $val
      ) {{ id }}
    }}
    """
    vars = {"item": int(item["id"]), "col": LAST_COL, "val": date}
    u = requests.post(
        "https://api.monday.com/v2",
        json={"query": mutation, "variables": vars},
        headers=headers
    )
    u.raise_for_status()

    return jsonify(status="updated", item=item["id"], date=date), 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    print(f"🚀 Listening on http://0.0.0.0:{port}/webhook")
    app.run(host="0.0.0.0", port=port)
