import requests

API_KEY  = "ODE5YjQ5YTAtZGI4OC00NTlkLWJlMDctODExZjBlMDBjMzhhOmdXeFZMaXhad0ZIeA=="
BASE_URL = "https://api.instantly.ai/api/v2"  # include the /api here

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type":  "application/json",
}

# Correct endpoint path:
resp = requests.post(
    f"{BASE_URL}/leads/list",
    headers=headers,
    json={"limit": 100}
)
resp.raise_for_status()
data = resp.json()

for lead in data.get("items", []):
    email = lead.get("email")
    last  = lead.get("timestamp_last_contact")  # the lead’s “last contacted” timestamp
    print(f"{email} – last contacted at {last}")
