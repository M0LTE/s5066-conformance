# Calibration results: drc.table for M0LTE.Ms110d 0.6.1

Phase 7 item P7-9a (M0LTE.S5066 `docs/core-architecture.md` section 9). This page says how the calibrated `drc.table` was built from the P7-5 modem sweep, which rungs made the ladder and why, and what the data shows that the table cannot fix.

## Files

Everything is in `calibration/ms110d-cs-0.6.1/`. The directory name is the provenance: `ms110d-cs` is the C# modem M0LTE.Ms110d, `0.6.1` its version (design shape item 6). A node on another modem implementation or version needs its own calibration, or one shown to match.

| File | What |
|---|---|
| `own.tsv`, `next.tsv`, `meta.json`, `audit-sample.tsv` | The sweep's aggregates, as merged on the instance (M0LTE.Ms110d `docs/calibration-sweep.md`; commit be49721, HfChannel 0.2.0, 1357 of 1357 jobs, 237,749 bursts, 1852 signal-hours). About 7 MB; the TSVs hold everything the builder needs, so the tarball is not kept |
| `drc-table.json` | The default table: `{"source": {...}, "table": {...}}`. `table` is exactly the `drc.table` of corpus-format.md 6.1; `source` names the calibration, the modem (implementation, package, version, commit), HfChannel, and the builder's choices |
| `rungs.tsv` | Per channel and rung: the set SNR at which it meets each criterion, and whether that channel's rule would keep it (and if not, which rung beats it) |
| `error-vs-estimate.tsv` | Per channel, rung and estimate bin: bursts, D_PDUs, D_PDU errors and the error rate of the burst itself |
| `estimate-summary.tsv` | Per channel and rung: the range of the estimate and the bin from which the burst's own error rate meets each criterion |
| `next-check.tsv` | The check of the builder's independence assumption against the measured burst pairs |
| `settle.tsv`, `settle-ssb.tsv` | Where the bulk walk of corpus-format.md 6.2 settles, per channel and set SNR, with the default table and with an SSB-only table |

Rebuild and check (standard library only, about a second, 20 MB):

```sh
python3 -I tools/build_drc_table.py calibration/ms110d-cs-0.6.1           # writes the derived files
python3 -I tools/build_drc_table.py calibration/ms110d-cs-0.6.1 --check   # exit 1 if any differs
```

All arithmetic is exact (Python fractions), so the output is the same on every run and platform.

## Method

1. **Error rate against set SNR.** Per channel, rung and set SNR, the D_PDU error rate is summed from `own.tsv`. A rung meets a criterion at the lowest set SNR from which its error rate stays at or below the criterion's rate up to the top of its window, interpolated between the 1.5 dB grid points.
2. **The two criteria.** Latency: a D_PDU error rate at or below **100 per thousand** (the stated latency target; "very few" corrupted, C-0472; one short message in ten needs a retry). Bulk, for ordering and dropping rungs only: at or below **500 per thousand**, where a rung delivers at least half its data rate, after the suggestion in [Ed4 C.5.1.1, p.C-60] that throughput peaks near a 50% frame error rate. Both numbers are ours and sit at the top of the builder.
3. **The ladder** (open question 15, with the coordinator's tie ruling). On the Poor channel, separately for bulk and latency, a rung is dropped when another rung is no worse on both data rate and the set SNR it needs and strictly better on one; a rung that never meets the criterion inside its window is dropped too. The ladder is the union of the two kept sets, slowest first. On each kept set a higher rate always needs more SNR, so this is also the order by the set SNR each rung needs.
4. **Thresholds** (design shape item 5). For each of the 36 measured rungs a (so a burst from a peer on any rung gives an estimate) and each ladder rung j, the builder works out the expected D_PDU error rate on j given the bin of the estimate on a. It mixes, with equal weight per channel over all five channels (an unknown path and radio), the error rate of j at each set SNR at which a was measured, weighted by how often a's estimate fell in that bin there. Below j's window j's error rate counts as 1, above it as the value at the window top. Then:
   - `latency[j]` is the lowest bin edge from which j's expected error rate stays at or below 100 per thousand in every bin above it (null if the top bin fails);
   - `bulk[j]` is the lowest bin edge from which the rung of highest expected goodput (data rate x (1 - error rate)) is j or above in every bin above it. So the target of corpus-format.md 6.2 step 6 is the rung of highest expected throughput.

   Bins with fewer than 20 bursts of a are not used. The values are bin edges, so multiples of 5 tenths.
5. **Constants.** Starting values, for the P7-9 stack sweep rounds to tune: `smoothing_weight` 8, `clean_run` 2, `rx_error_limit_ppt` 500, `rx_ceiling_initial` 2, `rx_ceiling_cap` 16, `tx_step_down_waits` 2, `tx_ceiling_initial` 2, `tx_ceiling_cap` 8, and since corpus 0.33.0 `probe_run` 2 (the probe of corpus-format.md 6.2 step 6, P7-9c; interp C-1291), the same run as the trial. Nothing in this sweep measures them. Tuned in P7-9 round 2 (corpus 0.35.0) from the stack sweep: `clean_run` 1 and `probe_run` 1, from 2 and 2. The round 1 stack sweep spent the first 600 to 950 s of each 1800 s run climbing from `drc.default_speed` (WN 2 Long) one rung per two clean bursts, at a sender transmission about every 50 s; one burst a rung halves that. Measured on studybox (seeds 1 to 3, M0LTE.S5066 docs/stack-sweep.md): mean goodput up 6% at AWGN 18 dB, 16% at Poor 18 dB, 18% at Poor 30 dB and 16% on Poor-SSB 18 dB, down 9% at AWGN 12 dB and 3% at Poor 12 dB, where a probe of WN 8 Long fails more often; no links lost.

**Independence.** Step 4 uses `own.tsv` for every pair (a, j), assuming that across the 6 s gap a burst's errors depend on the channel and set SNR but not on the previous burst's estimate (meta.json: the fading decorrelates in well under a second). `next-check.tsv` tests this against the 100,400 measured pair rows: split by whether a's estimate fell below, at or above its median at that point, the observed errors on the next burst match the prediction from set SNR alone to within 1% on every channel (for example Poor, estimate below median: 330 observed against 329 predicted per thousand). So the pairs add nothing the bursts on their own do not, and the full `own.tsv` can be used for pairs further apart than the sweep's eight places.

## The ladder

Set SNR (dB) at which each rung meets each criterion on Poor (from `rungs.tsv`):

| Position | Rung | Rate (bit/s) | Bulk needs | Latency needs | Kept for |
|---|---|---|---|---|---|
| 0 | WN 1 Long | 150 | -2.63 | -0.66 | bulk and latency |
| 1 | WN 2 Long | 300 | 0.94 | 2.87 | bulk and latency |
| 2 | WN 3 Long | 600 | 1.70 | 2.95 | bulk and latency |
| 3 | WN 13 Long | 2400 | 5.29 | 7.16 | bulk and latency |
| 4 | WN 6 Medium | 3200 | 8.52 | 11.57 | bulk |
| 5 | WN 6 Long | 3200 | 8.94 | 10.80 | latency |
| 6 | WN 7 Medium | 4800 | 12.32 | 15.84 | bulk |
| 7 | WN 7 Long | 4800 | 12.74 | 14.70 | latency |
| 8 | WN 8 Long | 6400 | 15.50 | 17.62 | bulk and latency |

Why the other 27 went (each is beaten by the rung named in `rungs.tsv`):

- **WN 4 and WN 5, every interleaver**: beaten by WN 13 Long, which has 1.5 to 2 times the rate and needs no more SNR on Poor (5.29 dB bulk, against 5.36 for WN 4 Long, 5.52 for WN 5 Medium and 5.57 for WN 5 Long). These are near ties, well inside the sweep's resolution; strict dominance on the interpolated figures decides them, as ruled.
- **Medium, Short and Ultra Short of WN 1, 2, 3 and 13, and WN 8 Medium and Short**: beaten by the Long rung of the same waveform, which needs less SNR at the same rate. WN 13 Medium (5.31 dB) and WN 8 Medium (15.53 dB) miss by 0.02 and 0.03 dB: again near ties.
- **WN 6 and 7**: Medium needs less for bulk and Long less for latency, so each criterion keeps a different one and both stay; Short and Ultra Short are beaten by them.
- **Ultra Short of WN 1, 2, 6 and 13, and Short of WN 1 and 2**: never meet the latency target on Poor (the error floor below).

The ladder is all Long and Medium. On the AWGN and AWGN-SSB channels the same rule would keep Short and Medium rungs instead (`rungs.tsv`), because without fading a shorter interleaver costs nothing; Poor orders the ladder, as ruled, and the Long rungs lose little on AWGN: the walk follows the best ladder rung at every AWGN point but one (-3 dB, where it stays on WN 1 Long, 150 bit/s, against 230 on WN 2 Long), and the best ladder rung is at most 103 bit/s below the best of all 36 rungs (3 dB, WN 13 Medium).

## Error rate against the estimate

`error-vs-estimate.tsv` has the full curves; `estimate-summary.tsv` condenses them. For the ladder rungs, the estimate bin (dB) from which the burst's own D_PDU error rate stays at or below 50% and 10%, and the highest bin seen:

| Rung | AWGN 50% / 10% / top | Poor 50% / 10% / top | Poor-SSB 50% / 10% / top |
|---|---|---|---|
| WN 1 Long | -4.5 / -4.5 / 2.5 | -4.0 / -3.0 / 3.5 | -4.5 / -3.0 / 2.5 |
| WN 2 Long | -3.5 / -2.0 / 2.5 | -1.5 / -0.5 / 4.0 | -1.5 / -0.5 / 3.0 |
| WN 3 Long | -1.0 / -1.0 / 5.5 | -1.0 / 0.0 / 7.5 | -0.5 / 1.0 / 7.0 |
| WN 13 Long | 2.5 / 4.0 / 9.0 | 0.5 / 1.5 / 5.5 | 1.0 / 2.0 / 4.0 |
| WN 6 Medium | 5.5 / 7.0 / 12.0 | 2.5 / 3.5 / 6.5 | 2.5 / 4.0 / 4.5 |
| WN 6 Long | 5.5 / 6.0 / 12.0 | 2.5 / 3.5 / 6.0 | 2.5 / 3.5 / 4.0 |
| WN 7 Medium | 10.0 / 10.0 / 19.5 | 3.5 / 4.5 / 7.0 | 3.0 / 5.0 / 5.0 |
| WN 7 Long | 10.0 / 12.0 / 16.5 | 4.0 / 4.5 / 6.5 | 3.0 / 4.0 / 4.5 |
| WN 8 Long | 13.0 / 14.5 / 19.5 | 3.5 / 4.5 / 5.5 | never / never / 4.0 |

(The AWGN tops are the window tops; there the estimate keeps rising with the set SNR.)

## Known features of the data

- **The estimate saturates on fading, so the walk cannot reach the top rungs there.** On Poor the estimate on WN 6 to 8 stays between about 3 and 6 dB from 12 dB set SNR to 30 dB (WN 8 Long reads 4.6 dB at 30 dB), while on AWGN the same rung needs 10 to 14.5 dB before it works. One table cannot tell "Poor at 20 dB" from "AWGN at 5 dB" by the estimate, and those call for different rungs. The equal-weight mixture picks what is best on average, which tracks AWGN exactly but stops on fading. `settle.tsv`, bulk goodput in bit/s against the best ladder rung at the same point (modem error rates only, before protocol overheads):

  | Set SNR (dB) | AWGN settles on | AWGN best | Poor settles on | Poor best |
  |---|---|---|---|---|
  | 3 | WN 13 Long, 1346 | 1346 | WN 3 Long, 550 | 550 |
  | 6 | WN 6 Medium, 2855 | 2855 | WN 13 Long, 1725 | 1725 |
  | 9 | WN 6 Long, 3200 | 3200 | WN 13 Long, 2379 | 2379 |
  | 12 | WN 7 Long, 4794 | 4794 | WN 13 Long, 2400 | 3095 |
  | 15 | WN 8 Long, 6355 | 6355 | WN 6 Medium, 3164 | 4558 |
  | 18 | WN 8 Long, 6400 | 6400 | WN 6 Medium, 3164 | 6027 |
  | 21 | WN 8 Long, 6400 | 6400 | WN 6 Medium, 3167 | 6260 |
  | 24 | WN 8 Long, 6400 | 6400 | WN 6 Medium, 3171 | 6274 |

  Moderate stops at WN 6 Long (3200, against up to 6400 possible) and Poor-SSB at WN 13 Long (2400, against about 4300 to 4500 on WN 7 Long from 18 dB). Giving the fading channels all the weight does not help: a table built over Poor, Moderate and Poor-SSB alone still stops at WN 6 Long on Poor, because within Poor itself the estimate on WN 6 reads much the same at 12 dB, where WN 7 fails, as at 20 dB, where it works. This is the A5 finding (design shape, first bullet), now with numbers: a step up on fading cannot rest on the estimate. Corpus-format.md 6.2 step 6 moves up only when the estimate's target is above the current rung, so with this table, and with any table, the walk tops out around 3200 bit/s on Poor. `settle.tsv` also shows, for comparison only, a walk that steps up after a clean run whatever the estimate says and comes back down only through the receiver's cap, never through the estimate: it reaches WN 7 Long or WN 8 Long on Poor from 13.5 dB and stays within about 5% of the best rung there. Whether to add such a step is a core decision for P7-9 (a T2 scenario and an interp row), not something a table can do. (Decided: corpus 0.33.0 adds it as the probe, `probe_run`, interp C-1291, with the hold described next; the `probing_reaches` column of `settle.tsv` models it.) A step up alone is not enough: on Poor, from 15 dB up, the estimate on WN 7 Medium, WN 7 Long and WN 8 Long (3.5 to 5.5 dB) gives a `bulk` target of WN 6 Long in this table, so step 6's immediate move down would undo every step up at the next burst. The change has to stop the estimate moving a recommendation down after a clean burst as well, and leave the move down to errors and caps. Without it, the P7-10 gate on Poor fails above about 15 dB: the best fixed Long rung over 0 to 30 dB on Poor is WN 8 Long by these modem figures, and it beats 3200 bit/s from 16.5 dB up.
- **Short and Ultra Short rungs have an error floor on fading.** On Poor, WN 1 and 2 Ultra Short still lose 91% and 96% of their D_PDUs at the top of their windows, WN 6 and 13 Ultra Short 39% and 36%, WN 1 and 2 Short 17% and 11%, and WN 6 Short 9%. More SNR does not clear it (the pilot found the same 7.5 dB above the prior). They never meet the latency target, or meet it far above the Long rung of the same waveform, so none is on the ladder; the floor costs nothing because the Long rung of the same waveform meets each criterion lower. A peer that sends one anyway still gives an estimate: every measured rung has a `thresholds` entry.
- **WN 8 fails on Poor-SSB.** With the 400 to 2600 Hz band-pass on both radios plus Poor fading, WN 8 loses 80 to 100% at every interleaver even at 27 to 33 dB, and its estimate reads about 3 to 4 dB. WN 8 Long is on the ladder (Poor orders it), but the walk never gets there on Poor-SSB: the estimate on WN 7 Long stays at or below 4.5 dB there, far below the 12.5 dB `bulk` threshold for WN 8 Long. If the walk gains a step-up on a clean run (above), that trial fails on Poor-SSB, and the receiver's error cap and the sender's failed-trial ceiling (design shape item 7) are what keep it off; WN 7 Short and Ultra Short lose about 30% there too.
- **The Poor estimate is compressed.** All the fading thresholds of the ladder's upper half lie between 2.5 and 6 dB of estimate (table above), so a small bias in the estimate moves the recommendation by a rung or two. The bins are 0.5 dB wide; the smoothing weight decides how much burst-to-burst spread reaches the comparison. A modem change that moves the estimate needs a new calibration (provenance, design shape item 6).
- **Near ties in the ladder rule.** WN 13 Long against WN 13 Medium and WN 4 Long, and WN 8 Long against WN 8 Medium, are decided by a few hundredths of a dB of interpolated set SNR, well inside the sweep's resolution. The choice changes little: the dropped rungs have the same or lower rate and need the same SNR to within 0.1 dB.

## A table for SSB-limited radios?

Not warranted by the data. `settle-ssb.tsv` uses a table built the same way over the AWGN-SSB and Poor-SSB channels only. On those two channels it does better than the default table at 3 of 52 points, by at most 44 bit/s (AWGN-SSB 6 dB: 2397 against 2353), and the same everywhere else. The default table already avoids WN 8 on Poor-SSB through the estimate, and the host cannot know whether a radio is SSB-limited (an operator does not set the table). One default table serves both.

## For P7-9

- The step-up question above decides whether the done-when can be met on Poor at all; it is the first thing for the stack sweep rounds to settle.
- On AWGN the best fixed Long rung is WN 8 Long, and at 16.5 dB and above both it and the adaptive node deliver the full 6400 bit/s, so "strictly above" the baseline cannot hold there for any selector; open question 14's gate needs reading for points where the baseline already reaches the top rate.
- The latency ladder is Long and Medium only, so LOW-SPEED (acknowledgements and short messages) goes on 7.68 s or 10.24 s blocks at the low end (WN 1, 2 and 3 Long). That bears on issue #67.
- The constants are untuned starting values.
