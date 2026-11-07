# Harness contract

Each implementation (C# first, C++ later) has a small test harness that runs this corpus against its own core. This document says what every harness must do, so that "passes corpus vX.Y.Z" means the same thing in both languages. The file formats are in [corpus-format.md](corpus-format.md).

## 1. Discovery and reporting

- Read the corpus from a pinned copy (submodule or package) at a tagged version. Check `corpus/VERSION`: refuse to run a MAJOR version the harness was not written for.
- Discover every `corpus/t1/*.jsonl`, every `corpus/t2/**/*.jsonl` and `corpus/prng/splitmix64.jsonl`. Do not hard-code file names.
- Report one result per case id: `pass`, `fail` or `unsupported`, with a reason for anything but `pass`. A failure names the case id, the line number, and the first difference (expected and actual, as hex for bytes).
- `unsupported` is for a kind, an input or an output type the harness does not know yet (corpus-format.md section 8). It is never counted as a pass. A harness may also mark cases it knowingly skips with a reason, but the summary must count them.
- Exit non-zero if any case fails. Print a summary: totals of pass, fail, unsupported and skipped, and the corpus version.
- The harness may write a machine-readable result file (JSON Lines, one `{"id", "result", "reason"}` per case) for CI to compare across the two languages.

## 2. Running cases

### PRNG

Run `corpus/prng/splitmix64.jsonl` first, as described in [prng.md](prng.md) section 5. A failure here invalidates every T2 result, so report it prominently.

### T1

For each case:

- `encode`: build the value in the implementation's own types from `value`, encode, compare with `bytes`.
- `decode` with `value`: decode `bytes`, convert the result to the corpus JSON shape, compare with `value` as JSON values (corpus-format.md section 2).
- `decode` with `error`: decode `bytes`; it must fail, and the failure's kind must equal `error`.
- `both`: do both.

The conversion between the corpus JSON shape and the implementation's types lives in the harness, not in the core. The core does not need to know JSON.

### T2

For each scenario:

1. Merge `config` over `corpus/t2/defaults.json` (corpus-format.md section 6) and create a fresh core with it, at time 0, with the PRNG seeded from `prng_seed`.
2. Give the core a fake modem whose `PlanBurst` answers from the `modem` fixture (corpus-format.md section 5). Any other effect the core has on the outside world must come out as an output.
3. Keep a table of running timers: name and deadline. Update it from every `timer_start` and `timer_cancel` output.
4. For each input line in order:
   - Check time: `t` is not earlier than the previous input. Every running timer with a deadline at or before `t` must already have been fed as `timer_expired`, unless this input is that expiry. Otherwise fail with `missed_timer`.
   - For `timer_expired`: the named timer must be running with a deadline equal to `t`, or fail with `bad_expiry`. Remove it from the table, then feed it.
   - Feed the input to the core at time `t`.
   - Collect every output the core produced while handling it, in order.
   - Compare that list with the output lines that follow the input in the file, up to the next input. Same length, and each pair equal as JSON values. Bytes are compared exactly.
5. The scenario passes when every input's outputs match. Timers still running at the end are fine.

A harness must not reorder, merge or filter outputs, and must not fire timers by itself. The trace is the whole of the observable behaviour.

## 3. What the core must offer the harness

These follow from the sans-IO design (plan section 3.2) and are the only things the harness needs:

- Construction from a configuration object, a seed and a modem port.
- One entry point per input type in corpus-format.md section 4.2, each taking the current time in milliseconds.
- A way to collect the outputs produced by the last call, in order.
- T1 codec functions: encode a value to bytes, decode bytes to a value or an error with a kind.

How the core spells these in each language is up to that implementation.

## 4. Linking matrix rows to cases

The link is held in one place: each case's `rows` list. The matrix `tests` column is used only for tests that are not in this corpus (for example a T3 simulation or a T4 measurement), named by their test name.

CI runs `tools/validate_corpus.py`, which:

1. Checks every corpus file parses and follows the schemas in corpus-format.md and prng.md.
2. With `--matrix matrix/`, reads every `matrix/*.tsv` and checks that each row id a case cites exists in the matrix.
3. With `--coverage`, lists every row with `applies` = `yes` that is neither cited by a case nor has a non-empty `tests` column, and fails if there is one.
4. With `--strict`, rejects `"TODO"` in `rows`.

While the matrix is being written, CI runs steps 1 and 2 only. Once phase 0 is done, CI adds `--coverage` and `--strict`, so a requirement without a test, or a test without a requirement, fails the build.

Coverage says only that a test exists for each row, not that it is a good test. Review still matters.

## 5. Agreement between the two implementations

The C++ port's first milestone is all T1 and T2 cases passing (plan 11.3). Both harnesses run the same tagged corpus in CI, and the result files must agree case by case: a case that passes in one language and fails in the other is a bug in one of them, or an ambiguity in this contract, and gets fixed in the corpus or the docs before either side moves on.
