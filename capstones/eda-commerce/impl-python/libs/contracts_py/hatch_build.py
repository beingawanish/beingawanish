"""Hatchling build hook: regenerate contracts_py from contracts/ on every build or editable install.

This is what makes "generated code is never committed" practical (guide §2): ``uv sync`` builds the
editable package, the hook runs the generator, and the generated tree appears under
``src/contracts_py/_generated``. ``tool.uv.cache-keys`` in pyproject.toml makes uv rebuild (and so
regenerate) whenever a bundled schema or topics.yaml changes.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class ContractsCodegenHook(BuildHookInterface):  # type: ignore[type-arg]
    PLUGIN_NAME = "contracts-codegen"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        path = Path(self.root) / "contracts_codegen.py"
        spec = importlib.util.spec_from_file_location("contracts_codegen", path)
        assert spec
        assert spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules["contracts_codegen"] = module  # dataclasses need the module registered
        spec.loader.exec_module(module)
        module.write(module.generate(module.contracts_dir()))
        # The generated tree is git-ignored, so tell hatchling to ship it anyway.
        build_data.setdefault("artifacts", []).append("src/contracts_py/_generated/**")
