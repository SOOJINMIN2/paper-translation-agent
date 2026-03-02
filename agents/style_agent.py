"""Style Analysis Agent - 원문 문체 특성 분석."""
import json
import re
from pathlib import Path

from utils.console import ok
from utils.gemini_client import GeminiClient
import config


def run(parsed_data: dict, output_dir: Path, client: GeminiClient) -> dict:
    """
    원문의 수식 집약도와 전문 용어 밀도를 분석.
    반환: style_data dict
    """
    style_json = output_dir / "paper_style.json"

    sections = parsed_data["sections"]
    total_chars = sum(len(s["content"]) for s in sections)
    total_eq_chars = sum(
        sum(len(eq) for eq in s["equations"]) for s in sections
    )

    # 수식 집약도 계산
    equation_ratio = round(total_eq_chars / max(total_chars, 1), 3)

    # Abstract + Introduction 텍스트로 Gemini 분석
    sample_text = ""
    for s in sections:
        if re.search(r"abstract|introduction", s["title"], re.I):
            sample_text += s["content"][:2000]
        if len(sample_text) > 3000:
            break

    if not sample_text:
        sample_text = sections[0]["content"][:2000] if sections else ""

    prompt = f"""다음은 자연과학 논문의 Abstract 및 Introduction 텍스트입니다.

[텍스트]
{sample_text}

다음 항목을 분석하여 JSON으로만 응답하세요 (마크다운 코드블록 없이 순수 JSON):
{{
  "style_type": "equation-heavy | narrative-heavy | mixed",
  "term_density": "high | medium | low",
  "subfield": "논문의 세부 분야 (예: quantum mechanics, organic chemistry, ...)",
  "translation_guidance": "번역 시 주의사항을 한국어로 2-3문장으로 설명"
}}"""

    try:
        raw = client.generate(prompt, config.HIGH_PRIORITY_MODEL)
        raw = raw.strip().strip("```json").strip("```").strip()
        style_info = json.loads(raw)
    except Exception:
        style_info = {
            "style_type": "equation-heavy" if equation_ratio > 0.2 else "mixed",
            "term_density": "high",
            "subfield": "natural science",
            "translation_guidance": "수식 주변 설명 문장은 간결하게 번역하되 수식과의 연결성을 유지하세요.",
        }

    data = {
        "paper_id": parsed_data["paper_id"],
        "equation_ratio": equation_ratio,
        **style_info,
    }

    with open(style_json, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    ok(f"문체 분류: {data['style_type']} (수식 비율 {equation_ratio:.0%})")
    ok(f"전문 용어 밀도: {data['term_density']} | 세부 분야: {data.get('subfield', 'unknown')}")

    return data
