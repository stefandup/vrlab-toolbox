import requests
import pandas as pd
from io import StringIO
from pathlib import Path

REDCAP_URL = "https://redcap.sun.ac.za/api/"
API_TOKEN = ""
REPORT_ID = 14932

payload = {
    "token": API_TOKEN,
    "content": "report",
    "report_id": REPORT_ID,
    "format": "csv",
    "rawOrLabel": "raw",
    "rawOrLabelHeaders": "raw",
    "exportCheckboxLabel": "false",
    "returnFormat": "json",
}

response = requests.post(REDCAP_URL, data=payload)

print("Status code:", response.status_code)
print("Content type:", response.headers.get("Content-Type"))
print("Response:")
print(response.text[:2000])

response.raise_for_status()

df = pd.read_csv(StringIO(response.text))

print(df.head())
print()
print(f"Rows downloaded: {len(df)}")
print(f"Columns downloaded: {len(df.columns)}")

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = PROJECT_ROOT / "redcap_data"
OUTPUT_DIR.mkdir(exist_ok=True)

out_file = OUTPUT_DIR / "Get_all_data.csv"

df.to_csv(out_file, index=False)

print(f"Saved: {out_file}")