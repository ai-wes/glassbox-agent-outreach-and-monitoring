from __future__ import annotations


class HubSpotClient:
    def __init__(self, *args, **kwargs):
        raise RuntimeError(
            "HubSpot export has been removed from Glassbox Radar. "
            "Use the Google Sheets export path instead."
        )
