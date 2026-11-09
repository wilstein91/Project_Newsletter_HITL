"""승인 화면 — 승인 대기 중인 호를 보고 승인·수정·제외·반려한다.

  .venv\\Scripts\\streamlit run app.py

설계 원칙(9번 노드 4절): 담당자가 10초 안에 판단할 수 있어야 한다.
한 화면에 ① 멈춘 이유 ② 통과시키면 일어나는 일 ③ 기사별 요약·원문·AI 판단 근거를 같이 보여 주고,
답은 승인 / 고쳐서 승인 / 기사 빼고 승인 / 반려(사유 필수) 네 가지로 받는다.
"""
import json, os
from datetime import datetime

import streamlit as st

import graph

st.set_page_config(page_title="장전 브리핑 · 발행 승인", page_icon="📰", layout="wide")
KST = graph.KST
if st.session_state.get("done"):                                             # 방금 처리한 결과를 한 번 알려 준다
    st.toast(" · ".join(st.session_state.pop("done")))


def left(created_at: str) -> str:
    d = graph.deadline(created_at) - datetime.now(KST)
    if d.total_seconds() <= 0:
        return "기한 지남"
    h, m = divmod(int(d.total_seconds() // 60), 60)
    return f"{h}시간 {m}분 남음" if h else f"{m}분 남음"


# ── 사이드바: 새 호 만들기(시연용) ───────────────────────────────────────
with st.sidebar:
    st.header("새 호 만들기")
    st.caption("평소에는 매일 아침 자동 실행됩니다. 여기서는 시연용으로 직접 돌립니다. 1~2분 걸립니다.")
    mock = st.checkbox("가짜 AI로 (요금 없음)", value=True)
    force = st.checkbox("기준과 상관없이 멈추게 (시험용)", value=True)
    hours = st.number_input("수집 기간(시간)", 1, 72, 12)
    if st.button("실행", use_container_width=True):
        os.environ["LLM_MOCK"] = "1" if mock else "0"
        os.environ["FORCE_REVIEW"] = "1" if force else "0"
        with st.spinner("수집 → 선별 → 요약 → 검수 → 승인 판정 중…"):
            out = graph.run(int(hours))
        os.environ["LLM_MOCK"] = "0"; os.environ["FORCE_REVIEW"] = "0"
        st.session_state["last_log"] = out["log"]
    if st.session_state.get("last_log"):
        st.code("\n".join(st.session_state["last_log"]), language=None)
    st.divider()
    st.caption("발행은 .env 의 DRY_RUN=1 이면 실제로 보내지 않고 store/last_payload.json 만 만듭니다.")

tab_wait, tab_hist = st.tabs(["⏸ 승인 대기", "🗂 처리 기록"])

# ── 승인 대기 목록 ─────────────────────────────────────────────────────
with tab_wait:
    gone = graph.expire()
    if gone:
        st.info(f"기한이 지난 {len(gone)}건을 운영 규칙대로 자동 반려했습니다: {', '.join(gone)}")
    waiting = graph.pending()
    if not waiting:
        st.success("승인을 기다리는 호가 없습니다. 기준에 걸리지 않은 호는 자동으로 발행됩니다.")
    else:

        labels = [f"{p['thread']} · 기사 {len(p['articles'])}건 · {', '.join(p['stop_reasons'])} · {left(p['created_at'])}" for p in waiting]
        pick = st.radio("승인 대기 목록", range(len(waiting)), format_func=lambda i: labels[i])
        p = waiting[pick]
        t = p["thread"]
        arts = sorted(p["articles"], key=lambda a: not a["flags"])                # 걸린 기사를 위로

        # ① 멈춘 이유 ② 통과시키면 일어나는 일 — 맨 위에 한 번에
        c1, c2 = st.columns([3, 2])
        by_reason = {}                                                            # 같은 이유는 묶어서 한 줄로
        for a in arts:
            for f in a["flags"]:
                by_reason.setdefault(f.split(":")[0], []).append(str(a["idx"] + 1))
        c1.error("**멈춘 이유**  \n" + "  \n".join(f"- {r} — 기사 {'·'.join(sorted(set(n)))}" for r, n in by_reason.items()))
        c2.warning(f"**승인하면** {p['if_approved']}  \n**기한** {graph.deadline(p['created_at']):%m월 %d일 %H:%M}까지 "
                   f"({left(p['created_at'])}) — 지나면 자동 반려")

        # ③ 기사별 카드 — 고치기·빼기를 여기서 바로
        edits, drop = {}, []
        for a in arts:
            i = a["idx"]
            mark = "🔴" if a["flags"] else "🟢"
            with st.container(border=True):
                top = st.columns([6, 1])
                top[0].markdown(f"{mark} **{i + 1}. {a['headline']}**  \n"
                                f"<small>{a['source']} · {a['category']} · [원문 기사]({a['url']})</small>", unsafe_allow_html=True)
                if top[1].checkbox("이 기사 빼기", key=f"drop-{t}-{i}"):
                    drop.append(i)
                if a["flags"]:
                    st.markdown("**걸린 이유**: " + " / ".join(f"`{f}`" for f in a["flags"]))
                l, r = st.columns(2)
                with l:
                    h = st.text_input("헤드라인", a["headline"], key=f"h-{t}-{i}")
                    s = st.text_area("요약", a["summary"], key=f"s-{t}-{i}", height=110)
                    w = st.text_area("💡 인사이트", a["why"], key=f"w-{t}-{i}", height=70)
                    changed = {k: v for k, v, o in (("headline", h, a["headline"]), ("summary", s, a["summary"]), ("why", w, a["why"])) if v != o}
                    if changed:
                        edits[str(i)] = changed
                        st.caption("✏️ 고친 내용이 승인할 때 반영됩니다")
                with r:
                    st.markdown(f"**AI 판단 근거**  \n- 선별 이유: {a['select_reason'] or '—'}  \n"
                                f"- 검수: {'한 번 떨어진 뒤 다시 써서 통과' if a['regen'] else '한 번에 통과'}")
                    with st.expander("원문 본문 보기 (앞부분)"):
                        st.write(a["body"] or "(본문 없음)")

        # ④ 답 네 가지: 승인 / 고쳐서 승인 / 빼고 승인 → 한 버튼으로, 반려는 사유 필수
        st.divider()
        keep = len(arts) - len(drop)
        a1, a2 = st.columns(2)
        with a1:
            label = "승인하고 발행" + (f" (고친 기사 {len(edits)}건" if edits else "") + \
                    (f"{', ' if edits else ' ('}뺀 기사 {len(drop)}건" if drop else "") + (")" if edits or drop else "")
            if st.button(f"✅ {label} → {keep}건", type="primary", use_container_width=True):
                out = graph.resume(t, {"action": "approve", "by": "web", "edits": edits, "drop": drop})
                st.session_state["done"] = out["log"][-2:]
                st.rerun()
        with a2:
            reason = st.text_input("반려 사유 (필수)", key=f"reason-{t}", placeholder="예: 연준 기사 방향이 원문과 다름")
            if st.button("⛔ 반려 — 오늘 발행하지 않음", use_container_width=True, disabled=not reason.strip()):
                out = graph.resume(t, {"action": "reject", "by": "web", "reason": reason.strip()})
                st.session_state["done"] = out["log"][-2:]
                st.rerun()

# ── 처리 기록 ─────────────────────────────────────────────────────────
with tab_hist:
    path = graph.STORE / "decisions.jsonl"
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()] if path.exists() else []
    if not rows:
        st.info("아직 처리한 호가 없습니다.")
    else:
        st.dataframe([{"호": r["thread"], "답": {"approve": "승인", "reject": "반려"}.get(r["action"], r["action"]),
                       "누가": r.get("by", ""), "언제": r.get("answered_at", ""),
                       "걸린 기사": len(r.get("flags", {})), "고침": len(r.get("edits", {})), "뺌": len(r.get("drop", [])),
                       "사유": r.get("reason", "")} for r in reversed(rows)], use_container_width=True, hide_index=True)
        st.caption("반려·수정 사유는 멈춤 기준을 고칠 재료입니다 (store/decisions.jsonl).")
