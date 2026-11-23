# contracts_py

Generated from `../../../contracts/avro-bundled/*.avsc` and `contracts/topics.yaml` by `contracts_codegen.py`. The generated code is **not committed** (`src/contracts_py/_generated/` is git-ignored).

- A hatchling build hook (`hatch_build.py`) runs the generator on every build or editable install. `tool.uv.cache-keys` makes `uv sync` rebuild whenever a contract file changes.
- By hand: `uv run python libs/contracts_py/contracts_codegen.py`. In CI: `... --check` (fails if the tree is stale). Set `EDA_CONTRACTS_DIR` to build outside the repository layout.
- The output is the bundled schemas verbatim as package data (`contracts_py.schema_str(name)`), frozen dataclasses per record with `to_avro()`/`from_avro()` (enums decode unknown symbols to `UNKNOWN`), and `contracts_py.topics` (topics, keys, message → topic, consumer groups, retry policy).
- `tests/` holds the golden-message suite: every `.bin` decodes to its `.json`, typed round trips are byte-identical, and the registry wire format is checked.
