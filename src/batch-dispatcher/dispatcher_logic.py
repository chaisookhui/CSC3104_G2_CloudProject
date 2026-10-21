"""Part 4: fixed batches and counts/requests grouped by section and party size.

No demand ranking or allocator interaction in this module.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

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


class BatchDispatcher:
    """In-memory demo. Waiting Room remains authoritative for admission state."""

    def __init__(self, batch_size: int = 50):
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.batch_size = batch_size
        self.batch_number = 0
        self.pending_ids: set[str] = set()
        self.last_known_queue: list[QueueRequest] = []

    def update_queue(self, entries: Iterable[QueueRequest]) -> None:
        self.last_known_queue = sorted(entries, key=lambda r: r.global_position)

    def remaining_count(self) -> int:
        return sum(r.request_id not in self.pending_ids for r in self.last_known_queue)

    def create_next_batch(self) -> tuple[dict, list[QueueRequest]] | None:
        eligible = [r for r in self.last_known_queue if r.request_id not in self.pending_ids]
        if not eligible:
            return None
        snapshot = eligible[:self.batch_size]
        self.batch_number += 1
        batch_id = f"batch-{self.batch_number:04d}"
        self.pending_ids.update(r.request_id for r in snapshot)
        batched = [BatchedRequest(r.request_id, r.global_position, r.section,
                                  r.party_size, batch_id) for r in snapshot]
        return send_allocation_input(batch_id, batched), snapshot

    def finish_preview(self, snapshot: list[QueueRequest]) -> None:
        """TEST ONLY: clear local pending state after Part 2 marks requests completed."""
        self.pending_ids.difference_update(r.request_id for r in snapshot)
