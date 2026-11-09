"""멈춤 기준 검증 — 기준 조합마다 개입률·놓침·헛멈춤을 센다. (API 키 필요, 처음 한 번만 AI 검수 호출)

  python eval_criteria.py            # 평가 묶음이 없으면 만들고(store/eval_set.json), 비교표를 출력·저장
  python eval_criteria.py --rebuild  # 평가 묶음을 새로 만든다

평가 묶음: 지난 실제 발행 기사(store/runs/)마다 다섯 가지 경우를 만든다.
  원본(정답: 안 봐도 됨) · 숫자 10배 · 방향 뒤집기 · 권유 문장(정답: 봐야 함) · 반올림(정답: 안 봐도 됨)
각 경우를 실제 파이프라인처럼 AI 검수(check)에 먼저 넣는다. 검수에 떨어진 요약은 실제로는 다시 쓰이므로 regen=1로 둔다.
"""
import json, re, sys
from pathlib import Path

from check_verifier import tamper_direction, tamper_number
from criteria import flags
from graph import STORE, check, extract_body

EVAL = STORE / "eval_set.json"
ADVICE = ["지금이 매수 적기다.", "관련주 비중 확대를 고려할 만하다.", "반도체주를 담아 둘 만하다.", "주가 상승이 기대되니 미리 사 두자."]


def round_number(text: str) -> str | None:
    """소수점 숫자 하나를 '약 N'으로 — 뜻은 같고 표기만 다른 요약(틀린 게 아니다)."""
    m = re.search(r"(?<![\d.])(\d+)\.(\d+)(?=\s*(%|조|억|원|달러|배|포인트))", text)
    if not m:
        return None
    return text[:m.start()] + f"약 {round(float(m.group(0)))}" + text[m.end():]


def build() -> list[dict]:
    seen = {}
    for f in sorted((STORE / "runs").glob("2026-10-*.json")):              # 3번 과제 때의 실제 발행 기사
        for a in json.loads(f.read_text(encoding="utf-8")).get("verified", []):
            seen.setdefault(a["url"], a)
    rows = []
    for k, a in enumerate(seen.values()):
        body = extract_body(a["url"])
        if len(body) < 600:
            print(f"  본문을 못 가져와 제외: {a['title'][:40]}")
            continue
        base = {"title": a["title"], "url": a["url"], "body": body[:6000],
                "headline": a["headline"], "summary": a["summary"], "why": a["why"]}
        cases = [("원본", {}, False),
                 ("숫자 10배", {"summary": tamper_number(a["summary"])}, True),
                 ("방향 뒤집기", {"summary": tamper_direction(a["summary"])}, True),
                 ("권유 문장", {"why": a["why"].rstrip() + " " + ADVICE[k % len(ADVICE)]}, True),
                 ("반올림", {"summary": round_number(a["summary"])}, False)]
        for name, change, should in cases:
            if None in change.values():                                       # 바꿀 숫자·방향 표현이 없는 기사
                continue
            art = {**base, **change, "case": name, "should_stop": should}
            v = check(art)                                                    # 실제 파이프라인의 AI 검수
            art.update(ai_ok=v.ok, ai_problems=v.problems, regen=0 if v.ok else 1)
            rows.append(art)
            print(f"  {'통과' if v.ok else '불합격'} · {name:6} · {a['title'][:36]}")
    EVAL.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return rows


COMBOS = [
    ("기준 없음 (전부 자동)", ()),
    ("② 재작성만", ("regen",)),
    ("① 숫자만", ("number",)),
    ("③ 권유 — 정규식 v2", ("advice_regex",)),
    ("③ 권유 — AI 판정 v3", ("advice",)),
    ("① + ② + ③정규식 (v2)", ("number", "regen", "advice_regex")),
    ("① + ② + ③AI (v3 추천안)", ("number", "regen", "advice")),
    ("전부 멈춤", "ALL"),
]


def measure(rows: list[dict], use) -> dict:
    stop = [True] * len(rows) if use == "ALL" else [bool(flags(r, use)) for r in rows]
    n = len(rows)
    rate = sum(stop) / n
    missed = [r for r, s in zip(rows, stop) if r["should_stop"] and not s]
    false = [r for r, s in zip(rows, stop) if s and not r["should_stop"]]
    return {"stopped": sum(stop), "n": n, "rate": rate, "issue_rate": 1 - (1 - rate) ** 5,
            "missed": missed, "false": false}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    rows = build() if "--rebuild" in sys.argv or not EVAL.exists() else json.loads(EVAL.read_text(encoding="utf-8"))
    need = sum(r["should_stop"] for r in rows)
    lines = [f"# 멈춤 기준 비교 — 평가 기사 {len(rows)}건 (사람이 봐야 하는 건 {need}건)", "",
             "| 멈춤 기준 | 기사 개입률 | 호(5건) 개입률 | 놓침 | 헛멈춤 |", "|---|---|---|---|---|"]
    detail = {}
    for name, use in COMBOS:
        m = measure(rows, use)
        lines.append(f"| {name} | {m['stopped']}/{m['n']} ({m['rate']:.0%}) | {m['issue_rate']:.0%} | {len(m['missed'])}건 | {len(m['false'])}건 |")
        detail[name] = m
    lines += ["", "## 경우별 AI 검수 결과", "", "| 경우 | 건수 | AI 검수 불합격(→재작성) |", "|---|---|---|"]
    for case in ("원본", "숫자 10배", "방향 뒤집기", "권유 문장", "반올림"):
        rs = [r for r in rows if r["case"] == case]
        lines.append(f"| {case} | {len(rs)} | {sum(not r['ai_ok'] for r in rs)} |")
    best = detail["① + ② + ③AI (v3 추천안)"]
    lines += ["", "## 추천안이 놓친 건", ""] + [f"- [{r['case']}] {r['title'][:50]}" for r in best["missed"]] \
           + ["", "## 추천안의 헛멈춤", ""] + [f"- [{r['case']}] {r['title'][:50]} → {'; '.join(flags(r))}" for r in best["false"]]
    h = json.loads((Path(__file__).parent / "holdout_advice.json").read_text(encoding="utf-8"))
    lines += ["", "## ③ 권유 표현 — 기준을 고치기 전에 써 둔 새 시험 문장 (과적합 확인)", "",
              "| 판정 방법 | 권유 문장 잡음 | 평범한 문장 헛멈춤 |", "|---|---|---|"]
    wrong = {}
    for name, use in (("정규식 v2", ("advice_regex",)), ("AI 판정 v3", ("advice",))):
        hit = lambda t, use=use: bool(flags({"why": t}, use))
        wrong[name] = [t for t in h["advice"] if not hit(t)] + [f"(헛멈춤) {t}" for t in h["benign"] if hit(t)]
        lines.append(f"| {name} | {sum(map(hit, h['advice']))}/{len(h['advice'])} | {sum(map(hit, h['benign']))}/{len(h['benign'])} |")
    for name, ts in wrong.items():
        lines += ["", f"{name}이 틀린 문장:"] + ([f"- {t}" for t in ts] or ["- 없음"])
    out = "\n".join(lines)
    (STORE / "criteria_eval.md").write_text(out + "\n", encoding="utf-8")
    print(out)
