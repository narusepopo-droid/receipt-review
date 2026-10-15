/* 테이블 안내판 v2 — 디자인 12종 × 크기(세로 인쇄용 / 가로 태블릿 대기화면)
 * window.signHTML(design, qrSrc, tableLabel) → 안내판 안쪽 HTML (글자는 모두 이스케이프)
 * window.SIGN_FONTS  글꼴 목록 (굵기별 파일)   window.signFontFace() → @font-face CSS
 * window.SIGN_TEMPLATES / SIGN_SIZES / signSize(design) / signFontsUsed(design) */
(function () {
const CDN = 'https://cdn.jsdelivr.net/';
const NN = CDN + 'gh/projectnoonnu/';
const PRE = CDN + 'npm/pretendard@1.3.9/dist/web/static/woff2/Pretendard-';
// 요즘 많이 쓰는 한글 글꼴 (모두 상업 이용 무료). weights: {굵기: 파일} — 변수 글꼴은 range
const FONTS = {
  pretendard: { name: '프리텐다드', family: 'SG Pretendard', weights: { 400: PRE + 'Regular.woff2', 600: PRE + 'SemiBold.woff2', 700: PRE + 'Bold.woff2', 800: PRE + 'ExtraBold.woff2', 900: PRE + 'Black.woff2' } },
  gmarket: { name: '지마켓 산스', family: 'SG Gmarket', weights: { 300: NN + 'noonfonts_2001@1.1/GmarketSansLight.woff', 500: NN + 'noonfonts_2001@1.1/GmarketSansMedium.woff', 700: NN + 'noonfonts_2001@1.1/GmarketSansBold.woff' } },
  hanna: { name: '배민 한나체 Pro', family: 'SG BMHanna', weights: { 400: NN + 'noonfonts_seven@1.0/BMHANNAPro.woff' } },
  jua: { name: '배민 주아체', family: 'SG BMJua', weights: { 400: NN + 'noonfonts_one@1.0/BMJUA.woff' } },
  dohyeon: { name: '배민 도현체', family: 'SG BMDohyeon', weights: { 400: NN + 'noonfonts_one@1.0/BMDOHYEON.woff' } },
  euljiro: { name: '배민 을지로체', family: 'SG BMEuljiro', weights: { 400: NN + 'noonfonts_twelve@1.0/BMEULJIRO.woff' } },
  hannaair: { name: '배민 한나 Air', family: 'SG BMHannaAir', weights: { 400: NN + 'noonfonts_four@1.0/BMHANNAAir.woff' } },
  jalnan: { name: '여기어때 잘난체', family: 'SG Jalnan', weights: { 700: NN + 'noonfonts_four@1.2/JalnanOTF00.woff' } },
  paperlogy: { name: '페이퍼로지', family: 'SG Paperlogy', weights: { 400: NN + '2408-3@1.0/Paperlogy-4Regular.woff2', 700: NN + '2408-3@1.0/Paperlogy-7Bold.woff2', 900: NN + '2408-3@1.0/Paperlogy-9Black.woff2' } },
  score: { name: '에스코어 드림', family: 'SG SCore', weights: { 400: NN + 'noonfonts_six@1.2/S-CoreDream-4Regular.woff', 700: NN + 'noonfonts_six@1.2/S-CoreDream-6Bold.woff', 900: NN + 'noonfonts_six@1.2/S-CoreDream-8Heavy.woff' } },
  suit: { name: 'SUIT', family: 'SG SUIT', variable: CDN + 'gh/sun-typeface/SUIT@2.0.5/fonts/variable/woff2/SUIT-Variable.woff2', weights: { 400: 1, 700: 1, 900: 1 } },
  nanumsq: { name: '나눔스퀘어 네오', family: 'SG NanumSquareNeo', variable: NN + 'noonfonts_11-01@1.0/NanumSquareNeo-Variable.woff2', weights: { 400: 1, 700: 1, 900: 1 } },
  ssurround: { name: '카페24 써라운드', family: 'SG Ssurround', weights: { 700: NN + 'noonfonts_2105_2@1.0/Cafe24Ssurround.woff' } },
  maru: { name: '마루 부리 (명조)', family: 'SG MaruBuri', weights: { 400: NN + 'noonfonts_20-10-21@1.0/MaruBuri-Regular.woff' } },
  dahyun: { name: '온글잎 박다현 (손글씨)', family: 'SG Dahyun', weights: { 400: NN + '2411-3@1.0/Ownglyph_ParkDaHyun.woff2' } },
};
const BODY = 'pretendard';

// 디자인 12종: 기본 제목 글꼴·굵기
const TEMPLATES = {
  clean:    { name: '화이트 클린', font: 'pretendard', w: 'black' },
  bold:     { name: '컬러 블록', font: 'gmarket', w: 'bold' },
  midnight: { name: '미드나잇 네온', font: 'pretendard', w: 'black' },
  gradient: { name: '그라데이션', font: 'paperlogy', w: 'black' },
  luxury:   { name: '블랙 골드', font: 'maru', w: 'regular' },
  pop:      { name: '팝 스티커', font: 'hanna', w: 'bold' },
  kraft:    { name: '카페 크라프트', font: 'jua', w: 'bold' },
  receipt:  { name: '영수증 컨셉', font: 'dohyeon', w: 'bold' },
  coupon:   { name: '쿠폰 티켓', font: 'jalnan', w: 'bold' },
  split:    { name: '투톤 분할', font: 'score', w: 'black' },
  minimal:  { name: '미니멀 라인', font: 'suit', w: 'bold' },
  glass:    { name: '글래스', font: 'nanumsq', w: 'black' },
};
const OLD = { neon: 'midnight' };   // 예전 디자인 이름

// 크기: 인쇄용은 mm (96dpi 로 그림 → 300dpi 로 저장), 태블릿은 화면 픽셀 (가로)
const SIZES = {
  a6:     { name: 'A6', sub: '105×148mm · 테이블용', mm: [105, 148] },
  a5:     { name: 'A5', sub: '148×210mm · 카운터·입구', mm: [148, 210] },
  square: { name: '정사각', sub: '100×100mm · 아크릴 스탠드', mm: [100, 100] },
  tablet: { name: '태블릿 가로 16:10', sub: '1920×1200 · 테이블오더 대기화면', px: [1280, 800], out: 1.5 },
  tablet169: { name: '태블릿 가로 16:9', sub: '1920×1080 · 와이드 태블릿', px: [1280, 720], out: 1.5 },
};
const MM = 96 / 25.4;

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function tplOf(d) { const t = OLD[d.template] || d.template; return TEMPLATES[t] ? t : 'clean'; }

// 안내판 실제 크기 (CSS px) + 저장 배율 + 가로형 여부
window.signSize = function (d) {
  const s = SIZES[d.size];
  let w, h, out = 300 / 96;
  if (s && s.px) { [w, h] = s.px; out = s.out; }
  else if (s) { w = s.mm[0] * MM; h = s.mm[1] * MM; }
  else { w = (d.customW || 105) * MM; h = (d.customH || 148) * MM; }
  const land = w > h * 1.15;
  // 글자 크기 기준: 세로는 폭 400 기준, 가로는 800×500 기준
  const fs = land ? Math.min(w / 800, h / 500) * 16 : Math.min(w / 400, h / 565) * 16;
  return { w: Math.round(w), h: Math.round(h), out, land, fs };
};

function weightFor(fontKey, want) {
  const ws = Object.keys(FONTS[fontKey].weights).map(Number).sort((a, b) => a - b);
  const target = { regular: 400, bold: 700, black: 900 }[want] || 700;
  return ws.reduce((best, x) => Math.abs(x - target) < Math.abs(best - target) ? x : best, ws[0]);
}
function titleFont(d) {
  const key = FONTS[d.titleFont] ? d.titleFont : TEMPLATES[tplOf(d)].font;
  const w = weightFor(key, d.titleWeight && d.titleWeight !== 'auto' ? d.titleWeight : TEMPLATES[tplOf(d)].w);
  return { key, w };
}
window.signFontsUsed = function (d) {
  const t = titleFont(d), b = FONTS[d.bodyFont] ? d.bodyFont : BODY;
  return [[t.key, t.w], [b, 400], [b, 700], [b, 800]].filter(([k, w]) => FONTS[k].weights[w] || FONTS[k].variable)
    .concat([[t.key, t.w]]);
};
window.signFontFace = function () {
  const out = [];
  for (const k in FONTS) {
    const f = FONTS[k];
    if (f.variable) out.push(`@font-face{font-family:'${f.family}';src:url('${f.variable}') format('woff2');font-weight:100 900;font-display:swap}`);
    else for (const w in f.weights) out.push(`@font-face{font-family:'${f.family}';src:url('${f.weights[w]}');font-weight:${w};font-display:swap}`);
  }
  return out.join('\n');
};
window.signFontFile = function (key, w) { const f = FONTS[key]; return f.variable || f.weights[w]; };

// ── 그림: 손님 휴대폰에서 일어나는 일 (QR → 영수증 자동 저장 → 리뷰 글 복사·붙여넣기) ──
function phone(inner) {
  return `<svg viewBox="0 0 60 104" class="ph" aria-hidden="true"><rect x="2" y="2" width="56" height="100" rx="10" class="ph-body"/>` +
    `<rect x="6" y="10" width="48" height="84" rx="4" class="ph-screen"/><rect x="23" y="5" width="14" height="2.4" rx="1.2" class="ph-notch"/>${inner}</svg>`;
}
const ICONS = {
  qr: phone(`<g class="ph-ink"><rect x="14" y="26" width="13" height="13" rx="1.5"/><rect x="33" y="26" width="13" height="13" rx="1.5"/><rect x="14" y="45" width="13" height="13" rx="1.5"/>
    <rect x="34" y="46" width="4" height="4"/><rect x="40" y="46" width="6" height="4"/><rect x="34" y="52" width="12" height="6"/></g>
    <g class="ph-hole"><rect x="17.5" y="29.5" width="6" height="6"/><rect x="36.5" y="29.5" width="6" height="6"/><rect x="17.5" y="48.5" width="6" height="6"/></g>
    <path class="ph-acc-stroke" d="M10 20 h6 M10 20 v6 M50 20 h-6 M50 20 v6 M10 66 h6 M10 66 v-6 M50 66 h-6 M50 66 v-6" fill="none" stroke-width="2.4" stroke-linecap="round"/>
    <rect x="12" y="74" width="36" height="9" rx="4.5" class="ph-acc"/><text x="30" y="80.6" class="ph-btn-t">찰칵</text>`),
  save: phone(`<path class="ph-paper" d="M16 16 h28 v42 l-3.5 3 -3.5 -3 -3.5 3 -3.5 -3 -3.5 3 -3.5 -3 -3.5 3 -3.5 -3z"/>
    <g class="ph-line"><rect x="20" y="22" width="20" height="2.4" rx="1"/><rect x="20" y="28" width="14" height="2" rx="1"/><rect x="20" y="33" width="18" height="2" rx="1"/><rect x="20" y="38" width="12" height="2" rx="1"/><rect x="20" y="46" width="20" height="3" rx="1"/></g>
    <circle cx="30" cy="74" r="9" class="ph-acc"/><path d="M30 69 v8 M26.5 74 l3.5 3.5 3.5-3.5" class="ph-white-stroke" fill="none" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>`),
  paste: phone(`<rect x="11" y="18" width="38" height="34" rx="3" class="ph-field"/>
    <g class="ph-line"><rect x="15" y="23" width="28" height="2.4" rx="1"/><rect x="15" y="29" width="30" height="2.4" rx="1"/><rect x="15" y="35" width="22" height="2.4" rx="1"/></g>
    <rect x="38.5" y="34" width="1.6" height="5" class="ph-acc"/>
    <rect x="13" y="58" width="34" height="11" rx="5.5" class="ph-acc"/><text x="30" y="65.6" class="ph-btn-t">붙여넣기</text>
    <path d="M24 82 l4 4 8-8" class="ph-acc-stroke" fill="none" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>`),
};
const ICON_GIFT = `<svg viewBox="0 0 24 24" class="ic-gift" aria-hidden="true"><path d="M3 10h18v4H3zM5 14h14v7H5z" fill="currentColor" opacity=".9"/><path d="M12 10v11" stroke="#fff" stroke-width="2"/><path d="M12 10c-2-4-6-5-6-2 0 1.6 2.4 2 6 2zm0 0c2-4 6-5 6-2 0 1.6-2.4 2-6 2z" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>`;

function flowHTML() {
  const steps = [['qr', 'QR 찍기', '번호만 입력'], ['save', '영수증 자동 저장', '요청할 필요 없어요'], ['paste', '리뷰 글 붙여넣기', '글도 자동으로 준비']];
  return `<div class="s-flow">${steps.map(([k, t, s], i) =>
    `<div class="fl"><div class="fl-ic">${ICONS[k]}<span class="fl-no">${i + 1}</span></div><div class="fl-t">${t}</div><div class="fl-s">${s}</div></div>` +
    (i < 2 ? '<div class="fl-arr" aria-hidden="true">›</div>' : '')).join('')}</div>`;
}

window.signHTML = function (d, qrSrc, tableLabel) {
  const t = tplOf(d);
  const lines = esc(d.headline || '').split(/\r?\n/).filter(s => s.trim());
  const steps = esc(d.steps || '').split(/\r?\n/).filter(s => s.trim());
  const logo = d.logo && /^data:image\/(png|jpe?g|gif|webp);base64,/.test(d.logo) ? d.logo : null;
  const guide = ['pic', 'text', 'both'].includes(d.guide) ? d.guide : 'pic';
  const table = esc(tableLabel || '');
  const qr = `<div class="s-qr"><div class="s-qr-box"><img src="${qrSrc}" alt="QR"></div><div class="s-qr-cap">카메라로 QR을 찍어 주세요</div></div>`;
  return `<div class="sg-in">
    <i class="deco d1"></i><i class="deco d2"></i><i class="deco d3"></i>
    <div class="s-top">
      ${logo ? `<img class="s-logo" src="${logo}" alt="">` : ''}
      <div class="s-store">${esc(d.storeName)}</div>
      ${table ? `<div class="s-table">${table}</div>` : ''}
    </div>
    <div class="s-left">
      <div class="s-hero">
        <div class="s-kicker"><span class="nv">N</span>영수증 리뷰</div>
        ${lines[0] ? `<div class="s-head">${lines[0]}</div>` : ''}
        ${lines[1] ? `<div class="s-sub">${lines[1]}</div>` : ''}
      </div>
      ${d.benefit ? `<div class="s-benefit">${ICON_GIFT}<span>${esc(d.benefit)}</span></div>` : ''}
      ${guide !== 'text' ? flowHTML() : ''}
      ${guide !== 'pic' && steps.length ? `<ol class="s-steps">${steps.map((s, i) => `<li><b>${i + 1}</b><span>${s}</span></li>`).join('')}</ol>` : ''}
    </div>
    <div class="s-right">${qr}</div>
    <div class="s-foot">영수증리뷰 자동완성 서비스</div>
  </div>`;
};

// 안내판 상자 꾸미기 (클래스·크기·글꼴·색 변수)
window.signApply = function (el, d, mix) {
  const z = window.signSize(d), t = tplOf(d), tf = titleFont(d), bf = FONTS[d.bodyFont] ? d.bodyFont : BODY;
  el.className = `sign t-${t} ${z.land ? 'land' : 'port'}${(d.guide || 'pic') === 'both' ? ' g-both' : ''}${(d.guide || 'pic') === 'text' ? ' g-text' : ''}`;
  // 굵기가 한 가지뿐인 글꼴(배민체 등)에 '아주 굵게' → 글자 테두리로 더 굵게
  if (d.titleWeight === 'black' && Object.keys(FONTS[tf.key].weights).length === 1) el.classList.add('fx-bold');
  el.style.width = z.w + 'px'; el.style.height = z.h + 'px'; el.style.fontSize = z.fs.toFixed(3) + 'px';
  const c = d.color || '#03C75A';
  el.style.setProperty('--ac', c);
  el.style.setProperty('--ac-d', mix(c, '#000000', .22));
  el.style.setProperty('--ac-dd', mix(c, '#000000', .55));
  el.style.setProperty('--ac-l', mix(c, '#ffffff', .82));
  el.style.setProperty('--ac-ll', mix(c, '#ffffff', .93));
  el.style.setProperty('--ac-m', mix(c, '#ffffff', .45));
  el.style.setProperty('--tf', `'${FONTS[tf.key].family}'`);
  el.style.setProperty('--tw', tf.w);
  el.style.setProperty('--bf', `'${FONTS[bf].family}'`);
  return z;
};

// 글꼴마다 글자 폭이 달라 큰 제목·혜택이 두 줄로 넘치면 한 줄에 맞게 조금씩 줄임 (글꼴 불러온 뒤 호출)
window.signFit = function (el) {
  el.querySelectorAll('.s-head, .s-sub, .s-benefit, .s-store').forEach(n => {
    n.style.fontSize = ''; n.style.whiteSpace = 'nowrap';
    const box = n.parentElement;
    let avail = box.clientWidth - parseFloat(getComputedStyle(box).paddingLeft) - parseFloat(getComputedStyle(box).paddingRight);
    if (n.classList.contains('s-store')) [...box.children].forEach(c => { if (c !== n && getComputedStyle(c).position !== 'absolute') avail -= c.offsetWidth + 8; });
    if (n.classList.contains('s-store') && el.classList.contains('port')) { const t = box.querySelector('.s-table'); if (t) avail -= 2 * t.offsetWidth + 8; }
    const need = () => Math.max(n.scrollWidth, n.getBoundingClientRect().width / (el.getBoundingClientRect().width / el.offsetWidth || 1));
    let fs = parseFloat(getComputedStyle(n).fontSize), i = 0;
    while (need() > avail + 1 && i++ < 18) { fs *= 0.95; n.style.fontSize = fs + 'px'; }
    if (need() > avail + 1) n.style.whiteSpace = '';    // 그래도 넘치면 줄바꿈 허용
  });
};

window.SIGN_FONTS = FONTS;
window.SIGN_TEMPLATES = TEMPLATES;
window.SIGN_SIZES = SIZES;
window.signTemplateKey = tplOf;
window.signWeightsOf = k => Object.keys(FONTS[k] ? FONTS[k].weights : {}).length;
})();
