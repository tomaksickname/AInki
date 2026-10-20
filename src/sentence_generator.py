#!/usr/bin/env python3
"""
AInki — Sentence Generator
==========================

Calls DeepSeek API to generate C1-level Russian sentences.

Key design principle:
    NEVER force practice words. Natural Russian > practice word coverage.

    A sentence using 1 practice word naturally is BETTER than one forcing 3.

Construction layer:
    When a `construction` is supplied, it becomes mandatory: the sentence must
    use it verbatim (or, for metavariable patterns like
    "(а) при чём здесь/тут Cop NP-Nom?", realize it concretely and report the
    realization). The model may signal a soft failure via
    {"fit_failure": true, "reason": "..."} — this short-circuits the retry
    loop and is returned to the caller as a parsed dict.

Responsibilities:
    - Load API key from .env
    - Build the prompt with "use if fits naturally" semantics
    - Call DeepSeek /chat/completions
    - Parse JSON response (with fallbacks)
    - Validate the result (length, quality, construction use)
    - Retry on transient failures
    - Rate limit between calls
"""

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


logger = logging.getLogger(__name__)


class SentenceGenerator:
    """Generates natural Russian sentences via DeepSeek."""

    def __init__(self, config: Dict[str, Any]):
        api = config.get("api_settings", {})

        self.base_url = api.get("base_url", "https://api.deepseek.com/v1").rstrip("/")
        self.model = api.get("model", "deepseek-chat")
        self.temperature = api.get("temperature", 0.7)
        self.max_tokens = api.get("max_tokens", 400)
        self.timeout = api.get("timeout", 60)
        self.rate_limit_seconds = api.get("rate_limit_seconds", 0.5)
        self.max_retries = api.get("max_retries", 3)

        key_env = api.get("api_key_env", "DEEPSEEK_API_KEY")
        self.api_key = self._load_api_key(key_env)

        self._last_call_time = 0.0

        logger.info(f"SentenceGenerator ready: model={self.model}, temp={self.temperature}")

    # ==================== API KEY ====================

    def _load_api_key(self, env_var_name: str) -> str:
        key = os.environ.get(env_var_name)
        if not key:
            env_file = Path(__file__).resolve().parent.parent / ".env"
            if env_file.exists():
                key = self._read_env_file(env_file, env_var_name)
        if not key:
            raise ValueError(
                f"API key not found. Set {env_var_name} in environment or .env file."
            )
        return key

    @staticmethod
    def _read_env_file(env_file: Path, var_name: str) -> Optional[str]:
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    if key.strip() == var_name:
                        return value.strip().strip('"').strip("'")
        except Exception as e:
            logger.warning(f"Failed to read .env: {e}")
        return None

    # ==================== PUBLIC API ====================

    def generate_sentence(
        self,
        target_word: str,
        translation: str,
        practice_words: List[str],
        cefr_level: str = "C1",
        is_review: bool = False,
        construction: Optional[str] = None,
        construction_gloss: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Generate one natural Russian sentence.

        Args:
            target_word:        Word to include.
            translation:        English meaning of the target word.
            practice_words:     Context words to include if they fit.
            cefr_level:         A1-C2 difficulty.
            is_review:          If True, the word has been seen before —
                                prompt the AI to inflect it and avoid the
                                dictionary form.
            construction:       Optional construction string. When set, the
                                sentence MUST use it. Example: "в течение".
            construction_gloss: Optional short gloss for the construction.
                                If None, no GLOSS line is emitted.

        Returns:
            On success, a dict:
                {
                  "russian": str,
                  "english": str,
                  "practice_words_used": [str, ...],
                  "construction_used": str | None,
                  "construction_instance": str | None,
                }
            On a soft "the model can't fit this construction" signal:
                {"fit_failure": True, "reason": str}
            On hard failure (all retries exhausted, unparseable, invalid):
                None
        """
        prompt = self._build_prompt(
            target_word, translation, practice_words, cefr_level,
            is_review=is_review,
            construction=construction,
            construction_gloss=construction_gloss,
        )

        for attempt in range(1, self.max_retries + 1):
            response_text = self._call_api(prompt, attempt)
            if not response_text:
                continue

            parsed = self._parse_response(response_text, practice_words)
            if parsed is None:
                logger.warning(f"Attempt {attempt}: response rejected, retrying...")
                time.sleep(1.0)
                continue

            # Soft fit-failure: the model says it cannot use this construction
            # naturally. Do NOT burn retries on this — return immediately and
            # let the caller decide on a fallback.
            if parsed.get("fit_failure"):
                logger.info(
                    f"Model signalled fit_failure for construction "
                    f"'{construction}': {parsed.get('reason', '')}"
                )
                return parsed

            if self._validate(parsed, target_word, construction=construction):
                return parsed

            logger.warning(f"Attempt {attempt}: response rejected, retrying...")
            time.sleep(1.0)

        logger.error(
            f"Failed to generate sentence for '{target_word}' "
            f"after {self.max_retries} attempts"
        )
        return None

    # ==================== PROMPT ====================

    def _build_prompt(
        self,
        target_word: str,
        translation: str,
        practice_words: List[str],
        cefr_level: str,
        is_review: bool = False,
        construction: Optional[str] = None,
        construction_gloss: Optional[str] = None,
    ) -> str:
        """
        Build the prompt.

        Rule order: construction first, then target word, then practice words.
        Naturalness always wins; the model is explicitly allowed to omit
        practice words that don't fit.

        When `construction` is provided, the model may signal a soft failure
        by returning {"fit_failure": true, "reason": "..."}.
        """
        practice_str = ", ".join(practice_words)

        # ---------- Construction block ----------
        if construction:
            gloss_line = (
                f"GLOSS: {construction_gloss}\n" if construction_gloss else ""
            )
            construction_block = f"""CONSTRUCTION (mandatory):
  "{construction}"
{gloss_line}You MUST use this construction in the sentence. Most constructions
are fixed multi-word frames ("в течение", "вместо того чтобы"). Some are
patterns with metavariables, e.g. "(а) при чём здесь/тут Cop NP-Nom?" — if
the construction looks like a pattern, DO NOT insert metavariable text
literally. Instead, realize the pattern with concrete Russian words that
fit the sentence, and report the concrete realization you used.

If you genuinely cannot use this construction naturally with the target
word, DO NOT force it. Return exactly:
  {{"fit_failure": true, "reason": "<short reason>"}}

"""
        else:
            construction_block = ""

        # ---------- Inflection + tone ----------
        if is_review:
            inflection_rule = (
                f'7. INFLECTION REQUIRED: The word "{target_word}" has been seen before. '
                f'Use it in a NATURAL INFLECTED form (any case, number, gender, tense, '
                f'or aspect that fits the sentence) — NOT the dictionary form. '
                f'Prefer the most common everyday usage. '
                f'For example: "перед президиумом" (instrumental), "членов президиума" (genitive), '
                f'"президиуму пришлось" (dative). Do NOT default to nominative.'
            )
            tone_rule = (
                "Vary the context from previous exposures: "
                "try a different situation, tone, or register than a plain statement."
            )
        else:
            inflection_rule = (
                f'7. The word "{target_word}" is being introduced for the first time. '
                f'You may use the dictionary form (nominative for nouns, infinitive for verbs), '
                f'or a natural inflected form — whichever sounds most natural in context.'
            )
            tone_rule = "Focus on clear, everyday usage."

        # ---------- Optional construction JSON fields ----------
        if construction:
            construction_json_fields = (
                '  "construction_used": "The construction as you used it (the exact '
                '"word" value you were given).",\n'
                '  "construction_instance": "The exact contiguous substring of `russian` '
                'that realizes the construction. For pattern constructions, this is the '
                'concrete realization — e.g. \'при чём здесь\' for the pattern '
                '\'(а) при чём здесь/тут Cop NP-Nom?\'.",\n'
            )
            construction_used_hint = (
                "\nCRITICAL for construction_used / construction_instance:\n"
                "- construction_used MUST be the exact construction string you were given.\n"
                "- construction_instance MUST be an exact contiguous substring of `russian`.\n"
                "- For pattern constructions, `construction_instance` is the concrete\n"
                "  realization, not the pattern text.\n"
            )
        else:
            construction_json_fields = ""
            construction_used_hint = ""

        prompt = f"""Write ONE natural {cefr_level}-level Russian sentence that uses the word "{target_word}" (meaning: {translation}).

{construction_block}You have a list of optional context words to include IF they fit naturally:
{practice_str}

RULES (in priority order):

1. NATURALNESS IS THE #1 PRIORITY.
   The sentence MUST sound like something a native Russian speaker would actually say.

2. USE ONLY PRACTICE WORDS THAT FIT.
   If a practice word does not fit the sentence naturally, OMIT IT.
   It is PERFECTLY FINE to use 0, 1, 2, or 3 of the practice words.
   Do NOT force awkward combinations.

3. The target word "{target_word}" MUST be in the sentence.

4. Length: 8-15 words.

5. Do NOT invent bizarre imagery. Stick to ordinary, realistic situations.

6. {tone_rule}

{inflection_rule}

BAD example (forced, nonsensical):
"Медлительный президиум пронизал зал, параллельно обсуждая речь."

GOOD example (natural, only uses fitting words):
"Президиум долго обсуждал повестку дня, и заседание затянулось."

Return EXACTLY this JSON, no markdown, no extra text:
{{
  "russian": "The Russian sentence.",
  "english": "English translation.",
  "practice_words_used": ["dictionary forms", "of the practice words you used"],
{construction_json_fields}}}

CRITICAL for practice_words_used:
- Report each practice word in its DICTIONARY FORM (lemma), NOT the inflected form.
- Example: sentence has "на заседании" → report "заседание".
- If you didn't use a practice word, don't include it.
{construction_used_hint}
Write the sentence now:"""

        return prompt

    # ==================== API CALL ====================

    def _call_api(self, prompt: str, attempt: int) -> Optional[str]:
        elapsed = time.time() - self._last_call_time
        if elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)
        self._last_call_time = time.time()

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }

        try:
            response = requests.post(
                url, headers=headers, json=payload, timeout=self.timeout
            )

            if response.status_code == 429:
                wait = 2 ** attempt
                logger.warning(f"Rate limited (429), waiting {wait}s")
                time.sleep(wait)
                return None

            if response.status_code >= 500:
                wait = 2 ** attempt
                logger.warning(f"Server error {response.status_code}, waiting {wait}s")
                time.sleep(wait)
                return None

            if response.status_code != 200:
                logger.error(
                    f"API error {response.status_code}: {response.text[:200]}"
                )
                return None

            data = response.json()
            return data["choices"][0]["message"]["content"]

        except requests.exceptions.Timeout:
            logger.warning(f"Attempt {attempt}: request timed out")
            return None
        except requests.exceptions.RequestException as e:
            logger.warning(f"Attempt {attempt}: network error: {e}")
            return None
        except (KeyError, IndexError, ValueError) as e:
            logger.error(f"Unexpected API response structure: {e}")
            return None

    # ==================== PARSING ====================

    def _parse_response(
        self,
        content: str,
        practice_words: List[str],
    ) -> Optional[Dict[str, Any]]:
        if not content:
            return None

        text = content.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        # Direct parse
        try:
            parsed = json.loads(text)
            return self._normalize(parsed, practice_words)
        except json.JSONDecodeError:
            pass

        # Regex extraction
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
                return self._normalize(parsed, practice_words)
            except json.JSONDecodeError:
                pass

        logger.warning(f"Could not parse response: {content[:150]}...")
        return None

    @staticmethod
    def _normalize(
        parsed: Any,
        offered_practice_words: List[str],
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(parsed, dict):
            return None

        # Soft fit-failure signal — pass through unchanged so generate_sentence
        # can short-circuit the retry loop.
        if parsed.get("fit_failure"):
            return {
                "fit_failure": True,
                "reason": str(parsed.get("reason", "")).strip() or "no reason given",
            }

        russian = (
            parsed.get("russian")
            or parsed.get("sentence")
            or parsed.get("text")
        )
        english = parsed.get("english") or parsed.get("translation") or ""

        if not russian or not isinstance(russian, str):
            return None

        used = parsed.get("practice_words_used") or parsed.get("used") or []
        if not isinstance(used, list):
            used = []

        offered_set = set(offered_practice_words)
        used_clean = [
            w for w in used
            if isinstance(w, str) and w in offered_set
        ]

        construction_used = parsed.get("construction_used")
        construction_instance = parsed.get("construction_instance")
        if construction_used is not None and not isinstance(construction_used, str):
            construction_used = None
        if construction_instance is not None and not isinstance(construction_instance, str):
            construction_instance = None

        return {
            "russian": russian.strip(),
            "english": (english or "").strip(),
            "practice_words_used": used_clean,
            "construction_used": (
                construction_used.strip()
                if isinstance(construction_used, str)
                else None
            ),
            "construction_instance": (
                construction_instance.strip()
                if isinstance(construction_instance, str)
                else None
            ),
        }

    # ==================== VALIDATION ====================

    @staticmethod
    def _validate(
        parsed: Dict[str, Any],
        target_word: str = "",
        construction: Optional[str] = None,
    ) -> bool:
        """
        Reject obviously bad output.

        Base checks:
            - Russian sentence present
            - Contains Cyrillic
            - 6-25 words
            - Target word present (case-insensitive substring, when provided)

        Construction checks (only when `construction` is provided):
            - construction_used must equal the requested construction string
              (case-sensitive — the model is told to echo the exact string)
            - construction_instance must be a non-empty substring of russian
              (case-insensitive — sentence-initial constructions get capitalized)

        LOOSE instance validation is deliberate: some constructions are
        metavariable patterns (e.g. "(а) при чём здесь/тут Cop NP-Nom?"), and
        the model is expected to report the concrete realization rather than
        the pattern text.
        """
        russian = parsed.get("russian", "")
        if not russian:
            return False

        # Must contain Cyrillic
        if not re.search(r"[а-яА-ЯёЁ]", russian):
            return False

        word_count = len(russian.split())
        if word_count < 6:
            logger.warning(f"Rejected (too short, {word_count} words): {russian}")
            return False
        if word_count > 25:
            logger.warning(f"Rejected (too long, {word_count} words): {russian}")
            return False

        # Case-insensitive: sentence-initial words get capitalized.
        if target_word and target_word.lower() not in russian.lower():
            logger.warning(
                f"Rejected (target '{target_word}' not in sentence): {russian}"
            )
            return False

        if construction:
            used = (parsed.get("construction_used") or "").strip()
            instance = (parsed.get("construction_instance") or "").strip()

            # Case-sensitive on purpose: the model is instructed to echo the
            # exact construction string it was given. A case change here means
            # the model is paraphrasing, which should trigger the fallback
            # chain rather than being silently accepted.
            if used != construction:
                logger.warning(
                    f"Rejected (construction_used mismatch: "
                    f"{used!r} != {construction!r})"
                )
                return False
            if not instance:
                logger.warning("Rejected (construction_instance missing)")
                return False
            # Case-insensitive: instance may be capitalized at sentence start.
            if instance.lower() not in russian.lower():
                logger.warning(
                    f"Rejected (construction_instance {instance!r} "
                    f"not a substring of sentence)"
                )
                return False

        return True


# ==================== STANDALONE TEST ====================

if __name__ == "__main__":
    import sys
    import logging as _logging

    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    sys.path.insert(0, ".")
    from file_manager import FileManager

    print("Testing SentenceGenerator (v3, with construction layer)...")
    print()

    fm = FileManager()
    config = fm.get_config()
    generator = SentenceGenerator(config)

    # Test 1: Natural fit expected
    print("=== Test 1: Words that should fit ===")
    result = generator.generate_sentence(
        target_word="президиум",
        translation="presidium",
        practice_words=["заседание", "обсуждать", "повестка"],
        cefr_level="C1",
    )
    if result and not result.get("fit_failure"):
        print(f"  Russian:  {result['russian']}")
        print(f"  English:  {result['english']}")
        print(f"  Used:     {result['practice_words_used']}")
    print()

    # Test 2: With a fixed construction
    print("=== Test 2: With construction 'в течение' ===")
    result = generator.generate_sentence(
        target_word="президиум",
        translation="presidium",
        practice_words=["заседание", "обсуждать", "повестка"],
        cefr_level="C1",
        construction="в течение",
        construction_gloss="during / over the course of",
    )
    if result and result.get("fit_failure"):
        print(f"  FIT FAILURE: {result['reason']}")
    elif result:
        print(f"  Russian:  {result['russian']}")
        print(f"  English:  {result['english']}")
        print(f"  Used:     {result['practice_words_used']}")
        print(f"  Constr:   {result['construction_used']}")
        print(f"  Instance: {result['construction_instance']}")
    print()

    # Test 3: Words that DON'T fit — AI should skip them
    print("=== Test 3: Words that don't fit (AI should drop most) ===")
    result = generator.generate_sentence(
        target_word="президиум",
        translation="presidium",
        practice_words=["пронизать", "медлительный", "параллельно"],
        cefr_level="C1",
    )
    if result and not result.get("fit_failure"):
        print(f"  Russian:  {result['russian']}")
        print(f"  English:  {result['english']}")
        print(f"  Used:     {result['practice_words_used']}")
        print(f"  (offered 3, used {len(result['practice_words_used'])})")
    print()

    print("✅ Test complete")
