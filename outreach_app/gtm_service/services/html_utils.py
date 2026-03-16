from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

_WHITESPACE_RE = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?])")
_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
    "dd",
    "div",
    "dl",
    "dt",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "td",
    "th",
    "tr",
    "ul",
}
_IGNORED_TAGS = {"noscript", "script", "style"}


def _normalize_space(value: str) -> str:
    normalized = _WHITESPACE_RE.sub(" ", html.unescape(value or "")).strip()
    return _SPACE_BEFORE_PUNCT_RE.sub(r"\1", normalized)


@dataclass(slots=True)
class HTMLDocument:
    title: str | None = None
    text: str = ""
    links: list[str] = field(default_factory=list)
    meta: list[dict[str, str]] = field(default_factory=list)


class _HTMLDocumentParser(HTMLParser):
    def __init__(self, *, base_url: str | None = None) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self._ignored_depth = 0
        self._in_title = False
        self._text_parts: list[str] = []
        self._title_parts: list[str] = []
        self.links: list[str] = []
        self.meta: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered_tag = tag.lower()
        normalized_attrs = {key.lower(): value for key, value in attrs if key and value is not None}
        if lowered_tag in _IGNORED_TAGS:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if lowered_tag in _BLOCK_TAGS:
            self._text_parts.append(" ")
        if lowered_tag == "title":
            self._in_title = True
        elif lowered_tag == "meta":
            self.meta.append(normalized_attrs)
        elif lowered_tag == "a":
            href = normalized_attrs.get("href")
            if href:
                resolved = urljoin(self.base_url, href) if self.base_url else href
                self.links.append(resolved)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        lowered_tag = tag.lower()
        if lowered_tag in _IGNORED_TAGS:
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return
        if self._ignored_depth:
            return
        if lowered_tag in _BLOCK_TAGS:
            self._text_parts.append(" ")
        if lowered_tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._in_title:
            self._title_parts.append(data)
        self._text_parts.append(data)

    def build(self) -> HTMLDocument:
        deduped_links: list[str] = []
        seen_links: set[str] = set()
        for link in self.links:
            normalized_link = link.strip()
            if not normalized_link or normalized_link in seen_links:
                continue
            seen_links.add(normalized_link)
            deduped_links.append(normalized_link)
        title = _normalize_space("".join(self._title_parts)) or None
        text = _normalize_space(" ".join(self._text_parts))
        return HTMLDocument(
            title=title,
            text=text,
            links=deduped_links,
            meta=self.meta,
        )


def parse_html_document(html_text: str, *, base_url: str | None = None) -> HTMLDocument:
    parser = _HTMLDocumentParser(base_url=base_url)
    parser.feed(html_text or "")
    parser.close()
    return parser.build()


def meta_content(document: HTMLDocument, *, selectors: list[dict[str, Any]]) -> str | None:
    for selector in selectors:
        for attrs in document.meta:
            if _attrs_match(attrs, selector):
                content = attrs.get("content")
                if content:
                    return content.strip()
    return None


def _attrs_match(attrs: dict[str, str], selector: dict[str, Any]) -> bool:
    for key, expected in selector.items():
        actual = attrs.get(key.lower())
        if actual is None:
            return False
        if hasattr(expected, "search"):
            if not expected.search(actual):
                return False
            continue
        if actual != str(expected):
            return False
    return True
