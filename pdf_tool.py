"""
PDF 도구: 병합 / 페이지 추출 및 순서 편집 (GUI)

필요한 외부 라이브러리: pypdf 1개 (이미지 파일도 불러오려면 Pillow, 선택)
    pip install pypdf
GUI는 파이썬에 기본 포함된 tkinter를 사용합니다.
실행에는 이 파일과 같은 폴더의 공통 모듈 pdf_common.py가 필요합니다.

쪽 범위를 지정해 PDF를 불러오고, 쪽 단위로 마우스로 순서를 바꾸거나 삭제한 뒤 새 PDF로 저장합니다.
여러 PDF를 불러오면 목록 순서대로 이어 붙여 하나로 합칩니다(원본 북마크 유지, 파일 이름 북마크 선택).
메뉴 막대(파일, 편집, 도움말)와 쪽 목록의 우클릭 메뉴가 있습니다.
Ctrl+O: 불러오기, Ctrl+S: 저장, Ctrl+Z: 실행 취소, Ctrl+Y (또는 Ctrl+Shift+Z): 다시 실행
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
    "merge_pdfs", "open_pdf", "outline_entries", "parse_page_ranges", "run_background", "save_pages", "build_window", "main",
]


# ---------------------------------------------------------------------------
def build_window(root):
    """창(root)에 제목, 크기, 메뉴 막대, 쪽 편집 화면을 붙이고 화면(PageTab)을 반환합니다."""
    root.title("PDF 도구: 병합 / 페이지 추출")
    root.geometry("780x560")
    root.minsize(640, 460)

    page = PageTab(root)
    page.make_menubar(root)
    page.pack(fill="both", expand=True)
    return page


def main():
    root = tk.Tk()
    build_window(root)
    root.mainloop()


if __name__ == "__main__":
    main()
