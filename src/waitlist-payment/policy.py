"""Legacy selection policy retained for compatibility; checkout never calls it.

This is not the current global admission or Demand-Cycle algorithm. Do not wire
it into rejoining without an explicit agreement with the admission owner.

Entries must already be validated and filtered to eligible waiting requests.
Initial entries carry batch_order, late/re-entry entries carry arrival_order.
"""


def select_next(initial, late, fitting_sizes):
    heads = {}
    for entry in initial:
        size = entry["party_size"]
        if size not in heads or entry["batch_order"] < heads[size]["batch_order"]:
            heads[size] = entry
    for size in sorted(heads, reverse=True):
        if size in fitting_sizes:
            return heads[size]
    if late:
        oldest = min(late, key=lambda entry: entry["arrival_order"])
        if oldest["party_size"] in fitting_sizes:
            return oldest
    return None
