# Contributing to Atlas

Atlas helps people recognize a messy folder and make quick Keep / Move / Trash decisions.
Small improvements to that journey are welcome. Avoid expanding it into a full file manager.

## Source map

```text
launch.py                 Local entry point
app/                      Read-only scanner, relations, local server, safe executor
ui/                       Editable HTML, CSS and browser JavaScript
scripts/build.py          Compile the single-page app and refresh private snapshot pages
scripts/agent_context.py  Export metadata for an external agent
tests/                    Isolated filesystem fixtures and browser-model checks
skills/atlas-cleanup/     Agent guidance for proposal-only cleanup analysis
docs/                     AI workflow, release notes and synthetic screenshots
.atlas/                   Private runtime data (ignored; never publish)
```

`app/atlas-template.html` is generated and committed so clones launch without a build.
Edit `ui/`, then rebuild. Use `--template-only` to leave existing local snapshot pages
alone, or omit it to refresh their interface while retaining scans and previews.

```sh
python3 scripts/build.py --template-only
node --check work/atlas.js
node tests/cleanup.cjs
python3 -m unittest discover -s tests
```

Python 3.9+ and Node 20+ are sufficient for these checks. No npm install is needed.
The JavaScript checks generate a synthetic scan; they do not depend on `.atlas/` or a
real Downloads folder. Filesystem tests create disposable fixtures, not personal cleanup actions.

## Changes worth reviewing

Explain the user problem, the resulting behavior, and how you checked it. For UI work,
include a screenshot with synthetic files. Keep the build output current and the browser
source-root decision keys compatible. New measurements need honest units and denominators.

Preserve the core guarantees: folders stay intact, marking is planning, execution is
explicit and content-checked, overwrites are refused, Trash is recoverable, and undo
journals survive interruptions. Never test an action on a user's pending cleanup plan.

Before opening a PR, check that no `.atlas/`, personal screenshots, exports, credentials
or private paths are included. See [SECURITY.md](SECURITY.md) for sensitive reports and
[docs/releasing.md](docs/releasing.md) for the initial publishing checklist.
