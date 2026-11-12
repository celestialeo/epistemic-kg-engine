"""Execute the submission in a fresh kernel with no local project modules or data.

Usage: python tools/validate_submission.py [--notebook 261273237.ipynb]
Successful execution replaces outputs in the same notebook; no duplicate is created.
"""
import argparse
from pathlib import Path
import os
import subprocess
import sys
import tempfile

import nbformat
from nbclient import NotebookClient
from jupyter_client import KernelManager


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notebook", type=Path, default=Path(__file__).resolve().parents[1] / "261273237.ipynb")
    args = parser.parse_args()
    path = args.notebook.resolve()
    notebook = nbformat.read(path, as_version=4)
    nbformat.validate(notebook)
    controls = [c for c in notebook.cells if "execution-control" in c.metadata.get("tags", [])]
    if len(controls) != 1 or 'MODE = "offline"' not in controls[0].source or 'SAVED_RUN = None' not in controls[0].source:
        raise ValueError("Restore default offline controls before automated fresh-kernel validation")
    root = path.parent
    for command in (["run_pipeline.py"], *[["-m", name] for name in (
            "pipeline.explorer", "pipeline.professor",
            "pipeline.replay_background", "pipeline.evaluate_saved_run")]):
        result = subprocess.run([sys.executable, *command, "--help"], cwd=root,
                                capture_output=True, text=True, timeout=30)
        if result.returncode != 0 or "usage:" not in result.stdout:
            raise RuntimeError(f"CLI help failed: {command}\n{result.stderr}")
        print("CLI help verified:", " ".join(command))
    with tempfile.TemporaryDirectory(prefix="ecse679-kernel-") as directory:
        workspace = Path(directory)
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env["JUPYTER_RUNTIME_DIR"] = str(workspace / "jupyter-runtime")
        manager = KernelManager(kernel_name="python3")
        manager.kernel_spec.argv[0] = sys.executable
        client = NotebookClient(notebook, km=manager, timeout=120,
                                resources={"metadata": {"path": directory}})
        client.execute(cwd=directory, env=env, cleanup_kc=True)
        if list(workspace.rglob("*.py")):
            raise AssertionError("Standalone execution unexpectedly materialized Python source files")
    nbformat.validate(notebook)
    errors = [output for cell in notebook.cells if cell.cell_type == "code"
              for output in cell.outputs if output.output_type == "error"]
    if errors:
        raise AssertionError(errors)
    nbformat.write(notebook, path)
    print(f"Fresh-kernel standalone execution passed; outputs saved in {path.name}.")


if __name__ == "__main__":
    main()
