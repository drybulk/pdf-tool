# PDF 도구

PDF 병합, 쪽 범위 추출, 쪽 단위 순서 편집(마우스 드래그)을 제공하는 tkinter 기반 GUI 프로그램입니다.
외부 라이브러리는 `pypdf` 하나만 사용합니다. (GUI는 파이썬 기본 포함 `tkinter`)

## 설치와 실행

```
pip install -r requirements.txt
python pdf_tool.py
```

검증한 환경은 Python 3.12, pypdf 5.9.0입니다.

## 기능

**탭 1. PDF 병합**
- 여러 PDF를 추가하고 위/아래 버튼으로 순서를 정한 뒤 하나로 합칩니다.
- 파일 이름으로 북마크(목차)를 추가하는 옵션이 있습니다.

**탭 2. 페이지 추출 / 편집**
- 쪽 범위를 지정해서 불러옵니다. 예: `721-732`, `1-3, 10, 15-20`, `5-`(5쪽부터 끝까지), 비우면 전체. 쪽 번호는 PDF 뷰어의 쪽 번호 기준이며 입력한 순서가 유지됩니다.
- 쪽을 마우스로 끌어서 순서를 바꿀 수 있습니다. Ctrl/Shift+클릭으로 여러 쪽을 선택해 함께 옮길 수 있고, 목록 바깥으로 끌면 자동 스크롤됩니다.
- 선택 삭제, 위/아래 이동, 맨 위/맨 아래, 위치 지정 이동, 전체 선택, 목록 비우기를 지원합니다.
- 현재 화면의 순서 그대로 새 PDF로 저장합니다.

## 단축키 (탭 2)

| 키 | 동작 |
|---|---|
| Ctrl+Z | 실행 취소 (최대 100단계) |
| Ctrl+Y, Ctrl+Shift+Z | 다시 실행 |
| Ctrl+A | 전체 선택 |
| Delete | 선택 삭제 |

## 테스트

```
pip install -r requirements.txt -r requirements-dev.txt
xvfb-run -a python tests/test_page_tab.py   # Linux. 화면이 있는 환경에서는 xvfb-run 없이 실행
xvfb-run -a python tests/test_undo.py
python tests/test_merge.py
```

Linux에서는 `python3-tk`와 `xvfb`가 필요합니다.

## 문서

- `CLAUDE.md`: 작업 원칙과 프로젝트 맥락 (Claude Code가 세션 시작 때 읽는 파일)
- `docs/extension_plan.md`: 미리보기, 이미지 저장, 메뉴 구조의 확장 계획
