"""논문번역 에이전트 - Streamlit 웹 앱."""
import json
import os
import tempfile
import threading
import queue
import time
from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="논문번역 에이전트",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ─────────────────────────────────────────────────────────
st.markdown("""
<style>
.stApp { background: #f7f8fc; }
.step-header { font-size: 22px; font-weight: 700; color: #1a1d2e; margin-bottom: 4px; }
.step-sub { font-size: 14px; color: #6b7280; margin-bottom: 24px; }
.priority-high   { color: #16a34a; font-weight: 600; }
.priority-medium { color: #d97706; font-weight: 600; }
.priority-low    { color: #6b7280; }
.download-section { background: #eef2ff; border-radius: 12px; padding: 20px; margin-top: 16px; }
</style>
""", unsafe_allow_html=True)


# ── 세션 상태 초기화 ──────────────────────────────────────────────
def init_state():
    defaults = {
        "stage": "upload",       # upload → priority → translating → review → done
        "api_key": "",
        "parsed_data": None,
        "style_data": None,
        "priority_data": None,
        "translated_data": None,
        "reviewed_data": None,
        "conflicts": [],
        "tmp_dir": None,
        "pdf_name": "",
        "progress_log": [],
        "error": None,
        "md_content": "",
        "html_content": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()


# ── 사이드바 ──────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🔬 논문번역 에이전트")
    st.markdown("자연과학(물리·화학) 논문 PDF를 한국어로 번역합니다.")
    st.divider()

    # API 키 입력 (Streamlit Cloud에서는 st.secrets 우선)
    secret_key = st.secrets.get("GEMINI_API_KEY", "") if hasattr(st, "secrets") else ""
    env_key = os.environ.get("GEMINI_API_KEY", "")
    default_key = secret_key or env_key

    if not default_key:
        api_key = st.text_input(
            "Gemini API Key",
            type="password",
            placeholder="AIza...",
            help="Google AI Studio (aistudio.google.com)에서 무료 발급",
        )
        st.session_state.api_key = api_key
    else:
        st.session_state.api_key = default_key
        st.success("✓ API 키 설정됨")

    st.divider()
    st.markdown("**번역 모델**")
    st.caption("Gemini 2.0 Flash (고·저우선순위 모두)")
    st.divider()

    if st.session_state.stage != "upload":
        if st.button("🔄 새 논문 번역", use_container_width=True):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

    st.markdown("---")
    st.caption("📖 [설계서](https://github.com)")


# ── 진행 단계 표시 ────────────────────────────────────────────────
STAGES = ["upload", "priority", "translating", "review", "done"]
stage_idx = STAGES.index(st.session_state.stage)
step_labels = ["① PDF 업로드", "② 우선순위 설정", "③ 번역 중", "④ 검토", "⑤ 완료"]
cols = st.columns(5)
for i, (col, label) in enumerate(zip(cols, step_labels)):
    with col:
        if i < stage_idx:
            st.markdown(f"<span style='color:#16a34a;font-size:13px;font-weight:600'>{label} ✓</span>", unsafe_allow_html=True)
        elif i == stage_idx:
            st.markdown(f"<span style='color:#4f72e3;font-size:13px;font-weight:700'>{label}</span>", unsafe_allow_html=True)
        else:
            st.markdown(f"<span style='color:#d1d5db;font-size:13px'>{label}</span>", unsafe_allow_html=True)

st.divider()


# ════════════════════════════════════════════════════════════════
# STAGE 1: 업로드
# ════════════════════════════════════════════════════════════════
if st.session_state.stage == "upload":
    st.markdown('<div class="step-header">PDF 논문 업로드</div>', unsafe_allow_html=True)
    st.markdown('<div class="step-sub">영어로 작성된 자연과학 논문 PDF를 업로드하세요.</div>', unsafe_allow_html=True)

    col1, col2 = st.columns([2, 1])
    with col1:
        uploaded = st.file_uploader(
            "논문 PDF",
            type=["pdf"],
            help="최대 파일 크기 200MB",
        )
        supp = st.file_uploader(
            "Supplementary Material PDF (선택)",
            type=["pdf"],
        )

    with col2:
        st.info("**지원 형식**\n- 단일/두 단 레이아웃\n- 수식 집약형 논문\n- DRM 미보호 PDF")

    if uploaded:
        if not st.session_state.api_key:
            st.error("사이드바에서 Gemini API 키를 입력하세요.")
        else:
            if st.button("🚀 분석 시작", type="primary", use_container_width=False):
                # 임시 폴더에 PDF 저장
                tmp = tempfile.mkdtemp()
                st.session_state.tmp_dir = tmp
                pdf_path = Path(tmp) / uploaded.name
                pdf_path.write_bytes(uploaded.read())
                st.session_state.pdf_name = uploaded.name

                if supp:
                    supp_path = Path(tmp) / supp.name
                    supp_path.write_bytes(supp.read())

                # Parsing + Style + Priority 실행
                with st.status("논문 분석 중...", expanded=True) as status:
                    try:
                        os.environ["GEMINI_API_KEY"] = st.session_state.api_key
                        from utils.gemini_client import GeminiClient
                        from agents import parsing_agent, style_agent, priority_agent

                        client = GeminiClient()
                        output_dir = Path(tmp)

                        st.write("📄 PDF 파싱 중...")
                        parsed = parsing_agent.run(pdf_path, output_dir, client)
                        st.session_state.parsed_data = parsed
                        st.write(f"✓ 섹션 {len(parsed['sections'])}개 추출")

                        st.write("🔍 문체 분석 중...")
                        style = style_agent.run(parsed, output_dir, client)
                        st.session_state.style_data = style
                        st.write(f"✓ 문체: {style.get('style_type')} (수식 비율 {style.get('equation_ratio',0):.0%})")

                        st.write("📊 섹션 우선순위 분석 중...")
                        # Priority Agent는 interactive 없이 자동 배정만
                        from agents.priority_agent import _default_priority
                        import re
                        sections_prio = []
                        for s in parsed["sections"]:
                            prio = _default_priority(s["title"])
                            sections_prio.append({
                                "id": s["id"],
                                "title": s["title"],
                                "level": s["level"],
                                "priority": prio,
                                "model": "gemini-2.0-flash",
                            })
                        st.session_state.priority_data = {
                            "paper_id": parsed["paper_id"],
                            "sections": sections_prio,
                        }
                        st.write(f"✓ 우선순위 배정 완료")

                        status.update(label="분석 완료!", state="complete")
                        st.session_state.stage = "priority"
                        st.rerun()

                    except Exception as e:
                        status.update(label="오류 발생", state="error")
                        st.error(f"오류: {e}")


# ════════════════════════════════════════════════════════════════
# STAGE 2: 우선순위 설정
# ════════════════════════════════════════════════════════════════
elif st.session_state.stage == "priority":
    st.markdown('<div class="step-header">섹션 우선순위 확인 및 조정</div>', unsafe_allow_html=True)
    st.markdown('<div class="step-sub">high 섹션은 고품질 번역, low 섹션은 빠른 번역이 적용됩니다.</div>', unsafe_allow_html=True)

    style = st.session_state.style_data or {}
    col1, col2, col3 = st.columns(3)
    col1.metric("문체 유형", style.get("style_type", "-"))
    col2.metric("수식 비율", f"{style.get('equation_ratio', 0):.0%}")
    col3.metric("용어 밀도", style.get("term_density", "-"))

    st.subheader("섹션 우선순위 설정")
    priority_options = ["high", "medium", "low"]

    updated_sections = []
    for sec in st.session_state.priority_data["sections"]:
        col1, col2 = st.columns([3, 1])
        with col1:
            indent = "　" * (sec["level"] - 1)
            st.markdown(f"{indent}**{sec['title']}**")
        with col2:
            prio = st.selectbox(
                label="우선순위",
                options=priority_options,
                index=priority_options.index(sec["priority"]),
                key=f"prio_{sec['id']}",
                label_visibility="collapsed",
            )
        updated_sections.append({**sec, "priority": prio})

    st.session_state.priority_data["sections"] = updated_sections

    if st.button("✅ 확인하고 번역 시작", type="primary"):
        st.session_state.stage = "translating"
        st.rerun()


# ════════════════════════════════════════════════════════════════
# STAGE 3: 번역 중
# ════════════════════════════════════════════════════════════════
elif st.session_state.stage == "translating":
    st.markdown('<div class="step-header">번역 진행 중</div>', unsafe_allow_html=True)
    st.markdown('<div class="step-sub">섹션별로 번역을 수행합니다. 잠시 기다려 주세요 (15~30분 소요).</div>', unsafe_allow_html=True)

    progress_bar = st.progress(0)
    status_text  = st.empty()
    log_area     = st.empty()
    log_lines    = []

    try:
        os.environ["GEMINI_API_KEY"] = st.session_state.api_key
        from utils.gemini_client import GeminiClient
        from utils.glossary import GlossaryManager
        from agents import translation_agent, reviewer_agent, reconstruction_agent

        client   = GeminiClient()
        glossary = GlossaryManager()
        output_dir = Path(st.session_state.tmp_dir)
        parsed     = st.session_state.parsed_data
        style      = st.session_state.style_data
        priority   = st.session_state.priority_data

        # Translation
        sections = parsed["sections"]
        total = len(sections)

        # 수동 번역 루프 (진행바 업데이트용)
        from agents.translation_agent import (
            _protect_equations, _restore_equations, _chunk_section,
            _build_prompt, _extract_new_terms,
        )
        import config

        style_guidance = style.get("translation_guidance", "자연스러운 한국어로 번역하세요.")
        subfield = style.get("subfield", "")
        glossary_block = glossary.glossary_prompt_block([subfield] if subfield else [])
        priority_map = {sp["id"]: sp for sp in priority["sections"]}
        chunk_terms: dict = {}
        all_new_terms: dict = {}
        translated_sections = []

        for idx, section in enumerate(sections, 1):
            title = section["title"]
            status_text.markdown(f"**[{idx}/{total}]** `{title}` 번역 중...")
            progress_bar.progress(idx / total)

            sec_id = section["id"]
            sp = priority_map.get(sec_id, {"priority": "medium", "model": config.LOW_PRIORITY_MODEL})
            model = sp["model"]

            import re
            is_ref = bool(re.search(r"reference|bibliograph", title, re.I))
            protected, eq_map = _protect_equations(section["content"])
            chunks = _chunk_section(protected)
            translated_chunks = []

            for chunk in chunks:
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
                new_terms = _extract_new_terms(result)
                chunk_terms.update(new_terms)
                all_new_terms.update(new_terms)

            translated_content = _restore_equations("\n".join(translated_chunks), eq_map)
            log_lines.append(f"✓ [{idx}/{total}] {title}")
            log_area.markdown("\n".join(log_lines[-8:]))  # 최근 8개 표시

            translated_sections.append({
                "id": sec_id,
                "title": title,
                "level": section["level"],
                "original_content": section["content"],
                "translated_content": translated_content,
                "priority": sp["priority"],
                "equations": section.get("equations", []),
                "figures": section.get("figures", []),
                "tables": section.get("tables", []),
            })

        translated_data = {
            "paper_id": parsed["paper_id"],
            "sections": translated_sections,
            "new_terms": all_new_terms,
            "references": parsed.get("references", []),
        }
        st.session_state.translated_data = translated_data

        # Reviewer
        status_text.markdown("**품질 검증 중...**")
        reviewed = reviewer_agent.run(parsed, translated_data, output_dir, client, glossary)
        st.session_state.reviewed_data = reviewed
        st.session_state.conflicts = reviewed.get("resolved_conflicts", {})

        # Reconstruction
        status_text.markdown("**출력 파일 생성 중...**")
        pdf_path = output_dir / st.session_state.pdf_name
        if not pdf_path.exists():
            # pdf_path가 없으면 stem만 사용
            class _FakePath:
                stem = Path(st.session_state.pdf_name).stem
            pdf_path = _FakePath()

        md_path, html_path = reconstruction_agent.run(reviewed, output_dir, pdf_path)
        st.session_state.md_content   = md_path.read_text(encoding="utf-8")
        st.session_state.html_content = html_path.read_text(encoding="utf-8")

        progress_bar.progress(1.0)
        status_text.markdown("**✅ 번역 완료!**")
        glossary.add_terms(all_new_terms, subfield or "general")

        st.session_state.stage = "done"
        time.sleep(0.5)
        st.rerun()

    except Exception as e:
        st.error(f"번역 중 오류 발생: {e}")
        st.exception(e)


# ════════════════════════════════════════════════════════════════
# STAGE 4: 완료
# ════════════════════════════════════════════════════════════════
elif st.session_state.stage == "done":
    st.markdown('<div class="step-header">✅ 번역 완료</div>', unsafe_allow_html=True)
    pdf_stem = Path(st.session_state.pdf_name).stem

    # 통계
    reviewed = st.session_state.reviewed_data or {}
    sections = reviewed.get("sections", [])
    new_terms = reviewed.get("new_terms", {})

    col1, col2, col3 = st.columns(3)
    col1.metric("번역된 섹션", f"{len(sections)}개")
    col2.metric("신규 등록 용어", f"{len(new_terms)}개")
    col3.metric("검수 통과", "✓" if reviewed.get("review_passed") else "경고 있음")

    st.markdown('<div class="download-section">', unsafe_allow_html=True)
    st.subheader("📥 결과 다운로드")
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            label="📝 Markdown 다운로드 (Obsidian용)",
            data=st.session_state.md_content.encode("utf-8"),
            file_name=f"{pdf_stem}_kr.md",
            mime="text/markdown",
            use_container_width=True,
        )
    with col2:
        st.download_button(
            label="🌐 HTML 다운로드 (브라우저 열기)",
            data=st.session_state.html_content.encode("utf-8"),
            file_name=f"{pdf_stem}_kr.html",
            mime="text/html",
            use_container_width=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

    # 번역 미리보기
    st.subheader("번역 미리보기")
    if sections:
        for sec in sections[:3]:  # 처음 3개 섹션 미리보기
            with st.expander(f"**{sec['title']}**"):
                st.markdown(sec["translated_content"][:800] + ("..." if len(sec["translated_content"]) > 800 else ""))

    # 신규 용어 목록
    if new_terms:
        st.subheader(f"📚 이번 번역에서 등록된 신규 용어 ({len(new_terms)}개)")
        term_rows = [{"영어": en, "한국어": ko} for en, ko in list(new_terms.items())[:30]]
        st.table(term_rows)
