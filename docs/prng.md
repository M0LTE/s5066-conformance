# The specified pseudo-random generator

Every random choice the core makes comes from one generator, specified here, so the C# and C++ cores draw identical sequences from the same seed and produce identical T2 traces (plan sections 3.2, 7.2 and 11.3). The standard asks for randomness but names no generator: Annex K gives only the range of the CSMA jitter draw [Ed4 K.3.2.3, p.K-10]. The choice below is ours.

## 1. Choice: SplitMix64

SplitMix64 (Steele, Lea and Flood, "Fast splittable pseudorandom number generators", OOPSLA 2014; the constants are those of the widely used public-domain reference code by Sebastiano Vigna). Reasons:

- 64 bits of state and three lines of arithmetic: add, xor, shift and multiply on unsigned 64-bit integers, all with wrap-around. C# `ulong` and C++ `uint64_t` do exactly that, with no platform-dependent behaviour.
- No 128-bit multiply, no floating point, no division in the generator itself.
- Every seed, including 0, is valid.
- Good statistical quality for this use. It is not cryptographic, and nothing here needs it to be.

## 2. Algorithm

State: one unsigned 64-bit integer `s`. All arithmetic is modulo 2^64. `>>` is a logical (unsigned) right shift.

```
next_u64():
    s = s + 0x9E3779B97F4A7C15
    z = s
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9
    z = (z ^ (z >> 27)) * 0x94D049BB133111EB
    return z ^ (z >> 31)
```

C# note: use `ulong` and an `unchecked` context, or the multiplications throw in a checked build. C++ note: use `uint64_t`; unsigned overflow is defined.

## 3. Seeding and use

- The seed is the configuration value `prng_seed` (corpus-format.md section 6), a 64-bit value written as 16 hex digits. The initial state is the seed itself: `s = seed`.
- One generator per core, created with the core and never re-seeded. Configuration changes at run time do not re-seed it.
- The core draws only at registered draw sites (section 6), and only through `uniform` below. A draw at any other place, or a different number of draws, changes every later value and breaks the traces, which is the point: it makes such a change visible.
- The host (D3) seeds from a real entropy source, since it does not need reproducibility. Tests seed from the configuration.

## 4. Uniform integer in [0, n)

For 1 <= n <= 2^64 - 1, without modulo bias, by rejection:

```
uniform(n):
    threshold = (0 - n) mod n        // in 64-bit unsigned arithmetic; equals 2^64 mod n
    loop:
        x = next_u64()
        if x >= threshold:
            return x mod n
```

Why it is unbiased: the accepted values run from `threshold` to 2^64 - 1, which is 2^64 - (2^64 mod n) values, a whole multiple of n, so each remainder is equally likely.

Rules that both implementations must keep:

- `uniform` always calls `next_u64` at least once, even for n = 1, which returns 0. So the number of draws does not depend on n being 1.
- A rejected draw is consumed. For the small n used by the core, rejection has probability below 2^-59 (n = 16 gives threshold 0, so it never rejects), but the large-n test values below make sure the loop is right.
- In C#, compute `threshold` as `(0UL - n) % n`, or `unchecked(-n) % n`. In C++, `(0 - n) % n` with `n` of type `uint64_t`, or `(~n + 1) % n`.

## 5. Test values

Computed with [tools/prng_vectors.py](../tools/prng_vectors.py), which uses only 64-bit wrap-around arithmetic. The same values are in machine-readable form in `corpus/prng/splitmix64.jsonl`. The first value for seed 0 agrees with the widely published SplitMix64 reference output, 0xE220A8397B1DCDAF.

### next_u64, seed 0x0000000000000000

| Draw | Value |
|---|---|
| 0 | 0xe220a8397b1dcdaf |
| 1 | 0x6e789e6aa1b965f4 |
| 2 | 0x06c45d188009454f |
| 3 | 0xf88bb8a8724c81ec |
| 4 | 0x1b39896a51a8749b |
| 5 | 0x53cb9f0c747ea2ea |
| 6 | 0x2c829abe1f4532e1 |
| 7 | 0xc584133ac916ab3c |
| 8 | 0x3ee5789041c98ac3 |
| 9 | 0xf3b8488c368cb0a6 |

### next_u64, other seeds

| Seed | Draw 0 | Draw 1 | Draw 2 |
|---|---|---|---|
| 0x0000000000000001 | 0x910a2dec89025cc1 | 0xbeeb8da1658eec67 | 0xf893a2eefb32555e |
| 0x0123456789abcdef | 0x157a3807a48faa9d | 0xd573529b34a1d093 | 0x2f90b72e996dccbe |
| 0xffffffffffffffff | 0xe4d971771b652c20 | 0xe99ff867dbf682c9 | 0x382ff84cb27281e9 |

### uniform(16), seed 0 (the default CSMA jitter draw)

Ten draws in order: 15, 4, 15, 12, 11, 10, 1, 12, 3, 6. Each used one `next_u64`.

### uniform(3), seed 0

Ten draws in order: 1, 0, 1, 1, 1, 0, 2, 2, 2, 2.

### uniform(1000), seed 0x000000000000002a

Ten draws in order: 413, 291, 858, 764, 250, 62, 925, 908, 5, 974.

### uniform(0x8000000000000001), seed 0 (exercises rejection)

Here the threshold is 0x7fffffffffffffff, so about half of all draws are rejected.

| Call | Value | next_u64 calls used |
|---|---|---|
| 0 | 0x6220a8397b1dcdae | 1 |
| 1 | 0x788bb8a8724c81eb | 3 |
| 2 | 0x4584133ac916ab3b | 4 |
| 3 | 0x73b8488c368cb0a5 | 2 |
| 4 | 0x42d326e0055bdef5 | 2 |

### Machine-readable schema

Each line of `corpus/prng/splitmix64.jsonl` is one of:

- `{"id", "seed", "op": "next_u64", "results": [hex64, ...]}`: create a generator with `seed`, call `next_u64` once per result.
- `{"id", "seed", "op": "uniform", "n": hex64, "results": [{"value": hex64, "draws": int}, ...], "state_after": hex64}`: create a generator with `seed`, call `uniform(n)` once per result; `draws` is the number of `next_u64` calls that call used, and `state_after` is the state `s` after the last call.

All 64-bit values are 16 lower-case hex digits without `0x`.

## 6. Draw sites

Every place the core draws is registered here, with the matrix row that requires it, in the change that adds it. Order matters: if one input causes several draws, they happen in the order listed in the scenario's outputs.

| Site | Draw | Defined by |
|---|---|---|
| `csma.jitter` | `uniform(csma.num_cont_slots)`, the slot count for the contention wait in jitter mode [Ed4 K.3.2.3, p.K-10; plan 7.2] | TODO (matrix row for K.3.2.3) |
