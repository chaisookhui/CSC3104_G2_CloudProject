"""Capped exponential backoff with equal jitter; no immediate synchronized retries."""
import random


def retry_delay(failures, *, cap=300, uniform=random.uniform):
    ceiling = min(cap, 2 ** min(max(1, failures), 9))
    return uniform(ceiling / 2, ceiling)
