# s5066-conformance

A language-neutral conformance corpus and requirements matrix for STANAG 5066 Edition 4 implementations. The C# implementation ([M0LTE.S5066](https://github.com/M0LTE/M0LTE.S5066)) and a later C++ port both run the same cases and must produce the same bytes.

- `matrix/`: one row per requirement, citing annex, section and page, with a one-line paraphrase. It never reproduces the standard's text.
- `corpus/`: test vectors and scenario traces.
- `docs/`: the corpus format and the harness contract each implementation follows.

## Licence

AGPL-3.0-or-later; see [LICENSE](LICENSE). Commercial licences are available from the copyright holder, Thomas Fanning. Open a GitHub issue titled "Commercial licence enquiry".
