# How the tests were checked

The app's tests passed. That alone says nothing about whether they would notice a
mistake. So the tests themselves were tested: a bug was planted in the code by hand, the
whole test suite run, and the bug taken out again, one bug at a time, 12 in all.

Each bug breaks one of the things the app must get right (the person's answer reaches
the server unchanged, the dialog shows the photo being judged, the login and the key are
used where they should be, and so on), in a way a developer could really get it wrong. A
bug counted as caught only if a test failed for the right reason, with a message that says
what went wrong. Where a bug could be planted in more than one way, every way had to be
caught.

Where a bug was not caught, a test was added or tightened, and the bug was planted again
to see that test fail. No planted bug was ever committed. The bugs were chosen from the
app's rules, not made by a tool that changes code at random ("mutation testing").

## What it found

| At first | Bugs |
|---|---|
| Caught, for the right reason, with a clear message | 2 |
| Got through: every test still passed | 8 |
| Caught for the wrong reason | 1 |
| Caught, but the message did not say what went wrong | 1 |

Now all 12 are caught, each by a test that names the rule. The check found no bug in the
app's code itself, but it showed one rule that was too loose; see the paragraph after the next.

The main lesson: the tests covered the main path well, but each one tried a single case.
Every question in them was a plain yes or no, every conversation had one photo, and the
live view had no test at all. So mistakes outside that one case could not show.

Two parts of the app had no tests at all: how the app words the inspection server's refusals
(key refused, login needed, login refused), and how the app's start passes the key or login,
the address and the trusted certificates on to its parts. Both have tests now, checked the
same way with 19 more planted bugs (41 to 59, in the second table). Along the way one rule
was tightened in the code: the app answered any server question with a single field using
its Yes/No dialog, even a question asking for text; it now turns down every question that
is not a plain yes or no (bug 41). The tests went from 21 to 41 (more were added since, for later changes).

The inspection server in the folder `server` was checked the same
way, with 28 bugs; its results are in [`server/docs/test-quality.md`](../../server/docs/test-quality.md).

The table names the test that catches each bug now. "Caught" means caught at first, with
nothing to change. The numbers go on from the server's list.

## App

| # | The bug planted | At first | What was changed | Now caught by |
|---|---|---|---|---|
| 29 | In the fail dialog, No is passed on as yes | Got through when the mistake was in the dialog (caught in the code that answers the server): no test clicked the dialog's buttons | A test clicks Yes, clicks No, and closes the dialog | `test_the_button_clicked_is_the_answer_passed_on` |
| 30 | Closing the dialog is sent as "refused to answer" | Caught | | `test_the_person_answers_the_servers_question_about_a_fail[closed]` |
| 31 | The app answers a question that is not a plain yes or no | Got through: every question in the tests was yes or no | A stand-in server asks yes or no plus a reason; the person must not be asked | `test_a_question_that_is_not_yes_or_no_is_declined_without_asking_the_person` |
| 32 | The dialog shows the wrong photo, for example from an earlier question | Got through: the tests took one photo, and the stand-in's photos were all alike | Each stand-in photo has a shade of its own; three photos over two questions | `test_the_dialog_shows_the_photo_being_recorded` |
| 33 | Enter in the fail dialog marks the part failed | Unclear message: `assert 1 == 2` | The dialog's results are named: "marked FAILED", "put aside" | `test_enter_puts_the_part_aside` and `..._even_with_the_focus_on_yes` |
| 34 | The login token is renewed too late, so the inspection server refuses it first | Got through when the margin was set to zero: the test compared with the margin itself | At least 20 seconds early, with a message | `test_the_token_is_renewed_before_the_inspection_server_would_refuse_it` |
| 35 | The check that the inspection server's address is the one the app uses is dropped | Got through when the check was no longer handed to the login: the test called it directly | Through the real login steps against stand-in servers: it must stop with what to do and open no browser | `test_no_login_to_an_inspection_server_known_by_another_address` |
| 36 | The live view stops sending the key or login | Got through: the live view had no test | A stand-in inspection server that wants the key | `test_the_live_view_sends_the_key` |
| 37 | The browser's login answer is taken from any address on the app's port | Got through | A forged answer at another address must get "not found" | `test_only_the_callback_address_brings_the_answer` |
| 38 | A refusal from the inspection server reaches Claude as if it had worked | Wrong reason in one of three forms: four tests failed because a test helper crashed | The helper fixed; the test says what Claude was told | `test_a_refusal_by_the_server_goes_back_to_claude` |
| 39 | The cost counts only the last step of a question | Caught | The two steps now cost differently, so more pricing mistakes show | `test_cost_counts_every_step` |
| 40 | Added during the check: the live view asks for pictures before the person has logged in, which starts a second login | Got through | A new test | `test_the_live_view_waits_for_the_login` |

## App: the refusals in words, and the start

Tests written for these two parts, and the yes-or-no rule; each bug was planted to see
its test fail.

| # | The bug planted | Now caught by |
|---|---|---|
| 41 | The app answers a server question that asks only for text (for example "why?") with the person's yes or no | `test_a_question_that_is_not_yes_or_no_is_declined_without_asking_the_person[only a reason]` |
| 42 | A "not found" answer during the login's lookups is taken for "there is no inspection server at this address", so the login never finishes | `test_the_inspection_servers_first_refusal_starts_the_login`, `test_a_login_the_inspection_server_refuses_is_told_in_words` |
| 43 | A "not found" from the inspection server is no longer put into words: the person reads "MCPError: Not Found" | `test_errors_are_told_in_words_a_person_can_act_on[nothing at the address]` |
| 44 | Any refusal of the key is taken for "this server takes logins", so the person is told to use --login when the key was simply wrong | `test_errors_are_told_in_words_a_person_can_act_on[key refused]` |
| 45 | A server that takes logins is reported as "the key was refused", so the person copies the key again instead of using --login | `test_errors_are_told_in_words_a_person_can_act_on[logins wanted]` |
| 46 | With a login, the inspection server's first refusal is final, so the login never starts | `test_the_inspection_servers_first_refusal_starts_the_login`, `test_a_login_the_inspection_server_refuses_is_told_in_words` |
| 47 | With a login, a refusal of the new token is never final, so the person never learns why | `test_a_login_the_inspection_server_refuses_is_told_in_words` |
| 48 | A refused login is described as a refused key | `test_a_login_the_inspection_server_refuses_is_told_in_words` |
| 49 | Errors wrapped by the connection library are not unwrapped: the person reads "ExceptionGroup: unhandled errors in a TaskGroup" | `test_errors_are_told_in_words_a_person_can_act_on` (all three cases) |
| 50 | With --login, the live view still sends the key | `test_with_a_login_the_station_and_the_live_view_use_it`, `test_each_key_needed_is_read_from_its_own_file` (both cases) |
| 51 | --login is ignored: the station sends the key | `test_with_a_login_the_station_and_the_live_view_use_it`, `test_each_key_needed_is_read_from_its_own_file[with a login]` |
| 52 | The live view asks the MCP address for frames instead of the live view's address | `test_the_station_and_the_live_view_go_to_the_same_server` (both cases) |
| 53 | The station ignores --server and always goes to localhost | `test_the_station_and_the_live_view_go_to_the_same_server[--server]` |
| 54 | --trust does not reach the station | `test_trust_gives_the_station_and_the_live_view_the_certificate_authority` |
| 55 | --trust does not reach the live view | `test_trust_gives_the_station_and_the_live_view_the_certificate_authority` |
| 56 | With --login, the live view asks for frames before the person has logged in | `test_with_a_login_the_station_and_the_live_view_use_it` |
| 57 | Without --login, the live view waits for a login that never comes | `test_without_a_login_the_station_and_the_live_view_send_the_key` |
| 58 | Claude's key is read from the inspection server's key file | `test_each_key_needed_is_read_from_its_own_file` (both cases) |
| 59 | The --trust file is never loaded | `test_trust_gives_the_station_and_the_live_view_the_certificate_authority` |

## The planted bugs, line by line

<details>
<summary>Each bug as it was planted (old line → new line), to plant it again</summary>

29. `station.py`: `content={CONFIRM_FIELD: said})` → `content={CONFIRM_FIELD: True})`; second form, `app.py`: `{1: True, 2: False}.get(...)` → `{1: True, 2: True}.get(...)`
30. `station.py`: `return ElicitResult(action="cancel")` → `return ElicitResult(action="decline")`
31. `station.py`: `if (list(properties) != [CONFIRM_FIELD]` and its two lines → deleted
32. `station.py`: `Question(params.message, self.photos.get(self.running.get("image_id")))` → `Question(params.message, next(iter(self.photos.values()), None))`; second form: the latest photo
33. `app.py`: `no.setDefault(True)` → `yes.setDefault(True)`; second form: the line turning off `setAutoDefault` → deleted
34. `login.py`: `RENEW_EARLY = 30` → `RENEW_EARLY = 0`; second form: `- RENEW_EARLY` → deleted
35. `login.py`: `validate_resource_url=self.same_address` → deleted; second form: `if published and ...` → `if False and published and ...`
36. `station.py`, `live_view`: `async with server_http(auth, verify) as http:` → `async with httpx2.AsyncClient(verify=verify) as http:`
37. `login.py`: `address.path != "/callback" or` → deleted
38. `station.py`: `"is_error": bool(result.is_error)}` → `"is_error": False}`; second form: the `is_error` key dropped; third form: `ToolResult(..., False)`
39. `station.py`: `cost += price(response.usage, prices)` → `cost = price(response.usage, prices)`
40. `station.py`, `live_view`: `if not ready():` and its three lines → deleted
41. `station.py`: `if (list(properties) != [CONFIRM_FIELD]` and the line after it → `if len(properties) != 1:` (the check as it was before the fix)
42. `station.py`: `if response.status_code == 404 and "/.well-known/" not in response.request.url.path:` → `if response.status_code == 404:`
43. `station.py`: the two lines `if response.status_code == 404 and ...:` / `raise ServerRefused(404)` → deleted
44. `station.py`: `wants_login = "resource_metadata" in response.headers.get("www-authenticate", "")` → `wants_login = "www-authenticate" in response.headers`
45. `station.py`: `raise ServerRefused(401, "wants a login" if wants_login else "key")` → `raise ServerRefused(401, "key")`
46. `station.py`: `if isinstance(auth, KeyAuth):` → `if isinstance(auth, httpx2.Auth):`
47. `station.py`: `refused_once.add(response.request)` → deleted
48. `station.py`: `case ServerRefused(status=401, why="login"):` → `case ServerRefused(status=401, why="log in"):`
49. `station.py`: the two lines `while isinstance(err, BaseExceptionGroup) ...:` / `err = err.exceptions[0]` → deleted
50. `app.py`: `live_view(live_url(args.server), auth,` → `live_view(live_url(args.server), KeyAuth(read_key("API_KEY", SERVER_KEY_FILE)),`
51. `app.py`: `auth = login.auth if login else KeyAuth(read_key("API_KEY", SERVER_KEY_FILE))` → `auth = KeyAuth(read_key("API_KEY", SERVER_KEY_FILE))`
52. `app.py`: `live_view(live_url(args.server),` → `live_view(args.server,`
53. `app.py`: `server_client(args.server, auth, confirm, verify)` → `server_client("http://localhost:8000/mcp", auth, confirm, verify)`
54. `app.py`: `server_client(args.server, auth, confirm, verify)` → `server_client(args.server, auth, confirm)`
55. `app.py`: `show, tell, verify, ready)` → `show, tell, ready=ready)`
56. `app.py`: `ready = (lambda: login.logged_in) if login else (lambda: True)` → `ready = lambda: True`
57. `app.py`: `ready = (lambda: login.logged_in) if login else (lambda: True)` → `ready = lambda: bool(login and login.logged_in)`
58. `app.py`: `read_key("ANTHROPIC_API_KEY", CLAUDE_KEY_FILE)` → `read_key("ANTHROPIC_API_KEY", SERVER_KEY_FILE)`
59. `app.py`: `verify.load_verify_locations(args.trust)` → `pass`

</details>
