# Brief: implementing eda-commerce (Python and Java)

The design package in `capstones/eda-commerce/` is finished: `README.md` (10-day plan with acceptance
criteria), `docs/architecture.md`, `docs/adr/`, `docs/implementation-guide.md`, `contracts/`, `infra/`.
Your job is to write one language's implementation so it is a **real-world template**, not a tutorial:
production-grade structure, error handling, config, observability and tests, that an engineer can
fork for an enterprise system.

## Rules

1. Read `README.md`, `docs/implementation-guide.md` (it is the build contract; §11 is the definition of
   done), `docs/architecture.md` and the ADRs that touch your services before writing code.
2. Everything on the guide's "fixed" list must match the contracts exactly: topics, keys, schemas,
   subjects, headers, HTTP APIs, shared tables, group ids, ports, env vars, metric names.
   Never edit `contracts/`, `infra/` or `docs/` (except your own `impl-*/` files). If a contract looks
   wrong, note it in your report instead.
3. Hexagonal layout per guide §3. The shared `edacommon` library (consumer runtime with inbox/retry/DLQ,
   outbox writer, saga kit, claim check, OTel propagation, idempotency keys) is written once and used by
   every service.
4. **Trade-offs in the code base**: each service gets a `README.md` with what it owns, its topics and APIs,
   the patterns it uses, and a "Decisions and trade-offs" section (why this pattern, what it buys, what it
   costs, which ADR). Put a short comment in code only where a choice is non-obvious, pointing to the ADR.
5. Tests: unit tests for domain and saga transitions (pure, fast); adapter/integration tests with
   Testcontainers written properly even if Docker is unavailable here (mark them so they skip cleanly).
   Golden-fixture tests: decode `contracts/examples/*.bin` and re-encode byte-for-byte.
   Run everything you can run here and report real results. Don't fake passing tests.
6. Use only the stacks in guide §9 (Python) / §10 (Java). Pin dependency versions.
7. Work only inside your `impl-python/` or `impl-java/` folder plus a scratch folder. No git.
8. Write files as you go so work survives interruptions. If resumed, check what exists before continuing.

Report: what you built, what you ran and its real results, what is unfinished, and any contract issues.
