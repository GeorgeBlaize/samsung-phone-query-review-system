"""Resolve phone names mentioned in free text ("s23", "Galaxy S22+", "fold 5")."""
from __future__ import annotations

import re
from typing import Sequence

DROP_TOKENS = {"samsung", "galaxy"}
VARIANT_SUFFIXES = {"ultra", "plus", "fe"}


def tokenize(text: str) -> list[str]:
    text = text.lower().replace("+", " plus ")
    text = re.sub(r"\b5g\b", " ", text)
    tokens = re.findall(r"[a-z]+|\d+", text)
    return ["plus" if t == "pluss" else t for t in tokens]


def aliases_for(name: str) -> list[tuple[str, ...]]:
    base = [t for t in tokenize(name) if t not in DROP_TOKENS]
    variants = {tuple(base)}
    if base and base[0] == "z":  # "Z Fold5" is often written "Fold 5"
        variants.add(tuple(base[1:]))
    return [v for v in variants if v]


class PhoneMatcher:
    """Longest-alias-first matching so "S23 Ultra" is not mistaken for "S23"."""

    def __init__(self, phones: Sequence):
        self.phones = list(phones)
        self._aliases: list[tuple[tuple[str, ...], object]] = []
        for phone in self.phones:
            for alias in aliases_for(phone.name):
                self._aliases.append((alias, phone))
        self._aliases.sort(key=lambda a: len(a[0]), reverse=True)

    def find(self, text: str) -> list:
        tokens = tokenize(text)
        used = [False] * len(tokens)
        found: list[tuple[int, object]] = []
        for alias, phone in self._aliases:
            n = len(alias)
            for i in range(len(tokens) - n + 1):
                if tuple(tokens[i:i + n]) == alias and not any(used[i:i + n]):
                    # "s23 ultra" must not resolve to "S23" when the Ultra is not in the DB
                    # (if it were, the longer alias would already have consumed these tokens)
                    nxt = tokens[i + n] if i + n < len(tokens) else None
                    if nxt in VARIANT_SUFFIXES:
                        continue
                    for j in range(i, i + n):
                        used[j] = True
                    if all(p is not phone for _, p in found):
                        found.append((i, phone))
        return [p for _, p in sorted(found, key=lambda x: x[0])]
