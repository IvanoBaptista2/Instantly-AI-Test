# webhook.py

import os
import requests
import json
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
    query($boardId: ID!, $columnId: String!) {
      boards(ids: [$boardId]) {
        items_page {
          items {
            id
            column_values(ids: [$columnId]) {
              id
              text
            }
          }
        }
      }
    }
    """
    vars_ = {
      "boardId": BOARD_ID,
      "columnId": EMAIL_COL
    }
    resp = requests.post(
      "https://api.monday.com/v2",
      json={"query": query, "variables": vars_},
      headers=HEADERS
    )
    if not resp.ok:
        print("❌ Monday items lookup failed:", resp.status_code, resp.text)
        print("🔍 Query variables:", vars_)
        resp.raise_for_status()

    response_data = resp.json()
    print("✅ Monday API response:", response_data)
    
    if "errors" in response_data:
        print("❌ GraphQL errors:", response_data["errors"])
        return jsonify(status="graphql-error", errors=response_data["errors"]), 500

    items = response_data["data"]["boards"][0]["items_page"]["items"]
    print(f"📋 Found {len(items)} items in board")
    
    for it in items:
        print(f"Item ID: {it['id']}, column_values: {it['column_values']}")

    match = next(
        (
            it for it in items
            if it["column_values"] and it["column_values"][0]["text"] == lead_email
        ),
        None
    )
    if not match:
        print(f"❌ No item found with email: {lead_email}, creating new item.")
        # Prepare column values for the new item
        column_values = {
            EMAIL_COL: {"email": lead_email, "text": lead_email},
            LAST_COL: date_str
        }
        create_item_mutation = """
        mutation ($boardId: ID!, $itemName: String!, $columnVals: JSON!) {
          create_item (
            board_id: $boardId,
            item_name: $itemName,
            column_values: $columnVals
          ) {
            id
          }
        }
        """
        create_vars = {
            "boardId": str(BOARD_ID),
            "itemName": lead_email,
            "columnVals": json.dumps(column_values)
        }
        create_resp = requests.post(
            "https://api.monday.com/v2",
            json={"query": create_item_mutation, "variables": create_vars},
            headers=HEADERS
        )
        if not create_resp.ok:
            print("❌ Monday create_item failed:", create_resp.status_code, create_resp.text)
            print("🔍 Create item variables:", create_vars)
            create_resp.raise_for_status()
        create_data = create_resp.json()
        print("✅ Monday create_item response:", create_data)
        if "errors" in create_data:
            print("❌ GraphQL create_item errors:", create_data["errors"])
            return jsonify(status="create-error", errors=create_data["errors"]), 500
        new_item_id = create_data["data"]["create_item"]["id"]
        print(f"✅ Created new item: {new_item_id}")
        return jsonify(status="created", item=new_item_id, email=lead_email, date=date_str), 201

    print(f"✅ Found matching item: {match['id']}")

    # ─── 2) UPDATE THAT ROW'S "Last Contact" COLUMN ──────────────────────────────
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
        print("🔍 Mutation variables:", vars2)
        upd.raise_for_status()

    update_response = upd.json()
    print("✅ Monday update response:", update_response)
    
    if "errors" in update_response:
        print("❌ GraphQL update errors:", update_response["errors"])
        return jsonify(status="update-error", errors=update_response["errors"]), 500

    return jsonify(status="updated", item=match["id"], date=date_str), 200

# ─── RUN ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5001"))
    print(f"🚀 Listening on http://0.0.0.0:{port}/webhook")
    app.run(host="0.0.0.0", port=port)
