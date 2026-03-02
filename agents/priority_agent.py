"""Priority Agent - 섹션 우선순위 배정 + 사용자 확인."""
import json
import re
from pathlib import Path

from utils.console import ok, info, priority_confirm_prompt
from utils.gemini_client import GeminiClient
import config

# 기본 우선순위 규칙 (섹션 제목 키워드 기반)
DEFAULT_PRIORITIES = [
    (r"abstract",             "high"),
    (r"introduction",         "high"),
    (r"method|experiment",    "high"),
    (r"result",               "high"),
    (r"discussion|conclusion","high"),
    (r"reference|bibliograph","medium"),
    (r"supplement|appendix",  "low"),
]


def _default_priority(title: str) -> str:
    lower = title.lower()
    for pattern, priority in DEFAULT_PRIORITIES:
        if re.search(pattern, lower):
            return priority
    return "medium"


def run(parsed_data: dict, style_data: dict, output_dir: Path, client: GeminiClient) -> dict:
    """
    Abstract 분석 기반으로 섹션 우선순위를 배정하고 사용자 확인을 받음.
    반환: priority_data dict
    """
    priority_json = output_dir / "paper_priority.json"
    sections = parsed_data["sections"]

    # Abstract 텍스트 추출
    abstract_text = ""
    for s in sections:
        if re.search(r"abstract", s["title"], re.I):
            abstract_text = s["content"][:2000]
            break

    # Gemini로 섹션 우선순위 배정
    section_list = "\n".join([f"- {s['title']}" for s in sections])
    prompt = f"""다음은 자연과학 논문의 Abstract와 섹션 목록입니다.

[Abstract]
{abstract_text}

[섹션 목록]
{section_list}

각 섹션의 번역 우선순위를 high / medium / low로 배정하세요.
- high: 고품질 번역이 필수 (핵심 내용)
- medium: 표준 품질로 충분
- low: 참고용 (보조 자료, 부록 등)

JSON으로만 응답 (마크다운 없이):
{{
  "priorities": {{
    "섹션제목": "high|medium|low",
    ...
  }},
  "rationale": "한 문장으로 우선순위 배정 근거"
}}"""

    try:
        raw = client.generate(prompt, config.HIGH_PRIORITY_MODEL)
        raw = raw.strip().strip("```json").strip("```").strip()
        result = json.loads(raw)
        ai_priorities = result.get("priorities", {})
        rationale = result.get("rationale", "")
    except Exception:
        ai_priorities = {}
        rationale = "기본 규칙 적용"

    # 섹션별 우선순위 결정
    section_priorities = []
    for s in sections:
        title = s["title"]
        # AI 배정 우선, 없으면 기본값
        priority = ai_priorities.get(title) or _default_priority(title)
        model = config.HIGH_PRIORITY_MODEL if priority == "high" else config.LOW_PRIORITY_MODEL
        section_priorities.append({
            "id": s["id"],
            "title": title,
            "level": s["level"],
            "priority": priority,
            "model": model,
        })

    data = {
        "paper_id": parsed_data["paper_id"],
        "rationale": rationale,
        "sections": section_priorities,
    }

    with open(priority_json, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 콘솔에 배정 결과 출력
    ok(f"섹션 우선순위 배정 완료 ({rationale})")
    print()
    for sp in section_priorities:
        color = "\033[32m" if sp["priority"] == "high" else ("\033[33m" if sp["priority"] == "medium" else "\033[90m")
        print(f"    {color}{sp['title']:<35}{sp['priority']:<8}\033[0m({sp['model']})")

    # 사용자 확인 대기
    priority_confirm_prompt(str(priority_json))

    # 사용자가 편집했을 경우 다시 로드
    with open(priority_json, encoding="utf-8") as f:
        data = json.load(f)

    ok("우선순위 확정. 번역을 시작합니다.")
    return data
