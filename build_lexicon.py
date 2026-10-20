#!/usr/bin/env python3
"""
Build grammar_lexicon.json with lexical facets integrated.
Run once. Writes data/grammar_lexicon.json.
"""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT = PROJECT_ROOT / "data" / "grammar_lexicon.json"

# ─── Cluster definitions ───
CLUSTERS = {
    "1":  { "name": "Core Sentence",              "rules": ["R001","R002","R003","R004","R005"] },
    "2":  { "name": "Gender & Number",            "rules": ["R006","R007","R008","R009","R010","R011"] },
    "3":  { "name": "Genitive Case",              "rules": ["R012","R013","R014","R015","R016","R017","R018"] },
    "4":  { "name": "Dative Case",                "rules": ["R019","R020","R021","R022","R023","R024"] },
    "5":  { "name": "Instrumental Case",          "rules": ["R025","R026","R027","R028","R029"] },
    "6":  { "name": "Prepositional Case",         "rules": ["R030","R031","R032","R033","R034"] },
    "7":  { "name": "Full Case Paradigm",         "rules": ["R035","R036","R037","R038","R039","R040"] },
    "8":  { "name": "Adjective Systems",          "rules": ["R041","R042","R043","R044","R045"] },
    "9":  { "name": "Comparative & Superlative",  "rules": ["R046","R047","R048","R049"] },
    "10": { "name": "Verb Aspect",                "rules": ["R050","R051","R052","R053","R054","R055","R056"] },
    "11": { "name": "Verb Tense & Mood",          "rules": ["R057","R058","R059","R060","R061","R062"] },
    "12": { "name": "Reflexive Verbs",            "rules": ["R063","R064","R065","R066"] },
    "13": { "name": "Verbs of Motion",            "rules": ["R067","R068","R069","R070","R071","R072"] },
    "14": { "name": "Verb Government",            "rules": ["R073","R074","R075","R076","R077"] },
    "15": { "name": "Verb Prefixes",              "rules": ["R078","R079","R080"] },
    "16": { "name": "Participles",                "rules": ["R081","R082","R083","R084","R085"] },
    "17": { "name": "Gerunds",                    "rules": ["R086","R087","R088"] },
    "18": { "name": "Personal & Possessive Pronouns", "rules": ["R089","R090","R091","R092","R093"] },
    "19": { "name": "Other Pronouns",             "rules": ["R094","R095","R096","R097","R098"] },
    "20": { "name": "Numerals",                   "rules": ["R099","R100","R101","R102","R103","R104","R105","R106"] },
    "21": { "name": "Adverbs",                    "rules": ["R107","R108","R109","R110"] },
    "22": { "name": "Prepositions",               "rules": ["R111","R112","R113","R114","R115"] },
    "23": { "name": "Clause Structure",           "rules": ["R116","R117","R118","R119","R120","R121"] },
    "24": { "name": "Reported Speech",            "rules": ["R122","R123","R124"] },
    "25": { "name": "Particles, Negation & Word Order", "rules": ["R125","R126","R127","R128","R129","R130","R131"] },
}

# ─── Rule definitions ───
# name, cluster, description, facets (grammar facets or ["default"]), facet_hints
RULES = {
    "R001": ("Nominative-Accusative basic sentence", 1, "Subject in nominative, direct object in accusative", ["default"], {}),
    "R002": ("Verb agreement with subject", 1, "Verb person and number agree with subject", ["default"], {}),
    "R003": ("Present tense: first and second conjugation", 1, "Regular present tense endings", ["default"], {}),
    "R004": ("Past tense: gender and number agreement", 1, "Past tense agrees with subject in gender and number", ["default"], {}),
    "R005": ("Zero copula in present", 1, "No 'to be' in present tense", ["default"], {}),

    "R006": ("Noun gender", 2, "Masculine, feminine, neuter gender endings", ["default"], {}),
    "R007": ("Regular plural formation", 2, "Standard plural endings -ы/-и/-а/-я", ["default"], {}),
    "R008": ("Irregular plurals", 2, "человек/люди, ребёнок/дети, etc.", ["default"], {}),
    "R009": ("Plural-only and singular-only nouns", 2, "Nouns used only in plural or singular", ["default"], {}),
    "R010": ("Adjective agreement in gender and number", 2, "Adjective endings match noun gender and number", ["default"], {}),
    "R011": ("Adjective-noun word order", 2, "Adjective precedes noun in neutral order", ["default"], {}),

    "R012": ("Genitive: possession", 3, "Genitive case for possession", ["fem_sg","masc_sg","neut_sg","pl","adj_agr"], {"fem_sg":"feminine singular noun in genitive","masc_sg":"masculine singular noun in genitive","neut_sg":"neuter singular noun in genitive","pl":"plural noun in genitive","adj_agr":"adjective agreeing in genitive"}),
    "R013": ("Genitive: negation (нет + Gen)", 3, "Genitive case after нет", ["fem_sg","masc_sg","neut_sg","pl","adj_agr"], {"fem_sg":"feminine singular noun after нет","masc_sg":"masculine singular noun after нет","neut_sg":"neuter singular noun after нет","pl":"plural noun after нет","adj_agr":"adjective agreeing in genitive after нет"}),
    "R014": ("Genitive: quantity", 3, "Много, мало, несколько + genitive", ["fem_sg","masc_sg","neut_sg","pl","adj_agr"], {"fem_sg":"feminine singular noun after quantity word","masc_sg":"masculine singular noun after quantity word","neut_sg":"neuter singular noun after quantity word","pl":"plural noun after quantity word","adj_agr":"adjective agreeing in genitive after quantity word"}),
    "R015": ("Genitive: partitive", 3, "Partitive genitive for indefinite quantity", ["fem_sg","masc_sg","neut_sg","adj_agr"], {"fem_sg":"feminine singular noun in partitive","masc_sg":"masculine singular noun in partitive","neut_sg":"neuter singular noun in partitive","adj_agr":"adjective in partitive construction"}),
    "R016": ("Genitive plural endings", 3, "Genitive plural formation", ["default"], {}),
    "R017": ("Genitive after numerals 2-4", 3, "Numerals 2, 3, 4 take genitive singular", ["fem","masc","neut","adj_agr"], {"fem":"feminine noun after 2-4","masc":"masculine noun after 2-4","neut":"neuter noun after 2-4","adj_agr":"adjective agreement after 2-4"}),
    "R018": ("Genitive prepositions", 3, "без, до, из, от, у, около, для + Gen", ["fem_sg","masc_sg","neut_sg","pl","adj_agr"], {"fem_sg":"feminine singular after genitive preposition","masc_sg":"masculine singular after genitive preposition","neut_sg":"neuter singular after genitive preposition","pl":"plural after genitive preposition","adj_agr":"adjective agreement after genitive preposition"}),

    "R019": ("Dative: indirect object", 4, "Recipient in dative", ["fem_sg","masc_sg","neut_sg","pl","adj_agr"], {"fem_sg":"feminine singular in dative","masc_sg":"masculine singular in dative","neut_sg":"neuter singular in dative","pl":"plural in dative","adj_agr":"adjective agreement in dative"}),
    "R020": ("Dative: impersonal constructions", 4, "Impersonal dative constructions", ["default"], {}),
    "R021": ("Dative: age", 4, "Age expressed with dative", ["default"], {}),
    "R022": ("Dative: verbs governing dative", 4, "Verbs that require dative", ["default"], {}),
    "R023": ("Dative prepositions", 4, "к, по, благодаря, согласно + Dat", ["fem_sg","masc_sg","neut_sg","pl"], {"fem_sg":"feminine singular after dative preposition","masc_sg":"masculine singular after dative preposition","neut_sg":"neuter singular after dative preposition","pl":"plural after dative preposition"}),
    "R024": ("Dative of experience", 4, "Мне кажется, мне хочется, мне нужно", ["default"], {}),

    "R025": ("Instrumental: means", 5, "Instrument or means of action", ["fem_sg","masc_sg","neut_sg","pl"], {"fem_sg":"feminine singular in instrumental","masc_sg":"masculine singular in instrumental","neut_sg":"neuter singular in instrumental","pl":"plural in instrumental"}),
    "R026": ("Instrumental: accompaniment (с + Instr)", 5, "С + instrumental for accompaniment", ["fem_sg","masc_sg","neut_sg","pl"], {"fem_sg":"feminine singular after с","masc_sg":"masculine singular after с","neut_sg":"neuter singular after с","pl":"plural after с"}),
    "R027": ("Instrumental: verbs governing instrumental", 5, "гордиться, заниматься, интересоваться", ["fem_sg","masc_sg","neut_sg","pl"], {"fem_sg":"feminine singular after instrumental verb","masc_sg":"masculine singular after instrumental verb","neut_sg":"neuter singular after instrumental verb","pl":"plural after instrumental verb"}),
    "R028": ("Instrumental prepositions", 5, "над, под, перед, между, за + Instr", ["fem_sg","masc_sg","neut_sg","pl"], {"fem_sg":"feminine singular after instrumental preposition","masc_sg":"masculine singular after instrumental preposition","neut_sg":"neuter singular after instrumental preposition","pl":"plural after instrumental preposition"}),
    "R029": ("Instrumental: predicative", 5, "Instrumental for profession or role", ["fem_sg","masc_sg","adj_agr"], {"fem_sg":"feminine singular in predicative instrumental","masc_sg":"masculine singular in predicative instrumental","adj_agr":"adjective agreement in predicative instrumental"}),

    "R030": ("Prepositional: location", 6, "в/на + prepositional for location", ["fem_sg","masc_sg","neut_sg","pl","adj_agr"], {"fem_sg":"feminine singular prepositional","masc_sg":"masculine singular prepositional","neut_sg":"neuter singular prepositional","pl":"plural prepositional","adj_agr":"adjective agreement in prepositional"}),
    "R031": ("Prepositional: topic", 6, "о/об + prepositional for topic", ["fem_sg","masc_sg","neut_sg","pl"], {"fem_sg":"feminine singular after о","masc_sg":"masculine singular after о","neut_sg":"neuter singular after о","pl":"plural after о"}),
    "R032": ("Prepositional prepositions", 6, "в, на, о, при + Prep", ["fem_sg","masc_sg","neut_sg","pl"], {"fem_sg":"feminine singular after prepositional preposition","masc_sg":"masculine singular after prepositional preposition","neut_sg":"neuter singular after prepositional preposition","pl":"plural after prepositional preposition"}),
    "R033": ("Location vs direction", 6, "Prep for location, Acc for direction", ["location","direction"], {"location":"prepositional case for location","direction":"accusative case for direction"}),
    "R034": ("в/на with geographic names", 6, "Usage of в/на with countries, cities", ["countries","cities","regions"], {"countries":"в/на with country names","cities":"в/на with city names","regions":"в/на with region names"}),

    "R035": ("Declension: masculine nouns", 7, "Hard and soft stem masculine declension", ["hard_stem","soft_stem"], {"hard_stem":"hard-stem masculine declension","soft_stem":"soft-stem masculine declension"}),
    "R036": ("Declension: feminine nouns", 7, "Hard and soft stem feminine declension", ["hard_stem","soft_stem"], {"hard_stem":"hard-stem feminine declension","soft_stem":"soft-stem feminine declension"}),
    "R037": ("Declension: neuter nouns", 7, "Neuter declension patterns", ["default"], {}),
    "R038": ("Declension: adjectives full paradigm", 7, "All six cases for adjectives", ["nom","acc","gen","dat","instr","prep"], {"nom":"nominative adjective","acc":"accusative adjective","gen":"genitive adjective","dat":"dative adjective","instr":"instrumental adjective","prep":"prepositional adjective"}),
    "R039": ("Irregular nouns", 7, "Irregular noun declensions", ["default"], {}),
    "R040": ("Indeclinable nouns", 7, "Nouns that don't decline", ["default"], {}),

    "R041": ("Long-form attributive adjective", 8, "Standard attributive adjective before noun", ["default"], {}),
    "R042": ("Short-form predicative adjective", 8, "Short form for state or condition", ["default"], {}),
    "R043": ("Short-form in impersonal constructions", 8, "Adverbs in short form as predicates", ["default"], {}),
    "R044": ("Possessive adjectives", 8, "мамин, папин, отцов, etc.", ["default"], {}),
    "R045": ("Adjective + numeral agreement", 8, "Agreement in numeral phrases", ["default"], {}),

    "R046": ("Comparative: simple form", 9, "-ее, -е, -ше comparative", ["default"], {}),
    "R047": ("Comparative: compound form", 9, "более + adjective", ["default"], {}),
    "R048": ("Superlative: simple and compound", 9, "-ейший or самый + adjective", ["default"], {}),
    "R049": ("Irregular comparatives", 9, "хороший/лучше, плохой/хуже, etc.", ["default"], {}),

    "R050": ("Aspect: perfective vs imperfective", 10, "Core aspect distinction", ["past_perf","past_imperf","future_perf","future_imperf","in_context"], {"past_perf":"past tense perfective","past_imperf":"past tense imperfective","future_perf":"future perfective","future_imperf":"future imperfective","in_context":"aspect choice in context"}),
    "R051": ("Aspect: prefix-based pairs", 10, "писать/написать, делать/сделать", ["default"], {}),
    "R052": ("Aspect: suppletive pairs", 10, "говорить/сказать, брать/взять", ["default"], {}),
    "R053": ("Aspect choice in context", 10, "Choosing aspect based on sentence meaning", ["default"], {}),
    "R054": ("Aspect in imperative", 10, "Imperfective for invitation, perfective for command", ["imperf_imperative","perf_imperative"], {"imperf_imperative":"imperfective imperative","perf_imperative":"perfective imperative"}),
    "R055": ("Aspect after phase verbs", 10, "начать, продолжать, кончить + imperfective", ["default"], {}),
    "R056": ("Prohibition aspect", 10, "не делай vs не сделай", ["default"], {}),

    "R057": ("Future: compound (imperfective)", 11, "буду + infinitive", ["default"], {}),
    "R058": ("Future: simple (perfective)", 11, "Perfective present-tense form = future", ["default"], {}),
    "R059": ("Imperative: formation", 11, "Standard imperative endings", ["default"], {}),
    "R060": ("Imperative: negative", 11, "не + imperative", ["default"], {}),
    "R061": ("Conditional/subjunctive (бы + past)", 11, "Hypothetical conditions", ["default"], {}),
    "R062": ("Optative constructions", 11, "пусть, давай + forms", ["default"], {}),

    "R063": ("Reflexive -ся: basic", 12, "Action reflects back on subject", ["default"], {}),
    "R064": ("Reflexive -ся: reciprocal", 12, "Mutual action (целоваться, встречаться)", ["default"], {}),
    "R065": ("Reflexive -ся: passive", 12, "Passive voice with -ся", ["default"], {}),
    "R066": ("Reflexive -ся: impersonal", 12, "хочется, спится, работается", ["default"], {}),

    "R067": ("Motion: unidirectional vs multidirectional", 13, "Motion verb pairs", ["default"], {}),
    "R068": ("Motion: prefixed spatial forms", 13, "Spatial prefixes on motion verbs", ["default"], {}),
    "R069": ("Motion: prefixed aspect pairs", 13, "приходить/прийти, уезжать/уехать", ["default"], {}),
    "R070": ("Motion: figurative uses", 13, "идти о чём, время идёт", ["default"], {}),
    "R071": ("Motion: по- perfective inchoative", 13, "пойти, поехать = start going", ["default"], {}),
    "R072": ("Motion: imperative forms", 13, "иди vs ходи in commands", ["default"], {}),

    "R073": ("Verb government: Genitive", 14, "бояться, избегать, желать + Gen", ["default"], {}),
    "R074": ("Verb government: Instrumental", 14, "гордиться, руководить, интересоваться + Instr", ["default"], {}),
    "R075": ("Verb government: Dative", 14, "помогать, верить, звонить + Dat", ["default"], {}),
    "R076": ("Verb government: о/в/на + Prep", 14, "думать о, верить в, смотреть на", ["default"], {}),
    "R077": ("Verb government: direct object variations", 14, "Verbs taking Acc vs Gen objects", ["default"], {}),

    "R078": ("Prefixes: aspectual", 15, "по-, про-, за- as delimitative/inceptive", ["po","pro","za"], {"po":"по- delimitative prefix","pro":"про- completive prefix","za":"за- inceptive prefix"}),
    "R079": ("Prefixes: spatial", 15, "в-, вы-, при-, у-, от-, под-, над-, пере-", ["default"], {}),
    "R080": ("Prefixes: lexical", 15, "пере- re-, недо- under-, etc.", ["default"], {}),

    "R081": ("Present active participle", 16, "-ущий/-ющий form", ["default"], {}),
    "R082": ("Past active participle", 16, "-вший form", ["default"], {}),
    "R083": ("Present passive participle", 16, "-емый/-имый form", ["default"], {}),
    "R084": ("Past passive participle", 16, "-нный/-тый form", ["default"], {}),
    "R085": ("Short-form passive participle", 16, "Short passive for state", ["default"], {}),

    "R086": ("Imperfective gerund", 17, "-а/-я form", ["default"], {}),
    "R087": ("Perfective gerund", 17, "-в/-вши form", ["default"], {}),
    "R088": ("Gerund usage and constraints", 17, "Same-subject rule; stylistic register", ["default"], {}),

    "R089": ("Personal pronouns: Nominative", 18, "я, ты, он, она, оно, мы, вы, они", ["default"], {}),
    "R090": ("Personal pronouns: full case paradigm", 18, "меня, мне, мной, обо мне, etc.", ["acc","gen","dat","instr","prep"], {"acc":"personal pronoun accusative","gen":"personal pronoun genitive","dat":"personal pronoun dative","instr":"personal pronoun instrumental","prep":"personal pronoun prepositional"}),
    "R091": ("Personal pronouns with prepositions", 18, "у меня, к нему, с ней", ["default"], {}),
    "R092": ("Possessive pronouns", 18, "мой, твой, наш, ваш, его, её, их", ["masc","fem","neut","pl"], {"masc":"masculine possessive agreement","fem":"feminine possessive agreement","neut":"neuter possessive agreement","pl":"plural possessive agreement"}),
    "R093": ("Possessive-reflexive свой", 18, "свой vs его/её/их", ["default"], {}),

    "R094": ("Reflexive pronoun себя", 19, "No nominative form", ["default"], {}),
    "R095": ("Demonstrative pronouns", 19, "этот, тот, такой", ["etot","tot","takoy"], {"etot":"этот (this)","tot":"тот (that)","takoy":"такой (such)"}),
    "R096": ("Determinative pronouns", 19, "весь, сам, самый", ["ves","sam","samy"], {"ves":"весь (all)","sam":"сам (self)","samy":"самый (the very)"}),
    "R097": ("Interrogative and relative pronouns", 19, "кто, что, какой, чей, который", ["kto_chto","kakoy","chey","kotory"], {"kto_chto":"кто/что","kakoy":"какой","chey":"чей","kotory":"который"}),
    "R098": ("Negative and indefinite pronouns", 19, "никто, ничто, кто-то, кое-кто", ["negative","indefinite"], {"negative":"negative pronouns (никто, ничто)","indefinite":"indefinite pronouns (кто-то, кое-кто)"}),

    "R099": ("Cardinal numerals 1-20", 20, "один, два, три... двадцать", ["one","two_four","five_plus","gender_agreement"], {"one":"numeral один","two_four":"numerals 2-4","five_plus":"numerals 5+","gender_agreement":"gender agreement of numerals"}),
    "R100": ("Declension of один", 20, "Agrees like adjective", ["default"], {}),
    "R101": ("Declension of два, три, четыре", 20, "Special declension patterns", ["default"], {}),
    "R102": ("Declension of пять and above", 20, "Decline like nouns", ["default"], {}),
    "R103": ("Ordinal numerals", 20, "первый, второй...", ["default"], {}),
    "R104": ("Collective numerals", 20, "двое, трое, четверо", ["default"], {}),
    "R105": ("Fractions", 20, "половина, треть, две трети", ["default"], {}),
    "R106": ("Compound numbers", 20, "21, 32, 104 — only last part declines", ["default"], {}),

    "R107": ("Adverb formation", 21, "-о/-е from adjectives", ["default"], {}),
    "R108": ("Adverb comparative and superlative", 21, "-ее, -ше; быстрее всех", ["default"], {}),
    "R109": ("Adverb position in sentence", 21, "Placement changes emphasis", ["default"], {}),
    "R110": ("Negative and indefinite adverbs", 21, "нигде, никогда; где-то, куда-нибудь", ["negative","indefinite"], {"negative":"negative adverbs (нигде, никогда)","indefinite":"indefinite adverbs (где-то, куда-нибудь)"}),

    "R111": ("Prepositions + Accusative", 22, "в, на, за, про, через + Acc", ["default"], {}),
    "R112": ("Prepositions + Genitive", 22, "без, до, из, от, у, около, для + Gen", ["default"], {}),
    "R113": ("Prepositions + Dative", 22, "к, по, благодаря + Dat", ["default"], {}),
    "R114": ("Prepositions + Instrumental", 22, "над, под, перед, между, с + Instr", ["default"], {}),
    "R115": ("Prepositions + Prepositional", 22, "в, на, о, при + Prep", ["default"], {}),

    "R116": ("Coordinating conjunctions", 23, "и, а, но, да, или, либо", ["default"], {}),
    "R117": ("Subordinating: что, чтобы", 23, "Clause introduction", ["chto","chtoby"], {"chto":"что clause","chtoby":"чтобы clause"}),
    "R118": ("Subordinating: cause", 23, "потому что, так как, поскольку", ["default"], {}),
    "R119": ("Subordinating: concessive", 23, "хотя, несмотря на то что", ["default"], {}),
    "R120": ("Temporal conjunctions", 23, "когда, пока, после того как, перед тем как", ["default"], {}),
    "R121": ("Relative clauses with который", 23, "Case and agreement", ["default"], {}),

    "R122": ("Direct speech", 24, "Punctuation and framing", ["default"], {}),
    "R123": ("Indirect speech: statements", 24, "что + shifted clause", ["default"], {}),
    "R124": ("Indirect speech: questions and imperatives", 24, "Reported questions and commands", ["default"], {}),

    "R125": ("Negation: не", 25, "Standard negation", ["default"], {}),
    "R126": ("Negation: ни (multiple negation)", 25, "никто не, никогда не", ["default"], {}),
    "R127": ("Emphatic particles", 25, "же, ведь, -то, именно", ["zhe","ved","to","imenno"], {"zhe":"же (emphasis)","ved":"ведь (after all)","to":"-то (emphasis suffix)","imenno":"именно (precisely)"}),
    "R128": ("Question particles", 25, "ли, разве, неужели", ["li","razve","neuzheli"], {"li":"ли (question particle)","razve":"разве (really?)","neuzheli":"неужели (could it be?)"}),
    "R129": ("Neutral word order", 25, "SVO default order", ["default"], {}),
    "R130": ("Topic/comment and emphasis", 25, "Word order for information structure", ["default"], {}),
    "R131": ("Inversion for questions", 25, "Question formation and stylistic inversion", ["default"], {}),
}
# ─── Lexical facets from the sorted export ───
# (loaded from data/lexical_facets.json, which is the file you exported)

LEXICAL_FACETS_PATH = PROJECT_ROOT / "data" / "lexical_facets.json"

# Mapping from export rule names to rule IDs
EXPORT_RULE_MAP = {
    "R020 · Dative impersonal": "R020",
    "R022 · Verbs + Dative": "R022",
    "R073 · Verbs + Genitive": "R073",
    "R074 · Verbs + Instrumental": "R074",
    "R076 · Verbs + о/в/на + case": "R076",
    "R016 · Genitive plural endings": "R016",
    "R039 · Irregular nouns": "R039",
    "R040 · Indeclinable nouns": "R040",
    "R066 · Reflexive impersonal": "R066",
    "R044 · Possessive adjectives": "R044",
    "R062 · Optative constructions": "R062",
    "R071 · Motion verbs with по-": "R071",
    "R021 · Dative of age": "R021",
}

# ─── Additional lexical facets (added without sorting) ───
# These get merged into the lexicon alongside the sorted items.

EXTRA_FACETS = {
    "R067": {
        "name": "Motion: unidirectional vs multidirectional",
        "cluster": 13,
        "description": "Base motion verb pairs",
        "facets": [
            ("идти", "go (on foot, one direction)", "Я иду в школу"),
            ("ходить", "go (on foot, habitual/round trip)", "Я хожу в школу каждый день"),
            ("ехать", "go (by vehicle, one direction)", "Я еду в Москву"),
            ("ездить", "go (by vehicle, habitual/round trip)", "Я езжу в Москву часто"),
            ("бежать", "run (one direction)", "Он бежит к автобусу"),
            ("бегать", "run (habitual/multi)", "Он бегает по утрам"),
            ("лететь", "fly (one direction)", "Самолёт летит в Париж"),
            ("летать", "fly (habitual/multi)", "Он летает в Париж часто"),
            ("плыть", "swim/sail (one direction)", "Корабль плывёт к берегу"),
            ("плавать", "swim (habitual/multi)", "Она плавает в бассейне"),
            ("нести", "carry (on foot, one direction)", "Он несёт чемодан"),
            ("носить", "carry (habitual/multi)", "Он носит очки"),
            ("везти", "transport (by vehicle, one direction)", "Он везёт детей на дачу"),
            ("возить", "transport (habitual)", "Он возит детей в школу"),
            ("вести", "lead (one direction)", "Он ведёт ребёнка в школу"),
            ("водить", "lead (habitual)", "Он водит машину"),
            ("ползти", "crawl (one direction)", "Ребёнок ползёт к маме"),
            ("ползать", "crawl (habitual)", "Ребёнок ползает по комнате"),
            ("лезть", "climb (one direction)", "Он лезет на дерево"),
            ("лазать", "climb (habitual)", "Дети лазают по деревьям"),
        ],
    },
    "R068": {
        "name": "Motion: prefixed spatial forms",
        "cluster": 13,
        "description": "Prefixed motion verbs with spatial meaning",
        "facets": [
            ("прийти / приехать", "arrive (foot / vehicle)", "Он пришёл домой"),
            ("уйти / уехать", "leave (foot / vehicle)", "Он ушёл на работу"),
            ("выйти / выехать", "go out / exit", "Он вышел из дома"),
            ("войти / въехать", "go in / enter", "Он вошёл в комнату"),
            ("зайти / заехать", "drop by", "Зайди ко мне вечером"),
            ("дойти / доехать", "reach (on foot / vehicle)", "Я дошёл до парка"),
            ("перейти / переехать", "cross / move (house)", "Он перешёл улицу"),
            ("отойти / отъехать", "move away", "Он отошёл от двери"),
            ("подойти / подъехать", "approach", "Он подошёл к столу"),
            ("обойти / объехать", "go around", "Мы обошли лужу"),
        ],
    },
    "R074_extra": {
        # Merged into R074
        "facets": [
            ("пахнуть", "smell like", "Пахнет цветами"),
            ("выглядеть", "look like / appear", "Он выглядит усталым"),
            ("называться", "be called", "Это называется городом"),
            ("считаться", "be considered", "Он считается специалистом"),
            ("казаться", "seem", "Он кажется добрым"),
            ("оказаться", "turn out to be", "Он оказался правым"),
        ],
    },
}


def build():
    lexicon = {
        "meta": {
            "version": "4.0",
            "total_rules": len(RULES),
            "total_clusters": len(CLUSTERS),
        },
        "clusters": {
            "order": [int(k) for k in sorted(CLUSTERS.keys(), key=int)],
            "definitions": {
                k: {
                    "name": v["name"],
                    "rules": v["rules"],
                }
                for k, v in CLUSTERS.items()
            },
        },
        "rules": {},
        "state": {},
    }

    # Base rule definitions
    for rid, (name, cluster, desc, facets, hints) in RULES.items():
        lexicon["rules"][rid] = {
            "cluster": cluster,
            "name": name,
            "description": desc,
            "facets": facets,
            "facet_hints": hints,
        }

    # Load the sorted lexical facets
    if LEXICAL_FACETS_PATH.exists():
        with open(LEXICAL_FACETS_PATH, "r", encoding="utf-8") as f:
            lexical = json.load(f)

        for export_name, items in lexical.items():
            rid = EXPORT_RULE_MAP.get(export_name)
            if not rid:
                print(f"WARNING: no rule mapping for {export_name}")
                continue

            facet_names = []
            facet_hints = {}
            for item in items:
                ru = item.get("ru", "").strip()
                if not ru:
                    continue
                facet_names.append(ru)
                facet_hints[ru] = item.get("hint", "") or item.get("en", "")

            lexicon["rules"][rid]["facets"] = facet_names
            lexicon["rules"][rid]["facet_hints"] = facet_hints

    # Add extra facets (R067, R068)
    for rid, data in EXTRA_FACETS.items():
        if rid == "R074_extra":
            continue

        facet_names = [name for name, en, hint in data["facets"]]
        facet_hints = {name: hint for name, en, hint in data["facets"]}

        lexicon["rules"][rid] = {
            "cluster": data["cluster"],
            "name": data["name"],
            "description": data["description"],
            "facets": facet_names,
            "facet_hints": facet_hints,
        }

    # Merge R074 extras into R074
    if "R074" in lexicon["rules"] and "R074_extra" in EXTRA_FACETS:
        r074 = lexicon["rules"]["R074"]
        for name, en, hint in EXTRA_FACETS["R074_extra"]["facets"]:
            if name not in r074["facets"]:
                r074["facets"].append(name)
                r074["facet_hints"][name] = hint

    # Initialize state section — every rule gets a state entry with empty facets
    for rid in lexicon["rules"]:
        lexicon["state"][rid] = {
            "state": "unlearned",
            "times_tested": 0,
            "times_correct": 0,
            "last_tested": None,
            "last_failed": None,
            "last_failed_facet": None,
            "facets": {},
        }

    # Special case: clusters 1 and 2 rules are pre-mastered
    for rid in ["R001", "R002", "R003", "R004", "R005",
                "R006", "R007", "R008", "R009", "R010", "R011"]:
        if rid in lexicon["state"]:
            lexicon["state"][rid]["state"] = "mastered"

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(lexicon, f, ensure_ascii=False, indent=2)

    print(f"Wrote {OUTPUT}")
    print(f"Total rules: {len(lexicon['rules'])}")
    print(f"Total with lexical facets: {sum(1 for r in lexicon['rules'].values() if len(r['facets']) > 1 or r['facets'] != ['default'])}")


if __name__ == "__main__":
    build()
