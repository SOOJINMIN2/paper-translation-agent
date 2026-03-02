"""Reconstruction Agent - Markdown + HTML 최종 출력 생성."""
import html as html_lib
import json
import re
from pathlib import Path

from utils.console import ok


# ── Markdown 생성 ────────────────────────────────────────────────

def _build_markdown(reviewed_data: dict, figures_dir: Path) -> str:
    lines = [f"# {reviewed_data['paper_id']} (한국어 번역)\n"]

    for sec in reviewed_data["sections"]:
        prefix = "#" * max(sec.get("level", 2), 1)
        lines.append(f"\n{prefix} {sec['title']}\n")

        content = sec["translated_content"]

        # 그림 경로를 상대 경로로 변환
        if figures_dir.exists():
            for fig in sec.get("figures", []):
                img_path = fig.get("image_path", "")
                if img_path:
                    rel = f"paper_figures/{img_path}"
                    caption = fig.get("caption_kr") or fig.get("caption", "")
                    content += f"\n\n![그림]({rel})\n*{caption}*\n"

        # 원문 병렬 표시 (재번역 실패 섹션)
        if sec.get("parallel_original"):
            content += "\n\n> **[번역 검토 필요 - 원문 병렬 표시]**\n"
            for orig_line in sec["parallel_original"].split("\n"):
                content += f"> {orig_line}\n"

        lines.append(content)

    # 참고문헌
    refs = reviewed_data.get("references", [])
    if refs:
        lines.append("\n## 참고문헌\n")
        for ref in refs:
            lines.append(f"{ref['id']} {ref['text']}\n")

    return "\n".join(lines)


# ── HTML 생성 ────────────────────────────────────────────────────

def _build_toc(sections: list[dict]) -> tuple[str, list[dict]]:
    """Sidebar TOC HTML + 섹션에 anchor id 부여."""
    toc_html = '<div class="toc-label">목차</div>\n'
    enriched = []
    for i, sec in enumerate(sections):
        anchor = f"sec-{i}"
        level = sec.get("level", 2)
        indent_class = f"level-{min(level, 3)}"
        title_escaped = html_lib.escape(sec["title"])
        toc_html += f'<a class="toc-item {indent_class}" href="#{anchor}">{title_escaped}</a>\n'
        enriched.append({**sec, "_anchor": anchor})
    return toc_html, enriched


def _section_to_html(sec: dict, figures_dir_name: str) -> str:
    """섹션 딕셔너리를 HTML로 변환."""
    level = sec.get("level", 2)
    h_tag = f"h{min(level + 1, 4)}"
    anchor = sec.get("_anchor", "")
    title = html_lib.escape(sec["title"])
    content = sec["translated_content"]

    # 수식 보호 (MathJax가 처리할 LaTeX 블록은 변환 제외)
    eq_map: dict[str, str] = {}
    counter = [0]

    def save_eq(m):
        key = f"EQPLACEHOLDER{counter[0]}"
        eq_map[key] = m.group(0)
        counter[0] += 1
        return key

    content = re.sub(r"\$\$[\s\S]+?\$\$", save_eq, content)
    content = re.sub(r"\$[^$\n]+?\$", save_eq, content)

    # 기본 마크다운 → HTML 변환 (간단 처리)
    content = html_lib.escape(content)
    for key, eq in eq_map.items():
        content = content.replace(html_lib.escape(key), eq)

    content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", content)
    content = re.sub(r"\*(.+?)\*",     r"<em>\1</em>", content)
    content = re.sub(r"`(.+?)`",       r"<code>\1</code>", content)

    # 표 변환 (마크다운 테이블)
    content = _md_table_to_html(content)

    # 단락 변환
    paragraphs = content.split("\n\n")
    html_paras = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if p.startswith("<table") or p.startswith("<pre") or p.startswith(">"):
            html_paras.append(p)
        else:
            lines = p.split("\n")
            if all(l.startswith("- ") or l.startswith("* ") for l in lines if l.strip()):
                items = "".join(f"<li>{l.lstrip('- *').strip()}</li>" for l in lines if l.strip())
                html_paras.append(f"<ul>{items}</ul>")
            else:
                html_paras.append(f"<p>{p.replace(chr(10), '<br>')}</p>")

    body = "\n".join(html_paras)

    # 그림 삽입
    for fig in sec.get("figures", []):
        img = fig.get("image_path", "")
        caption = html_lib.escape(fig.get("caption_kr") or fig.get("caption", ""))
        if img:
            body += f'\n<figure><img src="{figures_dir_name}/{img}" alt="{caption}"><figcaption>{caption}</figcaption></figure>'

    # 원문 병렬 표시
    if sec.get("parallel_original"):
        orig_escaped = html_lib.escape(sec["parallel_original"])
        body += f'\n<details class="parallel-original"><summary>원문 병렬 표시 (번역 검토 필요)</summary><pre>{orig_escaped}</pre></details>'

    return f'<section id="{anchor}">\n<{h_tag}>{title}</{h_tag}>\n{body}\n</section>'


def _md_table_to_html(text: str) -> str:
    """마크다운 표를 HTML 표로 변환."""
    def replace_table(m):
        rows = m.group(0).strip().split("\n")
        html = ["<table>"]
        for i, row in enumerate(rows):
            if re.match(r"^\|[-| :]+\|$", row):
                continue
            cells = [c.strip() for c in row.strip("|").split("|")]
            tag = "th" if i == 0 else "td"
            html.append("<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>")
        html.append("</table>")
        return "\n".join(html)

    return re.sub(r"(\|.+\|\n(?:\|[-: ]+\|\n)(?:\|.+\|\n?)+)", replace_table, text, flags=re.MULTILINE)


HOVER_JS = """
// hover tooltip for inline citations
document.querySelectorAll('a[data-ref]').forEach(a => {
  const tip = document.createElement('div');
  tip.className = 'tooltip';
  tip.textContent = a.dataset.ref;
  document.body.appendChild(tip);
  a.addEventListener('mousemove', e => {
    tip.style.left = e.pageX + 12 + 'px';
    tip.style.top  = e.pageY + 12 + 'px';
    tip.style.display = 'block';
  });
  a.addEventListener('mouseleave', () => tip.style.display = 'none');
});
// TOC active section tracking
const tocLinks = document.querySelectorAll('.toc-item');
const sections = document.querySelectorAll('section[id]');
const obs = new IntersectionObserver(entries => {
  entries.forEach(e => {
    if (e.isIntersecting) {
      tocLinks.forEach(l => l.classList.remove('active'));
      const a = document.querySelector(`.toc-item[href="#${e.target.id}"]`);
      if (a) a.classList.add('active');
    }
  });
}, { rootMargin: '-10% 0px -80% 0px' });
sections.forEach(s => obs.observe(s));
// scroll progress
const bar = document.getElementById('progress');
window.addEventListener('scroll', () => {
  const p = window.scrollY / (document.body.scrollHeight - window.innerHeight) * 100;
  bar.style.width = p + '%';
});
"""

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} - 한국어 번역</title>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js" async></script>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700&family=JetBrains+Mono&display=swap" rel="stylesheet">
<style>
:root{{--sidebar:260px;--hdr:52px;--accent:#4f72e3;--bg:#f7f8fc;--card:#fff;--border:#e2e5ef;--text:#1a1d2e;--muted:#6b7280;--sidebar-bg:#1e2232;--sidebar-txt:#9daabf;}}
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:'Noto Sans KR',sans-serif;background:var(--bg);color:var(--text);line-height:1.8;}}
#progress{{position:fixed;top:var(--hdr);left:0;height:3px;background:linear-gradient(90deg,var(--accent),#7c9cf5);z-index:200;transition:width .1s;}}
header{{position:fixed;top:0;left:0;right:0;height:var(--hdr);background:var(--sidebar-bg);display:flex;align-items:center;padding:0 20px;gap:12px;z-index:100;box-shadow:0 1px 8px rgba(0,0,0,.3);}}
header h1{{font-size:14px;font-weight:600;color:#fff;}}
header .meta{{margin-left:auto;font-size:12px;color:#7a8299;}}
nav#sidebar{{position:fixed;top:var(--hdr);left:0;bottom:0;width:var(--sidebar);background:var(--sidebar-bg);overflow-y:auto;padding:16px 0 40px;z-index:90;}}
nav#sidebar::-webkit-scrollbar{{width:4px;}}
nav#sidebar::-webkit-scrollbar-thumb{{background:#3a3f55;border-radius:2px;}}
.toc-label{{font-size:10px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#4a5268;padding:0 16px 8px;}}
.toc-item{{display:block;padding:5px 16px;font-size:12.5px;color:var(--sidebar-txt);text-decoration:none;border-left:2px solid transparent;transition:.15s;}}
.toc-item:hover{{background:#2d3348;color:#d0d8f0;}}
.toc-item.active{{color:#7c9cf5;border-left-color:#7c9cf5;background:rgba(124,156,245,.08);font-weight:500;}}
.toc-item.level-2{{padding-left:28px;font-size:12px;}}
.toc-item.level-3{{padding-left:42px;font-size:11.5px;color:#7a8299;}}
main{{margin-left:var(--sidebar);margin-top:var(--hdr);padding:44px 56px 80px;max-width:860px;}}
section{{margin-bottom:36px;}}
h2{{font-size:22px;font-weight:700;color:var(--text);margin:40px 0 12px;padding-bottom:8px;border-bottom:2px solid var(--accent);}}
h3{{font-size:17px;font-weight:700;color:var(--text);margin:28px 0 8px;padding-bottom:4px;border-bottom:1px solid var(--border);}}
h4{{font-size:14px;font-weight:600;color:var(--accent);margin:20px 0 6px;}}
p{{margin:8px 0;font-size:14.5px;}}
ul,ol{{margin:8px 0 8px 20px;font-size:14.5px;}}
li{{margin:4px 0;}}
strong{{font-weight:700;}}
code{{font-family:'JetBrains Mono',monospace;font-size:12.5px;background:#eef0f8;color:#c0392b;padding:1px 5px;border-radius:4px;}}
pre{{background:#1e2232;color:#a8d8a8;font-family:'JetBrains Mono',monospace;font-size:12.5px;padding:18px 22px;border-radius:10px;overflow-x:auto;margin:14px 0;}}
table{{width:100%;border-collapse:collapse;margin:14px 0;font-size:13.5px;background:var(--card);border-radius:10px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.06);}}
th{{background:var(--accent);color:#fff;padding:10px 14px;text-align:left;font-weight:600;font-size:13px;}}
td{{padding:9px 14px;border-bottom:1px solid var(--border);vertical-align:top;}}
tbody tr:hover{{background:#eef2ff;}}
tbody tr:last-child td{{border-bottom:none;}}
figure{{margin:16px 0;text-align:center;}}
figure img{{max-width:100%;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.1);}}
figcaption{{font-size:13px;color:var(--muted);margin-top:6px;}}
.parallel-original{{background:#fff8f0;border:1px solid #fde8c8;border-radius:8px;margin:12px 0;padding:4px;}}
.parallel-original summary{{cursor:pointer;padding:8px 12px;font-size:13px;color:#c0700a;font-weight:600;}}
.parallel-original pre{{background:#fff8f0;color:#666;font-size:12px;margin:0;padding:12px;}}
.tooltip{{position:absolute;background:#1e2232;color:#d0d8f0;font-size:12px;padding:6px 10px;border-radius:6px;pointer-events:none;display:none;max-width:320px;z-index:999;}}
a[data-ref]{{color:var(--accent);text-decoration:none;cursor:help;}}
hr{{border:none;border-top:1px solid var(--border);margin:32px 0;}}
@media(max-width:800px){{nav#sidebar{{display:none;}}main{{margin-left:0;padding:28px 20px 60px;}}}}
</style>
</head>
<body>
<div id="progress"></div>
<header>
  <span style="font-size:18px;">📄</span>
  <h1>{title} — 한국어 번역</h1>
  <div class="meta">자연과학 논문 번역 에이전트</div>
</header>
<nav id="sidebar">
{toc_html}
</nav>
<main>
{sections_html}
{refs_html}
</main>
<script>
MathJax = {{tex: {{inlineMath: [['$','$'],['\\\\(','\\\\)']]}}}};
</script>
<script>{hover_js}</script>
</body>
</html>
"""


def _build_refs_html(refs: list[dict]) -> str:
    if not refs:
        return ""
    items = "".join(
        f'<li id="ref{ref["id"].strip("[]")}">{html_lib.escape(ref["text"])}</li>'
        for ref in refs
    )
    return f'<section id="sec-refs"><h2>참고문헌</h2><ol>{items}</ol></section>'


# ── 메인 에이전트 ─────────────────────────────────────────────────

def run(reviewed_data: dict, output_dir: Path, pdf_path: Path) -> tuple[Path, Path]:
    """
    Markdown + HTML 최종 파일 생성.
    반환: (md_path, html_path)
    """
    stem = pdf_path.stem
    md_path   = output_dir / f"{stem}_kr.md"
    html_path = output_dir / f"{stem}_kr.html"
    figures_dir = output_dir / "paper_figures"

    # ── Markdown ──────────────────────────────────────────────────
    md_content = _build_markdown(reviewed_data, figures_dir)
    md_path.write_text(md_content, encoding="utf-8")
    ok(f"{md_path.name} 생성 완료")

    # ── HTML ──────────────────────────────────────────────────────
    toc_html, enriched_sections = _build_toc(reviewed_data["sections"])
    sections_html = "\n".join(_section_to_html(s, "paper_figures") for s in enriched_sections)
    refs_html = _build_refs_html(reviewed_data.get("references", []))
    title = html_lib.escape(reviewed_data["paper_id"])

    html_content = HTML_TEMPLATE.format(
        title=title,
        toc_html=toc_html,
        sections_html=sections_html,
        refs_html=refs_html,
        hover_js=HOVER_JS,
    )
    html_path.write_text(html_content, encoding="utf-8")
    ok(f"{html_path.name} 생성 완료 (Sidebar TOC 포함)")

    return md_path, html_path
