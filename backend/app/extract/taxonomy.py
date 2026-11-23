"""SkillMatcher: find canonical skill names in free text.

Matching is case-insensitive except for terms marked case_sensitive in the taxonomy (Go, R,
C, React, Spark...: their lowercase forms are ordinary words). A match must stand alone:
the characters on either side cannot be letters, digits, '+' or '#', so "Java" is not found
inside "JavaScript", while "C++", "C#", ".NET" and "Node.js." all match. Where two terms
overlap, the longer wins ("Spring Boot" over "Spring").
"""

import re
from pathlib import Path

import yaml

_EDGE = r"a-zA-Z0-9+#"
# Capitalised English words that are also skill names: at the start of a sentence or line
# they are the word ("Go above and beyond"), not the language.
_NOT_AT_SENTENCE_START = {"Go"}
_SENTENCE_START = re.compile(r"(?:^|[.!?:]\s+|\n\s*)$")


def _pattern(terms: list[str], flags: int) -> re.Pattern[str] | None:
    if not terms:
        return None
    ordered = sorted(set(terms), key=len, reverse=True)
    body = "|".join(re.escape(t) for t in ordered)
    # Case-sensitive single words also refuse a following hyphen: "go-to-market", "C-suite".
    tail = r"(?![" + _EDGE + r"\-])" if not flags & re.IGNORECASE else r"(?![" + _EDGE + "])"
    return re.compile(r"(?<![" + _EDGE + r"])(" + body + ")" + tail, flags)


class SkillMatcher:
    def __init__(self, entries: list[dict]) -> None:
        self._insensitive: dict[str, str] = {}
        self._sensitive: dict[str, str] = {}
        for entry in entries:
            name = entry["name"]
            exact = set(entry.get("case_sensitive") or [])
            for term in [name, *entry.get("aliases", [])]:
                if term in exact:
                    self._sensitive[term] = name
                else:
                    self._insensitive[term.lower()] = name
        self._i_re = _pattern(list(self._insensitive), re.IGNORECASE)
        self._s_re = _pattern(list(self._sensitive), 0)

    @classmethod
    def from_yaml(cls, path: Path) -> "SkillMatcher":
        return cls(yaml.safe_load(path.read_text(encoding="utf-8")) or [])

    def match(self, text: str) -> set[str]:
        found: set[str] = set()
        if self._i_re is not None:
            found |= {self._insensitive[m.group(1).lower()] for m in self._i_re.finditer(text)}
        if self._s_re is not None:
            for m in self._s_re.finditer(text):
                term = m.group(1)
                if term in _NOT_AT_SENTENCE_START and _SENTENCE_START.search(text[: m.start()]):
                    continue
                found.add(self._sensitive[term])
        return found

    def canonical(self, name: str) -> str | None:
        stripped = name.strip()
        return self._sensitive.get(stripped) or self._insensitive.get(stripped.lower())

    @property
    def names(self) -> set[str]:
        return set(self._insensitive.values()) | set(self._sensitive.values())
