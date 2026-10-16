"""Insert the new LLD chapters into the guide (run by guides/guide.py load(), after the other fix layers).

Fragments live in guides/lld/chapters/, named NN-slug.html and sorted by name:
06v2-… is Version 2 of Chapter 6 (an h2 section appended to that chapter),
07-… to 15-… are new problem chapters. They all go, in order, just before the outro,
which becomes the last chapter. The TOC gets an entry for every new h1 and h2.
Text edits to the intro and outro live in TEXT_EDITS (old, new, expected count).
"""
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
CHAPTERS = HERE / "chapters"
OUTRO_OLD = ("chapter-7-what-repeats", "Chapter 7: What Repeats")

TEXT_EDITS: list[tuple[str, str, int]] = [
    # ---- Chapter 0: counts -------------------------------------------------------------
    (
        "<p><em>Six low-level design problems, typed end to end",
        "<p><em>Fifteen low-level design problems, typed end to end",
        1,
    ),
    (
        "<p>Six problems. One method: you type every line.</p>",
        "<p>Fifteen problems. One method: you type every line.</p>",
        1,
    ),
    (
        "<p>Each of the six chapters takes one low-level design problem — parking lot, elevator system, traffic light, library management, vending machine, car rental — and walks you through a complete, working, tested solution. Nothing is pasted. You type it all.</p>",
        "<p>Each of the fifteen problem chapters takes one low-level design problem and walks you through a complete, working, tested solution. The first six are the classics: parking lot, elevator system, traffic light, library management, vending machine, car rental. The next nine are the problems 2026 interviews reach for: traffic management, rate limiter, LRU cache with TTL, movie ticket booking, expense sharing, ride-sharing, food delivery, an LLM gateway and an agent tool-calling framework. Car rental also gets a Version 2, where the interviewer's follow-ups are built as real code instead of answered in words. Nothing is pasted. You type it all.</p>",
        1,
    ),
    ("ten times across six chapters,", "ten times across fifteen chapters,", 1),
    # ---- Chapter 0: "The fifteen problems" ---------------------------------------------
    (
        '<li><a href="#the-six-problems" id="toc-the-six-problems">The six problems</a></li>',
        '<li><a href="#the-fifteen-problems" id="toc-the-fifteen-problems">The fifteen problems</a></li>\n'
        '<li><a href="#reading-paths" id="toc-reading-paths">Reading paths</a></li>',
        1,
    ),
    (
        '<h2 id="the-six-problems">The six problems</h2>',
        '<h2 id="the-fifteen-problems">The fifteen problems</h2>',
        1,
    ),
    (
        "<p>Different stories, same moves. By the third chapter you will start predicting the design before you read it. That feeling is the whole point.</p>",
        "<p>Then come nine more, in five families.</p>\n"
        "<p><strong>Classic infrastructure.</strong> <strong>Rate limiter</strong> is really about atomic read-modify-write. Five algorithms answer the same question, \"may this pass?\", and the hard part is making sure two threads can't both read 9 of 10 and both let a request through. <strong>LRU cache with TTL</strong> is two data structures doing one job: a dict for finding, a linked list for ordering. Add time that makes entries go stale, and a stampede to stop when a hot key expires.</p>\n"
        "<p><strong>Booking and money.</strong> <strong>Movie ticket booking</strong> is a race with exactly one winner. Two people click seat B2 at the same instant, one of them gets a ten-minute hold, and the payment that follows must move money exactly once. <strong>Expense sharing (Splitwise)</strong> is a ledger that must never lose a cent: integer money, one written-down rounding rule, and an honest answer to \"minimise the number of payments\", which turns out to be NP-hard.</p>\n"
        "<p><strong>Marketplaces.</strong> <strong>Ride-sharing</strong> is the elevator dispatcher with money attached, plus one hard guarantee: a driver is never handed two riders at once. <strong>Food delivery</strong> is a long order lifecycle with three parties in it (customer, restaurant, delivery partner), a bill built step by step, and an order that must be safe to place twice.</p>\n"
        "<p><strong>City systems.</strong> <strong>Traffic management</strong> is Chapter 3 grown up. Many intersections, a control centre pushing timing plans and green waves, and controllers that stay safe when the centre goes quiet or pushes a bad plan.</p>\n"
        "<p><strong>AI-era systems.</strong> <strong>LLM gateway</strong> is a thin orchestrator over small, single-purpose classes: routing, retries, a circuit breaker, fallback across providers, per-team quotas, and a ledger that bills every token. <strong>Agent tool-calling framework</strong> is the loop between a model and the functions it may call — and everything that loop does wrong by default. It runs forever. It crashes on the first tool error. It sends an email twice. It obeys a web page.</p>\n"
        "<p>And <strong>Car rental, Version 2</strong> is the follow-up round made real. The interviewer moves the goalposts five times: dynamic pricing, an electric fleet, a vehicle lifecycle, branches with one-way trips, payments with a deposit. Every change lands in a new package, and not one line of version 1 is edited.</p>\n"
        "<p>Different stories, same moves. By the third chapter you will start predicting the design before you read it. That feeling is the whole point.</p>\n"
        "<p><strong>What 2026 interviews add.</strong> The classics still open plenty of rounds. What has changed is the follow-up questions, and the nine newer chapters exist to rehearse them. Four themes come up again and again:</p>\n"
        "<ul>\n"
        "<li><strong>Concurrency correctness.</strong> Not \"did you add a lock\" but \"show me the check-then-act, and prove two threads can't both win.\" With free-threaded Python 3.13 builds around, \"the GIL protects me\" no longer counts as an answer.</li>\n"
        "<li><strong>Idempotency.</strong> The client will retry. The gateway will time out after it took the money. The same request must not act twice.</li>\n"
        "<li><strong>Money.</strong> Integer minor units, a rounding rule you can state, refunds that depend on who cancelled and when.</li>\n"
        "<li><strong>AI-era systems.</strong> Interviewers now ask for the gateway in front of a model and the runtime around an agent. They grade them with the same rubric as a parking lot.</li>\n"
        "</ul>\n"
        "<h2 id=\"reading-paths\">Reading paths</h2>\n"
        "<p>Reading straight through works, and it is the best path if you have the time. The chapters are in a sensible order, and a few later ones lean on earlier ones: Chapter 7 grows Chapter 3's transition table, and Chapter 13 borrows Chapter 12's surge policy. At one sitting a day, the whole guide is sixteen sittings, plus the outro.</p>\n"
        "<p>If the interview is two weeks away, take this path instead. It keeps one sitting a day and skips the two chapters whose moves you will meet elsewhere: Chapter 4 (repositories and notifications come back in Chapters 10 to 13) and Chapter 7 (it extends Chapter 3, which you will have typed). Read Chapter 16 on the last evening.</p>\n"
        "<table>\n"
        "<thead>\n"
        "<tr><th>Days</th><th>Sittings</th><th>What you are practising</th></tr>\n"
        "</thead>\n"
        "<tbody>\n"
        "<tr><td>1–3</td><td>Chapters 1, 2, 3</td><td>Allocation, dispatch, the transition table</td></tr>\n"
        "<tr><td>4–6</td><td>Chapter 5, Chapter 6, Chapter 6 Version 2</td><td>State plus money, intervals, follow-ups as code</td></tr>\n"
        "<tr><td>7–8</td><td>Chapters 8, 9</td><td>Atomic updates, eviction, expiry</td></tr>\n"
        "<tr><td>9–10</td><td>Chapters 10, 11</td><td>One-winner races, idempotent payments, exact money</td></tr>\n"
        "<tr><td>11–12</td><td>Chapters 12, 13</td><td>Compare-and-set claims, long lifecycles</td></tr>\n"
        "<tr><td>13–14</td><td>Chapters 14, 15</td><td>Retries, breakers, quotas, the agent loop</td></tr>\n"
        "</tbody>\n"
        "</table>\n"
        "<p>Shorter still, if you know what the role is about. A backend infrastructure round: Chapters 1, 6, 8, 9, 14. A product company with bookings and payments: Chapters 6 (with Version 2), 10, 11, 12, 13. An AI platform team: Chapters 8, 9, 14, 15, since the rate limiter and the cache are the gateway's own parts.</p>",
        1,
    ),
    # ---- Chapter 0: structure and setup -----------------------------------------------
    (
        "Once you have done one, you know the shape of the other five, and you can pace yourself against it.</p>",
        "Once you have done one, you know the shape of the other fourteen, and you can pace yourself against it. Chapter 6 has one extra section at the end, Version 2, where its follow-ups get built as code.</p>",
        1,
    ),
    (
        "<p>Each problem lives in its own directory under <code>code/</code>, with its tests beside it under <code>tests/</code>. Run the suite for the problem you are working on from the repository root:</p>",
        "<p>Each problem lives in its own package under <code>code/</code>, and all the tests live together under <code>tests/</code>. Run the suite from the guide root, the folder that holds both <code>code/</code> and <code>tests/</code>:</p>",
        1,
    ),
    (
        "<p>The <code>-v</code> flag matters while you are learning: it names each test as it runs, so a failure tells you exactly which behavior broke.</p>",
        "<p>The <code>-v</code> flag matters while you are learning: it names each test as it runs, so a failure tells you exactly which behavior broke.</p>\n"
        "<p>To run one problem's tests on their own, add <code>-t .</code> and a file pattern: <code>python3 -m unittest discover -s tests -t . -p 'test_rate_limiter*.py' -v</code>. The <code>-t .</code> makes discovery import <code>tests</code> as a package, so <code>tests/__init__.py</code> runs, and that file puts <code>code/</code> on <code>sys.path</code>. You never set <code>PYTHONPATH</code> yourself.</p>\n"
        "<p>Demos are the one exception to \"run it from the guide root.\" A package with a <code>__main__.py</code> runs as <code>python3 -m &lt;package&gt;</code> from inside <code>code/</code>: <code>cd code</code>, then <code>python3 -m rate_limiter</code>. Chapters 12 and 15 use a plain script instead, <code>python3 ride_demo.py</code> and <code>python3 agent_demo.py</code>, from the same folder. Some chapters suggest a flat project of your own, with the package and <code>tests/</code> side by side. In that layout, run everything from that one folder.</p>",
        1,
    ),
    ("so once you learn one, you know all six.", "so once you learn one, you know them all.", 1),
    (
        "<p>Suggested pace: one problem per sitting — the type-along first, the stretch tasks after. Six problems, six sittings, and at the end a set of moves your hands know. The outro chapter then shows you how those moves connect across problems and hands you fifteen interview questions to test the understanding behind them.</p>",
        "<p>Suggested pace: one problem per sitting — the type-along first, the stretch tasks after. Fifteen problems and one Version 2 make sixteen sittings, and at the end a set of moves your hands know. The reading paths above show how to cut that to two weeks. The outro, Chapter 16, then shows you how those moves connect across problems and hands you twenty-three interview questions to test the understanding behind them.</p>",
        1,
    ),
    # ---- Outro (Chapter 16) -----------------------------------------------------------
    (
        "<p>You have typed six complete systems. Step back",
        "<p>You have typed fifteen complete systems, and a second version of one of them. Step back",
        1,
    ),
    (
        "<p>It was never really six different problems. The same five patterns kept showing up in different clothes. The same six design moves solved the hard part every time.",
        "<p>It was never really fifteen different problems. A short list of patterns kept showing up in different clothes. The same ten design moves solved the hard part, chapter after chapter.",
        1,
    ),
    (
        '<h2 id="the-pattern-map">The pattern map</h2>',
        '<h2 id="the-pattern-map">The pattern map</h2>\n'
        "<p>Start with the first six chapters. That is where the vocabulary was learned: five classic patterns, each with one job.</p>",
        1,
    ),
    (
        "<p>Five patterns, six problems. Here is the shape of it.",
        "<p>Five patterns, and the first six problems. Here is the shape of it.",
        1,
    ),
    (
        '<title id="pattern-map-title">The cross-problem pattern map</title>',
        '<title id="pattern-map-title">The cross-problem pattern map for Chapters 1 to 6</title>',
        1,
    ),
    (
        '<desc id="pattern-map-desc">Five design patterns connect to the six LLD type-along problems; each labeled edge names the job the pattern does.</desc>',
        '<desc id="pattern-map-desc">Five design patterns connect to the six classic problems of Chapters 1 to 6; each labeled edge names the job the pattern does. The Pattern × chapter table after the map covers all fifteen problems.</desc>',
        1,
    ),
    (">Five patterns, six problems</text>", ">Five patterns, the first six problems</text>", 1),
    (">SIX TYPE-ALONG PROBLEMS</text>", ">THE CLASSICS · CHAPTERS 1–6</text>", 1),
    (">the six type-along problems</text>", ">the classics, Chapters 1–6</text>", 1),
    (
        "and it showed up four times in six chapters. When the interviewer hands you a seventh problem, your first question is not \"what do I build.\" It is \"which of these five is this.\"</p>",
        "and it showed up four times in the first six chapters. When the interviewer hands you a problem you have never seen, your first question is not \"what do I build.\" It is \"which of these is this.\"</p>",
        1,
    ),
    (
        "<p>If you only carry two patterns into an interview, make them Strategy and State. Strategy showed up four times",
        "<p>If you only carry two patterns into an interview, make them Strategy and State. In the classics, Strategy showed up four times",
        1,
    ),
    (
        '<li><a href="#the-pattern-map" id="toc-the-pattern-map">The pattern map</a></li>',
        '<li><a href="#the-pattern-map" id="toc-the-pattern-map">The pattern map</a></li>\n'
        '<li><a href="#pattern-by-chapter" id="toc-pattern-by-chapter">Pattern × chapter</a></li>',
        1,
    ),
    (
        '<h2 id="the-design-moves-that-repeat">The design moves that repeat</h2>',
        '<h2 id="pattern-by-chapter">Pattern × chapter</h2>\n'
        "<p>Then came nine more problems, and the real question was whether the five would hold. They did. Strategy turned up in all nine, and in Version 2 as well. State machines came back in four of them and in Version 2, plus once in disguise: the LLM gateway's circuit breaker is a three-state machine (closed, open, half-open). Repository carried the storage in six of the nine, and Observer the notifications in four.</p>\n"
        "<p>A few new names joined the list. <strong>Chain of Responsibility</strong> arrived three times: food delivery's discount rules, the gateway's guardrails, the agent's hooks. Each is a run of handlers that decide for themselves whether to act, and none of them knows about the others. <strong>Circuit breaker</strong> arrived with the gateway. It answers \"should I even try this provider?\", which is a different question from the retrier's \"should I wait and try again?\", so it is a different class.</p>\n"
        "<p>The last four columns are design moves rather than patterns, but they belong on the same map. The next section covers them.</p>\n"
        '<div style="overflow-x:auto">\n'
        "<table>\n"
        "<thead>\n"
        "<tr><th>Chapter</th><th>Strategy</th><th>State machine</th><th>Observer</th><th>Chain of Resp.</th><th>Repository</th><th>Circuit breaker</th><th>Idempotency key</th><th>Compare-and-set claim</th><th>Per-key lock</th><th>Injected clock</th></tr>\n"
        "</thead>\n"
        "<tbody>\n"
        "<tr><td>1 Parking lot</td><td>●</td><td></td><td></td><td></td><td>●</td><td></td><td></td><td></td><td></td><td>●</td></tr>\n"
        "<tr><td>2 Elevator</td><td>●</td><td>●</td><td>●</td><td></td><td>●</td><td></td><td></td><td></td><td></td><td>●</td></tr>\n"
        "<tr><td>3 Traffic light</td><td></td><td>●</td><td>●</td><td></td><td></td><td></td><td></td><td></td><td></td><td>●</td></tr>\n"
        "<tr><td>4 Library</td><td>●</td><td></td><td>●</td><td></td><td>●</td><td></td><td></td><td></td><td></td><td>●</td></tr>\n"
        "<tr><td>5 Vending machine</td><td></td><td>●</td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>\n"
        "<tr><td>6 Car rental</td><td>●</td><td></td><td></td><td></td><td>●</td><td></td><td></td><td></td><td></td><td>●</td></tr>\n"
        "<tr><td>6 Version 2</td><td>●</td><td>●</td><td></td><td></td><td>●</td><td></td><td>●</td><td></td><td></td><td>●</td></tr>\n"
        "<tr><td>7 Traffic management</td><td>●</td><td>●</td><td>●</td><td></td><td></td><td></td><td></td><td></td><td></td><td>●</td></tr>\n"
        "<tr><td>8 Rate limiter</td><td>●</td><td></td><td></td><td></td><td>●</td><td></td><td></td><td></td><td></td><td>●</td></tr>\n"
        "<tr><td>9 LRU cache with TTL</td><td>●</td><td></td><td>●</td><td></td><td></td><td></td><td></td><td></td><td></td><td>●</td></tr>\n"
        "<tr><td>10 Movie ticket booking</td><td>●</td><td>●</td><td></td><td></td><td>●</td><td></td><td>●</td><td>●</td><td>●</td><td>●</td></tr>\n"
        "<tr><td>11 Expense sharing</td><td>●</td><td></td><td></td><td></td><td>●</td><td></td><td></td><td></td><td>●</td><td>●</td></tr>\n"
        "<tr><td>12 Ride-sharing</td><td>●</td><td>●</td><td>●</td><td></td><td>●</td><td></td><td></td><td>●</td><td></td><td>●</td></tr>\n"
        "<tr><td>13 Food delivery</td><td>●</td><td>●</td><td>●</td><td>●</td><td>●</td><td></td><td>●</td><td>●</td><td></td><td>●</td></tr>\n"
        "<tr><td>14 LLM gateway</td><td>●</td><td>●</td><td></td><td>●</td><td></td><td>●</td><td></td><td></td><td></td><td>●</td></tr>\n"
        "<tr><td>15 Agent tool-calling</td><td>●</td><td></td><td></td><td>●</td><td>●</td><td></td><td>●</td><td></td><td>●</td><td>●</td></tr>\n"
        "</tbody>\n"
        "</table>\n"
        "</div>\n"
        "<p>Read the table by columns, not rows. Strategy's column is solid apart from the two pure state machines, because \"the rule might change\" never stopped being the most common sentence in a requirements doc. The clock column is solid apart from the vending machine, which never asks what time it is. The right-hand columns are empty in Chapters 1 to 6 and fill up from Version 2 on, exactly where retries, money and marketplaces arrive. That is the 2026 shift, in one picture.</p>\n"
        '<h2 id="the-design-moves-that-repeat">The design moves that repeat</h2>',
        1,
    ),
    (
        "<p>Patterns are the vocabulary. These six moves are the grammar — the small decisions that showed up in every chapter, in almost the same form, because they solve problems that every LLD problem has.</p>",
        "<p>Patterns are the vocabulary. These moves are the grammar — the small decisions that showed up chapter after chapter, in almost the same form, because they solve problems that every LLD problem has. The classics taught the first six. The newer chapters added four more.</p>",
        1,
    ),
    (
        '<li><a href="#fifteen-questions-to-test-the-understanding" id="toc-fifteen-questions-to-test-the-understanding">Fifteen questions to test the understanding</a></li>',
        '<li><a href="#twenty-three-questions-to-test-the-understanding" id="toc-twenty-three-questions-to-test-the-understanding">Twenty-three questions to test the understanding</a></li>',
        1,
    ),
    (
        '<h2 id="fifteen-questions-to-test-the-understanding">Fifteen questions to test the understanding</h2>',
        "<p><strong>Make retries safe with idempotency keys.</strong> Networks fail in the worst possible place: after the work happened, before the answer arrived. The caller can't tell which, so it retries. Version 2's payments, the movie booking's charges, food delivery's place-order and the agent's side-effecting tools all handle this the same way. Each request carries a key. The first result is stored under it, and a repeat gets the stored result back instead of acting twice. The agent chapter adds one sharp detail: build the key from what the call does (run id, tool name, canonical input), not from an id the model mints fresh on every retry.</p>\n"
        "<p><strong>Claim with compare-and-set.</strong> \"Is it free? Then it's mine\" is two steps, and another thread can always slip between them. Ride-sharing's <code>DriverRepository.claim(driver_id, expected, new)</code> flips a driver's status only if it still holds the expected value. Food delivery's partner reservation works the same way. So does the movie booking's confirm, which commits only if the booking is still <code>HELD</code>. The nice part is that the in-memory version and the database version have the same shape: an <code>UPDATE … WHERE status = 'AVAILABLE'</code>, then a check of the row count.</p>\n"
        "<p><strong>Lock per key, not per system.</strong> One lock for everything is correct and simple, and Chapter 1 defends it. But a rush on one show shouldn't slow every other show. Movie booking hands out one lock per show, Splitwise one per group, and the agent's idempotency store one per key. Each lock still guards a whole check-then-act. There are just more of them, so strangers stop queuing behind each other.</p>\n"
        "<p><strong>Keep slow work outside the lock.</strong> A lock held across a payment call makes every other user wait for one person's card. The movie booking splits its confirm into three phases for exactly this reason: check under the lock, charge with no lock held, then re-take the lock and commit. The rate limiter logs only after releasing its lock, and the cache never calls a listener while holding its own. The rule is short. Inside the lock, touch memory and nothing else.</p>\n"
        "<p>And the oldest move kept growing. The injected clock in the LLM gateway does more than tell the time. Its <code>FakeClock.sleep</code> advances time instead of blocking, so a test that walks through retries and a 30-second circuit cooldown still runs in milliseconds.</p>\n"
        '<h2 id="twenty-three-questions-to-test-the-understanding">Twenty-three questions to test the understanding</h2>',
        1,
    ),
    (
        "without the book open, the six chapters did their job.",
        "without the book open, the fifteen chapters did their job.",
        1,
    ),
    (
        '<h2 id="the-checklist-revisited">The checklist, revisited</h2>',
        "<p><strong>16. Why does a traffic controller clamp a timing plan instead of trusting it?</strong></p>\n"
        "<p>Because safety lives in the controller, never in the plan. A plan only says how many green seconds each axis gets. Yellow and all-red come from the controller's own safety timings, and any green below the minimum gets clamped. So a buggy plan, or one pushed by a compromised centre, can make traffic slow. It cannot make it unsafe. That is also why every timing strategy is safe to plug in.</p>\n"
        "<p><strong>17. How does a rate limiter stay correct when two requests for the same key arrive at once?</strong></p>\n"
        "<p>The whole read-modify-write runs as one atomic unit inside the store. <code>StateStore.update</code> reads the state, runs the algorithm's step, writes the result and sets the expiry together: a lock in memory, a Lua script in Redis. The algorithm itself is a pure function with no clock and no lock, so the same step can run in either place. Split the read from the write and you get the classic race: two threads both see 9 of 10, both write 10, and 11 requests pass.</p>\n"
        "<p><strong>18. Why does an LRU cache need both a dict and a doubly linked list?</strong></p>\n"
        "<p>The dict finds a key in O(1) but knows nothing about age. The list knows the order, but finding a key in it is O(n). Together, a hit is \"find the node through the dict, unlink it, push it to the front\", and eviction is \"take the node at the back.\" It has to be doubly linked, because unlinking from the middle needs the predecessor. Then admit the shortcut: <code>OrderedDict</code> is exactly this pair, written in C.</p>\n"
        "<p><strong>19. Why not hold the show's lock while the payment gateway charges the card?</strong></p>\n"
        "<p>A gateway call can take seconds, and under the lock every other user of that show waits. So confirm runs in three phases: check the hold under the lock, charge with no lock held, then re-take the lock and commit only if the booking is still <code>HELD</code>. The price is one extra case. The hold can expire while the money moves, and then the service refunds automatically. That case has its own test.</p>\n"
        "<p><strong>20. Why store money as integer minor units, and who gets the leftover cent?</strong></p>\n"
        "<p>Floats drift, and a ledger is updated thousands of times. Integers make every addition exact, and rounding happens once, inside one function, under one rule. The rule is largest remainder: everyone gets the floor of their share, and the leftover cents go to the largest fractional remainders, ties to whoever is listed first. So $100 split three ways is $33.34, $33.33, $33.33, and two servers computing the same split always agree.</p>\n"
        "<p><strong>21. How does ride-sharing guarantee a driver never gets two riders?</strong></p>\n"
        "<p>A compare-and-set claim. Dispatch ranks a snapshot of drivers, then claims the winner: the repository flips the driver from <code>AVAILABLE</code> to <code>OFFERED</code> only if the status is still <code>AVAILABLE</code>. If the claim fails, dispatch tries the next driver. An offered driver is invisible to every other dispatch. In a database the same move is an <code>UPDATE … WHERE status = 'AVAILABLE'</code> with a row-count check.</p>\n"
        "<p><strong>22. In the LLM gateway, why does every error carry a retryable flag?</strong></p>\n"
        "<p>Because three components key off it. The retrier retries only retryable errors, the breaker counts only retryable errors, and the fallback loop moves to the next model only after one. A 400 means the request itself is wrong. Retrying it, or sending it to another provider, just burns money and time to get the same answer. Retry inside a model, fall back across models.</p>\n"
        "<p><strong>23. Why does the agent framework turn tool failures into results instead of raising?</strong></p>\n"
        "<p>A model can fix its own mistakes, but only if it sees them. An unknown tool, a bad argument, a denied permission or a crashing tool all become a <code>tool_result</code> with <code>is_error: true</code> and a message that names the problem, and the loop keeps going. Only faults the model cannot fix raise: the model call itself, a broken message protocol, bad config. Same idea as answer 11, turned around. Exceptions are for faults; an error the caller can act on is data.</p>\n"
        '<h2 id="the-checklist-revisited">The checklist, revisited</h2>',
        1,
    ),
    # ---- Outro: where to go next ------------------------------------------------------
    (
        "<p>Two problems from your original list did not make this guide: <strong>ride sharing</strong> and the <strong>calendar/meeting scheduler</strong>. They are your next two type-alongs, and they are chosen deliberately — each one is a combination of moves you already own.</p>",
        "<p>One problem from your original list still has not made this guide: the <strong>calendar/meeting scheduler</strong>. It is your next type-along, and it is chosen deliberately — it is a combination of moves you already own.</p>",
        1,
    ),
    (
        "<p>Ride sharing is elevator dispatch with money attached. Match riders to drivers — the dispatcher, now with positions on a map instead of a shaft. Price the trip — Strategy again, with a surge multiplier. Notify both sides — Observer. Nothing in it is new. That is the point — you will feel the patterns transfer instead of reading about transfer.</p>",
        "<p>Ride sharing was on that list too, and it became Chapter 12. Think back to typing it. The dispatcher came from the elevator, now with positions on a map instead of a shaft. The surge pricing was Strategy again. The notifications were Observer. The one genuinely new idea was the compare-and-set claim. That is what transfer feels like from the inside.</p>",
        1,
    ),
    ("<p>After those two, the road forks upward", "<p>After that, the road forks upward", 1),
    (
        "Harder versions of the same ideas, at a scale where the network can fail.</p>",
        "Harder versions of the same ideas, at a scale where the network can fail. You have already had a preview. From Chapter 8 on, nearly every follow-up section asks what changes with several servers behind a load balancer, and the answer is usually the same move, rewritten: a Lua script, a conditional <code>UPDATE</code>, a unique constraint.</p>",
        1,
    ),
    (
        "<p>One practical suggestion for the fifteen questions above:",
        "<p>One practical suggestion for the twenty-three questions above:",
        1,
    ),
]


def _toc(fragment: str) -> str:
    """TOC <li> entries for the fragment's h1/h2 headings (h2 nested under its h1)."""
    out, open_h1 = [], False
    for m in re.finditer(r'<h([12]) id="([^"]+)">(.*?)</h\1>', fragment):
        level, hid, inner = m.groups()
        link = f'<a href="#{hid}" id="toc-{hid}">{inner}</a>'
        if level == "1":
            if open_h1:
                out.append("</ul></li>")
            out.append(f"<li>{link} <ul>")
            open_h1 = True
        else:
            out.append(f"<li>{link}</li>")
    if open_h1:
        out.append("</ul></li>")
    return "\n".join(out)


def apply(text: str) -> str:
    fragments = sorted(CHAPTERS.glob("*.html"))
    if not fragments:
        return text
    new_chapters = sum(1 for f in fragments if not f.name.startswith("06v2"))
    outro_n = 7 + new_chapters
    new_id, new_title = f"chapter-{outro_n}-what-repeats", f"Chapter {outro_n}: What Repeats"
    body = "\n".join(f.read_text().strip() for f in fragments)

    # Body: fragments go just before the outro heading, which is renumbered.
    old_h1 = f'<h1 id="{OUTRO_OLD[0]}">{OUTRO_OLD[1]}</h1>'
    assert text.count(old_h1) == 1, "outro heading not found exactly once"
    text = text.replace(old_h1, f'{body}\n<h1 id="{new_id}">{new_title}</h1>')

    # TOC: v2 entries nest inside Chapter 6's list; new chapters go before the outro entry.
    old_toc = f'<li><a href="#{OUTRO_OLD[0]}" id="toc-{OUTRO_OLD[0]}">{OUTRO_OLD[1]}</a>'
    assert text.count(old_toc) == 1, "outro TOC entry not found exactly once"
    chapter_toc = "\n".join(_toc(f.read_text()) for f in fragments if not f.name.startswith("06v2"))
    text = text.replace(old_toc, f'{chapter_toc}\n<li><a href="#{new_id}" id="toc-{new_id}">{new_title}</a>')
    # Version 2 sorts first (06v2 < 07), so in the body it already ends Chapter 6.
    # In the TOC its h2 entries go inside Chapter 6's list: before the "</ul></li>" that
    # closes Chapter 6, i.e. the last one before the next top-level entry.
    for f in fragments:
        if f.name.startswith("06v2"):
            ch6 = text.index('id="toc-chapter-6-car-rental-system"')
            nxt = text.index('<li><a href="#chapter-', ch6 + 1)
            close = text.rindex("</ul>", ch6, nxt)
            text = text[:close] + _toc(f.read_text()) + "\n" + text[close:]

    # Any remaining links to the old outro id.
    text = text.replace(f'href="#{OUTRO_OLD[0]}"', f'href="#{new_id}"')

    for old, new, count in TEXT_EDITS:
        assert text.count(old) == count, f"expected {count} of: {old[:70]}"
        text = text.replace(old, new)
    return text
