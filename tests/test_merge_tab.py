"""PDF 병합 탭 테스트: 파일 추가, 표 표시, 드래그 정렬, 버튼 이동, 삭제, 병합 결과 순서.
실행: xvfb-run -a python tests/test_merge_tab.py
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # 저장소 루트 (pdf_tool.py)
sys.path.insert(0, HERE)                   # tests/helpers.py

from helpers import make_pdf

TMP = tempfile.mkdtemp(prefix="pdf_tool_test_")
FILES = [make_pdf(os.path.join(TMP, f"{c}.pdf"), c, n) for c, n in [("A", 2), ("B", 3), ("C", 1), ("D", 1), ("E", 2)]]
import tkinter as tk
from tkinter import filedialog, messagebox
import pdf_tool as T
from pypdf import PdfReader

msgs = []
messagebox.showinfo = lambda *a, **k: msgs.append(("info", a))
messagebox.showwarning = lambda *a, **k: msgs.append(("warn", a))
messagebox.showerror = lambda *a, **k: msgs.append(("error", a))

root = tk.Tk(); root.geometry("780x560")
nb = T.ttk.Notebook(root); nb.pack(fill="both", expand=True)
merge = T.MergeTab(nb); nb.add(merge, text="병합"); nb.select(merge)
root.update()
tree = merge.tree

def names():
    return [tree.set(i, "name") for i in tree.get_children()]
def posok():
    return [str(tree.set(i, "pos")) for i in tree.get_children()] == [str(n) for n in range(1, len(tree.get_children()) + 1)]
def pump(sec=0.0):
    end = time.time() + sec
    root.update()
    while time.time() < end:
        root.update(); time.sleep(0.01)
def rowy(idx):
    x, y, w, h = tree.bbox(tree.get_children()[idx]); return y + h // 2
def rowtop(idx):
    x, y, w, h = tree.bbox(tree.get_children()[idx]); return y + 2
def press(idx, state=0):
    tree.event_generate("<ButtonPress-1>", x=20, y=rowy(idx), state=state); root.update()
def motion(y):
    tree.event_generate("<B1-Motion>", x=20, y=y, state=0x100); root.update()
def release(y):
    tree.event_generate("<ButtonRelease-1>", x=20, y=y); root.update(); pump(0.05)

# ---------- 1. 파일 추가와 표 표시 ----------
bad = os.path.join(TMP, "bad.pdf")
with open(bad, "w") as f:
    f.write("not a pdf")
filedialog.askopenfilenames = lambda **k: tuple(FILES) + (bad,)
merge.add_files(); pump()
assert names() == ["A.pdf", "B.pdf", "C.pdf", "D.pdf", "E.pdf"] and posok(), names()
first = tree.get_children()[0]
assert str(tree.set(first, "pages")) == "2" and tree.set(first, "folder") == TMP
assert merge.status.get() == "파일 5개, 총 9쪽", merge.status.get()
assert msgs and msgs[0][0] == "warn"                  # 손상 파일은 경고 후 제외
print("1. 파일 추가, 표 표시 OK")

# ---------- 2. 드래그: 단일 행 ----------
press(0); motion(rowy(1)); motion(rowy(2)); release(rowy(2))   # A를 C 뒤로
assert names() == ["B.pdf", "C.pdf", "A.pdf", "D.pdf", "E.pdf"] and posok(), names()
print("2. 단일 행 드래그 OK")

# ---------- 3. 드래그: 떨어진 여러 행을 맨 위로 모으기 ----------
press(1); release(rowy(1))                       # C
press(3, state=0x4); release(rowy(3))            # Ctrl+클릭 D
press(4, state=0x4); release(rowy(4))            # Ctrl+클릭 E
assert len(tree.selection()) == 3
press(3); motion(rowy(2)); motion(rowtop(0)); release(rowtop(0))
assert names() == ["C.pdf", "D.pdf", "E.pdf", "B.pdf", "A.pdf"] and posok(), names()
assert len(tree.selection()) == 3
print("3. 다중 선택 드래그 OK")

# ---------- 4. 버튼 이동과 삭제 ----------
tree.selection_set(tree.get_children()[4])       # A
merge.move_selected(-1)
assert names() == ["C.pdf", "D.pdf", "E.pdf", "A.pdf", "B.pdf"] and posok(), names()
merge.move_selected(-1); merge.move_selected(-1); merge.move_selected(-1)
merge.move_selected(-1)                           # 이미 맨 위: 변화 없음
assert names()[0] == "A.pdf" and posok()
tree.selection_set(tree.get_children()[1])       # C
merge.remove_selected()
assert names() == ["A.pdf", "D.pdf", "E.pdf", "B.pdf"] and posok(), names()
assert merge.status.get() == "파일 4개, 총 8쪽", merge.status.get()
print("4. 버튼 이동, 삭제 OK")

# ---------- 5. 병합 결과가 화면 순서와 일치 ----------
out = os.path.join(TMP, "merged.pdf")
filedialog.asksaveasfilename = lambda **k: out
msgs.clear(); merge.start_merge()
t0 = time.time()
while not msgs and time.time() - t0 < 10:
    pump(0.05)
assert msgs and msgs[0][0] == "info", msgs
texts = [p.extract_text().strip() for p in PdfReader(out).pages]
assert texts == ["A1", "A2", "D1", "E1", "E2", "B1", "B2", "B3"], texts
assert [o.title for o in PdfReader(out).outline] == ["A", "D", "E", "B"]
print("5. 병합 결과 순서 OK:", texts)

# ---------- 6. 목록 비우기 ----------
merge.clear_all()
assert names() == [] and merge.files == {} and merge.status.get() == "파일 0개, 총 0쪽"
msgs.clear(); merge.start_merge()
assert msgs and msgs[0][0] == "info"             # 2개 미만 안내
print("6. 비우기 OK")

print("ALL MERGE TAB TESTS PASSED")
root.destroy()
