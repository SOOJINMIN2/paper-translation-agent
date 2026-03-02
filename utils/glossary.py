"""용어집(glossary.json) 및 번역 불가 목록(no_translate.txt) 관리."""
import json
from pathlib import Path

import config
from utils.console import ok, warn, conflict_prompt


class GlossaryManager:
    def __init__(self):
        self.path = config.GLOSSARY_PATH
        self.path.mkdir(parents=True, exist_ok=True)
        self.glossary_file = self.path / "glossary.json"
        self.no_translate_file = self.path / "no_translate.txt"
        self._data: dict = {}
        self._no_translate: list[str] = []
        self._load()

    def _load(self):
        if self.glossary_file.exists():
            with open(self.glossary_file, encoding="utf-8") as f:
                self._data = json.load(f)
        else:
            self._data = {}
            self._save()
            ok(f"새 용어집 생성: {self.glossary_file}")

        if self.no_translate_file.exists():
            with open(self.no_translate_file, encoding="utf-8") as f:
                self._no_translate = [l.strip() for l in f if l.strip()]
        else:
            self._no_translate = []
            self.no_translate_file.write_text("", encoding="utf-8")

    def _save(self):
        with open(self.glossary_file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def get_terms(self, fields: list[str] | None = None) -> dict[str, str]:
        """분야별 용어 목록 반환 (fields=None이면 전체)."""
        if not fields:
            merged = {}
            for v in self._data.values():
                merged.update(v)
            return merged
        merged = {}
        for field in fields:
            merged.update(self._data.get(field, {}))
        return merged

    def get_no_translate(self) -> list[str]:
        return self._no_translate

    def add_terms(self, new_terms: dict[str, str], field: str = "general"):
        """번역 후 신규 용어를 용어집에 추가."""
        if field not in self._data:
            self._data[field] = {}
        added = 0
        for en, ko in new_terms.items():
            if en not in self._data[field]:
                self._data[field][en] = ko
                added += 1
        if added:
            self._save()
            ok(f"용어집에 신규 용어 {added}개 추가 ({field})")

    def resolve_conflicts(self, conflicts: list[dict]) -> dict[str, str]:
        """
        충돌 용어를 사용자에게 보여주고 해결.
        conflicts: [{"term": "state", "glossary": "상태", "current": "준위"}, ...]
        반환: {term: chosen_translation}
        """
        if not conflicts:
            return {}
        print("\n  ─── 용어 충돌 검토 ───")
        resolved = {}
        for c in conflicts:
            chosen = conflict_prompt(c["term"], c["glossary"], c["current"])
            resolved[c["term"]] = chosen
        return resolved

    def glossary_prompt_block(self, fields: list[str] | None = None) -> str:
        """번역 프롬프트에 삽입할 용어집 텍스트 블록 생성."""
        terms = self.get_terms(fields)
        no_tr = self.get_no_translate()
        lines = []
        if terms:
            lines.append("[확정 용어 번역]")
            for en, ko in list(terms.items())[:200]:  # 최대 200개
                lines.append(f"  {en} → {ko}")
        if no_tr:
            lines.append("[번역하지 않는 용어 (원어 유지)]")
            lines.append("  " + ", ".join(no_tr[:100]))
        return "\n".join(lines)
