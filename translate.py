#!/usr/bin/env python3
"""
논문번역 에이전트 CLI 진입점.

사용법:
  python translate.py paper.pdf
  python translate.py paper.pdf supplementary.pdf
  python translate.py --reconstruct-only paper.pdf
"""
import argparse
import sys
from pathlib import Path


def check_api_key():
    import config
    if not config.GEMINI_API_KEY:
        print("\n[오류] GEMINI_API_KEY가 설정되지 않았습니다.")
        print()
        print("  방법 1 - 터미널에서 설정:")
        print("    Windows: set GEMINI_API_KEY=your_key_here")
        print("    Linux/Mac: export GEMINI_API_KEY=your_key_here")
        print()
        print("  방법 2 - .env 파일 생성:")
        print("    .env.example 파일을 .env로 복사 후 API 키 입력")
        print()
        print("  Google AI Studio에서 무료 API 키 발급: https://aistudio.google.com/")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="논문번역 에이전트 - 자연과학 PDF 논문을 한국어로 번역합니다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python translate.py paper.pdf
  python translate.py paper.pdf supplementary.pdf
  python translate.py --reconstruct-only paper.pdf   # 출력 파일만 재생성
        """,
    )
    parser.add_argument(
        "pdf_files",
        nargs="+",
        help="번역할 PDF 파일 경로 (최대 2개: 주 논문 + Supplementary)",
    )
    parser.add_argument(
        "--reconstruct-only",
        action="store_true",
        help="번역 없이 MD/HTML 출력 파일만 재생성 (paper_reviewed.json 필요)",
    )
    args = parser.parse_args()

    # API 키 확인
    check_api_key()

    # PDF 경로 검증
    pdf_paths = []
    for p in args.pdf_files[:2]:  # 최대 2개
        path = Path(p)
        if not path.exists():
            print(f"[오류] 파일을 찾을 수 없습니다: {p}")
            sys.exit(1)
        if path.suffix.lower() != ".pdf":
            print(f"[오류] PDF 파일이 아닙니다: {p}")
            sys.exit(1)
        pdf_paths.append(path)

    # 파이프라인 실행
    from agents.orchestrator import run
    run(pdf_paths, reconstruct_only=args.reconstruct_only)


if __name__ == "__main__":
    # Windows ANSI 색상 지원
    import os
    if os.name == "nt":
        os.system("color")  # Windows 터미널 ANSI 활성화

    main()
