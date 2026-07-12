"""Tiny, dependency-free .env reader for the test scripts.

Parses KEY=value lines, ignoring comments/blanks, stripping inline comments and
surrounding quotes. Does NOT run the file as code, so odd values, spaces, and
`$(...)` can't break anything. Existing os.environ values win (so CLI/shell
overrides are respected)."""
import os


def _find_env(start: str = ".") -> str | None:
    """Walk up from cwd (and this file's dir) to find a .env."""
    seen = []
    for base in (os.getcwd(), os.path.dirname(os.path.abspath(__file__))):
        d = base
        for _ in range(6):
            cand = os.path.join(d, ".env")
            if cand not in seen:
                seen.append(cand)
                if os.path.isfile(cand):
                    return cand
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    return None


def load_dotenv(path: str | None = None, override: bool = False) -> int:
    path = path or _find_env()
    if not path or not os.path.isfile(path):
        return 0
    n = 0
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            if not key.replace("_", "").isalnum() or key[0].isdigit():
                continue
            # strip inline comment only when '#' follows whitespace
            for i in range(1, len(val)):
                if val[i] == "#" and val[i - 1] in " \t":
                    val = val[:i]
                    break
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            if override or key not in os.environ:
                os.environ[key] = val
                n += 1
    return n
