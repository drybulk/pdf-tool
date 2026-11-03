// Chrome 확장의 백그라운드 서비스 워커. 툴바 아이콘을 누르면 웹판 화면(index.html)을 새 탭으로 엽니다.
// 권한(permissions)이 필요하지 않은 동작만 씁니다: 자기 확장의 페이지를 새 탭으로 여는 것은 권한 없이 됩니다.

function openApp() {
  return chrome.tabs.create({ url: chrome.runtime.getURL("index.html") });
}

chrome.action.onClicked.addListener(() => {
  openApp();
});

// 자동 시험(tests/web/test_extension.cjs)은 툴바 아이콘을 누를 수 없으므로 이 함수를 직접 부름
globalThis.openApp = openApp;
