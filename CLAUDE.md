# Inspection Station MCP

An MCP server (Model Context Protocol, the standard way to plug tools, data and devices
into an AI application such as Claude Code) that lets the AI take photos with a camera,
look closer at part of a photo, and record inspection results, and a desktop app that
uses it. The safety rules are enforced in the server, not in the prompt.

Two separate programs in one repository, each with its own `pyproject.toml`, environment,
tests and `CLAUDE.md`:

- `server/`: the MCP server `inspection-server` (camera, tools, rules, audit log), its demo
  login server and certificate script. Read `server/CLAUDE.md` before changing it.
- `client/`: the desktop app `inspection-client`. Read `client/CLAUDE.md` before changing it.

The client never imports the server's code: they share only the interface listed in
`client/CLAUDE.md` (the MCP tools and a few things beside them), and the client's tests
run against `client/tests/stand_in_server.py` in an environment without the server, so
the server could be rewritten in another language without changing the client. A change
to that interface changes both folders in one commit.

Shared: `docs/setup.svg` (the figure in the main README), `LICENSE` and the CI workflow
`.github/workflows/tests.yml` (both test suites on Linux, Windows and macOS with Python
3.13 and 3.14, ruff and mypy per folder, and the client's contract test against the real
server). The main `README.md` tells the story (quick start, the AI's answers, the rules,
the audit trail); `server/README.md` and `client/README.md` are references for installing
and running each.

Each fact is written in one README and linked from the others, so a change is made once:

- Main README: the quick start (one computer, the secret key, Linux and Windows, the app and
  Claude Code, answering a fail in Claude Code), the rules (roles, the time limit for a
  fail question), the guarantees, the audit trail, the costs and the model comparison, the
  size of the code and the number of tests.
- `server/README.md`: everything else about the server: what it prints at start, Claude
  Code starting it, two computers, logins and the demo users, the window, the live view,
  cameras and photo sizes, settings, Windows details (`$env:` settings, firewall, `scp`).
- `client/README.md`: everything else about the app: installing, the Claude API key, what
  the window shows, the app on another computer and with logins, its Windows details.

When a sentence would repeat one of these, link to it instead.

## What else a change touches

Some facts live both in the code and in a README, and no test notices when only one side
changes:

- The server's start text, the `claude mcp add` line it prints (`next_steps` in
  `server/inspection_server/server.py`, checked in `server/tests/test_choice.py`) and the
  camera menu are quoted in the main and server READMEs: change the code, its test and
  every quote together.
- A tool added, removed or renamed: the main README's tool table and every "three tools",
  the stand-in server, and the list in `client/CLAUDE.md`.
- A field of the inspection record: the main README's audit trail (the example record and
  its list of fields).
- Code or tests: the counts in the main README's "Reading the code" (what they count is
  said there); a test renamed: its name in both `docs/test-quality.md` files.
- The look of the app's window or fail dialog: the screenshots in `client/docs/`.
- A model: see `client/CLAUDE.md`, and the main README's model comparison and costs.

## Rules for both programs

- The simplest working version first; no features nobody asked for.
- US English spelling.
- Python 3.13+: both 3.13 and 3.14 are tested by hand on Linux and Windows. Nobody has run
  the programs on a Mac; the CI workflow runs the test suites there.
- Each program in a virtual environment of its own, `.venv` in its folder as the READMEs
  make it, never the system Python. Each shell command starts afresh, so an activated
  environment does not carry over: call its Python by its path (`.venv/bin/python`, on
  Windows `.venv\Scripts\python`). Run its tests, ruff and mypy from inside its folder,
  never from the top folder: the two folders have separate environments and separate
  tests.
- Before committing, in each folder changed: `.venv/bin/python -m pytest -q`, then
  `.venv/bin/python -m ruff check . && .venv/bin/python -m mypy`. After a change to the
  interface the two programs share, both folders, and the client's contract test
  (`client/tests/test_contract.py`) in a throwaway environment with both programs, as the
  CI's contract job does. From the top folder: `python3 -m venv /tmp/contract`, then
  `/tmp/contract/bin/pip install -e server -e "client[test]"`, then in `client`:
  `/tmp/contract/bin/python -m pytest -q -ra tests/test_contract.py`. It must pass, not be
  skipped. Never install the server into the client's own environment.
- The tests guard the rules. Never loosen, skip or delete a test to make a change pass:
  say which test failed and why, and ask. A bug fix comes with a test that fails without
  the fix: plant the bug by hand and see the test fail for the right reason, as in
  `server/docs/test-quality.md`.
- Ask me before changing a rule a change must not break (`server/CLAUDE.md`) or a test
  that checks one, changing the interface the two programs share, adding a dependency, or
  rewriting the history. Never open or print the real key files
  (`~/.config/inspection-server/api-key`, `~/.config/anthropic/api-key`) or anything in
  `server/certs/`; the tests make their own keys.
- Add a dependency to `pyproject.toml` in the same step as installing it, as a range from
  the tested version to below the next major (such as `mcp>=2.3,<3`); only ruff and mypy,
  in the `dev` extra, are pinned exactly. When a dependency changes, make that folder's
  `constraints.txt` (the exact tested versions, which the CI workflow installs on every
  push) again as its header says, and keep the header; in the server's file, also keep the
  hand-written `cv2-enumerate-cameras` line, which a freeze on Linux cannot produce.
  `git diff` should then show only changed versions.

## Writing the READMEs

- Complete commands, in the order they are run, each saying on which computer and in
  which terminal. Each step is written for Linux (bash) and for Windows (PowerShell):
  change both.
- Headings say what the section holds. Other READMEs link to them: after renaming one,
  update the Contents list and search all three READMEs for the old anchor.
- One line per paragraph; every code block marked with its language (`bash`,
  `powershell`, `text` or `json`).
- Nobody types a secret: keys go into files, and commands read them from there.
- After changing steps, commit them, then follow them word for word in a fresh clone of
  that commit before pushing. On Linux, set `HOME` to an empty folder, so the key file and
  the saved camera choice start fresh and the real ones are never touched. List each step
  you could not follow (Windows, two computers, logins, a real camera); never report it as
  followed.

## Commits

- A subject line of at most 72 characters, and a body saying why.
- No references a stranger cannot follow, such as private notes or the steps of a plan
  kept elsewhere.
