"""Corpus passage repository and loader."""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class Passage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    category: str
    language: Optional[str] = None
    title: str
    text: str
    difficulty: str = "medium"
    source: str
    license: str
    author: str
    sha256: str = Field(..., min_length=64, max_length=64)


class CorpusRepository:
    """Manages passage lookup and selection across categories."""

    def __init__(self, passages: List[Passage]) -> None:
        self._passages: List[Passage] = passages
        self._by_id: Dict[str, Passage] = {p.id: p for p in passages}
        self._by_cat_lang: Dict[tuple[str, Optional[str]], List[Passage]] = {}
        for p in passages:
            key = (p.category, p.language)
            self._by_cat_lang.setdefault(key, []).append(p)

    @classmethod
    def load_from_dir(cls, corpus_dir: Path | str) -> CorpusRepository:
        path = Path(corpus_dir)
        index_file = path / "index.json"
        if index_file.exists():
            with open(index_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                passages = [Passage(**item) for item in data]
                return cls(passages)

        passages = []
        for json_file in path.glob("*.json"):
            if json_file.name == "index.json":
                continue
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    passages.extend([Passage(**item) for item in data])
        return cls(passages)

    def get_by_id(self, passage_id: str) -> Optional[Passage]:
        return self._by_id.get(passage_id)

    def get_random_passage(
        self,
        category: str,
        language: Optional[str] = None,
    ) -> Optional[Passage]:
        """Retrieve a random passage for category and optional language."""
        key = (category, language)
        candidates = self._by_cat_lang.get(key)
        if not candidates:
            # Fallback to any in category if language wasn't matched
            candidates = [p for p in self._passages if p.category == category]
        if not candidates:
            return None
        return random.choice(candidates)

    def list_categories(self) -> Dict[str, List[str]]:
        """Return a mapping of category -> available languages."""
        result: Dict[str, List[str]] = {}
        for p in self._passages:
            if p.category not in result:
                result[p.category] = []
            if p.language and p.language not in result[p.category]:
                result[p.category].append(p.language)
        return result

    def verify_passage_text(self, passage_id: str, text: str) -> bool:
        passage = self.get_by_id(passage_id)
        if not passage:
            return False
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        computed = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return computed == passage.sha256
