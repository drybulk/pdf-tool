"""
렌더링 속도 측정 스크립트: 렌더링판의 지연 로딩과 캐시 설정을 실제 PDF로 확인하기 위한 도구입니다.

사용법 (저장소 최상위 폴더에서 실행):
    python tools/bench_render.py 논문.pdf [보고서.pdf ...] [--pages 100]

각 PDF의 첫 쪽부터 최대 --pages쪽(기본 100)을 대상으로, 쪽마다 아래 작업에 걸린 시간을 재서
쪽당 평균과 최대를 밀리초(ms)로 출력합니다. 프로그램과 같은 함수를 사용합니다.
  - 렌더링: PDFium으로 쪽을 그림으로 그리는 시간. "쪽 불러오기"(doc[i]와 get_size)와 "그리기"(render)의 합이며,
    쪽 불러오기의 평균은 따로도 출력합니다.
  - PPM 변환: 그린 결과를 Tk가 표시할 수 있는 PPM 데이터로 바꾸는 시간
  - Tk 이미지: PPM 데이터로 화면 표시용 tk.PhotoImage를 만드는 시간 (썸네일과 미리보기만)
  - PNG 만들기: 그린 결과로 PNG 파일 데이터를 만드는 시간 (저장용 배율만, zlib 압축 수준 1과 6).
    이미지 저장 기능(작업 순서 3단계)을 설계하기 위한 참고값이며, 파일에 쓰는 시간은 포함하지 않습니다.

측정 순서와 행의 의미:
  - 쪽마다 먼저 썸네일 배율로 한 번 그리고, 이 시간을 "처음 그리기" 행에 기록합니다. 쪽을 처음 그릴 때는
    추가 비용이 드는 것을 확인했습니다(그 쪽에서 처음 쓰는 글꼴과 그림을 준비하는 비용으로 추정). 이 행은
    프로그램에서 썸네일을 처음 그리는 시간에 해당합니다.
  - 그다음 썸네일, 미리보기, 200 DPI, 300 DPI 순서로 그립니다. 이 네 행은 모두 같은 쪽을 이미 한 번 그린 뒤의
    시간이므로 서로 같은 조건에서 비교할 수 있습니다. "처음 그리기"와 "썸네일" 행의 차이가 처음 그릴 때의 추가 비용입니다.
  - 배율마다 쪽을 닫았다가 다시 불러오며, 문서는 파일마다 한 번만 엽니다. 프로그램도 같은 방식입니다.
  - 첫 파일을 재기 전에 그 파일의 첫 쪽을 별도로 열어 한 번 그려 둡니다. 프로그램 시작 직후에만 드는 비용
    (라이브러리 초기화, 파일을 처음 읽는 비용)이 첫 쪽의 측정값에 섞이지 않게 하기 위해서입니다.
  - "최대 쪽"은 렌더링 시간이 가장 길었던 쪽의 번호(1부터 시작)입니다.

배율: 썸네일 0.12 (프로그램과 같이 A4 크기 칸에 맞춤), 화면 미리보기 1.0, 저장용 200 DPI, 300 DPI

필요한 라이브러리: pypdfium2 (requirements-render.txt). 화면이 있는 환경에서 실행합니다.
"""

import argparse
import os
import platform
import statistics
import struct
import sys
import time
import tkinter as tk
import unicodedata
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 저장소 최상위

import pypdfium2 as pdfium
import pypdfium2.version as pdfium_version

from pdf_render import bitmap_to_ppm, thumb_scale

FIRST = "처음 그리기"
TARGETS = [  # (이름, 배율을 정하는 함수(쪽 너비, 쪽 높이), Tk 이미지 생성 측정 여부, PNG 만들기 측정 여부)
    ("썸네일 0.12", lambda w, h: thumb_scale(w, h), True, False),
    ("미리보기 1.0", lambda w, h: 1.0, True, False),
    ("저장 200 DPI", lambda w, h: 200 / 72, False, True),
    ("저장 300 DPI", lambda w, h: 300 / 72, False, True),
]
PNG_LEVELS = (1, 6)  # 측정할 zlib 압축 수준


def png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def encode_png(width, height, stride, data, level):
    """RGB 순서의 비트맵 데이터를 PNG 바이트로 만듭니다. 각 행 앞에 필터 0(필터 없음)을 붙여서 압축합니다."""
    buf = memoryview(data).cast("B")
    row = width * 3
    raw = b"".join(b"\x00" + bytes(buf[y * stride : y * stride + row]) for y in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8비트, RGB
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", zlib.compress(raw, level))
        + png_chunk(b"IEND", b"")
    )


def render_timed(doc, i, scale_of):
    """쪽을 불러와서 그리고 (비트맵, 쪽, 쪽 불러오기 시간, 렌더링 전체 시간)을 반환합니다."""
    t0 = time.perf_counter()
    page = doc[i]
    w, h = page.get_size()
    t1 = time.perf_counter()
    bitmap = page.render(scale=scale_of(w, h), rev_byteorder=True)
    t2 = time.perf_counter()
    return bitmap, page, t1 - t0, t2 - t0


def warm_up(path):
    """프로그램 시작 직후에만 드는 비용을 측정 전에 치러 둡니다. 측정에 쓰는 문서와는 따로 열고 닫습니다."""
    doc = pdfium.PdfDocument(path)
    try:
        page = doc[0]
        w, h = page.get_size()
        page.render(scale=thumb_scale(w, h), rev_byteorder=True).close()
        page.close()
    finally:
        doc.close()


def measure(path, max_pages, root):
    doc = pdfium.PdfDocument(path)
    try:
        total = len(doc)
        n = min(total, max_pages)
        first_w, first_h = doc[0].get_size()
        names = [FIRST] + [name for name, _, _, _ in TARGETS]
        times = {name: {"load": [], "render": [], "ppm": [], "tk": [], **{f"png{lv}": [] for lv in PNG_LEVELS}} for name in names}
        sizes = {}
        images = []
        pngs = []
        for i in range(n):
            # 이 쪽을 처음 그리는 시간 (썸네일 배율)
            bitmap, page, load, render = render_timed(doc, i, lambda w, h: thumb_scale(w, h))
            bitmap.close()
            page.close()
            times[FIRST]["load"].append(load)
            times[FIRST]["render"].append(render)

            for name, scale_of, with_tk, with_png in TARGETS:
                bitmap, page, load, render = render_timed(doc, i, scale_of)
                t1 = time.perf_counter()
                ppm = bitmap_to_ppm(bitmap.width, bitmap.height, bitmap.stride, bitmap.buffer)
                t2 = time.perf_counter()
                sizes.setdefault(name, (bitmap.width, bitmap.height))
                times[name]["load"].append(load)
                times[name]["render"].append(render)
                times[name]["ppm"].append(t2 - t1)
                if with_png:
                    for lv in PNG_LEVELS:
                        t3 = time.perf_counter()
                        pngs.append(encode_png(bitmap.width, bitmap.height, bitmap.stride, bitmap.buffer, lv))
                        times[name][f"png{lv}"].append(time.perf_counter() - t3)
                        pngs.clear()  # 큰 데이터를 측정 구간 밖에서 해제함
                bitmap.close()
                page.close()
                if with_tk:
                    t3 = time.perf_counter()
                    images.append(tk.PhotoImage(master=root, data=ppm, format="PPM"))
                    times[name]["tk"].append(time.perf_counter() - t3)
                    images.clear()  # 측정 구간 밖에서 이미지를 해제함
                # 큰 데이터(300 DPI는 약 26MB)를 측정 구간 밖에서 해제함. 그렇지 않으면 다음 측정에 해제 시간이 섞임
                del ppm
    finally:
        doc.close()
    return total, n, (first_w, first_h), sizes, times


def ms(values, fn):
    return f"{fn(values) * 1000:.1f}" if values else "-"


def text_width(text):
    """터미널에 표시되는 폭. 한글처럼 넓은 문자는 2칸으로 셉니다."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def cell(text, width, left=False):
    pad = " " * max(width - text_width(text), 0)
    return text + pad if left else pad + text


# 출력 표의 열: (첫째 줄 머리글, 둘째 줄 머리글, 폭)
COLUMNS = [
    ("", "단위: 쪽당 ms", 14),
    ("렌더링", "평균", 8), ("", "최대", 7), ("", "최대 쪽", 8), ("", "불러오기", 9),
    ("PPM 변환", "평균", 9), ("", "최대", 7),
    ("Tk 이미지", "평균", 10), ("", "최대", 7),
    ("PNG 만들기", "수준1", 11), ("", "수준6", 7),
    ("", "그림 크기(첫 쪽)", 18),
]


def print_row(values):
    out = []
    for i, (value, (_, _, width)) in enumerate(zip(values, COLUMNS)):
        out.append(cell(value, width, left=(i == 0)))
    print("   " + "".join(out).rstrip())


def main():
    parser = argparse.ArgumentParser(description="PDF 쪽 렌더링 속도 측정")
    parser.add_argument("pdfs", nargs="+", help="측정할 PDF 파일")
    parser.add_argument("--pages", type=int, default=100, help="파일마다 측정할 최대 쪽수 (기본 100)")
    args = parser.parse_args()

    print(f"Python {platform.python_version()} ({platform.system()} {platform.release()}, {platform.machine()})")
    print(f"pypdfium2 {pdfium_version.PYPDFIUM_INFO}, PDFium {pdfium_version.PDFIUM_INFO}, Tk {tk.TkVersion}")
    root = tk.Tk()
    root.withdraw()
    warmed = False
    for path in args.pdfs:
        print()
        try:
            print(f"== {os.path.basename(path)} ({os.path.getsize(path) / 1024 / 1024:.1f} MB)")
            if not warmed:
                warm_up(path)
                warmed = True
            total, n, first, sizes, times = measure(path, args.pages, root)
        except Exception as e:
            print(f"   측정하지 못했습니다: {e}")
            continue
        print(f"   전체 {total}쪽 중 앞 {n}쪽 측정, 첫 쪽 크기 {first[0]:.0f} x {first[1]:.0f} pt")
        print_row([c[0] for c in COLUMNS])
        print_row([c[1] for c in COLUMNS])
        for name in [FIRST] + [name for name, _, _, _ in TARGETS]:
            t = times[name]
            peak = t["render"].index(max(t["render"])) + 1
            w, h = sizes.get(name, sizes[TARGETS[0][0]])  # 처음 그리기는 썸네일과 같은 크기
            print_row([
                name,
                ms(t["render"], statistics.mean), ms(t["render"], max), f"{peak}쪽", ms(t["load"], statistics.mean),
                ms(t["ppm"], statistics.mean), ms(t["ppm"], max),
                ms(t["tk"], statistics.mean), ms(t["tk"], max),
                *(ms(t[f"png{lv}"], statistics.mean) for lv in PNG_LEVELS),
                f"{w} x {h}",
            ])
    root.destroy()


if __name__ == "__main__":
    main()
