#!/usr/bin/env python3
import os
import requests
import json
from datetime import datetime, timedelta
from test import fetch_email_thread

# ─── CONFIG FROM ENV ────────────────────────────────────────────────────────────
M_TOKEN      = os.getenv("MONDAY_API_TOKEN")
BOARD_ID     = os.getenv("MONDAY_BOARD_ID")
EMAIL_COL    = os.getenv("MONDAY_EMAIL_COL")
LAST_COL     = os.getenv("MONDAY_LAST_CONTACT")

HEADERS = {
    "Authorization": M_TOKEN,
    "Content-Type":  "application/json",
}

def get_monday_items():
    """Fetch all items from Monday.com board"""
    query = '''
    query ($boardId: ID!) {
        boards(ids: [$boardId]) {
            items {
                id
                name
                column_values {
                    id
                    value
                    text
                }
            }
        }
    }
    '''
    
    resp = requests.post(
        "https://api.monday.com/v2",
        json={"query": query, "variables": {"boardId": BOARD_ID}},
        headers=HEADERS
    )
    resp.raise_for_status()
    data = resp.json()
    
    if data.get("errors"):
        print("❌ GraphQL errors:", data["errors"])
        return []
    
    return data["data"]["boards"][0]["items"]

def get_email_from_item(item):
    """Extract email from Monday.com item"""
    for col in item["column_values"]:
        if col["id"] == EMAIL_COL:
            try:
                email_data = json.loads(col["value"])
                return email_data.get("email", "")
            except:
                return col.get("text", "")
    return ""

def get_last_contact_date(item):
    """Extract last contact date from Monday.com item"""
    for col in item["column_values"]:
        if col["id"] == LAST_COL:
            try:
                date_data = json.loads(col["value"])
                return date_data.get("date", "")
            except:
                return col.get("text", "")
    return ""

def is_older_than_days(date_str, days=2):
    """Check if date is older than specified days"""
    if not date_str:
        return False
    
    try:
        # Parse the date string (adjust format as needed)
        if "T" in date_str:
            date_obj = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        else:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        
        days_ago = datetime.now() - timedelta(days=days)
        return date_obj < days_ago
    except Exception as e:
        print(f"Error parsing date {date_str}: {e}")
        return False

def update_item_thread(item_id, new_thread):
    """Update Monday.com item with new email thread"""
    mutation = '''
    mutation ($itemId: ID!, $columnVals: JSON!) {
        change_column_value(
            item_id: $itemId,
            column_id: "long_text_mkspw74e",
            value: $columnVals
        ) { id }
    }
    '''
    
    thread_data = {"text": new_thread}
    vars = {
        "itemId": item_id,
        "columnVals": json.dumps(thread_data)
    }
    
    resp = requests.post(
        "https://api.monday.com/v2",
        json={"query": mutation, "variables": vars},
        headers=HEADERS
    )
    
    if not resp.ok:
        print(f"❌ Update failed for item {item_id}:", resp.status_code, resp.text)
        return False
    
    data = resp.json()
    if data.get("errors"):
        print(f"❌ GraphQL errors for item {item_id}:", data["errors"])
        return False
    
    print(f"✅ Updated thread for item {item_id}")
    return True

def main():
    print("🔄 Starting thread sync process...")
    
    # 1. Fetch all items from Monday.com
    print("📥 Fetching items from Monday.com...")
    items = get_monday_items()
    print(f"Found {len(items)} items")
    
    # 2. Filter items with emails and threads
    items_with_emails = []
    for item in items:
        email = get_email_from_item(item)
        if email:
            items_with_emails.append({
                "id": item["id"],
                "name": item["name"],
                "email": email,
                "last_contact": get_last_contact_date(item)
            })
    
    print(f"Found {len(items_with_emails)} items with emails")
    
    # 3. Find items older than 2 days
    old_items = []
    for item in items_with_emails:
        if is_older_than_days(item["last_contact"], days=2):
            old_items.append(item)
    
    print(f"Found {len(old_items)} items with last contact 2+ days ago")
    
    # 4. Re-fetch threads and update
    updated_count = 0
    for item in old_items:
        print(f"🔄 Processing {item['email']} (Item {item['id']})")
        
        try:
            # Fetch new thread
            new_thread = fetch_email_thread(item["email"])
            
            if new_thread and new_thread != "No emails found for this lead.":
                # Update Monday.com
                if update_item_thread(item["id"], new_thread):
                    updated_count += 1
            else:
                print(f"⚠️  No new thread data for {item['email']}")
                
        except Exception as e:
            print(f"❌ Error processing {item['email']}: {e}")
    
    print(f"✅ Sync complete! Updated {updated_count} items")

if __name__ == "__main__":
    main()
