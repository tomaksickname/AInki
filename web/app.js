/* ==================== AInki — Frontend v9 ==================== */

(() => {
    'use strict';

    // ==================== STATE ====================
    const state = {
        newCards: [],
        reviewCards: [],
        queue: [],
        pending: [],
        totalCards: 0,
        sessionGraduated: 0,
        revealed: false,
        submitting: false,
        sentenceIndex: 0,

        // Undo stack (frontend, local)
        undoStack: [],

        // Pause state
        paused: false,
    };

    // ==================== TIMER STATE ====================
    const timerState = {
        sessionTargetSeconds: 0,
        sessionStartMs: null,
        paused: false,
        pauseStartMs: null,

        cardStartMs: null,
        cardFrozenMs: 0,
        cardWord: null,
        cardNewPassCount: 0,

        totalSessionUnits: 0,
        cardTotalAllocationMs: 0,
        cardPassAllocationMs: 0,

        rafHandle: null,
        meetingFlashed: false,
    };

    // ==================== DOM ====================
    const $ = (id) => document.getElementById(id);
    const dom = {
        statNew: $('statNew'),
        statDue: $('statDue'),
        statReviewed: $('statReviewed'),
        progressFill: $('progressFill'),
        progressText: $('progressText'),
        card: $('card'),
        cardWord: $('cardWord'),
        cardSentence: $('cardSentence'),
        cardWordTranslation: $('cardWordTranslation'),
        cardTranslation: $('cardTranslation'),
        sentenceNav: $('sentenceNav'),
        sentenceCount: $('sentenceCount'),
        controls: $('controls'),
        inChatScroll: $('inChatScroll'),
        inChatInput: $('inChatInput'),
        inChatSend: $('inChatSend'),

        startPanel: $('start-panel'),
        startStageGen: $('start-stage-gen'),
        startStageTime: $('start-stage-time'),
        startSessionBtn: $('start-session-btn'),
        startProgress: $('start-progress'),
        startProgressFill: $('start-progress-fill'),
        startProgressMsg: $('start-progress-msg'),
        startCardsCount: $('start-cards-count'),
        startMinutes: $('start-minutes'),
        startBeginBtn: $('start-begin-btn'),

        cardTimer: $('progressCardTimer'),
        pauseBtn: $('pauseBtn'),
    };

    // ==================== HELPERS ====================
    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function highlightWord(sentence, word) {
        if (!sentence) return '';
        if (!word) return escapeHtml(sentence);
        const escSent = escapeHtml(sentence);
        const escWord = escapeHtml(word);
        const re = new RegExp(escWord.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i');
        return escSent.replace(re, (m) => `<span class="hl">${m}</span>`);
    }

    function hasActiveSelection() {
        const sel = window.getSelection();
        return !!(sel && sel.toString().length > 0);
    }

    // ==================== TTS ====================
    let ttsEnabled = true;
    let lastSpokenWord = null;

    function pickRussianVoice() {
        if (!window.speechSynthesis) return null;
        const voices = window.speechSynthesis.getVoices() || [];
        // Prefer Milena, then any ru-RU, then any ru-*
        return voices.find(v => v.name && v.name.toLowerCase().includes('milena'))
            || voices.find(v => v.lang === 'ru-RU')
            || voices.find(v => v.lang && v.lang.startsWith('ru'))
            || null;
    }

    function speakRussian(text) {
        if (!ttsEnabled) return;
        if (!text) return;
        if (!window.speechSynthesis) return;

        try {
            window.speechSynthesis.cancel();
            const u = new SpeechSynthesisUtterance(text);
            u.lang = 'ru-RU';
            u.rate = 0.9;
            u.pitch = 1.0;
            const v = pickRussianVoice();
            if (v) u.voice = v;
            window.speechSynthesis.speak(u);
        } catch (err) {
            console.warn('TTS failed:', err);
        }
    }

    // Some browsers need voices loaded asynchronously
    if (window.speechSynthesis) {
        window.speechSynthesis.onvoiceschanged = () => { /* triggers voice list refresh */ };
    }

    // ==================== API ====================
    async function apiGet(path) {
        const res = await fetch(path);
        if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);
        return res.json();
    }

    async function apiPost(path, body) {
        const res = await fetch(path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body || {}),
        });
        if (!res.ok) throw new Error(`POST ${path} → ${res.status}`);
        return res.json();
    }

    function currentLang() {
        return document.body.dataset.lang || 'en';
    }

    // ==================== UNIT MODEL ====================
    function isNewCard(card) {
        const srs = card.srs_data || {};
        return !srs.last_reviewed;
    }

    function cardUnits(card) {
        if (isNewCard(card)) return 5;
        const sentences = (card.sentences || []).filter(s => s && s.russian);
        return Math.max(1, Math.min(10, sentences.length));
    }

    function computeTotalSessionUnits() {
        let total = 0;
        for (const card of state.queue) total += cardUnits(card);
        return Math.max(1, total);
    }

    // ==================== LOADING ====================
    async function loadToday() {
        try {
            const data = await apiGet('/api/today');

            if (data.needs_generation) {
                showStartPanel();
                return;
            }

            hideStartPanel();

            state.newCards = data.new_cards || [];
            state.reviewCards = data.review_cards || [];
            state.queue = [...state.newCards, ...state.reviewCards];
            state.pending = [];
            state.totalCards = state.queue.length;
            state.sessionGraduated = 0;
            state.revealed = false;
            state.sentenceIndex = 0;
            state.undoStack = [];
            state.paused = false;

            dom.statNew.textContent = state.newCards.length;
            dom.statDue.textContent = state.reviewCards.length;
            dom.statReviewed.textContent = '0';

            if (state.queue.length > 0) {
                showSessionTimeStage();
            } else {
                render();
            }
        } catch (err) {
            console.error('Failed to load:', err);
            dom.cardWord.textContent = '⚠️ Failed to load';
            dom.cardSentence.textContent = 'Is the server running?';
        }
    }

    // ==================== START PANEL ====================
    let generatorPollTimer = null;

    function showStartPanel() {
        if (dom.startPanel) dom.startPanel.style.display = 'flex';
        if (dom.card) dom.card.style.display = 'none';
        if (dom.startStageGen) dom.startStageGen.style.display = 'flex';
        if (dom.startStageTime) dom.startStageTime.style.display = 'none';
        if (dom.startProgress) dom.startProgress.style.display = 'none';
        if (dom.startProgressFill) dom.startProgressFill.style.width = '0%';
        if (dom.startProgressMsg) dom.startProgressMsg.textContent = '';
        if (dom.startSessionBtn) dom.startSessionBtn.disabled = false;
    }

    function hideStartPanel() {
        if (dom.startPanel) dom.startPanel.style.display = 'none';
        if (dom.card) dom.card.style.display = '';
    }

    function setStartProgress(pct, msg) {
        if (dom.startProgress) dom.startProgress.style.display = 'flex';
        if (dom.startProgressFill) {
            dom.startProgressFill.style.width = `${Math.round((pct || 0) * 100)}%`;
        }
        if (dom.startProgressMsg) dom.startProgressMsg.textContent = msg || '';
    }

    function showSessionTimeStage() {
        if (dom.startPanel) dom.startPanel.style.display = 'flex';
        if (dom.card) dom.card.style.display = 'none';
        if (dom.startStageGen) dom.startStageGen.style.display = 'none';
        if (dom.startStageTime) dom.startStageTime.style.display = 'flex';
        if (dom.startCardsCount) {
            const n = state.queue.length;
            dom.startCardsCount.textContent = `${n} card${n === 1 ? '' : 's'} due today`;
        }
        if (dom.startMinutes) {
            dom.startMinutes.value = '60';
            dom.startMinutes.focus();
        }
    }

    async function startSession() {
        if (dom.startSessionBtn) dom.startSessionBtn.disabled = true;
        setStartProgress(0.0, 'Starting…');

        try {
            const res = await apiPost('/api/admin/generate', {});
            if (!res || !res.success) {
                setStartProgress(0, (res && res.error) ? res.error : 'Failed to start');
                if (dom.startSessionBtn) dom.startSessionBtn.disabled = false;
                return;
            }
            pollGeneratorStatus();
        } catch (err) {
            console.error('start generate failed:', err);
            setStartProgress(0, `Failed: ${err.message}`);
            if (dom.startSessionBtn) dom.startSessionBtn.disabled = false;
        }
    }

    function pollGeneratorStatus() {
        if (generatorPollTimer) clearTimeout(generatorPollTimer);
        generatorPollTimer = setTimeout(async () => {
            try {
                const s = await apiGet('/api/admin/generate/status');
                setStartProgress(s.progress || 0, s.message || '');

                if (s.status === 'running') {
                    pollGeneratorStatus();
                } else if (s.status === 'done') {
                    setStartProgress(1.0, 'Done — loading cards…');
                    setTimeout(async () => {
                        try {
                            const data = await apiGet('/api/today');
                            state.newCards = data.new_cards || [];
                            state.reviewCards = data.review_cards || [];
                            state.queue = [...state.newCards, ...state.reviewCards];
                            state.pending = [];
                            state.totalCards = state.queue.length;
                            state.sessionGraduated = 0;
                            state.revealed = false;
                            state.sentenceIndex = 0;
                            state.undoStack = [];
                            state.paused = false;
                            dom.statNew.textContent = state.newCards.length;
                            dom.statDue.textContent = state.reviewCards.length;
                            dom.statReviewed.textContent = '0';
                        } catch (err) {
                            console.error('pre-session fetch failed:', err);
                        }
                        showSessionTimeStage();
                    }, 400);
                } else if (s.status === 'error') {
                    if (dom.startSessionBtn) dom.startSessionBtn.disabled = false;
                    setStartProgress(s.progress || 0, s.error || 'Generation failed');
                } else {
                    pollGeneratorStatus();
                }
            } catch (err) {
                console.error('poll failed:', err);
                pollGeneratorStatus();
            }
        }, 800);
    }

    function beginSessionWithTime() {
        const input = dom.startMinutes;
        let minutes = 60;
        if (input) {
            const v = parseInt(input.value, 10);
            if (!isNaN(v) && v >= 0) minutes = v;
        }
        const seconds = minutes * 60;

        hideStartPanel();
        startSessionTimer(seconds);
        render();
    }

    // ==================== TIMER LOGIC ====================
    function startSessionTimer(targetSeconds) {
        timerState.sessionTargetSeconds = targetSeconds;
        timerState.sessionStartMs = Date.now();
        timerState.paused = false;
        timerState.pauseStartMs = null;
        timerState.totalSessionUnits = computeTotalSessionUnits();

        timerState.cardStartMs = null;
        timerState.cardFrozenMs = 0;
        timerState.cardWord = null;
        timerState.cardNewPassCount = 0;
        timerState.cardTotalAllocationMs = 0;
        timerState.cardPassAllocationMs = 0;
        timerState.meetingFlashed = false;

        state.paused = false;
        updatePauseButton();

        if (targetSeconds > 0) {
            startTimerLoop();
        } else {
            if (dom.cardTimer) {
                dom.cardTimer.classList.remove('visible', 'over', 'flash');
                dom.cardTimer.style.width = '0%';
            }
        }
    }

    function startTimerLoop() {
        if (timerState.rafHandle) return;
        const tick = () => {
            updateCardTimerVisual();
            timerState.rafHandle = requestAnimationFrame(tick);
        };
        timerState.rafHandle = requestAnimationFrame(tick);
    }

    function stopTimerLoop() {
        if (timerState.rafHandle) {
            cancelAnimationFrame(timerState.rafHandle);
            timerState.rafHandle = null;
        }
    }

    function currentCardElapsedMs() {
        if (timerState.cardStartMs === null) return timerState.cardFrozenMs;
        const now = timerState.paused && timerState.pauseStartMs !== null
            ? timerState.pauseStartMs
            : Date.now();
        return timerState.cardFrozenMs + (now - timerState.cardStartMs);
    }

    function computeCardTotalAllocationMs(card) {
        if (timerState.sessionTargetSeconds <= 0) return 0;
        const totalUnits = timerState.totalSessionUnits;
        if (totalUnits <= 0) return 0;
        const secondsPerUnit = timerState.sessionTargetSeconds / totalUnits;
        return cardUnits(card) * secondsPerUnit * 1000;
    }

    function onCardChanged() {
        const card = currentCard();
        if (!card) {
            timerState.cardWord = null;
            timerState.cardStartMs = null;
            if (dom.cardTimer) {
                dom.cardTimer.classList.remove('visible', 'over', 'flash');
                dom.cardTimer.style.width = '0%';
            }
            return;
        }

        if (card.word !== timerState.cardWord) {
            timerState.cardWord = card.word;
            timerState.cardFrozenMs = 0;
            timerState.cardStartMs = Date.now();
            timerState.cardNewPassCount = 0;
            timerState.cardTotalAllocationMs = computeCardTotalAllocationMs(card);
            timerState.meetingFlashed = false;

            if (dom.cardTimer) {
                dom.cardTimer.classList.remove('over', 'flash');
                dom.cardTimer.classList.add('visible');
            }
        } else if (timerState.cardStartMs === null && !timerState.paused) {
            timerState.cardStartMs = Date.now();
            if (dom.cardTimer) {
                dom.cardTimer.classList.remove('over', 'flash');
                dom.cardTimer.classList.add('visible');
            }
        }
    }

    function onCardRated() {
        if (timerState.cardStartMs !== null) {
            timerState.cardFrozenMs += (Date.now() - timerState.cardStartMs);
            timerState.cardStartMs = null;
        }
        timerState.cardNewPassCount += 1;
    }

    function updateCardTimerVisual() {
        const el = dom.cardTimer;
        if (!el) return;
        if (timerState.sessionTargetSeconds <= 0) {
            el.classList.remove('visible', 'over', 'flash');
            return;
        }
        if (!timerState.cardWord) {
            el.classList.remove('visible', 'over', 'flash');
            return;
        }

        const elapsed = currentCardElapsedMs();
        const allocation = timerState.cardTotalAllocationMs;
        if (allocation <= 0) return;

        const progress = Math.min(1, elapsed / allocation);

        const total = state.totalCards;
        const sessionPct = total > 0 ? (state.sessionGraduated / total) * 100 : 0;
        const emptyPct = Math.max(0, 100 - sessionPct);

        const timerWidthPct = emptyPct * progress;

        el.classList.add('visible');
        el.style.width = `${timerWidthPct}%`;

        const t = progress;
        const r = Math.round(90 + (220 - 90) * t);
        const g = Math.round(150 + (80 - 150) * t);
        const b = Math.round(220 + (60 - 220) * t);

        el.style.background = `linear-gradient(to left, rgb(90, 150, 220), rgb(${r}, ${g}, ${b}))`;

        if (progress >= 1) {
            el.classList.add('over');
            if (!timerState.meetingFlashed) {
                timerState.meetingFlashed = true;
                el.classList.remove('flash');
                void el.offsetWidth;
                el.classList.add('flash');
            }
        } else {
            el.classList.remove('over');
        }
    }

    // ==================== PAUSE / RESUME ====================
    function togglePause() {
        if (timerState.sessionTargetSeconds <= 0) return;
        if (state.queue.length === 0) return;

        if (!timerState.paused) {
            timerState.paused = true;
            timerState.pauseStartMs = Date.now();
            state.paused = true;
            updatePauseButton();
        } else {
            const pauseDuration = Date.now() - timerState.pauseStartMs;
            timerState.paused = false;
            timerState.pauseStartMs = null;
            timerState.sessionStartMs += pauseDuration;
            if (timerState.cardStartMs !== null) {
                timerState.cardStartMs += pauseDuration;
            }
            state.paused = false;
            updatePauseButton();
        }
    }

    function updatePauseButton() {
        if (!dom.pauseBtn) return;
        if (state.paused) {
            dom.pauseBtn.textContent = '▶';
            dom.pauseBtn.title = 'Resume session';
            dom.pauseBtn.classList.add('paused');
        } else {
            dom.pauseBtn.textContent = '⏸';
            dom.pauseBtn.title = 'Pause session';
            dom.pauseBtn.classList.remove('paused');
        }
    }

    // ==================== QUEUE PRIMING ====================
    function cardDueNow(card) {
        const srs = card.srs_data || {};
        if (srs.state !== 'learning') return true;
        const due = srs.due_date;
        if (!due) return true;
        return new Date(due) <= new Date();
    }

    function primeQueue() {
        let guard = state.queue.length + state.pending.length + 2;
        while (guard-- > 0) {
            if (state.queue.length === 0) break;
            const head = state.queue[0];
            if (cardDueNow(head)) return;
            state.queue.shift();
            state.pending.push(head);
        }
        if (state.pending.length > 0) {
            state.pending.sort((a, b) => {
                const da = (a.srs_data && a.srs_data.due_date) || '';
                const db = (b.srs_data && b.srs_data.due_date) || '';
                return da < db ? -1 : da > db ? 1 : 0;
            });
            state.queue.push(state.pending.shift());
        }
    }

    // ==================== CURRENT CARD / SENTENCE ====================
    function currentCard() {
        if (state.queue.length === 0) return null;
        return state.queue[0];
    }

    function cardSentences(card) {
        const arr = (card && card.sentences) ? card.sentences.slice() : [];
        return arr.filter(s => s && s.russian);
    }

    function currentSentence(card) {
        const arr = cardSentences(card);
        if (arr.length === 0) return null;
        const reversed = arr.slice().reverse();
        const idx = state.sentenceIndex % reversed.length;
        return reversed[idx];
    }

    function sentenceCount(card) {
        return cardSentences(card).length;
    }

    // ==================== RENDERING ====================
    function render() {
        primeQueue();
        if (state.queue.length === 0) return renderComplete();
        const card = currentCard();
        if (!card) return renderComplete();
        renderCard(card);
        renderProgress();
        updateInChatContext(card);
        onCardChanged();
    }

    function renderCard(card) {
        dom.card.classList.remove('empty', 'revealed');
        dom.cardWord.textContent = card.word;
        const s = currentSentence(card);
        if (s && s.russian) {
            dom.cardSentence.innerHTML = highlightWord(s.russian, card.word);
            dom.cardSentence.style.visibility = 'visible';
        } else {
            dom.cardSentence.textContent = '';
            dom.cardSentence.style.visibility = 'hidden';
        }
        dom.cardWordTranslation.textContent =
            card.english || card.translation || '';
        if (s && s.english) {
            dom.cardTranslation.textContent = s.english;
            dom.cardTranslation.style.visibility = 'visible';
        } else {
            dom.cardTranslation.textContent = '';
            dom.cardTranslation.style.visibility = 'hidden';
        }
        const count = sentenceCount(card);
        if (count > 1) {
            dom.sentenceNav.classList.add('visible');
            const displayIndex = (state.sentenceIndex % count) + 1;
            dom.sentenceCount.textContent = `${displayIndex} / ${count}`;
        } else {
            dom.sentenceNav.classList.remove('visible');
        }
        state.revealed = false;
        dom.controls.classList.remove('visible');

        // Auto-TTS on word change
        if (card.word && card.word !== lastSpokenWord) {
            lastSpokenWord = card.word;
            speakRussian(card.word);
        }
    }

    function renderProgress() {
        const done = state.sessionGraduated;
        const total = state.totalCards;
        const pct = total > 0 ? (done / total) * 100 : 0;
        dom.progressFill.style.width = `${pct}%`;
        dom.progressText.textContent = `${done} / ${total}`;
        dom.statReviewed.textContent = done;
    }

    function renderComplete() {
        dom.card.classList.add('empty');
        dom.card.classList.remove('revealed');
        dom.controls.classList.remove('visible');
        dom.sentenceNav.classList.remove('visible');
        dom.progressFill.style.width = '100%';
        dom.progressText.textContent = `${state.totalCards} / ${state.totalCards}`;
        dom.statReviewed.textContent = state.totalCards;

        stopTimerLoop();
        if (dom.cardTimer) {
            dom.cardTimer.classList.remove('visible', 'over', 'flash');
            dom.cardTimer.style.width = '0%';
        }
    }

    // ==================== ACTIONS ====================
    function reveal() {
        if (state.revealed) return;
        if (!currentCard()) return;
        state.revealed = true;
        dom.card.classList.add('revealed');
        dom.controls.classList.add('visible');
    }

    function cycleSentence() {
        const card = currentCard();
        if (!card) return;
        const count = sentenceCount(card);
        if (count <= 1) return;
        state.sentenceIndex = (state.sentenceIndex + 1) % count;
        const wasRevealed = state.revealed;
        renderCard(card);
        if (wasRevealed) {
            state.revealed = true;
            dom.card.classList.add('revealed');
            dom.controls.classList.add('visible');
        }
    }

    function rotateQueue(rating, card) {
        if (!card) return;
        const srs = card.srs_data || {};
        const isLearning = srs.state === 'learning';
        if (isLearning) {
            state.pending.push(card);
            return;
        }
        if (rating === 'good' || rating === 'easy') {
            state.sessionGraduated += 1;
        } else {
            state.queue.push(card);
        }
    }

    async function submitRating(rating) {
        if (state.submitting) return;
        if (!state.revealed) return;
        const card = currentCard();
        if (!card) return;
        state.submitting = true;

        // Determine whether this rating will graduate the card (for undo restore)
        const srs = card.srs_data || {};
        const isLearning = srs.state === 'learning';
        const willGraduate = !isLearning && (rating === 'good' || rating === 'easy');

        // Push to frontend undo stack BEFORE mutating state
        state.undoStack.push({
            card: card,
            rating: rating,
            graduated: willGraduate,
        });

        // If paused, unpause before rating (timer resumes)
        if (timerState.paused) {
            const pauseDuration = Date.now() - timerState.pauseStartMs;
            timerState.paused = false;
            timerState.pauseStartMs = null;
            timerState.sessionStartMs += pauseDuration;
            if (timerState.cardStartMs !== null) {
                timerState.cardStartMs += pauseDuration;
            }
            state.paused = false;
            updatePauseButton();
        }

        try {
            const res = await apiPost('/api/review', {
                rank: card.rank,
                word: card.word,
                rating: rating,
            });

            if (res.srs_data) card.srs_data = res.srs_data;
            if (res.remaining) {
                dom.statNew.textContent = res.remaining.new;
                dom.statDue.textContent = res.remaining.due;
            }

            onCardRated();
            state.queue.shift();
            rotateQueue(rating, card);
            state.sentenceIndex = 0;

            render();
        } catch (err) {
            console.error('Submit failed:', err);
            // Roll back the undo stack push on failure
            state.undoStack.pop();
        } finally {
            state.submitting = false;
        }
    }

    async function undo() {
        if (state.submitting) return;
        if (state.undoStack.length === 0) return;
        state.submitting = true;

        const entry = state.undoStack[state.undoStack.length - 1];

        try {
            const res = await apiPost('/api/undo', {});
            if (!res.success) {
                console.warn('Undo failed:', res.error);
                return;
            }

            // Pop the frontend stack
            state.undoStack.pop();

            // Put the card back at the front, unrevealed
            state.queue.unshift(entry.card);

            // Decrement graduated counter if this rating had graduated the card
            if (entry.graduated) {
                state.sessionGraduated = Math.max(0, state.sessionGraduated - 1);
            }

            // Reset reveal and sentence index
            state.revealed = false;
            state.sentenceIndex = 0;

            // Freeze any pending timer state for this card (it's coming back fresh)
            timerState.cardWord = null;
            timerState.cardStartMs = null;
            timerState.cardFrozenMs = 0;
            timerState.meetingFlashed = false;

            lastSpokenWord = null;

            render();
        } catch (err) {
            console.error('Undo failed:', err);
        } finally {
            state.submitting = false;
        }
    }

    // Pending ticker — promotes due learning cards, preserves reveal state
    setInterval(() => {
        if (state.submitting) return;
        if (state.pending.length === 0) return;
        const now = new Date();
        const ready = [];
        const stillPending = [];
        for (const c of state.pending) {
            const srs = c.srs_data || {};
            const isReady =
                srs.state !== 'learning' ||
                !srs.due_date ||
                new Date(srs.due_date) <= now;
            if (isReady) ready.push(c);
            else stillPending.push(c);
        }
        if (ready.length === 0) return;

        const beforeFront = currentCard();
        const wasRevealed = state.revealed;

        state.pending = stillPending;
        state.queue.push(...ready);

        const afterFront = currentCard();

        if (beforeFront === afterFront && wasRevealed) {
            renderCard(afterFront);
            state.revealed = true;
            dom.card.classList.add('revealed');
            dom.controls.classList.add('visible');
            renderProgress();
            updateInChatContext(afterFront);
            onCardChanged();
        } else {
            render();
        }
    }, 15000);

    // ==================== IN CHAT ====================
    let currentChatContext = null;

    function updateInChatContext(card) {
        currentChatContext = card
            ? {
                rank: card.rank,
                word: card.word,
                pos: card.pos || '',
                decision: card.decision || '',
                english: card.english || card.translation || '',
                srs_data: card.srs_data || {},
                current_sentence: currentSentence(card),
              }
            : null;
    }

    function appendInChat(role, text) {
        const msg = document.createElement('div');
        msg.className = `chat-msg chat-msg-${role}`;
        msg.innerHTML = `
            <div class="chat-avatar">${role === 'user' ? '🧑' : '🤖'}</div>
            <div class="chat-bubble"></div>
        `;
        msg.querySelector('.chat-bubble').textContent = text;
        dom.inChatScroll.appendChild(msg);
        dom.inChatScroll.scrollTop = dom.inChatScroll.scrollHeight;
    }

    async function sendInChat() {
        const text = dom.inChatInput.value.trim();
        if (!text) return;

        appendInChat('user', text);
        dom.inChatInput.value = '';
        dom.inChatInput.style.height = 'auto';

        try {
            const res = await apiPost('/api/in-chat', {
                message: text,
                card_context: currentChatContext,
                lang: currentLang(),
            });
            appendInChat('bot', (res && res.reply) || '⚠️ No reply.');
        } catch (err) {
            console.error('IN chat failed:', err);
            appendInChat('bot', `⚠️ Chat failed: ${err.message}`);
        }
    }

    // ==================== EVENTS ====================
    dom.card.addEventListener('click', (e) => {
        if (e.target.closest('.sentence-nav')) return;
        if (hasActiveSelection()) return;
        if (!state.revealed) reveal();
    });

    dom.sentenceNav.addEventListener('click', (e) => {
        e.stopPropagation();
        cycleSentence();
    });

    dom.controls.addEventListener('click', (e) => {
        const btn = e.target.closest('.ctrl-btn');
        if (!btn) return;
        e.stopPropagation();
        const action = btn.dataset.action;
        if (action === 'again') submitRating('again');
        else if (action === 'hard') submitRating('hard');
        else if (action === 'good') submitRating('good');
        else if (action === 'cycle') cycleSentence();
    });

    dom.inChatSend.addEventListener('click', sendInChat);
    dom.inChatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendInChat();
        }
    });
    dom.inChatInput.addEventListener('input', (e) => {
        e.target.style.height = 'auto';
        e.target.style.height = Math.min(e.target.scrollHeight, 100) + 'px';
    });

    if (dom.startSessionBtn) {
        dom.startSessionBtn.addEventListener('click', startSession);
    }
    if (dom.startBeginBtn) {
        dom.startBeginBtn.addEventListener('click', beginSessionWithTime);
    }
    if (dom.startMinutes) {
        dom.startMinutes.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                beginSessionWithTime();
            }
        });
    }
    if (dom.pauseBtn) {
        dom.pauseBtn.addEventListener('click', togglePause);
    }

    document.addEventListener('keydown', (e) => {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

        const key = e.key;

        // Shift → pause toggle (works whether paused or not, but not when the session hasn't started)
        if (key === 'Shift') {
            e.preventDefault();
            togglePause();
            return;
        }

        // Backspace → undo (only when not paused; use Shift to pause first)
        if (key === 'Backspace') {
            e.preventDefault();
            if (!state.paused) undo();
            return;
        }

        // S → re-speak the current word
        if (key === 's' || key === 'S') {
            e.preventDefault();
            const card = currentCard();
            if (card && card.word) speakRussian(card.word);
            return;
        }

        if (!state.revealed) {
            if (key === 'ArrowDown') { e.preventDefault(); cycleSentence(); return; }
            if (['Control', 'Alt', 'Meta', 'CapsLock', 'Tab', 'Escape'].includes(key)) return;
            if (key.startsWith('F') && key.length <= 3) return;
            e.preventDefault();
            reveal();
            return;
        }

        switch (key) {
            case 'ArrowLeft': e.preventDefault(); submitRating('again'); break;
            case 'ArrowUp': e.preventDefault(); submitRating('hard'); break;
            case 'ArrowRight': e.preventDefault(); submitRating('good'); break;
            case 'ArrowDown': e.preventDefault(); cycleSentence(); break;
            case '1': e.preventDefault(); submitRating('again'); break;
            case '2': e.preventDefault(); submitRating('hard'); break;
            case '3': e.preventDefault(); submitRating('good'); break;
            case '4': e.preventDefault(); submitRating('easy'); break;
        }
    });

    // ==================== INIT ====================
    updatePauseButton();
    loadToday();
})();
