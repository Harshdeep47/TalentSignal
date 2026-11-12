# Coding and Data-Structure Problems

These problems are modelled on real engineering problems inside TalentSignal. Each gives the problem, the brute-force idea, an optimised approach, Python code (executed with assertions when this book is built), complexity and edge cases. Try them before reading the code.

## Problem 1 - Duplicate profiles with a hash map

**Problem.** Given candidate records, report every record whose content (ignoring `candidate_id` and name) is identical to an earlier one, as `(duplicate_id, original_id)`.

**Brute force.** Compare every pair: \(O(n^2)\) comparisons of whole records - 5 × 10⁹ for 100,000.

**Optimised.** Serialise each record canonically (sorted keys) without the ignored fields, hash it, and keep a dictionary `hash → first id`. This is what `build_index` does with BLAKE2b.

```python
# runnable
import hashlib, json

def find_duplicates(records):
    first_by_hash, dups = {}, []
    for rec in records:
        content = {k: v for k, v in rec.items() if k not in ("candidate_id", "name")}
        key = hashlib.blake2b(json.dumps(content, sort_keys=True).encode(), digest_size=12).hexdigest()
        if key in first_by_hash:
            dups.append((rec["candidate_id"], first_by_hash[key]))
        else:
            first_by_hash[key] = rec["candidate_id"]
    return dups

recs = [{"candidate_id": "A", "name": "x", "skills": ["Python"]},
        {"candidate_id": "B", "name": "y", "skills": ["Python"]},
        {"candidate_id": "C", "name": "z", "skills": ["Java"]}]
assert find_duplicates(recs) == [("B", "A")]
```

**Complexity.** \(O(n \cdot s)\) time for total serialised size \(s\); \(O(n)\) memory. **Edge cases.** Key order (solved by `sort_keys`); floats such as 1.0 vs 1 (normalise first); hash collisions (negligible with 96-bit digests, but a production system could confirm by comparing content).

## Problem 2 - Deterministic sorting with tie-breaks

**Problem.** Sort candidates by eligible first, score descending, mandatory coverage descending, engagement descending, then id ascending.

**Approach.** A tuple sort key, negating the "descending" numeric fields. Python's sort is stable and compares tuples left to right.

```python
# runnable
def order(cands):
    return sorted(cands, key=lambda c: (not c["eligible"], -c["overall"], -c["mandatory"], -c["engagement"], c["id"]))

cands = [
    {"id": "C3", "eligible": True, "overall": 0.80, "mandatory": 0.9, "engagement": 0.5},
    {"id": "C1", "eligible": True, "overall": 0.80, "mandatory": 0.9, "engagement": 0.5},
    {"id": "C2", "eligible": True, "overall": 0.80, "mandatory": 0.95, "engagement": 0.1},
    {"id": "C0", "eligible": False, "overall": 0.99, "mandatory": 1.0, "engagement": 1.0},
]
assert [c["id"] for c in order(cands)] == ["C2", "C1", "C3", "C0"]
```

**Complexity.** \(O(n \log n)\). **Edge cases.** NaN scores break comparisons (Python treats NaN as unordered) - replace them first; held candidates must stay last even with high scores.

## Problem 3 - Top-K with a heap

**Problem.** Return the K best candidates from a stream of `(score, id)` pairs without sorting everything.

**Brute force.** Collect all, sort, take K: \(O(n \log n)\) time, \(O(n)\) memory.

**Optimised.** Keep a *min-heap* of size K holding the best K seen so far; replace its smallest element when a better one arrives. Ties: prefer the smaller id, so the heap key must make larger ids "smaller" - here we push `(score, negated id order)`.

```python
# runnable
import heapq

def top_k(stream, k):
    heap = []  # min-heap of (score, inverted id) - the root is the worst of the current top K
    for score, cid in stream:
        item = (score, [-ord(ch) for ch in cid])   # smaller id = larger key for ties
        if len(heap) < k:
            heapq.heappush(heap, (item, cid))
        elif item > heap[0][0]:
            heapq.heapreplace(heap, (item, cid))
    return [cid for _, cid in sorted(heap, reverse=True)]

stream = [(0.7, "C5"), (0.9, "C2"), (0.9, "C1"), (0.3, "C4"), (0.8, "C3")]
assert top_k(stream, 3) == ["C1", "C2", "C3"]
```

**Complexity.** \(O(n \log k)\) time, \(O(k)\) memory. **Connection.** TalentSignal sorts all candidates because it must rank everyone for "all eligible" runs and the held list; a heap (or `np.argpartition`) is the right tool when only K are needed from a very large pool (Book 2, Exercise 4.3).

## Problem 4 - Best evidence per group

**Problem.** Given skill rows `(candidate, strength)`, return each candidate's maximum strength and the index of the row that achieved it - in vectorised NumPy.

```python
# runnable
import numpy as np

def best_per_group(group, values, n):
    best = np.zeros(n); arg = np.full(n, -1)
    order = np.lexsort((-values, group))          # by group, then value descending
    g = group[order]
    first = np.ones(len(g), bool); first[1:] = g[1:] != g[:-1]
    sel = order[first]
    best[group[sel]] = values[sel]; arg[group[sel]] = sel
    return best, arg

group = np.array([0, 0, 2, 2, 2]); vals = np.array([0.1, 0.5, 0.3, 0.9, 0.2])
best, arg = best_per_group(group, vals, 4)
assert best.tolist() == [0.5, 0.0, 0.9, 0.0] and arg.tolist() == [1, -1, 3, -1]
```

**Brute force alternative.** A dictionary loop - correct but ~100× slower on a million rows in Python. **Complexity.** \(O(m \log m)\). **Edge cases.** Empty input (TalentSignal returns early); candidates with no rows keep 0 and −1.

## Problem 5 - Whole-word phrase matching

**Problem.** Report which requirement phrases appear in a description as whole words, case-insensitively. "rag" must not match "storage"; "a/b test" must match.

```python
# runnable
import re

def phrase_hits(text, phrases):
    low = text.lower()
    terms = sorted({p.lower() for p in phrases}, key=len, reverse=True)
    pat = re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(t) for t in terms) + r")(?![a-z0-9])")
    return sorted({m.group(0) for m in pat.finditer(low)})

desc = "Built RAG pipelines on object storage; ran an A/B test and NDCG evaluation."
assert phrase_hits(desc, ["rag", "a/b test", "ndcg", "java"]) == ["a/b test", "ndcg", "rag"]
assert phrase_hits("cloud storage engineer", ["rag"]) == []
assert phrase_hits("ran A/B tests weekly", ["a/b test"]) == []      # plural is NOT matched
```

!!! caution "A real limitation this exposes"
    Whole-word matching does not handle plurals or other word forms: "a/b test" does not match "A/B tests". TalentSignal's taxonomy compensates by listing common variants ("a/b test", "a/b testing"), and embedding similarity catches many paraphrases - but a stemmer or lemmatiser would be a more general fix. This was found while verifying this very example.

**Why `re.escape`.** Phrases such as "c++" or "a/b test" contain regex symbols. **Why longest first.** In an alternation the first match wins; "learning to rank" should win over "learning". **Complexity.** Linear in text length per scan; compile the pattern once per requirement, not per text.

## Problem 6 - Streaming JSONL with error reporting

**Problem.** Read candidates line by line; skip blank lines; report malformed lines with their line numbers; never load the whole file.

```python
# runnable
import io, json

def iter_records(fh):
    for line_no, line in enumerate(fh, start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            yield line_no, None, f"Invalid JSON: {exc.msg}"
            continue
        if not isinstance(obj, dict):
            yield line_no, None, "Each line must be a JSON object."
            continue
        yield line_no, obj, None

data = io.StringIO('{"candidate_id": "A"}\n\n{bad}\n[1, 2]\n{"candidate_id": "B"}\n')
rows = list(iter_records(data))
assert [(r[0], r[1] is not None) for r in rows] == [(1, True), (3, False), (4, False), (5, True)]
```

**Complexity.** \(O(\text{file size})\) time, \(O(\text{longest line})\) memory. **Edge cases.** A UTF-8 byte-order mark at the start; Windows line endings; a final line without a newline - all handled by line iteration and the JSON parser.

## Problem 7 - Missing-aware weighted mean

**Problem.** Combine sub-scores with weights where some values are missing (`None`), so missing values neither help nor hurt; return 0.5 when nothing is available.

```python
# runnable
def weighted_available(parts, weights):
    num = sum(weights[k] * v for k, v in parts.items() if v is not None)
    den = sum(weights[k] for k, v in parts.items() if v is not None)
    return num / den if den > 0 else 0.5

w = {"recency": 0.25, "response": 0.25, "offers": 0.05}
assert weighted_available({"recency": 0.8, "response": 0.6, "offers": None}, w) == 0.7
assert weighted_available({"recency": None, "response": None, "offers": None}, w) == 0.5
```

**Edge cases.** All missing; weights that sum to zero; NaN versus None (the NumPy version in TalentSignal uses NaN and `~np.isnan`).

## Problem 8 - An LRU cache

**Problem.** Cache the most recently used *capacity* scored pools; evict the least recently used. (`RunService` keeps 2 pools and 6 result tables this way.)

```python
# runnable
from collections import OrderedDict

class LRU:
    def __init__(self, capacity):
        self.capacity, self.items = capacity, OrderedDict()
    def get(self, key):
        if key not in self.items:
            return None
        self.items.move_to_end(key)
        return self.items[key]
    def put(self, key, value):
        self.items[key] = value
        self.items.move_to_end(key)
        while len(self.items) > self.capacity:
            self.items.popitem(last=False)

c = LRU(2); c.put("a", 1); c.put("b", 2); c.get("a"); c.put("c", 3)
assert list(c.items) == ["a", "c"]
```

**Complexity.** \(O(1)\) per operation. **Edge cases.** Thread safety - TalentSignal's `_LRU` adds a lock because job threads and request threads use it concurrently.

## Problem 9 - Pagination with filters

**Problem.** Given rows, a filter and a sort key, return page `p` of size `s` plus the total count; clamp invalid inputs.

```python
# runnable
def paginate(rows, page=1, page_size=50, predicate=None, key=None):
    page_size = max(1, min(page_size, 200))
    page = max(1, page)
    filtered = [r for r in rows if predicate is None or predicate(r)]
    if key is not None:
        filtered.sort(key=key)
    start = (page - 1) * page_size
    return {"total": len(filtered), "page": page, "page_size": page_size,
            "items": filtered[start:start + page_size]}

rows = [{"id": i, "country": "India" if i % 2 else "UK"} for i in range(1, 11)]
res = paginate(rows, page=2, page_size=2, predicate=lambda r: r["country"] == "India", key=lambda r: r["id"])
assert res["total"] == 5 and [r["id"] for r in res["items"]] == [5, 7]
assert paginate(rows, page=0, page_size=1000)["page_size"] == 200
```

**Complexity.** \(O(n)\) filter plus \(O(n \log n)\) sort per request; acceptable at 100,000 rows in pandas (150-270 ms). For much larger tables, pre-sorted indexes or a database with keyset pagination ("rows after id X") avoid re-sorting.

## Problem 10 - Percentile with ties

**Problem.** Convert raw scores to percentiles among positive scores, giving ties the same (highest) percentile and non-positive scores 0.

```python
# runnable
def percentile_positive(xs):
    pos = sorted(x for x in xs if x > 0)
    n = len(pos)
    def pct(x):
        if x <= 0:
            return 0.0
        # number of positive values <= x  ("max" tie method)
        lo, hi = 0, n
        while lo < hi:
            mid = (lo + hi) // 2
            if pos[mid] <= x:
                lo = mid + 1
            else:
                hi = mid
        return lo / n
    return [pct(x) for x in xs]

assert percentile_positive([0, 1.5, 0.5, 1.5]) == [0.0, 1.0, 1 / 3, 1.0]
```

**Why it matters.** The first TalentSignal version used `argsort().argsort()`, which gives tied values different ranks; identical profiles then scored differently. **Complexity.** \(O(n \log n)\) (sort plus binary searches).
