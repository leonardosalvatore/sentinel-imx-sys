"""Python port of the daemon's sanitize + encode pipeline (src/sanitizer.cpp,
src/encoder.cpp). It MUST stay byte-for-byte compatible with the C++ so the
model is trained on exactly the vectors the daemon feeds at run time.

The daemon captures the *already-sanitized* template, so training only needs
encode(); sanitize() is provided for offline experiments on raw log lines.
"""
import math

FEATURE_DIM = 64


def _is_digit(c):
    return "0" <= c <= "9"


def _is_hex(c):
    return ("0" <= c <= "9") or ("a" <= c <= "f")


def _run(s, i, pred):
    j = i
    n = len(s)
    while j < n and pred(s[j]):
        j += 1
    return j - i


def _match_uuid(s, i):
    groups = (8, 4, 4, 4, 12)
    p = i
    for g, want in enumerate(groups):
        if g > 0:
            if p >= len(s) or s[p] != "-":
                return 0
            p += 1
        got = _run(s, p, _is_hex)
        if got != want:
            return 0
        p += want
    return p - i


def _match_ipv4(s, i):
    p = i
    for g in range(4):
        if g > 0:
            if p >= len(s) or s[p] != ".":
                return 0
            p += 1
        got = _run(s, p, _is_digit)
        if got < 1 or got > 3:
            return 0
        p += got
    if p < len(s) and s[p] == "." and p + 1 < len(s) and _is_digit(s[p + 1]):
        return 0
    return p - i


def _match_hex(s, i):
    if i + 2 >= len(s):
        return 0
    if s[i] != "0" or s[i + 1] != "x":
        return 0
    got = _run(s, i + 2, _is_hex)
    if got == 0:
        return 0
    return 2 + got


def _match_bracket_pid(s, i):
    if s[i] != "[" and s[i] != "(":
        return 0
    close = "]" if s[i] == "[" else ")"
    got = _run(s, i + 1, _is_digit)
    if got == 0:
        return 0
    p = i + 1 + got
    if p >= len(s) or s[p] != close:
        return 0
    return (p - i) + 1


def sanitize(raw):
    s = raw.lower()
    out = []
    n = len(s)
    i = 0
    while i < n:
        length = _match_hex(s, i)
        if length:
            out.append("<HEX>"); i += length; continue
        length = _match_uuid(s, i)
        if length:
            out.append("<UUID>"); i += length; continue
        length = _match_ipv4(s, i)
        if length:
            out.append("<IP>"); i += length; continue
        if s[i] in "[(":
            length = _match_bracket_pid(s, i)
            if length:
                out.append("<PID>"); i += length; continue
        if _is_digit(s[i]):
            out.append("<NUM>"); i += _run(s, i, _is_digit); continue
        out.append(s[i]); i += 1
    joined = "".join(out)

    collapsed = []
    in_space = False
    for c in joined:
        if c.isspace():
            in_space = True
            continue
        if in_space and collapsed:
            collapsed.append(" ")
        in_space = False
        collapsed.append(c)
    return "".join(collapsed)


def _fnv1a(tok):
    h = 2166136261
    for b in tok.encode("utf-8", "surrogatepass"):
        h ^= b
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def _is_token_char(c):
    o = ord(c)
    return (97 <= o <= 122) or (65 <= o <= 90) or (48 <= o <= 57) \
        or c in "<>_"


def encode(tmpl):
    """Return the normalized INT8 feature vector as a list[int] of length 64,
    identical to src/encoder.cpp encode()."""
    acc = [0] * FEATURE_DIM
    n = len(tmpl)
    i = 0
    while i < n:
        if not _is_token_char(tmpl[i]):
            i += 1
            continue
        start = i
        while i < n and _is_token_char(tmpl[i]):
            i += 1
        h = _fnv1a(tmpl[start:i])
        acc[h % FEATURE_DIM] += 1 if (h & 0x10000) else -1

    norm2 = sum(v * v for v in acc)
    out = [0] * FEATURE_DIM
    if norm2 > 0:
        scale = 127.0 / math.sqrt(norm2)
        for k in range(FEATURE_DIM):
            # Match C++ std::lround: round half away from zero (Python's round()
            # is banker's rounding, which would disagree on .5 boundaries).
            x = acc[k] * scale
            q = math.floor(x + 0.5) if x >= 0 else math.ceil(x - 0.5)
            if q > 127:
                q = 127
            elif q < -127:
                q = -127
            out[k] = int(q)
    return out
