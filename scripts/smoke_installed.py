"""Run with a clean installed environment's Python, outside the source checkout."""
from __future__ import annotations

import importlib.metadata
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import wqo
from wqo.mining import templates

repo = Path(sys.argv[1]).resolve()
assert not Path(wqo.__file__).resolve().is_relative_to(repo), "imported checkout instead of installed package"
assert importlib.metadata.version("wqo") == wqo.__version__
assert templates.TEMPLATES, "built-in templates missing from distribution"
assert not any(d.metadata["Name"].lower() == "pytest" for d in importlib.metadata.distributions())
command = Path(sys.executable).parent / "wqo"
with tempfile.TemporaryDirectory(prefix="wqo-installed-") as directory:
    root = Path(directory).resolve()
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.update(WQO_DATA_DIR=str(root / "state"), WQO_SESSION=str(root / "no-session.json"),
               WQO_CREDENTIALS=str(root / "no-credentials.json"))
    def run(*args):
        return subprocess.run(args, env=env, cwd=root, capture_output=True, text=True, check=True)
    assert run(str(command), "--version").stdout.strip() == f"wqo {wqo.__version__}"
    run(str(command), "--help")
    run(str(command), "sim", "run", "--help")
    run(str(command), "account", "snapshot", "--help")
    missing_auth = subprocess.run([str(command), "account", "snapshot"],
                                  env=env, cwd=root, capture_output=True, text=True)
    assert missing_auth.returncode == 2, missing_auth.stderr
    assert not (root / "ACCOUNT.local.md").exists()
    state = json.loads(run(str(command), "state").stdout)
    assert state["data_dir"] == str(root / "state")
    assert not (root / "state").exists()
    run(sys.executable, "-m", "wqo", "--version")
print("Installed CLI, module, templates, version and state paths verified outside checkout.")
