"""Replay the event samples of the documentation through the generated models."""

from collections import Counter
import json
from pathlib import Path

from pydantic import ValidationError

from codegen.events import event_sample
from larkify.webhooks import EVENT_MODULES, get_event_class, parse_obj


def main() -> None:
    stats: Counter[str] = Counter()
    for path in sorted(Path("schema/events").glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        event_type = document["catalog"]["url"]
        content = document["detail"].get("content") or ""
        cls = get_event_class(event_type)
        if cls is None:
            print("no model", event_type)
            continue

        sample = event_sample(content)
        if sample is None:
            stats["no sample"] += 1
            continue

        try:
            event = cls.model_validate(sample)
        except ValidationError as e:
            stats["failed"] += 1
            first = e.errors()[0]
            print(event_type, ".".join(map(str, first["loc"])), first["type"])
            continue

        # Unknown keys land in `model_extra`, which means a field was missed.
        body = event.event
        extras = sorted(getattr(body, "model_extra", None) or ())
        stats["ok"] += 1
        if extras:
            stats["with undeclared fields"] += 1
            print("extra fields", event_type, extras[:6])

        # Some samples leave the header out, or abbreviate it.
        if (sample.get("header") or {}).get("event_type") == event_type:
            assert isinstance(parse_obj(sample), cls), event_type

    print(dict(stats), len(EVENT_MODULES))


if __name__ == "__main__":
    main()
