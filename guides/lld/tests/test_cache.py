"""Tests for the cache. Time is frozen with FakeClock throughout."""
import pathlib
import sys
import threading
import time
import unittest

# Make code/ importable when the suite runs from guides/lld/.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "code"))

from cache import (  # noqa: E402
    MISSING,
    Cache,
    CacheConfig,
    CacheConfigError,
    CacheError,
    DoublyLinkedList,
    EntryTooLargeError,
    EvictionKind,
    EvictionListener,
    FakeClock,
    FIFOPolicy,
    InvalidEntryError,
    LFUPolicy,
    LoadError,
    LRUPolicy,
    Node,
    OrderedDictLRUPolicy,
    RemovalCause,
    RemovalNotification,
    SingleFlightLoader,
    Sweeper,
    SweeperStateError,
    read_through,
)


class Recorder(EvictionListener):
    def __init__(self):
        self.seen: list[RemovalNotification] = []

    def on_removal(self, notification):
        self.seen.append(notification)

    def causes(self):
        return [(n.key, n.cause) for n in self.seen]


def make_cache(max_entries=3, **kwargs):
    clock = FakeClock()
    recorder = Recorder()
    config_fields = {k: kwargs.pop(k) for k in
                     ("max_size", "default_ttl", "eviction") if k in kwargs}
    cache = Cache(CacheConfig(max_entries=max_entries, **config_fields),
                  clock=clock, listeners=[recorder], **kwargs)
    return cache, clock, recorder


class LinkedListTests(unittest.TestCase):
    def setUp(self):
        self.lst = DoublyLinkedList()
        self.nodes = {k: Node(k) for k in "abc"}
        for k in "abc":
            self.lst.push_front(self.nodes[k])

    def test_push_front_orders_newest_first(self):
        self.assertEqual(list(self.lst), ["c", "b", "a"])
        self.assertEqual(self.lst.back().key, "a")

    def test_remove_middle_relinks_neighbours(self):
        self.lst.remove(self.nodes["b"])
        self.assertEqual(list(self.lst), ["c", "a"])
        self.assertEqual(len(self.lst), 2)

    def test_move_to_front(self):
        self.lst.move_to_front(self.nodes["a"])
        self.assertEqual(list(self.lst), ["a", "c", "b"])

    def test_back_of_empty_list_is_none(self):
        self.assertIsNone(DoublyLinkedList().back())


class PolicyTests(unittest.TestCase):
    """Insert c, b, a; then read a, a, b, c. Each policy picks differently."""

    def victim_of(self, policy):
        for key in "cba":
            policy.on_insert(key)
        for key in "aabc":
            policy.on_access(key)
        return policy.victim()

    def test_lru_evicts_least_recently_used(self):
        self.assertEqual(self.victim_of(LRUPolicy()), "a")

    def test_ordered_dict_lru_matches_hand_written_lru(self):
        self.assertEqual(self.victim_of(OrderedDictLRUPolicy()), "a")

    def test_lfu_evicts_least_frequently_used(self):
        self.assertEqual(self.victim_of(LFUPolicy()), "b")

    def test_fifo_ignores_reads(self):
        self.assertEqual(self.victim_of(FIFOPolicy()), "c")

    def test_lfu_tie_goes_to_least_recent(self):
        policy = LFUPolicy()
        for key in "xyz":
            policy.on_insert(key)
        self.assertEqual(policy.victim(), "x")

    def test_lfu_recovers_min_count_after_removal(self):
        policy = LFUPolicy()
        policy.on_insert("x")
        policy.on_insert("y")
        policy.on_access("y")
        policy.on_access("y")
        policy.on_remove("x")       # empties the count-1 bucket
        self.assertEqual(policy.victim(), "y")

    def test_empty_policy_victim_raises(self):
        for policy in (LRUPolicy(), LFUPolicy(), FIFOPolicy(),
                       OrderedDictLRUPolicy()):
            with self.subTest(policy=type(policy).__name__):
                with self.assertRaises(CacheError):
                    policy.victim()


class CacheBasicsTests(unittest.TestCase):
    def setUp(self):
        self.cache, self.clock, self.recorder = make_cache()

    def test_miss_returns_default(self):
        self.assertIsNone(self.cache.get("nope"))
        self.assertEqual(self.cache.get("nope", "dflt"), "dflt")

    def test_none_is_a_real_value(self):
        self.cache.put("k", None)
        self.assertIsNone(self.cache.get("k", MISSING))
        self.assertIn("k", self.cache)

    def test_overwrite_reports_replaced(self):
        self.cache.put("k", 1)
        self.cache.put("k", 2)
        self.assertEqual(self.cache.get("k"), 2)
        self.assertEqual(self.recorder.causes(), [("k", RemovalCause.REPLACED)])
        self.assertEqual(len(self.cache), 1)

    def test_delete_and_clear_are_explicit(self):
        for key in "abc":
            self.cache.put(key, key)
        self.assertTrue(self.cache.delete("a"))
        self.assertFalse(self.cache.delete("a"))
        self.cache.clear()
        self.assertEqual(len(self.cache), 0)
        self.assertTrue(all(c is RemovalCause.EXPLICIT
                            for _, c in self.recorder.causes()))

    def test_peek_has_no_side_effects(self):
        for key in "abc":
            self.cache.put(key, key)
        self.cache.peek("a")        # must NOT protect a from eviction
        self.cache.put("d", "d")
        self.assertNotIn("a", self.cache)
        self.assertEqual(self.cache.stats().requests, 0)


class CapacityTests(unittest.TestCase):
    def test_count_capacity_evicts_lru(self):
        cache, _, recorder = make_cache(max_entries=2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.get("a")
        cache.put("c", 3)
        self.assertEqual(recorder.causes(), [("b", RemovalCause.CAPACITY)])

    def test_size_capacity_evicts_until_it_fits(self):
        cache, _, recorder = make_cache(max_entries=10, max_size=10, sizer=len)
        cache.put("a", "xxxx")
        cache.put("b", "xxxx")
        cache.put("c", "xxxxxxxxx")  # 9: both a and b must go
        self.assertEqual([k for k, _ in recorder.causes()], ["a", "b"])
        self.assertEqual(cache.total_size, 9)

    def test_entry_exactly_max_size_fits(self):
        cache, _, _ = make_cache(max_entries=10, max_size=4, sizer=len)
        cache.put("a", "xxxx")
        self.assertEqual(cache.total_size, 4)

    def test_entry_bigger_than_cache_is_rejected(self):
        cache, _, _ = make_cache(max_entries=10, max_size=4, sizer=len)
        with self.assertRaises(EntryTooLargeError):
            cache.put("a", "xxxxx")

    def test_explicit_size_overrides_sizer(self):
        cache, _, _ = make_cache(max_entries=10, max_size=100)
        cache.put("a", "tiny", size=60)
        cache.put("b", "tiny", size=60)
        self.assertNotIn("a", cache)

    def test_config_picks_policy_by_name(self):
        cache, _, recorder = make_cache(max_entries=2,
                                        eviction=EvictionKind.FIFO)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.get("a")              # FIFO ignores this read
        cache.put("c", 3)
        self.assertEqual(recorder.causes(), [("a", RemovalCause.CAPACITY)])


class TTLTests(unittest.TestCase):
    def setUp(self):
        self.cache, self.clock, self.recorder = make_cache(default_ttl=10)

    def test_alive_just_before_ttl(self):
        self.cache.put("k", 1)
        self.clock.advance(9.999)
        self.assertEqual(self.cache.get("k"), 1)

    def test_dead_exactly_at_ttl(self):
        self.cache.put("k", 1)
        self.clock.advance(10)
        self.assertIsNone(self.cache.get("k"))
        self.assertEqual(self.recorder.causes(), [("k", RemovalCause.EXPIRED)])

    def test_per_entry_ttl_overrides_default(self):
        self.cache.put("short", 1, ttl=1)
        self.cache.put("long", 2, ttl=100)
        self.clock.advance(50)
        self.assertIsNone(self.cache.get("short"))
        self.assertEqual(self.cache.get("long"), 2)

    def test_no_default_ttl_means_forever(self):
        cache, clock, _ = make_cache()
        cache.put("k", 1)
        clock.advance(10**9)
        self.assertEqual(cache.get("k"), 1)

    def test_expiry_is_lazy(self):
        self.cache.put("k", 1)
        self.clock.advance(10)
        self.assertEqual(len(self.cache), 1)      # still stored
        self.assertNotIn("k", self.cache)         # but invisible
        self.cache.get("k")
        self.assertEqual(len(self.cache), 0)      # now gone

    def test_purge_expired_removes_only_dead(self):
        self.cache.put("a", 1)
        self.cache.put("b", 2, ttl=100)
        self.clock.advance(10)
        self.assertEqual(self.cache.purge_expired(), 1)
        self.assertEqual(self.cache.stats().expirations, 1)
        self.assertIn("b", self.cache)

    def test_invalid_ttl_rejected(self):
        for bad in (0, -1):
            with self.subTest(ttl=bad):
                with self.assertRaises(InvalidEntryError):
                    self.cache.put("k", 1, ttl=bad)


class StatsTests(unittest.TestCase):
    def test_hits_misses_and_rate(self):
        cache, _, _ = make_cache()
        cache.put("a", 1)
        cache.get("a")
        cache.get("a")
        cache.get("zzz")
        stats = cache.stats()
        self.assertEqual((stats.hits, stats.misses, stats.puts), (2, 1, 1))
        self.assertAlmostEqual(stats.hit_rate, 2 / 3)

    def test_evictions_and_expirations_counted_apart(self):
        cache, clock, _ = make_cache(max_entries=1, default_ttl=5)
        cache.put("a", 1)
        cache.put("b", 2)           # evicts a
        clock.advance(5)
        cache.get("b")              # expires b
        stats = cache.stats()
        self.assertEqual((stats.evictions, stats.expirations), (1, 1))

    def test_empty_cache_hit_rate_is_zero(self):
        cache, _, _ = make_cache()
        self.assertEqual(cache.stats().hit_rate, 0.0)


class ConfigTests(unittest.TestCase):
    def test_bad_values_rejected(self):
        bad = [dict(max_entries=0), dict(max_size=0), dict(default_ttl=0),
               dict(sweep_interval=0)]
        for fields in bad:
            with self.subTest(**fields):
                with self.assertRaises(CacheConfigError):
                    CacheConfig(**fields)

    def test_config_error_is_also_a_value_error(self):
        with self.assertRaises(ValueError):
            CacheConfig(max_entries=-5)


class ListenerTests(unittest.TestCase):
    def test_broken_listener_is_logged_not_raised(self):
        class Broken(EvictionListener):
            def on_removal(self, notification):
                raise RuntimeError("boom")

        recorder = Recorder()
        cache = Cache(CacheConfig(max_entries=1),
                      listeners=[Broken(), recorder])
        cache.put("a", 1)
        with self.assertLogs("cache.cache", level="ERROR"):
            cache.put("b", 2)
        self.assertEqual(recorder.causes(), [("a", RemovalCause.CAPACITY)])

    def test_listener_runs_outside_the_lock(self):
        holder = {}

        class Reentrant(EvictionListener):
            def on_removal(self, notification):
                holder["cache"].get("anything")   # deadlocks if lock held

        cache = Cache(CacheConfig(max_entries=1), listeners=[Reentrant()])
        holder["cache"] = cache
        cache.put("a", 1)
        worker = threading.Thread(target=cache.put, args=("b", 2), daemon=True)
        worker.start()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive(), "listener ran under the lock")


class SweeperTests(unittest.TestCase):
    def test_sweep_once(self):
        cache, clock, _ = make_cache(default_ttl=1)
        cache.put("a", 1)
        clock.advance(1)
        self.assertEqual(Sweeper(cache, interval=60).sweep_once(), 1)

    def test_background_thread_purges(self):
        cache, clock, _ = make_cache(default_ttl=1)
        cache.put("a", 1)
        clock.advance(1)
        with Sweeper(cache, interval=0.01):
            deadline = time.monotonic() + 2
            while len(cache) and time.monotonic() < deadline:
                time.sleep(0.01)
        self.assertEqual(len(cache), 0)

    def test_lifecycle_errors(self):
        cache, _, _ = make_cache()
        sweeper = Sweeper(cache, interval=60)
        with self.assertRaises(SweeperStateError):
            sweeper.stop()
        sweeper.start()
        with self.assertRaises(SweeperStateError):
            sweeper.start()
        sweeper.stop()


class LoaderTests(unittest.TestCase):
    def test_loads_once_then_serves_from_cache(self):
        cache, _, _ = make_cache()
        calls = []

        @read_through(cache)
        def fetch(key):
            calls.append(key)
            return key * 2

        self.assertEqual(fetch(21), 42)
        self.assertEqual(fetch(21), 42)
        self.assertEqual(calls, [21])
        self.assertEqual(fetch.__name__, "fetch")

    def test_loader_ttl_is_applied(self):
        cache, clock, _ = make_cache()
        flight = SingleFlightLoader(cache, lambda k: k, ttl=5)
        flight.get("k")
        clock.advance(5)
        flight.get("k")
        self.assertEqual(flight.load_count, 2)

    def test_failure_is_wrapped_and_not_cached(self):
        cache, _, _ = make_cache()
        attempts = []

        def flaky(key):
            attempts.append(key)
            if len(attempts) == 1:
                raise ConnectionError("db down")
            return "ok"

        flight = SingleFlightLoader(cache, flaky)
        with self.assertRaises(LoadError) as ctx:
            flight.get("k")
        self.assertIsInstance(ctx.exception.__cause__, ConnectionError)
        self.assertEqual(flight.get("k"), "ok")   # retried, not negative-cached

    def test_concurrent_misses_share_one_load(self):
        cache, _, _ = make_cache()
        started, release = threading.Event(), threading.Event()

        def slow(key):
            started.set()
            release.wait(2)
            return f"v-{key}"

        flight = SingleFlightLoader(cache, slow)
        results = []
        threads = [threading.Thread(target=lambda: results.append(flight.get("hot")))
                   for _ in range(20)]
        for t in threads:
            t.start()
        started.wait(2)
        release.set()
        for t in threads:
            t.join()
        self.assertEqual(results, ["v-hot"] * 20)
        self.assertEqual(flight.load_count, 1)

    def test_followers_see_the_leaders_failure(self):
        cache, _, _ = make_cache()
        started, release = threading.Event(), threading.Event()

        def failing(key):
            started.set()
            release.wait(2)
            raise TimeoutError("slow db")

        flight = SingleFlightLoader(cache, failing)
        errors = []

        def call():
            try:
                flight.get("k")
            except LoadError as exc:
                errors.append(exc)

        leader = threading.Thread(target=call)
        leader.start()
        started.wait(2)
        followers = [threading.Thread(target=call) for _ in range(5)]
        for t in followers:
            t.start()
        time.sleep(0.1)             # let followers park on the Future
        release.set()
        for t in [leader, *followers]:
            t.join()
        self.assertEqual(len(errors), 6)
        self.assertEqual(flight.load_count, 1)


class ConcurrencyTests(unittest.TestCase):
    def test_invariants_hold_under_contention(self):
        cache = Cache(CacheConfig(max_entries=50, max_size=200),
                      sizer=lambda v: v % 7 + 1)
        barrier = threading.Barrier(8)

        def hammer(seed):
            barrier.wait()
            for i in range(2000):
                key = (seed * 31 + i) % 120
                if i % 3:
                    cache.get(key)
                else:
                    cache.put(key, i)

        threads = [threading.Thread(target=hammer, args=(s,)) for s in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertLessEqual(len(cache), 50)
        self.assertLessEqual(cache.total_size, 200)
        stats = cache.stats()
        self.assertEqual(stats.requests + stats.puts, 8 * 2000)


if __name__ == "__main__":
    unittest.main()
