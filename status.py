#!/usr/bin/env python3
"""Check the status of an upload without uploading again.

Usage (run in the same folder as tokens.json):
    python3 status.py 'v_inbox_file~v2.7698641781580826676'
"""
import json
import sys

import requests

if len(sys.argv) < 2:
    sys.exit("Usage: python3 status.py 'PUBLISH_ID'")

with open("tokens.json") as f:
    token = json.load(f)["access_token"]

r = requests.post(
    "https://open.tiktokapis.com/v2/post/publish/status/fetch/",
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
    },
    json={"publish_id": sys.argv[1]},
    timeout=30,
)
print(json.dumps(r.json(), indent=2))