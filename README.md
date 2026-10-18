# mdfsrun

**One Markdown file = one runnable project.** Think of it as [PEP 723](https://peps.python.org/pep-0723/)
grown up to several files and a task runner:

- the **front matter** is a [Taskfile](https://taskfile.dev/),
- the **body** is documentation plus fenced code blocks marked with a file path,
- the code blocks are extracted into a work directory with
  [Entangled](https://entangled.github.io/), and the tasks run there.

All you need is [uv](https://docs.astral.sh/uv/). Task, Entangled and Python itself are fetched by uv.

````markdown
---
tasks:
  default:
    cmds:
      - uv run main.py
  test:
    cmds:
      - uv run --with pytest python -m pytest -q
---

# Hello

```python {.python file=main.py}
# /// script
# dependencies = ["rich"]
# ///
from pkg.core import greet
greet("world")
```

```python {.python file=pkg/core.py}
from rich import print

def greet(name: str) -> None:
    print(f"[bold green]Hello, {name}![/bold green]")
```

```python {.python file=pkg/__init__.py}
```
````

```sh
uvx mdfsrun app.md          # runs the "default" task
uvx mdfsrun app.md test     # runs the "test" task
```

## Usage

```
mdfsrun [--rm] FILE.md [TASK ...] [VAR=VALUE ...] [task options ...]
```

Everything after the `.md` file is passed to `task` unchanged, so `uvx mdfsrun app.md --list-all`
works too. Options of mdfsrun itself go before the `.md` file.

| Option / variable | Meaning |
| --- | --- |
| `--rm` / `MDFSRUN_RM=1` | delete the work directory after the run |
| `MDFSRUN_DIR` | use this work directory instead of `.mdfsrun/<name>/` next to the `.md` |

## How it works

1. The `.md` is copied into the work directory (`.mdfsrun/<name>/` next to the `.md` by default)
   and Entangled extracts the code blocks there. The work directory gets a `.gitignore`
   containing `*`, so Git ignores it.
2. The front matter is passed to `task` as the Taskfile, and the tasks run in the work directory.
   `version: '3'` is added if the front matter has no `version`.

Tasks receive these environment variables. Use them in templates (`{{.MD_DIR}}`) or in
commands (`$MD_DIR`):

| Variable | Value |
| --- | --- |
| `MD` | absolute path of the `.md` |
| `MD_DIR` | absolute path of the directory containing the `.md` |
| `OUT` | absolute path of the work directory |

For example, to load a `.env` that sits next to the `.md`:

```yaml
dotenv: ["{{.MD_DIR}}/.env"]
```

The work directory is kept after the run, but it is rebuilt from the `.md` every time:
files edited there are reset, and files whose block was removed from the `.md` are deleted.
Files created by the tasks themselves (such as `.venv`) are left alone.
mdfsrun refuses to use (or delete) an existing non-empty directory it did not create.

## Code blocks

A code block is extracted when its attributes contain `file=`. Both forms work:

````markdown
```python {.python file=main.py}
```

``` {.python file=main.py}
```
````

Blocks without `{...}` (```` ```sh ````, ```` ```python ````) are plain documentation.
Only fences of exactly three backticks are recognized, so a Markdown file that itself contains
`file=` blocks cannot be embedded.

## Using Entangled locally

The `.md` is the single source of truth: edit the `.md`, not the files in the work directory.
Writing changes back from the work directory (`entangled stitch`) is not supported; the files
there carry no annotations.

You can still run Entangled yourself next to the `.md`, including `entangled stitch`. Put this
`entangled.toml` next to the `.md`:

```toml
version = "2.0"
ignore_list = [".mdfsrun/**/*"]

[markers]
open  = '^(?P<indent>\s*)```[^\s{`]*\s*\{(?P<properties>[^{}]*)\}\s*$'
close = '^(?P<indent>\s*)```\s*$'
```

- `[markers]` makes Entangled accept the ```` ```python {.python file=...} ```` form
  (the same config as [mdfs](https://github.com/uniras/mdfs)).
- `ignore_list` keeps Entangled away from `.md` files that a run may have extracted into the
  work directory. It is not needed if you use `--rm` or a `MDFSRUN_DIR` outside the project.

mdfsrun always runs what is in the `.md`; changes you have not stitched back are not used.

## Notes

- Requires Python 3.13 or later (a requirement of Entangled 2.4.x); uv installs it if needed.
- The first run downloads Task, Entangled and the dependencies of your code; later runs use
  uv's cache.
- Running an `.md` file runs whatever its front matter and code say. Only run files you trust.

## License

[MIT](LICENSE)
