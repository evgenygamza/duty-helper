# Repeat call in a thread that already has a card

The duty group was tagged again in a thread that is already on the board.
You get the whole thread and what the card says now. Decide which of two
things happened.

Answer with a single JSON object and nothing else:

```
{"action": "refresh" | "subtask" | "keep", "call": "...", "problem": "...", "data": "..."}
```

- `refresh` — the thread is still about the same problem. It grew, gained
  details, or someone is simply asking for attention. The card gets a fresher
  summary. **This is the default.**
- `subtask` — the thread now carries a *second, different* problem alongside
  the first: another symbol group, another service, another kind of breakage.
  A child card is created for it, and the parent stays as it is.
- `keep` — the card was clearly rewritten by a person: it carries wording,
  conclusions or instructions that do not come from the thread. Leave it
  alone. Slack does not record who edited a cell, so this judgement is
  the only protection a hand-written card has.

The three text fields describe the refreshed card for `refresh` and the new
child card for `subtask`. For `keep` they are ignored.

Rules, in order of importance:

- **Never drop what a person added.** Slack does not record who edited a cell,
  so anything in the current card that the thread does not contain was put
  there by a human: a conclusion, a decision, an instruction. Carry it over
  word for word and add to it. Losing it is the worst outcome here

- a card that merely reads like your own earlier summary is **not** hand-written
- **When in doubt, choose `refresh`.** A wrong split scatters one case across
  two cards and is worse than a card that is merely too broad
- more detail about the same breakage is never a subtask
- «посмотрите пожалуйста», «поднимаю», «что там?» are requests for attention,
  not new problems
- a new symbol or ticket in the same breakage is not a new problem either
- never invent. Describe only what the thread says
- answer in Russian, be terse
