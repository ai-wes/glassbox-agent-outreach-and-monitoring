from __future__ import annotations

from dataclasses import dataclass

from app.tools.base import Tool


class ToolNotFoundError(KeyError):
    pass


@dataclass
class ToolRegistry:
    _tools: dict[str, Tool]

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolNotFoundError(name)
        return self._tools[name]

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return sorted(self._tools.keys())

    def specs(self) -> list[dict]:
        return [self._tools[n].spec() for n in self.names()]
