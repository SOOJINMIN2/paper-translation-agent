"""Parsing Agent - PDF → 구조화 JSON.

주 전략: pymupdf (텍스트 추출)
폴백: Gemini Vision (복잡한 레이아웃, 수식 집약형, DRM 보호 PDF)
"""
import json
import re
from pathlib import Path

import fitz  # pymupdf

import config
from utils.console import ok, warn, info
from utils.gemini_client import GeminiClient


# ── 텍스트 품질 판단 ─────────────────────────────────────────────

def _is_text_ok(text: str) -> bool:
    """페이지 텍스트가 충분히 읽을 수 있는 수준인지 확인."""
    if not text or len(text.strip()) < 50:
        return False
    # 깨진 문자 비율이 높으면 Vision 필요
    total = len(text)
    garbage = sum(1 for c in text if ord(c) > 0xFFFD or (ord(c) < 32 and c not in "\n\t "))
    return garbage / total < 0.05


# ── 섹션 파싱 헬퍼 ───────────────────────────────────────────────

def _split_sections(markdown_text: str) -> list[dict]:
    """마크다운 텍스트를 섹션 단위로 분리."""
    lines = markdown_text.split("\n")
    sections = []
    current: dict | None = None

    for line in lines:
        heading = re.match(r"^(#{1,4})\s+(.+)$", line)
        if heading:
            if current:
                sections.append(current)
            level = len(heading.group(1))
            title = heading.group(2).strip()
            current = {
                "id": re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_"),
                "title": title,
                "level": level,
                "content": "",
            }
        else:
            if current is None:
                current = {"id": "preamble", "title": "Preamble", "level": 0, "content": ""}
            current["content"] += line + "\n"

    if current:
        sections.append(current)
    return sections


def _extract_equations(text: str) -> list[str]:
    display = re.findall(r"\$\$[\s\S]+?\$\$", text)
    inline  = re.findall(r"\$[^$\n]+?\$", text)
    return display + inline


def _extract_tables(text: str) -> list[dict]:
    tables = []
    table_pattern = re.compile(r"(\|.+\|\n(?:\|[-: ]+\|\n)(?:\|.+\|\n)+)", re.MULTILINE)
    for i, m in enumerate(table_pattern.finditer(text)):
        tables.append({"id": f"tab{i+1}", "content": m.group(0)})
    return tables


def _enrich_section(sec: dict) -> dict:
    content = sec["content"]
    sec["equations"]          = _extract_equations(content)
    sec["has_equations"]      = bool(sec["equations"])
    sec["tables"]             = _extract_tables(content)
    sec["figures"]            = []
    sec["references_inline"]  = re.findall(r"\[(\d+)\]", content)
    return sec


# ── pymupdf 페이지 텍스트 추출 ───────────────────────────────────

def _extract_with_pymupdf(doc: fitz.Document, figures_dir: Path, client: GeminiClient) -> str:
    """페이지별로 pymupdf 추출 시도, 품질 불량 시 Gemini Vision 폴백."""
    VISION_PROMPT = (
        "이 논문 페이지를 구조화된 마크다운으로 변환하세요.\n"
        "규칙:\n"
        "- 섹션 제목은 ## 또는 ### 으로 표시\n"
        "- 수식은 $...$ 또는 $$...$$ LaTeX 형식으로 보존\n"
        "- 표는 마크다운 표 형식으로 변환\n"
        "- 그림은 [Figure N: caption] 형식으로 표시\n"
        "- 두 단(two-column) 레이아웃은 읽기 순서대로 단일 흐름으로 변환\n"
        "- 원문 영어 텍스트 그대로 출력 (번역 금지)"
    )

    pages_text = []
    vision_pages = 0

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        text = page.get_text("text")

        if _is_text_ok(text):
            # pymupdf로 충분히 추출됨
            pages_text.append(text)
        else:
            # Gemini Vision 폴백
            vision_pages += 1
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("png")

            # 페이지 이미지 저장 (figures_dir에)
            page_img = figures_dir / f"page_{page_num+1:03d}.png"
            page_img.write_bytes(img_bytes)

            info(f"  Vision 폴백: 페이지 {page_num+1}/{len(doc)}")
            page_text = client.vision_extract(img_bytes, VISION_PROMPT)
            pages_text.append(page_text)

        # 페이지 내 그림 이미지 추출
        img_list = page.get_images(full=True)
        for img_idx, img_info in enumerate(img_list):
            try:
                xref = img_info[0]
                base_image = doc.extract_image(xref)
                img_ext = base_image["ext"]
                img_data = base_image["image"]
                fig_name = f"fig_p{page_num+1}_{img_idx+1}.{img_ext}"
                (figures_dir / fig_name).write_bytes(img_data)
            except Exception:
                pass

    if vision_pages:
        warn(f"Vision 폴백 사용: {vision_pages}/{len(doc)} 페이지")

    return "\n\n".join(pages_text)


# ── 마크다운 구조 보완 ────────────────────────────────────────────

def _restore_structure_with_gemini(raw_text: str, client: GeminiClient) -> str:
    """추출된 텍스트에 섹션 구조(##, ###)를 Gemini로 복원."""
    prompt = (
        "다음은 PDF에서 추출된 자연과학 논문 텍스트입니다. "
        "섹션 구조를 마크다운 제목(##, ###)으로 복원하세요. "
        "텍스트 내용은 수정하지 말고 구조만 추가하세요. "
        "수식이 있으면 $...$ 형식으로 감싸세요.\n\n"
        f"[원문]\n{raw_text[:12000]}"
    )
    return client.generate(prompt, config.HIGH_PRIORITY_MODEL)


# ── 메인 에이전트 ────────────────────────────────────────────────

def run(pdf_path: Path, output_dir: Path, client: GeminiClient) -> dict:
    """PDF를 파싱하여 paper_parsed.json 생성. 반환: parsed_data dict"""
    figures_dir = output_dir / "paper_figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    parsed_json = output_dir / "paper_parsed.json"

    # pymupdf로 열기
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        raise RuntimeError(f"PDF 열기 실패: {e}") from e

    info("pymupdf로 텍스트 추출 중...")
    raw_text = _extract_with_pymupdf(doc, figures_dir, client)
    doc.close()

    # 섹션 구조가 없으면 Gemini로 복원
    heading_count = len(re.findall(r"^#{1,4}\s", raw_text, re.MULTILINE))
    if heading_count < 3:
        info("섹션 구조 복원 중 (Gemini)...")
        raw_text = _restore_structure_with_gemini(raw_text, client)

    # 섹션 분리 및 구조화
    raw_sections = _split_sections(raw_text)
    sections     = [_enrich_section(s) for s in raw_sections if s["content"].strip()]

    # 그림 파일 목록
    img_files = sorted(figures_dir.glob("fig_*.png"), key=lambda f: f.name)
    if img_files and sections:
        sections[0]["figures"] = [
            {"id": f"fig{i+1}", "image_path": f.name, "caption": ""}
            for i, f in enumerate(img_files)
        ]

    # 참고문헌 분리
    references = []
    ref_sec = next((s for s in sections if re.search(r"reference|bibliography", s["title"], re.I)), None)
    if ref_sec:
        for m in re.finditer(r"\[(\d+)\]\s*(.+)", ref_sec["content"]):
            references.append({"id": f"[{m.group(1)}]", "text": m.group(2).strip()})

    data = {
        "paper_id": pdf_path.stem,
        "source_pdf": str(pdf_path),
        "sections": sections,
        "references": references,
        "parse_method": "pymupdf+vision",
        "parse_issues": [],
    }

    with open(parsed_json, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    img_count = len(img_files)
    eq_count  = sum(len(s["equations"]) for s in sections)
    ok(f"섹션 {len(sections)}개, 수식 {eq_count}개, 그림 {img_count}개 추출")
    ok(f"paper_figures/ 폴더 생성 (PNG {img_count}개)")

    return data
