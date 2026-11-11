"""Text normalisation: accents, case, Portuguese plurals, and the public word lists."""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "config"

CATEGORIES = ("person", "place", "organisation", "topic")

# Plural forms whose singular the suffix rules below would get wrong.
IRREGULAR = {
    "meses": "mês", "países": "país", "gases": "gás", "deuses": "deus", "juízes": "juiz",
    "cidadãos": "cidadão", "irmãos": "irmão", "mãos": "mão", "órgãos": "órgão",
    "pães": "pão", "cães": "cão", "alemães": "alemão", "capitães": "capitão",
}
# Words ending in -s that are already singular (or invariable).
INVARIABLE = {
    "vírus", "ônibus", "tênis", "lápis", "atlas", "pires", "óculos", "bônus", "ônus", "férias",
    "parabéns", "juros", "tórax", "status", "campus", "news", "fake", "eua", "brics", "mercosul",
    "biquíni", "cais", "simples", "reais", "pais",
}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def singular(word: str) -> str:
    """Best-effort Portuguese singular of a lowercase word."""
    w = word.lower()
    if len(w) <= 3 or w in INVARIABLE or not w.endswith("s"):
        return w
    if w in IRREGULAR:
        return IRREGULAR[w]
    for suf, rep in (("ões", "ão"), ("ães", "ão"), ("ãos", "ão"), ("ais", "al"), ("éis", "el"),
                     ("óis", "ol"), ("uis", "ul"), ("ns", "m"), ("res", "r"), ("zes", "z")):
        if w.endswith(suf):
            return w[: -len(suf)] + rep
    if w[-2] in "áéíóúâêô":          # mês, gás, país, após: already singular
        return w
    if w.endswith("is"):              # civis -> civil, fuzis -> fuzil (but tênis stays)
        return w if strip_accents(w) != w else w[:-2] + "il"
    if w.endswith("us"):
        return w
    if w[-2] in "aeo":
        return w[:-1]
    return w


def key(text: str, singularise: bool = True) -> str:
    """Matching key: lowercase, no accents, singular words, single spaces, no edge punctuation."""
    words = re.findall(r"[^\W_]+(?:[-'][^\W_]+)*", text.lower())
    if singularise:
        words = [singular(w) for w in words]
    return strip_accents(" ".join(words))


def _read_list(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


@dataclass
class WordLists:
    stopwords: set[str] = field(default_factory=set)          # keys of single words
    stop_phrases: list[str] = field(default_factory=list)     # raw multi-word entries
    crime: set[str] = field(default_factory=set)              # keys of single words
    aliases: dict[str, str] = field(default_factory=dict)     # variant key -> canonical key
    canonical: dict[str, dict] = field(default_factory=dict)  # canonical key -> {label, category}

    @classmethod
    def load(cls, config_dir: Path = CONFIG) -> "WordLists":
        wl = cls()
        for entry in _read_list(config_dir / "stopwords.txt"):
            if " " in entry.strip():
                wl.stop_phrases.append(entry)
            else:
                wl.stopwords.add(key(entry))
                wl.stopwords.add(key(entry, singularise=False))
        wl.crime = {key(e) for e in _read_list(config_dir / "crime_terms.txt")}
        raw = json.loads((config_dir / "aliases.json").read_text(encoding="utf-8"))
        wl.add_aliases(raw)
        return wl

    def add_aliases(self, raw: dict) -> None:
        for name, spec in raw.items():
            if name.startswith("_"):
                continue
            ck = key(name, singularise=False)
            cat = spec.get("category")
            if cat is not None and cat not in CATEGORIES:
                raise ValueError(f"aliases.json: bad category {cat!r} for {name!r}")
            self.canonical[ck] = {"label": name, "category": cat}
            for v in [name, *spec.get("variants", [])]:
                # Register both forms: entity keys are not singularised, topic keys are.
                self.aliases[key(v, singularise=False)] = ck
                self.aliases[key(v)] = ck

    def is_stop(self, k: str) -> bool:
        return k in self.stopwords

    def resolve(self, k: str) -> str:
        return self.aliases.get(k, k)

    def is_crime(self, k: str) -> bool:
        return any(w in self.crime for w in k.split())

    def strip_stop_phrases(self, text: str) -> str:
        """Replace multi-word stopwords ("ao vivo") with a break so they never form terms."""
        for p in self.stop_phrases:
            text = re.sub(r"(?<!\w)" + re.escape(p) + r"(?!\w)", " | ", text, flags=re.IGNORECASE)
        return text
