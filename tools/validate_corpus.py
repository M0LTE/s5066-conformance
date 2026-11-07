#!/usr/bin/env python3
"""Validate the s5066-conformance corpus against docs/corpus-format.md and docs/prng.md.

Checks that every corpus file parses and follows the schema. It also carries a
small reference decoder for the registered D_PDU types and a reference
SplitMix64, and checks every T1 value, error kind and PRNG value against them,
to catch typing mistakes. It is a checker, not an implementation to copy.

Usage:
  python3 tools/validate_corpus.py [--root DIR] [--matrix DIR] [--coverage] [--strict]

  --root DIR    repository root (default: the parent of this script's directory)
  --matrix DIR  check cited row ids exist in DIR/*.tsv
  --coverage    with --matrix: fail if an applies=yes row has no case and no tests entry
  --strict      reject "TODO" in rows

Exit status 0 when valid, 1 when not. Python 3, standard library only.
"""
import argparse
import glob
import json
import os
import re
import sys

ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
ROW_RE = re.compile(r"^[A-Z]+-[0-9]{4}$")
HEX_RE = re.compile(r"^(?:[0-9a-f]{2})*$")
HEX64_RE = re.compile(r"^[0-9a-f]{16}$")
ADDR_RE = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")
TIMER_RE = re.compile(r"^(sis|cas|dts|csma|drc|station)\.[a-z0-9_]+(/[a-z0-9_.]+)?$")
MAX_INT = (1 << 53) - 1

IFRAME_TYPES = {0, 2, 4, 7, 8, 9, 11}
ED4_ONLY_TYPES = set(range(9, 15))
INTERLEAVERS = {"ultra_short", "very_short", "short", "medium", "long", "very_long"}
ERROR_KINDS = {"truncated", "bad_sync", "header_crc", "bad_header_size",
               "bad_address_size", "trailing_bytes", "invalid_field"}

# Registered D_PDU type-specific field sets: name -> (kind, max) where kind is "bool" or "int".
DPDU_FIELDS = {
    0: {"c_pdu_start": "bool", "c_pdu_end": "bool", "deliver_in_order": "bool",
        "drop_c_pdu": "bool", "tx_win_uwe": "bool", "tx_win_lwe": "bool", "tx_fsn": 255},
    3: {"full_reset_cmnd": "bool", "reset_tx_win_rqst": "bool", "reset_rx_win_cmnd": "bool",
        "reset_ack": "bool", "new_rx_lwe": 255, "reset_frame_id": 255},
    7: {"c_pdu_id": 4095, "deliver_in_order": "bool", "group_address": "bool",
        "c_pdu_size": 65535, "c_pdu_segment_offset": 65535, "c_pdu_reception_window": 65535},
    15: {"received_frame_type": 15, "reason": 15},
}
DPDU_FIELDS[8] = DPDU_FIELDS[7]

# T2 inputs: name -> (class, {key: type}).
T2_INPUTS = {
    "config": (0, {"set": "object"}),
    "timer_expired": (1, {"name": "timer"}),
    "burst_started": (2, {}),
    "bytes_received": (2, {"bytes": "hex"}),
    "burst_ended": (2, {"reason": "reason", "wn": "int", "interleaver": "interleaver",
                        "k": "int", "snr_tenth_db": "int_or_null_signed", "blocks": "int"}),
    "transmit_done": (2, {}),
    "channel_busy": (2, {"busy": "bool"}),
    "sis_connect": (3, {"conn": "posint"}),
    "sis_bytes": (3, {"conn": "posint", "bytes": "hex"}),
    "sis_disconnect": (3, {"conn": "posint"}),
}
T2_OUTPUTS = {
    "transmit": {"bytes": "hex", "wn": "int", "interleaver": "interleaver", "k": "int", "eom": "bool"},
    "terminate_receive": {},
    "set_max_input_blocks": {"n": "posint"},
    "timer_start": {"name": "timer", "ms": "posint"},
    "timer_cancel": {"name": "timer"},
    "sis_bytes": {"conn": "posint", "bytes": "hex"},
    "sis_close": {"conn": "posint"},
    "link_state": {"peer": "addr", "state": "str"},
}
BURST_END_REASONS = {"eom", "signal_lost", "terminated"}
# Registered names (corpus-format.md section 4.6). Empty until the first scenario needs one.
REGISTERED_TIMERS = set()
REGISTERED_LINK_STATES = set()


class Errors:
    def __init__(self):
        self.items = []

    def add(self, where, msg):
        self.items.append("%s: %s" % (where, msg))


def crc(data, poly):
    c = 0
    for d in data:
        i = 1
        while i < 256:
            bit = (c & 1) ^ (1 if d & i else 0)
            c >>= 1
            if bit:
                c ^= poly
            i <<= 1
    return c


def is_int(v, lo=0, hi=MAX_INT):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def is_hex(v):
    return isinstance(v, str) and HEX_RE.match(v) is not None


def addr_value(v):
    if not isinstance(v, str):
        return None
    m = ADDR_RE.match(v)
    if not m:
        return None
    w, x, y, z = (int(g) for g in m.groups())
    if w > 15 or x > 255 or y > 255 or z > 255 or str(w) != m.group(1) or str(x) != m.group(2) \
            or str(y) != m.group(3) or str(z) != m.group(4):
        return None
    return (w << 24) | (x << 16) | (y << 8) | z


def check_type(v, t):
    if t == "hex":
        return is_hex(v)
    if t == "int":
        return is_int(v)
    if t == "posint":
        return is_int(v, 1)
    if t == "bool":
        return isinstance(v, bool)
    if t == "str":
        return isinstance(v, str) and v != ""
    if t == "object":
        return isinstance(v, dict)
    if t == "interleaver":
        return v in INTERLEAVERS
    if t == "reason":
        return v in BURST_END_REASONS
    if t == "int_or_null_signed":
        return v is None or is_int(v, -MAX_INT)
    if t == "addr":
        return addr_value(v) is not None
    if t == "timer":
        return isinstance(v, str) and TIMER_RE.match(v) is not None
    raise AssertionError(t)


def check_keys(err, where, obj, required, optional=()):
    for k in required:
        if k not in obj:
            err.add(where, "missing key '%s'" % k)
    for k in obj:
        if k not in required and k not in optional:
            err.add(where, "unknown key '%s'" % k)


def read_jsonl(path, err):
    out = []
    with open(path, "rb") as f:
        raw = f.read()
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        err.add(path, "not ASCII")
        return out
    if "\r" in text:
        err.add(path, "carriage return found; use Unix line endings")
    if text and not text.endswith("\n"):
        err.add(path, "last line has no newline")
    for n, line in enumerate(text.split("\n")[:-1] if text.endswith("\n") else text.split("\n"), 1):
        where = "%s:%d" % (path, n)
        if line.strip() == "":
            err.add(where, "blank line")
            continue
        try:
            obj = json.loads(line, object_pairs_hook=no_duplicates, parse_constant=bad_constant)
        except ValueError as e:
            err.add(where, "JSON error: %s" % e)
            continue
        if not isinstance(obj, dict):
            err.add(where, "line is not a JSON object")
            continue
        if contains_float(obj):
            err.add(where, "floating point value found")
        out.append((where, obj))
    return out


def no_duplicates(pairs):
    seen = {}
    for k, v in pairs:
        if k in seen:
            raise ValueError("duplicate key %r" % k)
        seen[k] = v
    return seen


def bad_constant(s):
    raise ValueError("%s is not JSON" % s)


def contains_float(v):
    if isinstance(v, float):
        return True
    if isinstance(v, dict):
        return any(contains_float(x) for x in v.values())
    if isinstance(v, list):
        return any(contains_float(x) for x in v)
    return False


def check_rows(err, where, rows, ctx):
    if not isinstance(rows, list) or not rows:
        err.add(where, "rows must be a non-empty list")
        return
    for r in rows:
        if r == "TODO":
            ctx["todo"] += 1
            if ctx["strict"]:
                err.add(where, "row TODO not allowed in strict mode")
        elif isinstance(r, str) and ROW_RE.match(r):
            ctx["cited"].setdefault(r, []).append(where)
        else:
            err.add(where, "bad row id %r" % (r,))


def check_id(err, where, cid, ctx):
    if not isinstance(cid, str) or not ID_RE.match(cid):
        err.add(where, "bad id %r" % (cid,))
        return
    if cid in ctx["ids"]:
        err.add(where, "duplicate id '%s' (first at %s)" % (cid, ctx["ids"][cid]))
    else:
        ctx["ids"][cid] = where


# ---------------------------------------------------------------- T1

def check_t1(path, err, ctx):
    for where, c in read_jsonl(path, err):
        ctx["t1"] += 1
        check_keys(err, where, c, ("id", "kind", "dir", "rows", "source", "bytes"),
                   ("value", "error", "peer_edition", "note"))
        check_id(err, where, c.get("id"), ctx)
        check_rows(err, where, c.get("rows"), ctx)
        if not isinstance(c.get("source"), str) or not c.get("source"):
            err.add(where, "source must be a non-empty string")
        if "note" in c and not isinstance(c["note"], str):
            err.add(where, "note must be a string")
        d = c.get("dir")
        if d not in ("encode", "decode", "both"):
            err.add(where, "dir must be encode, decode or both")
        if not is_hex(c.get("bytes")):
            err.add(where, "bytes must be lower-case hex")
            continue
        b = bytes.fromhex(c["bytes"])
        has_v, has_e = "value" in c, "error" in c
        if has_v == has_e:
            err.add(where, "exactly one of value and error is required")
            continue
        if has_e:
            if d != "decode":
                err.add(where, "error cases must have dir decode")
            if c["error"] not in ERROR_KINDS:
                err.add(where, "unknown error kind %r" % (c["error"],))
        elif not isinstance(c["value"], dict):
            err.add(where, "value must be an object")
            continue
        kind = c.get("kind")
        if kind in ("crc16", "crc32"):
            check_crc_case(err, where, c, b, kind)
        elif kind == "dpdu":
            check_dpdu_case(err, where, c, b)
        else:
            err.add(where, "unregistered kind %r" % (kind,))


def check_crc_case(err, where, c, b, kind):
    width, poly = (2, 0x9299) if kind == "crc16" else (4, 0xF3A4E550)
    if c.get("dir") != "encode" or "value" not in c:
        err.add(where, "%s cases are encode only" % kind)
        return
    if "peer_edition" in c:
        err.add(where, "peer_edition is only for dpdu")
    v = c["value"]
    check_keys(err, where, v, ("data", "register"))
    if not is_hex(v.get("data")) or not is_int(v.get("register"), 0, (1 << (8 * width)) - 1):
        err.add(where, "value needs hex data and an integer register")
        return
    reg = crc(bytes.fromhex(v["data"]), poly)
    if reg != v["register"]:
        err.add(where, "register is 0x%X, data gives 0x%X" % (v["register"], reg))
    if b != reg.to_bytes(width, "little"):
        err.add(where, "bytes must be the register least significant byte first")


# Size-of-header field h (corpus-format.md section 3.3): fixed values, and minimums.
DPDU_FIXED_H = {0: 9, 3: 9, 7: 15, 8: 15, 15: 7}
DPDU_ED4_MIN_H = {10: 10}
UNDEFINED_MIN_H = 6


def dotted(a):
    return "%d.%d.%d.%d" % ((a >> 24) & 15, (a >> 16) & 255, (a >> 8) & 255, a & 255)


def ref_decode(b, peer):
    """Reference D_PDU decode following the check order in corpus-format.md section 3.3.

    Returns ("value", obj), ("error", kind) or ("unsupported", reason)."""
    if len(b) < 2:
        return "error", "truncated"
    if b[:2] != b"\x90\xeb":
        return "error", "bad_sync"
    if len(b) < 6:
        return "error", "truncated"
    t, m, h = b[2] >> 4, b[5] >> 5, b[5] & 31
    if m == 0:
        return "error", "bad_address_size"
    undefined = peer == "ed3" and t in ED4_ONLY_TYPES
    if undefined:
        ok = h >= UNDEFINED_MIN_H
    elif peer == "ed4" and t in DPDU_ED4_MIN_H:
        ok = h >= DPDU_ED4_MIN_H[t]
    elif t in DPDU_FIXED_H and not (peer == "any" and t in ED4_ONLY_TYPES):
        ok = h == DPDU_FIXED_H[t]
    else:
        return "unsupported", "no registered header size for type %d under %s" % (t, peer)
    if not ok:
        return "error", "bad_header_size"
    end = 2 + h + m
    if len(b) < end:
        return "error", "truncated"
    if crc(b[2:end - 2], 0x9299) != b[end - 2] | (b[end - 1] << 8):
        return "error", "header_crc"
    a = int.from_bytes(b[6:6 + m], "big")
    v = {"type": t, "eow": ((b[2] & 15) << 8) | b[3], "eot": b[4], "address_size": m,
         "dst": dotted(a >> (4 * m)), "src": dotted(a & ((1 << (4 * m)) - 1))}
    ts = b[6 + m:end - 2]
    rest = b[end:]
    n = None
    if undefined:
        v["fields"] = {"undefined": True, "type_specific": ts.hex()}
    elif t == 0:
        x = ts[0]
        v["fields"] = {"c_pdu_start": bool(x & 0x80), "c_pdu_end": bool(x & 0x40),
                       "deliver_in_order": bool(x & 0x20), "drop_c_pdu": bool(x & 0x10),
                       "tx_win_uwe": bool(x & 8), "tx_win_lwe": bool(x & 4), "tx_fsn": ts[2]}
        n = ((x & 3) << 8) | ts[1]
    elif t == 3:
        if ts[0] & 0xF0:
            return "unsupported", "NOT USED bits set (corpus-format.md section 3.3)"
        x = ts[0]
        v["fields"] = {"full_reset_cmnd": bool(x & 8), "reset_tx_win_rqst": bool(x & 4),
                       "reset_rx_win_cmnd": bool(x & 2), "reset_ack": bool(x & 1),
                       "new_rx_lwe": ts[1], "reset_frame_id": ts[2]}
    elif t in (7, 8):
        x = ts[0]
        v["fields"] = {"c_pdu_id": ((x >> 4) << 8) | ts[2], "deliver_in_order": bool(x & 8),
                       "group_address": bool(x & 4),
                       "c_pdu_size": int.from_bytes(ts[3:5], "big"),
                       "c_pdu_segment_offset": int.from_bytes(ts[5:7], "big"),
                       "c_pdu_reception_window": int.from_bytes(ts[7:9], "big")}
        n = ((x & 3) << 8) | ts[1]
    elif t == 15:
        v["fields"] = {"received_frame_type": ts[0] >> 4, "reason": ts[0] & 15}
    else:
        return "unsupported", "no registered field set for type %d" % t
    if n is not None:
        if len(rest) < n + 4:
            return "error", "truncated"
        seg = rest[:n]
        v["segment"] = seg.hex()
        v["segment_crc_ok"] = crc(seg, 0xF3A4E550) == int.from_bytes(rest[n:n + 4], "little")
        rest = rest[n + 4:]
    if rest:
        return "error", "trailing_bytes"
    return "value", v


def check_dpdu_case(err, where, c, b):
    peer = c.get("peer_edition")
    if peer not in ("any", "ed3", "ed4"):
        err.add(where, "dpdu cases need peer_edition any, ed3 or ed4")
        return
    if len(b) >= 3 and b[:2] == b"\x90\xeb":
        t = b[2] >> 4
        if peer == "any" and t in ED4_ONLY_TYPES:
            err.add(where, "type %d differs between editions; use peer_edition ed3 or ed4" % t)
        if peer == "ed3" and t in ED4_ONLY_TYPES and c.get("dir") != "decode":
            err.add(where, "an undefined type can only be decoded")
    if "value" in c:
        check_dpdu_value(err, where, c, peer)
    res, out = ref_decode(b, peer)
    if res == "unsupported":
        err.add(where, "cannot check: %s" % out)
    elif "error" in c:
        if res != "error" or out != c["error"]:
            err.add(where, "check order gives %s, case says error %s"
                    % (out if res == "error" else "a value", c["error"]))
    elif res == "error":
        err.add(where, "bytes decode to error %s" % out)
    elif out != c["value"]:
        diff = sorted(k for k in set(out) | set(c["value"]) if out.get(k) != c["value"].get(k))
        err.add(where, "value disagrees with the bytes in: %s" % ", ".join(diff))


def check_dpdu_value(err, where, c, peer):
    v = c["value"]
    t = v.get("type")
    if not is_int(t, 0, 15):
        err.add(where, "type must be 0 to 15")
        return
    undefined = peer == "ed3" and t in ED4_ONLY_TYPES
    has_seg = (t in IFRAME_TYPES) and not undefined
    req = ["type", "eow", "eot", "address_size", "dst", "src", "fields"]
    if has_seg:
        req += ["segment", "segment_crc_ok"]
    check_keys(err, where, v, req)
    if not is_int(v.get("eow"), 0, 4095):
        err.add(where, "eow must be 0 to 4095")
    if not is_int(v.get("eot"), 0, 255):
        err.add(where, "eot must be 0 to 255")
    m = v.get("address_size")
    if not is_int(m, 1, 7):
        err.add(where, "address_size must be 1 to 7")
        return
    for k in ("dst", "src"):
        a = addr_value(v.get(k))
        if a is None:
            err.add(where, "%s must be a dotted address" % k)
        elif a >= 1 << (4 * m):
            err.add(where, "%s does not fit in address_size %d" % (k, m))
    f = v.get("fields")
    if not isinstance(f, dict):
        err.add(where, "fields must be an object")
        return
    if undefined:
        check_keys(err, where, f, ("undefined", "type_specific"))
        if f.get("undefined") is not True or not is_hex(f.get("type_specific")):
            err.add(where, "undefined type needs undefined true and hex type_specific")
    else:
        spec = DPDU_FIELDS.get(t)
        if spec is None:
            err.add(where, "no registered field set for type %d" % t)
        else:
            check_keys(err, where, f, tuple(spec))
            for k, kt in spec.items():
                if k in f:
                    ok = isinstance(f[k], bool) if kt == "bool" else is_int(f[k], 0, kt)
                    if not ok:
                        err.add(where, "field %s has a bad value" % k)
    if has_seg:
        if not is_hex(v.get("segment")) or len(v.get("segment", "")) // 2 > 1023:
            err.add(where, "segment must be hex of at most 1023 bytes")
        if not isinstance(v.get("segment_crc_ok"), bool):
            err.add(where, "segment_crc_ok must be a boolean")
        elif not v["segment_crc_ok"] and c.get("dir") != "decode":
            err.add(where, "segment_crc_ok false is only allowed in decode cases")


# ---------------------------------------------------------------- T2

def merge(base, overlay, err, where, path=""):
    out = dict(base)
    for k, v in overlay.items():
        if k not in base:
            err.add(where, "config key '%s%s' is not in defaults.json" % (path, k))
        elif isinstance(base[k], dict) and isinstance(v, dict):
            out[k] = merge(base[k], v, err, where, path + k + ".")
        elif isinstance(base[k], dict) or isinstance(v, dict):
            err.add(where, "config key '%s%s' mixes an object and a non-object" % (path, k))
        else:
            out[k] = v
    return out


def check_modem_fixture(err, where, cfg):
    """corpus-format.md section 5: positive sizes, at most one entry per wn and interleaver."""
    wfs = cfg.get("modem", {}).get("waveforms") if isinstance(cfg.get("modem"), dict) else None
    if not isinstance(wfs, list):
        err.add(where, "modem.waveforms must be a list")
        return
    seen = set()
    for e in wfs:
        if not isinstance(e, dict):
            err.add(where, "modem.waveforms entries must be objects")
            continue
        check_keys(err, where, e, ("wn", "interleaver", "block_bytes", "block_ms"))
        if not (is_int(e.get("wn")) and e.get("interleaver") in INTERLEAVERS
                and is_int(e.get("block_bytes"), 1) and is_int(e.get("block_ms"), 1)):
            err.add(where, "modem.waveforms entry has a bad value")
        key = (e.get("wn"), e.get("interleaver"))
        if key in seen:
            err.add(where, "modem.waveforms has two entries for wn %r %r" % key)
        seen.add(key)


def check_t2(path, err, ctx, defaults):
    lines = read_jsonl(path, err)
    if not lines:
        err.add(path, "empty scenario")
        return
    ctx["t2"] += 1
    where, hdr = lines[0]
    check_keys(err, where, hdr, ("scenario", "rows", "source", "description", "config"), ("note",))
    check_id(err, where, hdr.get("scenario"), ctx)
    check_rows(err, where, hdr.get("rows"), ctx)
    for k in ("source", "description"):
        if not isinstance(hdr.get(k), str) or not hdr.get(k):
            err.add(where, "%s must be a non-empty string" % k)
    if not isinstance(hdr.get("config"), dict):
        err.add(where, "config must be an object")
    elif defaults is not None:
        check_modem_fixture(err, where, merge(defaults, hdr["config"], err, where))
    timers = {}  # name -> (deadline, start sequence number)
    starts = 0
    conns, closed = set(), set()
    last_t, last_class, now = -1, -1, 0
    last_expiry = None  # (t, start sequence) of the previous timer_expired input
    seen_input = False
    for where, s in lines[1:]:
        if "in" in s and "out" in s:
            err.add(where, "a step has either in or out, not both")
            continue
        if "in" in s:
            kind = s["in"]
            if kind not in T2_INPUTS:
                err.add(where, "unknown input %r" % (kind,))
                continue
            cls, keys = T2_INPUTS[kind]
            check_keys(err, where, s, ("t", "in") + tuple(keys))
            for k, kt in keys.items():
                if k in s and not check_type(s[k], kt):
                    err.add(where, "%s has a bad value" % k)
            t = s.get("t")
            if not is_int(t):
                err.add(where, "t must be a non-negative integer")
                continue
            if t < last_t:
                err.add(where, "t goes backwards")
            if t == last_t and cls < last_class:
                err.add(where, "same-time inputs out of class order")
            if kind == "timer_expired":
                name = s.get("name")
                entry = timers.pop(name, None)
                if entry is None or entry[0] != t:
                    err.add(where, "timer '%s' is not due at %d" % (name, t))
                elif last_expiry is not None and last_expiry[0] == t and entry[1] < last_expiry[1]:
                    err.add(where, "same-time expiries not in the order the timers were started")
                if entry is not None:
                    last_expiry = (t, entry[1])
            # A timer due at t may still be pending while class 0 (config) inputs at t are fed.
            due = [n for n, (dl, _) in timers.items() if dl < t or (dl == t and cls > 1)]
            if due:
                err.add(where, "timers due but not expired: %s" % ", ".join(sorted(due)))
                for n in due:
                    timers.pop(n)
            if kind == "config" and defaults is not None and isinstance(s.get("set"), dict):
                merge(defaults, s["set"], err, where)
            conn = s.get("conn")
            if kind == "sis_connect":
                if conn in conns or conn in closed:
                    err.add(where, "conn %r was already used in this scenario" % (conn,))
                conns.add(conn)
            elif kind in ("sis_bytes", "sis_disconnect") and conn not in conns:
                err.add(where, "conn %r is not connected" % (conn,))
            if kind == "sis_disconnect":
                conns.discard(conn)
                closed.add(conn)
            last_t, last_class, now, seen_input = t, cls, t, True
        elif "out" in s:
            kind = s["out"]
            if not seen_input:
                err.add(where, "output before any input")
            if kind not in T2_OUTPUTS:
                err.add(where, "unknown output %r" % (kind,))
                continue
            keys = T2_OUTPUTS[kind]
            check_keys(err, where, s, ("out",) + tuple(keys))
            for k, kt in keys.items():
                if k in s and not check_type(s[k], kt):
                    err.add(where, "%s has a bad value" % k)
            name = s.get("name")
            if kind in ("timer_start", "timer_cancel") and isinstance(name, str):
                base = name.split("/")[0]
                if base not in REGISTERED_TIMERS:
                    err.add(where, "timer name '%s' is not registered" % base)
                if kind == "timer_start" and is_int(s.get("ms"), 1):
                    starts += 1
                    timers[name] = (now + s["ms"], starts)
                elif kind == "timer_cancel":
                    timers.pop(name, None)
            if kind in ("sis_bytes", "sis_close") and s.get("conn") not in conns:
                err.add(where, "conn %r is not connected" % (s.get("conn"),))
            if kind == "sis_close":
                conns.discard(s.get("conn"))
                closed.add(s.get("conn"))
            if kind == "link_state" and s.get("state") not in REGISTERED_LINK_STATES:
                err.add(where, "link state %r is not registered" % (s.get("state"),))
        else:
            err.add(where, "step needs in or out")


# ---------------------------------------------------------------- PRNG

def splitmix64(s):
    """One SplitMix64 step: returns (new state, output)."""
    mask = (1 << 64) - 1
    s = (s + 0x9E3779B97F4A7C15) & mask
    z = ((s ^ (s >> 30)) * 0xBF58476D1CE4E5B9) & mask
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & mask
    return s, z ^ (z >> 31)


def check_prng(path, err, ctx):
    for where, c in read_jsonl(path, err):
        ctx["prng"] += 1
        check_id(err, where, c.get("id"), ctx)
        op = c.get("op")
        if op == "next_u64":
            check_keys(err, where, c, ("id", "seed", "op", "results"))
            ok = isinstance(c.get("results"), list) and c["results"] and \
                all(isinstance(r, str) and HEX64_RE.match(r) for r in c["results"])
        elif op == "uniform":
            check_keys(err, where, c, ("id", "seed", "op", "n", "results", "state_after"))
            ok = isinstance(c.get("n"), str) and HEX64_RE.match(c["n"]) and int(c["n"], 16) >= 1 \
                and isinstance(c.get("state_after"), str) and HEX64_RE.match(c["state_after"]) \
                and isinstance(c.get("results"), list) and c["results"] and all(
                    isinstance(r, dict) and set(r) == {"value", "draws"}
                    and isinstance(r["value"], str) and HEX64_RE.match(r["value"])
                    and is_int(r["draws"], 1) for r in c["results"])
        else:
            err.add(where, "op must be next_u64 or uniform")
            continue
        if not (isinstance(c.get("seed"), str) and HEX64_RE.match(c["seed"]) and ok):
            err.add(where, "bad seed, n or results")
            continue
        s = int(c["seed"], 16)
        if op == "next_u64":
            got = []
            for _ in c["results"]:
                s, x = splitmix64(s)
                got.append("%016x" % x)
        else:
            n = int(c["n"], 16)
            threshold = ((1 << 64) - n) % n
            got = []
            for _ in c["results"]:
                used = 0
                while True:
                    s, x = splitmix64(s)
                    used += 1
                    if x >= threshold:
                        break
                got.append({"value": "%016x" % (x % n), "draws": used})
            if "%016x" % s != c["state_after"]:
                err.add(where, "state_after should be %016x" % s)
        if got != c["results"]:
            err.add(where, "results disagree with SplitMix64 (prng.md)")


# ---------------------------------------------------------------- matrix

def read_matrix(mdir, err):
    rows = {}
    for path in sorted(glob.glob(os.path.join(mdir, "*.tsv"))):
        with open(path, encoding="ascii", errors="replace") as f:
            lines = f.read().split("\n")
        if not lines or not lines[0].startswith("id\t"):
            err.add(path, "first line must be the header row starting with id")
            continue
        cols = lines[0].split("\t")
        for n, line in enumerate(lines[1:], 2):
            if not line.strip():
                continue
            cells = dict(zip(cols, line.split("\t")))
            rid = cells.get("id", "")
            if rid in rows:
                err.add("%s:%d" % (path, n), "duplicate row id %s" % rid)
            rows[rid] = cells
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    ap.add_argument("--matrix")
    ap.add_argument("--coverage", action="store_true")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    root = os.path.normpath(a.root)
    corpus = os.path.join(root, "corpus")
    err = Errors()
    ctx = {"ids": {}, "cited": {}, "todo": 0, "strict": a.strict, "t1": 0, "t2": 0, "prng": 0}

    vpath = os.path.join(corpus, "VERSION")
    try:
        ver = open(vpath, encoding="ascii").read()
        if not re.match(r"^\d+\.\d+\.\d+\n$", ver):
            err.add(vpath, "must be one line MAJOR.MINOR.PATCH")
    except OSError:
        err.add(vpath, "missing")
        ver = "?"

    defaults = None
    dpath = os.path.join(corpus, "t2", "defaults.json")
    try:
        defaults = json.load(open(dpath, encoding="ascii"))
        if not isinstance(defaults, dict) or contains_float(defaults):
            err.add(dpath, "must be a JSON object with no floating point")
            defaults = None
    except (OSError, ValueError) as e:
        err.add(dpath, "cannot read: %s" % e)

    for p in sorted(glob.glob(os.path.join(corpus, "t1", "*.jsonl"))):
        check_t1(p, err, ctx)
    for p in sorted(glob.glob(os.path.join(corpus, "t2", "**", "*.jsonl"), recursive=True)):
        check_t2(p, err, ctx, defaults)
    ppath = os.path.join(corpus, "prng", "splitmix64.jsonl")
    if os.path.exists(ppath):
        check_prng(ppath, err, ctx)
    else:
        err.add(ppath, "missing")

    t1dir, t2dir = os.path.join(corpus, "t1"), os.path.join(corpus, "t2")
    stray = [p for p in glob.glob(os.path.join(corpus, "**", "*"), recursive=True)
             if os.path.isfile(p) and p not in (vpath, dpath, ppath)
             and not (p.endswith(".jsonl") and (os.path.dirname(p) == t1dir
                                                 or os.path.dirname(os.path.dirname(p)) == t2dir))]
    for p in stray:
        err.add(p, "unexpected file in corpus/")

    if a.matrix:
        mrows = read_matrix(a.matrix, err)
        for rid, wheres in sorted(ctx["cited"].items()):
            if rid not in mrows:
                err.add(wheres[0], "row %s is not in the matrix" % rid)
        if a.coverage:
            for rid, cells in sorted(mrows.items()):
                if cells.get("applies") == "yes" and rid not in ctx["cited"] \
                        and not cells.get("tests", "").strip():
                    err.add(a.matrix, "row %s applies but has no test" % rid)
    elif a.coverage:
        err.add("--coverage", "needs --matrix")

    for e in err.items:
        print("ERROR " + e.replace(root + os.sep, ""))
    print("corpus %s: %d T1 cases, %d T2 scenarios, %d PRNG cases, %d TODO row refs, %d errors"
          % (ver.strip(), ctx["t1"], ctx["t2"], ctx["prng"], ctx["todo"], len(err.items)))
    return 1 if err.items else 0


if __name__ == "__main__":
    sys.exit(main())
