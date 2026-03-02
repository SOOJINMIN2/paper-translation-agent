"""콘솔 출력 유틸리티 - 색상 및 진행 표시."""
import sys
import time

# ANSI 색상 코드 (Windows 터미널 지원)
RESET  = "\033[0m"
BOLD   = "\033[1m"
CYAN   = "\033[36m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
GRAY   = "\033[90m"
BLUE   = "\033[34m"

_pipeline_start: float = 0.0


def init_pipeline():
    global _pipeline_start
    _pipeline_start = time.time()


def elapsed() -> str:
    secs = int(time.time() - _pipeline_start)
    m, s = divmod(secs, 60)
    return f"{m}분 {s:02d}초"


def step(n: int, total: int, name: str):
    print(f"\n{CYAN}{BOLD}[{n}/{total}] {name}{RESET}")


def ok(msg: str):
    print(f"  {GREEN}✓{RESET} {msg}")


def warn(msg: str):
    print(f"  {YELLOW}⚠{RESET} {msg}", file=sys.stderr)


def error(msg: str):
    print(f"  {RED}✗{RESET} {msg}", file=sys.stderr)


def info(msg: str):
    print(f"  {GRAY}{msg}{RESET}")


def section_done(idx: int, total: int, title: str, start: float, eta_secs: float | None = None):
    secs = int(time.time() - start)
    m, s = divmod(secs, 60)
    eta_str = ""
    if eta_secs is not None:
        em, es = divmod(int(eta_secs), 60)
        eta_str = f", 잔여 ~{em}분 {es:02d}초"
    print(f"  {GREEN}[{idx}/{total} 섹션]{RESET} {title} 번역 완료 ({m}분 {s:02d}초{eta_str})")


def conflict_prompt(term: str, glossary_val: str, current_val: str) -> str:
    """용어 충돌 시 사용자에게 선택을 요청하고 결정값을 반환."""
    print(f"\n  {YELLOW}[충돌]{RESET} '{term}': 용어집='{glossary_val}', 이번 번역='{current_val}'")
    while True:
        choice = input(f"  → 어느 쪽을 사용할까요? [1={glossary_val}, 2={current_val}, 3=스킵]: ").strip()
        if choice == "1":
            return glossary_val
        elif choice == "2":
            return current_val
        elif choice == "3":
            return current_val  # 스킵 시 이번 번역 유지
        print("  1, 2, 3 중 하나를 입력하세요.")


def resume_prompt(last_stage: str) -> bool:
    """이어서 시작 여부를 묻고 True=이어서, False=처음부터 반환."""
    print(f"\n  {YELLOW}이전 작업 데이터가 발견되었습니다 (마지막 완료: {last_stage}).{RESET}")
    while True:
        choice = input("  → [1] 이어서 시작  [2] 처음부터 다시 시작: ").strip()
        if choice == "1":
            return True
        elif choice == "2":
            return False
        print("  1 또는 2를 입력하세요.")


def priority_confirm_prompt(priority_path: str):
    """Priority 배정 결과 확인 대기."""
    print(f"\n  {BLUE}paper_priority.json{RESET}에 저장되었습니다.")
    print(f"  수정 사항이 있으면 파일을 편집 후 Enter를 누르세요. (그냥 Enter → 번역 시작)")
    input("  → ")
