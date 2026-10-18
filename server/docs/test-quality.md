# How the tests were checked

The server's tests passed. That alone says nothing about whether they would notice a
mistake. So the tests themselves were tested: a bug was planted in the code by hand, the
whole test suite run, and the bug taken out again, one bug at a time, 28 in all.

Each bug breaks one of the rules the server promises to keep (a fail needs a person's
yes, a zoom has limits, every request needs a key or a login, and so on), in a way a
developer could really get it wrong. A bug counted as caught only if a test failed for the
right reason, with a message that says what went wrong. Where a bug could be planted in
more than one way, every way had to be caught.

Where a bug was not caught, a test was added or tightened, and the bug was planted again
to see that test fail. No planted bug was ever committed. The bugs were chosen from the
rules, not made by a tool that changes code at random ("mutation testing").

## What it found

| At first | Bugs |
|---|---|
| Caught, for the right reason, with a clear message | 11 |
| Got through: every test still passed | 9 |
| Caught for the wrong reason, or only by a test that hung | 3 |
| Caught, but the message did not say what went wrong | 4 |
| Caught, but the test reached out to the network | 1 |

Now all 28 are caught, each by a test that names the rule. The tests went from 132 to 140 (more were added since, for later changes).
The check found no bug in the server's code itself: every rule held.

Two lessons stand out. Tests that only checked "an error came back" passed for the wrong
reason: a photo ID shaped like a file path was still refused, but only because no such
photo existed, so the check of its shape could go missing unnoticed. And a rule checked
twice hides one of the checks: the MCP SDK also refuses expired login tokens, so the
server's own expiry check had never been tested on its own.

The app in the folder `client` was checked the same way; its
results are in [`client/docs/test-quality.md`](../../client/docs/test-quality.md).

The tables name the test that catches each bug now. "Caught" means caught at first, with
nothing to change.

## Server: a fail needs a person's yes

| # | The bug planted | At first | What was changed | Now caught by |
|---|---|---|---|---|
| 1 | The person answers No, but the part is recorded as failed | Caught | | `test_fail_without_a_yes_is_recorded_as_unsure` |
| 2 | A fail is recorded even when nobody said yes | Caught | | the same |
| 3 | "Refused to answer" and "closed the dialog" are swapped in the log | Caught | | the same |
| 4 | The person is asked to confirm a pass too | Caught | | `test_pass_is_recorded_without_asking_anyone` and others |
| 5 | The question is asked before the role check, so a viewer gets the fail question | Caught | | `test_a_viewer_may_look_but_not_record` |

## Server: zoom limits

| # | The bug planted | At first | What was changed | Now caught by |
|---|---|---|---|---|
| 6 | The too-small check looks only at the width, so a thin strip passes | Got through | A case for a crop wide enough but too short | `test_zoom_refuses_bad_rectangles[too short]` |
| 7 | A crop of exactly the smallest allowed size (a tenth of the photo) is refused | Got through | A new test: the smallest crop, in the corner | `test_zoom_takes_the_smallest_rectangle_right_up_to_the_corner` |
| 8 | The outside-the-photo check looks only left to right, not top to bottom | Got through | A case for a crop past the bottom | `test_zoom_refuses_bad_rectangles[past the bottom]` |
| 9 | The zoom crops the smaller photo sent to the AI instead of the full-size one | Caught | | `test_zoom_returns_the_chosen_region_enlarged` |

## Server: records and the audit log

| # | The bug planted | At first | What was changed | Now caught by |
|---|---|---|---|---|
| 10 | The same photo can be recorded twice | Wrong reason: the test failed only because a person was asked about the second record, a fail | A second record that asks nobody is tried first; the refusal must be in the audit log | `test_one_record_per_photo` |
| 11 | The shape of a photo ID is no longer checked | Got through: `../../etc/passwd` was still refused, but only because no such photo exists | Each bad input is checked for the reason it is refused | `test_bad_inputs_are_refused[photo ID that is a path]` |
| 12 | The photo's fingerprint is taken of the file's name, not its content | Caught | | `test_a_record_holds_the_fingerprint_of_its_photo` |
| 13 | Every record names "local" instead of the person logged in | Caught | | `test_an_inspector_records_under_their_name` |
| 14 | A refused attempt to record is not written to the audit log | Got through for a photo already recorded (caught for a missing role) | The audit line is checked | `test_one_record_per_photo`, `test_a_viewer_may_look_but_not_record` |
| 15 | Requests turned away at the door (no key, no login) are not logged | Unclear message: "file not found: audit.log", which looks like a broken test | A missing log reads as a log with no lines | `test_requests_without_the_key_are_refused` and others |

## Server: keys and logins

| # | The bug planted | At first | What was changed | Now caught by |
|---|---|---|---|---|
| 16 | Only the first characters of the secret key are compared, so a near-miss key gets in | Got through: the only wrong key tried differed in its first letter | Three near misses: the last character wrong, the first half, a character added | `test_requests_without_the_key_are_refused` |
| 17 | Roles sent as one piece of text count, so "trainee-viewer-inspector" holds "viewer" | Unclear message: a long dump of the result | The refusal's text is checked first | `test_roles_sent_as_text_count_for_nothing` |
| 18 | Expired login tokens are accepted by the server's own check | Got through: the MCP SDK refuses them too, so the server's check was never tested on its own | Each token that does not fit also goes through the server's own check | `test_tokens_that_do_not_fit_are_refused[expired]` |
| 19 | Tokens issued for another server are accepted | Unclear message: `400 == 401`, in a case named `bad0` | Case names, and the message "let in: the token was accepted" | `test_tokens_that_do_not_fit_are_refused[issued for another server]` and two forged-token cases |
| 20 | A login server on another computer is trusted over plain HTTP | Caught, but the test then really tried to reach that computer | The network is replaced in that test | `test_a_login_server_on_another_computer_needs_https` |
| 21 | The key file is made readable by every user of the computer | Unclear message: the permissions in decimal, `(33188 & 511) == 384` | Compared as `'0o644' == '0o600'` | `test_the_first_start_makes_the_key_file_and_later_starts_reuse_it` |

## Server: the live view

| # | The bug planted | At first | What was changed | Now caught by |
|---|---|---|---|---|
| 22 | A web page using its own web address gets the camera picture from this computer (DNS rebinding) | Caught | | `test_a_web_page_cannot_reach_the_live_view_under_its_own_name` |
| 23 | A login token that was sent but refused (expired) is treated as the person at this computer | Caught | | `test_a_refused_token_is_refused_on_this_computer_too` |
| 24 | Another computer sees the camera without a key | Got through in one of two forms: another computer calling the server "localhost" | A case for that, and readable case names | `test_other_computers_need_the_key_for_the_live_view` |

## Server: the camera

| # | The bug planted | At first | What was changed | Now caught by |
|---|---|---|---|---|
| 25 | A camera sending another photo size than the one chosen is accepted | Got through when only the width was compared: the wrong size tried differed in width too | A case with the same width, less high (a real webcam offers both 1280x960 and 1280x720) | `test_a_camera_that_sends_another_size_than_chosen_is_refused[same width, less high]` |
| 26 | When the chosen camera is unplugged, the sample photos are served instead | Caught only by a hang: the test started a real server that never returned | Tests of the start fail at once if a server starts | `test_a_chosen_camera_that_is_unplugged_stops_the_server_with_what_to_do` |
| 27 | With nobody to answer the camera list, the sample photos are taken silently | Caught | | `test_without_a_person_to_ask_the_server_stops_instead_of_guessing` |
| 28 | A single camera is chosen without asking | Wrong reason: the test passed the camera check by luck (the answer meant for the camera list answered the next question) | The test first checks that the camera question was asked | `test_a_single_camera_is_still_chosen_by_a_person` |

## The planted bugs, line by line

<details>
<summary>Each bug as it was planted (old line → new line), to plant it again</summary>

In `inspection_server/server.py` unless named otherwise.

1. `if confirmation != "yes":` → `if confirmation in ("declined", "no answer"):`
2. `if confirmation != "yes":` and `recorded = "unsure"` → deleted
3. `answer.action == "decline"` → `answer.action == "cancel"`
4. In `confirm_fail`, `if verdict != "fail":` and `return None` → deleted
5. In `confirm_fail`, `require(INSPECTOR, "record_inspection")` → deleted
6. `if width < MIN_ZOOM or height < MIN_ZOOM:` → `if width < MIN_ZOOM:`
7. `if width < MIN_ZOOM or height < MIN_ZOOM:` → `if width <= MIN_ZOOM or height <= MIN_ZOOM:`
8. `if left + width > 1 or top + height > 1:` → `if left + width > 1:`
9. In `zoom_image`, before `w, h = photo.size`: `photo.thumbnail(MAX_PHOTO)`
10. `ids.add(json.loads(line)["image_id"])` → `ids.add(json.loads(line)["part_id"])`
11. The `pattern=` of `ImageId` → commented out
12. `hashlib.sha256(photo_path(image_id).read_bytes())` → `hashlib.sha256(bytes(photo_path(image_id)))`
13. `user=caller()[0],` → `user="local",`
14. In `check_record`, `audit(f"REFUSED record_inspection {image_id}: already recorded")` → deleted; in `require`, `audit(f"REFUSED {tool}: needs the role {role}")` → deleted
15. In `http_app`, `app.add_middleware(LogRefusals, ...)` → deleted
16. `hmac.compare_digest(token.encode(), self.key)` → `hmac.compare_digest(token.encode()[:8], self.key[:8])`
17. In `caller`, `roles if isinstance(roles, list) else [])` → `roles)`
18. `options={"require": ["exp", "sub"]}` → `options={"require": ["exp", "sub"], "verify_exp": False}`
19. `audience=self.audience, options={"require": ["exp", "sub"]}` → `options={"require": ["exp", "sub"], "verify_aud": False}`
20. In `secure_or_local`, the return → `return address.scheme in ("https", "http")`
21. The key file's `0o600` → `0o644`
22. In `from_this_computer`, the check of the name (the Host header) → deleted
23. In `live_frame`, `("authorization" in request.headers or not from_this_computer(request))` → `not from_this_computer(request)`
24. In `live_frame`, the same condition → `"authorization" in request.headers`; second form, in `from_this_computer`: `return name in ("localhost", "127.0.0.1", "::1")`
25. `camera.py`: `if (frame.shape[1], frame.shape[0]) != self.size:` → `if frame.shape[1] != self.size[0]:`; second form: `if False:`
26. In `open_camera`, the stop with "The camera chosen earlier ... cannot be found" → a warning, then `camera = FakeCamera(...)`; second form, `camera.py`: the first camera listed taken when none matches
27. `choice.py`, `from_menus`: under the second `if not can_ask:`, `return Choice(FAKE, SAMPLE_PHOTOS, "nobody to choose a camera")` before the stop
28. `choice.py`, at the start of `ask`: `if len(entries) == 2: return entries[0]`

</details>
