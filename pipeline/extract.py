"""Term extraction from headlines with spaCy's Portuguese model.

Per headline we keep:
  * named entities (people, places, organisations) — spaCy NER, plus capitalised
    runs the NER missed;
  * topics — a noun with the adjectives that follow it, as ONE expression
    ("reforma tributária", "governo brasileiro"); its parts don't count separately.
Verbs, articles, prepositions etc. never count. Stopwords are dropped.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .normalize import WordLists, key

NER_CATEGORY = {"PER": "person", "LOC": "place", "ORG": "organisation", "MISC": None}
# Capitalised adjectives the tagger often reads as proper nouns ("governo Brasileiro").
ADJ_SUFFIXES = ("eiro", "eira", "ano", "ana", "ense", "ês", "esa", "ista", "al", "ico", "ica",
                "ino", "ina", "ário", "ária")
EDGE_POS = {"DET", "ADP", "CCONJ", "SCONJ", "PRON", "PUNCT", "AUX", "VERB", "NUM", "SYM"}

MODEL = "pt_core_news_sm"


@dataclass(frozen=True)
class Mention:
    key: str          # matching key after alias resolution
    surface: str      # text as written in the headline
    category: str | None   # vote from this mention (None = no opinion)


def load_nlp():
    import spacy
    return spacy.load(MODEL, exclude=["parser", "lemmatizer"])


def _looks_adjective(tok) -> bool:
    t = tok.text.lower()
    return tok.pos_ == "ADJ" or (tok.pos_ == "PROPN" and t.endswith(ADJ_SUFFIXES))


def _trim(span_tokens: list, wl: WordLists) -> list:
    toks = list(span_tokens)
    while toks and (toks[0].pos_ in EDGE_POS or wl.is_stop(key(toks[0].text))):
        toks.pop(0)
    while toks and (toks[-1].pos_ in EDGE_POS or wl.is_stop(key(toks[-1].text))):
        toks.pop()
    return toks


def _mention(toks: list, category: str | None, singularise: bool, wl: WordLists) -> Mention | None:
    if not toks:
        return None
    surface = " ".join(t.text for t in toks)
    k = key(surface, singularise=singularise)
    if not k or len(k) < 2 or k.isdigit() or wl.is_stop(k):
        return None
    k = wl.resolve(k)
    return Mention(k, surface, category)


def mentions_from_doc(doc, wl: WordLists) -> list[Mention]:
    out: list[Mention] = []
    used = [False] * len(doc)

    # 1. Named entities. A one-word "entity" that is really an adjective after a
    #    noun ("governo Brasileiro") is left for the topic pass instead.
    for ent in doc.ents:
        if len(ent) == 1 and ent.start > 0 and doc[ent.start - 1].pos_ == "NOUN" \
                and _looks_adjective(ent[0]):
            continue
        toks = _trim(list(ent), wl)
        m = _mention(toks, NER_CATEGORY.get(ent.label_), False, wl)
        for t in ent:
            used[t.i] = True
        if m:
            out.append(m)

    # 2. Topics: NOUN (ADJ)*, and capitalised PROPN runs the NER missed.
    i = 0
    while i < len(doc):
        tok = doc[i]
        if used[i]:
            i += 1
            continue
        if tok.pos_ == "NOUN" or (tok.pos_ == "PROPN" and tok.text[:1].isupper()):
            j = i + 1
            if tok.pos_ == "PROPN":
                while j < len(doc) and not used[j] and doc[j].pos_ == "PROPN":
                    j += 1
            while j < len(doc) and not (used[j] and len(doc.ents) and _is_multi_ent(doc, j)) \
                    and _looks_adjective(doc[j]) and not wl.is_stop(key(doc[j].text)):
                j += 1
            toks = _trim(list(doc[i:j]), wl)
            is_proper = all(t.pos_ == "PROPN" for t in toks)
            m = _mention(toks, None if is_proper else "topic", not is_proper, wl)
            if m:
                out.append(m)
            i = j
        else:
            i += 1

    # A term counts once per headline.
    seen, uniq = set(), []
    for m in out:
        if m.key not in seen:
            seen.add(m.key)
            uniq.append(m)
    return uniq


def _is_multi_ent(doc, i: int) -> bool:
    return any(e.start <= i < e.end and len(e) > 1 for e in doc.ents)


def extract(titles: Iterable[str], wl: WordLists, nlp=None) -> list[list[Mention]]:
    nlp = nlp or load_nlp()
    cleaned = [wl.strip_stop_phrases(t) for t in titles]
    return [mentions_from_doc(doc, wl) for doc in nlp.pipe(cleaned, batch_size=256)]
