"""Reviewer Agent - 번역 품질 검증 + 자동 재번역 + 용어 충돌 해결."""
import json
import re
from pathlib import Path

import config
from utils.console import ok, warn, info
from utils.gemini_client import GeminiClient
from utils.glossary import GlossaryManager


def _detect_issues(parsed_data: dict, translated_data: dict) -> list[dict]:
    """번역 이슈 탐지 (누락 섹션, 반복 단락, 용어 불일치)."""
    issues = []
    orig_ids = {s["id"] for s in parsed_data["sections"]}
    trans_ids = {s["id"] for s in translated_data["sections"]}

    # 1. 누락 섹션
    missing = orig_ids - trans_ids
    for sid in missing:
        issues.append({"type": "critical", "section_id": sid, "msg": f"섹션 누락: {sid}"})

    # 2. 섹션 수 불일치
    if len(orig_ids) != len(trans_ids):
        issues.append({
            "type": "warning",
            "section_id": None,
            "msg": f"섹션 수 불일치: 원문 {len(orig_ids)}개 vs 번역 {len(trans_ids)}개",
        })

    # 3. 반복 단락 탐지 (번역문에서 동일 문단이 두 번 이상)
    all_translated = " ".join(s["translated_content"] for s in translated_data["sections"])
    paragraphs = [p.strip() for p in all_translated.split("\n\n") if len(p.strip()) > 100]
    seen = {}
    for p in paragraphs:
        key = p[:80]
        seen[key] = seen.get(key, 0) + 1
        if seen[key] == 2:
            issues.append({"type": "warning", "section_id": None, "msg": f"반복 단락 감지: {key[:50]}..."})

    return issues


def _detect_conflicts(translated_data: dict, glossary: GlossaryManager) -> list[dict]:
    """glossary 기존 용어와 이번 번역 용어 충돌 탐지."""
    all_terms = glossary.get_terms()
    new_terms = translated_data.get("new_terms", {})
    conflicts = []
    for en, new_ko in new_terms.items():
        if en in all_terms and all_terms[en] != new_ko:
            conflicts.append({
                "term": en,
                "glossary": all_terms[en],
                "current": new_ko,
            })
    return conflicts


def _retranslate_section(
    section_id: str,
    parsed_data: dict,
    translated_data: dict,
    client: GeminiClient,
    attempt: int,
) -> str | None:
    """Critical 이슈 발생 시 해당 섹션 재번역."""
    orig = next((s for s in parsed_data["sections"] if s["id"] == section_id), None)
    if not orig:
        return None

    prompt = f"""다음 자연과학 논문 섹션을 한국어로 번역하세요 (재번역 시도 {attempt+1}회).

규칙:
- 수식 $...$ $$...$$ LaTeX 블록은 그대로 유지
- 전문 용어는 '한국어(영어)' 형식으로 병기
- 마크다운 구조 유지

[섹션: {orig['title']}]
{orig['content']}

[한국어 번역]"""

    return client.generate(prompt, config.HIGH_PRIORITY_MODEL)


def run(
    parsed_data: dict,
    translated_data: dict,
    output_dir: Path,
    client: GeminiClient,
    glossary: GlossaryManager,
) -> dict:
    """
    번역 품질 검증, 자동 재번역, 용어 충돌 해결 수행.
    반환: reviewed_data dict
    """
    reviewed_json  = output_dir / "paper_reviewed.json"
    report_json    = output_dir / "paper_review_report.json"

    issues    = _detect_issues(parsed_data, translated_data)
    conflicts = _detect_conflicts(translated_data, glossary)

    critical = [i for i in issues if i["type"] == "critical"]
    warnings = [i for i in issues if i["type"] == "warning"]

    # Critical 이슈: 자동 재번역 시도
    sections = {s["id"]: s for s in translated_data["sections"]}
    retranslation_log = []

    for issue in critical:
        sid = issue["section_id"]
        if not sid:
            continue
        warn(f"Critical 이슈: {issue['msg']} → 자동 재번역 시도")
        success = False
        for attempt in range(config.MAX_RETRANSLATION_ATTEMPTS):
            new_text = _retranslate_section(sid, parsed_data, translated_data, client, attempt)
            if new_text:
                # 섹션 찾아서 업데이트
                for s in translated_data["sections"]:
                    if s["id"] == sid:
                        s["translated_content"] = new_text
                        break
                sections[sid] = next(s for s in translated_data["sections"] if s["id"] == sid)
                retranslation_log.append({"section_id": sid, "attempt": attempt+1, "result": "success"})
                ok(f"재번역 성공: {sid}")
                success = True
                break

        if not success:
            warn(f"재번역 실패: {sid} → 원문 병렬 표시 처리")
            # 해당 섹션에 원문을 병렬로 추가
            orig = next((s for s in parsed_data["sections"] if s["id"] == sid), None)
            if orig and sid in sections:
                sections[sid]["parallel_original"] = orig["content"]
            retranslation_log.append({"section_id": sid, "attempt": config.MAX_RETRANSLATION_ATTEMPTS, "result": "failed"})

    # 용어 충돌 해결 (포스트 프로세싱)
    resolved_conflicts = {}
    if conflicts:
        resolved_conflicts = glossary.resolve_conflicts(conflicts)
        # 번역문에서 충돌 용어 교체
        for sec in translated_data["sections"]:
            for en, chosen_ko in resolved_conflicts.items():
                wrong_ko = next((c["current"] for c in conflicts if c["term"] == en), None)
                if wrong_ko and wrong_ko != chosen_ko:
                    sec["translated_content"] = sec["translated_content"].replace(wrong_ko, chosen_ko)

    # Warning 출력
    for w in warnings:
        warn(w["msg"])

    # 이슈 리포트 생성
    if issues or conflicts:
        report = {
            "paper_id": parsed_data["paper_id"],
            "critical_issues": critical,
            "warnings": warnings,
            "conflicts": conflicts,
            "resolved_conflicts": resolved_conflicts,
            "retranslation_log": retranslation_log,
        }
        with open(report_json, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    # 용어집 업데이트
    new_terms = translated_data.get("new_terms", {})
    if new_terms:
        subfield = "general"
        glossary.add_terms(new_terms, subfield)

    if not issues and not conflicts:
        ok("용어 일관성 검증 통과")
        ok("누락/반복 단락 없음")

    reviewed_data = {
        **translated_data,
        "review_passed": len(critical) == 0,
        "resolved_conflicts": resolved_conflicts,
    }

    with open(reviewed_json, "w", encoding="utf-8") as f:
        json.dump(reviewed_data, f, ensure_ascii=False, indent=2)

    return reviewed_data
