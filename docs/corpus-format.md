# Corpus format

This is the contract between the C# implementation and the C++ port. Both read the same files and must produce the same bytes and the same outputs. Where this document and an implementation disagree, the implementation is wrong or this document gets a versioned fix (see Versioning). It never describes protocol behaviour itself: that comes from the requirement rows a case cites.

Related documents: [prng.md](prng.md) (the random number generator) and [harness-contract.md](harness-contract.md) (what each language's test harness does).

## 1. Layout

```
corpus/
  VERSION                  corpus version, one line, MAJOR.MINOR.PATCH
  t1/*.jsonl               T1 codec vectors, one case per line
  t2/defaults.json         the base node configuration every T2 scenario starts from
  t2/<area>/<name>.jsonl   T2 scenario traces, one scenario per file
  prng/splitmix64.jsonl    PRNG test values (prng.md)
tools/
  validate_corpus.py       schema validator, run by CI
  prng_vectors.py          computes the PRNG test values
```

`<area>` is a short lower-case name for the sublayer or feature under test, for example `dts-nonarq`, `dts-arq`, `cas`, `csma`, `sis`. T1 file names group related cases and carry no meaning of their own.

## 2. Rules common to every file

- Files are UTF-8 with ASCII content only, Unix line endings, and one JSON object per line (JSON Lines). Blank lines are not allowed. There are no comment lines; use the `note` field.
- **Bytes** are lower-case hex strings with no separators, two digits per byte, for example `"90eb"`. An empty byte string is `""`.
- **Integers** are JSON numbers with no fraction or exponent, in the range 0 to 2^53-1 unless a field says otherwise, so every JSON parser reads them exactly. A value that needs 64 bits (a PRNG seed or output) is a 16-digit lower-case hex string without a `0x` prefix.
- **No floating point** anywhere. Quantities that are naturally fractional use an integer unit, for example SNR in tenths of a dB.
- **Booleans** are `true` or `false`, never 0 or 1.
- **Addresses** are dotted-decimal strings `"w.x.y.z"` holding the 28-bit address value: w is 0 to 15, x, y and z are 0 to 255 [Ed4 C.4.2.6, pp.C-14 to C-15]. A group address is not written as 16.x.y.z; the group flag is a separate field of the PDU that carries it.
- **Objects are compared as values:** key order does not matter, but every key must be present with the exact type. A decoder output that omits a field, or adds one, does not match.
- Unknown keys are errors. A new key needs a corpus version bump (section 8) and a validator update.

### Case ids

Every case and scenario has an `id` that is unique across the whole corpus: lower-case letters, digits, `.`, `_` and `-`, starting with a letter or digit. Ids are never reused or renamed, like matrix row ids. A wrong case is fixed in place (patch version) or retired by deleting it (minor version), and its id is not given to anything else.

### Matrix rows

Every case and scenario has `rows`, a non-empty list of matrix row ids (`C-0042`, see `matrix/README.md`) that the case gives evidence for. Until the matrix row exists, the entry is the string `"TODO"`. The validator accepts `"TODO"` by default and rejects it in strict mode, which CI turns on once the matrix is complete (harness-contract.md section 4).

### Sources

Every case has `source`, a short citation of where the expected bytes or behaviour come from: an annex reference such as `"Ed4 C.4.2.8, p.C-18"`, a JITC test procedure page such as `"JITC TP p.49 step 11"`, or `"derived"` for a case we built by changing a sourced one (the `note` says how). Sources are cited, never quoted.

## 3. T1 codec vectors

One line per case, in any `t1/*.jsonl` file.

| Key | Type | Meaning |
|---|---|---|
| `id` | string | Case id (section 2). |
| `kind` | string | Which codec, from the kind registry below. |
| `dir` | string | `encode` (value to bytes), `decode` (bytes to value or error) or `both`. |
| `rows` | list of strings | Matrix row ids or `"TODO"`. |
| `source` | string | Citation. |
| `value` | object | The structured value. Present unless `error` is. |
| `bytes` | hex | The encoded bytes, exactly as sent on air or on the wire. |
| `error` | string | Expected error kind for malformed input. Only with `dir` = `decode`, and then `value` is absent. |
| `peer_edition` | string | `dpdu` kind only: `any`, `ed3` or `ed4` (section 3.3). |
| `note` | string | Optional free text for humans. Harnesses ignore it. |

Meaning of `dir`:

- `encode`: encoding `value` must give exactly `bytes`.
- `decode`: decoding `bytes` must give exactly `value`, or fail with exactly `error`.
- `both`: both of the above.

A decode case consumes the whole of `bytes`. T1 bytes hold exactly one PDU; finding PDUs in a stream (sync search, trailing bytes) is tested in T2.

### 3.1 Error kinds

A decoder that rejects input reports one of these kinds. Harnesses compare the kind only, never an error message.

| Kind | Meaning |
|---|---|
| `truncated` | The input ends before the PDU does. |
| `bad_sync` | The PDU does not start with the expected sync or preamble bytes. |
| `header_crc` | The header CRC does not match. |
| `bad_header_size` | The size-of-header field is impossible for the PDU type. |
| `bad_address_size` | The size-of-address field is zero or otherwise impossible. |
| `trailing_bytes` | Bytes remain after the PDU in a T1 decode case. |
| `invalid_field` | A field holds a value the codec cannot represent. |

Where several apply, the kind is decided by the check order its kind registers (for `dpdu`, section 3.3), so both languages report the same kind. A CRC-32 mismatch on a segment is not an error kind: Annex C requires the header to be processed when its own CRC is valid, whatever the segment CRC says [Ed4 C.4.2.8, p.C-17], so the decoder returns the value with `segment_crc_ok` false.

### 3.2 Kind registry

A kind is added to this table, and to the validator, in the same change that adds its first case.

| Kind | Value object | `bytes` |
|---|---|---|
| `crc16` | `{"data": hex, "register": int}` | The 2 header CRC bytes as transmitted. |
| `crc32` | `{"data": hex, "register": int}` | The 4 segment CRC bytes as transmitted. |
| `dpdu` | Section 3.3 | One whole D_PDU from its first sync byte to its last CRC byte. |

For `crc16` and `crc32`, `register` is the final value of the Annex C shift-register code example after all bytes of `data` [Ed4 C.4.2.8, p.C-18; C.4.2.11, p.C-21], and `bytes` is that register sent least significant byte first [Ed4 pp.C-18, C-22]. These kinds are `encode` only.

Kinds planned for phase 1 and not yet registered: `eow`, `cpdu`, `spdu`, `sis_frame`, `address`, `speed_interleaver`.

### 3.3 The `dpdu` value

```json
{"type": 15, "eow": 0, "eot": 0, "address_size": 2, "dst": "0.0.0.5", "src": "0.0.0.100",
 "fields": {"received_frame_type": 0, "reason": 2}}
```

| Key | Meaning |
|---|---|
| `type` | D_PDU type, 0 to 15 [Ed4 Table C-2, p.C-8]. |
| `eow` | The 12-bit EOW field as one integer, 0 to 4095, EOW type in the top 4 bits [Ed4 C.4.2.2, pp.C-12 to C-13]. The `eow` kind will give its structure. |
| `eot` | The EOT field, 0 to 255, in half seconds [Ed4 C.4.2.3, p.C-13]. |
| `address_size` | The size-of-address field m, 1 to 7 [Ed4 C.4.2.4, p.C-13]. It is part of the value because the sender chooses it: leading zero nibbles may be dropped. |
| `dst`, `src` | Destination and source addresses. Each must fit in 4m bits. |
| `fields` | The type-specific header fields, below. |
| `segment` | I and I+C frame types only (0, 2, 4, 7, 8, 9, 11, and 10 or 13 when they carry data): the segmented C_PDU bytes. |
| `segment_crc_ok` | Present exactly when `segment` is. On decode, whether the CRC-32 matched. Must be `true` in `encode` and `both` cases. |

Not in the value, because they follow from it: the sync bytes, the size-of-header field, the size-of-segment field, and both CRCs. An encoder computes them; a decoder checks them.

`peer_edition` says which edition's type table the decoder applies:

- `any`: the type means the same to Ed3 and Ed4 peers (types 0 to 8 and 15).
- `ed4`: decode as from an Ed4 peer.
- `ed3`: decode as from an Ed3 peer. Types 9 to 14 are then undefined: `fields` is `{"undefined": true, "type_specific": hex}` holding the bytes between the address field and the header CRC, and there is no `segment`.

Registered `fields` sets (a type not listed here cannot appear in a case until its set is registered):

| Type | Fields (Annex C figure) |
|---|---|
| 0 | `c_pdu_start`, `c_pdu_end`, `deliver_in_order`, `drop_c_pdu`, `tx_win_uwe`, `tx_win_lwe` (booleans), `tx_fsn` (0 to 255) [Ed4 Fig C-9, p.C-23] |
| 3 | `full_reset_cmnd`, `reset_tx_win_rqst`, `reset_rx_win_cmnd`, `reset_ack` (booleans), `new_rx_lwe` (0 to 255), `reset_frame_id` (0 to 255) [Ed4 Fig C-19, p.C-36] |
| 7, 8 | `c_pdu_id` (0 to 4095), `deliver_in_order`, `group_address` (booleans), `c_pdu_size`, `c_pdu_segment_offset`, `c_pdu_reception_window` (0 to 65535) [Ed4 Fig C-24, p.C-46; Fig C-33, p.C-51] |
| 15 | `received_frame_type` (0 to 15), `reason` (0 to 15) [Ed4 Fig C-36, p.C-54] |

D_PDU decode check order. The decoder stops at the first failing step:

1. Fewer than 2 bytes: `truncated`.
2. The first two bytes are not `90 eb` [Ed4 C.4.2, p.C-11]: `bad_sync`.
3. Fewer than 6 bytes: `truncated`.
4. Size of address is 0: `bad_address_size`.
5. Size of header is not possible for the type under `peer_edition` (below the type's minimum, or not equal to its fixed size): `bad_header_size`.
6. Fewer bytes than 2 + (size of header) + (size of address): `truncated`.
7. Header CRC mismatch: `header_crc`.
8. For a type with a segment, fewer bytes than the header plus the size of segment plus 4: `truncated`.
9. A field value the codec cannot represent: `invalid_field`.
10. Bytes left over: `trailing_bytes`.

Fields marked NOT USED in the standard are not in the value; encoders write them as zero [Ed4 C.4.2, p.C-12].

### 3.4 Example

```json
{"id": "crc16-annex-c-example", "kind": "crc16", "dir": "encode", "rows": ["TODO"], "source": "Ed4 C.4.2.8, pp.C-18 to C-19", "value": {"data": "f0000047056402", "register": 7775}, "bytes": "5f1e"}
```

## 4. T2 scenario traces

A scenario drives one sans-IO core (plan section 3.2) through a script of timestamped inputs and lists every output the core must produce. One scenario per file, `corpus/t2/<area>/<name>.jsonl`.

### 4.1 File structure

Line 1 is the header:

| Key | Meaning |
|---|---|
| `scenario` | Scenario id (section 2 rules). |
| `rows`, `source` | As for T1. |
| `description` | One line saying what the scenario shows. |
| `config` | The node configuration overlay (section 6). May be `{}`. |
| `note` | Optional. |

Every following line is one step: either an input to the core (has `in`) or an expected output (has `out`).

```json
{"t": 0, "in": "sis_connect", "conn": 1}
{"t": 0, "in": "sis_bytes", "conn": 1, "bytes": "..."}
{"out": "sis_bytes", "conn": 1, "bytes": "..."}
{"t": 2500, "in": "timer_expired", "name": "csma.cont_wait"}
{"out": "transmit", "bytes": "90eb...", "wn": 2, "interleaver": "long", "k": 7, "eom": true}
```

The outputs listed after an input, up to the next input, are exactly the outputs the core produces while handling that input, in the order it produces them. An input followed by no output lines means the core must produce nothing. Outputs carry no `t`: they happen at the time of the input that caused them.

### 4.2 Inputs

Each input has `t` and `in`, plus the keys listed.

| `in` | Class | Keys | Meaning |
|---|---|---|---|
| `config` | 0 | `set` (object) | Change configuration at run time; `set` is an overlay, as in section 6. |
| `timer_expired` | 1 | `name` | A timer the core started has reached its deadline. |
| `burst_started` | 2 | none | The modem detected the start of a burst (carrier detect) [plan 5.1]. |
| `bytes_received` | 2 | `bytes` | Decoded bytes from one modem block [plan 5.1]. |
| `burst_ended` | 2 | `reason`, `wn`, `interleaver`, `k`, `snr_tenth_db`, `blocks` | End of a received burst and its quality [plan 5.1]. |
| `transmit_done` | 2 | none | The core's own transmission has finished on air. |
| `channel_busy` | 2 | `busy` (boolean) | The optional external busy input [plan 7.3]. |
| `sis_connect` | 3 | `conn` | A SIS client connected; `conn` is a positive integer chosen by the trace. |
| `sis_bytes` | 3 | `conn`, `bytes` | Bytes from that client's stream. They may hold part of a frame or several frames. |
| `sis_disconnect` | 3 | `conn` | The client went away. |

`burst_ended` keys: `reason` is one of `eom`, `signal_lost`, `terminated`; `wn` is the waveform number; `interleaver` is from the interleaver enum below; `k` is the constraint length; `snr_tenth_db` is an integer SNR in tenths of a dB, or `null` when the modem gives none; `blocks` is the number of blocks decoded.

Interleaver enum: `ultra_short`, `very_short`, `short`, `medium`, `long`, `very_long` (the Ed4 interleaver names, plan section 5.3).

### 4.3 Outputs

| `out` | Keys | Meaning |
|---|---|---|
| `transmit` | `bytes`, `wn`, `interleaver`, `k`, `eom` | One whole transmission, sent as one modem burst [plan 5.1, 5.4]. |
| `terminate_receive` | none | Ask the modem to stop the current reception [plan 5.1]. |
| `set_max_input_blocks` | `n` | Change the modem's maximum input data blocks [plan 5.1]. |
| `timer_start` | `name`, `ms` | Start, or restart, the named timer to expire `ms` milliseconds from now. |
| `timer_cancel` | `name` | Stop the named timer. Cancelling a timer that is not running is allowed and is still an output. |
| `sis_bytes` | `conn`, `bytes` | Bytes to write to a SIS client's stream. |
| `sis_close` | `conn` | Close that client connection. |
| `link_state` | `peer`, `state` | A link to `peer` changed state. State names are registered with the CAS work (section 4.6). |

### 4.4 Time model

- Time is an integer count of milliseconds since the core was created, which is time 0. The core's clock is the `t` of the input it is handling; it never reads time any other way.
- `t` never decreases from one input to the next.
- A timer's deadline is the `t` of the input that started it plus `ms`. `ms` is at least 1; a core that wants "now" acts now instead of starting a timer. Starting a timer that is already running replaces its deadline.
- Timers do not fire by themselves. The trace lists every expiry as a `timer_expired` input at exactly the deadline, and the harness checks it (harness-contract.md section 2). An input at time t may only be fed once every running timer with a deadline at or before t has been listed as expired.

### 4.5 Simultaneous events

When inputs share the same `t`, they are handled in class order (the Class column in section 4.2): configuration, then timer expiries, then modem events, then SIS events. A trace must list them in that order and the validator rejects one that does not. Within a class:

- Timer expiries at the same time are listed in the order the timers were last started.
- Modem events are listed in the order the modem reports them.
- SIS events are listed in the order the bytes or connections arrived.

The host process (D3) follows the same order when real events arrive in the same millisecond, so a trace is also a statement about the real node. The order is our choice; the standard does not state one.

### 4.6 Names

Timer names have the form `<sublayer>.<timer>`, optionally followed by `/<qualifier>` when one timer exists per peer or per connection, for example `csma.cont_wait` or `dts.ack_wait/0.0.1.2`. Sublayers are `sis`, `cas`, `dts`, `csma`, `drc` and `station`. Names use lower-case letters, digits and `_` in each part.

Each timer name, and each `link_state` state name, is registered in a table in this section by the change that first uses it, with the matrix row that defines it. A trace using an unregistered name is invalid.

| Timer name | Defined by |
|---|---|
| (none yet) | |

| Link state | Defined by |
|---|---|
| (none yet) | |

## 5. The modem fixture

The core needs burst durations from the modem port's `PlanBurst` (plan 5.1) before it transmits, for example to compute EOT. In T2 the harness answers those calls from a fixture in the configuration, so traces do not depend on the real modem. The fixture values are test data, not claims about MIL-STD-188-110D.

```json
"modem": {"preamble_ms": 720, "flush_ms": 0,
          "waveforms": [{"wn": 6, "interleaver": "short", "block_bytes": 192, "block_ms": 1000}]}
```

For a plan request with waveform number `wn`, interleaver `i` and `n` bytes, the harness finds the entry with that `wn` and `interleaver` (missing entry: the case fails with `unplanned_waveform`) and returns:

- blocks = max(1, ceil(n / block_bytes)), using integer arithmetic;
- bytes per block = block_bytes;
- duration_ms = preamble_ms + blocks x block_ms + flush_ms.

## 6. Node configuration

`corpus/t2/defaults.json` holds one JSON object: the full base configuration. A scenario's `config` is an overlay merged into it: objects merge key by key, recursively; any other value, including a list, replaces the base value. A key in the overlay that is not in the base is an error. `null` in the base means "no default": a scenario that exercises that setting must give a value, and a core that needs a `null` setting fails the case.

The base configuration and where each default comes from:

| Key | Default | Source |
|---|---|---|
| `local_address` | `null` | Per node. |
| `address_size` | `null` | Size-of-address field the node sends. |
| `prng_seed` | `"0000000000000000"` | [prng.md](prng.md) |
| `csma.mode` | `null` | `jitter` or `slotted`, network-wide (decision D7). |
| `csma.cont_slot_width_ms` | 3000 | [Ed4 K Table 7, p.K-12] |
| `csma.num_cont_slots` | 16 | [Ed4 K Table 7, p.K-12] |
| `csma.lbt_wait_dcd_ms` | 30000 | [Ed4 K Table 7, p.K-12] |
| `csma.lbt_wait_vdcd_ms` | 3000 | [Ed4 K Table 7, p.K-12] |
| `csma.node_slot_position` | `null` | Per node, slotted mode only [Ed4 K.2.2, p.K-4] |
| `modem.preamble_ms` | `null` | Section 5 |
| `modem.flush_ms` | `null` | Section 5 |
| `modem.waveforms` | `[]` | Section 5 |

New settings are added to `defaults.json` and this table together, each with its source, in the change that first needs them. Only settings the standard makes configurable, or that the plan records as ours, go in (plan 3.2 principle 5).

## 7. PRNG cases

`corpus/prng/splitmix64.jsonl` holds the generator's test values in the schema given in [prng.md](prng.md) section 5. Every harness runs them before any T2 scenario.

## 8. Versioning

`corpus/VERSION` holds `MAJOR.MINOR.PATCH`, and each release is a git tag `vMAJOR.MINOR.PATCH` on this repository. Implementations pin a tag (as a submodule or package) and state the version they pass.

- **MAJOR**: a format change that an existing harness cannot read correctly, for example a new required key or a changed meaning.
- **MINOR**: new cases, new kinds, new registered names or settings, retired cases. An older harness may meet kinds or inputs it does not know; it must report those cases as unsupported, not as passed.
- **PATCH**: corrections to existing cases (wrong expected bytes, wrong row ids, notes).

Before 1.0.0 the format is still settling, and a MINOR bump may also carry format changes.
