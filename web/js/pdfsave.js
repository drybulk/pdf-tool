// 새 PDF로 저장. 데스크톱판 pdf_common.save_pages, copy_named_destinations, outline_entries와 같은 규칙입니다.
// pdf-lib(@cantoo/pdf-lib)의 낮은 수준 API로 PDF 객체를 직접 다룹니다.

import {
  PDFDocument, PDFName, PDFArray, PDFDict, PDFRef, PDFString, PDFHexString, PDFNumber, PDFNull,
  PDFObjectCopier, PDFPage,
} from "../vendor/pdf-lib/pdf-lib.esm.min.js";

const N = (name) => PDFName.of(name);

// ---------------------------------------------------------------------------
// 문자열: 이름 붙은 대상의 이름은 바이트 그대로 비교해야 합니다(링크의 문자열과 이름 트리의 키를
// 뷰어가 바이트로 비교함). 그래서 이름을 "바이트 하나 = 글자 하나"인 문자열로 다룹니다.
// ---------------------------------------------------------------------------
function isStr(obj) {
  return obj instanceof PDFString || obj instanceof PDFHexString;
}

function nameKey(obj) {
  if (isStr(obj)) return String.fromCharCode(...obj.asBytes());
  if (obj instanceof PDFName) return obj.decodeText();
  return null;
}

function keyToPdf(key) {
  let hex = "";
  for (let i = 0; i < key.length; i++) hex += key.charCodeAt(i).toString(16).padStart(2, "0");
  return PDFHexString.of(hex);
}

/** 이름 뒤에 "~2" 같은 꼬리를 붙입니다. UTF-16 문자열(FE FF로 시작)이면 UTF-16으로 붙입니다. */
function withSuffix(key, k) {
  const tail = `~${k}`;
  if (key.startsWith("\xfe\xff")) return key + [...tail].map((c) => "\0" + c).join("");
  return key + tail;
}

/** 사람이 읽는 글자로 바꿉니다(테스트와 오류 문구용). */
export function keyToText(key) {
  if (key.startsWith("\xfe\xff")) {
    let s = "";
    for (let i = 2; i + 1 < key.length; i += 2) s += String.fromCharCode((key.charCodeAt(i) << 8) | key.charCodeAt(i + 1));
    return s;
  }
  return key;
}

// ---------------------------------------------------------------------------
// 원본 읽기
// ---------------------------------------------------------------------------
function lookup(doc, obj) {
  return obj instanceof PDFRef ? doc.context.lookup(obj) : obj;
}

function get(doc, dict, key) {
  if (!(dict instanceof PDFDict)) return undefined;
  return lookup(doc, dict.get(N(key)));
}

/** 이름 붙은 대상: Map(이름 키 -> 대상 값). 이름 트리(/Names /Dests)와 옛 방식(/Dests 사전)을 모두 읽습니다. */
function namedDestinations(doc) {
  const result = new Map();
  const seen = new Set();
  const walk = (node, depth) => {
    if (!(node instanceof PDFDict) || seen.has(node) || depth > 64) return;
    seen.add(node);
    const names = get(doc, node, "Names");
    if (names instanceof PDFArray) {
      for (let i = 0; i + 1 < names.size(); i += 2) {
        const key = nameKey(lookup(doc, names.get(i)));
        if (key !== null && !result.has(key)) result.set(key, lookup(doc, names.get(i + 1)));
      }
    }
    const kids = get(doc, node, "Kids");
    if (kids instanceof PDFArray) for (let i = 0; i < kids.size(); i++) walk(lookup(doc, kids.get(i)), depth + 1);
  };
  try {
    walk(get(doc, get(doc, doc.catalog, "Names"), "Dests"), 0);
    const old = get(doc, doc.catalog, "Dests");
    if (old instanceof PDFDict) {
      for (const [k, v] of old.entries()) {
        const key = k.decodeText();
        if (!result.has(key)) result.set(key, lookup(doc, v));
      }
    }
  } catch (e) {
    // 읽을 수 없으면 있는 만큼만 씀
  }
  return result;
}

/** 대상 값(배열, /D를 가진 사전, 이름)을 대상 배열로 풉니다. 풀 수 없으면 null. */
function destArray(doc, value, named, depth = 0) {
  value = lookup(doc, value);
  if (value instanceof PDFArray) return value;
  if (value instanceof PDFDict) return destArray(doc, value.get(N("D")), named, depth + 1);
  const key = nameKey(value);
  if (key !== null && named.has(key) && depth < 4) return destArray(doc, named.get(key), named, depth + 1);
  return null;
}

/**
 * 대상 배열에서 쪽 인덱스(0부터)와 쪽 안의 위치(종류와 인자)를 꺼냅니다.
 * 위치를 읽을 수 없으면 쪽 전체 보기(/Fit)로 둡니다(데스크톱판 dest_fit과 같음).
 */
function destTarget(doc, arr, pageIndex) {
  if (!arr || arr.size() < 1) return null;
  const first = arr.get(0);
  let index = null;
  if (first instanceof PDFRef) index = pageIndex.get(first.tag);
  else if (first instanceof PDFNumber) index = first.asNumber();
  if (index === undefined || index === null) return null;
  const type = lookup(doc, arr.get(1));
  let fit = [N("Fit")];
  if (type instanceof PDFName) {
    fit = [type];
    for (let i = 2; i < arr.size(); i++) {
      const v = lookup(doc, arr.get(i));
      fit.push(v instanceof PDFNumber || v === PDFNull ? v : PDFNull);
    }
  }
  return { index, fit };
}

/**
 * 원본의 북마크를 [{ title, index, depth, fit }, ...]로 펼칩니다(목차에 보이는 순서).
 * 데스크톱판 outline_entries와 같습니다. title은 원본의 문자열 객체 그대로입니다.
 */
function outlineEntries(doc, named, pageIndex) {
  const entries = [];
  const seen = new Set();
  const walk = (item, depth) => {
    let guard = 0;
    while (item instanceof PDFDict && !seen.has(item) && guard++ < 100000) {
      seen.add(item);
      let target = null;
      try {
        let dest = item.get(N("Dest"));
        if (dest === undefined) {
          const action = get(doc, item, "A");
          if (action instanceof PDFDict && get(doc, action, "S") === N("GoTo")) dest = action.get(N("D"));
        }
        target = dest === undefined ? null : destTarget(doc, destArray(doc, dest, named), pageIndex);
      } catch (e) {
        target = null;
      }
      const title = get(doc, item, "Title");
      entries.push({
        title: isStr(title) ? title : PDFHexString.fromText(""),
        index: target ? target.index : null,
        depth,
        fit: target ? target.fit : [N("Fit")],
      });
      walk(get(doc, item, "First"), depth + 1);
      item = get(doc, item, "Next");
    }
  };
  try {
    walk(get(doc, get(doc, doc.catalog, "Outlines"), "First"), 0);
  } catch (e) {
    return [];
  }
  return entries;
}

/** pdf-lib로 원본 PDF를 엽니다. 열람 비밀번호가 없는 암호화 PDF는 빈 비밀번호로 해제합니다. */
export async function openForCopy(bytes) {
  let doc;
  try {
    doc = await PDFDocument.load(bytes);
  } catch (e) {
    if (!(e && /encrypted/i.test(e.message))) throw e;
    doc = await PDFDocument.load(bytes, { password: "" });
  }
  if (doc.isEncrypted) throw new Error("암호화된 PDF를 해제하지 못했습니다.");
  return doc;
}

// ---------------------------------------------------------------------------
// 북마크 쓰기
// ---------------------------------------------------------------------------
class OutlineBuilder {
  constructor(out) {
    this.out = out;
    this.root = { children: [] };
  }

  /** 항목을 더하고 그 항목을 돌려줍니다. parent가 없으면 맨 위 단계에 둡니다. */
  add(title, dest, parent = null) {
    const item = { title, dest, children: [] };
    (parent || this.root).children.push(item);
    return item;
  }

  /** 문서에 /Outlines를 씁니다. 모든 항목은 펼친 상태(/Count 양수)입니다. */
  write() {
    if (!this.root.children.length) return;
    const ctx = this.out.context;
    const build = (node, parentRef) => {
      const refs = node.children.map(() => ctx.nextRef());
      let total = 0;
      node.children.forEach((item, i) => {
        const dict = ctx.obj({});
        dict.set(N("Title"), item.title);
        dict.set(N("Parent"), parentRef);
        dict.set(N("Dest"), ctx.obj(item.dest));
        if (i > 0) dict.set(N("Prev"), refs[i - 1]);
        if (i + 1 < refs.length) dict.set(N("Next"), refs[i + 1]);
        if (item.children.length) {
          const sub = build(item, refs[i]);
          dict.set(N("First"), sub.first);
          dict.set(N("Last"), sub.last);
          dict.set(N("Count"), PDFNumber.of(sub.count));
          total += sub.count;
        }
        ctx.assign(refs[i], dict);
        total += 1;
      });
      return { first: refs[0], last: refs[refs.length - 1], count: total };
    };
    const rootRef = ctx.nextRef();
    const top = build(this.root, rootRef);
    ctx.assign(rootRef, ctx.obj({ Type: "Outlines", First: top.first, Last: top.last, Count: top.count }));
    this.out.catalog.set(N("Outlines"), rootRef);
    this.out.catalog.set(N("PageMode"), N("UseOutlines"));
  }
}

function stem(name) {
  return name.replace(/\.[^.]*$/, "");
}

// ---------------------------------------------------------------------------
// 저장
// ---------------------------------------------------------------------------
/**
 * pages: [{ source, index }, ...] 순서대로 새 PDF를 만들어 바이트(Uint8Array)를 돌려줍니다.
 * source는 { name, bytes }이며, 같은 쪽이 여러 번 들어 있어도 됩니다.
 * options.fileBookmarks: 같은 파일의 쪽이 이어지는 구간마다 첫 쪽에 파일 이름 북마크를 추가합니다.
 * options.keepOutlines: 원본 북마크 중 가리키는 쪽이 결과에 있는 것을 유지합니다. 같은 쪽이 여러 번
 *   있으면 처음 나오는 위치를 가리킵니다. 상위 항목이 빠지면 남아 있는 가장 가까운 상위 항목(없으면 그 쪽이
 *   속한 구간의 파일 이름 북마크) 아래에 둡니다. 파일 이름 북마크를 만들 때는 같은 구간의 상위 항목만 씁니다.
 * 본문 링크가 가리키는 이름 붙은 대상은 옵션과 관계없이 원본의 쪽 안 위치를 유지합니다.
 * progress(n, total)는 원본 하나의 쪽을 모두 복사할 때마다 호출합니다.
 */
export async function savePages(pages, options = {}, progress = null) {
  if (typeof options === "function") [progress, options] = [options, {}];
  const { fileBookmarks = false, keepOutlines = false } = options;
  const out = await PDFDocument.create();
  const ctx = out.context;
  const total = pages.length;

  const sources = [...new Set(pages.map((p) => p.source))]; // 파일이 처음 나오는 순서
  const firstPos = new Map(); // source -> Map(쪽 인덱스 -> 결과에서 처음 나오는 위치)
  for (const s of sources) firstPos.set(s, new Map());
  pages.forEach((p, pos) => {
    const m = firstPos.get(p.source);
    if (!m.has(p.index)) m.set(p.index, pos);
  });
  const posRef = pages.map(() => ctx.nextRef()); // 결과의 쪽마다 미리 정한 객체 번호
  const nodes = new Array(total);
  const info = new Map(); // source -> { doc, pageIndex, named }

  let done = 0;
  for (const source of sources) {
    let doc;
    try {
      doc = await openForCopy(source.bytes);
    } catch (e) {
      throw new Error(`${source.name}: ${e && e.message ? e.message : e}`);
    }
    const srcPages = doc.getPages();
    const pageIndex = new Map(srcPages.map((pg, i) => [pg.ref.tag, i]));
    info.set(source, { doc, pageIndex, named: namedDestinations(doc) });

    // 쪽을 복사할 때 다른 쪽을 가리키는 참조(링크의 대상, 주석의 /P 등)를 결과의 쪽으로 바꿈.
    // pdf-lib의 copyPages는 이런 참조를 따라가서 가리키는 쪽 전체(내용과 자원)를 부모 없는 쪽으로
    // 함께 복사하므로 파일이 커짐. 결과에 없는 쪽을 가리키면 null로 둠.
    // traversedObjects는 PDFObjectCopier의 내부 속성(TypeScript private)이며, 미리 채워 두는 방식으로 씀.
    const copier = PDFObjectCopier.for(doc.context, ctx);
    const first = firstPos.get(source);
    srcPages.forEach((pg, i) => {
      copier.traversedObjects.set(pg.ref, first.has(i) ? posRef[first.get(i)] : PDFNull);
    });
    for (const [index, pos] of first) {
      nodes[pos] = copier.copy(srcPages[index].node);
      ctx.assign(posRef[pos], nodes[pos]);
    }
    // 같은 쪽의 두 번째부터: 첫 복사본을 얕게 복제함(내용과 자원은 함께 씀). 주석은 쪽마다 따로 둠
    pages.forEach((p, pos) => {
      if (p.source !== source || nodes[pos]) return;
      const orig = nodes[first.get(p.index)];
      const dup = orig.clone(ctx);
      const annots = lookup(out, orig.get(N("Annots")));
      if (annots instanceof PDFArray) {
        const arr = ctx.obj([]);
        for (let i = 0; i < annots.size(); i++) {
          const a = lookup(out, annots.get(i));
          if (!(a instanceof PDFDict)) continue;
          const copy = a.clone(ctx);
          if (copy.has(N("P"))) copy.set(N("P"), posRef[pos]);
          arr.push(ctx.register(copy));
        }
        dup.set(N("Annots"), arr);
      }
      nodes[pos] = dup;
      ctx.assign(posRef[pos], dup);
    });
    done += pages.filter((p) => p.source === source).length;
    if (progress) progress(done, total);
  }
  pages.forEach((_, pos) => out.addPage(PDFPage.of(nodes[pos], posRef[pos], out)));

  copyNamedDestinations(out, pages, info, firstPos, posRef);

  // 북마크
  const outline = new OutlineBuilder(out);
  const runOf = new Array(total);
  const runItem = new Array(total);
  let run = -1;
  let item = null;
  pages.forEach((p, pos) => {
    if (pos === 0 || p.source !== pages[pos - 1].source) {
      run++;
      item = fileBookmarks ? outline.add(PDFHexString.fromText(stem(p.source.name)), [posRef[pos], N("Fit")]) : null;
    }
    runOf[pos] = run;
    runItem[pos] = item;
  });
  if (keepOutlines) {
    for (const source of sources) {
      const { doc, pageIndex, named } = info.get(source);
      const stack = []; // [{ depth, item, run }, ...] 현재 항목의 상위 항목들
      for (const e of outlineEntries(doc, named, pageIndex)) {
        while (stack.length && stack[stack.length - 1].depth >= e.depth) stack.pop();
        const pos = e.index === null ? undefined : firstPos.get(source).get(e.index);
        if (pos === undefined) continue;
        let parent = runItem[pos];
        for (let i = stack.length - 1; i >= 0; i--) {
          if (!fileBookmarks || stack[i].run === runOf[pos]) {
            parent = stack[i].item;
            break;
          }
        }
        const added = outline.add(e.title, [posRef[pos], ...e.fit], parent);
        stack.push({ depth: e.depth, item: added, run: runOf[pos] });
      }
    }
  }
  outline.write();
  return out.save();
}

/**
 * 원본의 이름 붙은 대상을 쪽 안의 위치까지 결과로 옮깁니다(데스크톱판 copy_named_destinations와 같음).
 * - 가리키는 쪽이 결과에 없는 이름은 옮기지 않습니다. 같은 쪽이 여러 번 있으면 처음 나오는 위치를 가리킵니다.
 * - 앞 파일과 이름이 겹치면 뒤 파일의 이름을 "이름~2"처럼 바꾸고, 그 파일에서 온 쪽의 링크도 바꿉니다.
 */
function copyNamedDestinations(out, pages, info, firstPos, posRef) {
  const ctx = out.context;
  const used = new Set();
  const entries = new Map(); // 결과의 이름 -> 대상 배열 요소
  const renames = new Map(); // source -> Map(원래 이름 -> 바꾼 이름)
  for (const source of firstPos.keys()) {
    const { doc, pageIndex, named } = info.get(source);
    const mapping = new Map();
    for (const name of named.keys()) if (!used.has(name)) mapping.set(name, name);
    const taken = new Set([...used, ...named.keys()]);
    for (const name of named.keys()) {
      if (mapping.has(name)) continue;
      let k = 2;
      let next = withSuffix(name, k);
      while (taken.has(next)) next = withSuffix(name, ++k);
      mapping.set(name, next);
      taken.add(next);
    }
    for (const v of mapping.values()) used.add(v);
    renames.set(source, new Map([...mapping].filter(([a, b]) => a !== b)));
    for (const [name, value] of named) {
      let target = null;
      try {
        target = destTarget(doc, destArray(doc, value, named), pageIndex);
      } catch (e) {
        target = null;
      }
      const pos = target && firstPos.get(source).get(target.index);
      if (pos === undefined || pos === null) continue;
      entries.set(mapping.get(name), [posRef[pos], ...target.fit]);
    }
  }

  // 링크가 가리키는 이름을 바꾼 이름으로 고침. 옛 방식(/Dests 사전)의 이름은 PDF 이름 객체(/abc)로
  // 가리키는데, 결과에는 이름 트리만 만들므로 문자열로 바꿔야 뷰어가 찾을 수 있음
  const fix = (obj, map) => {
    const key = nameKey(obj);
    if (key === null) return null;
    if (map.has(key)) return keyToPdf(map.get(key));
    return obj instanceof PDFName ? keyToPdf(key) : null;
  };
  const done = new Set();
  pages.forEach((p, pos) => {
    const map = renames.get(p.source) || new Map();
    const node = ctx.lookup(posRef[pos]);
    const annots = lookup(out, node.get(N("Annots")));
    if (!(annots instanceof PDFArray)) return;
    for (let i = 0; i < annots.size(); i++) {
      const annot = lookup(out, annots.get(i));
      if (!(annot instanceof PDFDict) || done.has(annot) || lookup(out, annot.get(N("Subtype"))) !== N("Link")) continue;
      done.add(annot);
      const dest = fix(lookup(out, annot.get(N("Dest"))), map);
      if (dest) annot.set(N("Dest"), dest);
      const action = lookup(out, annot.get(N("A")));
      if (action instanceof PDFDict && lookup(out, action.get(N("S"))) === N("GoTo")) {
        const d = fix(lookup(out, action.get(N("D"))), map);
        if (d) {
          // 같은 동작 객체를 다른 쪽이 함께 쓸 수 있으므로 고치지 않고 새로 만들어 바꿔 끼움
          const fresh = action.clone(ctx);
          fresh.set(N("D"), d);
          annot.set(N("A"), fresh);
        }
      }
    }
  });

  if (entries.size) {
    const arr = ctx.obj([]);
    for (const name of [...entries.keys()].sort()) {
      arr.push(keyToPdf(name));
      arr.push(ctx.obj(entries.get(name)));
    }
    out.catalog.set(N("Names"), ctx.obj({ Dests: ctx.obj({ Names: arr }) }));
  }
}
