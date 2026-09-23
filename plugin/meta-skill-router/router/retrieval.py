"""Lexical candidate retrieval: BM25 over weighted manifest fields with Snowball stemming.

Same formulation as Hermes' deferred-tool search (``tools/tool_search_catalog.py``), kept local because
that module's entries are tool-shaped and its token cache is private. Admission uses the query's rarest
token so unrelated queries return nothing instead of one-token noise."""

from __future__ import annotations

import math
import re
import threading
from collections import Counter
from functools import lru_cache
from typing import Dict, List, Optional, Sequence, Tuple

from .schemas import Candidate, SkillManifest

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_FIELD_WEIGHTS = {"name": 3, "tags": 2, "triggers": 2, "description": 1, "category": 1}
_thread_local = threading.local()

K1 = 1.5
B = 0.75
# A document is admitted when it shares a *distinctive* token with the query: one that appears in at
# most DISTINCTIVE_DF_SHARE of the catalog. Hermes' tool search admits on the single rarest query token,
# which is right for "find the one tool" lookups and wrong for multi-skill requests ("find papers and
# save notes" must surface both arxiv and obsidian). A relative score floor trims the tail.
DISTINCTIVE_DF_SHARE = 0.34
RELATIVE_SCORE_FLOOR = 0.15

# Function words that carry no routing signal; tokenized on both sides so they never become the
# "rarest" token of a query.
STOPWORDS = frozenset("""
a about above after again against all am an and any are as at be because been before being below between
both but by can could did do does doing down during each few for from further had has have having he her here
hers herself him himself his how i if in into is it its itself just let me more most my myself no nor not now of
off on once only or other our ours ourselves out over own please same she should so some such than that the their
theirs them themselves then there these they this those through to too under until up us very was we were what
when where which while who whom why will with would you your yours yourself yourselves
""".split())


@lru_cache(maxsize=16384)
def _stem(token: str) -> str:
    try:
        import snowballstemmer
    except ImportError:  # degrade to no stemming
        return token
    stemmer = getattr(_thread_local, "stemmer", None)
    if stemmer is None:
        stemmer = _thread_local.stemmer = snowballstemmer.stemmer("english")
    return stemmer.stemWord(token)


def tokenize(text: str) -> List[str]:
    if not text:
        return []
    return [_stem(t) for t in (tok.lower() for tok in _TOKEN_RE.findall(text)) if t not in STOPWORDS]


def document_tokens(manifest: SkillManifest) -> List[str]:
    tokens: List[str] = []
    for field, text in manifest.search_text().items():
        tokens.extend(tokenize(text) * _FIELD_WEIGHTS.get(field, 1))
    return tokens


class Index:
    """Immutable BM25 index over a manifest list; rebuild when the catalog changes."""

    def __init__(self, manifests: Sequence[SkillManifest]) -> None:
        self.manifests = list(manifests)
        self.docs = [document_tokens(m) for m in self.manifests]
        self.term_freqs = [Counter(d) for d in self.docs]
        self.doc_sets = [set(d) for d in self.docs]
        self.doc_lengths = [len(d) for d in self.docs]
        self.avg_dl = sum(self.doc_lengths) / max(len(self.doc_lengths), 1)
        self.doc_freq: Dict[str, int] = dict(Counter(t for d in self.doc_sets for t in d))
        self.postings: Dict[str, List[int]] = {}
        for i, tokens in enumerate(self.doc_sets):
            for token in tokens:
                self.postings.setdefault(token, []).append(i)
        self.names_lower = [m.name.lower() for m in self.manifests]
        self.n_docs = len(self.docs)
        self.fingerprint = tuple((m.name, m.fingerprint) for m in self.manifests)

    def _idf(self, token: str) -> float:
        df = self.doc_freq.get(token, 0)
        return math.log(1 + (self.n_docs - df + 0.5) / (df + 0.5))

    def _score(self, query_tokens: List[str], doc_index: int) -> float:
        dl = self.doc_lengths[doc_index]
        tf_map = self.term_freqs[doc_index]
        score = 0.0
        for q in query_tokens:
            tf = tf_map.get(q, 0)
            if tf and self.doc_freq.get(q):
                score += self._idf(q) * tf * (K1 + 1) / (tf + K1 * (1 - B + B * dl / max(self.avg_dl, 1.0)))
        return score

    def search(self, query: str, limit: int = 12, *, exclude: Optional[set] = None) -> List[Candidate]:
        query_tokens = tokenize(query)
        if not query_tokens or not self.manifests or limit <= 0:
            return []
        exclude = exclude or set()
        max_df = max(1, int(self.n_docs * DISTINCTIVE_DF_SHARE))
        distinctive = {t for t in query_tokens if 0 < self.doc_freq.get(t, 0) <= max_df}
        q_lower = query.lower()
        candidate_ids = {i for token in distinctive for i in self.postings.get(token, ())}
        mentioned: set = set()
        for i, name in enumerate(self.names_lower):
            if name in q_lower and _name_mentioned(name, q_lower):
                candidate_ids.add(i)
                mentioned.add(i)
        scored: List[Tuple[float, int]] = []
        for i in candidate_ids:
            m = self.manifests[i]
            if m.name in exclude:
                continue
            s = self._score(query_tokens, i)
            if i in mentioned:
                s += 100.0  # a whole-word mention of the skill name always surfaces
            if s > 0:
                scored.append((s, i))
        if not scored:
            return []
        scored.sort(key=lambda p: (-p[0], self.manifests[p[1]].name))
        floor = scored[0][0] * RELATIVE_SCORE_FLOOR
        kept = [(s, i) for s, i in scored if s >= floor]
        return [Candidate(manifest=self.manifests[i], score=round(s, 4)) for s, i in kept[:limit]]


def _name_mentioned(name: str, text_lower: str) -> bool:
    """Whole-word mention of the skill name (``arxiv``, ``github-pr-workflow``) in the user text."""
    n = name.lower()
    if len(n) < 3:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])", text_lower) is not None


_SKILL_CONTEXT_RE = (
    r"(?:(?:use|using|load|with|via|run|apply|invoke|open)\s+(?:the\s+)?{name}\b"   # "use gmail-triage", "load the obsidian"
    r"|\b{name}\s+skill\b"                                                          # "obsidian skill"
    r"|(?<![\w/])/{name}\b"                                                          # "/obsidian"
    r"|`{name}`)"                                                                    # `obsidian`
)


def explicit_mentions(manifests: Sequence[SkillManifest], text: str) -> List[str]:
    """Skills the user *named as skills*. A bare word that happens to equal a skill name ("arXiv
    papers") is not a pin; a hyphenated or namespaced identifier (``gmail-triage``, ``pkg:skill``) is,
    and so is a name used in a skill-ish phrase ("use obsidian", "the obsidian skill", ``/obsidian``)."""
    lower = (text or "").lower()
    found: List[str] = []
    for m in manifests:
        n = m.name.lower()
        if len(n) < 3 or not _name_mentioned(n, lower):
            continue
        identifier_like = any(ch in n for ch in "-_:") and len(n) >= 6
        if identifier_like or re.search(_SKILL_CONTEXT_RE.format(name=re.escape(n)), lower):
            found.append(m.name)
    return found
