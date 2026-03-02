"""Translation Agent - 섹션별 Gemini 번역."""
import json
import re
import time
from pathlib import Path

import config
from utils.console import ok, warn, info, section_done
from utils.gemini_client import GeminiClient
from utils.glossary import GlossaryManager


# ── 수식 플레이스홀더 처리 ────────────────────────────────────────

def _protect_equations(text: str) -> tuple[str, dict]:
    """LaTeX 수식을 플레이스홀더로 치환하여 번역 중 보호."""
    placeholders = {}
    counter = [0]

    def replace(m):
        key = f"__EQ{counter[0]:04d}__"
        placeholders[key] = m.group(0)
        counter[0] += 1
        return key

    # 디스플레이 수식 우선 처리
    text = re.sub(r"\$\$[\s\S]+?\$\$", replace, text)
    text = re.sub(r"\$[^$\n]+?\$", replace, text)
    return text, placeholders


def _restore_equations(text: str, placeholders: dict) -> str:
    """플레이스홀더를 원래 수식으로 복원."""
    for key, eq in placeholders.items():
        text = text.replace(key, eq)
    return text


# ── 청킹 ─────────────────────────────────────────────────────────

def _chunk_section(content: str) -> list[str]:
    """섹션 내용을 MAX_SECTION_CHARS 이하로 분할."""
    if len(content) <= config.MAX_SECTION_CHARS:
        return [content]

    # 서브섹션(###) 단위로 분할 시도
    chunks = re.split(r"(?=^#{3,}\s)", content, flags=re.MULTILINE)
    result = []
    current = ""
    for chunk in chunks:
        if len(current) + len(chunk) <= config.MAX_SECTION_CHARS:
            current += chunk
        else:
            if current:
                result.append(current)
            current = chunk
    if current:
        result.append(current)
    return result or [content]


# ── 번역 프롬프트 생성 ────────────────────────────────────────────

def _build_prompt(
    section_title: str,
    content: str,
    style_guidance: str,
    glossary_block: str,
    chunk_terms: dict,
    is_references: bool = False,
) -> str:
    chunk_terms_str = ""
    if chunk_terms:
        chunk_terms_str = "\n[이번 논문 내 이미 확정된 신규 용어]\n" + "\n".join(
            f"  {en} → {ko}" for en, ko in chunk_terms.items()
        )

    if is_references:
        return f"""자연과학(물리·화학) 논문 전문 번역가입니다. 참고문헌 섹션을 번역하세요.

규칙:
- 논문 제목(title)만 한국어로 번역
- 저자명, 학술지명, 권호, 페이지는 원어 유지
- [N] 번호 형식 그대로 유지

{glossary_block}

[참고문헌 원문]
{content}

[번역된 참고문헌]"""

    return f"""자연과학(물리·화학) 논문 전문 번역가입니다. 다음 섹션을 한국어로 번역하세요.

[문체 지침]
{style_guidance}

{glossary_block}
{chunk_terms_str}

[필수 규칙]
1. 수식 플레이스홀더(__EQ0000__ 형식)는 절대 수정하지 않고 그대로 유지
2. 전문 용어 첫 등장 시 '한국어(영어)' 형식으로 병기 (예: 파동 함수(wave function))
3. no_translate 목록 용어는 원어 그대로 유지
4. 이미 확정된 용어는 반드시 동일하게 번역
5. Figure N → 그림 N, Table N → 표 N으로 변환
6. 표 내용도 전체 번역하되 헤더에 원어 병기 (예: 활성화 에너지(Activation Energy))
7. 마크다운 구조(#, **, |, -) 그대로 유지
8. 유창성 우선 (자연스러운 한국어로 의역 허용)

[섹션: {section_title}]
{content}

[한국어 번역]"""


# ── 신규 용어 추출 ────────────────────────────────────────────────

def _extract_new_terms(translated: str) -> dict[str, str]:
    """번역문에서 '한국어(English)' 패턴의 신규 용어 쌍 추출."""
    pattern = re.compile(r"([가-힣\s]+)\(([A-Za-z][a-zA-Z\s\-]+)\)")
    terms = {}
    for m in pattern.finditer(translated):
        ko = m.group(1).strip()
        en = m.group(2).strip()
        if len(en) > 2 and len(ko) > 1:
            terms[en] = ko
    return terms


# ── 메인 에이전트 ─────────────────────────────────────────────────

def run(
    parsed_data: dict,
    style_data: dict,
    priority_data: dict,
    output_dir: Path,
    client: GeminiClient,
    glossary: GlossaryManager,
) -> dict:
    """
    섹션별로 번역을 수행하고 paper_translated.json 생성.
    반환: translated_data dict
    """
    translated_json = output_dir / "paper_translated.json"
    sections = parsed_data["sections"]
    priority_map = {sp["id"]: sp for sp in priority_data["sections"]}

    style_guidance = style_data.get("translation_guidance", "자연스러운 한국어로 번역하세요.")
    subfield = style_data.get("subfield", "")
    fields = [subfield] if subfield else []
    glossary_block = glossary.glossary_prompt_block(fields)

    translated_sections = []
    all_new_terms: dict[str, str] = {}
    chunk_terms: dict[str, str] = {}  # 이번 논문 내 누적 신규 용어

    total = len(sections)
    pipeline_start = time.time()

    for idx, section in enumerate(sections, 1):
        sec_start = time.time()
        sec_id = section["id"]
        title = section["title"]
        content = section["content"]
        sp = priority_map.get(sec_id, {"priority": "medium", "model": config.LOW_PRIORITY_MODEL})
        model = sp["model"]
        is_ref = bool(re.search(r"reference|bibliograph", title, re.I))

        info(f"  [{idx}/{total}] {title} ({sp['priority']}) 번역 중...")

        # 수식 보호
        protected, eq_map = _protect_equations(content)

        # 청킹
        chunks = _chunk_section(protected)
        translated_chunks = []

        for ci, chunk in enumerate(chunks):
            prompt = _build_prompt(
                section_title=title,
                content=chunk,
                style_guidance=style_guidance,
                glossary_block=glossary_block,
                chunk_terms=chunk_terms,
                is_references=is_ref,
            )
            result = client.generate(prompt, model)
            translated_chunks.append(result)

            # 신규 용어 추출 및 누적
            new_terms = _extract_new_terms(result)
            chunk_terms.update(new_terms)
            all_new_terms.update(new_terms)

        translated_content = "\n".join(translated_chunks)
        # 수식 복원
        translated_content = _restore_equations(translated_content, eq_map)

        # 경과 시간 및 ETA 계산
        elapsed_total = time.time() - pipeline_start
        avg_per_section = elapsed_total / idx
        eta = avg_per_section * (total - idx)
        section_done(idx, total, title, sec_start, eta)

        translated_sections.append({
            "id": sec_id,
            "title": title,
            "level": section["level"],
            "original_content": section["content"],
            "translated_content": translated_content,
            "priority": sp["priority"],
            "equations": section["equations"],
            "figures": section.get("figures", []),
            "tables": section.get("tables", []),
        })

    if all_new_terms:
        ok(f"신규 용어 {len(all_new_terms)}개 확정: " + ", ".join(
            f"{ko}({en})" for en, ko in list(all_new_terms.items())[:5]
        ) + ("..." if len(all_new_terms) > 5 else ""))

    data = {
        "paper_id": parsed_data["paper_id"],
        "sections": translated_sections,
        "new_terms": all_new_terms,
        "references": parsed_data.get("references", []),
    }

    with open(translated_json, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return data
