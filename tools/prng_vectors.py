#!/usr/bin/env python3
"""Reference SplitMix64 and uniform-draw generator for docs/prng.md.

Writes corpus/prng/splitmix64.jsonl (the machine-readable test values) and
prints the same values as a Markdown table for the document. Every value is
computed with 64-bit wrap-around arithmetic only, exactly as specified in
docs/prng.md. Python 3, standard library only.

Usage: python3 tools/prng_vectors.py [--write]
"""
import json
import os
import sys

MASK = (1 << 64) - 1
GAMMA = 0x9E3779B97F4A7C15
MUL1 = 0xBF58476D1CE4E5B9
MUL2 = 0x94D049BB133111EB


class SplitMix64:
    def __init__(self, seed):
        self.state = seed & MASK

    def next_u64(self):
        self.state = (self.state + GAMMA) & MASK
        z = self.state
        z = ((z ^ (z >> 30)) * MUL1) & MASK
        z = ((z ^ (z >> 27)) * MUL2) & MASK
        return z ^ (z >> 31)

    def uniform(self, n):
        """Integer uniform in [0, n), n >= 1, by rejection. Returns (value, draws used)."""
        if n < 1 or n > MASK:
            raise ValueError("n out of range")
        threshold = ((MASK + 1) - n) % n  # equals 2^64 mod n
        used = 0
        while True:
            x = self.next_u64()
            used += 1
            if x >= threshold:
                return x % n, used


def h64(v):
    return "%016x" % v


def cases():
    out = []
    # Raw outputs.
    for cid, seed, count in [
        ("splitmix64-seed-0", 0, 10),
        ("splitmix64-seed-1", 1, 5),
        ("splitmix64-seed-0123456789abcdef", 0x0123456789ABCDEF, 5),
        ("splitmix64-seed-ffffffffffffffff", MASK, 5),
    ]:
        g = SplitMix64(seed)
        out.append({
            "id": cid,
            "seed": h64(seed),
            "op": "next_u64",
            "results": [h64(g.next_u64()) for _ in range(count)],
        })
    # Uniform draws. Each result is [value, draws_used].
    for cid, seed, n, count in [
        ("uniform-seed-0-n-16", 0, 16, 10),
        ("uniform-seed-0-n-3", 0, 3, 10),
        ("uniform-seed-0-n-1", 0, 1, 3),
        ("uniform-seed-2a-n-1000", 0x2A, 1000, 10),
        ("uniform-seed-0-n-8000000000000001", 0, (1 << 63) + 1, 10),
    ]:
        g = SplitMix64(seed)
        res = []
        for _ in range(count):
            v, used = g.uniform(n)
            res.append({"value": h64(v), "draws": used})
        out.append({
            "id": cid,
            "seed": h64(seed),
            "op": "uniform",
            "n": h64(n),
            "results": res,
            "state_after": h64(g.state),
        })
    return out


def main():
    all_cases = cases()
    # Sanity check against the widely published first SplitMix64 output for seed 0.
    assert all_cases[0]["results"][0] == "e220a8397b1dcdaf", all_cases[0]["results"][0]
    for c in all_cases:
        print("### %s (seed 0x%s, op %s%s)" % (c["id"], c["seed"], c["op"],
              ", n 0x" + c["n"] if "n" in c else ""))
        for i, r in enumerate(c["results"]):
            if isinstance(r, dict):
                print("| %d | 0x%s | %d |" % (i, r["value"], r["draws"]))
            else:
                print("| %d | 0x%s |" % (i, r))
        print()
    if "--write" in sys.argv:
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "corpus", "prng")
        os.makedirs(root, exist_ok=True)
        with open(os.path.join(root, "splitmix64.jsonl"), "w", newline="\n") as f:
            for c in all_cases:
                f.write(json.dumps(c, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
