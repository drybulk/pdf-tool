// 쪽 목록의 순서를 바꾸는 순수 함수들. 화면과 관계없이 시험할 수 있도록 따로 둡니다.
// 데스크톱판 DragTree의 _gather_selection, shift_selection, move_selection_to와 같은 규칙입니다.
// rows: 행 ID 배열, selected: 선택한 행 ID의 Set. 순서가 바뀌면 새 배열, 바뀌지 않으면 null을 돌려줍니다.

function sameOrder(a, b) {
  return a.length === b.length && a.every((x, i) => x === b[i]);
}

/** 선택한 행들을 상대 순서를 유지한 채, 선택하지 않은 행 목록의 pos번째(0부터) 자리에 모읍니다. */
export function gatherSelection(rows, selected, pos) {
  const moving = rows.filter((r) => selected.has(r));
  if (!moving.length) return null;
  const others = rows.filter((r) => !selected.has(r));
  pos = Math.min(Math.max(pos, 0), others.length);
  const next = [...others.slice(0, pos), ...moving, ...others.slice(pos)];
  return sameOrder(next, rows) ? null : next;
}

/** 놓을 자리 slot(행 사이의 경계 번호, 0부터)을 gatherSelection의 pos로 바꿉니다. */
export function slotToPos(rows, selected, slot) {
  let n = 0;
  for (let i = 0; i < slot && i < rows.length; i++) if (!selected.has(rows[i])) n++;
  return n;
}

/** 선택한 행들을 step(-1 또는 +1)칸 옮깁니다. 끝에 닿아 옮기지 못하면 null. */
export function shiftSelection(rows, selected, step) {
  const idx = [];
  rows.forEach((r, i) => selected.has(r) && idx.push(i));
  if (!idx.length) return null;
  if ((step < 0 && idx[0] === 0) || (step > 0 && idx[idx.length - 1] === rows.length - 1)) return null;
  const next = rows.slice();
  for (const i of step < 0 ? idx : idx.slice().reverse()) {
    [next[i], next[i + step]] = [next[i + step], next[i]];
  }
  return next;
}

/** 선택한 행들을 position번째(1부터) 위치로 옮깁니다. */
export function moveSelectionTo(rows, selected, position) {
  return gatherSelection(rows, selected, position - 1);
}
