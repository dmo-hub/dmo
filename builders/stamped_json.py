"""Shared JSON writer for outputs that carry a date stamp (built_at / fetched_at).

The stamp records when the CONTENT last changed, not when the script last ran.
Stamping date.today() unconditionally made every rebuild on a new day produce
a one-line diff, which failed tools/validate.py's idempotency gate and put
noise into every refresh PR even when no data moved.
"""

import json
from pathlib import Path


def _same_except(a: dict, b: dict, key: str) -> bool:
    return ({k: v for k, v in a.items() if k != key}
            == {k: v for k, v in b.items() if k != key})


def write_stamped(path: Path, payload: dict, key: str) -> None:
    """Write payload as JSON, keeping the old payload[key] if nothing else changed.

    payload[key] should already hold today's stamp; it is replaced by the stamp
    already on disk only when every other field is identical.
    """
    # Round-trip so tuples/ints compare the way they will read back from disk.
    new = json.loads(json.dumps(payload, ensure_ascii=False))
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = None
    if isinstance(old, dict) and key in old and _same_except(old, new, key):
        payload = {k: (old[key] if k == key else v) for k, v in payload.items()}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
