/**
 * 영수증리뷰 - 손님 모바일 웹 JavaScript
 */

(function() {
    'use strict';

    // 브라우저 감지
    const BrowserDetect = {
        ua: navigator.userAgent,

        get isIOS() {
            return /iPad|iPhone|iPod/.test(this.ua);
        },

        get isAndroid() {
            return /Android/.test(this.ua);
        },

        get isKakaoTalk() {
            return /KAKAOTALK/.test(this.ua);
        },

        get isNaverApp() {
            return /NAVER\(inapp/.test(this.ua);
        },

        get isInstagram() {
            return /Instagram/.test(this.ua);
        },

        get isFacebook() {
            return /FBAN|FBAV/.test(this.ua);
        },

        get isLine() {
            return /\bLine\//.test(this.ua);
        },

        get isInApp() {
            return this.isKakaoTalk || this.isNaverApp || this.isInstagram || this.isFacebook || this.isLine;
        },

        get browserName() {
            if (this.isKakaoTalk) return '카카오톡';
            if (this.isNaverApp) return '네이버앱';
            if (this.isInstagram) return '인스타그램';
            if (this.isFacebook) return '페이스북';
            if (this.isLine) return '라인';
            if (/SamsungBrowser/.test(this.ua)) return '삼성인터넷';
            if (/Chrome/.test(this.ua) && !/Edg/.test(this.ua)) return 'Chrome';
            if (/Safari/.test(this.ua) && !/Chrome/.test(this.ua)) return 'Safari';
            if (/Firefox/.test(this.ua)) return 'Firefox';
            return '기타';
        }
    };

    // 인앱 브라우저 처리
    const InAppHandler = {
        tryOpenExternal() {
            const currentUrl = window.location.href;

            if (BrowserDetect.isKakaoTalk) {
                // 카카오톡 외부 브라우저 열기
                window.location.href = `kakaotalk://web/openExternal?url=${encodeURIComponent(currentUrl)}`;
                return true;
            }

            if (BrowserDetect.isLine) {
                // 라인 외부 브라우저
                const newUrl = currentUrl.includes('?')
                    ? `${currentUrl}&openExternalBrowser=1`
                    : `${currentUrl}?openExternalBrowser=1`;
                window.location.href = newUrl;
                return true;
            }

            return false;
        },

        showExternalBrowserGuide() {
            const guide = document.createElement('div');
            guide.className = 'inapp-guide';
            guide.innerHTML = `
                <div class="inapp-guide__content">
                    <div class="inapp-guide__icon">🌐</div>
                    <p class="inapp-guide__text">
                        더 나은 경험을 위해<br>
                        <strong>외부 브라우저</strong>에서 열어주세요
                    </p>
                    <p class="inapp-guide__hint">
                        오른쪽 위 ⋯ → 외부 브라우저로 열기
                    </p>
                    <button class="btn btn--secondary inapp-guide__continue">
                        그냥 계속하기
                    </button>
                </div>
            `;

            document.body.appendChild(guide);

            guide.querySelector('.inapp-guide__continue').addEventListener('click', () => {
                guide.remove();
            });
        }
    };

    // 전화번호 포맷팅
    const PhoneFormatter = {
        format(value) {
            const numbers = value.replace(/\D/g, '');

            if (numbers.length <= 3) {
                return numbers;
            } else if (numbers.length <= 7) {
                return `${numbers.slice(0, 3)}-${numbers.slice(3)}`;
            } else {
                return `${numbers.slice(0, 3)}-${numbers.slice(3, 7)}-${numbers.slice(7, 11)}`;
            }
        },

        validate(value) {
            const numbers = value.replace(/\D/g, '');
            return /^01[016789]\d{7,8}$/.test(numbers);
        },

        normalize(value) {
            return value.replace(/\D/g, '');
        }
    };

    // 현재 세션 id (서버가 화면에 넣어줌, 없으면 이전 화면에서 저장한 값)
    function currentSessionId() {
        return window.SESSION_ID || sessionStorage.getItem('sessionId') || '';
    }

    // 클립보드
    const Clipboard = {
        /** 사용자 탭 핸들러 안에서 await 없이 바로 호출할 것 (iOS 제스처 제한) */
        copySync(text) {
            let ok = false;
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.setAttribute('readonly', '');
            textarea.style.cssText = 'position:fixed;left:0;top:0;opacity:0;font-size:16px;';
            document.body.appendChild(textarea);
            const range = document.createRange();
            range.selectNodeContents(textarea);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
            textarea.setSelectionRange(0, text.length);
            try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
            document.body.removeChild(textarea);
            sel.removeAllRanges();
            // 최신 API 도 함께 시도 (실패해도 무시)
            if (navigator.clipboard && navigator.clipboard.writeText) {
                const p = navigator.clipboard.writeText(text).then(() => true).catch(() => ok);
                return ok ? Promise.resolve(true) : p;
            }
            return Promise.resolve(ok);
        },

        async copy(text) {
            try {
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    await navigator.clipboard.writeText(text);
                    return true;
                }
            } catch (e) {
                console.log('Clipboard API failed, trying execCommand');
            }

            // 폴백: execCommand
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.style.cssText = 'position:fixed;left:-9999px;top:0';
            document.body.appendChild(textarea);
            textarea.select();
            textarea.setSelectionRange(0, textarea.value.length);

            try {
                const success = document.execCommand('copy');
                document.body.removeChild(textarea);
                return success;
            } catch (e) {
                document.body.removeChild(textarea);
                return false;
            }
        }
    };

    // 이미지 저장
    const ImageSaver = {
        async saveFromUrl(imageUrl, filename = 'receipt.png') {
            try {
                const response = await fetch(imageUrl);
                const blob = await response.blob();
                return await this.saveBlob(blob, filename);
            } catch (e) {
                console.error('Image fetch failed:', e);
                return false;
            }
        },

        async saveBlob(blob, filename = 'receipt.png') {
            const file = new File([blob], filename, { type: blob.type || 'image/png' });

            // iOS: Web Share API
            if (BrowserDetect.isIOS && navigator.share && navigator.canShare) {
                try {
                    if (navigator.canShare({ files: [file] })) {
                        await navigator.share({ files: [file], title: '영수증' });
                        return 'shared';
                    }
                } catch (e) {
                    if (e.name !== 'AbortError') {
                        console.error('Share failed:', e);
                    }
                    return false;
                }
            }

            // Android / Desktop: 다운로드
            try {
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                setTimeout(() => URL.revokeObjectURL(url), 100);
                return 'downloaded';
            } catch (e) {
                console.error('Download failed:', e);
                return false;
            }
        }
    };

    // 토스트 메시지
    const Toast = {
        show(message, type = 'info', duration = 3000) {
            const existing = document.querySelector('.toast');
            if (existing) existing.remove();

            const toast = document.createElement('div');
            toast.className = `toast toast--${type}`;
            toast.innerHTML = `
                <span class="toast__icon">${type === 'success' ? '✓' : type === 'error' ? '✗' : 'ℹ'}</span>
                <span class="toast__message">${message}</span>
            `;

            // 스타일 추가
            toast.style.cssText = `
                position: fixed;
                bottom: calc(100px + env(safe-area-inset-bottom, 0));
                left: 50%;
                transform: translateX(-50%);
                display: flex;
                align-items: center;
                gap: 8px;
                padding: 12px 20px;
                background: ${type === 'success' ? '#03C75A' : type === 'error' ? '#ff4757' : '#1a1a1a'};
                color: white;
                border-radius: 12px;
                font-size: 15px;
                font-weight: 500;
                box-shadow: 0 4px 16px rgba(0,0,0,0.2);
                z-index: 9999;
                animation: toastIn 0.3s ease;
            `;

            document.body.appendChild(toast);

            setTimeout(() => {
                toast.style.animation = 'toastOut 0.3s ease forwards';
                setTimeout(() => toast.remove(), 300);
            }, duration);
        }
    };

    // 토스트 애니메이션 스타일
    const toastStyle = document.createElement('style');
    toastStyle.textContent = `
        @keyframes toastIn {
            from { opacity: 0; transform: translateX(-50%) translateY(20px); }
            to { opacity: 1; transform: translateX(-50%) translateY(0); }
        }
        @keyframes toastOut {
            from { opacity: 1; transform: translateX(-50%) translateY(0); }
            to { opacity: 0; transform: translateX(-50%) translateY(20px); }
        }
        .inapp-guide {
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.6);
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 24px;
            z-index: 10000;
        }
        .inapp-guide__content {
            background: white;
            border-radius: 16px;
            padding: 32px 24px;
            text-align: center;
            max-width: 300px;
        }
        .inapp-guide__icon {
            font-size: 48px;
            margin-bottom: 16px;
        }
        .inapp-guide__text {
            font-size: 17px;
            line-height: 1.5;
            margin-bottom: 12px;
        }
        .inapp-guide__hint {
            font-size: 14px;
            color: #666;
            margin-bottom: 20px;
        }
    `;
    document.head.appendChild(toastStyle);

    // 화면 1: 전화번호 입력
    const PhoneInputPage = {
        init() {
            const phoneInput = document.getElementById('phoneInput');
            const submitBtn = document.getElementById('submitPhone');
            const privacyCheck = document.getElementById('privacyAgree');

            if (!phoneInput) return;

            // 전화번호 포맷팅
            phoneInput.addEventListener('input', (e) => {
                const formatted = PhoneFormatter.format(e.target.value);
                e.target.value = formatted;
                this.validateForm();
            });

            // 체크박스 변경
            privacyCheck?.addEventListener('change', () => this.validateForm());

            // 제출
            submitBtn?.addEventListener('click', () => this.submit());

            // 엔터키
            phoneInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') this.submit();
            });
        },

        validateForm() {
            const phoneInput = document.getElementById('phoneInput');
            const submitBtn = document.getElementById('submitPhone');
            const privacyCheck = document.getElementById('privacyAgree');

            const phoneValid = PhoneFormatter.validate(phoneInput.value);
            const privacyValid = privacyCheck?.checked;

            submitBtn.disabled = !(phoneValid && privacyValid);
        },

        async submit() {
            const phoneInput = document.getElementById('phoneInput');
            const marketingCheck = document.getElementById('marketingAgree');
            const submitBtn = document.getElementById('submitPhone');
            const errorEl = document.getElementById('errorMessage');

            const phone = PhoneFormatter.normalize(phoneInput.value);
            const marketingOptIn = marketingCheck?.checked || false;

            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="loading__spinner"></span> 처리 중...';

            try {
                const url = `/api/v1/session/start?store_code=${encodeURIComponent(window.STORE_CODE)}`;
                const response = await fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        phone,
                        table_no: window.TABLE_NO,
                        marketing_opt_in: marketingOptIn
                    })
                });

                const data = await response.json();

                if (response.ok) {
                    // 세션 저장 (서버도 쿠키로 기억함)
                    sessionStorage.setItem('sessionId', data.session_id);

                    // 오늘 이미 영수증을 받은 손님이면 바로 결과 화면으로
                    if (data.is_returning && data.existing_receipt_id) {
                        Toast.show('오늘 이미 참여하셨어요. 받으신 영수증을 다시 보여드릴게요', 'info', 2000);
                        window.location.href = `/t/${window.STORE_CODE}/${window.TABLE_NO}/result`;
                    } else {
                        window.location.href = `/t/${window.STORE_CODE}/${window.TABLE_NO}/keywords`;
                    }
                } else {
                    const errMsg = typeof data.detail === 'string' ? data.detail :
                                   (data.detail?.msg || data.message || JSON.stringify(data.detail) || '오류가 발생했습니다');
                    throw new Error(errMsg);
                }
            } catch (e) {
                errorEl.textContent = e.message || '오류가 발생했습니다';
                errorEl.classList.add('visible');
                submitBtn.disabled = false;
                submitBtn.textContent = '다음';
            }
        }
    };

    // 화면 2: 키워드 선택
    const KeywordsPage = {
        selectedKeywords: new Set(),

        init() {
            const chips = document.querySelectorAll('.keyword-chip');
            const submitBtn = document.getElementById('submitKeywords');

            if (!chips.length) return;

            // 기본 선택된 키워드
            chips.forEach(chip => {
                if (chip.classList.contains('active')) {
                    this.selectedKeywords.add(chip.dataset.keyword);
                }

                chip.addEventListener('click', () => {
                    chip.classList.toggle('active');

                    if (chip.classList.contains('active')) {
                        this.selectedKeywords.add(chip.dataset.keyword);
                    } else {
                        this.selectedKeywords.delete(chip.dataset.keyword);
                    }
                });
            });

            submitBtn?.addEventListener('click', () => this.submit());
        },

        async submit() {
            const submitBtn = document.getElementById('submitKeywords');
            const sessionId = currentSessionId();

            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="loading__spinner"></span> 처리 중...';

            try {
                const response = await fetch(`/api/v1/session/${sessionId}/keywords`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        keywords: Array.from(this.selectedKeywords)
                    })
                });

                if (response.ok) {
                    window.location.href = `/t/${window.STORE_CODE}/${window.TABLE_NO}/result`;
                } else {
                    const data = await response.json();
                    throw new Error(data.detail || '오류가 발생했습니다');
                }
            } catch (e) {
                Toast.show(e.message, 'error');
                submitBtn.disabled = false;
                submitBtn.textContent = '다음';
            }
        }
    };

    // 화면 3: 결과
    const ResultPage = {
        receiptBlob: null,

        async init() {
            const mainBtn = document.getElementById('mainAction');
            const regenerateBtn = document.getElementById('regenerateText');
            const receiptImg = document.getElementById('receiptImage');

            if (!mainBtn) return;

            // 메인 버튼 (이미지 준비 전에도 누를 수 있게 먼저 연결)
            mainBtn.addEventListener('click', (e) => this.handleMainAction(e));

            // 문구 재생성
            regenerateBtn?.addEventListener('click', () => this.regenerateText());

            // 문구 수정 → 서버 저장
            const textEl = document.getElementById('reviewText');
            textEl?.addEventListener('blur', () => this.saveEditedText());

            // 영수증 이미지 미리 받아두기 (iOS 공유는 탭 순간에 파일이 준비돼 있어야 함)
            if (receiptImg && receiptImg.getAttribute('src')) {
                try {
                    const response = await fetch(receiptImg.getAttribute('src'), { credentials: 'same-origin' });
                    if (response.ok) {
                        this.receiptBlob = await response.blob();
                        this.receiptFile = new File([this.receiptBlob], `receipt_${Date.now()}.png`, { type: 'image/png' });
                    }
                } catch (e) {
                    console.error('Receipt preload failed:', e);
                }
            }
        },

        async saveEditedText() {
            const textEl = document.getElementById('reviewText');
            const text = textEl?.innerText?.trim();
            if (!text || text === this.lastSavedText) return;
            this.lastSavedText = text;
            try {
                await fetch(`/api/v1/session/${currentSessionId()}/text`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text })
                });
            } catch (e) {
                console.error('Text save failed:', e);
            }
        },

        goNaver() {
            const naverUrl = window.NAVER_REVIEW_URL;
            if (!naverUrl) {
                Toast.show('매장의 네이버 리뷰 주소가 아직 설정되지 않았어요. 직원에게 알려주세요.', 'error', 4000);
                return;
            }
            this.recordEvent('redirected');
            window.location.href = naverUrl;
        },

        handleMainAction(e) {
            e.preventDefault();
            const mainBtn = document.getElementById('mainAction');

            // 두 번째 탭 (iOS: 저장 후 네이버로 이동)
            if (this.readyToGo) {
                this.goNaver();
                return;
            }

            const reviewText = document.getElementById('reviewText')?.innerText?.trim() || '';

            // ▼ 여기부터는 await 없이 탭 순간에 바로 시작해야 함 (iOS 제한)
            const copyPromise = Clipboard.copySync(reviewText);

            let sharePromise = null;
            const canShareFile = BrowserDetect.isIOS && this.receiptFile && navigator.share && navigator.canShare
                && navigator.canShare({ files: [this.receiptFile] });
            if (canShareFile) {
                sharePromise = navigator.share({ files: [this.receiptFile], title: '영수증' });
            }
            // ▲

            this.saveEditedText();

            if (sharePromise) {
                // iOS: 공유창에서 "이미지 저장" → 닫히면 [네이버로 이동] 버튼
                sharePromise.then(() => {
                    this.recordEvent('downloaded');
                }).catch((err) => {
                    if (err && err.name !== 'AbortError') console.error('Share failed:', err);
                }).finally(() => {
                    this.readyToGo = true;
                    mainBtn.disabled = false;
                    mainBtn.innerHTML = '<span>저장했으면</span><strong>네이버로 이동</strong>';
                    mainBtn.classList.add('btn--pulse');
                    copyPromise.then((ok) => {
                        Toast.show(ok ? '문구가 복사되었어요. 네이버 글 입력칸에 붙여넣으세요' : '문구를 길게 눌러 복사해 주세요', ok ? 'success' : 'info', 3000);
                    });
                });
                return;
            }

            if (BrowserDetect.isIOS && !this.receiptFile) {
                // 이미지 준비 실패 → 길게 눌러 저장 안내
                Toast.show('영수증 이미지를 길게 눌러 "사진에 저장"을 선택해 주세요', 'info', 4000);
                this.readyToGo = true;
                mainBtn.innerHTML = '<span>저장했으면</span><strong>네이버로 이동</strong>';
                return;
            }

            // Android / 기타: 다운로드 후 1초 뒤 네이버로
            mainBtn.disabled = true;
            mainBtn.innerHTML = '<span class="loading__spinner"></span> 저장 중...';
            if (this.receiptBlob) {
                ImageSaver.saveBlob(this.receiptBlob, `receipt_${Date.now()}.png`).then((r) => {
                    if (r) this.recordEvent('downloaded');
                    else Toast.show('영수증 이미지를 길게 눌러 저장해 주세요', 'info', 3000);
                });
            } else {
                Toast.show('영수증 이미지를 길게 눌러 저장해 주세요', 'info', 3000);
            }
            copyPromise.then((ok) => {
                Toast.show(ok ? '문구가 복사되었어요' : '이동 중...', ok ? 'success' : 'info', 1500);
            });
            setTimeout(() => {
                mainBtn.disabled = false;
                this.readyToGo = true;
                mainBtn.innerHTML = '<span>다시</span><strong>네이버로 이동</strong>';
                this.goNaver();
            }, 1000);
        },

        async regenerateText() {
            const regenerateBtn = document.getElementById('regenerateText');
            const textEl = document.getElementById('reviewText');
            const sessionId = currentSessionId();

            regenerateBtn.disabled = true;

            try {
                const response = await fetch(`/api/v1/session/${sessionId}/regenerate`, {
                    method: 'POST'
                });

                if (response.ok) {
                    const data = await response.json();
                    textEl.textContent = data.generated_text;
                    this.lastSavedText = data.generated_text;
                    Toast.show('새로운 문구가 생성되었습니다', 'success');
                } else {
                    const data = await response.json();
                    throw new Error(data.detail || '문구 생성에 실패했습니다');
                }
            } catch (e) {
                Toast.show(e.message, 'error');
            } finally {
                regenerateBtn.disabled = false;
            }
        },

        async recordEvent(eventType) {
            const sessionId = currentSessionId();
            try {
                await fetch(`/api/v1/session/${sessionId}/event`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ event: eventType }),
                    keepalive: true
                });
            } catch (e) {
                console.error('Event record failed:', e);
            }
        }
    };

    // 화면 5: 완료
    const CompletionPage = {
        init() {
            const clockEl = document.getElementById('liveClock');
            const confirmBtn = document.getElementById('confirmBenefit');

            if (!clockEl) return;

            // 실시간 시계
            this.updateClock();
            setInterval(() => this.updateClock(), 1000);

            // 혜택 확인 버튼
            confirmBtn?.addEventListener('click', () => this.showPinInput());
        },

        updateClock() {
            const clockEl = document.getElementById('liveClock');
            const dateEl = document.getElementById('liveDate');

            if (!clockEl) return;

            const now = new Date();
            clockEl.textContent = now.toLocaleTimeString('ko-KR', {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
                hour12: false
            });

            if (dateEl) {
                dateEl.textContent = now.toLocaleDateString('ko-KR', {
                    year: 'numeric',
                    month: 'long',
                    day: 'numeric',
                    weekday: 'long'
                });
            }
        },

        showPinInput() {
            const confirmBtn = document.getElementById('confirmBenefit');
            const pinSection = document.getElementById('pinSection');

            confirmBtn.classList.add('hidden');
            pinSection?.classList.remove('hidden');

            document.getElementById('pinInput')?.focus();
        },

        async verifyPin() {
            const pinInput = document.getElementById('pinInput');
            const sessionId = currentSessionId();

            try {
                const response = await fetch(`/api/v1/session/${sessionId}/benefit`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ pin: pinInput.value })
                });

                if (response.ok) {
                    Toast.show('혜택 지급이 완료되었습니다!', 'success');
                    document.getElementById('pinSection').innerHTML = `
                        <div class="completion-code" style="background: #e8f5e9; border-color: #03C75A;">
                            <div class="completion-code__value" style="color: #03C75A;">✓ 완료</div>
                        </div>
                    `;
                } else {
                    const data = await response.json();
                    throw new Error(data.detail || 'PIN이 일치하지 않습니다');
                }
            } catch (e) {
                Toast.show(e.message, 'error');
                pinInput.value = '';
                pinInput.focus();
            }
        }
    };

    // 초기화
    document.addEventListener('DOMContentLoaded', () => {
        // 인앱 브라우저 처리
        if (BrowserDetect.isInApp && !BrowserDetect.isNaverApp) {
            if (!InAppHandler.tryOpenExternal()) {
                // 외부 브라우저 열기 실패 시 안내 표시 (선택적)
                // InAppHandler.showExternalBrowserGuide();
            }
        }

        // 페이지별 초기화
        PhoneInputPage.init();
        KeywordsPage.init();
        ResultPage.init();
        CompletionPage.init();
    });

    // 전역 노출
    window.ReviewApp = {
        BrowserDetect,
        PhoneFormatter,
        Clipboard,
        ImageSaver,
        Toast,
        CompletionPage
    };
})();
