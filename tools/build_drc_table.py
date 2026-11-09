#!/usr/bin/env python3
"""Build the calibrated drc.table from the P7-5 modem calibration aggregates.

Reads own.tsv, next.tsv and meta.json from a calibration directory (for example
calibration/ms110d-cs-0.6.1/, written by the M0LTE.Ms110d calibration sweep,
docs/calibration-sweep.md there) and writes, into the same directory:

  drc-table.json        the default table for an unknown channel: {"source": {...},
                        "table": {...}}, where "table" is exactly the drc.table of
                        docs/corpus-format.md section 6.1
  rungs.tsv             per channel and rung: data rate, the set SNR at which the
                        rung meets the bulk and the latency criterion, the error
                        rate at the top of its window, and the ladder verdict
  error-vs-estimate.tsv per channel, rung and estimate bin: bursts, D_PDUs and the
                        D_PDU error rate of the burst itself
  estimate-summary.tsv  per channel and rung: the estimate's range and the bin
                        from which the burst's own error rate meets each criterion
  next-check.tsv        the independence check of the method against next.tsv
  settle.tsv            per channel and set SNR, where the bulk walk of
                        corpus-format.md 6.2 settles with the default table (a
                        static prediction), against the best rung there
  settle-ssb.tsv        the same for a table built over the SSB channels only, to
                        show whether such a table would be worth having

Method (core-architecture.md 9, phase 7, design shape items 4 to 6 and open
question 15; docs/calibration-results.md gives the reasons):

1. Per channel, rung and set SNR, the D_PDU error rate p is summed from own.tsv
   over the estimate bins. The set SNR at which a rung meets a criterion is the
   lowest set SNR from which p stays at or below the criterion's error rate to
   the top of the rung's window, interpolated linearly between grid points. Bulk
   uses BULK_ERROR_PPT (expected goodput at least half the data rate), latency
   uses LATENCY_TARGET_PPT. A rung whose window top is still above the error
   rate never meets the criterion on that channel.
2. The ladder: on the ordering channel (Poor). The bulk set: a rung is dropped
   when another rung is no worse on both data rate and the set SNR it needs for
   bulk and strictly better on one (strict Pareto dominance, the coordinator's
   ruling on the open question 15 tie); a rung that never meets the criterion
   is dropped. The latency set (P7-9 round 3, block duration counts): the rungs
   that are the latency choice (below) at some set SNR of the ordering channel's
   grid. The ladder is the union of the two sets, ordered by data rate, then by
   the least set SNR it needs for a criterion whose set holds it; bulk_rungs and
   latency_rungs give the positions of each set (open question 15: the MAX-SPEED
   walk uses only the bulk set, the LOW-SPEED walk only the latency set).
3. Thresholds, per measured rung a (every rung measured) and ladder rung j: the
   expected D_PDU error rate of a burst on j given the estimate bin of a burst
   on a is the mixture, over channels c with weights w_c and the set SNRs s at
   which a was measured on c (uniform within c), of p_j(c, s), weighted by how
   often a's estimate fell in that bin at (c, s). This assumes the channel
   across the turnaround gap is independent given (c, s), which meta.json
   argues and next-check.tsv tests against the measured pairs. Below j's
   window p_j is taken as 1, above it as the value at the window top, and
   between grid points linearly.
   - latency, element j of a latency rung: the lowest bin edge from which the
     latency choice among the latency rungs is at position j or above in every
     bin with data above it; null when it never is. The latency choice is, of
     the rungs whose expected error rate is at or below LATENCY_TARGET_PPT, the
     one with the least expected time on air for a short message of
     LATENCY_MESSAGE_BYTES (whole blocks, so the block duration counts), over
     1 - error rate; ties go to the higher data rate.
   - bulk, element j of a bulk rung: the lowest bin edge from which the bulk
     rung with the highest expected value of the bulk objective, data rate x
     (1 - error rate)^2 (P7-9 round 3: the square charges retransmission), is
     at position j or above in every bin with data above it; null when it never
     is. So the target of corpus-format.md 6.2 step 6 is that rung.
   Elements of rungs outside the criterion's set are null.
   Bins with fewer than MIN_BIN_BURSTS bursts of a are not used.
4. The constants are starting values for the P7-9 stack sweep rounds.

All arithmetic is exact (fractions.Fraction); the output is integers only and
the same on every run and platform.

Usage:
  python3 -I tools/build_drc_table.py CALIBRATION_DIR [--check]

  --check   build in memory and compare with the files in CALIBRATION_DIR;
            exit 1 if any differs (nothing is written)

Python 3, standard library only.
"""
import argparse
import csv
import json
import os
import sys
from fractions import Fraction

# --- Choices of ours (docs/calibration-results.md) ------------------------------

# Bulk criterion for ordering and dropping rungs: the error rate at or below which
# a rung delivers at least half its data rate. C.5.1.1 suggests throughput peaks
# near a 50% frame error rate [Ed4 C.5.1.1, p.C-60]. Parts per thousand.
BULK_ERROR_PPT = 500
# The latency target: the D_PDU error rate at or below which a rung counts as
# meeting the latency criterion ("very few" corrupted, C-0472). Parts per thousand.
LATENCY_TARGET_PPT = 100
# The short message the latency criterion times (P7-9 round 3): about a 100-byte
# U_PDU in one D_PDU, or an acknowledgement with its fill copies. Bytes.
LATENCY_MESSAGE_BYTES = 128
# The channel that orders the ladder (design shape item 4).
ORDER_CHANNEL = "Poor"
# Channel weights of the default table (an unknown channel and radio) and of the
# SSB-only comparison table.
DEFAULT_WEIGHTS = {"AWGN": 1, "Poor": 1, "Moderate": 1, "AWGN-SSB": 1, "Poor-SSB": 1}
SSB_WEIGHTS = {"AWGN-SSB": 1, "Poor-SSB": 1}
# drc.default_speed in corpus/t2/defaults.json: where the walk starts.
DEFAULT_SPEED = "wn2-long"
# A bin of a's estimate needs this many bursts of a over the weighted channels.
MIN_BIN_BURSTS = 20
# Starting values of the constants, tuned by the P7-9 stack sweep rounds.
CONSTANTS = {
    "smoothing_weight": 8,
    # P7-9 round 2 (stack sweep, docs/calibration-results.md): 1, from 2, halves the climb.
    "clean_run": 1,
    "rx_error_limit_ppt": 500,
    "rx_ceiling_initial": 2,
    "rx_ceiling_cap": 16,
    "tx_step_down_waits": 2,
    "tx_ceiling_initial": 2,
    "tx_ceiling_cap": 8,
    # The probe of corpus-format.md 6.2 step 6 (P7-9c; interp C-1291).
    "probe_run": 1,
}

IL_ORDER = {"ultra_short": 0, "short": 1, "medium": 2, "long": 3}


def rung_key(name):
    wn, il = name.split("-", 1)
    return int(wn[2:]), il


def rung_obj(name):
    wn, il = rung_key(name)
    return {"wn": wn, "interleaver": il}


def tenths(fr):
    """Round a Fraction (tenths of a dB) to the nearest integer, halves up."""
    return (2 * fr.numerator + fr.denominator) // (2 * fr.denominator)


# --- Loading --------------------------------------------------------------------


def load(caldir):
    with open(os.path.join(caldir, "meta.json"), encoding="ascii") as f:
        meta = json.load(f)
    if not meta.get("merge", {}).get("complete"):
        sys.exit("meta.json: the merge is not complete")
    rate = {r["rung"]: r["data_rate_bps"] for r in meta["rungs"]}
    global BLOCK_BYTES
    BLOCK_BYTES = {r["rung"]: r["bytes_per_block"] for r in meta["rungs"]}
    # point[(c, rung, s)] = [dpdus, errors, bursts]; binned[(c, rung, s)][bin] = bursts
    point = {}
    binned = {}
    errbin = {}
    with open(os.path.join(caldir, "own.tsv"), encoding="ascii", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            k = (r["channel"], r["rung"], int(r["set_snr_tenth"]))
            p = point.setdefault(k, [0, 0, 0])
            p[0] += int(r["dpdus"])
            p[1] += int(r["dpdu_errors"])
            p[2] += int(r["bursts"])
            if r["est_bin_tenth"] != "-":
                b = int(r["est_bin_tenth"])
                d = binned.setdefault(k, {})
                d[b] = d.get(b, 0) + int(r["bursts"])
                e = errbin.setdefault((r["channel"], r["rung"], b), [0, 0, 0])
                e[0] += int(r["bursts"])
                e[1] += int(r["dpdus"])
                e[2] += int(r["dpdu_errors"])
    channels = [c["name"] for c in meta["channels"]]
    rungs = sorted(rate, key=lambda n: (rate[n], IL_ORDER[rung_key(n)[1]]))
    return meta, rate, channels, rungs, point, binned, errbin


# --- Per channel curves ---------------------------------------------------------


class Curve:
    """D_PDU error rate of one rung on one channel against set SNR."""

    def __init__(self, pts):
        self.s = sorted(pts)
        self.p = [Fraction(pts[s][1], pts[s][0]) for s in self.s]

    def at(self, s):
        if s < self.s[0]:
            return Fraction(1)
        if s >= self.s[-1]:
            return self.p[-1]
        for i in range(len(self.s) - 1):
            s0, s1 = self.s[i], self.s[i + 1]
            if s0 <= s < s1:
                return self.p[i] + (self.p[i + 1] - self.p[i]) * Fraction(s - s0, s1 - s0)
        raise AssertionError

    def needs(self, limit_ppt):
        """Lowest set SNR (Fraction, tenths) from which p <= limit to the window
        top; None when the top still fails; the window bottom when it never fails."""
        lim = Fraction(limit_ppt, 1000)
        if self.p[-1] > lim:
            return None
        i = len(self.p) - 1
        while i > 0 and self.p[i - 1] <= lim:
            i -= 1
        if i == 0:
            return Fraction(self.s[0])
        s0, s1, p0, p1 = self.s[i - 1], self.s[i], self.p[i - 1], self.p[i]
        return s0 + (s1 - s0) * (p0 - lim) / (p0 - p1)


def curves(point):
    by = {}
    for (c, rung, s), v in point.items():
        if v[0] > 0:
            by.setdefault((c, rung), {})[s] = v
    return {k: Curve(v) for k, v in by.items()}


# --- Ladder ---------------------------------------------------------------------


def pareto(cands, rate):
    """cands: {rung: needed SNR (Fraction)}. Strict Pareto dominance: a rung is
    dropped when another is no worse on data rate and needed SNR and strictly
    better on one. Returns {rung: None when kept, else the dominating rung that
    needs the least SNR (then the fastest)}."""
    out = {}
    for x, sx in cands.items():
        doms = [y for y, sy in cands.items() if y != x and rate[y] >= rate[x] and sy <= sx
                and (rate[y] > rate[x] or sy < sx)]
        out[x] = min(doms, key=lambda y: (cands[y], -rate[y], y)) if doms else None
    return out


BLOCK_BYTES = {}
POINT = {}


def message_time(r, rate):
    """Seconds on air (a Fraction) for LATENCY_MESSAGE_BYTES on rung r: whole blocks,
    each bytes_per_block x 8 / data rate long (the block duration counts)."""
    bpb = BLOCK_BYTES[r]
    blocks = -(-LATENCY_MESSAGE_BYTES // bpb)
    return Fraction(blocks * bpb * 8, rate[r])


def latency_choice(cands, err, rate):
    """Of the rungs cands whose error rate err[r] (a Fraction) is at or below the
    latency target, the least expected time for the short message, time / (1 -
    err), ties to the higher data rate then the earlier in cands; None when none."""
    lim = Fraction(LATENCY_TARGET_PPT, 1000)
    ok = [r for r in cands if err[r] <= lim]
    if not ok:
        return None
    return min(ok, key=lambda r: (message_time(r, rate) / (1 - err[r]), -rate[r], cands.index(r)))


def bulk_value(rate_bps, err):
    """The bulk objective (P7-9 round 3): data rate x (1 - error rate)^2."""
    return rate_bps * (1 - err) * (1 - err)


def kept_of(verdict):
    return sorted(r for r, by in verdict.items() if by is None)


def latency_set(c, cv, rate, rungs, point):
    """The rungs that are the latency choice at some set SNR of channel c's grid."""
    snrs = sorted({s for (cc, r, s) in point if cc == c})
    have = [r for r in rungs if (c, r) in cv]
    out = set()
    for s in snrs:
        r = latency_choice(have, {x: cv[(c, x)].at(s) for x in have}, rate)
        if r is not None:
            out.add(r)
    return sorted(out)


def build_ladder(cv, rate, rungs, point):
    need = {}
    for crit, ppt in (("bulk", BULK_ERROR_PPT), ("latency", LATENCY_TARGET_PPT)):
        need[crit] = {}
        for r in rungs:
            c = cv.get((ORDER_CHANNEL, r))
            n = c.needs(ppt) if c else None
            if n is not None:
                need[crit][r] = n
    kept = {"bulk": kept_of(pareto(need["bulk"], rate)),
            "latency": latency_set(ORDER_CHANNEL, cv, rate, rungs, point)}
    union = set(kept["bulk"]) | set(kept["latency"])

    def order(r):
        sn = [need[k][r] for k in ("bulk", "latency") if r in kept[k] and r in need[k]]
        return (rate[r], min(sn) if sn else Fraction(0))

    ladder = sorted(union, key=order)
    return ladder, need, kept


# --- Thresholds -----------------------------------------------------------------


def expected_errors(a, weights, cv, point, binned, ladder):
    """{bin: (bursts, [expected error rate of each ladder rung])} for estimates on a."""
    # P(c, s | bin) proportional to w_c / N_c(a) * n_bin(c, s) / n(c, s)
    acc = {}
    count = {}
    for c in sorted(weights):
        pts = sorted(s for (cc, r, s) in point if cc == c and r == a)
        if not pts:
            continue
        w = Fraction(weights[c], len(pts))
        for s in pts:
            total = point[(c, a, s)][2]
            for b, n in sorted(binned.get((c, a, s), {}).items()):
                lw = w * Fraction(n, total)
                row = acc.setdefault(b, [Fraction(0), [Fraction(0)] * len(ladder)])
                row[0] += lw
                for j, rj in enumerate(ladder):
                    row[1][j] += lw * cv[(c, rj)].at(s)
                count[b] = count.get(b, 0) + n
    out = {}
    for b in sorted(acc):
        if count[b] < MIN_BIN_BURSTS:
            continue
        tw, sums = acc[b]
        out[b] = (count[b], [x / tw for x in sums])
    return out


def edges(best, bins, positions, n):
    """Element j (j in positions): the lowest bin from which best[b] >= j in every
    bin above; None when the top bin fails. Other elements None."""
    row = [None] * n
    for j in positions:
        edge = None
        for b in reversed(bins):
            if best[b] >= j:
                edge = b
            else:
                break
        row[j] = edge
    return row


def thresholds_for(exp, ladder, rate, walks):
    bins = sorted(exp)
    n = len(ladder)
    best = {}
    lbest = {}
    for b in bins:
        err = {ladder[j]: exp[b][1][j] for j in range(n)}
        good = {j: bulk_value(rate[ladder[j]], exp[b][1][j]) for j in walks["bulk"]}
        top = max(good.values())
        best[b] = max(j for j in good if good[j] == top) if top > 0 else -1
        choice = latency_choice([ladder[j] for j in walks["latency"]], err, rate)
        lbest[b] = ladder.index(choice) if choice is not None else -1
    bulk = edges(best, bins, walks["bulk"], n)
    lat = edges(lbest, bins, walks["latency"], n)
    return bulk, lat, best


def build_table(weights, cv, point, binned, rate, rungs, ladder, kept):
    walks = {crit: [j for j, r in enumerate(ladder) if r in kept[crit]] for crit in ("bulk", "latency")}
    entries = []
    for a in rungs:
        if not all((c, a) in cv for c in weights):
            continue
        exp = expected_errors(a, weights, cv, point, binned, ladder)
        if not exp:
            continue
        bulk, lat, _ = thresholds_for(exp, ladder, rate, walks)
        e = rung_obj(a)
        e["bulk"] = bulk
        e["latency"] = lat
        entries.append(e)
    entries.sort(key=lambda e: (e["wn"] if e["wn"] != 13 else 4.5, IL_ORDER[e["interleaver"]]))
    table = {"ladder": [rung_obj(r) for r in ladder], "thresholds": entries}
    table.update(CONSTANTS)
    table["bulk_rungs"] = walks["bulk"]
    table["latency_rungs"] = walks["latency"]
    return table


# --- Outputs --------------------------------------------------------------------


def ppt(fr):
    return (fr.numerator * 1000 * 2 + fr.denominator) // (2 * fr.denominator)


def source(meta, caldir, weights, kind):
    return {
        "calibration": os.path.basename(os.path.normpath(caldir)),
        "modem": meta["modem"],
        "hfchannel": meta["hfchannel"],
        "gap_ms": meta["gap_ms"],
        "kind": kind,
        "channel_weights": weights,
        "order_channel": ORDER_CHANNEL,
        "bulk_error_ppt": BULK_ERROR_PPT,
        "latency_target_ppt": LATENCY_TARGET_PPT,
        "latency_message_bytes": LATENCY_MESSAGE_BYTES,
        "bulk_objective": "rate x (1 - e)^2",
        "min_bin_bursts": MIN_BIN_BURSTS,
        "builder": "tools/build_drc_table.py",
    }


def table_json(doc):
    """Stable, readable JSON: one ladder rung or thresholds entry per line."""
    t = doc["table"]
    lines = ["{", '  "source": ' + json.dumps(doc["source"], sort_keys=True) + ",", '  "table": {']
    lines.append('    "ladder": [')
    lines.append(",\n".join("      " + json.dumps(r) for r in t["ladder"]))
    lines.append("    ],")
    lines.append('    "thresholds": [')
    lines.append(",\n".join("      " + json.dumps(e) for e in t["thresholds"]))
    lines.append("    ],")
    keys = [k for k in t if k not in ("ladder", "thresholds")]
    lines.append(",\n".join("    " + json.dumps(k) + ": " + json.dumps(t[k]) for k in keys))
    lines.append("  }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def tsv(rows):
    return "".join("\t".join(str(x) for x in r) + "\n" for r in rows)


def channel_sets(c, cv, rate, rungs):
    """The bulk and latency sets the ladder rule would keep if channel c ordered it."""
    need = {}
    for r in rungs:
        if (c, r) in cv:
            n = cv[(c, r)].needs(BULK_ERROR_PPT)
            if n is not None:
                need[r] = n
    out = {"bulk": pareto(need, rate)}
    chosen = set(latency_set(c, cv, rate, rungs, POINT))
    out["latency"] = {r: (None if r in chosen else "!not chosen") for r in rungs
                      if (c, r) in cv and (r in chosen or cv[(c, r)].needs(LATENCY_TARGET_PPT) is not None)}
    return out


def verdict(v, r):
    if r not in v:
        return "never meets"
    if v[r] is None:
        return "kept"
    return v[r][1:] if v[r].startswith("!") else "beaten by " + v[r]


def db2(fr):
    """A Fraction in tenths of a dB as dB with two decimals."""
    h = tenths(fr * 10)
    sign = "-" if h < 0 else ""
    return "%s%d.%02d" % (sign, abs(h) // 100, abs(h) % 100)


def rungs_tsv(channels, rungs, rate, cv, ladder):
    """Per channel and rung. bulk and latency say whether the rung would be kept if
    that channel ordered the ladder, and if not which rung beats it; ladder gives
    its position in the table (Poor orders it)."""
    rows = [["channel", "rung", "data_rate_bps", "window_low_tenth", "window_high_tenth",
             "top_error_ppt", "bulk_needs_db", "latency_needs_db", "bulk", "latency", "ladder"]]
    for c in channels:
        kept = channel_sets(c, cv, rate, rungs)
        for r in rungs:
            k = (c, r)
            if k not in cv:
                continue
            cur = cv[k]
            nb = cur.needs(BULK_ERROR_PPT)
            nl = cur.needs(LATENCY_TARGET_PPT)
            rows.append([c, r, rate[r], cur.s[0], cur.s[-1], ppt(cur.p[-1]),
                         db2(nb) if nb is not None else "never",
                         db2(nl) if nl is not None else "never",
                         verdict(kept["bulk"], r),
                         verdict(kept["latency"], r),
                         str(ladder.index(r)) if r in ladder else "-"])
    return tsv(rows)


def errbin_tsv(errbin, channels, rungs):
    rows = [["channel", "rung", "est_bin_tenth", "bursts", "dpdus", "dpdu_errors", "error_ppt"]]
    for c in channels:
        for r in rungs:
            for b in sorted(b for (cc, rr, b) in errbin if cc == c and rr == r):
                n, d, e = errbin[(c, r, b)]
                rows.append([c, r, b, n, d, e, ppt(Fraction(e, d)) if d else "-"])
    return tsv(rows)


def median_bin(hist):
    total = sum(hist.values())
    run = 0
    for b in sorted(hist):
        run += hist[b]
        if 2 * run >= total:
            return b
    raise AssertionError


def estimate_summary(errbin, channels, rungs):
    """Per channel and rung: the range of the burst estimate (bins with at least
    MIN_BIN_BURSTS bursts) and the lowest bin from which the burst's own D_PDU
    error rate stays at or below the bulk and latency error rates."""
    rows = [["channel", "rung", "lowest_bin_tenth", "highest_bin_tenth", "bulk_from_bin_tenth",
             "latency_from_bin_tenth"]]
    for c in channels:
        for r in rungs:
            bins = sorted(b for (cc, rr, b) in errbin if cc == c and rr == r
                          and errbin[(cc, rr, b)][0] >= MIN_BIN_BURSTS and errbin[(cc, rr, b)][1] > 0)
            if not bins:
                continue
            res = []
            for lim in (BULK_ERROR_PPT, LATENCY_TARGET_PPT):
                edge = "never"
                for b in reversed(bins):
                    n, d, e = errbin[(c, r, b)]
                    if e * 1000 <= lim * d:
                        edge = b
                    else:
                        break
                res.append(edge)
            rows.append([c, r, bins[0], bins[-1]] + res)
    return tsv(rows)


def next_check(caldir, cv, binned, channels):
    """Test the independence assumption of the thresholds against the measured
    pairs: next.tsv's errors on b after a burst on a, split by whether a's
    estimate fell below, at or above a's median bin at that channel and set SNR,
    against the prediction from own.tsv at the same channel and set SNR alone.
    If the channel carried over the gap, a low estimate on a would be followed by
    more errors on b than predicted, and a high one by fewer."""
    obs = {}
    with open(os.path.join(caldir, "next.tsv"), encoding="ascii", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if r["est_bin_a_tenth"] == "-":
                continue
            c, a, b, s = r["channel"], r["rung_a"], r["rung_b"], int(r["set_snr_tenth"])
            m = median_bin(binned[(c, a, s)])
            e = int(r["est_bin_a_tenth"])
            cls = "below" if e < m else ("at" if e == m else "above")
            d = int(r["dpdus"])
            o = obs.setdefault((c, cls), [0, 0, 0, Fraction(0)])
            o[0] += int(r["pairs"])
            o[1] += d
            o[2] += int(r["dpdu_errors"])
            o[3] += d * cv[(c, b)].at(s)
    rows = [["channel", "estimate_on_a", "pairs", "dpdus", "observed_errors", "predicted_errors",
             "observed_ppt", "predicted_ppt"]]
    for c in channels:
        for cls in ("below", "at", "above"):
            if (c, cls) in obs:
                n, d, e, p = obs[(c, cls)]
                rows.append([c, cls + " median", n, d, e, tenths(p), ppt(Fraction(e, d)), ppt(p / d)])
    return tsv(rows)


def target(entry, crit, smoothed):
    """corpus-format.md 6.2 step 6: the highest position whose element is not
    null and not above the smoothed estimate, or 0."""
    t = 0
    for j, v in enumerate(entry[crit]):
        if v is not None and v <= smoothed:
            t = j
    return t


def estimate_at(c, r, s, binned, fading):
    """Median estimate bin of rung r at (c, s). Outside r's window: the nearest
    measured point's median, shifted by the SNR difference on a channel without
    fading (where the estimate reads the channel SNR) and unshifted on fading
    (where it saturates)."""
    pts = sorted(ss for (cc, rr, ss) in binned if cc == c and rr == r)
    if not pts:
        return None
    if s in pts:
        return median_bin(binned[(c, r, s)])
    near = pts[-1] if s > pts[-1] else pts[0]
    if pts[0] < s < pts[-1]:
        near = max(ss for ss in pts if ss < s)
    m = median_bin(binned[(c, r, near)])
    return m if fading[c] else m + (s - near) // 5 * 5


def settle(table, channels, cv, point, binned, rate, rungs, ladder, default_rung, fading):
    """A static prediction of where the bulk walk settles, per channel and set SNR,
    with the receiver's estimate taken as the median bin on the rung in use (the
    smoothing converges near it) and a step up refused when the higher rung loses
    more than rx_error_limit_ppt there (its cap would bring it back), over the
    positions of bulk_rungs, one at a time (a lower bound on the walk, which
    goes straight to its target since P7-9 round 3). The P7-9
    stack sweeps measure the real thing; this only shows what the table implies."""
    ent = {(e["wn"], e["interleaver"]): e for e in table["thresholds"]}
    walk = table.get("bulk_rungs") or list(range(len(ladder)))

    def up(p):
        """The next position of the bulk walk above p, or None (P7-9 round 3)."""
        return next((w for w in walk if w > p), None)
    lim = Fraction(table["rx_error_limit_ppt"], 1000)
    rows = [["channel", "set_snr_tenth", "settles_on", "goodput_bps", "probing_reaches", "probing_goodput_bps", "best_ladder_rung", "best_ladder_bps",
             "best_any_rung", "best_any_bps", "stop_reason"]]
    for c in channels:
        snrs = sorted({s for (cc, r, s) in point if cc == c})
        for s in snrs:
            def good(r):
                return rate[r] * (1 - cv[(c, r)].at(s)) if (c, r) in cv else Fraction(0)
            pos = ladder.index(default_rung) if default_rung in ladder else 0
            reason = "stable"
            trial = None
            seen = set()
            while True:
                if pos in seen:
                    reason = "cycle"
                    break
                seen.add(pos)
                r = ladder[pos]
                est = estimate_at(c, r, s, binned, fading)
                if est is None:
                    reason = "no estimate"
                    break
                t = target(ent[rung_key(r)], "bulk", est)
                if t < pos:
                    pos = t
                elif t > pos:
                    if cv[(c, ladder[up(pos)])].at(s) > lim:
                        reason = "next rung fails, capped"
                        trial = ladder[up(pos)]
                        break
                    pos = up(pos)
                else:
                    break
            r = ladder[pos]
            if reason == "stable" and (c, r, s) not in binned:
                reason = "stable, estimate extrapolated"
            bl = max(ladder, key=lambda x: (good(x), -ladder.index(x)))
            ba = max(rungs, key=lambda x: (good(x), -rungs.index(x)))
            g = good(r)
            if trial is not None:
                # Once the cap has doubled to rx_ceiling_cap, one failed trial every
                # rx_ceiling_cap + clean_run + 1 bursts.
                n = table["rx_ceiling_cap"] + table["clean_run"]
                g = (g * n + good(trial)) / (n + 1)
            # The probe of corpus-format.md 6.2 step 6 (P7-9c; interp C-1291): a step
            # up on probe_run clean bursts whatever the estimate says, back down only
            # through the receiver's cap.
            q = pos
            while up(q) is not None and cv[(c, ladder[up(q)])].at(s) <= lim:
                q = up(q)
            gp = good(ladder[q])
            if up(q) is not None:
                n = table["rx_ceiling_cap"] + table["probe_run"]
                gp = (gp * n + good(ladder[up(q)])) / (n + 1)
            rows.append([c, s, r, tenths(g), ladder[q], tenths(gp), bl, tenths(good(bl)), ba, tenths(good(ba)), reason])
    return tsv(rows)


def build(caldir):
    meta, rate, channels, rungs, point, binned, errbin = load(caldir)
    cv = curves(point)
    global POINT
    POINT = point
    ladder, need, kept = build_ladder(cv, rate, rungs, point)
    fading = {c["name"]: bool(c["paths"]) for c in meta["channels"]}
    out = {}
    for name, weights, kind in (("drc-table.json", DEFAULT_WEIGHTS, "default: unknown channel and radio"),
                                ("drc-table-ssb.json", SSB_WEIGHTS, "comparison: SSB band-pass channels only")):
        table = build_table(weights, cv, point, binned, rate, rungs, ladder, kept)
        if name == "drc-table.json":
            out[name] = table_json({"source": source(meta, caldir, weights, kind), "table": table})
            out["settle.tsv"] = settle(table, channels, cv, point, binned, rate, rungs, ladder, DEFAULT_SPEED, fading)
        else:
            out["settle-ssb.tsv"] = settle(table, channels, cv, point, binned, rate, rungs, ladder, DEFAULT_SPEED, fading)
    out["rungs.tsv"] = rungs_tsv(channels, rungs, rate, cv, ladder)
    out["error-vs-estimate.tsv"] = errbin_tsv(errbin, channels, rungs)
    out["estimate-summary.tsv"] = estimate_summary(errbin, channels, rungs)
    out["next-check.tsv"] = next_check(caldir, cv, binned, channels)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("caldir")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    out = build(args.caldir)
    bad = 0
    for name, text in out.items():
        path = os.path.join(args.caldir, name)
        if args.check:
            try:
                with open(path, encoding="ascii") as f:
                    same = f.read() == text
            except FileNotFoundError:
                same = False
            if not same:
                print("differs: " + path)
                bad = 1
        else:
            with open(path, "w", encoding="ascii", newline="\n") as f:
                f.write(text)
            print("wrote " + path)
    return bad


if __name__ == "__main__":
    sys.exit(main())
