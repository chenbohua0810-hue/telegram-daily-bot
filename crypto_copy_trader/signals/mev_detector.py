from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from models import OnChainEvent

DEFAULT_BLACKLIST_PATH = "data/mev_blacklist.json"
HIGH_FREQUENCY_SWAP_THRESHOLD = 100


@dataclass
class MevDetector:
    blacklist: set[str]
    recent_events: tuple[OnChainEvent, ...] = ()
    now: datetime | None = None

    def check(self, event: OnChainEvent) -> OnChainEvent:
        normalized_wallet = event.wallet.lower()
        if normalized_wallet in self.blacklist:
            flagged = replace(event, is_mev_suspect=True)
            self.recent_events = (*self.recent_events, flagged)[-1000:]
            return flagged

        matching_same_block = [
            recent
            for recent in self.recent_events
            if recent.wallet.lower() == normalized_wallet
            and recent.token_address.lower() == event.token_address.lower()
            and _block_number(recent) == _block_number(event)
            and recent.tx_type != event.tx_type
        ]
        if matching_same_block:
            flagged = replace(event, is_mev_suspect=True)
            self.recent_events = (*self.recent_events, flagged)[-1000:]
            return flagged

        cutoff = (self.now or datetime.now(timezone.utc)) - timedelta(hours=24)
        recent_wallet_swaps = [
            recent
            for recent in self.recent_events
            if recent.wallet.lower() == normalized_wallet and recent.block_time >= cutoff
        ]
        if len(recent_wallet_swaps) >= HIGH_FREQUENCY_SWAP_THRESHOLD:
            flagged = replace(event, is_mev_suspect=True)
            self.recent_events = (*self.recent_events, flagged)[-1000:]
            return flagged

        self.recent_events = (*self.recent_events, event)[-1000:]
        return event

    def with_event(self, event: OnChainEvent) -> "MevDetector":
        return replace(self, recent_events=(*self.recent_events, event)[-1000:])


def check_mev_event(
    event: OnChainEvent,
    *,
    blacklist_path: str = DEFAULT_BLACKLIST_PATH,
    recent_events: Iterable[OnChainEvent] = (),
) -> OnChainEvent:
    detector = MevDetector(blacklist=load_mev_blacklist(blacklist_path), recent_events=tuple(recent_events))
    return detector.check(event)


def load_mev_blacklist(path: str) -> set[str]:
    file_path = Path(path)
    if not file_path.exists():
        return set()
    with file_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        entries = payload
    else:
        entries = [
            *(payload.get("entries") or []),
            *(payload.get("eth") or []),
            *(payload.get("bsc") or []),
            *(payload.get("sol") or []),
        ]
    return {
        str(entry.get("address", entry)).lower()
        for entry in entries
        if entry
    }


def _block_number(event: OnChainEvent) -> int | None:
    raw = event.raw or {}
    value = raw.get("block_number") or raw.get("blockNumber")
    return None if value is None else int(value)
