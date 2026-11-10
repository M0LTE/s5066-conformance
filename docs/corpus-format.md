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

`<area>` is a short lower-case name for the sublayer or feature under test, for example `dts-nonarq`, `dts-arq`, `cas`, `csma`, `sis`. T1 file names group related cases and carry no meaning of their own. No other files may be under `corpus/`, and T1 files are not in subdirectories.

## 2. Rules common to every file

- Files are ASCII only (no byte order mark), Unix line endings, and one JSON object per line (JSON Lines). Every line, including the last, ends with a newline. Blank lines are not allowed. There are no comment lines; use the `note` field. A key may not appear twice in one object, and `NaN`, `Infinity` and other non-JSON constants are not allowed.
- **Bytes** are lower-case hex strings with no separators, two digits per byte, for example `"90eb"`. An empty byte string is `""`. Harnesses compare byte strings as bytes, after decoding the hex, so the case of hex a harness prints in a failure report does not matter.
- **Integers** are JSON numbers with no fraction or exponent, in the range 0 to 2^53-1 unless a field says otherwise, so every JSON parser reads them exactly. The only signed field so far is `snr_tenth_db` (section 4.2). A value that needs 64 bits (a PRNG seed or output) is a 16-digit lower-case hex string without a `0x` prefix.
- **No floating point** anywhere. Quantities that are naturally fractional use an integer unit, for example SNR in tenths of a dB.
- **Booleans** are `true` or `false`, never 0 or 1.
- **Addresses** are dotted-decimal strings `"w.x.y.z"` holding the 28-bit address value: w is 0 to 15, x, y and z are 0 to 255 [Ed4 C.4.2.6, pp.C-14 to C-15]. A group address is not written as 16.x.y.z; the group flag is a separate field of the PDU that carries it.
- **Objects are compared as values:** key order does not matter, but every key must be present with the exact type. A decoder output that omits a field, or adds one, does not match.
- Unknown keys are errors for the validator. A new key needs a corpus version bump (section 8) and a validator update. A harness that meets a key it does not know reports that case or scenario as `unsupported` (harness-contract.md section 1), never as passed or failed.

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
| `bad_version` | `sis_frame` and `sis_stream`: the version byte is not 0. |
| `bad_size` | `sis_frame` and `sis_stream`: the size field is 0. |
| `unknown_type` | `sis_frame` and `sis_stream`: the type byte is 0 or above 27 (and so not a primitive of this edition or a deprecated one). |
| `deprecated_type` | `sis_frame` and `sis_stream`: the type is a hard link (6 to 13) or expedited data (24 to 27) primitive. It is recognised and reported, never decoded. |
| `bad_length` | `sis_frame` and `sis_stream`: the body length does not fit the type's layout, or an inner size field disagrees with the body. |
| `bad_compression` | `cftp_gzip`: the data do not decompress (bad header, bad check value, cut short). |

Where several apply, the kind is decided by the check order its kind registers (for `dpdu`, section 3.3), so both languages report the same kind. A CRC-32 mismatch on a segment is not an error kind: Annex C requires the header to be processed when its own CRC is valid, whatever the segment CRC says [Ed4 C.4.2.8, p.C-17], so the decoder returns the value with `segment_crc_ok` false.

### 3.2 Kind registry

A kind is added to this table, and to the validator, in the same change that adds its first case.

| Kind | Value object | `bytes` |
|---|---|---|
| `crc16` | `{"data": hex, "register": int}` | The 2 header CRC bytes as transmitted. |
| `crc32` | `{"data": hex, "register": int}` | The 4 segment CRC bytes as transmitted. |
| `dpdu` | Section 3.3 | One whole D_PDU from its first sync byte to its last CRC byte. |
| `cpdu` | Section 3.5 | One whole CAS C_PDU. |
| `spdu` | Section 3.6 | One whole SIS peer S_PDU. |
| `eow` | Section 3.8 | The 12-bit EOW as 2 bytes: the EOW type, then the contents byte. |
| `address` | Section 3.9 | The m-byte address field. |
| `speed_interleaver` | `{"interleaver": 0-7, "speed": 0-31}` | The one speed and interleaver byte [Ed4 Figure C-49, p.C-72]: interleaver in bits 7-5, speed in bits 4-0. |
| `drc_smooth` | `{"weight": 1-16, "samples": [int -32767 to 32767, or null, ...]}` | The smoothed estimate after each sample (section 6.2), each as 2 bytes, 16-bit two's complement, most significant byte first; `8000` while still empty. Encode only. |
| `drc_ed3_basic_rate` | `{"wn", "interleaver"}`: a rung our ladder can hold (WN 1 to 8 or 13; ultra_short, short, medium, long) | The 2-byte ED3-BASIC-RATE EOW we send for that rung (section 6.2; interp C-1273), as kind `eow` encodes it. Encode only. |
| `sis_frame` | Section 3.7 | One whole SIS Access Protocol frame, from the first preamble byte to the last body byte. |
| `sis_stream` | Section 3.7 | A byte stream made of several frames, junk and partial frames, with the events a streaming decoder gives. |
| `rcop1` | Section 3.10 | One RCOPv1 PDU of CFTP: the 4-octet header, then the data. |
| `bftp1` | Section 3.10 | One whole BFTPv1 PDU, from its DLE STX to the last file octet. |
| `cftp_mail` | Section 3.10 | One uncompressed CFTP mail file. |
| `cftp_recipients` | Section 3.10 | One CFTP RecipientList field, without its line feed. |
| `cftp_gzip` | Section 3.10 | Compressed CFTP data. Decode only. |

For `crc16` and `crc32`, `register` is the final value of the Annex C shift-register code example after all bytes of `data` [Ed4 C.4.2.8, p.C-18; C.4.2.11, p.C-21], and `bytes` is that register sent least significant byte first [Ed4 pp.C-18, C-22]. These kinds are `encode` only.

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
| `dst`, `src` | Destination and source addresses. Each must fit in 4m bits. The m-byte address field holds the 8m-bit number (dst x 2^(4m)) + src, most significant byte first [Ed4 C.4.2.6, Figures C-4(a) and C-4(b), pp.C-14 to C-15]. |
| `fields` | The type-specific header fields, below. |
| `segment` | I and I+C frame types only (0, 2, 4, 7, 8, 9, 11): the segmented C_PDU bytes. Types 10 and 13 never use it (see above and the type 13 row). |
| `segment_crc_ok` | Present exactly when `segment` is. On decode, whether the CRC-32 matched. Must be `true` in `encode` and `both` cases. |

Not in the value, because they follow from it: the sync bytes, the size-of-header field, the size-of-segment field, and both CRCs. An encoder computes them; a decoder checks them.

Multi-byte fields (EOW, the type 7 and 8 C_PDU ID split across two places, C_PDU size, offset and reception window, size of segment) are most significant bits first, as the Annex C figures draw them. The CRCs are the exception: least significant byte first (section 3.2).

`peer_edition` says which edition's type table the decoder applies:

- `any`: the type means the same to Ed3 and Ed4 peers (types 0 to 8 and 15).
- `ed4`: decode as from an Ed4 peer.
- `ed3`: decode as from an Ed3 peer. Types 9 to 14 are then undefined: `fields` is `{"undefined": true, "type_specific": hex}` holding the bytes between the address field and the header CRC, and there is no `segment`. Any bytes after the header CRC are `trailing_bytes`. Undefined-type cases are `decode` only.

`peer_edition` `any` may only be used when the bytes carry type 0 to 8 or 15. Types 9 to 14 use `ed4` (or `ed3` for the undefined reading).

Size-of-header values h (h counts the four fixed bytes, the type-specific part and the header CRC, not the address [Ed4 C.4.2.5, p.C-14]). A value outside the range allowed here is `bad_header_size`. Ranges come from the figures (a fixed part plus a variable ack, extension or management field of a stated maximum length, in a 5-bit field):

| Type | Allowed h |
|---|---|
| 0, 3, 4 | exactly 9 [Fig C-9, p.C-23; Fig C-19, p.C-36; Fig C-21, p.C-40] |
| 9, 12 | exactly 10 [Fig C-10, p.C-24; Fig C-20, p.C-37] |
| 7, 8 | exactly 15 [Fig C-24, p.C-46; Fig C-33, p.C-51] |
| 14 | exactly 6 [Fig C-35, p.C-53] |
| 15 | exactly 7 [Fig C-36, p.C-54] |
| 1, 5 | 7 to 23: 7 plus 0 to 16 ack bytes [Fig C-11, p.C-27; Fig C-22, p.C-42] |
| 2 | 10 to 26: 10 plus 0 to 16 ack bytes [Fig C-17, p.C-33] |
| 6 | 8 to 31: 8 plus 0 to 23 extended bytes [Fig C-23, p.C-43] |
| 10 | 10 to 31 [Fig C-12, p.C-28], and consistent with the ack length (see below) |
| 11 | 13 to 31: 13 plus 0 to 18 ack bytes [Fig C-18, p.C-34] |
| 13 | 7 to 31 [Fig C-34, p.C-52] |
| 9 to 14, `ed3` (undefined) | at least 6, the four fixed bytes and the CRC. The standard gives an undefined type no size; this minimum is ours (C-1021). |

Type 10 has a one-byte ack length aa in the header. With aa up to 21 the ack data sits in the header and h = 10 + aa; with aa over 21 the header has no ack data, h = 10, and aa bytes of ack data follow the header CRC, then a CRC-32 over them [Ed4 C.4.5.5, pp.C-31 to C-32; C-0235]. Any other combination is `bad_header_size`. The value holds `ack_data` (aa is its length, so it is not a field) and, in the long form only, `ack_data_crc_ok`, which must be `true` in `encode` and `both` cases.

Registered `fields` sets (all integers are 0 up to the maximum shown; booleans are `true` or `false`; `hexN` is a hex string of at most N bytes). A type not listed has no fields beyond those here.

| Type | Fields (Annex C figure) |
|---|---|
| 0 | `c_pdu_start`, `c_pdu_end`, `deliver_in_order`, `drop_c_pdu`, `tx_win_uwe`, `tx_win_lwe` (booleans), `tx_fsn` (255) [Ed4 Fig C-9, p.C-23] |
| 9 | as type 0 but `tx_fsn` is 0 to 65535, high byte first [Ed4 Fig C-10, p.C-24; C-0134] |
| 1, 5 | `rx_lwe` (255), `selective_acks` (hex16) [Ed4 Fig C-11, p.C-27; Fig C-22, p.C-42] |
| 2 | type 0 flags and `tx_fsn` (255), then `rx_lwe` (255), `selective_acks` (hex16) [Ed4 Fig C-17, p.C-33] |
| 10 | `rx_lwe` (65535), `encoding` (1), `offset` (127), `ack_data` (hex255), and `ack_data_crc_ok` (boolean) exactly when `ack_data` is over 21 bytes [Ed4 Fig C-12, p.C-28] |
| 11 | type 0 flags, `tx_fsn` (65535), `rx_lwe` (65535), `encoding` (1), `selective_acks` (hex18) [Ed4 Fig C-18, p.C-34] |
| 3 | `full_reset_cmnd`, `reset_tx_win_rqst`, `reset_rx_win_cmnd`, `reset_ack` (booleans), `new_rx_lwe` (255), `reset_frame_id` (255) [Ed4 Fig C-19, p.C-36] |
| 12 | as type 3 but `new_rx_lwe` is 0 to 65535 [Ed4 Fig C-20, p.C-37] |
| 4 | `c_pdu_start`, `c_pdu_end` (booleans), `c_pdu_id` (15), `tx_fsn` (255) [Ed4 Fig C-21, p.C-40] |
| 6 | `extended_message`, `valid_message`, `ack` (booleans), `management_frame_id` (255), `extended_data` (hex23) [Ed4 Fig C-23, p.C-43]. The flag is carried as it is on the wire; the codec does not require it to agree with the length of `extended_data` (C-1023) |
| 7, 8 | `c_pdu_id` (4095), `deliver_in_order`, `group_address` (booleans), `c_pdu_size`, `c_pdu_segment_offset`, `c_pdu_reception_window` (65535) [Ed4 Fig C-24, p.C-46; Fig C-33, p.C-51] |
| 13 | `extended_type` (255), `extended_header` (hex24): the bytes after the extended type up to the header CRC [Ed4 Fig C-34, p.C-52]. We implement no extended type, so a decoded type 13 is always an unrecognised extension, and the value is its header. Whether data follows the header depends on the extended type, so bytes after the header CRC are not part of the value and are not `trailing_bytes`; a receiver reading a stream resumes the sync search after the header CRC (C-0365). A case with such bytes is `decode` only |
| 14 | none, `{}` [Ed4 Fig C-35, p.C-53] |
| 15 | `received_frame_type` (15), `reason` (15) [Ed4 Fig C-36, p.C-54] |

`encoding` is the Encoding bit: 0 bitmap, 1 run length encoding (C-0227, C-0228). Types 1, 2, 5, 10 and 11 carry the acknowledgement bytes opaquely; the bitmap and run-length structure is tested with the selective ARQ work, not here.

D_PDU decode check order. The decoder stops at the first failing step:

1. Fewer than 2 bytes: `truncated`.
2. The first two bytes are not `90 eb` [Ed4 C.4.2, p.C-11]: `bad_sync`.
3. Fewer than 6 bytes: `truncated`.
4. Size of address is 0: `bad_address_size`.
5. Size of header is not allowed for the type under `peer_edition` (the table above): `bad_header_size`.
6. Fewer bytes than 2 + (size of header) + (size of address): `truncated`.
7. Header CRC mismatch: `header_crc`.
8. Type 10 only: the header size is inconsistent with the ack length (section above): `bad_header_size`. Then, for a type with a segment, fewer bytes than the header plus the size of segment plus 4: `truncated`; for a type 10 long form, fewer bytes than the header plus aa plus 4: `truncated`.
9. A field value the codec cannot represent: `invalid_field`.
10. Bytes left over: `trailing_bytes`. Type 13 is the exception (the type 13 row above).

Fields marked NOT USED in the standard (type 3 and 12 flag byte bits 7-4, type 6 bits 7-3, type 11 Encoding byte bits 6-0) are not in the value; encoders write them as zero [Ed4 C.4.2, p.C-12]. What a receiver does with a NOT USED bit that is one is NOT STATED. Until an `interp` row decides (ignore it, or `invalid_field`), no case may carry a NOT USED bit set to one, and the validator rejects one that does.

### 3.4 Example

```json
{"id": "crc16-annex-c-example", "kind": "crc16", "dir": "encode", "rows": ["TODO"], "source": "Ed4 C.4.2.8, pp.C-18 to C-19", "value": {"data": "f0000047056402", "register": 7775}, "bytes": "5f1e"}
```

### 3.5 The `cpdu` value

A CAS-1 C_PDU as carried inside a D_PDU segment [Ed4 B.7.1, pp.B-13 to B-25]. The type is the high nibble of the first octet (rows B-0105, B-0106). `peer_edition` is not used. Every `value` has `type` (0 to 10) plus:

| Type | Keys | Bytes |
|---|---|---|
| 0 DATA | `s_pdu` (hex; empty only in `decode` cases, since the CAS discards a DATA C_PDU with no S_PDU octet, interp row B-0325) | One octet (type, low nibble unused), then the S_PDU [Fig B-1, p.B-14]. |
| 1 PHYSICAL LINK REQUEST, 2 PHYSICAL LINK ACCEPTED | `short`, `ed4`, `link` (booleans) | One octet: bit 3 unused, bit 2 Short, bit 1 Ed4, bit 0 LINK [Figs B-2, B-3, pp.B-15, B-17]. |
| 3 PHYSICAL LINK REJECTED, 4 PHYSICAL LINK BREAK | `reason` (0 to 15) | One octet: low nibble is the reason [Figs B-4, B-5, pp.B-18, B-19]. |
| 5 PHYSICAL LINK BREAK CONFIRM | none | One octet, low nibble unused [Fig B-6, p.B-21]. |
| 6 PHYSICAL LINK BREAK REQUEST | `reason` (0 to 7), `priority` (0 to 255) | Two octets: octet 0 bit 3 unused, bits 2 to 0 reason; octet 1 the priority [Fig B-7, p.B-22]. |
| 7, 8, 9 (ALE resume family) | none | One octet, low nibble unused [Figs B-8 to B-10, pp.B-23, B-24]. Decode only. |
| 10 ALE RELINK | `reason` (0 to 7) | One octet: bit 3 unused, bits 2 to 0 reason [Fig B-11, p.B-24]. Decode only. |

Types 7 to 10 are ALE only and out of our profile, so their cases are `decode` only. Cases that carry Short without Ed4, or LINK, are also `decode` only: an encoder never sends them (rows B-0125, B-0127) but a decoder reports what arrived. NOT USED bits are written as zero by an encoder and ignored by a decoder (interp row B-0306), so a case that has one set is `decode` only. The codec does not interpret reasons: any value that fits the field decodes. The Priority octet is carried raw; reading values above 15 as 15 (interp row B-0311) is for the CAS above the codec.

Decode check order, stopping at the first failure:

1. No bytes: `truncated`.
2. Type 11 to 15 (undefined) [Ed4 B.7.1, p.B-13]: `invalid_field`.
3. Type 6 with fewer than 2 octets: `truncated`.
4. Any type except 0 with octets beyond the PDU's fixed length (1, or 2 for type 6): `trailing_bytes`.

### 3.6 The `spdu` value

A SIS peer S_PDU as carried in a DATA C_PDU [Ed4 A.3.1, pp.A-14 to A-18]. The type is the high nibble of octet 0. `peer_edition` is not used. Every `value` has `type` (0 to 2) plus:

| Type | Keys | Bytes |
|---|---|---|
| 0 DATA | `priority`, `src_sap`, `dst_sap` (0 to 15), `client_confirm` (boolean), `u_pdu` (hex), and `ttd` only when VALID TTD is 1 | Octet 0 type and priority; octet 1 source then destination SAP; octet 2 bit 7 client delivery confirm required, bit 6 VALID TTD, bits 5 and 4 unused, bits 3 to 0 the TTD day; then, only with VALID TTD, two octets of TTD, most significant first; then the U_PDU [Figs A-3, A-4, p.A-15]. |
| 1 DATA DELIVERY CONFIRM | `priority`, `src_sap`, `dst_sap`, `u_pdu` (hex, a full or partial copy, may be empty) | Two octets as DATA octets 0 and 1, then the copy [Fig A-6, p.A-17]. |
| 2 DATA DELIVERY FAIL | `reason` (0 to 15), `src_sap`, `dst_sap`, `u_pdu` (hex) | Two octets: type and reason, then the SAPs, then the copy [Fig A-8, p.A-18]. |

`ttd` is an object `{"day_mod16": 0 to 15, "half_seconds": 0 to 65535}`: the 4-bit day and the 16-bit seconds-in-day value after dropping the least significant bit [Ed4 A.3.1.1, p.A-16]. The codec does not resolve it to a time (interp rows A-0166, A-0167). When VALID TTD is 0, octet 2 bits 3 to 0 are NOT USED (Fig A-4) and an encoder writes them as zero. Unused bits, including the TTD day bits when VALID TTD is 0 (row A-0159), are ignored on receipt (interp row A-0157), so a case with one set is `decode` only. The codec does not police reasons (A-0185 maps any DATA DELIVERY FAIL reason in the SIS).

Decode check order, stopping at the first failure:

1. No bytes: `truncated`.
2. Type 3 to 15 (reserved) [Ed4 A.3.1, p.A-14]: `invalid_field`.
3. Fewer octets than the fixed part (2 for types 1 and 2; 3 for type 0, or 5 when VALID TTD is 1): `truncated`.

All the bytes after the fixed part belong to the U_PDU copy, so there is no `trailing_bytes` for S_PDUs.

### 3.7 The `sis_frame` and `sis_stream` kinds

Both kinds cover the S_primitive framing of Annex S [Ed4 S.5.2, pp.S-8 to S-10]: preamble `90 eb`, version `00`, a 2-byte big-endian size of the body, then the body, whose first byte is the type [matrix S-0060 to S-0072]. A decoder decodes every primitive of the profile whatever its direction (a client-to-node type received by a client is the node's or client's policy, not the codec's). Hard link types 6 to 13 and expedited types 24 to 27 are recognised and reported as `deprecated_type` [S-0157]. Fields marked NOT USED are not in the value, are written as zero, and are ignored on receipt [S-0073, S-0074]. RANK in S_BIND_REQUEST is not in the value for the same reason [S-0088].

`sis_frame` is one frame, in the same style as `dpdu`: `bytes` is exactly one frame, and `value` is the primitive. Its decode check order, stopping at the first failure:

1. Fewer than 2 bytes: `truncated`. The first two bytes are not `90 eb`: `bad_sync`.
2. Fewer than 5 bytes: `truncated`.
3. Version not 0: `bad_version`.
4. Size 0: `bad_size`.
5. Fewer than 5 + size bytes: `truncated`.
6. Type in 6 to 13 or 24 to 27: `deprecated_type`. Type 0 or above 23 (other than 24 to 27): `unknown_type`.
7. Body length not matching the type's layout: `bad_length`.
8. Bytes left over: `trailing_bytes`.

The value always has `primitive` (the Annex S name) and these keys. `service_type` is `{"tx_mode": 0-15, "confirm": 0-3, "order": 0-1, "extended": 0-1, "min_retx": 0-15}` (the 12-bit Service Type or Delivery Mode [S-0079, S-0139]). An address is `{"address": "w.x.y.z", "group": bool, "size": 0-7}`: the 28-bit value (written as in section 2), the group flag, and the SIZE field as sent. The 28 bits are read right-aligned whatever SIZE says, and an encoder writes SIZE as given [S-0059, S-0137]. `u_pdu` and `body` are hex.

| `primitive` | Keys |
|---|---|
| `S_BIND_REQUEST` | `sap` (0-15), `service_type` |
| `S_UNBIND_REQUEST`, `S_DATA_FLOW_ON`, `S_DATA_FLOW_OFF` (type 16 [S-0111]), `S_KEEP_ALIVE` | none |
| `S_BIND_ACCEPTED` | `sap`, `mtu` (0-65535) |
| `S_BIND_REJECTED`, `S_UNBIND_INDICATION` | `reason` (0-255) |
| `S_SUBNET_AVAILABILITY` | `node_status`, `reason` (0-255 each) |
| `S_MANAGEMENT_MSG_REQUEST`, `S_MANAGEMENT_MSG_INDICATION` | `msg_type` (0-255), `body` |
| `S_UNIDATA_REQUEST` | `priority` (0-15), `dest_sap`, `dest_address`, `delivery_mode` (a `service_type`), `ttl` (0 to 1048575, the 20-bit field as sent), `u_pdu` |
| `S_UNIDATA_INDICATION` | `priority`, `dest_sap`, `dest_address`, `tx_mode` (0-15), `src_sap`, `src_address`, `u_pdu` |
| `S_UNIDATA_REQUEST_CONFIRM` | `dest_sap`, `dest_address`, `u_pdu` |
| `S_UNIDATA_REQUEST_REJECTED` | `reason` (0-15), `dest_sap`, `dest_address`, `u_pdu` |

The U_PDU size fields are not in the value; the encoder computes them and the decoder checks them. Whether a value is acceptable to the node (a U_PDU over the MTU, TTL above 648000, an invalid service type, a group address with ARQ) is node policy and is not tested here.

`sis_stream` is decode only. `value` is `{"chunks": [hex, ...], "events": [event, ...]}`; `bytes` is the chunks joined. The harness feeds the chunks to a streaming decoder one by one and collects every event it gives, in order; the list must equal `events`. An event is a primitive (a value as above) or `{"error": kind}` where kind is one of the five SIS kinds above or `bad_sync`. Results must not depend on how the bytes are chunked, so a harness should also try the bytes as one chunk and one byte at a time. Rules [S-0075, S-0076, S-0159]:

- Bytes that are not at a preamble, where one is expected (at the start, or after a whole frame), give one `bad_sync` event, then the decoder scans forward byte by byte for the next `90 eb` and resumes there. A run of junk of any length, however chunked, gives one event.
- A bad version or zero size gives its event, then the scan restarts at the byte after the first preamble byte. The bytes that scan passes over give no further event.
- A deprecated type, an unknown type or a body of the wrong length is reported once the whole body has arrived, and the body is then skipped by its size field. That counts as a whole frame, so junk after it is a new run.
- A frame that has not fully arrived gives no event. A final lone `90` is held in case it starts a preamble. There is no end-of-input event.

### 3.8 The `eow` value

```json
{"type": 8, "fields": {"speed": 6, "interleaver": 3}}
```

`type` is the EOW type 0 to 15 [Ed4 Table C-4, p.C-66], `bytes` is 2 bytes: the type (0 to 15), then the contents byte [Ed4 C.4.2.2, pp.C-12 to C-13; Fig C-45, p.C-67]. In a D_PDU the 12 bits are split across header bytes 0 and 1 (C-0102); that is the `dpdu` kind's job. Fields by type (bit positions are in the contents byte):

| Type | Fields |
|---|---|
| 0 EMPTY | none [C.6.1, p.C-68] |
| 1 ED3-BASIC-RATE | `data_rate` (bits 7-4), `interleaving` (3-2), `other_parameters` (1-0) [Fig C-46, p.C-68] |
| 3 UNRECOGNIZED-TYPE-ERROR | `unrecognized_eow_type` (bits 3-0) [Fig C-47, p.C-70] |
| 4 ED3-CAPABILITY | booleans, bit 7 down to bit 0: `drc_capable`, `stanag_4529`, `ms110_75_2400`, `extended_rate`, `full_duplex`, `split_frequency`, `non_arcs_ale`, `arcs` [Table C-8, p.C-71] |
| 8 MAX-SPEED, 9 LOW-SPEED, 12 SPEED-USED | `speed` (bits 4-0), `interleaver` (bits 7-5) [Fig C-49, p.C-72] |
| 10 MAX-SEGMENT | `max_segment` (8 bits, in units of 4 bytes) [C.6.7, p.C-74] |
| 11 SENDER-APPROACH | `eow12_needed` (bit 3), `strategy` (bits 2-1), `fixed` (bit 0) [Fig C-52, p.C-74] |
| 15 CAPABILITY | `duplex` (bit 1), `ed4` (bit 0) [Fig C-53, p.C-75] |
| 2, 5, 6, 7, 13, 14 | `contents` (255): not structured by us; treated as unrecognised on receipt (C-0421, C-0411) |

Reserved bits are zero in every case here (C-1020, C-0094): a receiver ignores them. A `decode` of a type above 15 cannot arise from 2 bytes in the corpus; a decoder given a first byte over 15 reports `invalid_field`, and given other than 2 bytes `truncated` or `trailing_bytes`.

### 3.9 The `address` value

```json
{"address_size": 2, "dst": "0.0.0.5", "src": "0.0.0.100"}
```

`bytes` is the m-byte address field alone, as in section 3.3. A length of 0, or over 7, is `bad_address_size`. The group flag of types 7 and 8 is a field of those D_PDUs and is not part of this kind (C-0122).

### 3.10 The CFTP kinds (Annex V)

CFTP is an application above the SIS (Annex V, SAP 12), not part of the node, so these kinds are for the CFTP client library. Its behaviour (acknowledgement, retries, reassembly) is tested by each implementation's own tests, cited in the matrix `tests` column. `peer_edition` is not used. Strings are octets, one character per octet; the cases use ASCII only.

| Kind | Value | Bytes |
|---|---|---|
| `rcop1` | `connection_id` (0 to 15), `u_pdu_id` (0 to 255), `segment` (0 to 65535), `data` (hex) | Octet 0: connection ID in bits 7 to 4, reserved bits 3 to 0; octet 1 the U_PDU ID; octets 2 and 3 the segment number, most significant first; then the data [Ed4 V.4, Figure V-2, p.V-2]. |
| `bftp1` | `file_name` (hex, 0 to 255 octets), `file_data` (hex) | `10 02`, SIZE_OF_FILENAME (one octet), the name, SIZE_OF_FILE (four octets, most significant first), the data [Ed4 V.4.1.1, Figure V-4, p.V-4]. |
| `cftp_mail` | `message_id` (string), `recipient_list` (string, as carried), `message` (hex) | MessageID, LF, RecipientList, LF, MessageSize in decimal digits, LF, then the Message; no LF after it [Ed4 V.6, V.7, pp.V-5 to V-7]. |
| `cftp_recipients` | `return_path` (string, empty for none), `recipients` (list of strings, at least one) | The return path, then a comma and each recipient [Ed4 V.7 step 3, p.V-7]. |
| `cftp_gzip` | `data` (hex): the decompressed octets | RFC 1952 gzip data (one or more members), or, when they do not start `1f 8b`, an RFC 1950 zlib stream (interp V-0082). |

A Message Acknowledgement is an `rcop1` with `data` `100b` and `segment` 0 (V-0044, interp V-0075).

`cftp_gzip` is decode only, because deflate output is not unique: two correct compressors may give different bytes for the same input. An encoder is checked by decompressing what it makes.

Decode check order, stopping at the first failure:

- `rcop1`: fewer than 4 octets is `truncated`. Reserved bits are ignored (interp V-0081), so a case with them set is `decode` only; an encoder writes them as 0.
- `bftp1`: fewer than 2 octets `truncated`; not `10 02` `bad_sync`; then, in turn, too short for the name length, for the name and SIZE_OF_FILE, and for the data, `truncated`; octets after the data `trailing_bytes`.
- `cftp_mail`: no LF after the MessageID `truncated`; an empty MessageID `invalid_field`; no LF after the RecipientList or after the MessageSize `truncated`; a MessageSize that is empty, longer than 15 characters or not all digits `invalid_field` (leading zeros are accepted, and our encoder writes none); fewer octets after it than it says `truncated`, more `trailing_bytes` (interp V-0085).
- `cftp_recipients`: the field is split at every comma and spaces around each part are removed; the first part is the return path (a lone space so becomes empty). No comma, or an empty part after the first, is `invalid_field` (interp V-0086). So a case with spaces is `decode` only; an encoder writes the return path, then a comma before each recipient.
- `cftp_gzip`: any failure to decompress is `bad_compression`.

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
| `burst_started` | 2 | optional `block_ms` | The modem detected the start of a burst (carrier detect) [plan 5.1]. |
| `bytes_received` | 2 | `bytes` | Decoded bytes from one modem block [plan 5.1]. |
| `burst_ended` | 2 | `reason`, `wn`, `interleaver`, `k`, `snr_tenth_db`, `blocks` | End of a received burst and its quality [plan 5.1]. |
| `transmit_done` | 2 | none | The core's own transmission has finished on air. |
| `channel_busy` | 2 | `busy` (boolean) | The optional external busy input [plan 7.3], ORed into Annex K's DCD (K-0006). |
| `sis_connect` | 3 | `conn` | A SIS client connected; `conn` is a positive integer chosen by the trace. A `conn` value names one connection only and is not reused after it closes, within a scenario. |
| `sis_bytes` | 3 | `conn`, `bytes` | Bytes from that client's stream. They may hold part of a frame or several frames. |
| `sis_disconnect` | 3 | `conn` | The client went away. |

`burst_started` key: `block_ms`, when present, is a positive integer, the duration of one block of the waveform the modem locked to, in whole ms rounded down. A modem that does not say leaves it out. With it the core places each received EOT by the block holding its D_PDU's first byte (interp C-1289); without it, at the arrival of the bytes completing the header (C-1024). Added in corpus 0.31.0; traces without it are unchanged.

`burst_ended` keys: `reason` is one of `eom`, `signal_lost`, `terminated`; `wn` is the waveform number; `interleaver` is from the interleaver enum below; `k` is the constraint length; `snr_tenth_db` is a signed integer SNR in tenths of a dB (it may be negative), or `null` when the modem gives none; `blocks` is the number of blocks decoded.

Interleaver enum: `ultra_short`, `very_short`, `short`, `medium`, `long`, `very_long` (the Ed4 interleaver names, plan section 5.3).

### 4.3 Outputs

| `out` | Keys | Meaning |
|---|---|---|
| `transmit` | `bytes`, `wn`, `interleaver`, `k`, `eom` | One whole transmission, sent as one modem burst [plan 5.1, 5.4]. `eom` is true when the modem is to end the burst with its end-of-message marker. The fake modem answers the call with the duration the modem fixture gives for (`wn`, `interleaver`, length of `bytes`) (section 5). |
| `terminate_receive` | none | Ask the modem to stop the current reception [plan 5.1]. |
| `set_max_input_blocks` | `n` | Change the modem's maximum input data blocks [plan 5.1]. |
| `timer_start` | `name`, `ms` | Start, or restart, the named timer to expire `ms` milliseconds from now. |
| `timer_cancel` | `name` | Stop the named timer. Cancelling a timer that is not running is allowed and is still an output. |
| `sis_bytes` | `conn`, `bytes` | Bytes to write to a SIS client's stream. |
| `sis_close` | `conn` | Close that client connection. |
| `link_state` | `peer`, `state` | A link to `peer` (a dotted-decimal address, section 2) changed state. State names are registered with the CAS work (section 4.6). |

### 4.4 Time model

- Time is an integer count of milliseconds since the core was created, which is time 0. The core's clock is the `t` of the input it is handling; it never reads time any other way.
- `t` never decreases from one input to the next.
- A timer's deadline is the `t` of the input that started it plus `ms`. `ms` is at least 1; a core that wants "now" acts now instead of starting a timer. Starting a timer that is already running replaces its deadline.
- Zero-duration rule: because `ms` is at least 1, a core that would start a timer with 0 ms (some protocol waits can be zero, for example a CSMA wait under LBT rule 1 or a jitter draw of slot 0) starts nothing and emits nothing, and takes the action the expiry would have taken at once, while handling the same input. So a chain of zero waits can happen inside one input, and a core that started a 1 ms timer instead does not match the trace.
- Timers do not fire by themselves. The trace lists every expiry as a `timer_expired` input at exactly the deadline, and the harness checks it (harness-contract.md section 2). Before an input at time t, every running timer with a deadline before t must have been listed as expired. A timer with a deadline equal to t must be listed as expired before any modem or SIS input at t; `config` inputs at t come before it (section 4.5), and may cancel or restart it.

### 4.5 Simultaneous events

When inputs share the same `t`, they are handled in class order (the Class column in section 4.2): configuration, then timer expiries, then modem events, then SIS events. A trace must list them in that order and the validator rejects one that does not. Within a class:

- Timer expiries at the same time are listed in the order the timers were last started, that is, the order of their `timer_start` outputs in the trace.
- Modem events are listed in the order the modem reports them.
- SIS events are listed in the order the bytes or connections arrived.

The host process (D3) follows the same order when real events arrive in the same millisecond, so a trace is also a statement about the real node. The order is our choice; the standard does not state one.

### 4.6 Names

Timer names have the form `<sublayer>.<timer>`, optionally followed by `/<qualifier>` when one timer exists per peer or per connection, for example `csma.cont_wait` or `dts.ack_wait/0.0.1.2`. Sublayers are `sis`, `cas`, `dts`, `csma`, `drc` and `station`. The timer part uses lower-case letters, digits and `_`. A qualifier is a dotted-decimal address (section 2) or a decimal `conn` number. The registry below lists the `<sublayer>.<timer>` part and says which qualifier, if any, it takes.

Each timer name, and each `link_state` state name, is registered in a table in this section by the change that first uses it, with the matrix row that defines it. A trace using an unregistered name is invalid.

| Timer name | Qualifier | Defined by |
|---|---|---|
| `csma.lbt_wait` | none | LBT_WAIT_TIMER: started on entry to LBT_WAIT from SENSE with the value of the LBT rules, and with the value the same rules give when the channel is idle again after a busy indication in LBT_WAIT or CONT_WAIT (zero under rule 1 starts nothing); cancelled while the channel is busy (K-0030, K-0066, K-0070, K-0077, K-0087, K-0089, K-0120) |
| `csma.cont_wait` | none | CONT_WAIT_TIMER: started on entry to CONT_WAIT with the contention wait; cancelled when the round is lost or the queue empties (K-0031, K-0079 to K-0082, K-0089, K-0091) |
| `csma.vdcd_end` | none | The predicted end time of the channel activity heard, from parsed EOTs: runs exactly while the MAC is in SENSE or LBT_WAIT, data is queued, DCD and the external busy input are false and the predicted end time is later than now, with that end time as its deadline; its expiry is the VDCD idle event (C-0844, K-0006, K-0021, K-0073, K-0111) |
| `dts.ttd` | none | The DTS transmit queue's next change with no input: runs to the earliest TTD of a queued C_PDU, or, while a C_PDU waits for a C_PDU ID still in use, to the instant that ID is freed, whichever is sooner. Started or restarted when that instant changes, cancelled when there is none (for example when the transmit queue empties); at expiry every C_PDU whose TTD is at or before now is dropped and rejected (C-0857, C-0859, C-0864, C-0327, C-1050, C-1053) |
| `dts.reception_window` | none | The earliest reception window deadline among the incomplete non-ARQ C_PDUs being reassembled: started or restarted when that earliest deadline changes, cancelled when none is left; at its expiry every incomplete C_PDU whose deadline has passed is discarded (C-0336, C-0350, C-1077; core-architecture collapsing rule) |
| `dts.ack_wait` | peer address | The wait for an acknowledgement from the peer: started, or restarted, with `dts.ack_wait_ms` (or its derived value, section 6) when a transmission that carried ARQ data D_PDUs to the peer has ended and some of them await acknowledgement, peers in ascending address order; cancelled when an ACK-ONLY or DATA-ACK from the peer leaves none awaiting, or when the connection ends; at expiry every D_PDU still awaiting acknowledgement is taken to have failed and is retransmitted (C-0904, C-0911, C-1120), unless it is the sixteenth answer wait for the peer in a row to expire with no answer from it, when the connection is lost instead (C-1250) |
| `dts.reset_wait` | peer address | The wait for the RESET ACK of a RESET/WIN-RESYNC command this node sent (a FULL RESET CMD, or the RESET RX WIN CMND that answers a RESET TX WIN RQST): started with the same value as `dts.ack_wait` when the transmission carrying the command has ended; cancelled by the peer's RESET ACK, by a FULL RESET that makes an RX WIN CMND stale, or when the connection ends; at expiry the same command, same RESET FRAME ID, is sent again (C-0255, C-0264, C-0272, C-1172), unless it is the sixteenth answer wait for the peer in a row to expire with no answer from it, when the connection is lost instead (C-1250) |
| `cas.link_request` | peer address | The Caller's wait for an answer to its PHYSICAL LINK REQUEST: started with `cas.link_request_timeout_ms` (or its derived value, B-0420) when the transmission carrying the request has ended; cancelled on PHYSICAL LINK ACCEPTED or REJECTED or on a WARNING that restarts linking without the Ed4 bit; at expiry the request is sent again, or the link fails after `cas.link_request_retries` repeats (B-0203, B-0204, B-0221 to B-0223, B-0400, B-0407, B-0411) |
| `cas.break` | peer address | The Initiator's wait for PHYSICAL LINK BREAK CONFIRM: started with `cas.break_timeout_ms` (or its derived value) when the transmission carrying PHYSICAL LINK BREAK has ended; cancelled when the link is broken (a confirm, or a PHYSICAL LINK BREAK from the peer, or D_CONNECTION_LOST); at expiry PHYSICAL LINK BREAK is sent again, or after `cas.break_retries` repeats the link is declared broken (B-0283, B-0286 to B-0288, B-0316, B-0424) |
| `cas.clean_close` | peer address | The wait for clean close state of a close this node's SIS asked for: started with `cas.clean_close_timeout_ms` (or its derived value) when the DTS answers that the link is not clean; cancelled when PHYSICAL LINK BREAK is sent or the link is broken; at expiry PHYSICAL LINK BREAK is sent anyway (B-0243, B-0322, B-0421) |
| `cas.first_data` | peer address | The Called node's wait for the first DATA C_PDU on a link it accepted: started with `cas.first_data_timeout_ms` (or its derived value) when the transmission carrying PHYSICAL LINK ACCEPTED has ended, and restarted when a repeated accept has been sent; cancelled by the first DATA C_PDU received by ARQ from that peer, when the link starts closing or breaking, or when it is broken; at expiry the link is aborted (B-0215, B-0216, B-0400, B-0401, B-0403, B-0406, B-0420, B-0423) |
| `sis.confirm_wait` | none | The earliest deadline among the U_PDUs awaiting the answer to a delivery confirmation: a U_PDU held for a soft link has its TTD, one handed to the CAS `sis.confirm_wait_ms` after that (or its TTD when null); started or restarted when that earliest deadline changes, cancelled when the list empties; at expiry every U_PDU whose deadline has come is rejected to its client, reason 1 if it was still held and 3 if it was handed down, in deadline then insertion order (A-0221, A-0225, A-0226, A-0230, A-0232, A-0342) |
| `sis.soft_link_idle` | peer address | The idle wait of an open soft link: started with `sis.soft_link_idle_ms` (or its derived value) when the soft link is established or its last outstanding ARQ U_PDU is confirmed or rejected, with none outstanding; restarted by each ARQ C_PDU received from the peer while it runs; cancelled when an ARQ U_PDU to the peer is handed down, or when the soft link is closed or broken; at expiry the SIS closes the link with Idle Soft Link Terminated, or for a called node within its minimum hold when that hold ends (A-0011, A-0013, A-0197, A-0205, A-0320, A-0326) |
| `sis.soft_link_min_hold` | peer address | A called node's minimum hold: started with `sis.soft_link_min_hold_ms` (or its derived value; not started when it is 0) when its soft link is established; cancelled when the soft link is closed or broken; while it runs the node does not close the link on its own, and at expiry an idle close that fell due is made (A-0197, A-0325, A-0326) |
| `sis.soft_link_max` | peer address | The maximum session time: started with `sis.soft_link_max_ms` (or its derived value) when a soft link is established; cancelled when it is closed or broken; after expiry the link is closed with Soft Link Terminated to share channel as soon as U_PDUs for another peer are held off for want of a link (A-0014, A-0015, A-0322) |
| `sis.held_off` | peer address | The SIS's wait before it asks again for a link to a peer that answered PHYSICAL LINK REJECTED with reason 4, Too many active links: started with `sis.soft_link_max_ms` (or its derived value) when that rejection is reported; cancelled when the SIS asks again for that peer for another reason (B-0412) or the peer makes a link with us; at expiry the SIS asks again if U_PDUs still wait for the peer, otherwise drops the hold (B-0303, B-0451, A-0014) |

| Link state | Defined by |
|---|---|
| `calling` | The CAS has started the Caller procedure towards the peer and has no answer yet (B-0196, B-0202) |
| `linked` | A physical link with the peer is made: as Caller on PHYSICAL LINK ACCEPTED (B-0219), as Called node when the transmission carrying PHYSICAL LINK ACCEPTED has ended (B-0213, B-0400) |
| `unlinked` | No physical link and no link being made: emitted when a call fails (B-0220, B-0223), a link is aborted (B-0215) or a link is broken (B-0284 to B-0288, B-0324) |
| `closing` | A made link is being brought to clean close before it is broken: emitted when a PHYSICAL LINK BREAK REQUEST is received, or when this node's own close finds the link not clean (B-0239, B-0243, B-0244, B-0317, B-0421, B-0423) |
| `breaking` | This node is the Initiator of the break of a made link and has sent, or is about to send, PHYSICAL LINK BREAK (B-0282, B-0316) |

## 5. The modem fixture

The core needs burst durations from the modem port's `PlanBurst` (plan 5.1) before it transmits, for example to compute EOT. In T2 the harness answers those calls from a fixture in the configuration, so traces do not depend on the real modem. The fixture values are test data, not claims about MIL-STD-188-110D.

```json
"modem": {"preamble_ms": 720, "flush_ms": 0, "eom_bytes": 0,
          "waveforms": [{"wn": 6, "interleaver": "short", "block_bytes": 192, "block_ms": 1000}]}
```

`block_bytes` and `block_ms` are positive integers, and no two entries share a `wn` and `interleaver`. `eom_bytes` is a non-negative integer, default 0: the block space the modem's end-of-message marker takes after the last byte of every burst (a MIL-STD-188-110D modem's 32-bit EOM is 4; interp C-1290). It was added in corpus 0.31.0, and 0 gives the arithmetic of earlier versions. For a plan request with waveform number `wn`, interleaver `i` and `n` bytes, the harness finds the entry with that `wn` and `interleaver` (missing entry: the case fails with `unplanned_waveform`) and returns:

- blocks = max(1, ceil((n + eom_bytes) / block_bytes)), using integer arithmetic, that is (n + eom_bytes + block_bytes - 1) / block_bytes rounded down, and 1 when n + eom_bytes is 0;
- bytes_per_block = block_bytes;
- preamble_ms, block_ms and flush_ms, as in the fixture;
- duration_ms = preamble_ms + blocks x block_ms + flush_ms;
- eom_bytes, as in the fixture.

So n blocks carry at most n x block_bytes - eom_bytes bytes. The answer exposes all seven values, not only the duration: a core needs the start time of each block (preamble_ms + i x block_ms) to stamp a different EOT on each D_PDU, and the block capacity, less the marker's space, to size a transmission (interp C-1290). The real modem port gives the same seven values (plan 5.1).

## 6. Node configuration

`corpus/t2/defaults.json` holds one JSON object: the full base configuration. A scenario's `config` is an overlay merged into it: objects merge key by key, recursively; any other value, including a list or `null`, replaces the base value. A key in the overlay that is not in the base is an error, and so is replacing an object with a non-object or the other way round. A `config` input's `set` is merged the same way into the configuration in force at that moment. `null` in the base means "no default": a scenario that exercises that setting must give a value, and a core that needs a `null` setting fails the case.

The base configuration and where each default comes from:

| Key | Default | Source |
|---|---|---|
| `local_address` | `null` | Per node. |
| `groups` | `[]` | Group addresses (dotted, section 2) this node receives. Membership is configuration, since no protocol joins a group [Ed4 A.2.2.9, p.A-12; A-0119, A-0120]. |
| `time.epoch_year` | `2026` | UTC year of core time 0, for the TTD of DATA S_PDUs; the core has no clock, and day numbers restart each year (A-0161, A-0251). |
| `time.epoch_day` | `1` | UTC day-of-year of core time 0, 1 to 365 or 366 (A-0161, A-0251). |
| `time.epoch_second` | `0` | UTC seconds after midnight at core time 0, 0 to 86399 (A-0166, A-0251). |
| `prng_seed` | `"0000000000000000"` | [prng.md](prng.md) |
| `csma.mode` | `null` | `jitter`, `slotted` or `ed3`, network-wide (decision D7). `ed3` is the Ed3-compatible setting of the K-0107 ruling: jitter contention, one common LBT value equal to `lbt_wait_dcd_ms`, LBT rule 1 off. |
| `csma.cont_slot_width_ms` | 3000 | [Ed4 K Table 7, p.K-12] |
| `csma.num_cont_slots` | 16 | [Ed4 K Table 7, p.K-12] |
| `csma.lbt_wait_dcd_ms` | 30000 | [Ed4 K Table 7, p.K-12] |
| `csma.lbt_wait_vdcd_ms` | 3000 | [Ed4 K Table 7, p.K-12] |
| `csma.node_slot_position` | `null` | Per node, slotted mode only [Ed4 K.2.2, p.K-4] |
| `modem.preamble_ms` | `null` | Section 5 |
| `modem.flush_ms` | `null` | Section 5 |
| `modem.eom_bytes` | 0 | Section 5 (corpus 0.31.0) |
| `modem.waveforms` | `[]` | Section 5 |
| `sis.default_ttl` | 648000 | The default maximum TTL, in the 2-second units of the TTL field, used when a request gives TTL 0; it is configurable [Ed4 A.2.2.6, p.A-9; A-0087, A-0088], and we default it to the field maximum (A-0091). 1 to 648000. |
| `sis.soft_link_idle_ms` | `null` | How long an open soft link with no ARQ U_PDU outstanding and none received waits before the SIS closes it with Idle Soft Link Terminated; configurable, implementation dependent, and may be zero [Ed4 A.1.4, p.A-2; A-0011, A-0013]; our reading of idle is interp A-0320. 0 or more. When null it is derived: three answer waits (interp A-0321). |
| `sis.soft_link_min_hold_ms` | `null` | The least time a called node keeps a soft link before closing it on its own [Ed4 A.3.2.1.3, p.A-20; A-0197; interp A-0326]. 0 or more; 0 means no minimum hold runs. When null it is derived (interp A-0321, revised corpus 0.34.0): the called node's first-data wait, so n answer waits with n as for `cas.first_data_timeout_ms` when that is null, and three answer waits when it is set. |
| `sis.soft_link_max_ms` | `null` | The longest a soft link is kept while U_PDUs for another node wait for a link, after which it is closed with Soft Link Terminated to share channel [Ed4 A.1.4, p.A-3; A-0014, A-0015; interp A-0322]. 1 or more. When null it is derived: six answer waits (interp A-0321). |
| `sis.frag_size` | `null` | U_PDU_response_frag_size: the most bytes of the U_PDU copied into S_UNIDATA_REQUEST_CONFIRM and S_UNIDATA_REQUEST_REJECTED, which is configurable [Ed4 A.2.2.7, p.A-10; A.2.2.8, pp.A-11 to A-12; A-0102, A-0114], and into the DATA DELIVERY CONFIRM and FAIL S_PDUs the node sends (interp A-0341). A U_PDU no longer than it is copied whole. 0 or more. When null or absent the whole U_PDU is copied. |
| `sis.confirm_wait_ms` | `null` | How long the SIS waits for the answer to a U_PDU that asked for node or client delivery confirmation, from when it is handed to the CAS; configurable with no value given [Ed4 A.3.2.3, p.A-23; A-0221, A-0226; interp A-0232]. At the end of the wait the client gets S_UNIDATA_REQUEST_REJECTED reason 3 (A-0225, A-0230). 1 or more. When null the wait ends at the U_PDU's TTD (interp A-0342). |
| `dts.max_segment_size` | 1023 | The largest C_PDU segment a new D_PDU carries, configurable up to 1023 bytes [Ed4 C.5.1, p.C-57; C.5.2, p.C-61; C-0503, C-0523]. 1 to 1023. |
| `dts.max_transmission_ms` | 127500 | A configured maximum transmission length below the 127.5 s EOT limit [Ed4 K.3.2.5, p.K-12; K-0094, K-0095]; never applied so as to block one D_PDU (C-0551, C-0878). 1 to 127500. |
| `dts.max_window` | 32768 | The maximum allowable transmit window size for the 16-bit FSN family: no new ARQ D_PDU is sent while this many are outstanding. It should be configurable and must not exceed the maximum window size [Ed4 C.7.2 (g) to (j), p.C-99; C-0771 to C-0775]. 1 to 32768. |
| `dts.ack_wait_ms` | `null` | How long after the end of a transmission carrying ARQ data to a peer the node waits for an acknowledgement before it treats the D_PDUs still unacknowledged as failed and retransmits them. The standard gives no value (C-0911). When null the wait is derived (interp C-1120): `dts.max_transmission_ms` plus the longer of `csma.lbt_wait_dcd_ms` and `csma.lbt_wait_vdcd_ms` plus `csma.num_cont_slots * csma.cont_slot_width_ms`. 1 or more, or null. An explicit value below `csma.lbt_wait_dcd_ms` is refused when the configuration is loaded (interp C-1252). |
| `drc.default_speed` | `{"wn": 2, "interleaver": "long"}` | The waveform and interleaver of every transmission until rate selection (phase 7) chooses them; a conservative start (plan 6.2). An object with `wn` and `interleaver` (section 4.2 enum). |
| `drc.table` | an empty table (`ladder` and `thresholds` `[]`, every constant `null`) | The rate selection calibration (core-architecture.md 9, phase 7, design shape items 5 and 6; plan 6.2): data, not an operator setting. An empty `ladder` means no calibration: the node sends no MAX-SPEED, LOW-SPEED, MAX-SEGMENT or ED3-BASIC-RATE and transmits at `drc.default_speed` throughout, the fixed-rate baseline. Schema, smoothing and use in sections 6.1 and 6.2. A `drc/` scenario supplies a small synthetic table; the host loads the calibrated one. |
| `cas.max_links` | `null` | The configurable limit on active physical links; a request that would take the count above it is rejected with reason 4 (B-0193, B-0209, B-0313). Links being made count (B-0402). 1 or more. |
| `cas.link_request_timeout_ms` | `null` | The Caller's wait for an answer to a PHYSICAL LINK REQUEST, from the end of the transmission carrying it; configurable with no value given (B-0203, B-0204). 1 or more. When null it is derived: one answer wait, `dts.ack_wait_ms` or its derived value (interp B-0420). |
| `cas.link_request_retries` | `null` | How many times an unanswered PHYSICAL LINK REQUEST is sent again before the link fails, so 1 + retries sends in all (B-0222, B-0407). 0 or more. |
| `cas.first_data_timeout_ms` | `null` | The Called node's wait for the first DATA C_PDU on a link it accepted (B-0215, B-0216). 1 or more. When null it is derived (interp B-0420, revised corpus 0.34.0): n answer waits. With an empty `drc.table` ladder, n = 3. Otherwise L = 2054 bytes is the largest DATA C_PDU (1-octet C_PCI, B-0111; 5-octet S_PCI with a TTD, A-0160; a U_PDU at the 2048-byte MTU, A-0047), and c is the user bytes one transmission of the configured length carries on the slowest rung, `ladder[0]`: b = floor((min(127500, `dts.max_transmission_ms`) - `preamble_ms` - `flush_ms`) / `block_ms`) blocks, but at least 1 (section 5; the limit never blocks one D_PDU, C-0551), hold k = b x `block_bytes` - `modem.eom_bytes` bytes (C-1290); these are cut into DATA-ONLY D_PDUs of at most s = `dts.max_segment_size` bytes of segment, each with o = 23 bytes of overhead, its largest (2 sync, C-0082; a 10-byte header with its CRC, C-0111, C-0175; a 7-byte address field, C-0074; the 4-byte CRC-32, C-0157). With q = floor(k / (s + o)) and r = k - q x (s + o), c = q x s + max(0, r - o). Then n = max(3, ceil(L / c) + 2): the transmissions L needs, a retransmission and the turn. c below 1 gives n = 3. All integers. Corpus 0.33.0 had n = max(3, ceil(L / k)). What ends the wait is unchanged. |
| `cas.break_timeout_ms` | `null` | The Initiator's wait for PHYSICAL LINK BREAK CONFIRM, from the end of the transmission carrying PHYSICAL LINK BREAK; at least the time the peer needs to answer (B-0283, B-0424). 1 or more. When null it is derived: one answer wait (interp B-0420). |
| `cas.break_retries` | `null` | How many times an unanswered PHYSICAL LINK BREAK is sent again before the Initiator declares the link broken anyway, so 1 + retries sends in all (B-0287, B-0288, B-0424). 0 or more. |
| `cas.clean_close_timeout_ms` | `null` | The longest a close this node asked for waits for clean close state before it sends PHYSICAL LINK BREAK anyway (interp B-0322), from the moment the DTS reports the link not clean. 1 or more. When null it is derived: three answer waits (interp B-0420). |

There is no address size setting. A node sends each D_PDU with the smallest size-of-address field m that holds both its destination and its source, so m follows the addresses: a broadcast D_PDU always has m = 7 (C-0133, C-0130). Corpus 0.8.0 removed the `address_size` key that earlier versions had.

New settings are added to `defaults.json` and this table together, each with its source, in the change that first needs them. Only settings the standard makes configurable, or that the plan records as ours, go in (plan 3.2 principle 5).

### 6.1 The `drc.table`

`drc.table` holds the rate selection calibration (core-architecture.md 9, phase 7). Integers only. A scenario overlay gives the whole table it needs; since lists replace and the constants are `null` in the base, every key the scenario's behaviour reads must be given.

| Key | Value | Meaning |
|---|---|---|
| `ladder` | list of `{"wn", "interleaver"}` | The rungs, slowest first: the order in which recommendations and the sender move. No two entries are the same rung. Empty means no calibration (section 6). WN 0 is never on it (interp C-0470). |
| `thresholds` | list of `{"wn", "interleaver", "bulk", "latency"}` | One entry per rung an estimate can be measured on (on the ladder or not, for example `drc.default_speed`); no two entries share a rung. `bulk` and `latency` are each a list as long as `ladder`: element j is the smoothed estimate, in tenths of a dB, on this entry's rung at or above which ladder rung j meets the bulk (throughput) criterion, or the latency criterion; `null` means rung j never meets it from this rung. |
| `smoothing_weight` | integer 1 to 16 | The weight w of a new estimate, in sixteenths (section 6.2). 16 means no smoothing. |
| `clean_run` | integer, 1 or more | The clean bursts in a row on a rung before a recommendation moves up from it (the trial), and before MAX-SEGMENT doubles to a fixed-speed sender. |
| `rx_error_limit_ppt` | integer 0 to 1000 | A burst whose D_PDU error rate, in parts per thousand, is above this caps its rung in the recommendations, and with `probe_run` set lets the estimate move MAX-SPEED down. |
| `rx_ceiling_initial` | integer, 1 or more | The first cap on a rung lasts this many bursts from the peer. |
| `rx_ceiling_cap` | integer, at least `rx_ceiling_initial` | A cap doubles on each repeat failure of the rung, up to this many bursts. |
| `tx_step_down_waits` | integer, 1 or more | The sender's step down: this many `dts.ack_wait` expiries in a row with no answer from the peer move its rung down one (P7-7). |
| `tx_ceiling_initial` | integer, 1 or more | The sender's failed-trial ceiling lasts this many of its transmissions to the peer (P7-7). |
| `tx_ceiling_cap` | integer, at least `tx_ceiling_initial` | The failed-trial ceiling doubles on each repeat failure, up to this many transmissions (P7-7). |
| `probe_run` | integer, 1 or more, or `null` | The probe (P7-9c; interp C-1291): the clean bursts in a row on the MAX-SPEED rung after which MAX-SPEED moves up to the next position of its walk even when the estimate does not call for it; while set, the estimate moves MAX-SPEED down only after a burst over `rx_error_limit_ppt` or with a lost block, and then by one position of its walk (section 6.2 step 6; corpus 0.37.0). `null`, the default, means no probe. LOW-SPEED is never probed. |
| `bulk_rungs` | list of ladder positions, ascending, at least one, or `null` | The positions the MAX-SPEED walk uses (P7-9 round 3; open question 15): the rungs on the bulk set of the calibration. `null`, the default, means every position. |
| `latency_rungs` | the same | The positions the LOW-SPEED walk uses: the rungs on the latency set. `null` means every position. |

A rung is named by `wn` and `interleaver` (section 4.2 enum). A rung's position is its index in `ladder`. Example:

```json
"drc": {"table": {"ladder": [{"wn": 2, "interleaver": "long"}, {"wn": 4, "interleaver": "long"}],
                  "thresholds": [{"wn": 2, "interleaver": "long", "bulk": [-100, 80], "latency": [-100, 120]},
                                 {"wn": 4, "interleaver": "long", "bulk": [-100, 60], "latency": [-100, 100]}],
                  "smoothing_weight": 8, "clean_run": 2, "rx_error_limit_ppt": 500,
                  "rx_ceiling_initial": 2, "rx_ceiling_cap": 8,
                  "tx_step_down_waits": 2, "tx_ceiling_initial": 2, "tx_ceiling_cap": 8, "probe_run": null,
                  "bulk_rungs": null, "latency_rungs": null}}
```

**The calibrated table.** `calibration/<modem>-<version>/drc-table.json` holds the table measured on one modem implementation and version (for example `ms110d-cs-0.6.1`, M0LTE.Ms110d 0.6.1), as `{"source": {...}, "table": {...}}`: `table` is a `drc.table` exactly as above, and `source` names the calibration, the modem (`implementation`, `package`, `version`, `commit`), the channel simulator and the builder's choices. It is generated by `tools/build_drc_table.py` from the sweep's aggregates in the same directory, never by hand; [calibration-results.md](calibration-results.md) gives the method and the results. The corpus default stays empty, so no trace depends on it; a host loads it (core-architecture.md 9, design shape item 6).

### 6.2 Receiver recommendations (P7-6)

The exact arithmetic, so every implementation computes the same values (interp C-1270). Nothing here runs when `ladder` is empty.

**Smoothing.** Per peer and per measured rung, the smoothed estimate S starts empty. A burst on that rung with estimate x (`snr_tenth_db`, not null) sets S = x when S is empty, otherwise S = S + q, where d = x - S, q = (|d| x w) / 16 with integer division on the non-negative product, and q takes the sign of d (so it truncates towards zero for both signs). A burst with a null estimate leaves S unchanged. T1 kind `drc_smooth` holds vectors.

**Per burst.** At each `burst_ended`, for each source heard in the burst (a D_PDU header with a good CRC from it, whatever its destination, as C-0833), in ascending address order: h is how many of its D_PDUs arrived whole with a data part that a CRC-32 checks (a segment, or the ACK data after the header of a long type 10; a DROP PDU counts here), and e how many of those had a failed data CRC-32: those discarded for it (C-0836), and a DATA-ACK, whose acknowledgement is still used (C-1133), but not a DROP PDU (C-1125). So e is at most h. A D_PDU with no data part (PADDING, an ACK-ONLY with no ACK data, a WARNING, and so on) counts in neither, nor does one whose header is valid but which is cut off by the end of the burst or is invalid after its header; such a burst can have h = 0. A block of the burst (one `bytes_received`) is lost when none of its bytes lies within a D_PDU whose header was valid (from its first sync byte to its end as decoded; to the burst end for one cut off by it; over its header alone for one invalid after its header) and its bytes are not all zero (the modem's zero fill). The burst is clean when e = 0 and it has no lost block. (Corpus 0.36.0, P7-9 round 3: before, a burst was clean whenever e = 0, so one whose data D_PDUs all lost their headers while the ACK-ONLY fill after them got through counted as clean.) (Corpus 0.34.0 and before counted every valid header in h, so the ACK-ONLY copies and PADDING that fill a block diluted the error rate: a WN 8 Long burst of 24 data D_PDUs filled with 102 ACK-ONLY copies showed at most 190 per thousand even with every segment lost, and was never capped. The calibration's error rates, and so `rx_error_limit_ppt`, are per data D_PDU.) Let a be the burst's rung (`wn`, `interleaver`). In this order:

1. Caps: every active cap of the peer counts down by one; a cap that reaches 0 is lifted.
2. If a is on the ladder: when e x 1000 > `rx_error_limit_ppt` x h, the rung's failure count goes up by one and the rung is capped for min(`rx_ceiling_initial` x 2^(failures - 1), `rx_ceiling_cap`) bursts (replacing any cap it had), computed by starting at `rx_ceiling_initial` and doubling once per earlier failure while below `rx_ceiling_cap`, so no step overflows; when the burst is clean, the rung's failure count goes back to 0.
3. Clean run of rung a: one more when the burst is clean, else 0.
4. Smoothing of S on rung a, as above, when a has a `thresholds` entry.
5. The ceiling: the lowest position p - 1 over the capped rungs p, never below 0; no cap, no ceiling.
6. For each of MAX-SPEED (criterion `bulk`, walk W = `bulk_rungs`) and LOW-SPEED (`latency`, W = `latency_rungs`; every position when `null`), with current recommendation R (a position, or none): if this burst had an estimate and a has a `thresholds` entry, the target T is the highest position j in W whose element is not null and not above S, or the lowest position in W when there is none. Write down(p) for the highest position in W not above p (none when every position in W is above p) and up(p) for the lowest position in W above p. With no R yet, R = T, but when a is on the ladder R = down(min(T, a's position)), or the lowest position in W when that is none. Otherwise, let n be the clean run of the rung at R; for LOW-SPEED only, when a is on the ladder above R, n is the larger of that and the clean run of a (corpus 0.37.0, P7-9 round 4; before, the rung at R alone). If T < R, R = T (a move down is immediate); if T > R and n is at least `clean_run`, R = T (straight to the target, the trial; corpus 0.35.0 and before moved one position, R + 1). Then, in every case, if R is above the ceiling c, R = down(c), or c itself when that is none. Without an estimate only the ceiling applies.

   The probe (P7-9c; interp C-1291), for MAX-SPEED only and only when `probe_run` is not `null`, changes the "otherwise" branch above (R already set, and an estimate on a rung with a `thresholds` entry). Let n be the clean run of the rung at R. If T < R, R = max(T, down(R - 1)) only when e x 1000 > `rx_error_limit_ppt` x h or the burst has a lost block: the estimate alone never moves MAX-SPEED down after a clean burst or after one with corrupted D_PDUs under the limit and no lost block, and such a burst moves it down by at most one position of W (corpus 0.37.0, P7-9 round 4; before, any burst that was not clean moved it to T); the ceiling below may still take it further. If T > R and n is at least `clean_run`, R = T, the trial, as before. Then, if R is still what it was before this step, T is not above it, up(R) exists, and n is at least `probe_run`, R = up(R): the next position of the walk though the estimate does not call for it (one position of W; corpus 0.35.0 and before, R + 1 on the whole ladder). The ceiling then applies as before, so a capped rung bounds the probe; the sender bounds it by its failed-trial ceiling (interp C-1281). LOW-SPEED keeps the walk above whatever `probe_run` says.
7. MAX-SEGMENT, kept only for a fixed-speed sender (the peer's last SENDER-APPROACH, counting one in this burst, has Fixed = 1; interp C-1272): it starts at 255; when e x 2 > h it halves (integer division), not below 25, and its clean count goes to 0; otherwise, when the burst is clean its clean count goes up by one, and on reaching `clean_run` it doubles, not above 255, and the count goes to 0. To any other sender MAX-SEGMENT is 255.

**Widths.** `snr_tenth_db`, the thresholds and the constants are signed 32-bit integers (a loader refuses a table value outside that range). Compute d, |d| x w, e x 1000, `rx_error_limit_ppt` x h, e x 2 and the cap doubling in signed 64-bit; every other value, S included (it always lies between its old value and x), fits 32 bits. Every division is on non-negative operands, so truncation and flooring agree.

A recommendation sent is the rung at position R: MAX-SPEED or LOW-SPEED with Speed = WN and the interleaver code of the rung (C-0462, C-0469). To a peer recorded Ed3, ED3-BASIC-RATE instead, from the MAX-SPEED rung (C-0957, C-0959; interp C-1273). Which go where in the headers: core-architecture.md 9, open question 1, and interp C-1271.

## 7. PRNG cases

`corpus/prng/splitmix64.jsonl` holds the generator's test values in the schema given in [prng.md](prng.md) section 5. Every harness runs them before any T2 scenario.

## 8. Versioning

`corpus/VERSION` holds `MAJOR.MINOR.PATCH`, and each release is a git tag `vMAJOR.MINOR.PATCH` on this repository. Implementations pin a tag (as a submodule or package) and state the version they pass.

- **MAJOR**: a format change that an existing harness cannot read correctly, for example a new required key or a changed meaning.
- **MINOR**: new cases, new kinds, new registered names or settings, retired cases. An older harness may meet kinds or inputs it does not know; it must report those cases as unsupported, not as passed.
- **PATCH**: corrections to existing cases (wrong expected bytes, wrong row ids, notes).

Before 1.0.0 the format is still settling, and a MINOR bump may also carry format changes. So before 1.0.0 a harness accepts only the MAJOR.MINOR it was written for, and from 1.0.0 only its MAJOR (harness-contract.md section 1).
