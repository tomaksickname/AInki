/* ==================== AInki — Keyboard Layer ==================== */

(() => {
    'use strict';

    // ЙЦУКЕН mapping: physical English key → Cyrillic character.
    const RU_MAP = {
        'q': 'й', 'w': 'ц', 'e': 'у', 'r': 'к', 't': 'е',
        'y': 'н', 'u': 'г', 'i': 'ш', 'o': 'щ', 'p': 'з',
        '[': 'х', ']': 'ъ', '\\': 'ё',
        'a': 'ф', 's': 'ы', 'd': 'в', 'f': 'а', 'g': 'п',
        'h': 'р', 'j': 'о', 'k': 'л', 'l': 'д', ';': 'ж', "'": 'э',
        'z': 'я', 'x': 'ч', 'c': 'с', 'v': 'м', 'b': 'и',
        'n': 'т', 'm': 'ь', ',': 'б', '.': 'ю', '/': '.',
    };

    // ---- Focus tracking ----
    const paneFocus = {
        outWrite: null,
        outChat: null,
        inCard: null,
        inChat: null,
    };

    let activePane = 'outWrite';

    function paneOf(el) {
        if (!el || !el.closest) return null;
        if (el.closest('#outWritePane')) return 'outWrite';
        if (el.closest('#outChatPane'))  return 'outChat';
        if (el.closest('.in-card-pane')) return 'inCard';
        if (el.closest('.in-chat-pane')) return 'inChat';
        return null;
    }

    document.addEventListener('focusin', (e) => {
        const pane = paneOf(e.target);
        if (!pane) return;
        paneFocus[pane] = e.target;
        activePane = pane;
    });

    // ---- Tab swaps focus between top and bottom panes ----
    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Tab') return;

        const mode = document.body.dataset.mode || 'in';
        const current = paneOf(document.activeElement);
        let target = null;

        if (mode === 'out') {
            if (current === 'outWrite') {
                target = paneFocus.outChat || document.getElementById('outChatInput');
            } else if (current === 'outChat') {
                target = paneFocus.outWrite || document.getElementById('outWriteTextarea');
            } else {
                target = document.getElementById('outWriteTextarea');
            }
        } else {
            if (current === 'inCard') {
                target = paneFocus.inChat || document.getElementById('inChatInput');
            } else if (current === 'inChat') {
                target = document.getElementById('card');
            } else {
                target = document.getElementById('inChatInput');
            }
        }

        if (target && typeof target.focus === 'function') {
            e.preventDefault();
            target.focus();
            if (typeof target.setSelectionRange === 'function' && target.value !== undefined) {
                try { target.setSelectionRange(target.value.length, target.value.length); } catch (_) {}
            }
        }
    });

    // ---- Caps Lock tracking ----
    let capsLockOn = false;

    document.addEventListener('keydown', (e) => {
        if (e.key === 'CapsLock') {
            if (typeof e.getModifierState === 'function') {
                capsLockOn = e.getModifierState('CapsLock');
            } else {
                capsLockOn = !capsLockOn;
            }
        }
    });

    document.addEventListener('keyup', (e) => {
        if (e.key === 'CapsLock' && typeof e.getModifierState === 'function') {
            capsLockOn = e.getModifierState('CapsLock');
        }
    });

    // Sync on any keydown (Caps state can drift if toggled while unfocused)
    document.addEventListener('keydown', (e) => {
        if (typeof e.getModifierState === 'function' && e.key !== 'CapsLock') {
            capsLockOn = e.getModifierState('CapsLock');
        }
    }, true);

    // ---- Cyrillic remapping ----
    document.addEventListener('keydown', (e) => {
        const el = document.activeElement;
        if (!el || el.dataset === undefined) return;
        if (el.dataset.lang !== 'ru') return;
        if (el.tagName !== 'TEXTAREA' && el.tagName !== 'INPUT') return;

        if (e.ctrlKey || e.metaKey || e.altKey) return;

        const passthrough = [
            'Enter', 'Tab', 'Backspace', 'Delete',
            'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown',
            'Home', 'End', 'PageUp', 'PageDown', 'Escape', 'CapsLock',
        ];
        if (passthrough.includes(e.key)) return;
        if (e.key.length !== 1) return;

        const lower = e.key.toLowerCase();
        const mapped = RU_MAP[lower];
        if (!mapped) return;

        // Uppercase if: Shift XOR CapsLock
        const upper = e.shiftKey !== capsLockOn;
        const ch = upper ? mapped.toUpperCase() : mapped;

        e.preventDefault();
        insertText(el, ch);
    });

    function insertText(el, text) {
        const start = el.selectionStart;
        const end = el.selectionEnd;
        const value = el.value;

        try {
            const ok = document.execCommand('insertText', false, text);
            if (ok) return;
        } catch (_) {}

        el.value = value.slice(0, start) + text + value.slice(end);
        const pos = start + text.length;
        el.setSelectionRange(pos, pos);
        el.dispatchEvent(new Event('input', { bubbles: true }));
    }

    window.AInkiKeyboard = {
        RU_MAP,
        paneOf,
        getActivePane: () => activePane,
        isCapsLockOn: () => capsLockOn,
    };

    console.log('⌨️  Keyboard layer loaded — Tab swaps panes, RU mapping + Caps Lock active');
})();
