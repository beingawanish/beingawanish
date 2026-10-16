"""Demo: python3 -m rate_limiter

A manual clock makes every number below reproducible.
"""
from . import (
    Algorithm,
    ClientKey,
    KeyScope,
    LimitRule,
    ManualClock,
    RateLimiter,
    RateLimiterConfig,
)

START = 1_000.0


def per_key_limits() -> None:
    print("== per-key limits and tiers ==")
    clock = ManualClock(START)
    limiter = RateLimiter(RateLimiterConfig(
        tiers={
            "anonymous": LimitRule("anonymous", 2, 10.0, Algorithm.SLIDING_COUNTER),
            "free": LimitRule("free", 3, 10.0, Algorithm.TOKEN_BUCKET),
            "pro": LimitRule("pro", 10, 10.0, Algorithm.TOKEN_BUCKET),
        },
        default_tier_by_scope={KeyScope.IP: "anonymous", KeyScope.USER: "free"},
    ), clock=clock)
    alice = ClientKey(KeyScope.USER, "alice")
    for attempt in range(1, 5):
        d = limiter.check(alice)
        print(f"alice #{attempt}: {d.status_code} remaining={d.remaining}")
    print("alice 429 headers:", limiter.check(alice).headers())
    bob = ClientKey(KeyScope.USER, "bob", tier="pro")
    d = limiter.check(bob)
    print(f"bob (pro) right after: {d.status_code} remaining={d.remaining}")
    ip = ClientKey(KeyScope.IP, "203.0.113.7")
    print("anonymous IP:", [limiter.check(ip).status_code for _ in range(3)])
    clock.advance(4.0)
    print("alice after 4s:", limiter.check(alice).status_code)


def boundary_burst() -> None:
    print("== 5 requests at t=9.9s, 5 more at t=10.1s, limit 5 per 10s ==")
    for algorithm in Algorithm:
        clock = ManualClock(START - 0.1)  # 0.1s before a window boundary
        limiter = RateLimiter(RateLimiterConfig(
            tiers={"t": LimitRule("t", 5, 10.0, algorithm)},
            default_tier_by_scope={KeyScope.USER: "t"},
        ), clock=clock)
        user = ClientKey(KeyScope.USER, "u")
        allowed = sum(limiter.check(user).allowed for _ in range(5))
        clock.advance(0.2)
        allowed += sum(limiter.check(user).allowed for _ in range(5))
        print(f"{algorithm:<16} allowed {allowed:>2} of 10 within 0.2s")


def leaky_shaping() -> None:
    print("== leaky bucket shapes: 4 requests at once, 1 per second drain ==")
    limiter = RateLimiter(RateLimiterConfig(
        tiers={"q": LimitRule("q", 1, 1.0, Algorithm.LEAKY_BUCKET, burst=3)},
        default_tier_by_scope={KeyScope.API_KEY: "q"},
    ), clock=ManualClock(START))
    key = ClientKey(KeyScope.API_KEY, "k-123")
    for _ in range(4):
        d = limiter.check(key)
        print(f"allowed={d.allowed} delay={d.delay:.1f}s retry_after={d.retry_after:.1f}s")


def idle_cleanup() -> None:
    print("== idle-key cleanup ==")
    clock = ManualClock(START)
    limiter = RateLimiter(RateLimiterConfig(
        tiers={"free": LimitRule("free", 5, 60.0)},
        default_tier_by_scope={KeyScope.IP: "free"},
        idle_grace_seconds=5.0,
    ), clock=clock)
    for n in range(1000):
        limiter.check(ClientKey(KeyScope.IP, f"10.0.{n // 256}.{n % 256}"))
    clock.advance(30.0)
    limiter.check(ClientKey(KeyScope.IP, "10.0.0.0"))  # one key stays active
    clock.advance(40.0)
    print("purged after 70s:", limiter.sweep_idle())
    clock.advance(30.0)
    print("purged after 100s:", limiter.sweep_idle())


def main() -> None:
    per_key_limits()
    boundary_burst()
    leaky_shaping()
    idle_cleanup()


if __name__ == "__main__":
    main()
