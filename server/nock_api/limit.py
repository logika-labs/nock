"""The rate limit: one token bucket per client address across both endpoints, in memory only and never
stored or logged. A project sends a usage report at most weekly (a retry at most daily) and a summary per
round, so a burst of 5, then 6 a minute, is plenty."""

from collections import OrderedDict

BURST = 5
PER_SECOND = 6 / 60
# The most addresses held at once; past it the longest idle is forgotten first.
MOST_ADDRESSES = 50_000


class Limit:
    """An address is forgotten once its bucket has refilled, under a minute after its last request.

    It is used from the server's one event loop, between awaits, so it takes no lock."""

    def __init__(self, most: int = MOST_ADDRESSES) -> None:
        self.most = most
        # address -> (tokens, when they were counted, in seconds), least recently seen first
        self.buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()

    def take(self, address: str, now: float) -> float:
        """0 when this address may post at `now` (seconds), else the seconds until it may."""
        self.forget(now)
        tokens, counted = self.buckets.pop(address, (BURST, now))
        tokens = min(BURST, tokens + max(0.0, now - counted) * PER_SECOND)
        if tokens >= 1:
            self.buckets[address] = (tokens - 1, now)
            return 0
        self.buckets[address] = (tokens, now)
        return (1 - tokens) / PER_SECOND

    def forget(self, now: float) -> None:
        """Drop the full buckets, which mean what no bucket means. The least recently seen is the first
        to fill, so the sweep stops at one that is not full, unless there are too many addresses."""
        while self.buckets:
            address, (tokens, counted) = next(iter(self.buckets.items()))
            full = tokens + (now - counted) * PER_SECOND >= BURST
            if not full and len(self.buckets) < self.most:
                return
            del self.buckets[address]
