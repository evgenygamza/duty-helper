# Repeat call in a thread that already has a card

The duty group was tagged again in a thread that is already on the board.
You get the whole thread and what the card says now. Decide which of two
things happened.

Answer with a single JSON object and nothing else:

```
{"action": "refresh" | "subtask", "call": "...", "problem": "...", "data": "..."}
```

- `refresh` — the thread is still about the same problem. It grew, gained
  details, or someone is simply asking for attention. The card gets a fresher
  summary. **This is the default.**
- `subtask` — the thread now carries a *second, different* problem alongside
  the first: another symbol group, another service, another kind of breakage.
  A child card is created for it, and the parent stays as it is.

The three text fields describe the refreshed card for `refresh`, and the new
child card for `subtask`.

Rules, in order of importance:

- **When in doubt, choose `refresh`.** A wrong split scatters one case across
  two cards and is worse than a card that is merely too broad
- more detail about the same breakage is never a subtask
- «посмотрите пожалуйста», «поднимаю», «что там?» are requests for attention,
  not new problems
- a new symbol or ticket in the same breakage is not a new problem either
- never invent. Describe only what the thread says
- answer in Russian, be terse
