from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from datetime import datetime

from models.events import OnChainEvent


logger = logging.getLogger(__name__)


class EventLog:
    def __init__(self, path: str) -> None:
        self._path = path

    def append(self, event: OnChainEvent) -> None:
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        payload = json.dumps(event.to_dict(), separators=(",", ":"))

        with open(self._path, "a", encoding="utf-8") as handle:
            handle.write(f"{payload}\n")
            handle.flush()
            os.fsync(handle.fileno())

    def iter_events(self, since: datetime | None = None) -> Iterator[OnChainEvent]:
        if not os.path.exists(self._path):
            return

        with open(self._path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    payload = json.loads(line)
                    event = OnChainEvent.from_dict(payload)
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    logger.warning("Skipping malformed event log line")
                    continue

                if since is not None and event.block_time < since:
                    continue

                yield event
