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
            return /Line/.test(this.ua);
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

    // 클립보드
    const Clipboard = {
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
                    // 세션 저장
                    sessionStorage.setItem('sessionId', data.session_id);

                    // 기존 세션이면 바로 결과 화면으로
                    if (data.existing_session) {
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
            const sessionId = sessionStorage.getItem('sessionId');

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

            // 영수증 이미지 미리 로드
            if (receiptImg) {
                try {
                    const response = await fetch(receiptImg.src);
                    this.receiptBlob = await response.blob();
                } catch (e) {
                    console.error('Receipt preload failed:', e);
                }
            }

            // 메인 버튼
            mainBtn.addEventListener('click', (e) => this.handleMainAction(e));

            // 문구 재생성
            regenerateBtn?.addEventListener('click', () => this.regenerateText());
        },

        async handleMainAction(e) {
            e.preventDefault();

            const mainBtn = document.getElementById('mainAction');
            const reviewText = document.getElementById('reviewText')?.textContent?.trim();
            const naverUrl = window.NAVER_REVIEW_URL;

            mainBtn.disabled = true;
            mainBtn.innerHTML = '<span class="loading__spinner"></span> 처리 중...';

            let copySuccess = false;
            let saveSuccess = false;

            // 1. 문구 복사
            try {
                copySuccess = await Clipboard.copy(reviewText);
                if (copySuccess) {
                    console.log('Text copied');
                }
            } catch (e) {
                console.error('Copy failed:', e);
            }

            // 2. 이미지 저장
            if (this.receiptBlob) {
                try {
                    const result = await ImageSaver.saveBlob(
                        this.receiptBlob,
                        `receipt_${Date.now()}.png`
                    );
                    saveSuccess = !!result;

                    // iOS 공유 시트가 열렸으면
                    if (result === 'shared') {
                        mainBtn.disabled = false;
                        mainBtn.innerHTML = `
                            <span>이미지 저장 후</span>
                            <strong>네이버로 이동</strong>
                        `;

                        // 이동 버튼으로 변경
                        mainBtn.onclick = () => {
                            this.recordEvent('redirected');
                            window.location.href = naverUrl;
                        };

                        Toast.show('이미지 저장 후 버튼을 다시 눌러주세요', 'info');
                        return;
                    }
                } catch (e) {
                    console.error('Save failed:', e);
                }
            }

            // 3. 이벤트 기록
            this.recordEvent('downloaded');

            // 4. 네이버로 이동 (Android)
            if (BrowserDetect.isAndroid || !BrowserDetect.isIOS) {
                Toast.show(
                    copySuccess ? '문구가 복사되었습니다' : '이동 중...',
                    copySuccess ? 'success' : 'info',
                    1500
                );

                setTimeout(() => {
                    this.recordEvent('redirected');
                    window.location.href = naverUrl;
                }, 1000);
            }
        },

        async regenerateText() {
            const regenerateBtn = document.getElementById('regenerateText');
            const textEl = document.getElementById('reviewText');
            const sessionId = sessionStorage.getItem('sessionId');

            regenerateBtn.disabled = true;

            try {
                const response = await fetch(`/api/v1/session/${sessionId}/regenerate`, {
                    method: 'POST'
                });

                if (response.ok) {
                    const data = await response.json();
                    textEl.textContent = data.text;
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
            const sessionId = sessionStorage.getItem('sessionId');
            try {
                await fetch(`/api/v1/session/${sessionId}/event`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ event_type: eventType })
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
            const sessionId = sessionStorage.getItem('sessionId');

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
