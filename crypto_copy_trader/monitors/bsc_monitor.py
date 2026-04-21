from __future__ import annotations

from monitors.eth_monitor import EthMonitor


class BscMonitor(EthMonitor):
    chain = "bsc"
    _base_url = "https://api.bscscan.com/api"
