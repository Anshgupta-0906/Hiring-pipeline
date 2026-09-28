"""
ISO-8601 timestamp helpers used across the app.

Every timestamp in this app is one we generated ourselves (see now_iso()),
so a small hand-rolled parser is enough -- and, importantly, it keeps this
working on Python 3.6. datetime.fromisoformat() doesn't exist before 3.7,
and datetime.strptime()'s %z directive can't parse a colon in the UTC
offset ("+00:00") before 3.7 either. Relying on either breaks on older
interpreters with an AttributeError or ValueError, which is exactly the
bug this module exists to avoid.
"""
import re
from datetime import datetime, timezone, timedelta

_ISO_RE = re.compile(
    r"^(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})[T ]"
    r"(?P<h>\d{2}):(?P<mi>\d{2}):(?P<s>\d{2})"
    r"(?:\.(?P<us>\d{1,6}))?"
    r"(?P<tz>Z|[+-]\d{2}:?\d{2})?$"
)


def now_iso():
    """Current time as an ISO-8601 string with a UTC offset."""
    return datetime.now(timezone.utc).isoformat()


def parse_iso(ts):
    """Parse an ISO-8601 string (as produced by now_iso()) into an aware
    datetime, without relying on datetime.fromisoformat()."""
    m = _ISO_RE.match(ts.strip())
    if not m:
        # Not a shape we expect -- fall back and let Python's own parser
        # try, rather than silently returning something wrong.
        return datetime.fromisoformat(ts)

    us = (m.group("us") or "0").ljust(6, "0")[:6]

    tz = m.group("tz")
    tzinfo = timezone.utc
    if tz and tz != "Z":
        sign = 1 if tz[0] == "+" else -1
        digits = tz[1:].replace(":", "")
        hh = int(digits[0:2])
        mm = int(digits[2:4]) if len(digits) >= 4 else 0
        tzinfo = timezone(sign * timedelta(hours=hh, minutes=mm))

    return datetime(
        int(m.group("y")), int(m.group("mo")), int(m.group("d")),
        int(m.group("h")), int(m.group("mi")), int(m.group("s")),
        int(us), tzinfo=tzinfo,
    )
