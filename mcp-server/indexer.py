"""Chunking + BM25 full-text index for the billing guide.

Chunking: one chunk per `###` subsection (e.g. "4.2 Extra data charges"). Subsections
are short and self-contained, so a chunk is exactly what we want to return as an
excerpt together with its section number. Headings are also indexed (counted twice)
because they carry most of the meaning ("Late payment fee", "Partial payments").

Ranking: classic Okapi BM25 (k1=1.5, b=0.75) over lower-cased, lightly stemmed tokens.
A small synonym table expands the *query* so that everyday words such as "extra
internet cost" also match the guide's wording ("additional data ... charge").

Build once:   python indexer.py            -> writes index.json
The MCP server loads index.json at start-up; nothing is re-indexed per question.
"""
from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

HERE = Path(__file__).parent
DEFAULT_DOC = HERE / "docs" / "Mobile_Provider_Billing_Guide.md"
DEFAULT_INDEX = HERE / "index.json"

K1 = 1.5
B = 0.75

STOPWORDS = set(
    """a an and are as at be by can do does for from has have how i if in is it its my
    of on or so that the their them then there this to was what when where which who why
    will with you your me much any not no our than per""".split()
)

SYNONYMS = {
    "internet": ["data"],
    "data": ["internet"],
    "gb": ["data"],
    "cost": ["price", "charge", "fee"],
    "price": ["charge", "cost"],
    "charge": ["price", "cost", "fee"],
    "pay": ["payment"],
    "extra": ["additional"],
    "additional": ["extra"],
    "late": ["overdue"],
    "overdue": ["late"],
    "minute": ["phone"],
    "call": ["phone", "minute"],
    "phone": ["minute"],
    "high": ["higher", "extra"],
    "installment": ["partial"],
    "part": ["partial"],
    "complain": ["dispute"],
    "wrong": ["dispute"],
    "deadline": ["due"],
}


def stem(tok: str) -> str:
    # deliberately tiny suffix stripper; enough for an English policy document
    for suf in ("ies", "ing", "ed", "es", "s"):
        if tok.endswith(suf) and len(tok) - len(suf) >= 3:
            if suf == "ies":
                return tok[:-3] + "y"
            return tok[: -len(suf)]
    return tok


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text.lower().replace(",", ""))
    return [stem(w) for w in words if w not in STOPWORDS]


@dataclass
class Chunk:
    id: str           # "4.2"
    title: str        # "Extra data charges"
    parent: str       # "4. Internet (Mobile Data) Allowance and Pricing"
    text: str
    tokens: list[str]

    @property
    def reference(self) -> str:
        return f"Section {self.id} – {self.title}"


def chunk_markdown(md: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    parent = ""
    cur_id = cur_title = None
    buf: list[str] = []

    def flush():
        if cur_id is None:
            return
        body = "\n".join(buf).strip()
        tokens = tokenize(cur_title) * 2 + tokenize(parent) + tokenize(body)
        chunks.append(Chunk(cur_id, cur_title, parent, body, tokens))

    for line in md.splitlines():
        if m := re.match(r"^##\s+(\d+)\.\s+(.*)", line):
            flush()
            cur_id = None
            buf = []
            parent = f"{m.group(1)}. {m.group(2).strip()}"
        elif m := re.match(r"^###\s+(\d+\.\d+)\s+(.*)", line):
            flush()
            cur_id, cur_title, buf = m.group(1), m.group(2).strip(), []
        elif cur_id is not None:
            buf.append(line)
    flush()
    return chunks


class BM25Index:
    def __init__(self, chunks: list[Chunk], source: str = ""):
        self.chunks = chunks
        self.source = source
        self.n = len(chunks)
        self.avgdl = sum(len(c.tokens) for c in chunks) / max(self.n, 1)
        self.tf = [Counter(c.tokens) for c in chunks]
        df: Counter = Counter()
        for c in chunks:
            df.update(set(c.tokens))
        self.idf = {t: math.log(1 + (self.n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    # --- persistence -----------------------------------------------------
    def save(self, path: Path) -> None:
        data = {"source": self.source, "algorithm": "bm25", "k1": K1, "b": B,
                "chunks": [asdict(c) for c in self.chunks]}
        path.write_text(json.dumps(data, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "BM25Index":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls([Chunk(**c) for c in data["chunks"]], data.get("source", ""))

    @classmethod
    def from_markdown(cls, path: Path) -> "BM25Index":
        return cls(chunk_markdown(path.read_text(encoding="utf-8")), path.name)

    # --- search -------------------------------------------------------------
    @staticmethod
    def expand(query: str) -> dict[str, float]:
        """query term -> weight. Original terms weigh 1.0, synonyms 0.5."""
        weights: dict[str, float] = {}
        for t in tokenize(query):
            weights[t] = max(weights.get(t, 0), 1.0)
            for syn in SYNONYMS.get(t, []):
                s = stem(syn)
                weights[s] = max(weights.get(s, 0), 0.5)
        return weights

    def search(self, query: str, top_k: int = 3) -> list[tuple[Chunk, float]]:
        q = self.expand(query)
        scored = []
        for i, c in enumerate(self.chunks):
            dl = len(c.tokens)
            score = 0.0
            for term, w in q.items():
                f = self.tf[i].get(term)
                if not f:
                    continue
                score += w * self.idf[term] * f * (K1 + 1) / (f + K1 * (1 - B + B * dl / self.avgdl))
            if score > 0:
                scored.append((c, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


def load_or_build(index_path: Path = DEFAULT_INDEX, doc_path: Path = DEFAULT_DOC) -> BM25Index:
    if index_path.exists() and index_path.stat().st_mtime >= doc_path.stat().st_mtime:
        return BM25Index.load(index_path)
    idx = BM25Index.from_markdown(doc_path)
    idx.save(index_path)
    return idx


if __name__ == "__main__":
    doc = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DOC
    idx = BM25Index.from_markdown(doc)
    idx.save(DEFAULT_INDEX)
    print(f"Indexed {idx.n} chunks from {doc.name} -> {DEFAULT_INDEX.name} (avg {idx.avgdl:.0f} tokens/chunk)")
