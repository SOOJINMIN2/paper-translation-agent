import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Gemini 모델 설정 ──────────────────────────────────────────────
HIGH_PRIORITY_MODEL = os.environ.get("HIGH_PRIORITY_MODEL", "gemini-1.5-flash")
LOW_PRIORITY_MODEL  = os.environ.get("LOW_PRIORITY_MODEL",  "gemini-1.5-flash")
VISION_MODEL        = os.environ.get("VISION_MODEL",        "gemini-1.5-flash")

# ── 파이프라인 설정 ───────────────────────────────────────────────
MARKER_CONFIDENCE_THRESHOLD = float(os.environ.get("MARKER_THRESHOLD", "0.7"))
MAX_RETRANSLATION_ATTEMPTS  = int(os.environ.get("MAX_RETRANSLATION", "2"))
MAX_SECTION_CHARS           = int(os.environ.get("MAX_SECTION_CHARS", "20000"))  # ~5000 tokens

# ── 용어집 경로 ───────────────────────────────────────────────────
_default_glossary = Path.home() / "papers"
GLOSSARY_PATH = Path(os.environ.get("GLOSSARY_PATH", str(_default_glossary)))

# ── API 키 ────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
