"""Fail if a release archive includes runtime state, private files or unexpected assets."""
from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath


def check(directory: Path) -> None:
    wheels, sources = list(directory.glob("*.whl")), list(directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise SystemExit("expected exactly one wheel and one source archive")
    with zipfile.ZipFile(wheels[0]) as archive:
        names = archive.namelist()
        for name in names:
            path = PurePosixPath(name)
            allowed = (path.parts[0] == "wqo" and path.suffix == ".py") or path.parts[0].endswith(".dist-info")
            if not allowed or ".." in path.parts or path.is_absolute():
                raise SystemExit(f"unexpected wheel entry: {name}")
        entry = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
        if "wqo = wqo.__main__:main" not in archive.read(entry).decode():
            raise SystemExit("missing CLI entry point")
        assert "wqo/state.py" in names and "wqo/privacy.py" in names
    allowed_root = {".gitignore", "pyproject.toml", "PKG-INFO", "LICENSE", "README.md", "requirements.txt", "requirements-dev.txt"}
    allowed_docs = {"pypi.md", "installation.md", "safety.md"}
    with tarfile.open(sources[0]) as archive:
        for member in archive.getmembers():
            if member.isdir():
                continue
            path = PurePosixPath(member.name)
            parts = path.parts[1:]
            allowed = len(parts) == 1 and parts[0] in allowed_root
            allowed |= len(parts) >= 2 and parts[0] in {"wqo", "tests"} and path.suffix == ".py"
            allowed |= len(parts) == 2 and parts[0] == "docs" and parts[1] in allowed_docs
            allowed |= len(parts) == 2 and parts[0] == "scripts" and parts[1] in {"check_dist.py", "smoke_installed.py"}
            if not allowed or not member.isfile() or ".." in path.parts or path.is_absolute():
                raise SystemExit(f"unexpected source entry: {member.name}")
    print("Release archive contents and CLI entry point verified.")


if __name__ == "__main__":
    check(Path(sys.argv[1] if len(sys.argv) > 1 else "dist"))
