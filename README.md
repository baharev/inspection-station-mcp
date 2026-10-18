# Inspection Station MCP

An AI inspects parts with a camera: it takes photos, looks closer where it needs to, and
decides pass, fail or unsure. The camera sits behind an MCP server, which enforces the
rules and keeps the inspection log: whatever the AI is told, no part is marked as failed
without a person's yes.

![The setup. Left: the inspection station, where no AI runs: a camera above a conveyor belt, and the station computer with the MCP server, which keeps the inspection log. Right: the operator's computer with the desktop app, which talks to the MCP server over the network and to Claude, the AI, on the internet.](docs/setup.svg)

The station computer is the one the camera is plugged into; the MCP server runs there and
keeps the log. The operator's computer runs the desktop app, which talks to the server and
to Claude; Claude Code can take the app's place. The two computers can also be one and the
same, and the camera a USB webcam, or the fake camera, which serves stored photos instead.

MCP, the [Model Context Protocol](https://modelcontextprotocol.io), is the standard way to
plug tools, data and devices into AI applications such as Claude Code. This repository is a
self-built demonstration of connecting a device to an AI that way: the server, a desktop app
that uses it, photos of five test scenes, and the AI's real answers about them. It shows:

- **The rules in the server, not in the prompt**: inputs checked, limits in code, and a
  person's yes before any fail, asked through the part of MCP that lets a server ask the
  user a question ([the rules](#the-tools-the-server-provides-and-the-rules-it-enforces)).
- **An audit trail** of every photo, closer look, record and fail question, with each
  photo's fingerprint ([the audit trail](#the-audit-trail)).
- **Logins with roles** over OAuth, with a demo login server, or one shared secret key;
  over the network or started by Claude Code itself ([ways to run it](#other-ways-to-run-it)).
- **A desktop app with its own Claude loop**, through the Anthropic API, which can show
  every MCP message ([the app](client/README.md)).
- **The AI's real answers**, its mistakes included ([what the AI answered](#what-the-ai-answered)),
  and how the pattern grows into a plant ([from this demo to a plant](#from-this-demo-to-a-plant)).
- **Tests that were tested**, by planting bugs on purpose ([reading the code](#reading-the-code));
  checked on Linux and Windows, with a real webcam.

Author: [Ali Baharev](https://baharev.info/). I built it with Claude Code, Anthropic's AI
coding assistant, which wrote much of the code under my direction; the `CLAUDE.md` files are
the instructions I keep for it. The design, the rules and what to check were my decisions.
This is a finished demonstration, now in maintenance mode: I keep it working and up to date,
but issues and pull requests are turned off. You are welcome to fork it under the
[MIT license](LICENSE).

## Contents

- [Quick start](#quick-start)
- [What an inspection station is](#what-an-inspection-station-is)
- [Why an AI is needed here](#why-an-ai-is-needed-here)
- [What the AI answered](#what-the-ai-answered)
- [Choosing a model: Opus, Sonnet and Haiku compared](#choosing-a-model-opus-sonnet-and-haiku-compared)
- [The tools the server provides, and the rules it enforces](#the-tools-the-server-provides-and-the-rules-it-enforces)
- [What the server can and cannot guarantee](#what-the-server-can-and-cannot-guarantee)
- [The audit trail](#the-audit-trail)
- [Other ways to run it](#other-ways-to-run-it)
- [From this demo to a plant](#from-this-demo-to-a-plant)
- [Reading the code](#reading-the-code)
- [What is in this repository](#what-is-in-this-repository)

## Quick start

You need Python 3.13+, and access to Claude: either
[Claude Code](https://www.anthropic.com/claude-code), which needs a paid Claude plan or a
Claude API account, or a Claude API key for the desktop app. No camera is needed: the
server can serve stored sample photos instead.

Check the Python version first, with `python3 --version` (in PowerShell,
`python --version`). The Python that comes with the system is often too old: Ubuntu 24.04,
for example, comes with Python 3.12, which will not work. Install a newer Python next to
it, and write `python3.14` or `python3.13` instead of `python3` below.

Would you rather click than type? `inspection-server-window` opens a small window that
starts and stops the server ([the server window](server/README.md#the-server-window)).
Other setups, such as the server on one computer and the app on another, Claude Code
starting the server by itself, or a login for each person, are in
[Other ways to run it](#other-ways-to-run-it).

### On Linux or macOS

It has never been tested on macOS; it should work there too, since the code follows the
documentation of the libraries it uses. In a terminal (on Ubuntu and Debian,
`sudo apt install python3-venv` first, once):

```
git clone https://github.com/baharev/inspection-station-mcp.git
cd inspection-station-mcp/server
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
inspection-server --http
```

The server lists the cameras it finds and asks for a number: type the number of the last
entry, "Sample photos, no camera", and press Enter. It remembers the choice. Leave it
running; it is ready when it shows "Uvicorn running on http://127.0.0.1:8000". At its first
start it also made a secret key, in the file `~/.config/inspection-server/api-key`; the
commands below read it from there, so you never type it.

The sample photos come one per photo taken, in a fixed order: the complete tool tray first,
then the tray with its hammer missing, then the other scenes. Each start of the server
begins again with the first. While the server runs, `http://localhost:8000/live` in a
browser shows what the camera sees; with the sample photos, the one the next photo will
return.

#### Without any Claude access

A script plays the AI's part with fixed calls: a photo, a closer look and a proposed fail,
which you confirm or not in the terminal. It needs no running server and no key: the
server runs inside the script. In a second terminal, in the `inspection-station-mcp`
folder:

```
cd server
source .venv/bin/activate
python scripts/try_tools.py
```

#### With the desktop app

Put your Claude API key into the file `~/.config/anthropic/api-key` (see
[the app's README](client/README.md#your-claude-api-key)), then, in a second terminal, in
the `inspection-station-mcp` folder:

```
cd client
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
inspection-client
```

Ask in the window: "Take a photo of the inspection station. Is the tool tray complete?"
Then: "Take another photo. Check that every tool is in the tray; it is part tray-02.
Record the result." The fail question comes up as a dialog with the photo. After the second
question, the window looks like this: the camera's live view on the left; on the right the
conversation, with Claude's closer look at the tray, the fail it recorded and your yes:

![The desktop app. Left: the live view of the tool tray with its hammer missing. Right: Claude's closer look at the tray, the fail recorded after the person's yes, and Claude's answer that the hammer is missing.](client/docs/app-main.png)

The screenshot was taken with only the tray's photo in the sample folder, so the live view
shows the tray; with all the sample photos it shows the next one. Two of Claude's words in
it are wrong: it counts the serrated table knife as one of the tray's tools, and nothing was
"taken off the line": the demo only writes the record. The person's yes confirms the fail,
not every word of the AI's findings, which stay in the log as the AI's own text.

#### With Claude Code

Why Claude Code at all, next to the desktop app: it is an AI application this project did
not write, so it shows two things the app alone cannot. First, that the server is a plain
MCP server: any application that speaks MCP connects to it without a change, which is the
reason to use MCP rather than a private link between the server and its own app. Second,
that the rules hold whoever connects: Claude Code too must bring a person's yes before a
part is marked as failed, and with logins, a viewer is refused recording there too. It is
also the cheaper way in if you have a Claude subscription but no API account: Claude Code
runs on a paid Claude plan, while the app needs an API key, which is billed separately.

In a second terminal, in the folder where you will use Claude Code (the server is
registered for that folder only):

```
claude mcp add -s local --transport http inspection-server http://localhost:8000/mcp --header "Authorization: Bearer $(cat ~/.config/inspection-server/api-key)"
claude
```

Ask the same questions (if you asked them in the app first, restart the server, so that the
photos begin again with the complete tray). Claude Code first asks your permission to use
each tool: that is Claude Code's own question. When Claude records a fail, Claude Code shows
the server's question: tick the box "Mark this part as FAILED" and choose "Accept" to mark
the part as failed; "Accept" without the tick, or "Decline", marks it as unsure. Claude Code
shows the question as text, without the photo, so you are confirming the AI's description;
the photo it judged is `captures/<photo ID>.jpg` in the `server` folder.

### On Windows

The same steps, in PowerShell; what to ask, and what you will see, are as above.

```
git clone https://github.com/baharev/inspection-station-mcp.git
cd inspection-station-mcp\server
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
inspection-server --http
```

If activating fails because running scripts is disabled, allow your own scripts once with
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

#### Without any Claude access on Windows

In a second window, in the `inspection-station-mcp` folder:

```
cd server
.venv\Scripts\Activate.ps1
python scripts\try_tools.py
```

#### With the desktop app on Windows

The Claude API key goes into `$HOME\.config\anthropic\api-key` (see
[the app's README](client/README.md#on-windows)). Then, in a second window, in the
`inspection-station-mcp` folder:

```
cd client
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
inspection-client
```

#### With Claude Code on Windows

In a second window, in the folder where you will use Claude Code:

```
claude mcp add -s local --transport http inspection-server http://localhost:8000/mcp --header "Authorization: Bearer $(Get-Content $HOME\.config\inspection-server\api-key)"
claude
```

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
scrapped. The AI looks at the photo and decides pass, fail or unsure. A pass or an unsure
is written down straight away. A fail is not: wrongly scrapping a good part costs money,
so the server asks a person first.

## Why an AI is needed here

A device with a fixed task (set a temperature, read a sensor) is better driven by an
ordinary script. A camera at an inspection station is different: the questions are open
and change from part to part. A script needs to be written and tuned for every question;
the AI answers a new question about the same photo right away. It reads an analog gauge
like a person does, notices a torn pack, or sees that the hammer is missing from a tool
tray. It can also check whether what it reads makes sense, which a script that only copies
digits cannot do.

It does not always: the AI can also be confidently wrong, as the scale below shows. That
is why the server lets it look closer at any part of a photo, and why a person confirms
every fail.

## What the AI answered

Each answer below comes from a fresh Claude Code session (Claude Opus 5.5, October 2026)
that saw only the photo shown, served by the fake camera, and the question; nothing else
about the scene. Each question was asked twice, in two separate sessions. The sessions had
the photo and zoom tools but not the recording tool, so that they could be repeated
without filling the log; each answer's last paragraph, which says that it could not
record the result, is left out. Otherwise the answers are not edited, only shortened:
a cut is marked with a short summary in square brackets. I checked every reading against
the real objects. The photos are the sample photos in [`server/samples`](server/samples);
brand names on the objects are erased.

### The watch that is behind

<img src="server/samples/03-watches-behind.jpg" width="600" alt="Three wristwatches side by side on a white surface">

**Question:** Take a photo and do the final check before packing: all three watches must
show the same time, within one minute. Pass, fail or unsure for each watch?

> I took one photo (20261018-002046) and zoomed in on each dial.
>
> | Watch | Time shown | Result |
> |---|---|---|
> | **Left** (blue dial, no numerals) | about **1:24** | **Fail** |
> | **Middle** (grey dial, numbers) | **1:30** | **Pass** |
> | **Right** (black dial, plain marks) | about **1:30** | **Pass** |
>
> **Left watch: about 6 minutes behind.** Its long hand points between the 4 and 5 o'clock
> marks, closer to the 5. That's about 24 minutes past, not straight down at the date
> window, which would be 30. Its short hand agrees: it's just short of halfway between 1
> and 2. That's well beyond the one-minute limit, and the gap is too big to blame on
> reading the photo wrong.
>
> **Middle watch: 1:30.** The thick long hand points straight down at the 6, and the short
> hand is halfway between 1 and 2. The thin hand pointing at the 10 is the second hand (its
> short tail points toward the 4), not the minute hand.

In fact, the left watch showed about 1:23 to 1:24, the others 1:30. The second session
found the same.

### The tool tray, complete and not

<img src="server/samples/02-tray-incomplete.jpg" width="600" alt="A tool tray with foam cut-outs; the hammer's slot is empty and a serrated table knife lies in the slot for the hammer's handle">

**Question**, the same for both trays: Take a photo and do the kit check before packing:
every slot must hold its own tool, and the bit strip must be full. Pass, fail or unsure?

The tray with its hammer missing (above):

> **Fail.** The hammer is missing.
>
> - **Hammer slot (left side of the tray): empty.** The hammer-shaped recess is clearly
>   visible with nothing in it.
> - **Bit strip: looks full.** Zoomed in, I count 12 bits in a row with no gaps.
> - **Other slots: correct tools.** The adjustable wrench, knife, screwdriver, round black
>   piece and pliers are each in their own slot.

The complete tray ([photo](server/samples/01-tray-complete.jpg)):

> **Pass.** Each slot holds its own tool and the bit strip is full.
>
> [The six tools, each named with its slot.]
>
> The small rectangular cut-outs next to the round pocket and the pliers are finger holes
> for lifting the tools out, not empty tool slots.

Both sessions gave the same verdicts. But both took the serrated table knife, which lies
in the slot for the hammer's handle, for one of the tray's own tools: the AI checked what
the rule asked, slot by slot, and the knife sits in a slot. The verdict is still right,
and a person is asked before any fail is recorded.

Other sessions, in the desktop app, did notice the knife. Claude Sonnet 5.5, asked "Is the
tool tray complete? Every slot must hold its tool", answered: "The hammer slot on the left
is empty. A serrated knife lies across the hammer handle slot, and it doesn't belong in
this tray." Claude Opus 5.5, asked to check the tray and record the result, noticed it in
one of two sessions: "A serrated table knife (not part of the set) lies in the slot where
the hammer handle goes." The same question can get a more or less thorough answer from one
session to the next.

### Damaged packs, and what the camera cannot see

<img src="server/samples/04-packs.jpg" width="600" alt="Three foil packs side by side: the left one torn at its edge, the middle one folded sharply at a corner, the right one crumpled">

**Question:** Take a photo and do the final check before these packs go to the shop: a
pack passes only if its wrapper is intact and fit for the shelf. Pass, fail or unsure for
each pack, left to right?

> I took one photo and zoomed in on each pack. From left to right:
>
> | Pack | Verdict | Why |
> |---|---|---|
> | **1 (left)** | **Fail** | There's a tear in the wrapper. It starts at the left edge just under the black banner and runs across into the face of the pack, and the torn foil is lifting. |
> | **2 (middle)** | **Fail** | The top-left corner has been cut off at an angle, and the cut comes close to the black banner. The other two packs have square corners, so this is damage, not the design. The small notch on the right edge looks like a normal tear notch. I can't tell from above whether the seal is broken, but the wrapper isn't intact. |
> | **3 (right)** | **Unsure** | I couldn't find a tear, cut or opening on the front, and the edges are whole. But the pack is clearly wrinkled and creased, and its bottom edge is wavy. Whether that's acceptable for the shelf is your call. |
>
> **The camera only sees the front.** I couldn't check the backs of any of the packs, so a
> pass is only possible after someone looks at the back. That's another reason pack 3
> isn't a pass.

The left pack is torn, and the right one crumpled. The middle one is folded sharply at its
corner, not cut; it was folded on purpose for the test, and a fail is a fair call. The
second session gave the same three verdicts.

### A humidity reading just under the limit

<img src="server/samples/07-gauge.jpg" width="600" alt="A round analog gauge with a temperature scale above and a humidity scale below">

**Question:** Take a photo and do the storage room check: the humidity must stay below
42 %. Pass, fail or unsure?

> **Pass.** The gauge reads about **39 % RH**, which is below the 42 % limit.
>
> The hygrometer is the lower half of the dial. Its scale runs 90 on the left down to 10 on
> the right. Zoomed in, the thin needle sits about one small tick to the right of the long
> 40 mark, so it reads about 39 %.
>
> **One caveat:** the dial says the gauge is accurate to **±3 % rh**. A reading of 39 means
> the real humidity could be anywhere from 36 % to 42 %. The reading clearly passes, but the
> gap to the limit is no bigger than the gauge's own error. If "below 42 %" must hold even
> after allowing for that error, this one is borderline.

The gauge showed 39 to 40 %. Both sessions passed it and raised the gauge's printed
accuracy by themselves, leaving it to the operator whether to call it unsure instead.

### The scale that reads 7.8 and looks like 1.8

<img src="server/samples/06-scale-unlit.jpg" width="600" alt="A digital kitchen scale with a coin on it; the display's backlight is off">

**Question:** Take a photo and do the daily scale check: the check weight on the scale is a
50 cent coin, 7.80 g. The scale passes if it reads between 7.70 and 7.90 g. Pass, fail or
unsure?

The display shows 7.8, but its backlight is off, and without it the top bar of the 7 is
hard to see. The two sessions disagreed. The first:

> **Unsure.** I can't read the display reliably enough to pass or fail it.
>
> The scale reads either **7.8** (pass) or **1.8** (fail), and I can't tell which from this
> photo:
>
> - **First digit:** The backlight is off, so the display is dim. The digit clearly has its
>   right-hand vertical stroke, but I can't tell if the top bar is there. With the top bar
>   it's a 7; without it, a 1.
>
> [Two more points: the second digit and the decimal point.]
>
> To get a clear reading, turn on the display's backlight or add light from the front, then
> I'll take another photo. Someone could also just read the display directly.

The second, confidently wrong:

> **Fail.** The display reads **1.8 g**, far outside the 7.70–7.90 g band.
>
> I took two photos about 20 seconds apart and both showed the same, so the scale wasn't
> still settling. At full zoom (photo 20261018-002126), the first digit is only a vertical
> stroke, which is a "1". A "7" would also have a top bar, and there's no trace of one,
> while the rest of the "1" and the "8" show clearly.

The scale is fine. Had that fail been recorded, a good scale would have been taken out of
use: this is why the server asks a person before it records any fail. With the display
lit ([photo](server/samples/05-scale-lit.jpg)), both sessions read 7.8 and passed. On
another photo, not among the samples, where the unlit display was almost blank, both said
unsure and gave no number: "I'd be guessing if I said 7.8."

## Choosing a model: Opus, Sonnet and Haiku compared

The desktop app offers Claude Opus 5.5 (the default) and Claude Sonnet 5.5. On an earlier
set of photos of the same scenes, Opus 5.5, Sonnet 5.5 and Haiku 5.5 were each asked nine
questions, twice, in fresh Claude Code sessions, and their answers checked against the
real objects:

- **Haiku** read the dials as well as Opus, at about a thirtieth of the cost, but judged
  badly: it read the watches' times correctly and still missed the one that was 5 minutes
  behind, would not name the missing hammer, and made up tools that were not there.
- **Sonnet** came close to Opus at half the cost, but twice gave a wrong scale reading as
  certain ("the display reads 1.9 g", for 7.9).
- **Opus** did best on the hardest scene, the scale, and at explaining why, such as the
  difference between a reading error and a watch that is really behind.

In Claude Code, an answer cost about $0.19 with Opus, $0.09 with Sonnet and $0.006 with
Haiku, at list prices; most of that is Claude Code's own long instructions, sent at every
step. In the desktop app, which sends a short prompt, a question with a photo and a few
closer looks costs $0.04 to $0.07 with Opus and $0.01 to $0.02 with Sonnet. Two sessions per
question is a small sample. Still, it shows why the model is a choice to make for each use:
a cheap model can read an instrument well and still draw the wrong conclusion, and that is
also why the rules live in the server, where no model can skip them.

## The tools the server provides, and the rules it enforces

The server offers the AI three tools:

| Tool | What it does |
|---|---|
| `capture_image` | Takes a photo, saves it at the camera's full size, and returns it to the AI, at most 1280×720 pixels, with an ID such as `20261014-213005`. |
| `zoom_image(image_id, left, top, width, height)` | "Look closer": crops a rectangle of an earlier photo, at full size, and returns it enlarged. Read-only. |
| `record_inspection(image_id, part_id, verdict, findings)` | Adds one record to the inspection log: pass, fail or unsure. A fail needs a person's yes; without it, the part is recorded as unsure. |

The photo ID is passed from one call to the next: the MCP protocol version used here
(2026-07-28) keeps no session between calls. The zoom lets the AI decide for itself that it
cannot see well enough; enlarging shows what the camera captured more clearly, but cannot
add detail it did not capture.

Every rule is in the server's code (`server/inspection_server/server.py`), so it holds
whatever the AI is told or tries through the tools:

- **Inputs are checked.** Photo IDs, part labels, verdicts and the length of the findings
  must have the expected form; anything else is refused with a readable reason. A photo
  ID can never point to another file.
- **Limits are in code.** The photo the AI is sent is capped at 1280×720 pixels; zoom
  rectangles must lie inside the photo, and a crop less than a tenth of the photo's width
  or height, which would show only blur, is refused.
- **A person confirms a fail.** Before a fail is recorded, the server asks the person at
  the keyboard, through the part of MCP that lets a server ask the user a question
  (called elicitation). If they agree, the part is recorded as failed. If they say no,
  decline the question or close it, it is recorded as unsure, to be put aside for a person
  to look at. With AI applications that use the protocol version 2026-07-28, such as the
  desktop app, the person has an hour to answer; an answer that comes later, or after the
  server was restarted, records nothing, and the AI has to propose the fail again.
  Applications of the older version are asked while the call waits, with no time limit set
  by the server.
- **One record per photo**, so the log never holds two verdicts for the same picture.
- **Logged**: every photo, closer look, record and fail question, and every request a rule
  turns away (no key or login, a missing role, a zoom too small or outside the photo, a
  second record for a photo), with the time and who called. A malformed input, such as a
  photo ID that is not one, and a photo that does not exist are refused too, but leave no
  line in the log. See [The audit trail](#the-audit-trail).
- **Over the network, nobody gets in without a key or a login**, and a login's roles
  decide which tools its user may call: the role `viewer` allows photos, closer looks and
  the live view, the role `inspector` allows recording. The server checks the roles at
  every call, each on its own, so an inspector needs both, as the demo's user `inspector`
  has. The one exception: the live view needs no key on the station computer itself.

Tool annotations such as "read-only" are also set, but they are only hints for the AI
application, not protection.

## What the server can and cannot guarantee

The rules above hold whatever the AI does through the tools. A few things, though, are left
to the programs around the server, or are left open on purpose:

- **Guaranteed: the AI cannot give the person's yes through the three tools.** The answer
  to the fail question is not part of any tool's input: it comes back from the AI
  application, sealed to that exact question, part and user.
- **Not guaranteed: that a person, not a script, said yes.** The server relies on the AI
  application (the desktop app, or Claude Code) to show its question to a person and pass
  the answer on. Anyone with the secret key could write a program that says yes; logins
  narrow that down to named people with the inspector role.
- **Not guaranteed: that the AI has no other way in.** In the desktop app, Claude has only
  the three tools. Claude Code can also run commands on its computer: with the key at
  hand, it could call the server like any other program and answer the question itself.
  What stops it then is Claude Code's own permission prompt for commands, not the server.
  Where that matters, use the desktop app; a stronger design would have the server collect
  the yes itself, for example on a page the logged-in inspector opens in the browser.
- **Not checked: one verdict per part.** The part's label is whatever the AI types, and a
  part can be photographed again: a confirmed fail for `tray-02` can be followed by a pass
  for `tray-02` on another photo, recorded without asking anyone. In a plant the label
  comes from the line, and a part that failed or is unsure waits for a person's decision.
- **Trusted, not checked: what the server tells Claude.** The desktop app hands the server's
  instructions and tool descriptions to Claude as they are, so the server itself must be
  one you trust. The app answers only a question with the one yes-or-no field it expects,
  and declines any other.
- **Not filtered: what the camera sees.** It goes to the AI as it is: a note printed on a
  part is read like any other text in the picture.
- **Not confirmed by a person: a pass.** That is a choice: asking about every pass would
  make the person do the inspection. Here the person guards the costly action, scrapping a
  part. Where a bad part reaching the customer costs more, the passes need a check too, for
  example a person looking at a sample of them.

## The audit trail

Quality rules expect a factory to show who did what and when, to keep the evidence, and
never to lose a record. Here the server writes that trail itself, on the station computer,
so it holds whatever AI or app is connected. It keeps two files in its `logs/` folder:
`audit.log`, one line per event, and `inspections.jsonl`, one record per part inspected.

Here is part of `audit.log` from a real session with the desktop app and two logins, run
on one computer with the sample photos. Some lines are left out: the later parts' photos
and closer looks, the fail question for the watches, the live view, and two more refused
requests like the first line. The app makes one at each start: its first request goes out
without a login, and the refusal tells it where to log in.

```
2026-10-18T20:41:36+02:00 unknown REFUSED /mcp from 127.0.0.1: no key or login token sent
2026-10-18T20:42:15+02:00 viewer capture_image 20261018-204215 1920x1080 sha256=24c47b8108024a532050c2f1d102cd4eb5ebd21977c92dc5b36b7d5fd54aaf80
2026-10-18T20:42:19+02:00 viewer zoom_image 20261018-204215 box=(403, 140, 922, 248)
2026-10-18T20:42:32+02:00 viewer REFUSED record_inspection: needs the role inspector
2026-10-18T20:44:06+02:00 inspector capture_image 20261018-204406 1920x1080 sha256=706b4b4d0ede99f4f16ed5262906f07a3c34fa17c1ff73cdfbf42a44f32b2ceb
2026-10-18T20:44:10+02:00 inspector zoom_image 20261018-204406 box=(326, 108, 998, 918)
2026-10-18T20:44:16+02:00 inspector record_inspection tray-02 20261018-204406: fail proposed, asking the person
2026-10-18T20:44:28+02:00 inspector record_inspection tray-02 fail 20261018-204406 (AI: fail, fail confirmation: yes)
2026-10-18T20:45:38+02:00 inspector record_inspection watches-03 unsure 20261018-204507 (AI: fail, fail confirmation: no)
2026-10-18T20:46:25+02:00 inspector record_inspection scale-05 pass 20261018-204617 (AI: pass, fail confirmation: not asked)
```

Line by line:

1. A request without a key or a login, turned away before it reached any tool. It was
   sent on purpose, with `curl`, to show how a stranger's request looks. The server cannot
   know who sent it; it keeps the address it came from.
2. The AI, using the login of `viewer`, took a photo (the complete tool tray). The line
   holds the photo's size and its fingerprint.
3. It looked closer at a rectangle of that photo, given in the photo's pixels.
4. It tried to record the result and was refused: a viewer may not record.
5. A new login, `inspector`, and a new photo (the tray with its hammer missing).
6. A closer look at it.
7. The AI proposed a fail, and the server asked the person. This line is written when the
   question is asked, so a proposed fail is in the log even if no answer ever comes.
8. The person said yes: the part is recorded as failed.
9. Another part, a set of watches: the AI proposed a fail, and the person said no, so the
   part is recorded as unsure, to be put aside for a person to look at.
10. A pass, recorded straight away: no person is asked.

Each recorded part also has a record in `inspections.jsonl`, one JSON object per line.
The record of line 9, shown here one field per line:

```
{
  "time": "2026-10-18T20:45:38+02:00",
  "image_id": "20261018-204507",
  "photo_sha256": "28798061a271a2941884331118216958ba3670432cc2e2721ea59adaa3438648",
  "part_id": "watches-03",
  "ai_verdict": "fail",
  "ai_findings": "Times differ by more than 1 minute. Left (blue dial) reads about 1:24; middle (grey dial with numbers) about 1:30; right (black) about 1:30. Left watch is about 6 minutes behind.",
  "fail_confirmation": "no",
  "verdict": "unsure",
  "user": "inspector"
}
```

- `time`: when it was recorded, with its offset from UTC, so the hour that repeats when the
  clocks go back is still clear.
- `image_id`: the photo, kept as `captures/<image_id>.jpg`.
- `photo_sha256`: the photo file's fingerprint: if the file is changed or replaced later,
  it no longer matches.
- `part_id`: the part's label.
- `ai_verdict` and `ai_findings`: what the AI proposed, and what it saw, in its words.
- `fail_confirmation`: `not asked` unless the AI proposed a fail; then the person's
  answer: `yes`, `no`, `declined` (turned down: a person chose "Decline", or the AI
  application turned the question down by itself, as Claude Code does when it runs without
  a person, with `claude -p`), `no answer` (closed without answering), or `cannot ask` (the
  AI application cannot show questions, so nobody was asked).
- `verdict`: what was recorded: the AI's verdict, but a fail only with a person's yes.
- `user`: whose login the AI used: a login's user name, `api-key` (the shared secret key)
  or `local` (Claude Code started the server itself).

To check that a photo was not changed or replaced after it was recorded, compute its
fingerprint and compare it with `photo_sha256`; on Linux and macOS:

```
sha256sum captures/<image_id>.jpg
```

In PowerShell, `Get-FileHash captures\<image_id>.jpg` prints the same, in capitals. To
watch the log as it is written: `tail -f logs/audit.log`, or in PowerShell
`Get-Content logs\audit.log -Wait -Tail 20`. Both folders are in the `server` folder,
unless the setting `DATA_DIR` names another.

The limits, plainly:

- The logs are plain text files on the station computer, so whoever can change files there
  can change them unnoticed.
- With the shared secret key, every line says `api-key`: one key, no names. Logins give
  names. When Claude Code starts the server by itself on one computer, every line says
  `local`. Two exceptions: the live view opened on the station computer itself, which
  needs no key, is logged as `local`, and a refused request as `unknown`.
- The question the operator asked and the model that answered are known only to the app
  or to Claude Code, not to the server.

## Other ways to run it

The quick start uses the way that serves both Claude Code and the app, with the live view:
the server's secret key, all on one computer. All the ways, from the easiest:

| Your situation | How | Steps |
|---|---|---|
| Claude Code on one computer, nothing else to start | Claude Code starts the server by itself, in the background; no key, no live view | [Server README](server/README.md#claude-code-starts-the-server) |
| One computer, with the live view in a browser | The quick start: you start the server, Claude Code or the app connects with the key | [Server README](server/README.md#the-server-and-claude-code-on-one-computer), [app README](client/README.md#try-it-on-one-computer) |
| Two computers, for example two laptops on your home network: the server and the camera on one, the desktop app or Claude Code on the other | The same, plus a copy of the key file on the other computer, and HTTPS if the network is not trusted | [Server README](server/README.md#the-camera-on-one-computer-claude-code-on-another), [app README](client/README.md#the-camera-on-another-computer) |
| A login for each person, with roles | A demo login server (Keycloak, in a container), the server with logins, then Claude Code or the app | [Server README](server/README.md#logins-with-roles), [app README](client/README.md#logins-with-roles) |

The live view is a page in the browser that shows what the camera sees, as it happens, for
setting up a scene: `http://localhost:8000/live` while the server runs over HTTP.

To use a real camera, choose it instead of the sample photos when the server asks; any
webcam the computer can use will do. The server never picks a camera by itself
([choosing a camera](server/README.md#choosing-a-camera)). Tested on Linux and Windows;
never tested on macOS, though it should work there too.

## From this demo to a plant

The demo runs on one computer and talks to one device. A plant would build out the same
pattern like this.

Each existing system gets its own MCP server: a machine's OPC UA interface, a test bench, a
manufacturing execution system (MES), an in-house REST API. Each server offers a few
well-chosen tools built on the system's existing interface, not every endpoint it has. For
this demo's job, an industrial camera or a vision system would replace the webcam: only the
camera code changes, and the tools, the rules and the log stay as they are.

The servers run on the plant network, over MCP's HTTP transport, with logins, so it is
known which person and which application called what; starting a server on one computer is
for development. A plant would use its existing login server (for example Microsoft Entra
ID or Keycloak) and its own certificates instead of the demo's. The AI application runs in
the office network: only the MCP servers reach into the production network, through its
firewall, and no computer connects the machines straight to the internet (the figure above
leaves this out). The photos go to the AI provider, which is a question for the plant's
data protection officer and, where there is one, its works council, since a camera can
catch people. When the internet or the AI service is down, people do the inspection.

Tools that only read come first. Tools that change anything are added one at a time, each
with its rules in the server, and a person's yes where a mistake costs money. A yes in a
dialog is never a safety function: a machine's safety interlocks stay in its own
controller.

The rules and the logs stay in the servers, so they hold whatever AI application or model
is connected. A plant writes the records into its own database, for example the MES, with
its own protected history, not into text files; and the part's label comes from the line,
for example from a scanner, not from the AI.

Before the AI is trusted with a check, it is tried on parts whose answers are known, good
and bad, to measure how often it passes a bad part and fails a good one. The model's
version is fixed; a new model, new instructions, a new camera or new lighting mean
measuring again. Each record then also names the model and the version of the rule it was
checked against, which this demo's server does not know.

An answer takes about half a minute, so this suits the checks that fixed camera software
cannot do and that the line can wait for: setting up a new product, the first part of a
batch, spot checks, a daily check like the scale. At full line speed, trained machine
vision does the routine checks.

The servers are tested like any software, against fakes of the real systems, as the tests
here run against the fake camera.

## Reading the code

About 3,000 lines of Python in all: the server about 1,700, with 164 tests, the app about
1,250, with 62. The MCP ideas live in about 400 of those lines. A reading order:

1. `client/tests/stand_in_server.py`: a small server with the same three tools that the
   app's tests run against; the shortest example of a tool that asks the person a question.
2. `server/scripts/try_tools.py`: a whole MCP client in one page, calling the real server's
   tools without an AI.
3. `server/inspection_server/server.py`, in this order: `PhotoInfo`, `Confirmation` and
   `InspectionRecord` (what goes in and out); `capture_image` and `zoom_image` (limits in
   code); `confirm_fail` and `record_inspection` (the person's yes); `caller` and `require`
   (roles from the login token); `ApiKeyVerifier` and `JwtVerifier`; `key_auth`,
   `oauth_auth` and `http_app` (wiring the checks in).
4. `client/inspection_client/station.py`, the app's own loop between Claude and the
   server: `Station.ask` (the loop), `Station.tool_result` (an MCP result turned into what
   Claude reads), `call_tool` and `Station.answer` (the server's question, the person's
   answer), `Station.drop_unfinished_turn` (getting back on track after a failure).
5. The tests read like a specification of the rules: `server/tests/test_server.py`.

Safe to skip at first: the server window (`window.py`), choosing the camera (`choice.py`),
the camera code (`camera.py`, apart from `FakeCamera`), the live view page, the app's window
(`app.py`) and its login (`login.py`).

The server speaks MCP protocol version 2026-07-28, which keeps no session: there, the
server's question for the person comes back as the tool call's result, with the server's
state sealed inside it, and the call is sent again with the answer. It also serves clients
of the older version 2025-11-25, which keeps a session and asks during the call. The app's
"Show MCP messages" checkbox shows the messages' contents as the app sent and received
them, with the pictures and the sealed state shortened.

The tests were tested too: bugs were planted in the code by hand, one at a time, each
breaking a rule the way a developer could really get it wrong, and each gap they found got
a test. See [the server's](server/docs/test-quality.md) and
[the app's](client/docs/test-quality.md) record of it. There are about as many lines of
tests as of code: the server's 1,207 lines of code have 1,192 lines of tests (0.99 lines of
tests per line of code), and the app's 927 lines have 870 (0.94). These count only lines
with code on them: no blank lines, comments or docstrings, and not the two scripts in
`server/scripts`.

Built with the official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
2.3.0, the [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python) and
[PySide6](https://doc.qt.io/qtforpython-6/).

## What is in this repository

Two separate programs, each installed on its own, with its own tests:

- [`server`](server/README.md): the MCP server `inspection-server` for the station computer,
  with the server window, the sample photos, a demo login server and a script for HTTPS
  certificates.
- [`client`](client/README.md): the desktop app `inspection-client`. It talks to the server
  only through MCP, over the network, and never imports the server's code; its tests run
  against a stand-in server, so the server could be rewritten in another language without
  changing the app.
- `docs/setup.svg`: the figure above.
