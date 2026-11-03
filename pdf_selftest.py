"""
실행 파일(exe)로 묶은 렌더링판이 필요한 구성 요소를 모두 갖추었는지 확인하는 자체 검사입니다.

    pdf-tool.exe --selftest 결과파일.txt

창 없이 실행하는 실행 파일에는 콘솔 출력이 없으므로 결과를 파일에 씁니다. 모든 검사를 통과하면
종료 코드 0, 하나라도 실패하면 1로 끝납니다. 빌드 스크립트(tools/build_exe.py)와 GitHub Actions가
이 검사로 PDFium, Pillow, Tcl/Tk가 실행 파일에 제대로 들어갔는지 확인합니다.
검사는 임시 폴더에서만 파일을 만들고 지웁니다.
"""

import importlib.metadata
import os
import platform
import sys
import tempfile
import traceback


def _make_pdf(path):
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_blank_page(width=842, height=595)
    with open(path, "wb") as f:
        writer.write(f)


def _make_images(folder):
    from PIL import Image

    paths = []
    im = Image.new("RGB", (40, 30), (200, 30, 30))
    for ext in ("png", "jpg"):
        path = os.path.join(folder, f"image.{ext}")
        im.save(path)
        paths.append(path)
    return paths


def run(result_path):
    lines = [f"Python {platform.python_version()} ({sys.platform}, frozen={getattr(sys, 'frozen', False)})"]
    ok = True

    def check(name, func):
        nonlocal ok
        try:
            detail = func()
            lines.append(f"OK   {name}" + (f": {detail}" if detail else ""))
        except Exception:
            ok = False
            lines.append(f"FAIL {name}")
            lines.extend("     " + s for s in traceback.format_exc().rstrip().splitlines())

    with tempfile.TemporaryDirectory() as folder:
        pdf_path = os.path.join(folder, "sample.pdf")
        state = {}

        def versions():
            from pdf_tool_render import RenderPageTab
            return ", ".join(f"{n} {importlib.metadata.version(n)}" for n in RenderPageTab.LIBRARIES)

        def make_files():
            _make_pdf(pdf_path)
            state["images"] = _make_images(folder)
            return f"PDF 2쪽, 이미지 {len(state['images'])}개"

        def load():
            from pdf_common import image_to_pdf, open_source
            counts = [len(open_source(p).pages) for p in [pdf_path] + state["images"]]
            state["image_pdfs"] = {p: image_to_pdf(p) for p in state["images"]}
            return "쪽 수 " + ", ".join(map(str, counts))

        def render():
            from pdf_render import PdfiumDocs, encode_jpg, encode_png, thumb_scale
            docs = PdfiumDocs(source=lambda p: state["image_pdfs"].get(p, p))
            try:
                sizes = []
                for path in [pdf_path] + state["images"]:
                    w, h = docs.page_size(path, 0)
                    tw, th, _ = docs.render_ppm(path, 0, thumb_scale(w, h))
                    sizes.append(f"{tw}x{th}")
                rw, rh, rgb = docs.render_rgb(pdf_path, 0, 72 / 72)
                png = encode_png(rw, rh, rgb, dpi=72)
                jpg = encode_jpg(rw, rh, rgb, dpi=72)
                if not png.startswith(b"\x89PNG") or not jpg.startswith(b"\xff\xd8"):
                    raise ValueError("PNG/JPG 변환 결과가 올바르지 않습니다.")
            finally:
                docs.close_all()
            return "썸네일 " + ", ".join(sizes) + f", PNG {len(png)}B, JPG {len(jpg)}B"

        def save():
            from pdf_common import open_source, save_pages
            from pypdf import PdfReader
            readers = {p: open_source(p) for p in [pdf_path] + state["images"]}
            pages = [(pdf_path, 1), (state["images"][1], 0), (pdf_path, 0)]
            out = os.path.join(folder, "out.pdf")
            save_pages(pages, out, readers=readers, file_bookmarks=True, keep_outlines=True)
            return f"저장한 쪽 수 {len(PdfReader(out).pages)}"

        def window():
            import tkinter as tk
            from pdf_tool_render import build_window
            root = tk.Tk()
            try:
                page = build_window(root)
                root.update()
                return f"Tk {root.tk.call('info', 'patchlevel')}, 메뉴 {page.winfo_toplevel()['menu'] != ''}"
            finally:
                root.destroy()

        for name, func in (("라이브러리 버전", versions), ("시험 파일 만들기", make_files),
                           ("PDF/이미지 불러오기", load), ("렌더링과 이미지 변환", render),
                           ("PDF 저장", save), ("창 만들기", window)):
            check(name, func)

    lines.append("결과: " + ("통과" if ok else "실패"))
    text = "\n".join(lines) + "\n"
    if result_path:
        # BOM을 붙여야 Windows PowerShell 5의 Get-Content가 한국어를 깨뜨리지 않고 읽음 (기본이 CP949)
        with open(result_path, "w", encoding="utf-8-sig") as f:
            f.write(text)
    elif sys.stdout is not None:
        sys.stdout.write(text)
    return 0 if ok else 1
