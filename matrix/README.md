# Requirements matrix

There is one tab-separated file per source: `main.tsv` (main body), then `A.tsv`, `B.tsv`, `C.tsv`, `D.tsv`, `J.tsv`, `K.tsv` and `S.tsv` (Edition 4 annexes). Our profile is "CSMA Fixed Frequency"; see plan section 4.

Each row is one requirement or one interpretation. The columns, in order:

| Column | Meaning |
|---|---|
| `id` | Annex letter and a 4-digit number, for example `C-0042`. Main body rows use `MAIN` instead of a letter, for example `MAIN-0007`, because the main body has no annex letter and `M` is a reserved annex. Never reused or renumbered. |
| `source` | Section reference, for example `Ed4 C.4.2.3`. Write `Ed4 C (section unnumbered)` when the number is missing. |
| `page` | Printed page, for example `C-13`. |
| `strength` | `shall`, `should`, `may`, `info` (a definition or encoding that code must follow even though it is not phrased as shall), or `interp` (our resolution of an ambiguity, contradiction or gap). |
| `requirement` | One line in our own words. Never the standard's text. |
| `applies` | `yes`, `no` (out of our profile or scope), or `na` (not applicable to a node of this kind). |
| `reason` | Required when `applies` is not `yes`, for example `deprecated option HARD LINKS (main Table 1)`. |
| `impl` | Code location, filled in during implementation. |
| `tests` | Corpus case ids or test names, filled in during implementation. |
| `notes` | Cross references, conflicts, Ed1 differences. |

Rules:

- One requirement per row. Split compound sentences.
- `interp` rows cite every conflicting place and state the reading chosen. Plan section 4.4 lists the known ones.
- Rows for Edition 3 interop (types 0 to 3, ED3 EOWs) apply, because Ed3 interop is mandatory in Edition 4 (decision D6).
