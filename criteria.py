"""사람 승인(HITL) 멈춤 기준 — 기사 한 건을 보고 '사람이 봐야 하는 이유' 목록을 돌려준다.

파이프라인(graph.py)의 gate 노드와 기준 검증 스크립트(eval_criteria.py)가 같은 함수를 쓴다.
기준 값은 audience.yaml 의 review 칸에서 읽는다.

  ① number  헤드라인·요약의 숫자가 원문 본문에 없음 (반올림 값은 통과)       — 코드 검사
  ② regen   검수에서 한 번 떨어진 뒤 다시 쓴 요약                            — 코드 검사
  ③ advice  인사이트 문장이 투자 권유인가 (v3: AI 판정 예/아니오, 실패하면 정규식으로 대신)
"""
import hashlib, json, os, re
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
CFG = yaml.safe_load((ROOT / "audience.yaml").read_text(encoding="utf-8"))
REVIEW = CFG["review"]
CACHE = ROOT / "store" / "advice_cache.json"          # 같은 문장은 다시 묻지 않는다(검증을 여러 번 돌려도 비용 0)

NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


# ── ① 숫자 ─────────────────────────────────────────────────────────────
def numbers(text: str) -> set[str]:
    """글 속 숫자를 쉼표를 뺀 꼴로 모은다. '106조5천억원' → {'106', '5'}"""
    return {m.replace(",", "") for m in NUM_RE.findall(text or "")}


def rounded(n: str) -> set[str]:
    """원문 숫자를 반올림·버림한 꼴. '4.00' → {'4'}, '783.1' → {'783'} — 요약이 '약 4%'로 써도 틀린 게 아니다."""
    try:
        f = float(n)
    except ValueError:
        return set()
    return {str(round(f)), str(int(f))}


def missing_numbers(article: dict) -> list[str]:
    """헤드라인·요약에 있는데 원문 본문에는 없는 숫자 (원문 숫자를 반올림한 값은 있는 것으로 본다)."""
    body = numbers(article.get("body", ""))
    body |= {r for n in body if "." in n for r in rounded(n)}
    shown = numbers(article.get("headline", "") + " " + article.get("summary", ""))
    return sorted(n for n in shown if n not in body)


# ── ③ 투자 권유 ────────────────────────────────────────────────────────
def advice_regex(text: str) -> list[str]:
    """v2 정규식 — AI 판정이 실패할 때 대신 쓰고, 비교 실험에도 쓴다."""
    return [m.group(0) for p in REVIEW.get("advice_patterns", []) for m in [re.search(p, text)] if m]


class AdviceVerdict(BaseModel):
    is_advice: bool = Field(description="독자에게 특정 종목·업종·자산을 사거나 팔거나 계속 들고 있으라고 권하거나, 매매 시점을 제안하면 true")
    phrase: str = Field(description="권유에 해당하는 부분을 문장에서 그대로 옮긴 것. 없으면 빈 문자열")

SYS_ADVICE = ("당신은 금융 뉴스레터의 준법 검토자입니다. 아래 한 문장이 독자에게 투자 권유가 되는지 판정하세요.\n"
              "권유: 특정 종목·업종·자산을 사거나 팔거나 계속 들고 있으라고 하는 말, 매매할 시점을 제안하는 말.\n"
              "권유가 아님: 수급·실적·정책 같은 사실 전달(예: 외국인 순매수, 매수세가 강해졌다), "
              "'~를 확인해 볼 포인트'처럼 살펴볼 지표만 짚는 문장.")

_client, _cache = None, None
def advice_ai(text: str) -> list[str]:
    """AI 판정. 권유면 [해당 부분], 아니면 []. 같은 문장은 캐시에서 꺼낸다."""
    global _client, _cache
    if _cache is None:
        _cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    key = hashlib.sha1(text.encode("utf-8")).hexdigest()
    if key not in _cache:
        if _client is None:
            from openai import OpenAI
            _client = OpenAI()
        r = _client.chat.completions.parse(model=CFG["model"], temperature=0, response_format=AdviceVerdict,
                                           messages=[{"role": "system", "content": SYS_ADVICE},
                                                     {"role": "user", "content": text}])
        v = r.choices[0].message.parsed
        _cache[key] = {"text": text, "is_advice": v.is_advice, "phrase": v.phrase}
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps(_cache, ensure_ascii=False, indent=1), encoding="utf-8")
    c = _cache[key]
    return [c["phrase"] or "(AI 판정)"] if c["is_advice"] else []


def advice_hits(text: str) -> tuple[list[str], str]:
    """(걸린 부분, 판정 방법). 가짜 LLM 모드이거나 AI 호출이 실패하면 정규식으로 대신한다."""
    if REVIEW.get("advice_ai", True) and os.environ.get("LLM_MOCK") != "1":
        try:
            return advice_ai(text), "AI"
        except Exception:
            pass
    return advice_regex(text), "정규식"


# ── 종합 ───────────────────────────────────────────────────────────────
def flags(article: dict, use: tuple = ("number", "regen", "advice")) -> list[str]:
    """이 기사를 사람이 봐야 하는 이유. 빈 목록이면 자동 발행해도 된다.
    use 에 'advice_regex' 를 넣으면 ③을 정규식으로만 판정한다(비교 실험용)."""
    out = []
    if "number" in use and REVIEW.get("number_check", True):
        miss = missing_numbers(article)
        if miss:
            out.append(f"원문에 없는 숫자: {', '.join(miss)}")
    if "regen" in use and REVIEW.get("regen_check", True) and article.get("regen", 0) >= 1:
        out.append("검수에서 한 번 떨어진 뒤 다시 쓴 요약")
    if "advice" in use or "advice_regex" in use:
        hits, how = (advice_regex(article.get("why", "")), "정규식") if "advice_regex" in use \
            else advice_hits(article.get("why", ""))
        if hits:
            out.append(f"투자 권유로 읽힐 표현({how}): {', '.join(hits)}")
    return out
