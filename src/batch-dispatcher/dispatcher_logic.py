"""Part 4: fixed batches and counts/requests grouped by section and party size.

No demand ranking or allocator interaction in this module.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

SECTIONS = ("A", "B", "C", "D")
PARTY_SIZES = (1, 2, 3, 4)


@dataclass(frozen=True)
class QueueRequest:
    request_id: str
    global_position: int
    section: str
    party_size: int


@dataclass(frozen=True)
class BatchedRequest(QueueRequest):
    batch_id: str


def parse_waiting_room_queue(data: dict) -> list[QueueRequest]:
    """Read Part 2's GET /queue, using its queue_number naming convention."""
    if not isinstance(data, dict) or not isinstance(data.get("requests"), list):
        raise ValueError("Invalid waiting-room /queue response")
    if data.get("sale_state") != "sale_started":
        raise ValueError("Sale has not started")

    items = []
    for entry in data["requests"]:
        if not isinstance(entry, dict):
            raise ValueError("Invalid waiting-room request record")
        if entry.get("status") != "QUEUED":
            continue
        rid = entry.get("request_id")
        pos = entry.get("queue_number")
        section = entry.get("section")
        size = entry.get("party_size")
        if (not isinstance(rid, str) or not rid or
                type(pos) is not int or pos < 1 or
                section not in SECTIONS or type(size) is not int or
                size not in PARTY_SIZES):
            raise ValueError("Invalid queued request received from waiting room")
        items.append(QueueRequest(rid, pos, section, size))

    if len({r.request_id for r in items}) != len(items):
        raise ValueError("Duplicate request IDs returned by waiting room")
    if len({r.global_position for r in items}) != len(items):
        raise ValueError("Duplicate queue numbers returned by waiting room")
    return sorted(items, key=lambda r: r.global_position)


def group_by_section(requests: list[BatchedRequest]) -> dict:
    grouped = {section: [] for section in SECTIONS}
    for item in requests:
        grouped[item.section].append(item)
    for group in grouped.values():
        group.sort(key=lambda request: request.global_position)
    return grouped


def count_party_sizes(requests: list[BatchedRequest]) -> dict[int, int]:
    counts = {size: 0 for size in PARTY_SIZES}
    for item in requests:
        counts[item.party_size] += 1
    return counts


def send_allocation_input(batch_id: str, batch: list[BatchedRequest]) -> dict:
    """Prepare unranked hand-off data. Part 5 owns any subsequent ranking."""
    sections = {}
    for section, requests in group_by_section(batch).items():
        sections[section] = {
            "request_count": len(requests),
            "demand_counts": count_party_sizes(requests),
            "requests_by_party_size": {
                size: [asdict(item) for item in requests if item.party_size == size]
                for size in PARTY_SIZES
            },
        }
    return {
        "batch_id": batch_id,
        "batch_size": len(batch),
        "global_positions": [r.global_position for r in batch],
        "sections": sections,
    }


def build_allocator_payload(batch_payload: dict) -> dict:
    """
    Convert dispatcher grouping into Part 5's input format.

    Dispatcher counts demand only.
    Part 5 decides the allocation order.
    """
    requests = []
    section_demand = {}

    for section in SECTIONS:
        data = batch_payload["sections"][section]

        if data["request_count"] == 0:
            continue

        section_demand[section] = {
            str(size): data["demand_counts"][size]
            for size in PARTY_SIZES
        }

        for size in PARTY_SIZES:
            for item in data["requests_by_party_size"][size]:
                requests.append({
                    "request_id": item["request_id"],
                    "section": item["section"],
                    "party_size": item["party_size"],
                    "global_position": item["global_position"]
                })

    requests.sort(key=lambda item: item["global_position"])

    return {
        "batch_id": batch_payload["batch_id"],
        "requests": requests,
        "section_demand": section_demand
    }
