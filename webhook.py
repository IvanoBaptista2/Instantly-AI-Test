# webhook.py
#!/usr/bin/env python3
import os
import requests
import json
from flask import Flask, request, jsonify
from datetime import datetime
from test import fetch_email_thread

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

    # Handle campaign_completed events
    if payload.get("event_type") == "campaign_completed":
        campaign_id   = payload.get("campaign_id")
        campaign_name = payload.get("campaign_name")
        date_str      = payload.get("timestamp", "").split("T")[0]
        print(f"🚀 Handling campaign_completed: id={campaign_id}, name={campaign_name}, date={date_str}")

        column_values = { LAST_COL: date_str }
        mutation = '''
        mutation ($boardId: ID!, $groupId: String!, $itemName: String!, $columnVals: JSON!) {
          create_item (
            board_id: $boardId,
            group_id: $groupId,
            item_name: $itemName,
            column_values: $columnVals
          ) { id }
        }
        '''
        vars = {
            "boardId":    str(BOARD_ID),
            "groupId":    os.getenv("MONDAY_CAMPAIGN_GROUP", "") ,  # configure your group
            "itemName":   campaign_name or campaign_id or "Campaign Completed",
            "columnVals": json.dumps(column_values)
        }
        resp = requests.post(
            "https://api.monday.com/v2",
            json={"query": mutation, "variables": vars},
            headers=HEADERS
        )
        if not resp.ok:
            print("❌ Monday create_item failed:", resp.status_code, resp.text)
            resp.raise_for_status()
        data = resp.json()
        if data.get("errors"):  # GraphQL errors
            print("❌ GraphQL errors:", data["errors"])
            return jsonify(status="create-error", errors=data["errors"]), 500

        new_id = data["data"]["create_item"]["id"]
        print(f"✅ Created campaign item {new_id}")
        return jsonify(status="created-campaign", item=new_id,
                       campaign_id=campaign_id, campaign_name=campaign_name,
                       date=date_str), 201

    # Only proceed for email_sent events
    if payload.get("event_type") != "email_sent":
        return jsonify(status="ignored"), 200

    lead_email   = payload.get("lead_email")
    email_account= payload.get("email_account")
    timestamp    = payload.get("timestamp", "")
    date_part, time_part = "", ""
    if timestamp:
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z","+00:00"))
            date_part = dt.strftime("%Y-%m-%d")
            time_part = dt.strftime("%H:%M:%S")
        except Exception as e:
            print("Timestamp parse error:", e)

    if lead_email and email_account and date_part:
        # fetch conversation
        thread = fetch_email_thread(lead_email)

        column_values = {
            EMAIL_COL:       {"email": lead_email, "text": lead_email},
            "tekst__1":     payload.get("firstName"),
            "tekst6__1":    payload.get("lastName"),
            "lead_company": payload.get("companyName"),
            "title__1":     payload.get("jobTitle"),
            "tekst_1__1":   payload.get("linkedIn"),
            "date":         {"date": date_part, "time": time_part},
            "email_type_mkmpw2vk": payload.get("email_account"),
            "email_status_mkmp5hf8":payload.get("event_type"),
            "long_text_mkspw74e":    {"text": thread}
        }
        print("Posting to Monday:", json.dumps(column_values, indent=2))

        mutation = '''
        mutation ($boardId: ID!, $groupId: String!, $itemName: String!, $columnVals: JSON!) {
          create_item(
            board_id: $boardId,
            group_id: $groupId,
            item_name: $itemName,
            column_values: $columnVals
          ) { id }
        }
        '''
        vars = {
            "boardId":    str(BOARD_ID),
            "groupId":    os.getenv("MONDAY_EMAIL_GROUP", ""),
            "itemName":   f"{payload.get('firstName','')} {payload.get('lastName','')}.strip()" or lead_email,
            "columnVals": json.dumps(column_values)
        }
        resp = requests.post(
            "https://api.monday.com/v2",
            json={"query": mutation, "variables": vars},
            headers=HEADERS
        )
        if not resp.ok:
            print("❌ create_item failed:", resp.status_code, resp.text)
            resp.raise_for_status()
        data = resp.json()
        if data.get("errors"):
            print("❌ GraphQL errors:", data["errors"])
            return jsonify(status="create-error", errors=data["errors"]), 500

        new_id = data["data"]["create_item"]["id"]
        print(f"✅ Created email_sent item {new_id}")
        return jsonify(status="created", item=new_id, email=lead_email,
                       date=date_part), 201

    return jsonify(status="no-action"), 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5001"))
    print(f"🚀 Serving on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port)

