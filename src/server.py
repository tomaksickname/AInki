#!/usr/bin/env python3
"""
AInki — API Server
==================

Flask server: static file serving, IN-half review API, OUT-half LLM API.

OUT-half architecture:
    - Two separate LLM clients: drill (generates English sentences)
      and chat (grades, reviews, chats).
    - Rule selection: cluster boost is ×10, so the current cluster
      dominates (~65-75% of drills) while previous clusters fill the rest.
    - Facet selection within a rule is done by the drill LLM.
    - Self-verification: after generation, a second LLM call confirms
      the sentence actually exercises the target rule.
    - Grading distinguishes typos from grammar errors. Inaudible spelling
      variations (phonetic reductions, ий/ый, тся/ться, etc.) do not fail
      the target rule. Only grammatical errors do.

Chat shortcuts:
    OUT chat:  "." = explain current sentence, "?" = what's this testing,
               short word/phrase = translate it, "how many" = drill count
    IN chat:   "e" = explain word, "." = explain sentence, "?" = explain both

Word-selection translation:
    mode="translate" with selection={words, sentence}.

Chat history:
    Passed via the "history" field: [{role, content}, ...].
"""

import json
import logging
import os
import re
import sys
import threading
from datetime import datetime
from pathlib import Path

import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

sys.path.insert(0, str(Path(__file__).resolve().parent))

from file_manager import FileManager
from srs_engine import SRSEngine
from urgency_engine import UrgencyEngine


# ==================== SETUP ====================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

SRC_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SRC_DIR.parent
WEB_DIR = PROJECT_ROOT / "web"

app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="")
CORS(app)

_fm = None
_srs = None
_urgency = None


def get_engines():
    global _fm, _srs, _urgency
    if _fm is None:
        _fm = FileManager()
        config = _fm.get_config()
        _srs = SRSEngine(config)
        _urgency = UrgencyEngine(config)
    return _fm, _srs, _urgency


def get_config():
    fm, _, _ = get_engines()
    return fm.get_config()


def _completed_today(word, today_str):
    srs = word.get("srs_data", {})
    last = srs.get("last_reviewed")
    if not last:
        return False
    if last[:10] != today_str:
        return False
    return srs.get("state") != "learning"


def _is_learning(word):
    return word.get("srs_data", {}).get("state") == "learning"


# ==================== ENV LOADING ====================

_env_cache = None


def _read_env(var_name):
    global _env_cache
    if _env_cache is None:
        _env_cache = {}
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            try:
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, _, v = line.partition("=")
                        _env_cache[k.strip()] = v.strip().strip('"').strip("'")
            except Exception as e:
                logger.warning(f"Failed to read .env: {e}")

    val = os.environ.get(var_name) or _env_cache.get(var_name)
    if val:
        return val

    return os.environ.get("DEEPSEEK_API_KEY") or _env_cache.get("DEEPSEEK_API_KEY")


# ==================== LLM CLIENT ====================

class LLMClient:
    def __init__(self, settings, label="llm"):
        self.label = label
        self.base_url = settings.get("base_url", "https://api.deepseek.com/v1").rstrip("/")
        self.model = settings.get("model", "deepseek-chat")
        self.temperature = settings.get("temperature", 0.7)
        self.max_tokens = settings.get("max_tokens", 500)
        self.timeout = settings.get("timeout", 40)
        self.api_key_env = settings.get("api_key_env", "DEEPSEEK_API_KEY")
        self.api_key = _read_env(self.api_key_env)

        if not self.api_key:
            logger.warning(
                f"[{label}] No API key found for env var {self.api_key_env}. "
                f"LLM calls will fail."
            )
        else:
            logger.info(f"[{label}] ready: model={self.model} base={self.base_url}")

    def call(self, prompt, system=None, json_mode=False, temperature=None, history=None):
        if not self.api_key:
            logger.error(f"[{self.label}] no API key — cannot call")
            return None

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        if history:
            for m in history:
                role = m.get("role")
                content = m.get("content")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        except requests.exceptions.RequestException as e:
            logger.warning(f"[{self.label}] request error: {e}")
            return None

        if resp.status_code != 200:
            logger.warning(
                f"[{self.label}] HTTP {resp.status_code}: {resp.text[:200]}"
            )
            return None

        try:
            return resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as e:
            logger.error(f"[{self.label}] malformed response: {e}")
            return None

    def call_json(self, prompt, system=None, history=None):
        text = self.call(prompt, system=system, json_mode=True, history=history)
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group())
                except json.JSONDecodeError:
                    pass
            logger.warning(f"[{self.label}] could not parse JSON: {text[:150]}")
            return None


_drill_llm = None
_chat_llm = None


def get_drill_llm():
    global _drill_llm
    if _drill_llm is None:
        config = get_config()
        settings = config.get("drill_settings", {})
        _drill_llm = LLMClient(settings, label="drill")
    return _drill_llm


def get_chat_llm():
    global _chat_llm
    if _chat_llm is None:
        config = get_config()
        settings = config.get("chat_settings", {})
        _chat_llm = LLMClient(settings, label="chat")
    return _chat_llm


# ==================== HELPERS ====================

def _contains_cyrillic(s):
    return bool(re.search(r"[а-яА-ЯёЁ]", s or ""))


def _is_single_word(s):
    s = (s or "").strip()
    if not s:
        return False
    return len(s.split()) == 1


def _lang_directive(lang):
    if lang == "ru":
        return "Отвечай ПО-РУССКИ. Используй русский язык во всём ответе."
    return "Reply in ENGLISH."


# ==================== STATIC FILES ====================

@app.route("/")
def serve_index():
    return send_from_directory(str(WEB_DIR), "index.html")


@app.route("/styles.css")
def serve_styles():
    return send_from_directory(str(WEB_DIR), "styles.css")


@app.route("/app.js")
def serve_app():
    return send_from_directory(str(WEB_DIR), "app.js")


@app.route("/shell.css")
def serve_shell_styles():
    return send_from_directory(str(WEB_DIR), "shell.css")


@app.route("/keyboard.js")
def serve_keyboard_script():
    return send_from_directory(str(WEB_DIR), "keyboard.js")


@app.route("/shell.js")
def serve_shell_script():
    return send_from_directory(str(WEB_DIR), "shell.js")


# ==================== GENERATOR STATE ====================

GENERATOR_STATE_PATH = PROJECT_ROOT / "data" / "generator_state.json"

_gen_state = {
    "status": "idle",
    "progress": 0.0,
    "message": "",
    "started_at": None,
    "finished_at": None,
    "error": None,
}
_gen_lock = threading.Lock()


def _load_generator_state():
    try:
        if not GENERATOR_STATE_PATH.exists():
            return {}
        with open(GENERATOR_STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save_generator_state(state):
    try:
        import tempfile as _tempfile
        import os as _os
        GENERATOR_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = _tempfile.mkstemp(
            dir=GENERATOR_STATE_PATH.parent,
            prefix=".genstate.",
            suffix=".tmp",
        )
        try:
            with _os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            _os.replace(tmp_path, GENERATOR_STATE_PATH)
        except Exception:
            if _os.path.exists(tmp_path):
                _os.remove(tmp_path)
            raise
    except Exception as e:
        logger.error(f"Failed to save generator state: {e}")


def _has_run_today():
    state = _load_generator_state()
    today = datetime.now().date().isoformat()
    return state.get("last_run_date") == today


def _set_gen_status(status, progress=None, message=None, error=None):
    with _gen_lock:
        _gen_state["status"] = status
        if progress is not None:
            _gen_state["progress"] = progress
        if message is not None:
            _gen_state["message"] = message
        if error is not None:
            _gen_state["error"] = error
        if status == "running" and _gen_state["started_at"] is None:
            _gen_state["started_at"] = datetime.now().isoformat()
        if status in ("done", "error"):
            _gen_state["finished_at"] = datetime.now().isoformat()


def _run_generator_thread():
    try:
        from daily_generator import DailyGenerator
        gen = DailyGenerator()

        def on_progress(pct, msg):
            _set_gen_status("running", progress=float(pct), message=str(msg))

        _set_gen_status("running", progress=0.0, message="Starting...")
        summary = gen.run(progress_callback=on_progress)

        state = _load_generator_state()
        state["last_run_date"] = datetime.now().date().isoformat()
        state["last_run_completed_at"] = datetime.now().isoformat()
        state["last_summary"] = {
            "new_cards": summary.get("new_cards", 0),
            "review_cards": summary.get("review_cards", 0),
            "sentences_generated": summary.get("sentences_generated", 0),
            "sentences_failed": summary.get("sentences_failed", 0),
        }
        _save_generator_state(state)

        _set_gen_status("done", progress=1.0, message="Done")
    except Exception as e:
        logger.exception("Generator thread failed")
        _set_gen_status("error", message="Generation failed", error=str(e))


# ==================== API: GENERATOR ====================

@app.route("/api/admin/generate", methods=["POST"])
def admin_generate():
    with _gen_lock:
        if _gen_state["status"] == "running":
            return jsonify({
                "success": False,
                "error": "Generator already running",
            }), 409
        _gen_state["status"] = "idle"
        _gen_state["progress"] = 0.0
        _gen_state["message"] = ""
        _gen_state["error"] = None
        _gen_state["started_at"] = None
        _gen_state["finished_at"] = None

    t = threading.Thread(target=_run_generator_thread, daemon=True)
    t.start()
    return jsonify({"success": True, "message": "Generator started"})


@app.route("/api/admin/generate/status", methods=["GET"])
def admin_generate_status():
    with _gen_lock:
        return jsonify({
            "status": _gen_state["status"],
            "progress": _gen_state["progress"],
            "message": _gen_state["message"],
            "error": _gen_state["error"],
            "started_at": _gen_state["started_at"],
            "finished_at": _gen_state["finished_at"],
        })


# ==================== DAILY DRILL COUNTER ====================

DRILL_STATS_PATH = PROJECT_ROOT / "data" / "drill_stats.json"


def _load_drill_stats():
    try:
        if not DRILL_STATS_PATH.exists():
            return {}
        with open(DRILL_STATS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except Exception as e:
        logger.warning(f"Could not load drill stats: {e}")
        return {}


def _save_drill_stats(stats):
    try:
        import tempfile as _tempfile
        import os as _os
        DRILL_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = _tempfile.mkstemp(
            dir=DRILL_STATS_PATH.parent,
            prefix=".drillstats.",
            suffix=".tmp",
        )
        try:
            with _os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(stats, f, ensure_ascii=False, indent=2)
            _os.replace(tmp_path, DRILL_STATS_PATH)
        except Exception:
            if _os.path.exists(tmp_path):
                _os.remove(tmp_path)
            raise
    except Exception as e:
        logger.error(f"Failed to save drill stats: {e}")


def _increment_drill_count():
    today = datetime.now().date().isoformat()
    stats = _load_drill_stats()
    stats[today] = int(stats.get(today, 0)) + 1
    _save_drill_stats(stats)
    return stats[today]


def _get_drill_count(day=None):
    if day is None:
        day = datetime.now().date().isoformat()
    stats = _load_drill_stats()
    return int(stats.get(day, 0))


def _is_how_many_query(message):
    m = (message or "").lower()
    triggers = [
        "how many",
        "drill count",
        "drills today",
        "how many drills",
        "session count",
    ]
    return any(t in m for t in triggers)


# ==================== GRAMMAR LEXICON ====================

GRAMMAR_LEXICON_PATH = PROJECT_ROOT / "data" / "grammar_lexicon.json"
FACET_WARNINGS_LOG = PROJECT_ROOT / "data" / "facet_warnings.log"
_grammar_cache = None


def _load_grammar_lexicon():
    global _grammar_cache
    if _grammar_cache is None:
        try:
            with open(GRAMMAR_LEXICON_PATH, "r", encoding="utf-8") as f:
                _grammar_cache = json.load(f)
            logger.info(
                f"Loaded grammar lexicon: "
                f"{len(_grammar_cache.get('rules', {}))} rules, "
                f"{len(_grammar_cache.get('state', {}))} state entries"
            )
        except FileNotFoundError:
            logger.warning(f"Grammar lexicon not found at {GRAMMAR_LEXICON_PATH}")
            _grammar_cache = {
                "clusters": {"definitions": {}},
                "rules": {},
                "state": {},
            }
    return _grammar_cache


def _save_grammar_lexicon():
    if _grammar_cache is None:
        return
    try:
        import tempfile as _tempfile
        import os as _os
        GRAMMAR_LEXICON_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = _tempfile.mkstemp(
            dir=GRAMMAR_LEXICON_PATH.parent,
            prefix=".grammar.",
            suffix=".tmp",
        )
        try:
            with _os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(_grammar_cache, f, ensure_ascii=False, indent=2)
            _os.replace(tmp_path, GRAMMAR_LEXICON_PATH)
        except Exception:
            if _os.path.exists(tmp_path):
                _os.remove(tmp_path)
            raise
    except Exception as e:
        logger.error(f"Failed to save grammar lexicon: {e}")


def _log_facet_warning(rule_id, reported_facet, context):
    try:
        FACET_WARNINGS_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now().isoformat(),
            "rule_id": rule_id,
            "reported_facet": reported_facet,
            "context": context,
        }
        with open(FACET_WARNINGS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"Could not write facet warning log: {e}")


# ==================== RULE / FACET SELECTION ====================

import random as _random


def _now_iso():
    return datetime.now().isoformat()


def _parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _days_since(s):
    dt = _parse_iso(s)
    if dt is None:
        return 3650
    return max(0, (datetime.now() - dt).days)


def _rule_priority(rule_id, rule_def, rule_state, primary_cluster):
    state = rule_state.get("state", "unlearned")
    cluster = rule_def.get("cluster", 1)

    # Base priority by state
    if state == "unlearned":
        base = 3.0
    elif state == "learning":
        base = 2.0
    else:  # mastered
        base = 0.3

    # Cluster boost: current cluster dominates at ×10
    if cluster == primary_cluster:
        base *= 10.0

    # Recency boost for learning rules that failed recently
    if state == "learning":
        days_since_fail = _days_since(rule_state.get("last_failed"))
        if days_since_fail <= 2:
            base *= 2.0
        elif days_since_fail <= 7:
            base *= 1.5

    # Staleness boost for mastered rules so regressions get caught
    if state == "mastered":
        days_since_test = _days_since(rule_state.get("last_tested"))
        if days_since_test >= 30:
            base *= 1.5
        elif days_since_test >= 14:
            base *= 1.2

    # Jitter
    base *= _random.uniform(0.7, 1.3)
    return base


def _select_rule(active_clusters, primary_cluster):
    lex = _load_grammar_lexicon()
    clusters_def = lex.get("clusters", {}).get("definitions", {})
    rules = lex.get("rules", {})
    state = lex.get("state", {})

    candidate_ids = []
    for cid in active_clusters:
        cdef = clusters_def.get(str(cid)) or clusters_def.get(cid)
        if not cdef:
            continue
        for rid in cdef.get("rules", []):
            if rid in rules:
                candidate_ids.append(rid)

    if not candidate_ids:
        return None, None, None

    weights = []
    for rid in candidate_ids:
        rule_def = rules[rid]
        rule_state = state.get(rid, {})
        weights.append(_rule_priority(rid, rule_def, rule_state, primary_cluster))

    total = sum(weights)
    if total <= 0:
        rid = _random.choice(candidate_ids)
    else:
        pick = _random.uniform(0, total)
        acc = 0.0
        rid = candidate_ids[-1]
        for r, w in zip(candidate_ids, weights):
            acc += w
            if acc >= pick:
                rid = r
                break

    return rid, rules.get(rid), state.get(rid, {})


def _cluster_name(cluster_id):
    lex = _load_grammar_lexicon()
    cdef = (lex.get("clusters", {}).get("definitions", {}) or {}).get(str(cluster_id))
    if cdef:
        return cdef.get("name", f"Cluster {cluster_id}")
    return f"Cluster {cluster_id}"


def _facet_history_block(rule_id, rule_def, rule_state):
    facets = rule_def.get("facets", ["default"])
    hints = rule_def.get("facet_hints", {})
    facet_state = rule_state.get("facets", {})

    lines = []
    for fname in facets:
        fs = facet_state.get(fname, {})
        tested = fs.get("times_tested", 0)
        correct = fs.get("times_correct", 0)
        consec = fs.get("consecutive_correct", 0)
        last_failed = fs.get("last_failed")
        hint = hints.get(fname, "")

        parts = [f"  - {fname}"]
        if hint:
            parts.append(f"({hint})")
        parts.append(f"| tested {tested}×, correct {correct}×, consecutive clean {consec}")
        if last_failed:
            days = _days_since(last_failed)
            parts.append(f"| last failed {days}d ago")
        lines.append(" ".join(parts))

    return "\n".join(lines)


# ==================== OUTPUT: DRILL GENERATION ====================

def _verify_drill_requires_rule(llm, en, rule_name, rule_desc):
    """
    Ask the LLM whether the given English sentence, when translated to
    Russian, requires the target rule. Returns True/False/None.
    """
    if not llm.api_key:
        return None

    prompt = f"""You are evaluating a translation drill for quality.

The drill is meant to test this Russian grammar rule:
  Rule: {rule_name}
  What it does: {rule_desc}

The drill sentence (English): "{en}"

Question: When a learner translates this sentence into Russian, does the
translation REQUIRE the learner to use the rule above? Or could the
sentence be translated correctly WITHOUT using the rule at all?

Be strict. If the rule is optional (learner could avoid it), the answer
is NO. If the rule is required (learner must use it to sound natural),
the answer is YES.

Return JSON only: {{"requires": true | false, "reason": "one short sentence"}}
"""
    result = llm.call_json(prompt)
    if result and isinstance(result, dict):
        return bool(result.get("requires"))
    return None


@app.route("/api/output/generate_drill", methods=["POST"])
def generate_drill():
    try:
        data = request.get_json(force=True, silent=True) or {}
        active_clusters = data.get("active_clusters") or [1]
        primary_cluster = data.get("primary_cluster") or active_clusters[-1]
        vocab_scope = data.get("vocab_scope", "B1")

        rule_id, rule_def, rule_state = _select_rule(active_clusters, primary_cluster)
        if rule_id is None:
            return jsonify({
                "success": False,
                "error": "No rules in active clusters",
            }), 400

        cluster_id = rule_def.get("cluster", 1)
        cluster_name = _cluster_name(cluster_id)
        rule_name = rule_def.get("name", rule_id)
        rule_desc = rule_def.get("description", "")
        example = (rule_def.get("example_sentences") or [""])[0]

        facet_block = _facet_history_block(rule_id, rule_def, rule_state)
        facets_available = rule_def.get("facets", ["default"])

        llm = get_drill_llm()
        if not llm.api_key:
            return jsonify({
                "success": False,
                "error": "Drill LLM not configured",
            }), 503

        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            retry_hint = ""
            if attempt > 1:
                retry_hint = (
                    "\n\nIMPORTANT: A previous attempt produced a sentence that "
                    "could be translated WITHOUT using the target rule. Be stricter "
                    "this time. The sentence MUST force the learner to produce the "
                    "target structure — there should be no natural way to avoid it."
                )

            prompt = f"""You are generating a translation drill for a Russian learner.

The learner is practising this grammar rule:
  Rule: {rule_id} — {rule_name}
  What it does: {rule_desc}
  Example: {example}

The rule has these facets (sub-dimensions), with the learner's history:
{facet_block}

Pick the ONE facet most worth testing. Prefer facets with more failures,
fewer samples, or an older last-tested date. Then generate ONE natural
English sentence (6-15 words) that, when translated into Russian,
REQUIRES the learner to use that facet. Not "makes it likely" or
"invites it" — REQUIRES it. If the learner could produce a natural
Russian translation without using the target structure, the drill is
invalid.

The sentence should describe an ordinary everyday situation. It should
not be a question, an instruction, or a hypothetical.

The rest of the sentence (beyond the target structure) may use ANY
Russian grammar, including rules the learner has not studied yet. The
sentence should sound natural, not artificially limited.

Hard constraints:
- Output a single English sentence. No preamble, no explanation.
- Do NOT mention the grammar rule, "translate", or "sentence" in the output.
- Do NOT use placeholder names like "John" or "the learner".
- The facet you picked MUST be one of: {facets_available}

Vocabulary complexity target: CEFR {vocab_scope}.{retry_hint}

Return JSON only:
{{
  "facet": "the facet name you picked",
  "reason": "one short sentence explaining why",
  "en": "the English sentence"
}}
"""
            result = llm.call_json(prompt)
            if not (result and isinstance(result, dict) and result.get("en")):
                logger.warning(f"[drill] attempt {attempt}: no usable output for {rule_id}")
                continue

            en = result["en"].strip()
            chosen_facet = result.get("facet", "default")
            if chosen_facet not in facets_available:
                _log_facet_warning(rule_id, chosen_facet, "generation")
                chosen_facet = "default"

            verified = _verify_drill_requires_rule(llm, en, rule_name, rule_desc)
            if verified is True:
                logger.info(
                    f"[drill] {rule_id} facet={chosen_facet} verified  "
                    f"reason={result.get('reason', '')[:60]}"
                )
                return jsonify({
                    "success": True,
                    "drill": {
                        "en": en,
                        "rule_id": rule_id,
                        "rule_name": rule_name,
                        "facet": chosen_facet,
                        "facet_reason": result.get("reason", ""),
                        "cluster": cluster_id,
                        "cluster_name": cluster_name,
                        "vocab": vocab_scope,
                    },
                })
            else:
                logger.warning(
                    f"[drill] attempt {attempt}: drill for {rule_id} failed verification "
                    f"(requires={verified}). Sentence: {en[:80]}"
                )

        logger.warning(f"[drill] gave up after {max_attempts} attempts for {rule_id}")
        return jsonify({
            "success": False,
            "error": "Drill generation failed verification. Retry.",
        }), 502

    except Exception as e:
        logger.exception("Error in /api/output/generate_drill")
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== OUTPUT: WRITE PROMPT ====================

@app.route("/api/output/generate_write_prompt", methods=["POST"])
def generate_write_prompt():
    try:
        data = request.get_json(force=True, silent=True) or {}
        active_clusters = data.get("active_clusters") or [1]
        primary_cluster = data.get("primary_cluster") or active_clusters[-1]
        vocab_scope = data.get("vocab_scope", "B1")
        lang = data.get("lang", "en")

        rule_id, rule_def, _ = _select_rule(active_clusters, primary_cluster)
        cluster_id = rule_def.get("cluster", 1) if rule_def else 1
        rule_name = rule_def.get("name", "") if rule_def else ""
        cluster_name = _cluster_name(cluster_id)

        lang_instruction = (
            "Write the prompt in ENGLISH."
            if lang == "en"
            else "Напиши задание ПО-РУССКИ."
        )

        llm = get_chat_llm()
        if llm.api_key:
            prompt = f"""You are generating a short writing prompt for a
Russian learner.

Current grammar focus: {cluster_name} (rule: {rule_name})
Vocabulary complexity target: CEFR {vocab_scope}

{lang_instruction}

The prompt should be a single short instruction, under 15 words. Examples:
"Describe your morning routine."
"Write about a trip you took last year."

Return JSON only: {{"prompt": "..."}}
"""
            result = llm.call_json(prompt)
            if result and isinstance(result, dict) and result.get("prompt"):
                return jsonify({
                    "success": True,
                    "prompt": result["prompt"].strip(),
                })

        fallback = (
            f"Write a short paragraph using structures from {cluster_name}."
            if lang == "en"
            else f"Напиши короткий абзац, используя конструкции из темы «{cluster_name}»."
        )
        return jsonify({"success": True, "prompt": fallback, "fallback": True})

    except Exception as e:
        logger.exception("Error in /api/output/generate_write_prompt")
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== OUTPUT: CHAT ====================

@app.route("/api/output/chat", methods=["POST"])
def output_chat():
    try:
        data = request.get_json(force=True, silent=True) or {}
        mode = data.get("mode", "chat")
        lang = data.get("lang", "en")

        if mode == "chat":
            message = (data.get("message") or "").strip()
            if _is_how_many_query(message):
                count = _get_drill_count()
                today = datetime.now().date().isoformat()
                return jsonify({
                    "success": True,
                    "reply": f"{count} drills today ({today})",
                })

        llm = get_chat_llm()
        if not llm.api_key:
            return jsonify({
                "success": False,
                "reply": "⚠️ Chat LLM not configured. Check config + .env.",
            })

        if mode == "drill":
            reply = _handle_drill_chat(llm, data, lang)
        elif mode == "write":
            reply = _handle_write_chat(llm, data, lang)
        elif mode == "translate":
            reply = _handle_translate_chat(llm, data, lang)
        else:
            reply = _handle_free_chat(llm, data, lang)

        return jsonify({"success": True, "reply": reply})

    except Exception as e:
        logger.exception("Error in /api/output/chat")
        return jsonify({
            "success": False,
            "reply": f"⚠️ Server error: {e}",
        }), 500


def _build_app_context(data):
    active = data.get("active_clusters") or []
    primary = data.get("primary_cluster")
    vocab = data.get("vocab_scope", "")
    drill = data.get("current_drill") or data.get("drill") or {}

    lines = []
    if primary is not None:
        lines.append(f"- Grammar topic: {_cluster_name(primary)} (#{primary} of 25)")
    elif active:
        lines.append(f"- Grammar topic: {_cluster_name(active[-1])} (#{active[-1]} of 25)")
    if vocab:
        lines.append(f"- Vocabulary complexity target: CEFR {vocab}")
    if drill:
        rule_name = drill.get("rule_name") or drill.get("rule_id")
        facet = drill.get("facet")
        if rule_name:
            extra = f", facet {facet}" if facet else ""
            lines.append(f"- Current drill target rule: {rule_name}{extra}")
    return "\n".join(lines) if lines else "(no app context)"


# ─── Typo/grammar policy text shared by grading prompts ───

TYPO_POLICY_BLOCK = """
IMPORTANT — distinguish between grammatical errors and typos:

A **grammatical error** means the required grammatical form was not
produced: wrong case ending, wrong gender/number agreement, wrong
aspect, wrong verb government, wrong preposition that changes the
required case, or the target structure was avoided entirely. These
DO count as rule failures.

A **typo** means the grammatical form is CORRECT but a letter is
misspelled in a way that a native speaker would not hear. These do
NOT count as rule failures. Note them in the feedback so the learner
sees the mistake, but do not fail the rule.

Typos include (for Russian):
- Phonetic vowel reductions written phonetically: `харашо` for `хорошо`,
  `малако` for `молоко`, `сабака` for `собака`.
- The `-тся` / `-ться` distinction in reflexive verbs — these are
  pronounced identically and cannot be heard.
- ш/ж/ч/щ/ц vowel rules: writing `-ы` after ш/ж/ч/щ where `-и` is correct,
  or `-о` after these consonants where `-е` is correct.
- Missing or extra `ь` in positions where it does not change the
  grammatical form.
- Double consonant errors in loanwords: `клас` for `класс`.
- `ё` vs `е` when the meaning is unambiguous.

Hard/soft stem adjective endings get a MIDDLE verdict (`partial`):
- `-ый` vs `-ий` (masculine nominative singular)
- `-ые` vs `-ие` (plural nominative)
- `-ого` vs `-его` (genitive)
- Any other hard/soft stem marker on adjective or noun endings
These cannot be heard, but the learner is being tested on producing
the correct form, so mark `partial` — not full failure, but not clean
either.

Test form FIRST, spelling SECOND. If the required form is correct but
the spelling has a typo, the form passed.
"""


def _handle_drill_chat(llm, data, lang):
    user_answer = (data.get("user_answer") or "").strip()
    drill = data.get("drill") or {}
    en = drill.get("en", "")
    rule_id = drill.get("rule_id", "")
    rule_name = drill.get("rule_name", "")
    facet = drill.get("facet", "default")
    cluster_name = drill.get("cluster_name", "")
    history = data.get("history") or []

    app_context = _build_app_context(data)

    lang_note = (
        "Output must be in Russian (Cyrillic) except the labels "
        "'Natural:', 'Correct', and the grammar category names, which stay "
        "in English."
        if lang == "ru"
        else "Output must be in English, except all Russian word forms "
             "and the final corrected sentence."
    )

    prompt = f"""You are grading a Russian translation drill.

APP CONTEXT:
{app_context}

DRILL:
English sentence: {en}
Learner's Russian translation: {user_answer}
Target grammar rule: {rule_name} (rule {rule_id}, facet {facet})
Grammar cluster: {cluster_name}

{TYPO_POLICY_BLOCK}

Analyze the translation carefully. Identify every grammatical error.

Return EXACTLY this format, no preamble, no closing, no markdown:

Line 1: "Natural: yes" or "Natural: mostly" or "Natural: no"

Line 2: If fully correct, write "Correct"
        Otherwise, write "<N> corrections" where N is the exact count.

Then, if there are errors, group them by grammar category. For each
category:

  <Category name>
    <wrong form> → <correct form>
    <one short sentence explaining the underlying rule>

Categories are things like: Aspect, Numeral agreement, Case governance,
Gender agreement, Verb tense, Preposition, Word order, Typo, etc.
Put each distinct correction on its own line. Keep each explanation
to one short sentence — no more. Indent the corrections and the
explanation by four spaces under the category name.

Final line: The full corrected Russian sentence, on its own line,
preceded by a blank line.

If the translation is fully correct, output ONLY:
Natural: yes
Correct
<the learner's translation, unchanged>

Do NOT write paragraphs. Do NOT add closing remarks. Do NOT use markdown
bullets or asterisks — just indentation.

{lang_note}
"""
    reply = llm.call(prompt, temperature=0.3, history=history)
    if not reply:
        reply = "Natural: ?\nGrading failed."

    try:
        new_count = _increment_drill_count()
        logger.info(f"[drill] count today = {new_count}")
    except Exception as e:
        logger.warning(f"Could not increment drill count: {e}")

    verdict = _get_structured_verdict(llm, en, user_answer, rule_id, rule_name, facet)
    if verdict:
        _update_state_from_verdict(verdict)

    return reply.strip()


def _get_structured_verdict(llm, en, user_answer, rule_id, rule_name, facet):
    prompt = f"""You are classifying a Russian translation drill.

English: {en}
Learner's translation: {user_answer}
Target rule: {rule_name} (rule {rule_id}, facet: {facet})

Classify ONLY the target rule. Errors on OTHER grammar do not affect this
verdict. If the target rule was used correctly — even if there are errors
elsewhere in the sentence — the verdict is "correct".

{TYPO_POLICY_BLOCK}

Classify as:
  "correct" — the target rule's grammatical form was used correctly
              (typos on the target form do NOT count against this)
  "partial" — the target rule was used but with a hard/soft stem
              spelling error, OR the target lexical item was replaced
              by a synonym (form avoided but meaning kept)
  "wrong"   — the target rule was used incorrectly or not at all

Return JSON only:
{{
  "rule_id": "{rule_id}",
  "facet": "{facet}",
  "verdict": "correct" | "partial" | "wrong",
  "explanation": "one short sentence"
}}
"""
    result = llm.call_json(prompt)
    if result and isinstance(result, dict) and result.get("verdict") in ("correct", "partial", "wrong"):
        return result
    return None


def _update_state_from_verdict(verdict):
    lex = _load_grammar_lexicon()
    rules = lex.get("rules", {})
    state = lex.get("state", {})

    rule_id = verdict.get("rule_id")
    facet = verdict.get("facet", "default")
    v = verdict.get("verdict")

    if not rule_id or rule_id not in rules:
        return

    rule_def = rules[rule_id]
    facets_available = rule_def.get("facets", ["default"])
    if facet not in facets_available:
        _log_facet_warning(rule_id, facet, "grading")
        facet = "default"

    rs = state.setdefault(rule_id, {
        "state": "unlearned",
        "times_tested": 0,
        "times_correct": 0,
        "last_tested": None,
        "last_failed": None,
        "last_failed_facet": None,
        "facets": {},
    })
    fs = rs.setdefault("facets", {}).setdefault(facet, {
        "times_tested": 0,
        "times_correct": 0,
        "consecutive_correct": 0,
    })

    now = _now_iso()

    fs["times_tested"] = int(fs.get("times_tested", 0)) + 1
    rs["times_tested"] = int(rs.get("times_tested", 0)) + 1
    rs["last_tested"] = now

    if v == "correct":
        fs["times_correct"] = int(fs.get("times_correct", 0)) + 1
        rs["times_correct"] = int(rs.get("times_correct", 0)) + 1
        fs["consecutive_correct"] = int(fs.get("consecutive_correct", 0)) + 1
    elif v == "partial":
        # Partial does not increment consecutive_correct, but it also
        # does not reset it. This lets a hard/soft stem slip not break
        # a streak that was otherwise going well.
        pass
    else:  # wrong
        fs["consecutive_correct"] = 0
        fs["last_failed"] = now
        rs["last_failed"] = now
        rs["last_failed_facet"] = facet

    current_state = rs.get("state", "unlearned")
    if current_state == "unlearned":
        rs["state"] = "learning"

    all_mastered = True
    for fname in facets_available:
        f = rs["facets"].get(fname, {})
        if int(f.get("consecutive_correct", 0)) < 3:
            all_mastered = False
            break

    if current_state == "learning" and all_mastered:
        rs["state"] = "mastered"
        logger.info(f"Rule {rule_id} → mastered")

    if v == "wrong" and current_state == "mastered":
        rs["state"] = "learning"
        logger.info(f"Rule {rule_id} regressed to learning")

    _save_grammar_lexicon()


def _handle_write_chat(llm, data, lang):
    user_answer = (data.get("user_answer") or "").strip()
    prompt_text = data.get("write_prompt", "")
    history = data.get("history") or []
    app_context = _build_app_context(data)

    lang_note = (
        "Output must be in Russian (Cyrillic) except the labels "
        "'Natural:', 'Correct', and the grammar category names, which stay "
        "in English."
        if lang == "ru"
        else "Output must be in English, except all Russian text."
    )

    prompt = f"""You are reviewing a Russian learner's free writing.

APP CONTEXT:
{app_context}

WRITING TASK:
Prompt given: {prompt_text}
Learner's Russian writing:
{user_answer}

{TYPO_POLICY_BLOCK}

Analyze the writing carefully. Identify every grammatical error.

Return EXACTLY this format, no preamble, no closing, no markdown:

Line 1: "Natural: yes" or "Natural: mostly" or "Natural: no"

Line 2: If clean, write "Correct"
        Otherwise, write "<N> corrections" where N is the exact count.

Then, if there are errors, group them by grammar category. For each
category:

  <Category name>
    <wrong phrase> → <correct phrase>
    <one short sentence explaining the underlying rule>

Categories are things like: Aspect, Case, Agreement, Word order,
Verb tense, Preposition, Typo, etc. Keep each explanation to one short
sentence. Indent the corrections and the explanation by four spaces
under the category name.

Final line: The full corrected passage, on its own line, preceded by
a blank line.

If the writing is fully correct, output ONLY:
Natural: yes
Correct
<the learner's passage, unchanged>

Do NOT write paragraphs. Do NOT add closing remarks. Do NOT use markdown
bullets or asterisks — just indentation.

{lang_note}
"""
    reply = llm.call(prompt, temperature=0.4, history=history)
    if not reply:
        return "Natural: ?\nReview failed."
    return reply.strip()


def _handle_translate_chat(llm, data, lang):
    selection = data.get("selection") or {}
    words = selection.get("words") or []
    sentence = selection.get("sentence", "")
    phrase = " ".join(words)
    history = data.get("history") or []

    if not phrase:
        return "⚠️ No words selected."

    lang_note = (
        "Output must be in Russian (Cyrillic)."
        if lang == "ru"
        else "Output must be in English, except the Russian translation."
    )

    prompt = f"""The learner is translating an English sentence into Russian.
They selected a word or phrase from the sentence and want it translated
in context.

Full English sentence: "{sentence}"
Selected: "{phrase}"

Give the Russian translation of the selected word or phrase AS USED IN
THIS SPECIFIC SENTENCE. Not a literal dictionary translation — the
context-appropriate one.

Format (keep it short):
Line 1: {phrase} → <russian translation>
Line 2-3 (optional): 1-2 lines explaining the form, case, or why this fits.

Under 4 lines total. No preamble.

{lang_note}
"""
    reply = llm.call(prompt, temperature=0.4, history=history)
    return reply or "⚠️ Translation failed."


def _handle_free_chat(llm, data, lang):
    message = (data.get("message") or "").strip()
    current_drill = data.get("current_drill") or {}
    write_prompt = data.get("write_prompt")
    history = data.get("history") or []
    app_context = _build_app_context(data)

    if message == ".":
        en = current_drill.get("en", "")
        if not en:
            return "No active drill to explain."
        prompt = f"""The learner sent "." — they want the current Russian
sentence explained. But first, note: they haven't submitted a translation
yet, so you have the ENGLISH source only.

APP CONTEXT:
{app_context}

ENGLISH SENTENCE THEY ARE TRANSLATING:
{en}

Give a compact word-by-word breakdown of what the Russian would look
like: cover the key structural choices (which case, which aspect, which
verb form) without giving a full translated sentence. Present it as
short lines, one per meaningful chunk. 5-8 lines maximum.

{_lang_directive(lang)}
"""
        reply = llm.call(prompt, temperature=0.4, history=history)
        return reply or "⚠️ Explain failed."

    if message == "?":
        if not current_drill:
            return "No active drill."
        rule_name = current_drill.get("rule_name", "")
        rule_id = current_drill.get("rule_id", "")
        facet = current_drill.get("facet", "")
        cluster_name = current_drill.get("cluster_name", "")
        reason = current_drill.get("facet_reason", "")
        prompt = f"""The learner sent "?" — they want to know what this
drill is testing, in 1-3 short lines.

Drill target:
  Rule: {rule_name} ({rule_id})
  Facet: {facet}
  Cluster: {cluster_name}
  Why this was picked: {reason}

Reply in 1-3 short lines. Do not lecture. Name the rule, the specific
sub-skill, and why this drill was chosen. No explanation of what the
rule is unless asked.

{_lang_directive(lang)}
"""
        reply = llm.call(prompt, temperature=0.3, history=history)
        return reply or "⚠️ Explain failed."

    words_only = re.findall(r"\b\w+\b", message)
    is_short_lookup = (
        1 <= len(words_only) <= 3
        and not _contains_cyrillic(message)
        and not any(p in message.lower() for p in [
            "how", "why", "what", "when", "where", "explain", "translate",
            "difference", "mean", "mean?", "?"
        ])
    )

    if is_short_lookup:
        phrase = message
        prompt = f"""The learner typed a short English word or phrase: «{phrase}»

They want the Russian translation, plus brief grammar notes if useful.

Give:
Line 1: {phrase} → <Russian translation>
Line 2: part of speech + key grammatical info (gender, case it governs,
        declension notes) if relevant
Line 3 (optional): one short note only if it clarifies usage.

Keep it under 4 lines. No prose. Do NOT write a full example sentence.

{_lang_directive(lang)}
"""
        reply = llm.call(prompt, temperature=0.4, history=history)
        return reply or "⚠️ Lookup failed."

    context_parts = []
    if current_drill:
        context_parts.append(
            f"Current drill — English: {current_drill.get('en', '')} "
            f"| Target rule: {current_drill.get('rule_name', '')} "
            f"({current_drill.get('rule_id', '')}, facet {current_drill.get('facet', '')})"
        )
    if write_prompt:
        context_parts.append(f"Current write prompt: {write_prompt}")

    drill_context = "\n".join(context_parts) if context_parts else "(no active drill)"

    prompt = f"""You are a Russian language tutor embedded in a drilling app.
The learner writes in English; you may answer in either language according
to the directive below.

APP CONTEXT:
{app_context}

CURRENT SESSION:
{drill_context}

LEARNER MESSAGE:
{message}

CRITICAL: Directly ANSWER what the learner asked. Do not greet them. Do
not ask what they want to work on. Do not stall. If they sent a word or
phrase, translate or explain it. If they asked a question, answer it.

Reply briefly — 1-2 sentences is usually enough. Only give a longer
answer if the user explicitly asks for detail, explanation, or a
deep dive. Do not lecture. Do not pad.

Use Cyrillic when writing Russian words or examples.

{_lang_directive(lang)}
"""
    reply = llm.call(prompt, temperature=0.6, history=history)
    return reply or "⚠️ Chat failed."


# ==================== IN CHAT ====================

@app.route("/api/in-chat", methods=["POST"])
def in_chat():
    try:
        data = request.get_json(force=True, silent=True) or {}
        message = (data.get("message") or "").strip()
        card = data.get("card_context") or {}
        lang = data.get("lang", "en")

        if not message:
            return jsonify({"success": False, "reply": "Empty message"}), 400

        llm = get_chat_llm()
        if not llm.api_key:
            return jsonify({
                "success": False,
                "reply": "⚠️ Chat LLM not configured.",
            })

        ctx_lines = []
        if card.get("word"):
            ctx_lines.append(f"Word: {card['word']}")
        if card.get("pos"):
            ctx_lines.append(f"Part of speech: {card['pos']}")
        if card.get("english"):
            ctx_lines.append(f"English: {card['english']}")
        if card.get("decision"):
            ctx_lines.append(f"Card category: {card['decision']}")
        srs = card.get("srs_data") or {}
        if srs:
            ctx_lines.append(
                f"SRS: state={srs.get('state', '?')} "
                f"interval={srs.get('interval_days', '?')}d "
                f"reps={srs.get('review_count', '?')}"
            )
        sent = card.get("current_sentence") or {}
        if sent.get("russian"):
            ctx_lines.append(f"Russian sentence: {sent['russian']}")
        if sent.get("english"):
            ctx_lines.append(f"English sentence: {sent['english']}")

        context_block = "\n".join(ctx_lines) if ctx_lines else "(no card context)"
        lang_note = _lang_directive(lang)

        if message == "e":
            if not card.get("word"):
                return jsonify({"success": True, "reply": "No active card."})
            prompt = f"""The learner sent "e" — they want the current WORD
explained. Cover: meaning, part of speech, case/government, declension
or conjugation notes, and how it appears in the current sentence.

CARD CONTEXT:
{context_block}

Short lines, no prose. 3-5 lines maximum.

{lang_note}
"""
            reply = llm.call(prompt, temperature=0.4)
            return jsonify({"success": True, "reply": reply or "⚠️ Explain failed."})

        if message == ".":
            sent = card.get("current_sentence") or {}
            if not sent.get("russian"):
                return jsonify({"success": True, "reply": "No sentence on this card."})
            prompt = f"""The learner sent "." — they want the current SENTENCE
explained, word by word.

CARD CONTEXT:
{context_block}

Give a compact word-by-word breakdown. Short lines, one per meaningful
chunk. Cover case, aspect, agreement, word role. 5-8 lines maximum.

{lang_note}
"""
            reply = llm.call(prompt, temperature=0.4)
            return jsonify({"success": True, "reply": reply or "⚠️ Explain failed."})

        if message == "?":
            prompt = f"""The learner sent "?" — they want BOTH the current
word and the current sentence explained together.

CARD CONTEXT:
{context_block}

Start with the word (meaning + grammar), then the sentence (word-by-word
structure). Short lines. 6-10 lines maximum.

{lang_note}
"""
            reply = llm.call(prompt, temperature=0.4)
            return jsonify({"success": True, "reply": reply or "⚠️ Explain failed."})

        prompt = f"""You are a Russian language tutor embedded in a study app.
The learner is looking at a card and has a question about it.

CARD CONTEXT:
{context_block}

LEARNER MESSAGE:
{message}

Reply briefly — 1-2 sentences is usually enough. Expand only if the
learner asks for detail or explanation. Use Cyrillic when writing Russian.
{lang_note}
"""
        reply = llm.call(prompt, temperature=0.6)
        return jsonify({"success": True, "reply": reply or "⚠️ Chat failed."})

    except Exception as e:
        logger.exception("Error in /api/in-chat")
        return jsonify({"success": False, "reply": f"⚠️ Server error: {e}"}), 500


# ==================== HEALTH ====================

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})


# ==================== TODAY ====================

@app.route("/api/today", methods=["GET"])
def get_today():
    try:
        if not _has_run_today():
            return jsonify({
                "success": True,
                "needs_generation": True,
                "date": datetime.now().isoformat(),
                "new_cards": [],
                "review_cards": [],
                "total": 0,
            })

        fm, srs, _ = get_engines()
        working = fm.load_working_data()
        words = working["decisions"]
        today = datetime.now().date().isoformat()

        introduced_today = [
            w for w in words
            if w.get("decision") == "new"
            and w.get("srs_data", {}).get("introduced_date") == today
            and not _completed_today(w, today)
        ]
        introduced_today.sort(key=lambda w: w.get("rank", 0))

        introduced_today_count = sum(
            1 for w in words
            if w.get("decision") == "new"
            and w.get("srs_data", {}).get("introduced_date") == today
        )

        if introduced_today:
            new_cards = introduced_today
        elif introduced_today_count >= srs.new_cards_per_day:
            new_cards = []
        else:
            needed = srs.new_cards_per_day - introduced_today_count
            fresh = [
                w for w in words
                if w.get("decision") == "new"
                and w.get("srs_data", {}).get("last_reviewed") is None
                and w.get("srs_data", {}).get("introduced_date") is None
            ]
            fresh.sort(key=lambda w: w.get("rank", 0))
            new_cards = fresh[:needed]

            for w in new_cards:
                w.setdefault("srs_data", {})["introduced_date"] = today

            if new_cards:
                fm.save_working_data(working)
                logger.info(f"Introduced {len(new_cards)} new cards for {today}")

        review_cards = srs.get_due_reviews(words)
        new_ranks = {w.get("rank") for w in new_cards}
        review_cards = [
            w for w in review_cards if w.get("rank") not in new_ranks
        ]

        for card in new_cards + review_cards:
            sentences = card.get("sentences", [])
            card["current_sentence"] = sentences[-1] if sentences else None

        return jsonify({
            "success": True,
            "date": datetime.now().isoformat(),
            "new_cards": new_cards,
            "review_cards": review_cards,
            "total": len(new_cards) + len(review_cards),
        })
    except Exception as e:
        logger.exception("Error in /api/today")
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== REVIEW ====================

@app.route("/api/review", methods=["POST"])
def submit_review():
    try:
        data = request.get_json(force=True, silent=True) or {}
        rank = data.get("rank")
        word_text = data.get("word")
        rating = data.get("rating", "").lower()

        if rank is None or not word_text:
            return jsonify({"success": False, "error": "Missing 'rank' or 'word'"}), 400
        if rating not in ("again", "hard", "good", "easy"):
            return jsonify({"success": False, "error": f"Invalid rating: {rating}"}), 400

        fm, srs, urgency = get_engines()
        working = fm.load_working_data()
        words = working["decisions"]
        exposure_data = fm.load_exposure_data()
        pause = fm.load_pause_data()

        card = next((w for w in words if w.get("rank") == rank), None)
        if card is None:
            return jsonify({"success": False, "error": f"Card not found: rank={rank}"}), 404

        import copy
        undo_entry = {
            "rank": rank,
            "word": card.get("word"),
            "rating": rating,
            "timestamp": datetime.now().isoformat(),
            "previous_srs_data": copy.deepcopy(card.get("srs_data", {})),
            "previous_decision": card.get("decision"),
            "previous_urgency_data": copy.deepcopy(card.get("urgency_data", {})),
            "previous_last_review_date": pause.get("last_review_date"),
        }
        undo_stack = pause.get("undo_stack", [])
        undo_stack.append(undo_entry)
        undo_stack = undo_stack[-50:]
        pause["undo_stack"] = undo_stack

        srs.rate_card(card, rating)
        urgency.record_review_exposure(card, exposure_data)

        srs_data = card.get("srs_data", {})
        review_count = srs_data.get("review_count", 0)
        interval = srs_data.get("interval_days", 0)

        if card.get("decision") == "new" and review_count >= 5 and interval >= 3:
            card["decision"] = "practice"
            logger.info(f"Card promoted to practice: {word_text}")
        elif card.get("decision") == "practice" and review_count >= 10 and interval >= 30:
            card["decision"] = "mastered"
            logger.info(f"Card promoted to mastered: {word_text}")

        pause["last_review_date"] = datetime.now().isoformat()

        fm.save_working_data(working)
        fm.save_exposure_data(exposure_data)
        fm.save_pause_data(pause)

        new_remaining = srs.count_new_remaining(words)
        due_remaining = srs.count_due_now(words, include_learning=False)

        return jsonify({
            "success": True,
            "word": word_text,
            "rating": rating,
            "new_decision": card.get("decision"),
            "srs_data": card.get("srs_data"),
            "remaining": {"new": new_remaining, "due": due_remaining},
        })
    except Exception as e:
        logger.exception("Error in /api/review")
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== STATS ====================

@app.route("/api/stats", methods=["GET"])
def get_stats():
    try:
        fm, srs, _ = get_engines()
        working = fm.load_working_data()
        words = working["decisions"]

        counts = {"new": 0, "practice": 0, "mastered": 0}
        for w in words:
            d = w.get("decision", "unknown")
            if d in counts:
                counts[d] += 1

        learning = sum(
            1 for w in words
            if w.get("srs_data", {}).get("state") == "learning"
            and w["srs_data"].get("last_reviewed")
        )
        review = sum(
            1 for w in words
            if w.get("srs_data", {}).get("state") == "review"
        )

        due_now = srs.count_due_now(words, include_learning=False)
        new_remaining = srs.count_new_remaining(words)

        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        reviews_today = 0
        for w in words:
            lr = w.get("srs_data", {}).get("last_reviewed")
            if lr:
                try:
                    if datetime.fromisoformat(lr) >= today_start:
                        reviews_today += 1
                except (ValueError, TypeError):
                    pass

        return jsonify({
            "success": True,
            "total_words": len(words),
            "new_words": counts["new"],
            "practice_words": counts["practice"],
            "mastered_words": counts["mastered"],
            "new_remaining": new_remaining,
            "due_now": due_now,
            "learning": learning,
            "in_review": review,
            "reviews_today": reviews_today,
        })
    except Exception as e:
        logger.exception("Error in /api/stats")
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== UNDO ====================

@app.route("/api/undo", methods=["POST"])
def undo_review():
    try:
        fm, srs, urgency = get_engines()
        working = fm.load_working_data()
        words = working["decisions"]
        exposure_data = fm.load_exposure_data()
        pause = fm.load_pause_data()

        undo_stack = pause.get("undo_stack", [])
        if not undo_stack:
            return jsonify({"success": False, "error": "Nothing to undo"}), 400

        entry = undo_stack.pop()
        rank = entry.get("rank")
        word_text = entry.get("word")

        card = next((w for w in words if w.get("rank") == rank), None)
        if card is None:
            return jsonify({"success": False, "error": f"Card not found: rank={rank}"}), 404

        card["srs_data"] = entry.get("previous_srs_data", {})
        if entry.get("previous_decision") is not None:
            card["decision"] = entry["previous_decision"]
        if "previous_urgency_data" in entry:
            card["urgency_data"] = entry["previous_urgency_data"]
        if entry.get("previous_last_review_date"):
            pause["last_review_date"] = entry["previous_last_review_date"]

        pause["undo_stack"] = undo_stack

        fm.save_working_data(working)
        fm.save_exposure_data(exposure_data)
        fm.save_pause_data(pause)

        new_remaining = srs.count_new_remaining(words)
        due_remaining = srs.count_due_now(words, include_learning=False)

        return jsonify({
            "success": True,
            "rank": rank,
            "word": word_text,
            "undone_rating": entry.get("rating"),
            "remaining": {"new": new_remaining, "due": due_remaining},
            "undo_remaining": len(undo_stack),
        })
    except Exception as e:
        logger.exception("Error in /api/undo")
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== RESET ====================

@app.route("/api/reset_today", methods=["POST"])
def reset_today():
    try:
        fm, _, _ = get_engines()
        working = fm.load_working_data()
        words = working["decisions"]

        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        reverted = 0
        for w in words:
            srs_data = w.get("srs_data", {})
            lr = srs_data.get("last_reviewed")
            if not lr:
                continue
            try:
                if datetime.fromisoformat(lr) >= today_start:
                    srs_data["last_reviewed"] = None
                    srs_data["due_date"] = None
                    reverted += 1
            except (ValueError, TypeError):
                pass

        fm.save_working_data(working)
        return jsonify({"success": True, "reverted_cards": reverted})
    except Exception as e:
        logger.exception("Error in /api/reset_today")
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== ENTRY POINT ====================

def main():
    config = get_config()
    api_settings = config.get("api_settings", {})

    port = 5000
    host = "127.0.0.1"

    fm, _, _ = get_engines()
    fm.ensure_all_files()

    print()
    print("=" * 60)
    print("  AInki — API Server")
    print("=" * 60)
    print(f"  Project root:  {PROJECT_ROOT}")
    print(f"  Data dir:      {fm.data_dir}")
    print(f"  Web dir:       {WEB_DIR}")
    print(f"  Daily model:   {api_settings.get('model', 'unknown')}")
    print(f"  Drill model:   {config.get('drill_settings', {}).get('model', '?')}")
    print(f"  Chat model:    {config.get('chat_settings', {}).get('model', '?')}")
    print()
    print(f"  🌐 Open:       http://{host}:{port}")
    print()
    print("  Press Ctrl+C to stop")
    print("=" * 60)
    print()

    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Server stopped")
