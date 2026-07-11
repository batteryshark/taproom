from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable

from .models import Capability


TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


class Catalog:
    def __init__(self, capabilities: Iterable[Capability]):
        self.capabilities = list(capabilities)
        self.by_id = {capability.id: capability for capability in self.capabilities}
        if len(self.by_id) != len(self.capabilities):
            seen: set[str] = set()
            duplicates: set[str] = set()
            for capability in self.capabilities:
                if capability.id in seen:
                    duplicates.add(capability.id)
                seen.add(capability.id)
            raise ValueError(f"Duplicate capability IDs: {', '.join(duplicates)}")
        self.documents = [
            tokenize(
                " ".join(
                    (
                        item.name.replace("-", " "),
                        item.description,
                        item.category,
                        " ".join(item.tags),
                        item.kind,
                        item.tap,
                        item.source,
                    )
                )
            )
            for item in self.capabilities
        ]

    def get(self, capability_id: str) -> Capability | None:
        return self.by_id.get(capability_id)

    def search(
        self,
        query: str,
        *,
        kind: str | None = None,
        tap: str | None = None,
        limit: int = 5,
    ) -> list[dict]:
        terms = tokenize(query)
        if not terms or limit < 1:
            return []
        eligible = [
            index
            for index, item in enumerate(self.capabilities)
            if (kind is None or item.kind == kind) and (tap is None or item.tap == tap)
        ]
        if not eligible:
            return []
        lengths = [len(self.documents[index]) for index in eligible]
        average = sum(lengths) / len(lengths) or 1
        document_frequency = Counter(
            term
            for index in eligible
            for term in set(self.documents[index])
        )
        scores: list[tuple[float, int]] = []
        total = len(eligible)
        for index in eligible:
            document = self.documents[index]
            frequency = Counter(document)
            score = 0.0
            for term in terms:
                count = frequency[term]
                if not count:
                    continue
                inverse = math.log(1 + (total - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
                denominator = count + 1.5 * (1 - 0.75 + 0.75 * len(document) / average)
                score += inverse * count * 2.5 / denominator
            if score:
                scores.append((score, index))
        scores.sort(key=lambda value: (-value[0], self.capabilities[value[1]].id))
        return [
            {**self.capabilities[index].to_dict(), "score": round(score, 6)}
            for score, index in scores[: min(limit, 25)]
        ]
