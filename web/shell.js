/* ==================== AInki — Shell ==================== */

(() => {
    'use strict';

    const MODES = ['in', 'out'];
    const OUT_MODES = ['loop', 'drill', 'write'];
    const LANGS = ['en', 'ru'];
    const STORAGE_KEY_MODE = 'ainki.mode';
    const STORAGE_KEY_LANG = 'ainki.lang';
    const STORAGE_KEY_SETTINGS = 'ainki.out.settings';

    const body = document.body;
    const modeButtons = document.querySelectorAll('.mode-btn');
    const langButtons = document.querySelectorAll('.lang-btn');
    const shellIn = document.getElementById('shell-in');
    const shellOut = document.getElementById('shell-out');

    const outWritePane      = document.getElementById('outWritePane');
    const outChatPane       = document.getElementById('outChatPane');
    const outPromptLabel    = document.getElementById('outPromptLabel');
    const outPromptText     = document.getElementById('outPromptText');
    const outPromptSub      = document.getElementById('outPromptSub');
    const outWriteTextarea  = document.getElementById('outWriteTextarea');
    const outChatScroll     = document.getElementById('outChatScroll');
    const outChatInput      = document.getElementById('outChatInput');
    const outChatSend       = document.getElementById('outChatSend');
    const outModeButtons    = document.querySelectorAll('.out-mode-btn');

    const grammarMinusBtn   = document.getElementById('grammarMinus');
    const grammarPlusBtn    = document.getElementById('grammarPlus');
    const grammarLabel      = document.getElementById('grammarLabel');
    const grammarDropdown   = document.getElementById('grammarDropdown');

    const vocabMinusBtn     = document.getElementById('vocabMinus');
    const vocabPlusBtn      = document.getElementById('vocabPlus');
    const vocabLabel        = document.getElementById('vocabLabel');

    const bufferMinusBtn    = document.getElementById('bufferMinus');
    const bufferPlusBtn     = document.getElementById('bufferPlus');
    const bufferLabel       = document.getElementById('bufferLabel');

    // ==================== CLUSTERS ====================
    const CLUSTERS = [
        { id: 1,  name: 'Core Sentence' },
        { id: 2,  name: 'Gender & Number' },
        { id: 3,  name: 'Genitive Case' },
        { id: 4,  name: 'Dative Case' },
        { id: 5,  name: 'Instrumental Case' },
        { id: 6,  name: 'Prepositional Case' },
        { id: 7,  name: 'Full Case Paradigm' },
        { id: 8,  name: 'Adjective Systems' },
        { id: 9,  name: 'Comparative & Superlative' },
        { id: 10, name: 'Verb Aspect' },
        { id: 11, name: 'Verb Tense & Mood' },
        { id: 12, name: 'Reflexive Verbs' },
        { id: 13, name: 'Verbs of Motion' },
        { id: 14, name: 'Verb Government' },
        { id: 15, name: 'Verb Prefixes' },
        { id: 16, name: 'Participles' },
        { id: 17, name: 'Gerunds' },
        { id: 18, name: 'Personal & Possessive Pronouns' },
        { id: 19, name: 'Other Pronouns' },
        { id: 20, name: 'Numerals' },
        { id: 21, name: 'Adverbs' },
        { id: 22, name: 'Prepositions' },
        { id: 23, name: 'Clause Structure' },
        { id: 24, name: 'Reported Speech' },
        { id: 25, name: 'Particles, Negation & Word Order' },
    ];

    const VOCAB_LEVELS = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2'];
    const BUFFER_MIN = 1;
    const BUFFER_MAX = 30;

    // ==================== FACET LABELS ====================
    const FACET_LABELS = {
        fem_sg: "feminine singular",
        masc_sg: "masculine singular",
        neut_sg: "neuter singular",
        pl: "plural",
        adj_agr: "adjective agreement",
        fem: "feminine",
        masc: "masculine",
        neut: "neuter",
        past_perf: "past perfective",
        past_imperf: "past imperfective",
        future_perf: "future perfective",
        future_imperf: "future imperfective",
        in_context: "aspect choice in context",
        imperf_imperative: "imperfective imperative",
        perf_imperative: "perfective imperative",
        one: "numeral 1",
        two_four: "numerals 2–4",
        five_plus: "numerals 5+",
        gender_agreement: "gender agreement",
        ending_ov: "ending -ов",
        ending_ev: "ending -ев",
        ending_ej: "ending -ей",
        zero_ending: "zero ending",
        hard_stem: "hard stem",
        soft_stem: "soft stem",
        nom: "nominative",
        acc: "accusative",
        gen: "genitive",
        dat: "dative",
        instr: "instrumental",
        prep: "prepositional",
        location: "location",
        direction: "direction",
        countries: "countries",
        cities: "cities",
        regions: "regions",
        unidirectional: "unidirectional",
        multidirectional: "multidirectional",
        pri: "при- prefix",
        u: "у- prefix",
        vy: "вы- prefix",
        po: "по- prefix",
        za: "за- prefix",
        do: "до- prefix",
        pere: "пере- prefix",
        o_prep: "о + prepositional",
        v_acc: "в + accusative",
        na_acc: "на + accusative",
        po_pref: "по- aspectual",
        pro: "про- completive",
        etot: "этот",
        tot: "тот",
        takoy: "такой",
        ves: "весь",
        sam: "сам",
        samy: "самый",
        kto_chto: "кто / что",
        kakoy: "какой",
        chey: "чей",
        kotory: "который",
        negative: "negative",
        indefinite: "indefinite",
        chto: "что",
        chtoby: "чтобы",
        zhe: "же",
        ved: "ведь",
        to: "-то",
        imenno: "именно",
        li: "ли",
        razve: "разве",
        neuzheli: "неужели",
    };

    function facetLabel(facet) {
        if (!facet || facet === "default") return null;
        return FACET_LABELS[facet] || facet;
    }

    // ==================== PERSISTED SETTINGS ====================
    function loadSettings() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY_SETTINGS);
            if (!raw) return {};
            return JSON.parse(raw) || {};
        } catch (_) {
            return {};
        }
    }

    function saveSettings() {
        try {
            localStorage.setItem(STORAGE_KEY_SETTINGS, JSON.stringify({
                mode: outState.mode,
                clusterIndex: outState.clusterIndex,
                vocabIndex: outState.vocabIndex,
                bufferTarget: outState.bufferTarget,
            }));
        } catch (_) {}
    }

    const _saved = loadSettings();

    // ==================== STATE ====================
    const outState = {
        mode: (typeof _saved.mode === 'string' && OUT_MODES.includes(_saved.mode))
            ? _saved.mode : 'loop',
        clusterIndex: (typeof _saved.clusterIndex === 'number'
            && _saved.clusterIndex >= 0
            && _saved.clusterIndex < CLUSTERS.length)
            ? _saved.clusterIndex : 0,
        vocabIndex: (typeof _saved.vocabIndex === 'number'
            && _saved.vocabIndex >= 0
            && _saved.vocabIndex < VOCAB_LEVELS.length)
            ? _saved.vocabIndex : 2,
        bufferTarget: (typeof _saved.bufferTarget === 'number'
            && _saved.bufferTarget >= BUFFER_MIN
            && _saved.bufferTarget <= BUFFER_MAX)
            ? _saved.bufferTarget : 10,
        drillBuffer: [],
        currentDrill: null,
        writeIndex: 0,
        writePrompt: null,
        lastDrill: null,
        inflight: 0,
        writePromptLoading: false,

        clusterGenerationEpoch: 0,

        chatHistory: [],

        sentence: {
            active: false,
            words: [],
            tokens: [],
            cursor: -1,
            anchor: -1,
            selecting: false,
        },
    };

    function currentLang() {
        return body.dataset.lang || 'en';
    }

    // ==================== API HELPERS ====================
    async function apiPost(path, body_obj) {
        const res = await fetch(path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body_obj || {}),
        });
        if (!res.ok) throw new Error(`POST ${path} → ${res.status}`);
        return res.json();
    }

    // ==================== IN/OUT MODE ====================
    function readInitialMode() {
        const hash = (location.hash || '').replace('#', '').toLowerCase();
        if (MODES.includes(hash)) return hash;
        try {
            const saved = localStorage.getItem(STORAGE_KEY_MODE);
            if (MODES.includes(saved)) return saved;
        } catch (_) {}
        return 'in';
    }

    function setMode(mode, { updateHash = true } = {}) {
        if (!MODES.includes(mode)) mode = 'in';
        body.dataset.mode = mode;

        modeButtons.forEach(btn => {
            const active = btn.dataset.mode === mode;
            btn.classList.toggle('active', active);
            btn.setAttribute('aria-selected', active ? 'true' : 'false');
        });

        shellIn.classList.toggle('shell-active', mode === 'in');
        shellOut.classList.toggle('shell-active', mode === 'out');

        try { localStorage.setItem(STORAGE_KEY_MODE, mode); } catch (_) {}

        if (updateHash) {
            const newHash = `#${mode}`;
            if (location.hash !== newHash) {
                history.replaceState(null, '', newHash);
            }
        }

        if (mode === 'out') {
            setTimeout(() => outWriteTextarea && outWriteTextarea.focus(), 0);
        }
    }

    modeButtons.forEach(btn => {
        btn.addEventListener('click', () => setMode(btn.dataset.mode));
    });

    window.addEventListener('hashchange', () => {
        const hash = (location.hash || '').replace('#', '').toLowerCase();
        if (MODES.includes(hash)) setMode(hash, { updateHash: false });
    });

    // ==================== LANGUAGE TOGGLE ====================
    function readInitialLang() {
        try {
            const saved = localStorage.getItem(STORAGE_KEY_LANG);
            if (LANGS.includes(saved)) return saved;
        } catch (_) {}
        return 'en';
    }

    function setLang(lang) {
        if (!LANGS.includes(lang)) lang = 'en';
        body.dataset.lang = lang;
        langButtons.forEach(btn => {
            const active = btn.dataset.lang === lang;
            btn.classList.toggle('active', active);
            btn.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        try { localStorage.setItem(STORAGE_KEY_LANG, lang); } catch (_) {}
    }

    langButtons.forEach(btn => {
        btn.addEventListener('click', () => setLang(btn.dataset.lang));
    });

    // ==================== GRAMMAR STEPPER ====================
    function currentCluster() { return CLUSTERS[outState.clusterIndex]; }
    function currentVocab()   { return VOCAB_LEVELS[outState.vocabIndex]; }

    function activeClusters() {
        return CLUSTERS.slice(0, outState.clusterIndex + 1).map(c => c.id);
    }

    function updateGrammarLabel() {
        const c = currentCluster();
        grammarLabel.textContent = c.name;
        grammarLabel.title = `${c.id} of ${CLUSTERS.length} · ${c.name}`;
    }

    function buildGrammarDropdown() {
        grammarDropdown.innerHTML = '';
        CLUSTERS.forEach((c, i) => {
            const item = document.createElement('button');
            item.type = 'button';
            item.className = 'stepper-dropdown-item' + (i === outState.clusterIndex ? ' active' : '');
            item.innerHTML = `<span class="dropdown-index">${c.id}</span>${c.name}`;
            item.addEventListener('click', () => {
                outState.clusterIndex = i;
                updateGrammarLabel();
                saveSettings();
                closeGrammarDropdown();
                wipeBufferAndRegenerate();
                appendOutChat('bot', `Grammar topic set to ${c.name}. Buffer cleared.`);
                if (outState.mode === 'loop') setOutMode('loop');
                else if (outState.mode === 'drill') serveDrill();
            });
            grammarDropdown.appendChild(item);
        });
    }

    function openGrammarDropdown() {
        buildGrammarDropdown();
        grammarDropdown.classList.add('open');
        setTimeout(() => {
            document.addEventListener('click', onGlobalClickCloseGrammar);
        }, 0);
    }

    function closeGrammarDropdown() {
        grammarDropdown.classList.remove('open');
        document.removeEventListener('click', onGlobalClickCloseGrammar);
    }

    function onGlobalClickCloseGrammar(e) {
        if (!e.target.closest('#grammarStepper')) closeGrammarDropdown();
    }

    grammarMinusBtn.addEventListener('click', () => {
        if (outState.clusterIndex === 0) return;
        outState.clusterIndex -= 1;
        updateGrammarLabel();
        saveSettings();
        wipeBufferAndRegenerate();
        if (outState.mode === 'loop') setOutMode('loop');
        else if (outState.mode === 'drill') serveDrill();
    });

    grammarPlusBtn.addEventListener('click', () => {
        if (outState.clusterIndex >= CLUSTERS.length - 1) return;
        outState.clusterIndex += 1;
        updateGrammarLabel();
        saveSettings();
        wipeBufferAndRegenerate();
        if (outState.mode === 'loop') setOutMode('loop');
        else if (outState.mode === 'drill') serveDrill();
    });

    grammarLabel.addEventListener('click', (e) => {
        e.stopPropagation();
        if (grammarDropdown.classList.contains('open')) closeGrammarDropdown();
        else openGrammarDropdown();
    });

    // ==================== VOCAB STEPPER ====================
    function updateVocabLabel() { vocabLabel.textContent = currentVocab(); }

    vocabMinusBtn.addEventListener('click', () => {
        if (outState.vocabIndex === 0) return;
        outState.vocabIndex -= 1;
        updateVocabLabel();
        saveSettings();
        wipeBufferAndRegenerate();
        if (outState.mode === 'loop') setOutMode('loop');
        else if (outState.mode === 'drill') serveDrill();
    });

    vocabPlusBtn.addEventListener('click', () => {
        if (outState.vocabIndex >= VOCAB_LEVELS.length - 1) return;
        outState.vocabIndex += 1;
        updateVocabLabel();
        saveSettings();
        wipeBufferAndRegenerate();
        if (outState.mode === 'loop') setOutMode('loop');
        else if (outState.mode === 'drill') serveDrill();
    });

    // ==================== BUFFER STEPPER ====================
    function updateBufferLabel() { bufferLabel.textContent = outState.bufferTarget; }

    bufferMinusBtn.addEventListener('click', () => {
        if (outState.bufferTarget <= BUFFER_MIN) return;
        outState.bufferTarget -= 1;
        updateBufferLabel();
        saveSettings();
        if (outState.drillBuffer.length > outState.bufferTarget) {
            outState.drillBuffer = outState.drillBuffer.slice(0, outState.bufferTarget);
        }
    });

    bufferPlusBtn.addEventListener('click', () => {
        if (outState.bufferTarget >= BUFFER_MAX) return;
        outState.bufferTarget += 1;
        updateBufferLabel();
        saveSettings();
        ensureGeneration();
    });

    // ==================== WIPE + REGEN ====================
    function wipeBufferAndRegenerate() {
        outState.drillBuffer = [];
        outState.currentDrill = null;
        outState.clusterGenerationEpoch += 1;
        ensureGeneration();
    }

    // ==================== OUT MODE ====================
    function setOutMode(mode) {
        if (!OUT_MODES.includes(mode)) mode = 'loop';
        outState.mode = mode;
        saveSettings();

        outModeButtons.forEach(btn => {
            const active = btn.dataset.outmode === mode;
            btn.classList.toggle('active', active);
            btn.setAttribute('aria-selected', active ? 'true' : 'false');
        });

        if (mode === 'drill') {
            outPromptLabel.textContent = 'DRILL';
            serveDrill();
        } else if (mode === 'write') {
            outPromptLabel.textContent = 'WRITE';
            loadWritePrompt();
        } else {
            outPromptLabel.textContent = outState.drillBuffer.length > 0 ? 'DRILL' : 'WRITE';
            if (outState.drillBuffer.length > 0) {
                serveDrill();
            } else {
                loadWritePrompt();
            }
        }
        clearWriteArea();
    }

    outModeButtons.forEach(btn => {
        btn.addEventListener('click', () => setOutMode(btn.dataset.outmode));
    });

    // ==================== GENERATION ====================
    function ensureGeneration() {
        const missing = outState.bufferTarget - outState.drillBuffer.length - outState.inflight;
        if (missing <= 0) return;
        for (let i = 0; i < missing; i++) launchOneGeneration();
    }

    const MAX_DRILL_RETRIES = 3;

    async function launchOneGeneration(attempt = 1) {
        outState.inflight += 1;
        const epochAtLaunch = outState.clusterGenerationEpoch;
        let success = false;
        try {
            const payload = {
                active_clusters: activeClusters(),
                primary_cluster: currentCluster().id,
                vocab_scope: currentVocab(),
            };
            const res = await apiPost('/api/output/generate_drill', payload);
            if (res && res.success && res.drill) {
                // Discard if the cluster changed while this request was in flight
                if (epochAtLaunch !== outState.clusterGenerationEpoch) {
                    console.log('[drill] discarded stale drill (topic changed mid-flight)');
                    success = true; // treat as "resolved" — don't retry the stale drill
                } else {
                    outState.drillBuffer.push(res.drill);
                    success = true;

                    if (outState.mode === 'loop' && !outState.currentDrill) {
                        outPromptLabel.textContent = 'DRILL';
                        serveDrill();
                    } else if (outState.mode === 'drill' && !outState.currentDrill) {
                        serveDrill();
                    }
                }
            }
        } catch (err) {
            console.warn(`generate_drill attempt ${attempt} failed:`, err.message || err);
        } finally {
            outState.inflight -= 1;
        }

        if (!success && attempt < MAX_DRILL_RETRIES) {
            await new Promise(r => setTimeout(r, 400));
            return launchOneGeneration(attempt + 1);
        }

        if (!success) {
            console.error(`generate_drill gave up after ${attempt} attempts`);
        }

        if (outState.bufferTarget - outState.drillBuffer.length - outState.inflight > 0) {
            ensureGeneration();
        }
    }

    // ==================== SUB-LINE FORMATTING ====================
    function buildPromptSubLine(drill) {
        const parts = ['Translate to Russian'];

        if (drill.cluster_name) {
            parts.push(drill.cluster_name);
        }
        if (drill.rule_name) {
            parts.push(drill.rule_name);
        }
        const fLabel = facetLabel(drill.facet);
        if (fLabel) {
            parts.push(fLabel);
        }
        if (drill.vocab) {
            parts.push(`${drill.vocab} vocab`);
        }

        return parts.join(' · ');
    }

    // ==================== DRILL SERVING ====================
    function serveDrill() {
        if (outState.drillBuffer.length > 0) {
            const d = outState.drillBuffer.shift();
            outState.currentDrill = d;
            outPromptLabel.textContent = 'DRILL';
            outPromptText.textContent = d.en;
            outPromptSub.textContent = buildPromptSubLine(d);
            outWriteTextarea.dataset.kind = 'drill';
            resetSentenceNavigation();
            ensureGeneration();
        } else {
            outState.currentDrill = null;
            if (outState.mode === 'loop') {
                outPromptLabel.textContent = 'WRITE';
                loadWritePrompt();
            } else {
                outPromptText.textContent = 'Generating next drill…';
                outPromptSub.textContent = 'Waiting for generator…';
                outWriteTextarea.dataset.kind = 'drill';
            }
            ensureGeneration();
        }
    }

    // ==================== WRITE PROMPT ====================
    async function loadWritePrompt() {
        if (outState.writePromptLoading) return;
        outState.writePromptLoading = true;

        outPromptLabel.textContent = 'WRITE';
        outPromptText.textContent = outState.writePrompt || 'Choosing a prompt…';
        outPromptSub.textContent = `Write in Russian · ${currentCluster().name} · ${currentVocab()} vocab`;
        outWriteTextarea.dataset.kind = 'write';
        resetSentenceNavigation();

        try {
            const res = await apiPost('/api/output/generate_write_prompt', {
                active_clusters: activeClusters(),
                primary_cluster: currentCluster().id,
                vocab_scope: currentVocab(),
                lang: currentLang(),
            });
            if (res && res.success && res.prompt) {
                outState.writePrompt = res.prompt;
                if (outWriteTextarea.dataset.kind === 'write') {
                    outPromptText.textContent = res.prompt;
                }
            }
        } catch (err) {
            console.error('generate_write_prompt failed:', err);
            const fallback = currentLang() === 'ru'
                ? `Напиши короткий абзац по теме «${currentCluster().name}».`
                : `Write a short paragraph using structures from ${currentCluster().name}.`;
            outState.writePrompt = fallback;
            if (outWriteTextarea.dataset.kind === 'write') {
                outPromptText.textContent = fallback;
            }
        } finally {
            outState.writePromptLoading = false;
        }
    }

    // ==================== SENTENCE NAVIGATION ====================
    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function tokenizeSentence(sentence) {
        const tokens = [];
        const regex = /(\S+)/g;
        let lastIndex = 0;
        let match;
        while ((match = regex.exec(sentence)) !== null) {
            if (match.index > lastIndex) {
                tokens.push({ type: 'space', text: sentence.slice(lastIndex, match.index) });
            }
            tokens.push({ type: 'word', text: match[1] });
            lastIndex = regex.lastIndex;
        }
        if (lastIndex < sentence.length) {
            tokens.push({ type: 'space', text: sentence.slice(lastIndex) });
        }
        return tokens;
    }

    function renderSentence() {
        const s = outState.sentence;
        if (!s.tokens.length) {
            outPromptText.textContent = outState.currentDrill ? outState.currentDrill.en : '';
            return;
        }
        const parts = [];
        let wordIdx = 0;
        for (const tok of s.tokens) {
            if (tok.type === 'space') {
                parts.push(escapeHtml(tok.text));
            } else {
                const i = wordIdx;
                let cls = 'word-token';
                if (s.active) {
                    if (i === s.cursor && !s.selecting) cls += ' cursor';
                    if (s.selecting && i >= Math.min(s.anchor, s.cursor) && i <= Math.max(s.anchor, s.cursor)) {
                        cls += ' selected';
                    }
                }
                parts.push(`<span class="${cls}" data-word-index="${i}">${escapeHtml(tok.text)}</span>`);
                wordIdx++;
            }
        }
        outPromptText.innerHTML = parts.join('');
    }

    function resetSentenceNavigation() {
        outState.sentence.active = false;
        outState.sentence.words = [];
        outState.sentence.tokens = [];
        outState.sentence.cursor = -1;
        outState.sentence.anchor = -1;
        outState.sentence.selecting = false;

        outPromptText.classList.remove('focused');

        const en = outState.currentDrill ? outState.currentDrill.en : '';
        if (en && outWriteTextarea.dataset.kind === 'drill') {
            outState.sentence.tokens = tokenizeSentence(en);
            outState.sentence.words = outState.sentence.tokens
                .filter(t => t.type === 'word')
                .map(t => t.text);
        }
        renderSentence();
    }

    function enterSentenceLine() {
        if (outWriteTextarea.dataset.kind !== 'drill') return;
        if (!outState.sentence.words.length) return;

        outState.sentence.active = true;
        outState.sentence.selecting = false;
        outState.sentence.anchor = -1;
        outState.sentence.cursor = Math.floor(outState.sentence.words.length / 2);

        outWritePane.classList.remove('focused');
        outWriteTextarea.blur();
        outPromptText.classList.add('focused');
        renderSentence();
    }

    function exitSentenceLine() {
        outState.sentence.active = false;
        outState.sentence.selecting = false;
        outState.sentence.anchor = -1;
        outState.sentence.cursor = -1;

        outPromptText.classList.remove('focused');
        renderSentence();
        outWriteTextarea.focus();
    }

    function moveCursorLeft() {
        const s = outState.sentence;
        if (s.selecting) {
            if (s.cursor > Math.min(s.anchor, s.cursor)) {
                s.cursor -= 1;
            }
        } else {
            if (s.cursor > 0) s.cursor -= 1;
        }
        renderSentence();
    }

    function moveCursorRight() {
        const s = outState.sentence;
        const last = s.words.length - 1;
        if (s.selecting) {
            if (s.cursor < last) s.cursor += 1;
        } else {
            if (s.cursor < last) s.cursor += 1;
        }
        renderSentence();
    }

    function anchorSelection() {
        const s = outState.sentence;
        if (!s.active) return;
        if (s.selecting) return;

        s.selecting = true;
        s.anchor = s.cursor;
        renderSentence();
    }

    function getSelectedWords() {
        const s = outState.sentence;
        if (!s.selecting) {
            return [s.words[s.cursor]].filter(Boolean);
        }
        const a = Math.min(s.anchor, s.cursor);
        const b = Math.max(s.anchor, s.cursor);
        return s.words.slice(a, b + 1);
    }

    async function sendSelectionToChat() {
        const s = outState.sentence;
        if (!s.active) return;
        const selected = getSelectedWords();
        if (!selected.length) return;

        const sentence = outState.currentDrill ? outState.currentDrill.en : '';
        const selectionText = selected.join(' ');

        exitSentenceLine();

        appendOutChat('user', selectionText);
        outState.chatHistory.push({ role: 'user', content: selectionText });

        try {
            const res = await apiPost('/api/output/chat', {
                mode: 'translate',
                selection: { words: selected, sentence },
                active_clusters: activeClusters(),
                primary_cluster: currentCluster().id,
                vocab_scope: currentVocab(),
                lang: currentLang(),
                history: outState.chatHistory.slice(0, -1),
            });
            const reply = (res && res.reply) || '⚠️ No reply.';
            appendOutChat('bot', reply);
            outState.chatHistory.push({ role: 'assistant', content: reply });
        } catch (err) {
            console.error('translate failed:', err);
            const errMsg = `⚠️ Translation failed: ${err.message}`;
            appendOutChat('bot', errMsg);
            outState.chatHistory.push({ role: 'assistant', content: errMsg });
        }
    }

    // ==================== SUBMIT ====================
    async function submitWrite() {
        const text = outWriteTextarea.value.trim();
        if (!text) return;

        const kind = outWriteTextarea.dataset.kind || 'drill';

        if (kind === 'drill') {
            const submitted = outState.currentDrill;
            if (!submitted) { clearWriteArea(); return; }

            appendOutChat('user', text);
            outState.chatHistory.push({ role: 'user', content: text });

            clearWriteArea();

            try {
                const res = await apiPost('/api/output/chat', {
                    mode: 'drill',
                    user_answer: text,
                    drill: submitted,
                    active_clusters: activeClusters(),
                    primary_cluster: currentCluster().id,
                    vocab_scope: currentVocab(),
                    lang: currentLang(),
                    history: outState.chatHistory.slice(0, -1),
                });
                const reply = (res && res.reply) || '⚠️ No reply.';
                appendOutChat('bot', reply);
                outState.chatHistory.push({ role: 'assistant', content: reply });
            } catch (err) {
                console.error('drill chat failed:', err);
                const errMsg = `⚠️ Analysis failed: ${err.message}`;
                appendOutChat('bot', errMsg);
                outState.chatHistory.push({ role: 'assistant', content: errMsg });
            }

            outState.lastDrill = submitted;
            serveDrill();
        } else {
            const prompt = outState.writePrompt || '(unknown prompt)';
            appendOutChat('user', text);
            outState.chatHistory.push({ role: 'user', content: text });
            clearWriteArea();

            try {
                const res = await apiPost('/api/output/chat', {
                    mode: 'write',
                    user_answer: text,
                    write_prompt: prompt,
                    active_clusters: activeClusters(),
                    primary_cluster: currentCluster().id,
                    vocab_scope: currentVocab(),
                    lang: currentLang(),
                    history: outState.chatHistory.slice(0, -1),
                });
                const reply = (res && res.reply) || '⚠️ No reply.';
                appendOutChat('bot', reply);
                outState.chatHistory.push({ role: 'assistant', content: reply });
            } catch (err) {
                console.error('write chat failed:', err);
                const errMsg = `⚠️ Analysis failed: ${err.message}`;
                appendOutChat('bot', errMsg);
                outState.chatHistory.push({ role: 'assistant', content: errMsg });
            }

            outState.writeIndex += 1;
            outState.writePrompt = null;

            if (outState.mode === 'loop') {
                if (outState.drillBuffer.length > 0 || outState.currentDrill) {
                    serveDrill();
                } else {
                    ensureGeneration();
                    loadWritePrompt();
                }
            } else if (outState.mode === 'write') {
                loadWritePrompt();
            }
        }
    }

    function clearWriteArea() {
        outWriteTextarea.value = '';
        outWriteTextarea.focus();
    }

    // ==================== CHAT ====================
    function appendOutChat(role, text) {
        const msg = document.createElement('div');
        msg.className = `chat-msg chat-msg-${role}`;
        msg.innerHTML = `
            <div class="chat-avatar">${role === 'user' ? '🧑' : '🤖'}</div>
            <div class="chat-bubble"></div>
        `;
        msg.querySelector('.chat-bubble').textContent = text;
        outChatScroll.appendChild(msg);
        outChatScroll.scrollTop = outChatScroll.scrollHeight;
    }

    async function sendOutChat() {
        const text = outChatInput.value.trim();
        if (!text) return;

        appendOutChat('user', text);
        outState.chatHistory.push({ role: 'user', content: text });
        outChatInput.value = '';
        outChatInput.style.height = 'auto';

        if (text.toLowerCase().includes('redo') && outState.lastDrill) {
            outState.drillBuffer.unshift({ ...outState.lastDrill });
            const msg = 'OK — reloaded the previous drill.';
            appendOutChat('bot', msg);
            outState.chatHistory.push({ role: 'assistant', content: msg });
            if (outState.mode === 'drill' || outState.mode === 'loop') serveDrill();
            return;
        }

        try {
            const res = await apiPost('/api/output/chat', {
                mode: 'chat',
                message: text,
                current_drill: outState.currentDrill,
                write_prompt: outState.writePrompt,
                active_clusters: activeClusters(),
                primary_cluster: currentCluster().id,
                vocab_scope: currentVocab(),
                lang: currentLang(),
                history: outState.chatHistory.slice(0, -1),
            });
            const reply = (res && res.reply) || '⚠️ No reply.';
            appendOutChat('bot', reply);
            outState.chatHistory.push({ role: 'assistant', content: reply });
        } catch (err) {
            console.error('out chat failed:', err);
            const errMsg = `⚠️ Chat failed: ${err.message}`;
            appendOutChat('bot', errMsg);
            outState.chatHistory.push({ role: 'assistant', content: errMsg });
        }
    }

    // ==================== EVENT WIRING ====================
    outWriteTextarea.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            submitWrite();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            enterSentenceLine();
        }
    });

    document.addEventListener('keydown', (e) => {
        if (!outState.sentence.active) return;
        if (document.body.dataset.mode !== 'out') return;

        const key = e.key;

        if (key === 'ArrowLeft') {
            e.preventDefault();
            moveCursorLeft();
        } else if (key === 'ArrowRight') {
            e.preventDefault();
            moveCursorRight();
        } else if (key === 'ArrowDown') {
            e.preventDefault();
            exitSentenceLine();
        } else if (key === 'Escape') {
            e.preventDefault();
            exitSentenceLine();
        } else if (key === 'Shift') {
            e.preventDefault();
            anchorSelection();
        } else if (key === 'Enter') {
            e.preventDefault();
            sendSelectionToChat();
        }
    }, true);

    outPromptText.addEventListener('click', () => {
        if (outState.sentence.active) return;
        if (outWriteTextarea.dataset.kind !== 'drill') return;
        if (!outState.sentence.words.length) return;
        enterSentenceLine();
    });

    outWriteTextarea.addEventListener('focus', () => {
        outWritePane.classList.add('focused');
        if (outState.sentence.active) exitSentenceLine();
    });
    outWriteTextarea.addEventListener('blur',  () => outWritePane.classList.remove('focused'));
    outChatInput.addEventListener('focus',    () => outChatPane.classList.add('focused'));
    outChatInput.addEventListener('blur',     () => outChatPane.classList.remove('focused'));

    outChatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendOutChat();
        }
    });

    outChatInput.addEventListener('input', (e) => {
        e.target.style.height = 'auto';
        e.target.style.height = Math.min(e.target.scrollHeight, 100) + 'px';
    });

    outChatSend.addEventListener('click', sendOutChat);

    // ==================== INIT ====================
    setMode(readInitialMode(), { updateHash: false });
    setLang(readInitialLang());

    updateGrammarLabel();
    updateVocabLabel();
    updateBufferLabel();

    outState.currentDrill = null;
    setOutMode(outState.mode);
    ensureGeneration();

    console.log('🐚 Shell loaded — epoch tracking + readable facet labels active');
})();
