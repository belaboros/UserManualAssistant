# Demo questions

These five questions are built to show where each strategy shines and where it struggles. They
work against the bundled sample manuals in [`sample_manuals/`](../sample_manuals/), three short
manuals for a fictional smart-home product line:

| Manual | Folder | Files |
|--------|--------|-------|
| Nimbus Thermostat User Manual | [`nimbus-thermostat`](../sample_manuals/nimbus-thermostat/) | `getting-started.md`, `settings.md` |
| Nimbus Hub Guide | [`nimbus-hub`](../sample_manuals/nimbus-hub/) | `hub-guide.md` |
| Nimbus App Help | [`nimbus-app`](../sample_manuals/nimbus-app/) | `pairing.html`, `troubleshooting.html` |

Ingest them with `uv run python -m uma ingest --sample`, start the app with `uv run python -m uma serve`, and ask the questions in order.
Section references below are given as *manual › file › heading*, with the section id the app uses in
brackets; the planted cases are checked by
[`tests/test_sample_corpus.py`](../tests/test_sample_corpus.py).

Model output varies from run to run, especially for the agentic strategy, so treat "expected
behaviour" as what a good run looks like, not a guarantee. If a strategy does something else, that's
often the more interesting lesson.

## 1. "How do I pair the thermostat with the hub?"

**The planted case: overlap.** The procedure is split across all three manuals, and no manual has
the whole of it:

- **Hub:** Nimbus Hub Guide › `hub-guide.md` › Pairing devices
  (`nimbus-hub:hub-guide:pairing-devices`): hold the Link button for 3 seconds; the LED blinks blue
  and pairing mode lasts two minutes. It says to see the device and app manuals for the rest.
- **Thermostat:** Nimbus Thermostat User Manual › `settings.md` › Connect to a hub
  (`nimbus-thermostat:settings:connect-to-a-hub`): put the hub in pairing mode first, then
  **Menu > Settings > Connect > Hub**, stay within 5 meters, and the display shows a 6-digit code.
- **App:** Nimbus App Help › `pairing.html` › Add a thermostat
  (`nimbus-app:pairing:add-a-thermostat`): **Devices > Add > Thermostat**, compare the 6-digit
  code, confirm, then name the thermostat and choose a room.

| Strategy | Expected behaviour |
|----------|-------------------|
| Whole-context | One ordered list in the right order (hub, then thermostat, then app), with citations into all three manuals. |
| RAG | Usually good, because the coverage rule tops up any missing manual. Check the retrieval trace: if one of the three sections is missing, the answer will have a gap there. |
| Agentic | Good when it follows the cross-references ("as described in the hub guide"). If it stops after the thermostat section, the Link-button step goes missing. |

**What it teaches:** cross-document synthesis. Whole-context gets this for free; RAG needs the
coverage rule to get it; the agent needs to decide to keep looking.

## 2. "How do I control the thermostat with Alexa?"

**The planted case: a gap.** No sample manual mentions Alexa, Siri, Google Assistant, HomeKit or
voice assistants at all (the test asserts this). The correct answer is that the manuals don't cover
it, with the status `not_covered`.

| Strategy | Expected behaviour |
|----------|-------------------|
| Whole-context | `not_covered`. It has read everything, so the claim is about the whole corpus. |
| RAG | `not_covered`, and correct here. But the retrieval trace will still list 8 chunks (search always returns *something*, such as app or hub sections), and RAG would report the same status if the right section existed and had simply not been retrieved. |
| Agentic | `not_covered` after a few searches ("Alexa", "voice", "assistant", perhaps `list_manuals`). It may spend several calls confirming the absence. |

**What it teaches:** honesty. All three should say "not covered", but only whole-context's "no" is
backed by having seen everything. It's the question to ask when deciding whether you can trust a
"not covered" from a strategy.

## 3. "How long do I hold the reset button to factory-reset the thermostat?"

**The planted case: a contradiction.** Two manuals disagree:

- Nimbus Thermostat User Manual › `settings.md` › Factory reset
  (`nimbus-thermostat:settings:factory-reset`): hold the reset pin for **10 seconds**, until the
  Nimbus logo appears.
- Nimbus App Help › `troubleshooting.html` › Reset the thermostat
  (`nimbus-app:troubleshooting:reset-the-thermostat`): press and hold the reset pin for **5
  seconds**, until the logo appears.

There is also a distractor: the hub's hardware reset (Nimbus Hub Guide › `hub-guide.md` › Hardware ›
Reset, `nimbus-hub:hub-guide:reset-1`) also uses a 10-second hold, but on a different device. The
hub's Link button held for 10 seconds (Network › Reset, `nimbus-hub:hub-guide:reset`) resets only
network settings.

| Strategy | Expected behaviour |
|----------|-------------------|
| Whole-context | `contradiction_found`, stating both 10 s and 5 s, with both sections cited. |
| RAG | `contradiction_found` if both reset sections are retrieved. If only one is, it answers confidently with that one number and `answered`, which is a silent failure. Hub reset chunks may also crowd the list. |
| Agentic | `contradiction_found` if it reads both sections. If it reads only the thermostat manual's section, it answers "10 seconds" without noticing the conflict. |

**What it teaches:** contradictions are only visible if both sides are in front of the model. It
also shows why answer status is worth tracking ([ADR 0009](adr/0009-answer-status-tag-protocol.md)).

## 4. "What does error E3 mean?"

**The planted case: a single-passage lookup.** The answer is in one section: Nimbus Thermostat User
Manual › `settings.md` › Error codes › E3: Heating or cooling system not responding
(`nimbus-thermostat:settings:e3-heating-or-cooling-system-not-responding`). The thermostat calls for
heat or cooling but the system doesn't respond; check the breaker, the system's safety switch and
the R/W (heating) or R/Y (cooling) wiring, then call a heating technician. E3 doesn't mean the
thermostat is defective.

| Strategy | Expected behaviour |
|----------|-------------------|
| Whole-context | Correct, but it sends the whole corpus to answer from one paragraph. |
| RAG | Correct and the cheapest: "E3" is an exact keyword, so BM25 ranks the E3 section at or near the top. One small call. |
| Agentic | Correct, but it typically uses two to four tool calls (search, read, maybe list manuals first) where one would do: the over-research failure. |

**What it teaches:** for simple lookups, RAG is the right tool. On the tiny sample corpus the cost
gap to a *cached* whole-context call is small; it grows with the corpus, because RAG's prompt stays
the same size and whole-context's doesn't. Compare the cost in the footers.

## 5. "Give me a complete first-day setup checklist"

**The planted case: broad synthesis.** A good answer pulls from many sections across all three
manuals, for example:

- Thermostat › `getting-started.md`: Before you install, Installation, First-time setup
  (`nimbus-thermostat:getting-started:before-you-install`, `…:installation`, `…:first-time-setup`);
- Thermostat › `settings.md`: Wi-Fi, Connect to a hub (`nimbus-thermostat:settings:wi-fi`,
  `…:connect-to-a-hub`);
- Hub › `hub-guide.md`: Setup, Pairing devices (`nimbus-hub:hub-guide:setup`, `…:pairing-devices`);
- App › `pairing.html`: Install the app and sign in, Add a hub, Add a thermostat, Rooms and names
  (`nimbus-app:pairing:install-the-app-and-sign-in`, `…:add-a-hub`, `…:add-a-thermostat`,
  `…:rooms-and-names`).

That is a dozen or so sections, more than RAG's top 8.

| Strategy | Expected behaviour |
|----------|-------------------|
| Whole-context | The most complete checklist: power off, wire, mount, first-time setup, hub setup, app account, pairing, rooms. |
| RAG | A plausible but partial checklist built from whichever 8–10 chunks were retrieved. It rarely says what it left out. |
| Agentic | Depends on the budget: it may run out of its 8 tool calls before reading everything and be told to answer with what it has. Watch the trace. |

**What it teaches:** broad questions are where top-k retrieval hits its ceiling and where agents hit
their budget. Whole-context's "read everything" approach is at its best here, as long as the corpus
fits.

## After the questions

Rate each answer, then open the leaderboard to see how the strategies compare over many questions.
For when to use each strategy in a real system, see [choosing a strategy](choosing-a-strategy.md).
