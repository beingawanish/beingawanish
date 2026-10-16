"""Make the chapter packages under code/ importable when the suite runs from the guide root."""
import pathlib
import sys

_CODE = pathlib.Path(__file__).resolve().parent.parent / "code"
if str(_CODE) not in sys.path:
    sys.path.insert(0, str(_CODE))
