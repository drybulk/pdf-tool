# PDF 도구 웹판

브라우저에서 실행하는 PDF 도구입니다. 데스크톱판과 달리 설치할 것이 없고, 파일은 브라우저 안에서만 처리하며 어디에도 올리지 않습니다. 서버 없이 정적 파일(HTML, JavaScript)만으로 동작하므로 GitHub Pages에 그대로 올릴 수 있고, 나중에 Chrome 확장 프로그램으로도 옮길 수 있게 만들었습니다.

## 지금 되는 것 (첫 버전)

- PDF 불러오기 (버튼, Ctrl+O, 파일을 창으로 끌어다 놓기). 쪽 범위 입력은 데스크톱판과 같은 규칙입니다.
- 쪽 목록과 썸네일(화면에 보이는 쪽만 그림), 클릭한 쪽의 미리보기
- 마우스로 끌어서 순서 바꾸기(빨간 표시선, 여러 쪽 함께 옮기기), Ctrl/Shift+클릭 선택
- 선택 삭제, 위로, 아래로, 맨 위로, 맨 아래로, 위치 지정 이동, 전체 선택, 목록 비우기
- 실행 취소(Ctrl+Z), 다시 실행(Ctrl+Y, Ctrl+Shift+Z), 최대 100단계
- 새 PDF로 저장 (여러 PDF를 불러오면 목록 순서대로 병합). 저장한 파일은 브라우저의 다운로드 폴더에 들어갑니다.

## 아직 안 되는 것 (다음 단계)

- 원본 북마크 유지, 파일 이름 북마크
- 본문 링크(인용 번호 등)가 가리키는 이름 붙은 대상의 쪽 안 위치 유지. 지금은 이 정보가 저장한 파일에 옮겨지지 않습니다.
- 이미지 파일 불러오기, 쪽을 이미지(PNG, JPG)로 저장
- 메뉴 막대와 우클릭 메뉴

## 내 컴퓨터에서 실행하기

`index.html`을 두 번 클릭해서 열면 동작하지 않습니다. 브라우저가 `file://`로 연 페이지에서는 JavaScript 모듈과 작업 스레드(worker)를 막기 때문입니다. 아래처럼 간단한 웹 서버를 켜고 엽니다.

저장소 폴더에서 Python의 내장 웹 서버를 켭니다.

```
python -m http.server 8000 --directory web
```

브라우저에서 `http://localhost:8000` 을 엽니다. 다 쓴 뒤에는 명령 창에서 Ctrl+C로 서버를 끕니다.

## 구성

- `index.html`, `style.css`: 화면
- `js/app.js`: 화면 동작 (데스크톱판 `PageTab`, `DragTree`에 해당)
- `js/ranges.js`: 쪽 범위 해석 (`parse_page_ranges`와 같은 규칙)
- `js/order.js`: 순서 변경 규칙 (모으기, 위로/아래로, 위치 지정)
- `js/pdfio.js`: PDF 열기와 그리기(pdf.js), 저장(pdf-lib)
- `vendor/`: 외부 라이브러리 파일. Chrome 확장은 외부에서 코드를 내려받아 실행할 수 없으므로, CDN을 쓰지 않고 파일을 함께 둡니다. 라이선스는 저장소의 `THIRD_PARTY_NOTICES.md`에 있습니다.

## 테스트

```
npm install --no-save playwright
npx playwright install chromium
node tests/web/test_web.cjs
```
