"""
렌더링 속도 측정 스크립트: 렌더링판의 지연 로딩과 캐시 설정을 실제 PDF로 확인하기 위한 도구입니다.

사용법 (저장소 최상위 폴더에서 실행):
    python tools/bench_render.py 논문.pdf [보고서.pdf ...] [--pages 100]

각 PDF의 첫 쪽부터 최대 --pages쪽(기본 100)을 대상으로, 쪽마다 아래 작업에 걸린 시간을 재서
쪽당 평균과 최대를 밀리초(ms)로 출력합니다. 프로그램과 같은 함수를 사용합니다.
  - 렌더링: PDFium으로 쪽을 그림으로 그리는 시간 (쪽 불러오기 포함)
  - PPM 변환: 그린 결과를 Tk가 표시할 수 있는 PPM 데이터로 바꾸는 시간
  - Tk 이미지: PPM 데이터로 화면 표시용 tk.PhotoImage를 만드는 시간 (썸네일과 미리보기만)
배율: 썸네일 0.12 (프로그램과 같이 A4 크기 칸에 맞춤), 화면 미리보기 1.0, 저장용 200 DPI, 300 DPI

필요한 라이브러리: pypdfium2 (requirements-render.txt). 화면이 있는 환경에서 실행합니다.
"""

import argparse
import os
import platform
import statistics
import sys
import time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 저장소 최상위

import pypdfium2 as pdfium
import pypdfium2.version as pdfium_version

from pdf_render import bitmap_to_ppm, thumb_scale

TARGETS = [  # (이름, 배율을 정하는 함수(쪽 너비, 쪽 높이), Tk 이미지 생성 측정 여부)
    ("썸네일 0.12", lambda w, h: thumb_scale(w, h), True),
    ("미리보기 1.0", lambda w, h: 1.0, True),
    ("저장 200 DPI", lambda w, h: 200 / 72, False),
    ("저장 300 DPI", lambda w, h: 300 / 72, False),
]


def measure(path, max_pages, root):
    doc = pdfium.PdfDocument(path)
    try:
        total = len(doc)
        n = min(total, max_pages)
        first_w, first_h = doc[0].get_size()
        times = {name: {"render": [], "ppm": [], "tk": []} for name, _, _ in TARGETS}
        sizes = {}
        images = []
        for i in range(n):
            for name, scale_of, with_tk in TARGETS:
                t0 = time.perf_counter()
                page = doc[i]
                w, h = page.get_size()
                bitmap = page.render(scale=scale_of(w, h), rev_byteorder=True)
                t1 = time.perf_counter()
                ppm = bitmap_to_ppm(bitmap.width, bitmap.height, bitmap.stride, bitmap.buffer)
                t2 = time.perf_counter()
                sizes.setdefault(name, (bitmap.width, bitmap.height))
                bitmap.close()
                page.close()
                times[name]["render"].append(t1 - t0)
                times[name]["ppm"].append(t2 - t1)
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
    return f"{fn(values) * 1000:8.1f}" if values else "       -"


def main():
    parser = argparse.ArgumentParser(description="PDF 쪽 렌더링 속도 측정")
    parser.add_argument("pdfs", nargs="+", help="측정할 PDF 파일")
    parser.add_argument("--pages", type=int, default=100, help="파일마다 측정할 최대 쪽수 (기본 100)")
    args = parser.parse_args()

    print(f"Python {platform.python_version()} ({platform.system()} {platform.release()}, {platform.machine()})")
    print(f"pypdfium2 {pdfium_version.PYPDFIUM_INFO}, PDFium {pdfium_version.PDFIUM_INFO}, Tk {tk.TkVersion}")
    root = tk.Tk()
    root.withdraw()
    for path in args.pdfs:
        print()
        print(f"== {os.path.basename(path)} ({os.path.getsize(path) / 1024 / 1024:.1f} MB)")
        try:
            total, n, first, sizes, times = measure(path, args.pages, root)
        except Exception as e:
            print(f"   측정하지 못했습니다: {e}")
            continue
        print(f"   전체 {total}쪽 중 앞 {n}쪽 측정, 첫 쪽 크기 {first[0]:.0f} x {first[1]:.0f} pt")
        print("   단위: 쪽당 ms        렌더링(평균  최대)   PPM 변환(평균  최대)   Tk 이미지(평균  최대)   그림 크기(첫 쪽)")
        for name, _, _ in TARGETS:
            t = times[name]
            w, h = sizes[name]
            print(
                f"   {name:<12} {ms(t['render'], statistics.mean)} {ms(t['render'], max)}"
                f"   {ms(t['ppm'], statistics.mean)} {ms(t['ppm'], max)}"
                f"   {ms(t['tk'], statistics.mean)} {ms(t['tk'], max)}   {w} x {h}"
            )
    root.destroy()


if __name__ == "__main__":
    main()
