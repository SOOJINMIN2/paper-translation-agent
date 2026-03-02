"""Orchestrator Agent - 전체 파이프라인 제어."""
import json
import time
from pathlib import Path

import config
from agents import parsing_agent, style_agent, priority_agent, translation_agent, reviewer_agent, reconstruction_agent
from utils.console import step, ok, warn, error, elapsed, init_pipeline, resume_prompt
from utils.gemini_client import GeminiClient
from utils.glossary import GlossaryManager

TOTAL_STEPS = 6


def _check_existing(output_dir: Path) -> str | None:
    """완료된 마지막 단계 반환. 없으면 None."""
    stages = [
        ("paper_reviewed.json",    "Reviewer"),
        ("paper_translated.json",  "Translation"),
        ("paper_priority.json",    "Priority"),
        ("paper_style.json",       "Style Analysis"),
        ("paper_parsed.json",      "Parsing"),
    ]
    for filename, name in stages:
        if (output_dir / filename).exists():
            return name
    return None


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _clear_intermediates(output_dir: Path):
    for name in [
        "paper_parsed.json", "paper_style.json", "paper_priority.json",
        "paper_translated.json", "paper_reviewed.json", "paper_review_report.json",
    ]:
        p = output_dir / name
        if p.exists():
            p.unlink()


def run(pdf_paths: list[Path], reconstruct_only: bool = False):
    """
    메인 파이프라인 실행.
    pdf_paths: [주 논문 PDF, (선택) Supplementary PDF]
    """
    init_pipeline()
    client   = GeminiClient()
    glossary = GlossaryManager()

    for pdf_path in pdf_paths:
        if not pdf_path.exists():
            error(f"파일을 찾을 수 없습니다: {pdf_path}")
            continue

        output_dir = pdf_path.parent
        print(f"\n\033[1m[논문번역 에이전트]\033[0m {pdf_path.name}")

        # ── Reconstruction-only 모드 ───────────────────────────────
        if reconstruct_only:
            reviewed_json = output_dir / "paper_reviewed.json"
            if not reviewed_json.exists():
                error("paper_reviewed.json이 없습니다. 먼저 전체 파이프라인을 실행하세요.")
                continue
            step(6, TOTAL_STEPS, "Reconstruction Agent (단독 재실행)")
            reviewed_data = _load_json(reviewed_json)
            md_path, html_path = reconstruction_agent.run(reviewed_data, output_dir, pdf_path)
            print(f"\n  출력: {md_path.name}, {html_path.name}")
            continue

        # ── 재개 여부 판단 ─────────────────────────────────────────
        last_stage = _check_existing(output_dir)
        resume = False
        if last_stage:
            resume = resume_prompt(last_stage)
            if not resume:
                _clear_intermediates(output_dir)

        # ── Step 1: Parsing ───────────────────────────────────────
        parsed_json = output_dir / "paper_parsed.json"
        if resume and parsed_json.exists():
            step(1, TOTAL_STEPS, "Parsing Agent (캐시 사용)")
            parsed_data = _load_json(parsed_json)
            ok(f"섹션 {len(parsed_data['sections'])}개 로드")
        else:
            step(1, TOTAL_STEPS, "Parsing Agent")
            parsed_data = parsing_agent.run(pdf_path, output_dir, client)

        # ── Step 2: Style Analysis ────────────────────────────────
        style_json = output_dir / "paper_style.json"
        if resume and style_json.exists():
            step(2, TOTAL_STEPS, "Style Analysis Agent (캐시 사용)")
            style_data = _load_json(style_json)
            ok(f"문체: {style_data.get('style_type')}")
        else:
            step(2, TOTAL_STEPS, "Style Analysis Agent")
            style_data = style_agent.run(parsed_data, output_dir, client)

        # ── Step 3: Priority ──────────────────────────────────────
        priority_json = output_dir / "paper_priority.json"
        if resume and priority_json.exists():
            step(3, TOTAL_STEPS, "Priority Agent (캐시 사용 - 편집하려면 파일을 수정 후 계속)")
            priority_data = _load_json(priority_json)
            from utils.console import priority_confirm_prompt
            priority_confirm_prompt(str(priority_json))
            priority_data = _load_json(priority_json)
        else:
            step(3, TOTAL_STEPS, "Priority Agent")
            priority_data = priority_agent.run(parsed_data, style_data, output_dir, client)

        # ── Step 4: Translation ───────────────────────────────────
        translated_json = output_dir / "paper_translated.json"
        if resume and translated_json.exists():
            step(4, TOTAL_STEPS, "Translation Agent (캐시 사용)")
            translated_data = _load_json(translated_json)
            ok(f"섹션 {len(translated_data['sections'])}개 로드")
        else:
            step(4, TOTAL_STEPS, "Translation Agent")
            translated_data = translation_agent.run(
                parsed_data, style_data, priority_data, output_dir, client, glossary
            )

        # ── Step 5: Reviewer ──────────────────────────────────────
        reviewed_json = output_dir / "paper_reviewed.json"
        if resume and reviewed_json.exists():
            step(5, TOTAL_STEPS, "Reviewer Agent (캐시 사용)")
            reviewed_data = _load_json(reviewed_json)
        else:
            step(5, TOTAL_STEPS, "Reviewer Agent")
            reviewed_data = reviewer_agent.run(
                parsed_data, translated_data, output_dir, client, glossary
            )

        # ── Step 6: Reconstruction ────────────────────────────────
        step(6, TOTAL_STEPS, "Reconstruction Agent")
        md_path, html_path = reconstruction_agent.run(reviewed_data, output_dir, pdf_path)

        print(f"\n\033[1m\033[32m완료!\033[0m 총 소요 시간: {elapsed()}")
        print(f"  출력: {md_path}")
        print(f"        {html_path}")
        print(f"        {output_dir / 'paper_figures'}/")
