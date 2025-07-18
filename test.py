import requests

API_KEY  = "ODE5YjQ5YTAtZGI4OC00NTlkLWJlMDctODExZjBlMDBjMzhhOmdXeFZMaXhad0ZIeA=="
BASE_URL = "https://api.instantly.ai/api/v2"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type":  "application/json",
}

def fetch_email_thread(lead_email):
    print(f"\n--- Fetching email thread for: {lead_email} ---")
    params = {
        "lead": lead_email,
        "limit": 100,
        "sort_order": "asc",
    }
    resp = requests.get(
        f"{BASE_URL}/emails",
        headers=headers,
        params=params
    )
    resp.raise_for_status()
    payload = resp.json()
    emails = []
    if "items" in payload and isinstance(payload["items"], list):
        emails = payload["items"]
    elif "data" in payload and isinstance(payload["data"], list):
        emails = payload["data"]
    elif "emails" in payload and isinstance(payload["emails"], list):
        emails = payload["emails"]

    if not emails:
        print(f"No emails found for {lead_email}")
        return "No emails found for this lead."

    # Group by thread_id
    threads = {}
    for em in emails:
        tid = em.get("thread_id") or "_no_thread_"
        threads.setdefault(tid, []).append(em)

    # Build the email thread as a string
    thread_content = []
    
    # Print each thread
    for tid, msgs in threads.items():
        print(f"\n=== Thread {tid} ===")
        thread_content.append(f"=== Thread {tid} ===")
        
        msgs.sort(key=lambda e: e.get("timestamp_email") or "")
        for m in msgs:
            ts   = m.get("timestamp_email", "")
            frm  = m.get("from") or m.get("sender") or m.get("from_address_email") or ""
            sub  = m.get("subject", "")
            body = (
                m.get("body", {}).get("text")
                or m.get("plain_body", "")
                or m.get("body", {}).get("html", "")
            ).strip()
            
            # Print to console
            print(f"[{ts}] {frm}: {sub}\n{body}\n")
            
            # Add to thread content
            thread_content.append(f"[{ts}] {frm}: {sub}")
            thread_content.append(body)
            thread_content.append("")  # Empty line for spacing

    # Return the formatted thread as a string
    return "\n".join(thread_content)

if __name__ == "__main__":
    # 1. List all leads
    print("All leads:")

    # 2. Fetch and print email thread for a specific lead
    print("\n\nFetching email thread for vicky.wragg@twinings.com:")
    fetch_email_thread("jessica@hightechburrito.com")