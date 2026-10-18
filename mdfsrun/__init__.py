# /// script
# requires-python = ">=3.13"
# dependencies = ["go-task-bin", "entangled-cli"]
# ///
"""mdfsrun: tangle a front-matter Markdown file with Entangled and run its front matter as a Taskfile.

Usage:
    mdfsrun [--rm] FILE.md [TASK ...] [VAR=VALUE ...] [task options ...]

- Code blocks in the body (```python {.python file=main.py} and the like) are extracted
  into a work directory.
- The front matter is passed as-is to `task -t -` as a Taskfile and run in the work directory.
- The work directory defaults to ".mdfsrun/<name of the .md>/" next to the .md.
  Set MDFSRUN_DIR to use another location.
- The work directory is kept after the run (it is rebuilt from the .md on the next run).
  Pass --rm (or set MDFSRUN_RM=1) to delete it after the run.
- Tasks receive these environment variables (usable in templates as {{.MD}} and in
  commands as $MD):
    MD      absolute path of the source .md
    MD_DIR  absolute path of the directory containing the .md
            (e.g. dotenv: ["{{.MD_DIR}}/.env"])
    OUT     absolute path of the work directory
- Writing changes back from extracted files (stitch) is not supported.
  The .md is always the single source of truth.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Never

__version__ = "0.1.3"

# Not a .md name, so the user's own Entangled (watch_list "**/*.md") never picks the copy up.
SOURCE_NAME = "source.mdfsrun"
# [markers] is the same as in mdfs (the entangled.toml bundled in the riafeed/mdfs image):
# also accept a plain language name between ``` and {...}, as in ```python {.python file=...}
# (Entangled itself still takes the language from the .python class).
ENTANGLED_TOML = r"""version = "2.0"
watch_list = ["source.mdfsrun"]

[markers]
open  = '^(?P<indent>\s*)```[^\s{`]*\s*\{(?P<properties>[^{}]*)\}\s*$'
close = '^(?P<indent>\s*)```\s*$'
"""


def fail(msg: str, code: int = 1) -> Never:
    print(f"mdfsrun: {msg}", file=sys.stderr)
    sys.exit(code)


def find_tool(name: str) -> str:
    """Prefer the executable installed in the same environment (the uvx / uv run environment)."""
    bindir = Path(sys.executable).parent
    found = shutil.which(name, path=str(bindir)) or shutil.which(name)
    if found is None:
        fail(f"'{name}' not found")
    return found


def split_frontmatter(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        fail("no front matter (YAML between --- lines) at the top of the file")
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i]) + "\n", "\n".join(lines[i + 1 :]) + "\n"
    fail("closing --- of the front matter not found")


def ensure_version(fm: str) -> str:
    """Add the version that Task requires if it is missing.

    Everything else is left untouched: Task ignores keys it does not know.
    """
    if re.search(r"^version\s*:", fm, re.MULTILINE):
        return fm
    return "version: '3'\n" + fm


# Matches the open marker in ENTANGLED_TOML (with or without a language name).
FENCE_OPEN = re.compile(r"^\s*(```)[^\s{`]*\s*\{[^{}]*\bfile=[^{}]*\}\s*$")


def pad_empty_blocks(text: str) -> str:
    """Put one blank line into empty file= blocks.

    Entangled 2.4.3 crashes with an internal error when it tangles an empty block with
    --annotate naked (which easily happens with an empty __init__.py).
    """
    lines = text.splitlines()
    out: list[str] = []
    for i, line in enumerate(lines):
        out.append(line)
        m = FENCE_OPEN.match(line)
        if m and i + 1 < len(lines) and lines[i + 1].strip() == m.group(1):
            out.append("")
    return "\n".join(out) + "\n"


def clear_previous(out: Path) -> None:
    """Delete the files from the previous tangle and Entangled's state, to start from scratch.

    Entangled does not rewrite a file whose block did not change in the .md, so a file edited
    by hand in the work directory would survive; files whose block was removed from the .md
    would also be left behind. Files created by tasks (.venv and so on) are not touched.
    """
    for rel in read_targets(out):
        p = out / rel
        if p.is_file():
            p.unlink()
        parent = p.parent
        while parent != out and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    shutil.rmtree(out / ".entangled", ignore_errors=True)


def read_targets(out: Path) -> set[str]:
    db = out / ".entangled" / "filedb.json"
    try:
        return set(json.loads(db.read_text(encoding="utf-8")).get("targets", []))
    except (OSError, ValueError):
        return set()


def is_ours(out: Path) -> bool:
    """Whether the work directory was created by mdfsrun (and so is safe to delete)."""
    return (out / SOURCE_NAME).is_file()


def check_out_dir(out: Path) -> None:
    """Refuse to tangle into (and later delete) an unrelated directory."""
    if out.exists() and not out.is_dir():
        fail(f"a file exists where the work directory should be: {out}")
    if out.is_dir() and any(out.iterdir()) and not is_ours(out):
        fail(f"the work directory is an existing directory not created by mdfsrun: {out}")


def remove_out_dir(out: Path) -> None:
    def onexc(func, path, exc):  # read-only files (Windows)
        try:
            os.chmod(path, 0o700)
            func(path)
        except OSError:
            pass

    if not is_ours(out):
        return
    shutil.rmtree(out, onexc=onexc)
    if out.exists():
        print(f"mdfsrun: could not completely delete the work directory: {out}", file=sys.stderr)
        return
    # At the default location (.mdfsrun/<name>), also remove .mdfsrun once it is empty.
    parent = out.parent
    if parent.name == ".mdfsrun":
        try:
            parent.rmdir()
        except OSError:
            pass


def tangle(md: Path, body_source: str, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / ".gitignore").write_text("*\n", encoding="utf-8")
    (out / "entangled.toml").write_text(ENTANGLED_TOML, encoding="utf-8")
    (out / SOURCE_NAME).write_text(pad_empty_blocks(body_source), encoding="utf-8")

    clear_previous(out)
    # naked: no annotation comments, so nothing can be stitched back from the work directory
    # force: write the content of the .md even if Entangled reports conflicts
    r = subprocess.run(
        [find_tool("entangled"), "tangle", "--annotate", "naked", "--force"],
        cwd=out,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        fail(f"failed to tangle {md.name}", r.returncode)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    rm = os.environ.get("MDFSRUN_RM", "") not in ("", "0")

    # Only options before the .md belong to mdfsrun; everything after it goes to task.
    while args and args[0].startswith("-"):
        opt = args.pop(0)
        if opt in ("-h", "--help"):
            print(__doc__.strip())
            return 0
        if opt in ("-V", "--version"):
            print(f"mdfsrun {__version__}")
            return 0
        if opt == "--rm":
            rm = True
        else:
            fail(f"unknown option: {opt} (put task options after the .md file)")
    if not args:
        print(__doc__.strip())
        return 0

    md = Path(args[0]).resolve()
    if not md.is_file():
        fail(f"file not found: {args[0]}")

    text = md.read_text(encoding="utf-8-sig")  # a BOM is fine
    fm, _ = split_frontmatter(text)

    out_env = os.environ.get("MDFSRUN_DIR")
    out = Path(out_env).resolve() if out_env else md.parent / ".mdfsrun" / md.stem
    check_out_dir(out)

    # Passed as environment variables: command-line variables are not visible to
    # top-level keys such as dotenv:.
    env = {**os.environ, "MD": str(md), "MD_DIR": str(md.parent), "OUT": str(out)}
    try:
        # Entangled ignores the YAML front matter, so the whole .md can be passed as-is.
        tangle(md, text, out)
        cmd = [find_tool("task"), "-t", "-", *args[1:]]
        return subprocess.run(cmd, cwd=out, env=env, input=ensure_version(fm).encode("utf-8")).returncode
    except KeyboardInterrupt:
        return 130
    finally:
        if rm:
            remove_out_dir(out)


if __name__ == "__main__":
    sys.exit(main())
