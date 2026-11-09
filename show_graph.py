"""지금 코드의 LangGraph 워크플로를 그림으로 본다.

  .venv\\Scripts\\python.exe show_graph.py

graph.py 에서 실제로 컴파일한 그래프의 연결(노드·엣지)을 Mermaid 글로 뽑아 docs/graph.html 로 저장하고 브라우저로 연다.
그림은 브라우저가 내 컴퓨터에서 그린다(그래프 내용을 바깥 서비스로 보내지 않음).
실선 화살표 = 항상 가는 길, 점선 화살표 = 조건에 따라 고르는 길(조건부 엣지).
"""
import webbrowser
from pathlib import Path

import graph

ROOT = Path(__file__).resolve().parent
mermaid = graph.app().get_graph().draw_mermaid()
(ROOT / "docs" / "graph.mmd").write_text(mermaid, encoding="utf-8")

html = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>장전 브리핑 HITL 워크플로</title>
<style>body{{font-family:'Malgun Gothic',sans-serif;margin:24px;background:#fff;color:#222}} .note{{color:#555;font-size:14px}}</style></head>
<body><h2>장전 브리핑 HITL — LangGraph 워크플로</h2>
<p class="note">graph.py 에서 실제로 컴파일한 그래프입니다. 실선 = 항상 가는 길, 점선 = 조건에 따라 고르는 길.<br>
gate → review(사람 승인 대기, interrupt로 멈춤) → publish(발행) 또는 rejected(반려)</p>
<pre class="mermaid">{mermaid}</pre>
<script type="module">import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.esm.min.mjs"; mermaid.initialize({{startOnLoad:true}});</script>
</body></html>"""
out = ROOT / "docs" / "graph.html"
out.write_text(html, encoding="utf-8")
print(f"저장: {out}")
webbrowser.open(out.as_uri())
