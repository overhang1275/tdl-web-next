"""Deterministic test executable. Never contacts Telegram."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def main(args: list[str]) -> int:
    def option(name: str, default: str = "") -> str:
        return args[args.index(name) + 1] if name in args else default

    if "version" in args or "--version" in args:
        print("fake-tdl 1.0 (tests only)")
    elif "ls" in args:
        print(json.dumps([{"id": 123, "title": "Canal de pruebas", "type": "channel"}]))
    elif "export" in args:
        chat = option("-c", "123")
        rows = [{"id": i, "file": f"sample-{i}.txt", "text": "#demo", "file_size": 8} for i in range(1, 4)]
        if option("--type") == "last":
            rows = rows[-int(option("--input", "1")):]
        elif option("--type") == "id":
            lower, upper = map(int, option("--input").split(","))
            rows = [row for row in rows if lower <= row["id"] <= upper]
        target = Path(option("-o"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"id": int(chat), "messages": rows}), encoding="utf-8")
    elif "download" in args:
        data = json.loads(Path(option("-f")).read_text(encoding="utf-8"))
        for message in data["messages"]:
            destination = Path(option("-d")) / str(message["id"]) / Path(message["file"]).name
            destination.parent.mkdir(parents=True, exist_ok=True)
            time.sleep(0.2)
            destination.write_bytes(b"complete")
    else:
        print("Unsupported fake-tdl command", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
