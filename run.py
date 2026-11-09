"""파이프라인 실행 · 승인 대기 확인 · 승인/반려를 명령줄에서 한다. (화면으로 하려면 streamlit run app.py)

  python run.py                    # 새 호를 만든다. 기준에 걸리면 승인 대기로 멈춘다(.env 의 DRY_RUN 기본: 보내지 않음)
  python run.py --dry-run          # 무조건 보내지 않고 store/last_payload.json 만 만든다
  python run.py --mock             # API 키 없이 배선만 시험(가짜 LLM, 발행 안 함)
  python run.py --force-review     # 시험용: 기준과 상관없이 승인 대기로 멈춰 본다
  python run.py --hours 48         # 수집 기간을 48시간으로
  python run.py --list             # 승인 대기 중인 호 목록
  python run.py --approve THREAD   # 그 호를 그대로 승인 → 발행
  python run.py --reject THREAD "사유"  # 그 호를 반려 → 발행 안 함
"""
import os, sys

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    a = sys.argv
    if "--dry-run" in a:
        os.environ["DRY_RUN"] = "1"
    if "--mock" in a:
        os.environ["LLM_MOCK"] = "1"
    if "--force-review" in a:
        os.environ["FORCE_REVIEW"] = "1"
    hours = int(a[a.index("--hours") + 1]) if "--hours" in a else None

    import graph                        # 환경변수를 정한 뒤에 불러온다

    if "--list" in a:
        waiting = graph.pending()
        print(f"승인 대기 {len(waiting)}건")
        for p in waiting:
            print(f"- {p['thread']} · 기사 {len(p['articles'])}건 · 멈춘 이유: {', '.join(p['stop_reasons'])}"
                  f" · 기한 {graph.deadline(p['created_at']):%m-%d %H:%M}")
    elif "--approve" in a or "--reject" in a:
        approve = "--approve" in a
        i = a.index("--approve" if approve else "--reject")
        thread = a[i + 1]
        reason = a[i + 2] if not approve and len(a) > i + 2 else ""
        out = graph.resume(thread, {"action": "approve" if approve else "reject", "by": "cli", "reason": reason})
        print("\n".join(out["log"][-3:]))
    else:
        out = graph.run(hours)
        print("\n".join(out["log"]))    # 이 출력이 GitHub Actions 로그에 그대로 남는다
