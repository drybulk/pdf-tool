"""공통 모듈(pdf_common.py) 단독 테스트: pdf_tool.py 없이 가져와서 처리 로직, 백그라운드 실행, DragTree를 검사합니다.
실행: xvfb-run -a python tests/test_common.py
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # 저장소 루트 (pdf_common.py)
sys.path.insert(0, HERE)                   # tests/helpers.py

from helpers import make_pdf
from pypdf import PdfReader

import pdf_common as C

# ---------- 1. 공통 모듈은 경량판 GUI 없이 가져올 수 있다 ----------
assert "pdf_tool" not in sys.modules
print("1. pdf_tool 없이 가져오기 OK")

tmp = tempfile.mkdtemp(prefix="pdf_common_test_")
a = make_pdf(os.path.join(tmp, "a.pdf"), "A", 3)
b = make_pdf(os.path.join(tmp, "b.pdf"), "B", 2)
out = os.path.join(tmp, "out.pdf")

def texts(path):
    return [p.extract_text().strip() for p in PdfReader(path).pages]

# ---------- 2. 처리 로직 ----------
assert C.parse_page_ranges("2-3, 1", 3) == [1, 2, 0]
assert len(C.open_pdf(a).pages) == 3
calls = []
assert C.merge_pdfs([b, a], out, add_bookmarks=False, progress=lambda c, t: calls.append((c, t))) == 5
assert texts(out) == ["B1", "B2", "A1", "A2", "A3"] and calls == [(1, 2), (2, 2)], (texts(out), calls)
readers = {}
assert C.save_pages([(a, 2), (b, 0)], out, readers=readers) == 2
assert texts(out) == ["A3", "B1"] and set(readers) == {a, b}   # 읽은 PdfReader가 캐시에 보관됨
print("2. 처리 로직 OK")

# ---------- GUI 준비 ----------
import tkinter as tk
root = tk.Tk(); root.geometry("400x300")

def pump(sec=0.0):
    end = time.time() + sec
    root.update()
    while time.time() < end:
        root.update(); time.sleep(0.01)

def wait(cond, limit=5.0):
    t0 = time.time()
    while not cond() and time.time() - t0 < limit:
        pump(0.02)
    return cond()

# ---------- 3. run_background: 진행률, 완료, 오류 전달 ----------
events = []
def work(report):
    for i in range(1, 5):
        report(i, 4)
    return "결과"
C.run_background(root, work, on_progress=lambda v: events.append(("p", v)),
                 on_done=lambda r: events.append(("done", r)), on_error=lambda m: events.append(("err", m)))
assert wait(lambda: events and events[-1][0] == "done")
assert events == [("p", 25.0), ("p", 50.0), ("p", 75.0), ("p", 100.0), ("done", "결과")], events

events.clear()
def fail(report):
    raise ValueError("의도한 오류")
C.run_background(root, fail, on_progress=lambda v: events.append(("p", v)),
                 on_done=lambda r: events.append(("done", r)), on_error=lambda m: events.append(("err", m)))
assert wait(lambda: events)
assert events == [("err", "의도한 오류")], events
print("3. run_background OK")

# ---------- 4. DragTree 단독 사용 ----------
reorders = []
tree = C.DragTree(root, on_reorder=reorders.append, columns=("pos", "name"), show="headings")
tree.pack(fill="both", expand=True)
for n in range(1, 7):
    tree.insert("", "end", values=(0, f"r{n}"))
tree.renumber()
pump()

def order():
    return [tree.set(i, "name") for i in tree.get_children()]
def posok():
    return [str(tree.set(i, "pos")) for i in tree.get_children()] == [str(n) for n in range(1, len(tree.get_children()) + 1)]
def rowy(idx):
    x, y, w, h = tree.bbox(tree.get_children()[idx]); return y + h // 2

# 버튼용 이동 기능
kids = tree.get_children()
tree.selection_set(kids[1], kids[2])
assert tree.shift_selection(1) and order() == ["r1", "r4", "r2", "r3", "r5", "r6"] and posok()
tree.selection_set(tree.get_children()[0])
assert not tree.shift_selection(-1)                            # 맨 위에서는 이동하지 않음
tree.selection_set(tree.get_children()[5])
tree.move_selection_to(1)
assert order() == ["r6", "r1", "r4", "r2", "r3", "r5"] and posok()
assert reorders == []                                          # 버튼용 기능은 on_reorder를 호출하지 않음

# 마우스 드래그: 맨 위 행을 3번째 위치로
before = tree.get_children()
x, y, w, h = tree.bbox(before[0])
tree.event_generate("<ButtonPress-1>", x=x + 10, y=y + h // 2); root.update()
tree.event_generate("<B1-Motion>", x=20, y=rowy(1), state=0x100); root.update()
tree.event_generate("<B1-Motion>", x=20, y=rowy(2), state=0x100); root.update()
tree.event_generate("<ButtonRelease-1>", x=20, y=rowy(2)); root.update()
pump(0.05)
assert order() == ["r1", "r4", "r6", "r2", "r3", "r5"] and posok(), order()
assert reorders == [before], reorders                          # 드래그 전 행 순서가 전달됨
print("4. DragTree OK")

# ---------- 5. 경량판은 공통 모듈의 객체를 그대로 사용한다 ----------
import pdf_tool as T
for name in ("IS_MAC", "DragTree", "open_pdf", "parse_page_ranges", "merge_pdfs", "save_pages", "run_background"):
    assert getattr(T, name) is getattr(C, name), name
print("5. pdf_tool의 공통 이름 연결 OK")

print("ALL COMMON TESTS PASSED")
root.destroy()
