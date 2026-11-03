"""렌더링판의 이미지 저장 테스트: PNG/JPG 변환, 파일 이름 규칙, 저장 옵션 대화 상자, 저장 과정과 오류 처리.
실행: xvfb-run -a python tests/test_image_export.py   (pip install -r requirements-render.txt 필요)
"""
import io
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # 저장소 루트
sys.path.insert(0, HERE)                   # tests/helpers.py

import importlib.util
for mod in ("pypdfium2", "PIL"):
    if importlib.util.find_spec(mod) is None:
        raise SystemExit(f"{mod}가 설치되어 있지 않습니다: pip install -r requirements-render.txt")

from helpers import make_pdf
from PIL import Image
from reportlab.pdfgen import canvas

import pdf_render as PR

TMP = tempfile.mkdtemp(prefix="pdf_tool_test_")

# ---------- 1. RGB 변환: 행 간격(stride)이 너비x3보다 큰 경우 행 단위로 잘라 냄 ----------
data = bytes([1, 2, 3, 4, 5, 6, 99, 99,  7, 8, 9, 10, 11, 12, 99, 99])  # 너비 2, 높이 2, stride 8
assert PR.bitmap_to_rgb(2, 2, 8, data) == bytes(range(1, 13))
assert PR.bitmap_to_ppm(2, 2, 8, data) == b"P6 2 2 255\n" + bytes(range(1, 13))
print("1. RGB 변환 OK")

# ---------- 2. PNG, JPG 변환: Pillow로 다시 읽어서 크기, 픽셀, 해상도 정보 확인 ----------
w, h = 3, 2
rgb = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 10, 20, 30, 40, 50, 60, 200, 210, 220])
png = PR.encode_png(w, h, rgb, dpi=150)
img = Image.open(io.BytesIO(png))
assert img.format == "PNG" and img.mode == "RGB" and img.size == (w, h)
assert img.tobytes() == rgb                                       # 손실 없는 형식이므로 픽셀이 그대로
assert round(img.info["dpi"][0]) == 150, img.info.get("dpi")
assert "dpi" not in Image.open(io.BytesIO(PR.encode_png(w, h, rgb))).info  # dpi를 주지 않으면 기록하지 않음
for level in (1, 9):
    assert Image.open(io.BytesIO(PR.encode_png(w, h, rgb, level=level))).tobytes() == rgb
gray = bytes([128]) * (40 * 30 * 3)
jpg = PR.encode_jpg(40, 30, gray, dpi=300, quality=90)
img = Image.open(io.BytesIO(jpg))
assert img.format == "JPEG" and img.size == (40, 30) and round(img.info["dpi"][0]) == 300
assert all(abs(v - 128) <= 2 for v in img.getpixel((20, 15)))      # 단색은 거의 그대로
small = len(PR.encode_jpg(40, 30, os.urandom(40 * 30 * 3), quality=10))
large = len(PR.encode_jpg(40, 30, os.urandom(40 * 30 * 3), quality=95))
assert small < large, (small, large)                              # 품질이 높을수록 파일이 큼
print("2. PNG, JPG 변환 OK")

# ---------- 3. 파일 이름 규칙 ----------
names = PR.image_file_names(
    [("/a/report.pdf", 720), ("/a/report.pdf", 0), ("/a/report.pdf", 720), ("/b/report.pdf", 720),
     ("/b/REPORT.pdf", 720), ("/a/big.pdf", 12344)],
    "png",
)
assert names == [
    "report_p0721.png", "report_p0001.png", "report_p0721_2.png", "report_p0721_3.png",
    "REPORT_p0721_4.png",                       # Windows는 대소문자를 구분하지 않으므로 같은 이름으로 취급
    "big_p12345.png",                           # 4자리를 넘는 쪽 번호는 그대로
], names
print("3. 파일 이름 규칙 OK")

# ---------- GUI 준비 ----------
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pdf_tool_render as R

msgs = []
messagebox.showinfo = lambda *a, **k: msgs.append(("info", a))
messagebox.showwarning = lambda *a, **k: msgs.append(("warn", a))
messagebox.showerror = lambda *a, **k: msgs.append(("error", a))
answers = []  # askyesno가 돌려줄 값
asked = []
def fake_askyesno(*a, **k):
    asked.append(a)
    return answers.pop(0)
messagebox.askyesno = fake_askyesno

# 쪽마다 색이 다른 A4 PDF (빨강, 초록, 파랑)
COLORS = [(1, 0, 0), (0, 1, 0), (0, 0, 1)]
SRC = os.path.join(TMP, "색상.pdf")
c = canvas.Canvas(SRC, pagesize=(595, 842))
for col in COLORS:
    c.setFillColorRGB(*col); c.rect(0, 0, 595, 842, fill=1, stroke=0); c.showPage()
c.save()

root = tk.Tk(); root.geometry("1200x750")
nb = ttk.Notebook(root); nb.pack(fill="both", expand=True)
page = R.RenderPageTab(nb)
nb.add(page, text="추출"); nb.select(page)
tree = page.tree

def pump(sec=0.0):
    end = time.time() + sec
    root.update()
    while time.time() < end:
        root.update(); time.sleep(0.01)
def load(rng, path=SRC):
    filedialog.askopenfilenames = lambda **k: (path,)
    page.range_var.set(rng); page.load_pdfs(); pump(0.3)
def wait_done(timeout=20):
    t0 = time.time()
    while not msgs and time.time() - t0 < timeout:
        pump(0.05)
    assert msgs, "저장이 끝나지 않았습니다"
    return msgs[-1]
def center(path):
    with Image.open(path) as im:
        return im.size, im.getpixel((im.width // 2, im.height // 2)), im.format
pump(0.5)

# ---------- 4. 버튼 배치: "새 PDF로 저장"의 왼쪽, 같은 아래쪽 영역 ----------
assert page.image_btn.master is page.save_btn.master
assert page.image_btn.winfo_rootx() < page.save_btn.winfo_rootx()
assert abs(page.image_btn.winfo_rooty() - page.save_btn.winfo_rooty()) < 5
msgs.clear(); page.save_images()
assert msgs and msgs[0][0] == "info"                               # 쪽이 없으면 안내만 함
print("4. 버튼 배치 OK")

# ---------- 5. 대화 상자: 기본값, 선택이 없을 때, 품질 입력 검사, 취소 ----------
load("")
def run_dialog(action, n_selected, n_all):
    out = {}
    def drive():
        d = page._image_dialog
        out["dialog"] = d
        d.update_idletasks()
        out["pos"] = (d.winfo_rootx() + d.winfo_width() // 2, d.winfo_rooty() + d.winfo_height() // 2)
        out["state"] = {
            "scope": d.scope_var.get(), "format": d.format_var.get(), "dpi": d.dpi_var.get(),
            "quality": d.quality_var.get(), "quality_disabled": d.quality_box.instate(["disabled"]),
        }
        try:
            action(d)
        except BaseException as e:
            out["error"] = e
            d.destroy()  # 검사가 실패해도 대화 상자를 닫아서 테스트가 멈추지 않게 함
    root.after(200, drive)
    out["result"] = page.ask_image_options(n_selected, n_all)
    if "error" in out:
        raise out["error"]
    return out

out = run_dialog(lambda d: d.ok(), 0, 3)
assert out["state"] == {"scope": "all", "format": "PNG", "dpi": "150", "quality": "90", "quality_disabled": True}, out["state"]
assert out["result"] == {"scope": "all", "format": "PNG", "dpi": 150, "quality": 90}, out["result"]

# 대화 상자는 본 창의 가운데에 뜸
dx, dy = out["pos"]
cx = root.winfo_rootx() + root.winfo_width() // 2
cy = root.winfo_rooty() + root.winfo_height() // 2
# geometry("+x+y")는 창 테두리와 제목 표시줄을 포함한 바깥 모서리의 위치이고, winfo_rootx/rooty는 그 안쪽 내용
# 영역의 위치입니다. 그래서 창 관리자가 테두리를 그리는 Windows에서는 대화 상자의 내용이 계산한 위치보다
# 오른쪽 아래로 밀립니다(Windows 11, 배율 100%에서 9, 37픽셀). 화면 배율이 크면 더 커질 수 있으므로 80픽셀까지
# 허용합니다. 이전처럼 화면 왼쪽 위에 뜨면 1200x750 창 기준으로 수백 픽셀 차이가 나므로 구분됩니다.
assert abs(dx - cx) < 80 and abs(dy - cy) < 80, (out["pos"], (cx, cy))

out = run_dialog(lambda d: d.ok(), 2, 3)
assert out["state"]["scope"] == "selected"                         # 선택한 쪽이 있으면 기본값은 "선택한 쪽"

def jpg_bad_quality(d):
    d.format_var.set("JPG"); d._update_quality()
    assert not d.quality_box.instate(["disabled"])
    d.quality_var.set("0"); d.ok()                                 # 범위를 벗어난 값은 경고하고 창을 유지
    assert d.winfo_exists() and msgs and msgs[-1][0] == "warn"
    d.quality_var.set("75"); d.dpi_var.set("300"); d.ok()
msgs.clear()
out = run_dialog(jpg_bad_quality, 1, 3)
assert out["result"] == {"scope": "selected", "format": "JPG", "dpi": 300, "quality": 75}, out["result"]

out = run_dialog(lambda d: d.cancel(), 1, 3)
assert out["result"] is None
def press_escape(d):
    d.focus_force(); d.update()                                    # Xvfb에는 창 관리자가 없으므로 포커스를 직접 줌
    d.event_generate("<Escape>")
out = run_dialog(press_escape, 1, 3)
assert out["result"] is None

R.HAS_PILLOW = False                                               # Pillow가 없으면 JPG를 고를 수 없음
def check_no_pillow(d):
    assert d.jpg_button.instate(["disabled"])
    d.cancel()
run_dialog(check_no_pillow, 0, 3)
R.HAS_PILLOW = True
print("5. 저장 옵션 대화 상자 OK")

# ---------- 6. 선택한 쪽을 PNG로 저장: 화면 순서, 파일 이름, 크기, 색 ----------
OUT = os.path.join(TMP, "out"); os.makedirs(OUT)
filedialog.askdirectory = lambda **k: OUT
kids = tree.get_children()
tree.selection_set((kids[2], kids[0]))
page.ask_image_options = lambda n_sel, n_all: {"scope": "selected", "format": "PNG", "dpi": 72, "quality": 90}
msgs.clear(); page.save_images()
assert page.busy and page.image_btn.instate(["disabled"]) and page.save_btn.instate(["disabled"])
kind, args = wait_done()
assert kind == "info" and "2개" in args[1], (kind, args)
assert not page.busy and not page.image_btn.instate(["disabled"])
assert sorted(os.listdir(OUT)) == ["색상_p0001.png", "색상_p0003.png"], os.listdir(OUT)
size, px, fmt = center(os.path.join(OUT, "색상_p0001.png"))
assert size == (595, 842) and px == (255, 0, 0) and fmt == "PNG", (size, px, fmt)   # 72 DPI = 배율 1
size, px, fmt = center(os.path.join(OUT, "색상_p0003.png"))
assert px == (0, 0, 255)
print("6. 선택한 쪽 PNG 저장 OK")

# ---------- 7. 목록 전체를 JPG로 저장, 해상도 반영 ----------
OUT2 = os.path.join(TMP, "out2"); os.makedirs(OUT2)
filedialog.askdirectory = lambda **k: OUT2
page.ask_image_options = lambda n_sel, n_all: {"scope": "all", "format": "JPG", "dpi": 150, "quality": 85}
msgs.clear(); page.save_images()
kind, args = wait_done()
assert kind == "info" and "3개" in args[1], (kind, args)
assert sorted(os.listdir(OUT2)) == ["색상_p0001.jpg", "색상_p0002.jpg", "색상_p0003.jpg"]
size, px, fmt = center(os.path.join(OUT2, "색상_p0002.jpg"))
assert fmt == "JPEG" and abs(size[0] - 595 * 150 / 72) < 1 and abs(size[1] - 842 * 150 / 72) < 1, size
assert px[1] > 240 and px[0] < 15 and px[2] < 15, px                                    # 초록
print("7. 목록 전체 JPG 저장 OK")

# ---------- 8. 같은 이름의 파일이 있으면 덮어쓸지 한 번 물음 ----------
target = os.path.join(OUT2, "색상_p0001.jpg")
with open(target, "wb") as f:
    f.write(b"old")
asked.clear(); answers[:] = [False]; msgs.clear()
page.save_images(); pump(0.3)
assert len(asked) == 1 and "3개" in asked[0][1] and not msgs and not page.busy     # 아니요: 저장하지 않음
assert open(target, "rb").read() == b"old"
answers[:] = [True]
page.save_images(); wait_done()
assert len(asked) == 2 and center(target)[2] == "JPEG"                             # 예: 덮어씀
print("8. 덮어쓰기 확인 OK")

# ---------- 9. 같은 쪽이 두 번 있으면 _2를 붙임, 저장 순서는 화면 순서 ----------
OUT3 = os.path.join(TMP, "out3"); os.makedirs(OUT3)
filedialog.askdirectory = lambda **k: OUT3
load("1")                                                          # 1쪽을 한 번 더 불러와 4행이 됨
assert len(tree.get_children()) == 4
page.ask_image_options = lambda n_sel, n_all: {"scope": "all", "format": "PNG", "dpi": 72, "quality": 90}
msgs.clear(); page.save_images(); wait_done()
assert sorted(os.listdir(OUT3)) == ["색상_p0001.png", "색상_p0001_2.png", "색상_p0002.png", "색상_p0003.png"]
assert center(os.path.join(OUT3, "색상_p0001_2.png"))[1] == (255, 0, 0)
# 대화 상자가 열린 동안 실행 취소로 행이 바뀌어도, 대화 상자를 열 때의 쪽 목록으로 저장함
OUT3b = os.path.join(TMP, "out3b"); os.makedirs(OUT3b)
filedialog.askdirectory = lambda **k: OUT3b
def undo_then_ok(n_sel, n_all):
    page.undo(); root.update()                                     # "1쪽 한 번 더 불러오기"를 취소해서 행 ID가 바뀜
    return {"scope": "all", "format": "PNG", "dpi": 72, "quality": 90}
page.ask_image_options = undo_then_ok
msgs.clear(); page.save_images(); kind, args = wait_done()
assert kind == "info" and len(tree.get_children()) == 3, (kind, args)
assert len(os.listdir(OUT3b)) == 4
page.ask_image_options = lambda n_sel, n_all: {"scope": "all", "format": "PNG", "dpi": 72, "quality": 90}
print("9. 같은 쪽 두 번 저장 OK")

# ---------- 10. 오류 처리: 그리지 못한 쪽, 쓸 수 없는 폴더 ----------
OUT4 = os.path.join(TMP, "out4"); os.makedirs(OUT4)
filedialog.askdirectory = lambda **k: OUT4
real_render = page.docs.render_rgb
def flaky(path, index, scale):
    if index == 1:
        raise ValueError("시험용 렌더링 실패")
    return real_render(path, index, scale)
page.docs.render_rgb = flaky
msgs.clear(); page.save_images()
kind, args = wait_done()
assert kind == "error" and "2쪽을 그릴 수 없습니다" in args[1], args
assert not page.busy and not page.image_btn.instate(["disabled"]) and not page.save_btn.instate(["disabled"])
page.docs.render_rgb = real_render
time.sleep(0.3)
assert "색상_p0002.png" not in os.listdir(OUT4)

# 앞 쪽을 변환하는 도중에 다음 쪽 렌더링이 실패하면, 변환 중인 파일이 다 쓰인 뒤에 결과를 알림
OUT4b = os.path.join(TMP, "out4b"); os.makedirs(OUT4b)
filedialog.askdirectory = lambda **k: OUT4b
real_png = R.encode_png
def slow_png(*a, **k):
    time.sleep(0.5)
    return real_png(*a, **k)
R.encode_png = slow_png
page.docs.render_rgb = flaky
msgs.clear(); page.save_images()
kind, args = wait_done()
assert kind == "error" and "저장한 이미지: 1개" in args[1], args
assert os.listdir(OUT4b) == ["색상_p0001.png"] and not page.busy              # 알림 시점에 이미 파일이 있음
R.encode_png = real_png
page.docs.render_rgb = real_render

filedialog.askdirectory = lambda **k: os.path.join(TMP, "없는폴더")   # 파일을 쓸 수 없는 경우
msgs.clear(); page.save_images()
kind, args = wait_done()
assert kind == "error" and "저장한 이미지: 0개" in args[1], args
assert not page.busy
print("10. 오류 처리 OK")

# ---------- 11. 저장 중에도 화면이 반응함 (300 DPI, 여러 쪽) ----------
MANY = make_pdf(os.path.join(TMP, "many.pdf"), "M", 12)
OUT5 = os.path.join(TMP, "out5"); os.makedirs(OUT5)
filedialog.askdirectory = lambda **k: OUT5
page.clear_all(); load("", MANY)
page.ask_image_options = lambda n_sel, n_all: {"scope": "all", "format": "PNG", "dpi": 300, "quality": 90}
ticks = []
def tick():
    ticks.append(time.perf_counter())
    if not msgs:
        root.after(10, tick)
msgs.clear(); page.save_images(); tick()
values = []
t0 = time.time()
while not msgs and time.time() - t0 < 60:
    root.update(); values.append(page.progress["value"]); time.sleep(0.005)
assert msgs and msgs[-1][0] == "info", msgs
assert len(os.listdir(OUT5)) == 12
gaps = [b - a for a, b in zip(ticks, ticks[1:])]
assert max(gaps) < 0.5, max(gaps)                                  # 한 번에 오래 멈추지 않음
assert any(0 < v < 100 for v in values) and values == sorted(values)  # 진행률이 중간값을 거쳐 늘어남
print(f"11. 저장 중 화면 반응 OK (12쪽 300 DPI, 가장 긴 멈춤 {max(gaps) * 1000:.0f}ms)")

# ---------- 12. 변환 스레드에서 가비지 컬렉션이 일어나도 Tk를 호출하지 않음 ----------
# 닫은 대화 상자처럼 순환 참조로 남은 StringVar가 변환 스레드에서 정리되면 Variable.__del__이 그 스레드에서
# Tk를 호출합니다. update()로만 화면을 갱신하는 동안에는 변수 하나마다 약 1초 기다린 뒤 RuntimeError가 나서,
# 드물게 저장이 20초 안에 끝나지 않았습니다. export_images가 시작할 때 메인 스레드에서 먼저 정리하는지 확인합니다.
import gc
class Cyclic:
    def __init__(self):
        self.me = self
        self.vars = [tk.StringVar(master=root, value="x") for _ in range(5)]
OUT6 = os.path.join(TMP, "out6"); os.makedirs(OUT6)
filedialog.askdirectory = lambda **k: OUT6
page.clear_all(); load("1-2")
page.ask_image_options = lambda n_sel, n_all: {"scope": "all", "format": "PNG", "dpi": 72, "quality": 90}
unraisable = []
old_hook, sys.unraisablehook = sys.unraisablehook, lambda u: unraisable.append(u.exc_value)
real_png = R.encode_png
def png_with_gc(*a, **k):
    gc.collect()                                                   # 변환 스레드에서 가비지 컬렉션
    return real_png(*a, **k)
R.encode_png = png_with_gc
gc.disable()                                                       # 시험 도중 메인 스레드에서 미리 정리되지 않게 함
try:
    Cyclic()
    msgs.clear(); t0 = time.time(); page.save_images()
    kind, _ = wait_done()
    elapsed = time.time() - t0
finally:
    gc.enable(); R.encode_png = real_png; sys.unraisablehook = old_hook
assert kind == "info" and len(os.listdir(OUT6)) == 2, (kind, os.listdir(OUT6))
assert not unraisable, unraisable
assert elapsed < 3, elapsed
print(f"12. 변환 스레드의 가비지 컬렉션 OK ({elapsed:.2f}초)")

print("ALL IMAGE EXPORT TESTS PASSED")
root.destroy()
