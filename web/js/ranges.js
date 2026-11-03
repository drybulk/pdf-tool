// 쪽 범위 해석. 데스크톱판 pdf_common.parse_page_ranges와 같은 규칙입니다.

export class PageRangeError extends Error {}

/**
 * 쪽 범위 문자열을 0부터 시작하는 쪽 인덱스 목록으로 바꿉니다.
 * - 쪽 번호는 1부터 시작하며, 입력한 순서를 그대로 유지합니다.
 * - 예: "721-732", "1-3, 7, 10-12", "5-" (5쪽부터 끝까지), "-3" (처음부터 3쪽까지)
 * - 빈 문자열이면 전체 쪽을 뜻합니다.
 * 해석할 수 없으면 PageRangeError를 던집니다.
 */
export function parsePageRanges(text, total) {
  text = text.trim();
  if (!text) return Array.from({ length: total }, (_, i) => i);

  const result = [];
  for (let part of text.replaceAll("~", "-").split(/[,;]/)) {
    part = part.trim();
    if (!part) continue;
    let start, end;
    const m = part.match(/^(\d+)?\s*-\s*(\d+)?$/);
    if (m) {
      if (m[1] === undefined && m[2] === undefined) {
        throw new PageRangeError("'-' 만으로는 범위를 지정할 수 없습니다.");
      }
      start = m[1] !== undefined ? parseInt(m[1], 10) : 1;
      end = m[2] !== undefined ? parseInt(m[2], 10) : total;
    } else if (/^\d+$/.test(part)) {
      start = end = parseInt(part, 10);
    } else {
      throw new PageRangeError(`해석할 수 없는 범위입니다: '${part}'`);
    }
    if (start < 1 || end > total) {
      throw new PageRangeError(`'${part}'은(는) 문서의 쪽수(1~${total}쪽)를 벗어납니다.`);
    }
    if (start > end) {
      throw new PageRangeError(`'${part}'은(는) 시작 쪽이 끝 쪽보다 큽니다.`);
    }
    for (let i = start - 1; i < end; i++) result.push(i);
  }
  if (!result.length) throw new PageRangeError("유효한 범위가 없습니다.");
  return result;
}
