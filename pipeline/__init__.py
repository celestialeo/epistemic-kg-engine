"""Terminal compatibility package; implementation lives in 261273237.ipynb.

Only implementation/resource cells are loaded. Notebook experiments never run on import.
"""
import json as _json
from pathlib import Path as _Path
import sys as _sys

if "_submission_runtime" not in _sys.modules:
    _root = _Path(__file__).resolve().parents[1]
    _notebook = _root / "261273237.ipynb"
    if not _notebook.is_file():
        # Renaming to an actual student ID does not require keeping a second copy.
        _candidates = list(_root.glob("*.ipynb"))
        if len(_candidates) != 1:
            raise ImportError("Keep the submission notebook beside run_pipeline.py")
        _notebook = _candidates[0]
    _cells = _json.loads(_notebook.read_text(encoding="utf-8"))["cells"]
    _bootstraps = [c for c in _cells if "submission-bootstrap" in c.get("metadata", {}).get("tags", [])]
    if len(_bootstraps) != 1:
        raise ImportError("Notebook must contain exactly one submission-bootstrap cell")
    _namespace = {"PROJECT_ROOT": _root}
    exec(compile("".join(_bootstraps[0]["source"]), str(_notebook) + ":bootstrap", "exec"), _namespace)
    _runtime = _sys.modules["_submission_runtime"]
    for _cell in _cells:
        _metadata = _cell.get("metadata", {})
        if "module" in _metadata or "asset" in _metadata:
            _header, _source = "".join(_cell["source"]).split("\n", 1)
            if "module" in _metadata:
                _runtime.register_module(_metadata["module"], _source)
            else:
                _runtime.register_asset(_metadata["asset"], _source)
