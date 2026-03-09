from __future__ import annotations

import abc
from collections.abc import Sequence

import httpx

from glassbox_radar.contracts import CollectedSignal, CollectionContext


class Collector(abc.ABC):
    @abc.abstractmethod
    async def collect(self, context: CollectionContext, client: httpx.AsyncClient) -> Sequence[CollectedSignal]:
        raise NotImplementedError
