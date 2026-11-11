"""Run: python -m unittest discover -s tests   (spaCy tests skip if the model is missing)."""
import unittest

from pipeline.extract import Mention
from pipeline.normalize import WordLists, key, singular, strip_accents
from pipeline.score import rank, outlets_by_term, term_meta, window_terms


def _model_available() -> bool:
    try:
        import spacy  # noqa: F401
        import pt_core_news_sm  # noqa: F401
        return True
    except ImportError:
        return False


class Normalisation(unittest.TestCase):
    def test_accents_and_case(self):
        self.assertEqual(strip_accents("Eleição São Paulo"), "Eleicao Sao Paulo")
        self.assertEqual(key("  Reforma  TRIBUTÁRIA! "), "reforma tributaria")

    def test_plurals(self):
        cases = {
            "impostos": "imposto", "eleições": "eleição", "homens": "homem", "mulheres": "mulher",
            "hospitais": "hospital", "papéis": "papel", "civis": "civil", "vezes": "vez",
            "alemães": "alemão", "cidadãos": "cidadão", "países": "país", "meses": "mês",
            "escolas": "escola", "redes": "rede",
        }
        for plural, sing in cases.items():
            self.assertEqual(singular(plural), sing, plural)

    def test_singulars_untouched(self):
        for w in ("país", "mês", "gás", "vírus", "ônibus", "tênis", "juros", "lápis", "governo"):
            self.assertEqual(singular(w), w, w)

    def test_plural_and_singular_share_a_key(self):
        self.assertEqual(key("Eleições"), key("eleição"))
        self.assertEqual(key("reformas tributárias"), key("reforma tributária"))

    def test_entity_keys_not_singularised(self):
        self.assertEqual(key("Petrobras", singularise=False), "petrobras")
        self.assertEqual(key("Estados Unidos", singularise=False), "estados unidos")


class Aliases(unittest.TestCase):
    def setUp(self):
        self.wl = WordLists()
        self.wl.add_aliases({
            "_comment": "ignored",
            "Lula": {"category": "person", "variants": ["presidente Lula", "Luiz Inácio Lula da Silva"]},
            "EUA": {"category": "place", "variants": ["Estados Unidos"]},
        })

    def test_variants_resolve_to_canonical(self):
        for v in ("Lula", "presidente Lula", "Presidente LULA", "Luiz Inácio Lula da Silva"):
            self.assertEqual(self.wl.resolve(key(v, singularise=False)), "lula", v)
            self.assertEqual(self.wl.resolve(key(v)), "lula", v)
        self.assertEqual(self.wl.resolve(key("Estados Unidos", singularise=False)), "eua")

    def test_unknown_passes_through(self):
        self.assertEqual(self.wl.resolve("haddad"), "haddad")

    def test_alias_label_and_category_override_votes(self):
        items = [{"o": "a", "ts": 0}, {"o": "b", "ts": 0}]
        mentions = [[Mention("eua", "Estados Unidos", "organisation")],
                     [Mention("eua", "EUA", "organisation")]]
        meta = term_meta(items, mentions, self.wl)
        self.assertEqual(meta["eua"]["label"], "EUA")
        self.assertEqual(meta["eua"]["category"], "place")

    def test_bad_category_rejected(self):
        with self.assertRaises(ValueError):
            self.wl.add_aliases({"X": {"category": "animal", "variants": []}})

    def test_shipped_aliases_load(self):
        wl = WordLists.load()
        self.assertEqual(wl.resolve(key("Supremo Tribunal Federal", singularise=False)), "stf")


class Stopwords(unittest.TestCase):
    def setUp(self):
        self.wl = WordLists.load()

    def test_filler_words_are_stopwords(self):
        for w in ("diz", "após", "veja", "Vídeos", "o", "de"):
            self.assertTrue(self.wl.is_stop(key(w)), w)

    def test_content_words_are_not(self):
        for w in ("governo", "imposto", "Lula"):
            self.assertFalse(self.wl.is_stop(key(w)), w)

    def test_multiword_stopword_removed_from_text(self):
        out = self.wl.strip_stop_phrases("Assista AO VIVO: sessão do Senado")
        self.assertNotIn("vivo", out.lower())
        self.assertIn("Senado", out)

    def test_crime_flag(self):
        self.assertTrue(self.wl.is_crime(key("tráfico de drogas")))
        self.assertTrue(self.wl.is_crime(key("Homicídios")))
        self.assertFalse(self.wl.is_crime(key("reforma tributária")))


class DistinctOutletScoring(unittest.TestCase):
    def _data(self):
        # 'imposto': 3 articles, all from ONE outlet. 'lula': 2 articles from 2 outlets.
        items = [
            {"id": "1", "o": "g1", "ts": 100}, {"id": "2", "o": "g1", "ts": 101},
            {"id": "3", "o": "g1", "ts": 102}, {"id": "4", "o": "folha", "ts": 103},
        ]
        m = lambda k: Mention(k, k, "topic")  # noqa: E731
        mentions = [[m("imposto"), m("lula")], [m("imposto")], [m("imposto")], [m("lula")]]
        return items, mentions

    def test_score_counts_outlets_not_articles(self):
        items, mentions = self._data()
        acc = outlets_by_term(items, mentions, 0, 1000)
        ranked = rank(acc, items, min_outlets=1)
        self.assertEqual(ranked[0], ("lula", 2, 2))
        self.assertEqual(ranked[1], ("imposto", 1, 3))

    def test_min_outlets_filters_single_outlet_terms(self):
        items, mentions = self._data()
        ranked = rank(outlets_by_term(items, mentions, 0, 1000), items, min_outlets=2)
        self.assertEqual([r[0] for r in ranked], ["lula"])

    def test_window_bounds(self):
        items, mentions = self._data()
        acc = outlets_by_term(items, mentions, 102, 1000)  # only items 3 and 4
        self.assertEqual({k: len(v) for k, v in acc.items()}, {"imposto": 1, "lula": 1})

    def test_trend_against_previous_window(self):
        items, mentions = self._data()
        meta = {"lula": {"label": "Lula", "category": "person", "crime": False},
                "imposto": {"label": "imposto", "category": "topic", "crime": False}}
        terms, _ = window_terms(items, mentions, meta, now=1000, window="6h",
                                prev_scores={"lula": 5})
        self.assertEqual(terms[0]["key"], "lula")
        self.assertEqual(terms[0]["trend"], -3)
        unknown, _ = window_terms(items, mentions, meta, now=1000, window="6h", prev_scores=None)
        self.assertIsNone(unknown[0]["trend"])


@unittest.skipUnless(_model_available(), "spaCy Portuguese model not installed")
class Extraction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pipeline.extract import extract, load_nlp
        cls.wl = WordLists.load()
        cls.nlp = load_nlp()
        cls.extract = staticmethod(lambda titles: extract(titles, cls.wl, cls.nlp))

    def keys(self, title):
        return {m.key for m in self.extract([title])[0]}

    def test_spec_example(self):
        # Only "governo brasileiro" and "impostos" count; "O" and "decide" don't.
        self.assertEqual(self.keys("O governo Brasileiro decide cortar impostos"),
                         {"governo brasileiro", "imposto"})

    def test_expression_not_split(self):
        ks = self.keys("Lula pede reforma tributária ao Senado")
        self.assertIn("reforma tributaria", ks)
        self.assertNotIn("reforma", ks)
        self.assertNotIn("tributaria", ks)
        self.assertNotIn("pede", ks)

    def test_aliases_applied(self):
        self.assertIn("lula", self.keys("Presidente Lula viaja aos Estados Unidos"))
        self.assertIn("eua", self.keys("Presidente Lula viaja aos Estados Unidos"))

    def test_stop_phrase_removed(self):
        ks = self.keys("Veja ao vivo: Senado vota PEC")
        self.assertFalse(any("vivo" in k or "veja" in k for k in ks), ks)


if __name__ == "__main__":
    unittest.main()
