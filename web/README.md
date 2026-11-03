# PDF 도구 웹판

브라우저에서 실행하는 PDF 도구입니다. 데스크톱판과 달리 설치할 것이 없고, 파일은 브라우저 안에서만 처리하며 어디에도 올리지 않습니다. 서버 없이 정적 파일(HTML, JavaScript)만으로 동작하므로 GitHub Pages에 그대로 올릴 수 있고, 나중에 Chrome 확장 프로그램으로도 옮길 수 있게 만들었습니다.

## 지금 되는 것

- PDF와 이미지 불러오기 (버튼, Ctrl+O, 파일을 창으로 끌어다 놓기). 쪽 범위 입력은 데스크톱판과 같은 규칙이며 PDF에만 적용합니다.
  - 이미지(PNG, JPG, BMP, GIF, WebP)는 1장을 1쪽으로 불러옵니다. 쪽 너비는 A4 너비이고 높이는 비율대로입니다. JPG는 다시 압축하지 않고 그대로 넣으며, 사진의 회전 정보(Exif 방향)를 반영합니다. 투명한 부분은 흰색으로 채웁니다.
  - TIFF는 Chrome과 Edge가 읽지 못해서 불러올 수 없습니다(데스크톱판에서는 됩니다).
- 쪽 목록과 썸네일(화면에 보이는 쪽만 그림), 클릭한 쪽의 미리보기
- 마우스로 끌어서 순서 바꾸기(빨간 표시선, 여러 쪽 함께 옮기기), Ctrl/Shift+클릭 선택
- 선택 삭제, 위로, 아래로, 맨 위로, 맨 아래로, 위치 지정 이동, 전체 선택, 목록 비우기
- 실행 취소(Ctrl+Z), 다시 실행(Ctrl+Y, Ctrl+Shift+Z), 최대 100단계
- 메뉴 막대(파일, 편집, 도움말)와 쪽 목록의 우클릭 메뉴("이 파일의 쪽 모두 선택", 이동, 삭제, 이미지로 저장). 구성은 데스크톱판과 같습니다.
- 새 PDF로 저장 (여러 파일을 불러오면 목록 순서대로 병합). 저장한 파일은 브라우저의 다운로드 폴더에 들어갑니다.
  - 원본 북마크(목차) 유지(기본 켬), 파일 이름으로 북마크 추가(기본 끔)
  - 본문 링크(인용 번호, 그림 번호 등)가 가리키는 위치를 쪽 안의 원래 위치까지 유지합니다. 여러 PDF의 이름이 겹치면 뒤 파일의 이름을 바꿔서 각자의 위치로 이어지게 합니다. 데스크톱판과 같은 사례로 결과가 같은지 테스트합니다.
- 쪽을 이미지(PNG, JPG)로 저장: 선택한 쪽 또는 목록 전체, DPI 72/150/200/300(기본 150), JPG 품질 1~95(기본 90). 파일 이름은 `원본이름_p0001.png`처럼 원본 쪽 번호를 씁니다. 브라우저는 폴더에 여러 파일을 바로 쓸 수 없으므로, 2장 이상이면 zip 파일 하나로 내려받습니다.

데스크톱판에 있고 웹판에 없는 것: 프로그램 종료 메뉴(브라우저 탭을 닫으면 됨), TIFF 불러오기, 비밀번호가 있는 PDF 열기(데스크톱판도 지원하지 않음).

## 내 컴퓨터에서 실행하기

`index.html`을 두 번 클릭해서 열면 동작하지 않습니다. 브라우저가 `file://`로 연 페이지에서는 JavaScript 모듈과 작업 스레드(worker)를 막기 때문입니다. 아래처럼 간단한 웹 서버를 켜고 엽니다.

저장소 폴더에서 Python의 내장 웹 서버를 켭니다.

```
python -m http.server 8000 --directory web
```

브라우저에서 `http://localhost:8000` 을 엽니다. 다 쓴 뒤에는 명령 창에서 Ctrl+C로 서버를 끕니다.

## Chrome 확장으로 설치하기

웹판을 Chrome 확장으로 묶어서 설치할 수 있습니다. 설치하면 툴바의 아이콘을 눌러 새 탭에서 바로 열 수 있고, 위의 웹 서버를 켤 필요가 없습니다. 인터넷 연결 없이도 동작합니다. 확장은 아무 권한도 요청하지 않습니다.

1. 저장소 폴더에서 확장을 만듭니다. `build/extension` 폴더가 생깁니다.

```
python tools/build_extension.py
```

2. Chrome 주소창에 `chrome://extensions` 를 입력합니다.
3. 오른쪽 위의 "개발자 모드"를 켭니다.
4. "압축해제된 확장 프로그램을 로드합니다"를 누르고 `build/extension` 폴더를 고릅니다.
5. 툴바의 퍼즐 조각 아이콘을 눌러 "PDF 도구"를 고정하면 툴바에서 바로 누를 수 있습니다.

새 버전을 받은 뒤에는 1번을 다시 실행하고 `chrome://extensions` 에서 "PDF 도구"의 새로고침 단추를 누릅니다. Edge(`edge://extensions`)에서도 같은 방법으로 설치할 수 있을 것으로 보지만 확인하지 않았습니다.

`tools/build_extension.py`는 Chrome 웹 스토어에 올릴 때 쓰는 zip(`build/pdf-tool-extension-<버전>.zip`)도 함께 만듭니다. 확장의 파일은 `extension/`(manifest, 백그라운드 스크립트, 아이콘)에 있고, 화면은 `web/`의 파일을 그대로 씁니다.

## 구성

- `index.html`, `style.css`: 화면
- `js/app.js`: 화면 동작 (데스크톱판 `PageTab`, `DragTree`에 해당)
- `js/ranges.js`: 쪽 범위 해석 (`parse_page_ranges`와 같은 규칙)
- `js/order.js`: 순서 변경 규칙 (모으기, 위로/아래로, 위치 지정)
- `js/pdfio.js`: PDF 열기와 그리기(pdf.js)
- `js/pdfsave.js`: 저장(pdf-lib). 북마크와 이름 붙은 대상 처리 (`save_pages`, `copy_named_destinations`와 같은 규칙)
- `js/imageimport.js`: 이미지 → PDF 쪽 (`image_to_pdf`와 같은 규칙)
- `js/imageexport.js`: PNG/JPG 만들기(해상도 기록), 파일 이름 규칙, zip 만들기
- `js/version.js`: 프로그램 버전 (데스크톱판 `APP_VERSION`과 같은 값)
- `vendor/`: 외부 라이브러리 파일. Chrome 확장은 외부에서 코드를 내려받아 실행할 수 없으므로, CDN을 쓰지 않고 파일을 함께 둡니다. 라이선스는 저장소의 `THIRD_PARTY_NOTICES.md`에 있습니다.

## 테스트

```
npm install --no-save playwright
npx playwright install chromium
node tests/web/test_web.cjs
node tests/web/test_web_features.cjs
```

Chrome 확장 테스트는 확장을 만들어 설치한 Chromium에서 위의 두 테스트를 다시 실행합니다(Python 필요).

```
node tests/web/test_extension.cjs
```

저장 결과를 데스크톱판과 비교하는 테스트는 Python도 필요합니다(`pip install -r requirements.txt -r requirements-dev.txt`).

```
python tests/web/test_web_save.py
```
