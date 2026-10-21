"""Pure, fixed-snapshot demand-cycle scheduling; no inventory mutations."""
from collections import Counter, deque

SECTIONS = ("A", "B", "C", "D")


def prepare_batch(payload, sections=SECTIONS):
    """Validate dispatcher input and return immutable-in-practice scheduled jobs.

    Demand is number of parties, not number of seats. Dispatcher-supplied counts
    must match the snapshot. No global admission decisions are made here.
    """
    if not isinstance(payload, dict) or set(payload) != {"batch_id", "requests", "section_demand"}:
        raise ValueError("Expected batch_id, requests and section_demand")
    batch_id = payload["batch_id"]
    if not isinstance(batch_id, str) or not batch_id.strip() or len(batch_id) > 128:
        raise ValueError("batch_id must be a nonempty string of at most 128 characters")
    parties = payload["requests"]
    if not isinstance(parties, list) or not 1 <= len(parties) <= 100:
        raise ValueError("A fixed batch must contain 1 to 100 requests")
    ids, positions = set(), set()
    for party in parties:
        if not isinstance(party, dict) or set(party) != {
            "request_id", "section", "party_size", "global_position"
        }:
            raise ValueError("Each request needs request_id, section, party_size, global_position")
        rid = party["request_id"]
        if not isinstance(rid, str) or not rid.strip() or len(rid) > 128 or rid in ids:
            raise ValueError("request_id must be unique and contain 1 to 128 characters")
        if party["section"] not in sections:
            raise ValueError("Unsupported section (current SeatStore defaults to A/B/C)")
        if type(party["party_size"]) is not int or party["party_size"] not in range(1, 5):
            raise ValueError("party_size must be an integer from 1 to 4")
        pos = party["global_position"]
        if type(pos) is not int or pos < 1 or pos in positions:
            raise ValueError("global_position must be a unique positive integer within this batch")
        ids.add(rid)
        positions.add(pos)
    demand = payload["section_demand"]
    present = {p["section"] for p in parties}
    if not isinstance(demand, dict) or set(demand) != present:
        raise ValueError("section_demand must contain exactly the sections present in requests")
    orders, jobs = {}, []
    for section in sorted(present):
        counts = demand[section]
        actual = Counter(p["party_size"] for p in parties if p["section"] == section)
        if not isinstance(counts, dict) or set(counts) != {"1", "2", "3", "4"}:
            raise ValueError("Each section demand needs JSON keys 1, 2, 3, 4 (including zeros)")
        if any(type(counts[str(s)]) is not int or counts[str(s)] != actual[s] for s in range(1, 5)):
            raise ValueError("section_demand does not match the fixed request snapshot")
        order = sorted((s for s in range(1, 5) if actual[s]), key=lambda s: (-counts[str(s)], s))
        orders[section] = order
        groups = {s: deque(sorted((p for p in parties if p["section"] == section and p["party_size"] == s),
                                 key=lambda p: p["global_position"])) for s in order}
        priority = 0
        while any(groups.values()):
            for size in order:
                if groups[size]:
                    jobs.append({**groups[size].popleft(), "batch_id": batch_id, "priority": priority})
                    priority += 1
    return orders, jobs
