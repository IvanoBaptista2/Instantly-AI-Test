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
    app.logger.debug("Instantly /emails response [%s]: %s", resp.status_code, resp.text)
    resp.raise_for_status()

    payload = resp.json()
    emails = (payload.get("data") if isinstance(payload.get("data"), list)
              else payload.get("emails", []))
    if not emails and isinstance(payload, list):
        emails = payload

    if not emails:
        return ""  # no emails for this lead

    threads = {}
    for em in emails:
        tid = em.get("thread_id") or "_no_thread_"
        threads.setdefault(tid, []).append(em)

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

    if payload.get("event_type") == "campaign_completed":
        campaign_id   = payload.get("campaign_id")
        campaign_name = payload.get("campaign_name")
        date_str      = payload.get("timestamp", "").split("T")[0]
        column_values = { LAST_COL: date_str }
        mutation = """
            mutation ($boardId: ID!, $groupId: String!, $itemName: String!, $columnVals: JSON!) {
              create_item (
                board_id: $boardId,
                group_id: $groupId,
                item_name: $itemName,
                column_values: $columnVals
              ) { id }
            }
        """
        vars = {
            "boardId":   str(BOARD_ID),
            "groupId":   "your_group_id_here",
            "itemName":  campaign_name or campaign_id or "Campaign Completed",
            "columnVals": json.dumps(column_values)
        }
        r = requests.post(
            "https://api.monday.com/v2",
            json={"query": mutation, "variables": vars},
            headers=HEADERS
        )
        r.raise_for_status()
        resp = r.json()
        if resp.get("errors"): return jsonify(status="create-error", errors=resp["errors"]), 500
        return jsonify(status="created-campaign", item=resp["data"]["create_item"]["id"]), 201

    if payload.get("event_type") != "email_sent":
        return jsonify(status="ignored"), 200

    lead_email    = payload.get("lead_email")
    email_account = payload.get("email_account")
    timestamp     = payload.get("timestamp", "")
    date_part, time_part = "", ""
    if timestamp:
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            date_part = dt.strftime("%Y-%m-%d")
            time_part = dt.strftime("%H:%M:%S")
        except Exception as e:
            app.logger.warning("Timestamp parsing error: %s", e)

    email_thread = get_email_thread_from_instantly(lead_email, email_account)
    app.logger.info("📨 Fetched email thread (%d chars)", len(email_thread))

    # ─── 1) Find existing item by lead_email ────────────────────────────────────
    find_query = """
      query ($boardId: Int!, $emailCol: String!, $emailVal: String!) {
        items_page_by_column_values(
          board_id: $boardId,
          columns: [{ column_id: $emailCol, column_values: [$emailVal] }]
        ) {
          items {
            id
            column_values { id, value }
          }
        }
      }
    """
    find_vars = {
        "boardId":  int(BOARD_ID),
        "emailCol": EMAIL_COL,
        "emailVal": lead_email
    }
    find_resp = requests.post(
        "https://api.monday.com/v2",
        headers=HEADERS,
        json={"query": find_query, "variables": find_vars}
    )
    find_resp.raise_for_status()
    items = find_resp.json().get("data", {}) \
                   .get("items_page_by_column_values", {}) \
                   .get("items", [])

    LONG_TEXT_COL     = "long_text_mkspw74e"
    LAST_CONTACTED_COL = "date"

    if items:
        item = items[0]
        item_id = int(item["id"])
        current_thread = ""
        for cv in item["column_values"]:
            if cv["id"] == LONG_TEXT_COL:
                try:
                    val = json.loads(cv["value"]) if cv["value"] else {}
                    current_thread = val.get("text", "")
                except:
                    current_thread = cv["value"] or ""
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
        update_vals = {
            LONG_TEXT_COL: {"text": new_thread},
            LAST_CONTACTED_COL: {"date": date_part, "time": time_part}
        }
        update_vars = {"itemId": item_id, "columnVals": json.dumps(update_vals)}
        upd = requests.post(
            "https://api.monday.com/v2",
            headers=HEADERS,
            json={"query": update_mutation, "variables": update_vars}
        )
        upd.raise_for_status()
        return jsonify(status="updated", item=item_id), 200
    else:
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
            LONG_TEXT_COL:         {"text": email_thread}
        }
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
        create_resp.raise_for_status()
        new_item_id = create_resp.json()["data"]["create_item"]["id"]
        return jsonify(status="created", item=new_item_id), 201

    return jsonify(status="ignored"), 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5001"))
    print(f"🚀 Listening on http://0.0.0.0:{port}/webhook")
    app.run(host="0.0.0.0", port=port)
