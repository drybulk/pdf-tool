"""
PDF 도구: 병합 / 페이지 추출 및 순서 편집 (GUI)

필요한 외부 라이브러리: pypdf 1개
    pip install pypdf
GUI는 파이썬에 기본 포함된 tkinter를 사용합니다.
실행에는 이 파일과 같은 폴더의 공통 모듈 pdf_common.py가 필요합니다.

쪽 범위를 지정해 PDF를 불러오고, 쪽 단위로 마우스로 순서를 바꾸거나 삭제한 뒤 새 PDF로 저장합니다.
여러 PDF를 불러오면 목록 순서대로 이어 붙여 하나로 합칩니다(원본 북마크 유지, 파일 이름 북마크 선택).
Ctrl+Z: 실행 취소, Ctrl+Y (또는 Ctrl+Shift+Z): 다시 실행
"""

import tkinter as tk
from tkinter import ttk

# 기존 테스트가 pdf_tool.이름으로 접근하므로 공통 모듈의 이름을 다시 내보냄
from pdf_common import (
    IS_MAC,
    UNDO_LIMIT,
    DragTree,
    PageTab,
    merge_pdfs,
    open_pdf,
    outline_entries,
    parse_page_ranges,
    run_background,
    save_pages,
)

__all__ = [
    "IS_MAC", "UNDO_LIMIT", "DragTree", "PageTab",
    "merge_pdfs", "open_pdf", "outline_entries", "parse_page_ranges", "run_background", "save_pages", "main",
]


# ---------------------------------------------------------------------------
def main():
    root = tk.Tk()
    root.title("PDF 도구: 병합 / 페이지 추출")
    root.geometry("780x560")
    root.minsize(640, 460)

    PageTab(root).pack(fill="both", expand=True)

    root.mainloop()


if __name__ == "__main__":
    main()
