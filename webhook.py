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
    print("📥 Incoming request payload:", payload)

    if payload.get("event_type") == "campaign_completed":
        campaign_id = payload.get("campaign_id")
        campaign_name = payload.get("campaign_name")
        date_str = payload.get("timestamp", "").split("T")[0]
        print(f"🚀 Handling campaign_completed: id={campaign_id}, name={campaign_name}, date={date_str}")
        # Prepare column values for the new item (customize as needed)
        column_values = {
            LAST_COL: date_str
        }
        create_item_mutation = """
        mutation ($boardId: ID!, $groupId: String!, $itemName: String!, $columnVals: JSON!) {
          create_item (
            board_id: $boardId,
            group_id: $groupId,
            item_name: $itemName,
            column_values: $columnVals
          ) {
            id
          }
        }
        """
        create_vars = {
            "boardId": str(BOARD_ID),
            "groupId": "your_group_id_here",  # <--- put the group id here
            "itemName": campaign_name or campaign_id or "Campaign Completed",
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
        print(f"✅ Created new campaign item: {new_item_id}")
        return jsonify(status="created-campaign", item=new_item_id, campaign_id=campaign_id, campaign_name=campaign_name, date=date_str), 201

    if payload.get("event_type") != "email_sent":
        return jsonify(status="ignored"), 200

    # Always create a new item with lead_email, sender email, and date
    lead_email = payload.get("lead_email")
    email_account = payload.get("email_account")
    date_str = payload.get("timestamp", "").split("T")[0]

    if lead_email and email_account and date_str:
        column_values = {
            "lead_email": {"email": payload["lead_email"], "text": payload["lead_email"]},
            "tekst__1": payload.get("firstName"),
            "tekst6__1": payload.get("lastName"),
            "lead_company": payload.get("companyName"),
            "title__1": payload.get("jobTitle"),
            "tekst_1__1": payload.get("linkedIn"),
            "date": payload.get("timestamp", ""),  # Store full timestamp (date and time)
            "email_type_mkmpw2vk": payload.get("email_account"),
            "email_status_mkmp5hf8": payload.get("event_type"),
        }
        print("About to post to Monday.com:", column_values)
        create_item_mutation = """
        mutation ($boardId: ID!, $groupId: String!, $itemName: String!, $columnVals: JSON!) {
          create_item (
            board_id: $boardId,
            group_id: $groupId,
            item_name: $itemName,
            column_values: $columnVals
          ) {
            id
          }
        }
        """
        create_vars = {
            "boardId": str(BOARD_ID),
            "groupId": "group_mknz7nc",  # <--- put the group id here
            "itemName": f"{payload.get('firstName', '')} {payload.get('lastName', '')}".strip() or lead_email,
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

    return jsonify(status="created"), 201

# ─── RUN ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5001"))
    print(f"🚀 Listening on http://0.0.0.0:{port}/webhook")
    app.run(host="0.0.0.0", port=port)
