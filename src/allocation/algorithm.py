
import random


def group_requests_by_party_size(requests):
    """
    Step 1: Group ticket requests by party size (1 to 4).

    Each party-size group has its own list of requests.
    """

    groups = {1: [], 2: [], 3: [], 4: []}

    for request in requests:
        party_size = request["party_size"]

        if party_size not in groups:
            raise ValueError("Party size must be between 1 and 4")

        groups[party_size].append(request)

    return groups


def shuffle_requests(groups):
    """
    Step 2: Randomly shuffle requests within each party-size group.

    This prevents the original submission order from always
    determining which user receives priority.
    """

    for size in groups:
        random.shuffle(groups[size])

    return groups


def sort_sizes_by_demand(groups):
    """
    Step 3: Sort party sizes by demand, highest first.

    If two party sizes have equal demand, the smaller
    party size goes first, as specified in Section B0.
    """

    size_order = sorted(
        [size for size in groups if len(groups[size]) > 0],
        key=lambda size: (-len(groups[size]), size)
    )

    return size_order


def allocate_section(section, requests, hold_seats):
    """
    Steps 4-6: Execute the Demand-Cycle Allocation algorithm.

    Module 2 determines allocation order.

    The hold_seats function communicates with Module 3,
    which is responsible for checking seat availability
    and performing the actual seat reservation.

    Module 2 never modifies seat states directly.
    """

    # Step 1: Group requests by party size
    groups = group_requests_by_party_size(requests)

    # Step 2: Randomize requests within each group
    shuffle_requests(groups)

    # Step 3: Determine allocation priority
    size_order = sort_sizes_by_demand(groups)

    # Track party sizes that can still be allocated
    active_sizes = size_order.copy()

    # Store successful and unsuccessful allocation results
    results = []

    # Step 4: Allocate requests in repeated demand cycles
    while active_sizes:

        progress_made = False

        # Iterate over a copy because active_sizes may change
        for size in active_sizes.copy():

            # Skip party sizes without remaining requests
            if not groups[size]:
                active_sizes.remove(size)
                continue

            # Select the next request from the shuffled group
            party = groups[size].pop(0)

            # Ask Module 3 to reserve adjacent seats
            response = hold_seats(
                section,
                size,
                party["request_id"]
            )

            if response["success"]:

                progress_made = True

                # Store successful allocation
                results.append({
                    "request_id": party["request_id"],
                    "outcome": "seated",
                    "seats": response["seats"],
                    "hold_expiry": response["hold_expiry"]
                })

            else:

                # No fitting seats available for this party size
                # Preserve the unsuccessful request
                groups[size].insert(0, party)

                # Stop attempting this party size in this batch
                active_sizes.remove(size)

        # Stop if no allocations succeeded during this cycle
        if not progress_made:
            break

    # Step 5: Collect all remaining unseated requests
    unseated = []

    for size in groups:
        unseated.extend(groups[size])

    # Step 6: Mark unsuccessful requests as temporarily full
    for party in unseated:

        results.append({
            "request_id": party["request_id"],
            "outcome": "temporarily_full",
            "seats": [],
            "hold_expiry": None
        })

    return results
