# MCP inspection camera: the desktop app

A window where Claude inspects parts with a camera. You type a question, such as "Is the
tray complete?". Claude takes a photo, looks closer where it needs to, answers, and can
record the result. The window shows each step with its pictures, and the camera's live
picture next to it. When Claude finds a part bad, a dialog asks you first, with the
photo; no part is marked as failed without your yes.

A self-built demonstration of connecting a device to AI models through the
[Model Context Protocol](https://modelcontextprotocol.io) (MCP), the standard way to
plug tools, data and devices into AI applications. The camera sits behind an MCP server,
in the companion repository `mcp-server`; this repository holds the programs that use
it: this app, and a ready-made setup for Claude Code. The app is small on purpose: about
640 lines of Python, using the official MCP and Anthropic libraries.

Author: [Ali Baharev](https://baharev.info/)

## What an inspection station is

A factory makes parts: a filled box, a tray of tools, a pack of food, a gauge. Before a
part moves on to the next machine or to the customer, someone checks it. That check is
the inspection, and the place where it happens is the inspection station: a table or a
spot on the conveyor belt, with a camera and good lighting above it, and usually a screen
for a worker, the operator.

Each part gets one of three outcomes:

- **Pass**: the part is fine and moves on.
- **Fail**: the part is bad (torn, a tool missing, a reading out of range). It is taken
  off the line, to be scrapped or repaired. A fail costs money, because a part is thrown
  away or reworked.
- **Unsure**: the check cannot tell. The part is put aside for a person to look at.

Every outcome is also written down, with the part's label (such as `tray-07`), the time,
the photo and what was seen. That list is the inspection log. Factories keep it because
customers and quality rules demand proof that every part was checked, and so that bad
parts can be traced back later.

Simple checks are usually done by fixed camera software ("is there a hole at this
spot?"). This demo is about the checks such software cannot do, the open questions: "is
anything missing from this tray?", "does any of these watches show a different time?"

In this demo, each photo stands for one part, and there is no production line: recording
an outcome means writing one line to the inspection log, and nothing is moved or
scrapped. Claude looks at the photo and decides pass, fail or unsure. A pass or an unsure
is written down straight away. A fail is not: wrongly scrapping a good part costs money,
so the camera server asks a person first, and this app shows that question as a dialog,
with the photo. If you agree, the part is marked as failed. If you say no, or close the
dialog without answering, the part is marked as unsure, to be put aside for a person to
look at, and the log says that Claude called it a fail and what your answer was. Every
part checked ends up in the log.

![The setup. Left: the inspection station, where no AI runs: a camera above a conveyor belt, and the station computer with the MCP server, which keeps the inspection log. Right: the operator's computer with the desktop app, which talks to the MCP server over the network and to Claude, the AI, on the internet.](docs/setup.svg)

The station computer, the one the camera is plugged into, and the operator's computer
can also be one and the same, and the camera a USB webcam, or the fake camera, which
serves stored photos instead.

## What it does, step by step

1. You type a question and press Enter.
2. The app sends Claude the conversation, and the camera server's tools: take a photo,
   look closer at part of a photo, record an inspection result.
3. When Claude asks for a tool, the app passes the call on to the camera server and
   gives the result, photos included, back to Claude. The window shows each step: what
   Claude asked for, in plain words, and what came back.
4. Steps 2 and 3 repeat until Claude answers.

The rules live in the camera server, not in the app and not in what Claude is told: the
server caps the photo size, refuses zooms too small to show anything but blur, keeps one
record per photo, logs every action, and asks a person before marking a part as
failed. The app only passes the server's question on to you, and your answer back. A refusal from the
server is shown in red, and Claude reads it too.

Below the conversation, the window shows what each question cost and what the whole
conversation cost so far. In our tests, a question with a photo and a few closer looks
cost $0.04 to $0.07 with Claude Opus 5.5 and $0.01 to $0.02 with Claude Sonnet 5.5; a
short follow-up question costs less than a cent. You choose the model below the conversation.
"New conversation" starts over; until then, Claude remembers the earlier questions and
photos, so you can ask "now look closer at the left one".

## Installing

Python 3.14, the version tested. The app was tested on Linux; Windows and macOS are not
tested yet. The commands are for Linux, and should work the same in the macOS Terminal;
for PowerShell, see [On Windows](#on-windows).

You need both repositories, side by side in one folder, and one Python environment that
holds them both: the camera server from `mcp-server`, and this app. There are two ways
to make that environment; use one of them, not both:

- [With a virtual environment](#with-a-virtual-environment), if Python 3.14 is
  installed on your computer. The environment is a folder, `station-env`, next to the
  two repositories.
- [With conda](#with-conda), if you use Miniconda or Anaconda, which bring their own
  Python. Conda keeps the environment in a place of its own and you call it by its name,
  `mcp`; there is no `station-env` folder.

### With a virtual environment

In a terminal, in the folder that holds both repositories:

```
python3.14 -m venv station-env
source station-env/bin/activate
pip install -e "./mcp-server[test]"
pip install -e "./mcp-client[test]"
cd mcp-client
pytest -q
```

The first line makes the folder `station-env`, with a Python environment in it; the
second activates it; the rest installs the server and the app into it and runs the
app's tests. **In every new terminal**, activate it again before starting anything, in
the folder that holds both repositories:

```
source station-env/bin/activate
```

### With conda

In a terminal, in the folder that holds both repositories:

```
conda create -n mcp python=3.14
conda activate mcp
pip install -e "./mcp-server[test]"
pip install -e "./mcp-client[test]"
cd mcp-client
pytest -q
```

The first line makes a conda environment called `mcp`, with Python 3.14 in it; the
second activates it; the rest installs the server and the app into it and runs the
app's tests. The first time, conda may ask whether you accept the terms of service of
Anaconda's package channels (answer `a` to each question), then `Proceed ([y]/n)?`. If
you already made the environment `mcp` with the `mcp-server` README's conda steps, leave
out the first line: the app goes into the same environment. **In every new terminal**,
activate it again before starting anything:

```
conda activate mcp
```

Activating conda's own `base` environment is not enough: the commands are in `mcp`.

### What the install adds

The tests use the real camera server with a fake camera, and a stand-in for Claude that
follows a script, so they need no camera, no key and no internet. The install adds two
commands: `inspection-camera` starts the camera server, `inspection-station` starts the
app. They exist only inside the environment: in a terminal where it is not active, the
answer is "command not found".

On a computer that only runs the app, the camera being on another computer, the server
is not needed: `pip install -e "./mcp-client"` instead of both install lines is enough
there (the tests then cannot run, as they use the server).

## Your Claude API key

The app talks to Claude through Anthropic's API, which needs an API key, and is paid per
use (see the costs above).

1. Sign in to the Claude Console at platform.claude.com.
2. Under "API keys", create a key, and copy it.
3. In a terminal, make the key file and open it in an editor:

   ```
   mkdir -p ~/.config/anthropic
   nano ~/.config/anthropic/api-key
   ```

4. Paste the key, save with Ctrl+O and Enter, and close the editor with Ctrl+X. Then
   make the file readable for you only:

   ```
   chmod 600 ~/.config/anthropic/api-key
   ```

The app reads the key from this file every time it starts. (If the environment variable
`ANTHROPIC_API_KEY` is set, the app uses that instead.) To stop the key from working,
delete it in the Console; a spending limit for the key's workspace can be set there as
well.

## How to start it

Every terminal below needs the environment active first, the way you installed it:
`source station-env/bin/activate` in the folder that holds both repositories for a
[virtual environment](#with-a-virtual-environment), or `conda activate mcp` for
[conda](#with-conda).

| Your situation | What you start | See |
|---|---|---|
| Try it on one computer, no camera needed | The camera server with its fake camera, then the app | [Try it on one computer](#try-it-on-one-computer) |
| The camera on one computer, the app on another | The camera server on the station computer, the app on yours | [The camera on another computer](#the-camera-on-another-computer) |
| You want Claude Code instead of this app | Claude Code, in this repository's folder | [With Claude Code instead](#with-claude-code-instead) |

## Try it on one computer

Without a camera, the server uses a fake one, which serves stored photos of the demo
scenes (a gauge, packs, a scale, a tool tray, watches), a new one for every photo taken.

**In a first terminal**, with the environment active, start the camera server, and
leave it running:

```
inspection-camera --http
```

It is ready when it shows "Uvicorn running on http://127.0.0.1:8000". Its first line
says where its secret key is: `~/.config/inspection-camera/api-key`, made at its first
start. The app reads the same file, so there is nothing to copy on one computer.

**In a second terminal**, with the environment active, start the app:

```
inspection-station
```

The status line at the bottom of the window says "Connected" and lists the server's
tools; the live view on the left shows the photo the fake camera will serve next. Ask,
for example: "Take a photo. What does the gauge read?" Then ask "Take another photo.
Inspect the packs for damage; they are part packs-01. Record the result." If Claude
finds a pack damaged, the confirmation dialog comes up.

To stop, close the window, and press Ctrl+C in the server's terminal. The photos the
server took are in `mcp-server/captures/`, its logs in `mcp-server/logs/`.

## The camera on another computer

The station computer runs the camera server, as described in the `mcp-server` README,
section "The camera on one computer, Claude Code on another": choose the camera, start
the server with `--http --host 0.0.0.0`, and copy its key file to the app's computer, to
the same place: `~/.config/inspection-camera/api-key`. That section's steps for Claude
Code are not needed here.

On the app's computer, in a terminal with the environment active, start the app with the
station computer's address (here 192.168.0.20; on Linux, `hostname -I` on the station
computer shows it):

```
inspection-station --server http://192.168.0.20:8000/mcp
```

If something is wrong, the window says what: the camera server cannot be reached (is it
running, with `--host 0.0.0.0`, and does a firewall let port 8000 through?), it refused
the key (the key files differ), or there is no camera server at that address.

## With Claude Code instead

This folder's `.mcp.json` tells Claude Code how to start the camera server with the fake
camera, in the background, whenever Claude Code starts here. Claude Code finds the
command `inspection-camera` only when it is started with the environment active. In a
terminal with the environment active, in this repository's folder `mcp-client`:

```
claude
```

Approve the `inspection-camera` server when Claude Code asks. Type `/mcp`: it should
show `inspection-camera` as connected. Then ask, for example: "Take a photo of the
inspection station. What does the gauge read?" In Claude Code, the fail confirmation is
a question in the terminal, with the box "Mark this part as FAILED?" and the choices
"Accept" and "Decline": "Accept" with the box ticked marks the part as failed;
"Decline" marks it as unsure. For a real camera, or
a camera on another computer, see the `mcp-server` README.

## On Windows

Not tested yet. **With a virtual environment**: the same steps in PowerShell, in the
folder that holds both repositories:

```
python -m venv station-env
station-env\Scripts\Activate.ps1
pip install -e "./mcp-server[test]"
pip install -e "./mcp-client[test]"
cd mcp-client
pytest -q
```

If activating fails because running scripts is disabled, allow your own scripts once
with `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. In every new PowerShell
window, activate the environment again, in the folder that holds both repositories, with
`station-env\Scripts\Activate.ps1`.

**With Miniconda**: open "Anaconda PowerShell Prompt" from the Start menu (not "Anaconda
Prompt", the older Command Prompt), and run the commands of [With conda](#with-conda)
there, unchanged; in every new Anaconda PowerShell Prompt, `conda activate mcp`.

The Claude API key goes into `$HOME\.config\anthropic\api-key`:

```
mkdir $HOME\.config\anthropic
notepad $HOME\.config\anthropic\api-key
```

Paste the key, save, and close Notepad. Notepad may add `.txt` to the name when saving;
check with `dir $HOME\.config\anthropic` that the file is called `api-key`.

## Files

- `inspection_station/station.py`: the work behind the window: the loop between Claude
  and the camera server, the costs, and errors in plain words
- `inspection_station/app.py`: the window: live view, conversation, confirmation dialog
- `tests/test_station.py`: the loop, against the real camera server with its fake camera
  and a stand-in for Claude
- `.mcp.json`: the camera server with the fake camera, for Claude Code in this folder
- `docs/setup.svg`: the figure of the setup

Built with the official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
version 2.3.0, the [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python)
version 1.15.0, and [PySide6](https://doc.qt.io/qtforpython-6/) (Qt for Python) version
6.12.0.

## License

MIT, see [LICENSE](LICENSE).
