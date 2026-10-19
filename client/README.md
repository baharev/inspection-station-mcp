# Inspection MCP client: the desktop app

The desktop app of [Inspection Station MCP](../README.md): a window where Claude inspects parts with the camera of the inspection server, in the folder [`server`](../server/README.md). You type a question, such as "Is the tool tray complete?". Claude takes a photo, looks closer where it needs to, answers, and can record the result. The window shows each step with its pictures, and the camera's live picture next to it. When Claude proposes a fail, a dialog asks you first, with the photo; no part is marked as failed without your approval.

The app runs its own loop between Claude, through Anthropic's API, and the inspection server, through MCP, using the official MCP and Anthropic libraries. This README is the reference for installing and running it. What the project is for, the quick start, Claude's answers and the rules are in the [main README](../README.md).

## Contents

- [What it does, step by step](#what-it-does-step-by-step)
- [Installing](#installing)
- [Your Claude API key](#your-claude-api-key)
- [How to start it](#how-to-start-it)
- [Try it on one computer](#try-it-on-one-computer)
- [The camera on another computer](#the-camera-on-another-computer)
- [Logins with roles](#logins-with-roles)
- [On Windows](#on-windows)
- [How the tests were checked](#how-the-tests-were-checked)
- [Files](#files)

## What it does, step by step

![The window. Left: the live view of the tool tray with its hammer missing. Right: Claude's closer look at the tray, the fail recorded after the person's approval, and Claude's answer that the hammer is missing.](docs/app-main.png)

Two things Claude says in this screenshot are wrong, as the main README explains ([quick start](../README.md#quick-start)): the table knife is not one of the tray's tools, and nothing was taken off any line.

1. You type a question and press Enter.
2. The app sends Claude the conversation, and the inspection server's tools: take a photo, look closer at part of a photo, record an inspection result.
3. When Claude asks for a tool, the app passes the call on to the inspection server and gives the result, photos included, back to Claude. The window shows each step, in gray below your question: what Claude asked for, in plain words, and what came back. Tick "Show MCP messages" to see the messages themselves as well, as the Model Context Protocol carries them between the app and the inspection server (their contents, with pictures and the server's sealed state shortened): indented, one field per line, each message between two thin lines. Where a text holds JSON of its own, such as the inspection record, that JSON is shown unpacked, not as one string full of escapes. A fail question comes back as the call's result, with the server's sealed state (shortened in the window); the dialog shows, and the call goes to the server again with your answer and that state.
4. Steps 2 and 3 repeat until Claude answers.

The rules live in the inspection server, not in the app and not in what Claude is told ([the rules](../README.md#the-tools-the-server-provides-and-the-rules-it-enforces)). The app only passes the server's question on to you, and your answer back. A refusal from the server is shown in red, and Claude reads it too.

When Claude proposes a fail, the server's question comes up as a dialog, with the photo, and your answer then shows in the conversation too. If you agree, the part is marked as failed. If you say no, or close the dialog without answering, the part is marked as unsure, to be put aside for a person to look at, and the log says that Claude called it a fail and what your answer was. An answer that comes too late for the server ([the rules](../README.md#the-tools-the-server-provides-and-the-rules-it-enforces) give the limit), or after the inspection server was restarted, records nothing; the window then says so, and you ask again. Every part Claude records ends up in the log, which the server keeps on the station computer, not the app: see [the audit trail](../README.md#the-audit-trail).

![The dialog "The inspection server asks you": the AI found a problem with part tray-02, the hammer is missing; if you agree, the part is marked FAILED, if not, UNSURE. Below, the photo of the tray, and the buttons "Yes, mark it as failed" and "No, put it aside".](docs/app-dialog.png)

Each answer ends with what the question cost, and below the conversation the window shows what the whole conversation cost so far; typical costs are in the main README, [Choosing a model](../README.md#choosing-a-model-opus-sonnet-and-haiku-compared). You choose the model below the conversation. "New conversation" starts over; until then, Claude remembers the earlier questions and photos, so you can ask "now look closer at the left one".

## Installing

Python 3.13+. The app's automatic tests pass on macOS, but nobody has run it on a Mac; it should work there too. The commands are for Linux, and should work the same in the macOS Terminal; for PowerShell, see [On Windows](#on-windows).

The app and the inspection server are separate programs. The app talks to the server only over the network, through MCP, even when both run on one computer; it needs no part of the server installed beside it. So each has a Python environment of its own: the server's is made as [its README](../server/README.md#installing) describes, and the app's as below. There are two ways to make the app's environment; use one of them, not both:

- [With a virtual environment](#with-a-virtual-environment), if Python 3.13+ is installed on your computer. The environment is a folder, `.venv`, in the `client` folder.
- [With conda](#with-conda), if you use Miniconda or Anaconda, which bring their own Python. Conda keeps the environment in a place of its own and you call it by its name, `inspection-client`.

On Linux, the window needs the system library `libxcb-cursor0`, which the desktop installs of Ubuntu and Xubuntu leave out. Without it, on a desktop that uses X11, such as Xubuntu's, the app stops at once with the message "xcb-cursor0 or libxcb-cursor0 is needed to load the Qt xcb platform plugin". On Ubuntu and Debian, install it once with `sudo apt install libxcb-cursor0`.

If the install or the tests fail with the newest versions of the packages the app uses, install the exact versions the tests passed with, listed in `constraints.txt`, instead:

```bash
pip install -e ".[test]" -c constraints.txt
```

### With a virtual environment

In a terminal, in the `client` folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
pytest -q
```

The first line makes the folder `.venv`, with a Python environment in it (if `python3 --version` shows a version older than 3.13, write `python3.13` or `python3.14` instead of `python3`; on Ubuntu and Debian, it needs the virtual-environment package for your Python version once, such as `sudo apt install python3.13-venv`); the second activates it; the rest installs the app into it and runs its tests. **In every new terminal**, activate it again before starting the app, in the `client` folder:

```bash
source .venv/bin/activate
```

### With conda

In a terminal, in the `client` folder:

```bash
conda create -n inspection-client python=3.14
conda activate inspection-client
pip install -e ".[test]"
pytest -q
```

The first line makes a conda environment called `inspection-client`, with Python 3.14 in it; the second activates it; the rest installs the app into it and runs its tests. The first time, conda may ask whether you accept the terms of service of Anaconda's package channels (answer `a` to each question), then `Proceed ([y]/n)?`. **In every new terminal**, activate it again before starting the app:

```bash
conda activate inspection-client
```

Activating conda's own `base` environment is not enough: the app is in `inspection-client`.

### What the install adds

The command `inspection-client`, which starts the app. It exists only inside the environment: in a terminal where it is not active, the answer is "command not found". The tests use stand-ins for the inspection server and for Claude, so they need no server, no camera, no key and no internet.

## Your Claude API key

The app talks to Claude through Anthropic's API, which needs an API key, and is paid per use (see [the costs](../README.md#choosing-a-model-opus-sonnet-and-haiku-compared) in the main README).

1. Sign in to the Claude Console at platform.claude.com.
2. Under "API keys", create a key, and copy it.
3. In a terminal, make the key file and open it in an editor:

   ```bash
   mkdir -p ~/.config/anthropic
   nano ~/.config/anthropic/api-key
   ```

4. Paste the key, save with Ctrl+O and Enter, and close the editor with Ctrl+X. Then make the file readable for you only:

   ```bash
   chmod 600 ~/.config/anthropic/api-key
   ```

The app reads the key from this file every time it starts. (If the environment variable `ANTHROPIC_API_KEY` is set, the app uses that instead.) To stop the key from working, delete it in the Console; a spending limit for the key's workspace can be set there as well.

## How to start it

Every terminal below needs an environment active first: for the app, its own, the way you installed it (`source .venv/bin/activate` in the `client` folder, or `conda activate inspection-client`); for the inspection server, the server's, as its README describes.

Which way to run it in which situation, Claude Code included, is in the main README's table, [Other ways to run it](../README.md#other-ways-to-run-it); the sections below have the app's steps for each.

## Try it on one computer

The main README's quick start, [With the desktop app](../README.md#with-the-desktop-app), has the steps: the inspection server with its sample photos in a first terminal, the app in a second, and what to ask. (Or start the server with a click: `inspection-server-window` opens [the server window](../server/README.md#the-server-window).)

The app reads the server's secret key from the file the server made, `~/.config/inspection-server/api-key`, so there is nothing to copy on one computer. (If the server was started with the setting `API_KEY` instead, set `API_KEY` for the app too: the app reads it before the file.) Once the app runs, the status line at the bottom of the window says "Connected" and lists the server's tools; the live view on the left shows the photo the fake camera will serve next.

To stop, close the window, and press Ctrl+C in the server's terminal. The photos the server took are in `server/captures/`, its logs in `server/logs/`.

## The camera on another computer

The station computer runs the inspection server, as described in the server's README, [The camera on one computer, Claude Code on another](../server/README.md#the-camera-on-one-computer-claude-code-on-another): choose the camera, start the server with `--http --host 0.0.0.0`, and copy its key file to the app's computer, to the same place: `~/.config/inspection-server/api-key`. That section's steps for Claude Code are not needed here.

On the app's computer, in a terminal with the app's environment active, start the app with the station computer's address (here 192.168.0.20; on Linux, `hostname -I` on the station computer shows it):

```bash
inspection-client --server http://192.168.0.20:8000/mcp
```

If something is wrong, the window says what: the inspection server cannot be reached (is it running, with `--host 0.0.0.0`, and does a firewall let port 8000 through?), it refused the key (the key files differ), or there is no inspection server at that address.

## Logins with roles

Instead of one key that everyone shares, each person can log in with their own name. The login happens in the browser, at a login server, which hands the app a token that the inspection server checks; the server then writes the name into every log line and record, and lets each person do only what their role allows. The roles and the demo login server are described in the server's README, [Logins with roles](../server/README.md#logins-with-roles); its script `scripts/keycloak.sh` starts the login server with two users: `inspector` (password `inspector`) and `viewer` (password `viewer`). This app is registered there in advance as `inspection-client`, the way an administrator registers each application that may connect.

On one computer, in three terminals. In the first two, start the login server and the inspection server with logins, as the server's README shows in [Logins with roles](../server/README.md#logins-with-roles) (its terminals 1 and 2).

In a third terminal with the app's environment active, start the app:

```bash
inspection-client --login
```

The app opens the login page in your browser. Log in as `viewer`; the browser says "Logged in", and the window "Logged in as viewer". Ask, for example, "Take a photo. Is the tool tray complete? Record it as part tray-01." (The fake camera serves its photos in turn, the complete tool tray first.) The inspection server refuses to record, with the reason, shown in red; Claude reads the refusal and tells you. Close the window, start the app again, and log in as `inspector` (if the login page offers `viewer` again, the round arrows next to the name start over with another user). Ask "Take a photo. Check that every tool is in the tray; it is part tray-02. Record the result.": the next photo shows the tray with its hammer missing, and now the result is recorded, after the confirmation dialog if Claude finds a tool missing. Every line of `server/logs/audit.log` and every record names the person logged in.

The app keeps the login only while it runs: each start asks again. A login token is valid for a few minutes (the demo's: 5); the app renews it by itself while it runs, as long as the login server allows.

**The camera on another computer**: the token travels with every request, so over the network it should be encrypted (HTTPS); Claude Code, for one, sends logins only over HTTPS or to `localhost`. On the station computer, start the login server and the inspection server with certificates, as the server's README describes in [Logins with roles](../server/README.md#logins-with-roles), "Logins on two computers". Copy `certs/ca.pem` from there to the app's computer, into the folder you start the app in, and start it with the station computer's address (here 192.168.0.20):

```bash
inspection-client --login --server https://192.168.0.20:8000/mcp --trust ca.pem
```

`--trust` tells the app to accept certificates signed by the demo's own certificate authority, `ca.pem`. The browser warns about the private certificate on the login page once; accept it, or import `ca.pem` into the browser.

If something is wrong, the window says what, for example that the inspection server takes logins and the app was started without `--login`, or that the address given with `--server` differs from the one the inspection server was started with (`SERVER_URL`): it must be the same, letter for letter.

## On Windows

**With a virtual environment**: the same steps in PowerShell, in the `client` folder:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[test]"
pytest -q
```

If activating fails because running scripts is disabled, allow your own scripts once with `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. In every new PowerShell window, `cd` to the `client` folder and activate the environment again with `.venv\Scripts\Activate.ps1`.

**With Miniconda**: open "Anaconda PowerShell Prompt" from the Start menu (not "Anaconda Prompt", the older Command Prompt), `cd` to the `client` folder, and run the commands of [With conda](#with-conda) there, unchanged; in every new Anaconda PowerShell Prompt, `conda activate inspection-client`.

The Claude API key goes into `$HOME\.config\anthropic\api-key`:

```powershell
mkdir $HOME\.config\anthropic
New-Item $HOME\.config\anthropic\api-key
notepad $HOME\.config\anthropic\api-key
```

Paste the key, save, and close Notepad. The second line makes the file, empty, so that Notepad opens it; given a file that does not exist yet, Notepad would make `api-key.txt` instead, which the app does not read.

For [Logins with roles](#logins-with-roles) on Windows, the inspection server's settings are written the PowerShell way, and the login server's script `scripts/keycloak.sh` runs on a Linux computer: both are in the server's README, [On Windows](../server/README.md#on-windows).

Checked on Windows Server 2025 with Python 3.13 and 3.14, in a virtual environment (3.14 also with Miniconda), from fresh copies of both programs: the tests; the app with the fake camera and the key file (the live view, answers, the confirmation dialog); logins with the login server on a Linux computer, over HTTP and over HTTPS with `--trust` (a viewer refused recording, an inspector's fail confirmed, the login renewed without asking again).

## How the tests were checked

The tests were tested too: 12 bugs were planted in the code by hand, one at a time, each breaking something the app must get right the way a developer could really get it wrong (No in the fail dialog passed on as yes, the dialog showing the wrong photo, the live view sent without the key, and so on). At first, 2 were caught by a test that failed for the right reason with a clear message, and 8 got through with every test still passing; the other 2 were caught, but for the wrong reason or with an unclear message. Each gap now has a test, and all 12 are caught. Two parts that had no tests at all (how refusals are put into words, and how the start passes the key or login on) were then covered the same way, with 19 more planted bugs. The bugs and what each one showed: [docs/test-quality.md](docs/test-quality.md). The inspection server's tests were checked the same way.

## Files

- `inspection_client/station.py`: the work behind the window: the loop between Claude and the inspection server, the costs, and errors in plain words
- `inspection_client/app.py`: the window: live view, conversation, confirmation dialog
- `inspection_client/login.py`: the login in the browser (the MCP SDK does the rest)
- `tests/test_station.py`: the loop, against stand-ins for the inspection server and for Claude
- `tests/stand_in_server.py`: the stand-in for the inspection server: the same tools, as any inspection server offers them over MCP
- `tests/test_contract.py`: the stand-in compared with the real inspection server; it runs only where the server is installed too, and is skipped otherwise
- `tests/test_login.py`: the app's part of the login, with a stand-in for the browser
- `tests/test_window.py`: the conversation in the window (MCP messages only when asked for, pictures and links, your answer to a fail question), the live view's "try again", and the status line checked again once the live view is back
- `tests/test_dialog.py`: the confirmation dialog: Enter never marks a part as failed
- `tests/test_main.py`: the app's start: which key or login, address and certificates its parts are given
- `tests/conftest.py`: what several test files share: HTTP to stand-ins, never the network
- `docs/test-quality.md`: how the tests were checked, with bugs planted on purpose
- `docs/app-main.png`, `docs/app-dialog.png`: the screenshots in this README
- `constraints.txt`: the exact versions of the packages the tests passed with

Built with the official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) version 2.3.0, the [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python) version 1.15.0, and [PySide6](https://doc.qt.io/qtforpython-6/) (Qt for Python) version 6.12.0, its essential modules only (the package `PySide6-Essentials`).
