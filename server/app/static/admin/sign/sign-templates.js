/* 테이블 안내판 템플릿 4종 (원본: table-sign-editor.html)
 * signHTML(design, qrImgSrc, tableLabel) → 안내판 안쪽 HTML. 글자는 모두 이스케이프. */
(function () {
let V = {};
let qrSvg = '';
const naverBadge = `<div class="naver-badge"><span class="naver-logo">N</span><span>영수증리뷰</span></div>`;
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
const templates = {
  glass: () => `
    ${V.tableNo ? `<div class="table-badge">${V.tableNo}</div>` : ''}
    <div class="sign-header">
      ${V.logo ? `<img src="${V.logo}" class="sign-logo">` : ''}
      <div class="sign-store">${V.storeName}</div>
    </div>
    <div class="sign-benefit-wrap">
      <div class="sign-benefit">${V.benefit}</div>
    </div>
    <div class="sign-qr-section">
      <div class="sign-qr">${qrSvg}</div>
      <div class="sign-qr-label">QR 스캔하고 참여하기</div>
      ${naverBadge}
    </div>
    <ol class="sign-steps">${V.steps.split('\n').map((s, i) => `<li><span class="step-num">${i+1}</span>${s}</li>`).join('')}</ol>
  `,

  neon: () => `
    ${V.tableNo ? `<div class="table-badge">${V.tableNo}</div>` : ''}
    <div class="sign-header">
      ${V.logo ? `<img src="${V.logo}" class="sign-logo">` : ''}
      <div class="sign-title">리뷰 이벤트</div>
      <div class="sign-store">${V.storeName}</div>
    </div>
    <div class="sign-benefit-wrap">
      <div class="sign-benefit">${V.benefit}</div>
    </div>
    <div class="sign-qr-section">
      <div class="sign-qr">${qrSvg}</div>
      <div class="sign-qr-label">👆 QR 스캔하기</div>
      ${naverBadge}
    </div>
    <ol class="sign-steps">${V.steps.split('\n').map(s => `<li>${s}</li>`).join('')}</ol>
  `,

  minimal: () => `
    ${V.tableNo ? `<div class="table-badge">${V.tableNo}</div>` : ''}
    <div class="sign-header">
      ${V.logo ? `<img src="${V.logo}" class="sign-logo">` : ''}
      <div class="sign-store">${V.storeName}</div>
    </div>
    <div class="sign-benefit">${V.benefit}</div>
    <div class="sign-qr-section">
      <div class="sign-qr">${qrSvg}</div>
      <div class="sign-qr-label">SCAN TO REVIEW</div>
      ${naverBadge}
    </div>
    <ol class="sign-steps">${V.steps.split('\n').map((s, i) => `<li>${i+1}. ${s}</li>`).join('')}</ol>
  `,

  luxury: () => `
    <div class="sign-header">
      ${V.logo ? `<img src="${V.logo}" class="sign-logo" style="filter:none">` : ''}
      <div class="sign-store">${V.storeName}</div>
    </div>
    <div class="sign-body">
      <div class="sign-benefit">${V.benefit.replace(/(.+?)(!|$)/, '<strong>$1</strong>$2')}</div>
      <div class="sign-qr-section">
        <div class="sign-qr">${qrSvg}</div>
        <div class="sign-qr-label">SCAN QR CODE</div>
        ${naverBadge}
      </div>
      <ol class="sign-steps">${V.steps.split('\n').map(s => `<li>${s}</li>`).join('')}</ol>
    </div>
    <div class="sign-footer">${V.tableNo || '영수증리뷰 자동완성 서비스'}</div>
  `
};

window.signHTML = function (d, qrSrc, tableLabel) {
  V = {
    storeName: esc(d.storeName),
    benefit: esc(d.benefit),
    steps: esc(d.steps || '').split(/\r?\n/).filter(s => s.trim()).join('\n'),
    tableNo: esc(tableLabel || ''),
    logo: d.logo && /^data:image\/(png|jpe?g|gif|webp);base64,/.test(d.logo) ? d.logo : null,
  };
  qrSvg = `<img src="${qrSrc}" alt="QR" style="width:100%;height:100%;display:block;image-rendering:pixelated">`;
  const html = (templates[d.template] || templates.glass)();
  // 완전자동 안내 (손님이 일반 네이버 영수증 QR 과 구분하도록) — 혜택 문구 바로 위
  const lines = esc(d.headline || '').split(/\r?\n/).filter(s => s.trim());
  if (!lines.length) return html;
  const auto = `<div class="sign-auto"><div class="sign-auto-main">${lines[0]}</div>` +
    (lines[1] ? `<div class="sign-auto-sub">${lines[1]}</div>` : '') + `</div>`;
  const i = html.indexOf('<div class="sign-benefit');
  return i < 0 ? auto + html : html.slice(0, i) + auto + html.slice(i);
};
window.SIGN_TEMPLATES = Object.keys(templates);
})();
