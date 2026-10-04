# Git save and load redesign: inventory

The two acceptance lists of PROMPT.md section 4, taken from the code of release 1.30.60 before any
change. Both were made by reading the sources and by scripts; nothing was run. Each list says how it was
made and how its completeness was checked.

| List | Rows | File |
|---|---|---|
| Every capability reachable today from the Progress tab, the header save menu, the folder browser, the lab banner and the home card: control, function, endpoint, conditions, tests | 84 | [inventory/CAPABILITIES.md](inventory/CAPABILITIES.md) |
| Every message with which the Git flows refuse or disable something: text, where it is raised, what triggers it, how it reaches the person, the tests that pin it | 490 | [inventory/REFUSALS.md](inventory/REFUSALS.md) |

How to read them:

- **Capabilities.** The last column, *After (new home)*, names where each capability lives in the new
  design. "Done" for the project means no row is left without one.
- **Refusals.** Each row has a category: `F` a folder rule (35 rows), `S` a state or sequence (74), `X`
  outside the manager's control (174), `V` input validation (98), `O` other (109). The last column,
  *New outcome*, says what happens instead. The 35 `F` rows are the ones [DESIGN.md](DESIGN.md) section
  2 removes; an `X` row stays a sentence in the chip panel with the action that clears it
  (DESIGN.md 3.6).
- **Why folders may not overlap today.** REFUSALS.md quotes every passage. None gives a technical
  reason; DESIGN.md 2.2 checks the rule against every helper mode instead.

Appendix A of CAPABILITIES.md lists every reference to the Progress tab (273 in 76 files); it is the
work list for the tab's removal and for the documentation.
