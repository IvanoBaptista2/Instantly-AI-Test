# webhook.py

import os
import requests
import json
from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

# ─── INSTANTLY API SETUP ───────────────────────────────────────────────────────
INSTANTLY_API_KEY = os.getenv("INSTANTLY_API_KEY")
if not INSTANTLY_API_KEY:
    raise RuntimeError("Missing INSTANTLY_API_KEY in environment")

def get_email_thread_from_instantly(lead_email, email_account):
    """
    Fetches all emails for a lead from Instantly (v2), sorted ascending,
    and returns them concatenated by thread_id and timestamp.
    """
    url = "https://api.instantly.ai/api/v2/emails"
    params = {
        "lead":       lead_email,
        "limit":      100,
        "sort_order": "asc",
    }
    headers = {
        "Authorization": f"Bearer {INSTANTLY_API_KEY}",
        "Content-Type":  "application/json",
    }

    resp = requests.get(url, headers=headers, params=params)
    # Log raw Instantly response for debugging
    app.logger.debug("Instantly /emails response [%s]: %s", resp.status_code, resp.text)
    resp.raise_for_status()

    payload = resp.json()
    # Extract email list
    emails = (payload.get("data") if isinstance(payload.get("data"), list)
              else payload.get("emails", []))
    if not emails and isinstance(payload, list):
        emails = payload

    if not emails:
        return ""  # no emails for this lead

    # Group by thread_id
    threads = {}
    for em in emails:
        tid = em.get("thread_id") or "_no_thread_"
        threads.setdefault(tid, []).append(em)

    # Build human-readable string for each thread
    sections = []
    for tid, msgs in threads.items():
        msgs.sort(key=lambda e: e.get("timestamp_email") or "")
        lines = [f"=== Thread {tid} ==="]
        for m in msgs:
            ts   = m.get("timestamp_email", "")
            frm  = m.get("from") or m.get("sender") or ""
            sub  = m.get("subject", "")
            body = (m.get("body", {}).get("text") or
                    m.get("plain_body", "")).strip()
            lines.append(f"[{ts}] {frm}: {sub}\n{body}")
        sections.append("\n\n".join(lines))

    return "\n\n---\n\n".join(sections)

# ─── CONFIG FROM ENV ────────────────────────────────────────────────────────────
M_TOKEN       = os.getenv("MONDAY_API_TOKEN")
BOARD_ID      = os.getenv("MONDAY_BOARD_ID")        # e.g. "2032211365"
EMAIL_COL     = os.getenv("MONDAY_EMAIL_COL")       # e.g. "lead_email"
LAST_COL      = os.getenv("MONDAY_LAST_CONTACT")    # e.g. "date_mksfxnwb"

HEADERS = {
    "Authorization": M_TOKEN,
    "Content-Type":  "application/json",
}

# ─── WEBHOOK ───────────────────────────────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def instantly_webhook():
    payload = request.get_json(force=True)
    app.logger.info("📥 Incoming payload: %s", payload)

    # Handle campaign_completed
    if payload.get("event_type") == "campaign_completed":
        campaign_id   = payload.get("campaign_id")
        campaign_name = payload.get("campaign_name")
        date_str      = payload.get("timestamp", "").split("T")[0]

        app.logger.info("🚀 campaign_completed: %s (%s) on %s",
                        campaign_name, campaign_id, date_str)

        column_values = { LAST_COL: date_str }
        create_item_mutation = """
            mutation ($boardId: ID!, $groupId: String!, $itemName: String!, $columnVals: JSON!) {
              create_item (
                board_id: $boardId,
                group_id: $groupId,
                item_name: $itemName,
                column_values: $columnVals
              ) { id }
            }
        """
        create_vars = {
            "boardId":   str(BOARD_ID),
            "groupId":   "your_group_id_here",
            "itemName":  campaign_name or campaign_id or "Campaign Completed",
            "columnVals": json.dumps(column_values)
        }
        resp = requests.post(
            "https://api.monday.com/v2",
            json={"query": create_item_mutation, "variables": create_vars},
            headers=HEADERS
        )
        if not resp.ok:
            app.logger.error("❌ Monday create_item failed: %s %s", resp.status_code, resp.text)
            resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            return jsonify(status="create-error", errors=data["errors"]), 500

        new_item_id = data["data"]["create_item"]["id"]
        return jsonify(status="created-campaign", item=new_item_id), 201

    # Only handle email_sent
    if payload.get("event_type") != "email_sent":
        return jsonify(status="ignored"), 200

    lead_email    = payload.get("lead_email")
    email_account = payload.get("email_account")
    timestamp     = payload.get("timestamp", "")

    # Parse date & time
    date_part, time_part = "", ""
    if timestamp:
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            date_part = dt.strftime("%Y-%m-%d")
            time_part = dt.strftime("%H:%M:%S")
        except Exception as e:
            app.logger.warning("Timestamp parsing error: %s", e)

    # Fetch email thread from Instantly
    email_thread = get_email_thread_from_instantly(lead_email, email_account)
    app.logger.info("📨 Fetched email thread (%d chars)", len(email_thread))

    # 1) Find existing item by lead_email
    find_query = """
        query ($boardId: Int!, $columnId: String!, $columnValue: String!) {
          items_by_column_values(
            board_id: $boardId,
            column_id: $columnId,
            column_value: $columnValue
          ) {
            id
            column_values { id, value }
          }
        }
    """
    find_vars = {
        "boardId": int(BOARD_ID),
        "columnId": EMAIL_COL,
        "columnValue": lead_email
    }
    find_resp = requests.post(
        "https://api.monday.com/v2",
        headers=HEADERS,
        json={"query": find_query, "variables": find_vars}
    )
    app.logger.debug("Monday find_item response [%s]: %s", find_resp.status_code, find_resp.text)
    try:
        find_resp.raise_for_status()
    except Exception:
        return jsonify(status="monday-find-error", detail=find_resp.text), 500

    items = find_resp.json().get("data", {}).get("items_by_column_values", [])

    # Column IDs
    LONG_TEXT_COL    = "long_text_mkspw74e"
    LAST_CONTACTED_COL = "date"

    if items:
        # Update existing item
        item = items[0]
        item_id = int(item["id"])

        # Extract current thread
        current_thread = ""
        for cv in item["column_values"]:
            if cv["id"] == LONG_TEXT_COL:
                try:
                    val = json.loads(cv["value"]) if cv["value"] else {}
                    current_thread = val.get("text", "")
                except Exception:
                    current_thread = cv["value"] or ""

        # Append new thread
        new_thread = (current_thread + "\n---\n" if current_thread else "") + email_thread

        update_mutation = f"""
            mutation ($itemId: Int!, $columnVals: JSON!) {{
              change_column_values(
                item_id: $itemId,
                board_id: {BOARD_ID},
                column_values: $columnVals
              ) {{ id }}
            }}
        """
        update_column_values = {
            LONG_TEXT_COL: new_thread,
            LAST_CONTACTED_COL: {"date": date_part, "time": time_part}
        }
        update_vars = {"itemId": item_id, "columnVals": json.dumps(update_column_values)}

        update_resp = requests.post(
            "https://api.monday.com/v2",
            headers=HEADERS,
            json={"query": update_mutation, "variables": update_vars}
        )
        app.logger.debug("Monday update_item response [%s]: %s", update_resp.status_code, update_resp.text)
        try:
            update_resp.raise_for_status()
        except Exception:
            return jsonify(status="update-error", detail=update_resp.text), 500

        return jsonify(status="updated", item=item_id), 200

    else:
        # Create new item
        column_values = {
            EMAIL_COL:             {"email": lead_email, "text": lead_email},
            "tekst__1":            payload.get("firstName"),
            "tekst6__1":           payload.get("lastName"),
            "lead_company":        payload.get("companyName"),
            "title__1":            payload.get("jobTitle"),
            "tekst_1__1":          payload.get("linkedIn"),
            "date":                {"date": date_part, "time": time_part},
            "email_type_mkmpw2vk": payload.get("email_account"),
            "email_status_mkmp5hf8":payload.get("event_type"),
            LONG_TEXT_COL:         email_thread
        }
        app.logger.info("Creating new item with columns: %s", column_values)

        create_mutation = """
            mutation ($boardId: ID!, $groupId: String!, $itemName: String!, $columnVals: JSON!) {
              create_item (
                board_id: $boardId,
                group_id: $groupId,
                item_name: $itemName,
                column_values: $columnVals
              ) { id }
            }
        """
        create_vars = {
            "boardId":   str(BOARD_ID),
            "groupId":   "group_mknz7nc",
            "itemName":  f"{payload.get('firstName','')} {payload.get('lastName','')}".strip() or lead_email,
            "columnVals": json.dumps(column_values)
        }

        create_resp = requests.post(
            "https://api.monday.com/v2",
            headers=HEADERS,
            json={"query": create_mutation, "variables": create_vars}
        )
        app.logger.debug("Monday create_item response [%s]: %s", create_resp.status_code, create_resp.text)
        try:
            create_resp.raise_for_status()
        except Exception:
            return jsonify(status="create-error", detail=create_resp.text), 500

        new_item_id = create_resp.json()["data"]["create_item"]["id"]
        return jsonify(status="created", item=new_item_id), 201

    return jsonify(status="ignored"), 200

# ─── RUN ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5001"))
    print(f"🚀 Listening on http://0.0.0.0:{port}/webhook")
    app.run(host="0.0.0.0", port=port)
