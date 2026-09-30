"""테스트용 PDF를 만드는 도우미. 쪽마다 "접두어+쪽번호" 글자를 넣어서 순서를 검증할 수 있게 합니다."""
import os

from reportlab.pdfgen import canvas


def make_pdf(path, prefix, pages):
    c = canvas.Canvas(path)
    for i in range(1, pages + 1):
        c.drawString(100, 700, f"{prefix}{i}")
        c.showPage()
    c.save()
    return path


def make_test_pdfs(directory):
    """(800쪽 'P1'~'P800', 5쪽 'S1'~'S5') 경로를 반환합니다."""
    big = make_pdf(os.path.join(directory, "big.pdf"), "P", 800)
    small = make_pdf(os.path.join(directory, "small.pdf"), "S", 5)
    return big, small
