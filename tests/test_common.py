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

# ---------- 4-1. 놓을 위치 표시선과 모으기 ----------
def drag(src_idx, path_ys, state=0):
    x, y, w, h = tree.bbox(tree.get_children()[src_idx])
    tree.event_generate("<ButtonPress-1>", x=x + 10, y=y + h // 2, state=state); root.update()
    for yy in path_ys:
        tree.event_generate("<B1-Motion>", x=20, y=yy, state=0x100); root.update()
def drop(yy):
    tree.event_generate("<ButtonRelease-1>", x=20, y=yy); root.update(); pump(0.05)
def rowtop(idx):
    x, y, w, h = tree.bbox(tree.get_children()[idx]); return y + 2
def rowbottom(idx):
    x, y, w, h = tree.bbox(tree.get_children()[idx]); return y + h - 2

# 행의 위쪽 절반은 그 행 앞, 아래쪽 절반은 그 행 뒤
assert tree._drop_slot(rowtop(3)) == 3 and tree._drop_slot(rowbottom(3)) == 4

# 끄는 동안에는 순서가 바뀌지 않고 표시선만 나타남. 표시선은 3번째 행의 위쪽 경계에 있음
start = order()
drag(0, [rowy(1), rowtop(3)])
assert order() == start and tree._indicator.winfo_ismapped()
root.update_idletasks()
x3, y3, w3, h3 = tree.bbox(tree.get_children()[3])
assert abs(tree._indicator.winfo_y() + 1 - y3) <= 1, (tree._indicator.winfo_y(), y3)
drop(rowtop(3))
assert not tree._indicator.winfo_ismapped()
assert order() == start[1:3] + start[:1] + start[3:] and posok(), order()

# 떨어진 행 여러 개(1, 3, 5번째 행)를 선택해 맨 위(첫 행의 위쪽 절반)에 놓으면 한곳에 모임
reorders.clear()
kids = tree.get_children()
picked = [tree.set(kids[i], "name") for i in (1, 3, 5)]
tree.selection_set(kids[1], kids[3], kids[5])
drag(3, [rowy(2), rowy(1), rowtop(0)])
drop(rowtop(0))
assert order()[:3] == picked and posok(), order()
assert len(reorders) == 1

# 잡은 행 위에서 놓거나 같은 자리에 놓으면 순서가 바뀌지 않고 기록도 없음
reorders.clear()
start = order()
tree.selection_set(tree.get_children()[0], tree.get_children()[1], tree.get_children()[2])
drag(1, [rowy(3), rowbottom(2)])                               # 선택한 묶음의 바로 뒤
drop(rowbottom(2))
assert order() == start and reorders == []
print("4-1. 표시선, 모으기 OK")

# ---------- 4-2. 옮긴 행 강조와 화면 표시 ----------
style = C.ttk.Style(root)
def sel_bg():
    return style.lookup(tree.style_name, "background", ["selected"])
pump(C.DragTree.FLASH_MS / 1000 + 0.3)                         # 4-1에서 옮긴 직후의 강조가 끝날 때까지 대기
assert sel_bg() == C.DragTree.SELECT_BG
tree.selection_set(tree.get_children()[0])
assert tree.shift_selection(1)
assert sel_bg() == C.DragTree.FLASH_BG                         # 옮긴 직후 강조색
pump(C.DragTree.FLASH_MS / 1000 + 0.3)
assert sel_bg() == C.DragTree.SELECT_BG                        # 잠시 뒤 원래 선택 색
# 강조색은 위젯마다 따로 바뀜
other = C.DragTree(root, columns=("pos",), show="headings")
assert other.style_name != tree.style_name
tree.flash_selection()
assert style.lookup(other.style_name, "background", ["selected"]) == C.DragTree.SELECT_BG
pump(C.DragTree.FLASH_MS / 1000 + 0.3)
other.destroy()

# 화면 밖으로 옮긴 행이 보이도록 스크롤됨
for n in range(7, 61):
    tree.insert("", "end", values=(0, f"r{n}"))
tree.renumber(); tree.yview_moveto(0); pump()
tree.selection_set(tree.get_children()[0])
assert tree.move_selection_to(10**9)
pump()
assert tree.bbox(tree.get_children()[-1]) and tree.yview()[0] > 0
assert not tree.move_selection_to(10**9)                      # 이미 맨 아래: 변화 없음
print("4-2. 강조색, 화면 표시 OK")

# ---------- 5. 경량판은 공통 모듈의 객체를 그대로 사용한다 ----------
import pdf_tool as T
for name in ("IS_MAC", "UNDO_LIMIT", "DragTree", "PageTab",
             "open_pdf", "outline_entries", "parse_page_ranges", "merge_pdfs", "save_pages", "run_background"):
    assert getattr(T, name) is getattr(C, name), name
print("5. pdf_tool의 공통 이름 연결 OK")

# ---------- 6. 창 아이콘: assets/icon.png를 읽어 창에 붙이고, 파일이 없으면 기본 아이콘을 둠 ----------
icon = C.set_window_icon(root)
assert icon is not None and (icon.width(), icon.height()) == (256, 256) and root._app_icon is icon
assert os.path.isfile(C.resource_path("assets", "icon.ico"))
original_resource_path = C.resource_path
C.resource_path = lambda *parts: os.path.join(tempfile.gettempdir(), "없는_폴더", *parts)
try:
    top = tk.Toplevel(root)
    assert C.set_window_icon(top) is None and not hasattr(top, "_app_icon")
    top.destroy()
finally:
    C.resource_path = original_resource_path
print("6. 창 아이콘 OK")

print("ALL COMMON TESTS PASSED")
root.destroy()
