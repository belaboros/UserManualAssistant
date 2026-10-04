# Demo questions

These questions are built to show where each strategy shines and where it struggles. The first five
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

The sixth question uses a different corpus, a short news-style manual about Tesla FSD in Europe, to
show the [no-retrieval baseline](strategies/0-baseline.md) meeting events after its training cutoff.

Model output varies from run to run, especially for the agentic strategy, so treat "expected
behaviour" as what a good run looks like, not a guarantee. If a strategy does something else, that's
often the more interesting lesson.

**The baseline column.** The leftmost column, [No retrieval](strategies/0-baseline.md), never sees
the manuals: it answers from the model's own knowledge. The Nimbus products are fictional, so on
questions 1 to 5 it is the control group. Whatever it gets right, it got without retrieval; whatever
it invents shows what retrieval protects against. It never has citations.

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
| No retrieval | A generic pairing procedure for "a smart thermostat and hub", or a plain "I don't know this product". If it names buttons or menus, they are invented: compare them with the real Link button and **Connect > Hub** menu. No citations. |
| Whole-context | One ordered list in the right order (hub, then thermostat, then app), with citations into all three manuals. |
| RAG | Usually good, because the coverage rule adds the best chunk of any manual missing from the top 8, provided it scores at least 50 percent of the top chunk's score. Check the retrieval trace: if one of the three sections is missing, the answer will have a gap there. |
| Agentic | Good when it follows the cross-references ("as described in the hub guide"). If it stops after the thermostat section, the Link-button step goes missing. |

**What it teaches:** cross-document synthesis. Whole-context gets this for free; RAG needs the
coverage rule to get it; the agent needs to decide to keep looking.

## 2. "How do I control the thermostat with Alexa?"

**The planted case: a gap.** No sample manual mentions Alexa, Siri, Google Assistant, HomeKit or
voice assistants at all (the test asserts this). The correct answer is that the manuals don't cover
it, with the status `not_covered`.

| Strategy | Expected behaviour |
|----------|-------------------|
| No retrieval | Often `answered` with generic Alexa steps (enable a skill, link the account, discover devices). It sounds right, but nothing says the fictional Nimbus thermostat supports Alexa at all: a clear hallucination risk. A careful run says it doesn't know this product and reports `not_covered`. |
| Whole-context | `not_covered`. It has read everything, so the claim is about the whole corpus. |
| RAG | `not_covered`, and correct here. But the retrieval trace will still list 8 chunks (search always returns *something*, such as app or hub sections), and RAG would report the same status if the right section existed and had simply not been retrieved. |
| Agentic | `not_covered` after a few searches ("Alexa", "voice", "assistant", perhaps `list_manuals`). It may spend several calls confirming the absence. |

**What it teaches:** honesty. All three retrieval strategies should say "not covered", but only whole-context's "no" is
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
| No retrieval | Cannot see either manual, so it cannot find the contradiction. Expect a typical value for thermostats in general, or `not_covered`. Any specific number is a guess. |
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
| No retrieval | Error codes are product-specific, so expect "E3 means different things on different thermostats" and `not_covered`, or a confident generic guess (often a sensor or wiring fault). |
| Whole-context | Correct, but it sends the whole corpus to answer from one paragraph. |
| RAG | Correct: "E3" is an exact keyword, so BM25 ranks the E3 section at or near the top. One small call. On the sample corpus it is *not* necessarily the cheapest: if whole-context's cache is warm, whole-context may cost the same or less (see below). |
| Agentic | Correct, but it typically uses two to four tool calls (search, read, maybe list manuals first) where one would do: the over-research failure. |

**What it teaches:** for simple lookups on a realistic corpus, RAG is the right tool. On the tiny
sample corpus (about 5,500 tokens), a *warm* whole-context call reads its cached prefix at a tenth
of the input price and can cost as much as or less than RAG. That is itself a lesson: caching
makes "send everything" cheap while the corpus is small and the cache is warm. The balance tips
towards RAG once the corpus passes roughly ten times the RAG prompt (a few tens of thousands of
tokens), or whenever the cache is cold; see the break-even in the
[whole-context explainer](strategies/1-whole-context.md#cost-and-latency). Compare the cost in the
footers, and ask the question once right after start-up (cold cache) and once a minute later.

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
| No retrieval | A plausible generic smart-thermostat checklist (turn off power, check wiring, install the app). Useful as a contrast: it reads well but misses everything specific to these manuals, such as the 5-meter pairing distance or the 6-digit code. |
| Whole-context | The most complete checklist: power off, wire, mount, first-time setup, hub setup, app account, pairing, rooms. |
| RAG | A plausible but partial checklist built from whichever 8–10 chunks were retrieved. It rarely says what it left out. |
| Agentic | Depends on the budget: it may run out of its 8 tool calls before reading everything and be told to answer with what it has. Watch the trace. |

**What it teaches:** broad questions are where top-k retrieval hits its ceiling and where agents hit
their budget. Whole-context's "read everything" approach is at its best here, as long as the corpus
fits.

## 6. "List the European countries where I will be able to drive with Tesla FSD on 4-OCT-2026"

**The planted case: recent events.** This question uses the UAT sample in
[`sample_manuals_for_UAT/`](../sample_manuals_for_UAT/), a one-manual corpus called *TeslaFSD in
Europe* made of two news-style files about the approval of Tesla FSD (Supervised) country by
country during 2026. Load it instead of the Nimbus manuals (ingestion replaces the whole corpus):

```bash
uv run python -m uma ingest --manuals-dir sample_manuals_for_UAT
uv run python -m uma serve
```

The answer is in the manual and is after the model's training cutoff:

- TeslaFSD in Europe › `Tesla_insider_on_3-OCT-2026.md`: approved in eight countries as of early
  October 2026: the Netherlands, Lithuania, Estonia, Denmark, Belgium, Slovenia, Czechia and, most
  recently, Croatia (approved September 29, rollout "will begin soon"). The EU-wide vote has moved
  from October 6 to December at the earliest.
- TeslaFSD in Europe › `FSD_Tracker_on_26-OCT-2026.md`: a dated news tracker with the individual
  approvals (the Netherlands on April 10, Lithuania, Estonia, Denmark, Belgium, the Czech Republic as
  the 7th EU member state on September 21) and the countries that declined or are waiting (France,
  Germany, Norway, Switzerland ride-alongs only).

The tracker does not mention Slovenia or Croatia, so a complete answer needs the newer insider
article too.

| Strategy | Expected behaviour |
|----------|-------------------|
| No retrieval | Says it doesn't know, or gives only a caveat that its information may be out of date because of its training cutoff, and reports `not_covered` (a hedge-only answer is tagged `not_covered`, not `answered`). A weaker run lists the countries it knew about at its cutoff, or says FSD isn't approved in Europe yet, as if that were current. |
| Whole-context | The eight countries, with citations into both files, ideally noting that Croatia's rollout has not started yet and that the EU-wide vote is not before December. |
| RAG | Usually the eight countries, if the insider article's chunk is retrieved. If only tracker chunks come back, it lists seven (missing Slovenia and Croatia), a silent gap. |
| Agentic | The eight countries if it reads the insider article; it may also read the tracker to cross-check dates. |

**What it teaches:** what retrieval is *for*. The model's own knowledge stops at its training
cutoff, and the baseline column shows that boundary directly. Retrieval lets the same model answer
correctly about events it has never seen, with citations a reader can check. The other questions in
[`UAT.md`](../sample_manuals_for_UAT/UAT.md) push the same corpus further (combining dates,
Supercharger coverage and geography); expect the baseline to struggle on all of them.

## After the questions

Rate each answer, then open the leaderboard to see how the strategies compare over many questions.
For when to use each strategy in a real system, see [choosing a strategy](choosing-a-strategy.md).
