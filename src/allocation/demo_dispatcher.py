"""Dummy module-4 handoff, not a replacement global-admission dispatcher."""
import argparse
import json
from collections import Counter
import requests


def sample_batch(batch_id="demo-1", second=False):
    # First cycle 4,2,3,1; second cycle 3,4,1,2 (last two tie).
    sizes = ([4] * 4 + [2] * 3 + [3] * 2 + [1] if not second
             else [3] * 4 + [4] * 3 + [1] + [2])
    parties = [{"request_id": f"{batch_id}-{i}", "section": "A", "party_size": size,
                "global_position": i + (101 if second else 1)} for i, size in enumerate(sizes)]
    parties += [{"request_id": f"{batch_id}-B", "section": "B", "party_size": 1,
                 "global_position": 200 if second else 100}]
    demand = {}
    for section in ("A", "B"):
        counts = Counter(p["party_size"] for p in parties if p["section"] == section)
        demand[section] = {str(size): counts[size] for size in range(1, 5)}
    return {"batch_id": batch_id, "requests": parties, "section_demand": demand}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-id", default="demo-1")
    parser.add_argument("--second", action="store_true")
    parser.add_argument("--send", action="store_true", help="Without this flag, only print JSON")
    parser.add_argument("--url", default="http://127.0.0.1:5002")
    args = parser.parse_args()
    payload = sample_batch(args.batch_id, args.second)
    if args.send:
        response = requests.post(args.url.rstrip("/") + "/batches", json=payload, timeout=10)
        print(response.status_code, response.text)
        response.raise_for_status()
    else:
        print(json.dumps(payload, indent=2))
