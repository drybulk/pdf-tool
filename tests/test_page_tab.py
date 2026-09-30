"""페이지 추출/편집 탭 회귀 테스트: 범위 해석, 불러오기, 드래그(단일/다중/자동 스크롤), 삭제, 저장.
실행: xvfb-run -a python tests/test_page_tab.py
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # 저장소 루트 (pdf_tool.py)
sys.path.insert(0, HERE)                   # tests/helpers.py

from helpers import make_test_pdfs

TMP = tempfile.mkdtemp(prefix="pdf_tool_test_")
BIG, SMALL = make_test_pdfs(TMP)
import tkinter as tk
from tkinter import filedialog, messagebox
import pdf_tool as T
from pypdf import PdfReader

# ---------- 1. 범위 파서 ----------
P = T.parse_page_ranges
assert P("721-732", 800) == list(range(720, 732))
assert P("1-3, 7, 10-11", 20) == [0,1,2,6,9,10]
assert P("5-", 8) == [4,5,6,7]
assert P("-3", 8) == [0,1,2]
assert P("", 4) == [0,1,2,3]
assert P("5,1-2", 8) == [4,0,1]       # 입력 순서 유지
assert P("3~4", 8) == [2,3]
for bad in ["0-3", "7-900", "9-2", "abc", "-", "1-2-3"]:
    try: P(bad, 800 if bad!="7-900" else 800); print("FAIL no error:", bad); sys.exit(1)
    except ValueError as e: pass
print("1. 범위 파서 OK")

# ---------- GUI 준비 ----------
msgs = []
messagebox.showinfo = lambda *a, **k: msgs.append(("info", a))
messagebox.showwarning = lambda *a, **k: msgs.append(("warn", a))
messagebox.showerror = lambda *a, **k: msgs.append(("error", a))

root = tk.Tk(); root.geometry("780x560")
nb = T.ttk.Notebook(root); nb.pack(fill="both", expand=True)
merge = T.MergeTab(nb); page = T.PageTab(nb)
nb.add(merge, text="병합"); nb.add(page, text="추출"); nb.select(page)
root.update()
tree = page.tree

def order():
    return [tree.set(i, "page") for i in tree.get_children()]
def posok():
    return [str(tree.set(i, "pos")) for i in tree.get_children()] == [str(n) for n in range(1, len(tree.get_children())+1)]
def pump(sec=0.0):
    end = time.time()+sec
    root.update()
    while time.time() < end:
        root.update(); time.sleep(0.01)

# ---------- 2. 721-732 불러오기 ----------
filedialog.askopenfilenames = lambda **k: (BIG,)
page.range_var.set("721-732")
page.load_pdfs(); pump()
assert order() == [str(n) for n in range(721, 733)], order()
assert posok()
print("2. 721-732 불러오기 OK:", page.status.get())

def press(item, state=0, dy=0):
    x, y, w, h = tree.bbox(item)
    tree.event_generate("<ButtonPress-1>", x=x+10, y=y+h//2+dy, state=state); root.update()
def motion(y):
    tree.event_generate("<B1-Motion>", x=20, y=y, state=0x100); root.update()
def release(y):
    tree.event_generate("<ButtonRelease-1>", x=20, y=y); root.update()
def rowy(idx):
    x, y, w, h = tree.bbox(tree.get_children()[idx]); return y+h//2

# ---------- 3. 단일 행 드래그: 맨 위(721)를 4번째 행 위치로 ----------
kids = tree.get_children()
press(kids[0]); motion(rowy(1)); motion(rowy(3)); release(rowy(3)); pump(0.1)
assert order()[:5] == ["722","723","724","721","725"], order()
assert posok()
print("3. 단일 행 드래그 OK:", order()[:5])

# ---------- 4. 클릭만 하면 선택만 변경 (순서 불변) ----------
before = order()
kids = tree.get_children()
press(kids[5]); release(rowy(5)); pump(0.05)
assert order() == before and len(tree.selection()) == 1
print("4. 클릭만: 순서 불변 OK")

# ---------- 5. 다중 선택(Ctrl) 후 함께 드래그 ----------
page.clear_all()
page.range_var.set("1-10"); page.load_pdfs(); pump()
kids = tree.get_children()
press(kids[1]); release(rowy(1))
press(kids[2], state=0x4); release(rowy(2))       # Ctrl+클릭
press(kids[6], state=0x4); release(rowy(6))
assert len(tree.selection()) == 3
# 선택된 2,3,7쪽 중 '3쪽'(index 2)을 잡고 index 5까지 끈다
press(tree.get_children()[2]); motion(rowy(4)); motion(rowy(5)); release(rowy(5)); pump(0.1)
print("   다중 드래그 결과:", order())
o = order()
# 2,3,7이 상대 순서(2<3<7)를 유지하며 3칸 아래로 이동했는지 확인
assert o.index("2") < o.index("3") < o.index("7")
assert o.index("3") == 5, o
assert posok() and len(o) == 10
print("5. 다중 선택 드래그 OK")

# ---------- 6. Shift 범위 선택 + 버튼 이동 ----------
page.clear_all(); page.range_var.set("1-10"); page.load_pdfs(); pump()
kids = tree.get_children()
press(kids[2]); release(rowy(2))
press(kids[4], state=0x1); release(rowy(4))
assert [tree.set(i,"page") for i in tree.selection()] == ["3","4","5"]
page.move_to(1); pump()
assert order()[:4] == ["3","4","5","1"], order()
page.move_to(10**9); pump()
assert order()[-3:] == ["3","4","5"], order()
assert posok()
print("6. Shift 선택, 맨 위/맨 아래 OK")

# ---------- 7. 삭제 ----------
page.clear_all(); page.range_var.set("1-10"); page.load_pdfs(); pump()
kids = tree.get_children()
tree.selection_set(kids[0], kids[9]); page.delete_selected(); pump()
assert order() == [str(n) for n in range(2, 10)] and posok() and len(page.pages) == 8
print("7. 삭제 OK:", page.status.get())

# ---------- 8. 800쪽 전체 불러오기 + 자동 스크롤 드래그 ----------
page.clear_all(); page.range_var.set(""); page.load_pdfs(); pump(0.3)
assert len(tree.get_children()) == 800
tree.yview_moveto(0); pump()
kids = tree.get_children()
press(kids[0])                               # 1쪽을 잡고
h = tree.winfo_height()
motion(h + 40)                               # 목록 아래 바깥으로 이동 -> 자동 스크롤
t0 = time.time()
while time.time() - t0 < 15.0:
    pump(0.05)
    if order()[-1] == "1": break
release(h + 40); pump(0.1)
print("   자동 스크롤 경과: %.1f초, 1쪽의 위치: %d" % (time.time()-t0, order().index("1")+1))
assert order()[-1] == "1" and posok()
print("8. 800쪽 자동 스크롤 드래그 OK")

# ---------- 9. 위 방향 자동 스크롤 (800쪽 목록의 맨 아래 -> 위로) ----------
tree.yview_moveto(1.0); pump()
kids = tree.get_children()
last_visible = tree.identify_row(h - 5)
press(last_visible)
grabbed_page = tree.set(last_visible, "page")
motion(-30)
t0 = time.time()
while time.time() - t0 < 12.0:
    pump(0.05)
    if order()[0] == grabbed_page: break
release(-30); pump(0.1)
print("   위쪽 자동 스크롤 경과: %.1f초" % (time.time()-t0))
assert order()[0] == grabbed_page and posok()
print("9. 위쪽 자동 스크롤 OK")

# ---------- 10. 저장 (현재 화면 순서 그대로) ----------
page.clear_all()
page.range_var.set("721-723"); page.load_pdfs(); pump()
filedialog.askopenfilenames = lambda **k: (SMALL,)
page.range_var.set("2, 4-5"); page.load_pdfs(); pump()
print("   현재 목록:", [(tree.set(i,'file'), tree.set(i,'page')) for i in tree.get_children()])
# 마지막 행(S5)을 맨 위로 드래그
kids = tree.get_children()
press(kids[-1]); motion(rowy(0)); release(rowy(0)); pump(0.1)
filedialog.asksaveasfilename = lambda **k: os.path.join(TMP, "result.pdf")
msgs.clear(); page.save()
t0 = time.time()
while not msgs and time.time()-t0 < 10: pump(0.05)
print("   메시지:", msgs)
assert msgs and msgs[0][0] == "info", msgs
texts = [p.extract_text().strip() for p in PdfReader(os.path.join(TMP, "result.pdf")).pages]
print("   저장된 PDF 내용:", texts)
assert texts == ["S5","P721","P722","P723","S2","S4"], texts
print("10. 저장 결과 OK")

# ---------- 11. 잘못된 범위 ----------
msgs.clear(); page.range_var.set("900-950"); page.load_pdfs(); pump()
assert msgs and msgs[0][0] == "warn"
print("11. 잘못된 범위 경고 OK:", msgs[0][1][1])


print("ALL PASSED")
root.destroy()
