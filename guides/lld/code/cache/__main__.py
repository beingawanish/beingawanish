"""Runnable slice: LRU order, TTL, size capacity, listeners, stats, single-flight.

Uses a FakeClock so the output is identical on every run.
Run with:  python3 -m cache   (from the code/ directory)
"""
import logging
import threading
import time

from cache import (
    Cache,
    CacheConfig,
    EvictionListener,
    FakeClock,
    LFUPolicy,
    RemovalNotification,
    read_through,
)


class PrintingListener(EvictionListener[str, object]):
    def on_removal(self, notification: RemovalNotification[str, object]) -> None:
        print(f"  listener: {notification.key!r} left ({notification.cause.value})")


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    clock = FakeClock()

    print("1) LRU, max 3 entries")
    lru = Cache(CacheConfig(max_entries=3), clock=clock,
                listeners=[PrintingListener()])
    for key in ("a", "b", "c"):
        lru.put(key, key.upper())
    lru.get("a")                    # a is now the most recent
    lru.put("d", "D")               # full: the least recent (b) goes
    print(f"  keys present: {[k for k in 'abcd' if k in lru]}")

    print("2) Same moves, LFU policy injected")
    lfu = Cache(CacheConfig(max_entries=3), policy=LFUPolicy(), clock=clock,
                listeners=[PrintingListener()])
    for key in ("a", "b", "c"):
        lfu.put(key, key.upper())
    for key in ("a", "a", "b", "c", "c"):
        lfu.get(key)
    lfu.put("d", "D")               # b has the lowest count; LRU would drop a

    print("3) Per-entry TTL, lazy expiry")
    ttl = Cache(CacheConfig(default_ttl=60), clock=clock,
                listeners=[PrintingListener()])
    ttl.put("session:awanish", "token-1")
    ttl.put("config", "v7", ttl=600)
    clock.advance(61)
    print(f"  stored before read: {len(ttl)}")
    print(f"  session after 61s: {ttl.get('session:awanish')}")
    print(f"  config after 61s:  {ttl.get('config')}")

    print("4) Capacity by size (bytes)")
    blobs = Cache(CacheConfig(max_entries=100, max_size=10), clock=clock,
                  sizer=len, listeners=[PrintingListener()])
    blobs.put("x", b"1234")
    blobs.put("y", b"1234")
    blobs.put("z", b"123456")       # 4 + 4 + 6 > 10: evict until it fits
    print(f"  total size now: {blobs.total_size}")

    print("5) Stats")
    print(f"  {lru.stats()}  hit rate {lru.stats().hit_rate:.0%}")

    print("6) Read-through with single-flight")
    users = Cache(CacheConfig(max_entries=100, default_ttl=30), clock=clock)

    @read_through(users)
    def load_user(user_id: int) -> str:
        time.sleep(0.05)            # a slow database call
        return f"user-{user_id}"

    barrier = threading.Barrier(50)
    results: list[str] = []

    def request() -> None:
        barrier.wait()              # all 50 miss at the same moment
        results.append(load_user(7))

    threads = [threading.Thread(target=request) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print(f"  {len(results)} callers got {set(results)}; "
          f"loader ran {load_user.single_flight.load_count} time(s)")


if __name__ == "__main__":
    main()
