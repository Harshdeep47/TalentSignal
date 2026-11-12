# Mathematical and Logical Problem Solving

Work each problem on paper before reading the solution. All numbers are verified (the formulas are the ones in the code; results were computed with the project's own functions or reproduced exactly).

## Problem 1 - weighted ranking score

Default weights: requirements 0.34, role_fit 0.20, semantic 0.12, lexical 0.05, experience 0.10, engagement 0.11, logistics 0.08. Candidate X has components (0.80, 1.00, 0.60, 0.90, 0.85, 0.40, 0.70) in that order; candidate Y has (0.70, 0.80, 0.50, 0.70, 1.00, 0.95, 1.00). No policy factors apply. Who ranks first?

**Solution.**

\[
X = 0.34(0.80) + 0.20(1.00) + 0.12(0.60) + 0.05(0.90) + 0.10(0.85) + 0.11(0.40) + 0.08(0.70) = 0.774
\]
\[
Y = 0.34(0.70) + 0.20(0.80) + 0.12(0.50) + 0.05(0.70) + 0.10(1.00) + 0.11(0.95) + 0.08(1.00) = 0.7775
\]

Y ranks first by 0.0035 - X has the stronger evidence, Y the better availability.

## Problem 2 - effect of changing a weight

The recruiter raises engagement from 0.11 to 0.25 (others unchanged). Recompute.

**Solution.** The weights now sum to 1.14 and are normalised by dividing by 1.14. \(X = 0.830 / 1.14 = 0.728\); \(Y = 0.9105 / 1.14 = 0.799\). The gap widens from 0.0035 to 0.071. *Lesson:* because weights are normalised, raising one weight also lowers every other component's share - requirements fall from 34% to 29.8% of the score.

## Problem 3 - cosine similarity

Compute the cosine similarity of \(u = (1, 2, 2)\) and \(v = (2, 1, 2)\), then its calibrated value with the requirement window [0.62, 0.80].

**Solution.** \(u \cdot v = 2 + 2 + 4 = 8\); \(\lVert u \rVert = \lVert v \rVert = 3\); cosine = \(8/9 = 0.889\). Calibrated: \(\mathrm{clip}((0.889 - 0.62)/0.18, 0, 1) = \mathrm{clip}(1.49) = 1\).

## Problem 4 - precision and recall

A shortlist of 10 contains 6 relevant candidates; the pool contains 8 relevant candidates in total. Compute precision@10 and recall.

**Solution.** Precision@10 = 6/10 = 0.6; recall = 6/8 = 0.75. To raise recall to 1 you must include the 2 missing relevant candidates - possibly at the cost of precision.

## Problem 5 - NDCG@5 step by step

Ranked labels: [3, 2, 0, 1, 3]. Pool labels: [3, 3, 2, 1, 0, 0]. Gain \(2^{rel} - 1\), discount \(\log_2(i + 1)\).

| Position i | label | gain | \(\log_2(i+1)\) | contribution |
|---|---|---|---|---|
| 1 | 3 | 7 | 1.000 | 7.000 |
| 2 | 2 | 3 | 1.585 | 1.893 |
| 3 | 0 | 0 | 2.000 | 0.000 |
| 4 | 1 | 1 | 2.322 | 0.431 |
| 5 | 3 | 7 | 2.585 | 2.708 |
| | | | **DCG@5** | **12.031** |

Ideal order of the pool: [3, 3, 2, 1, 0] → \(7 + 7/1.585 + 3/2 + 1/2.322 + 0 = 13.347\). **NDCG@5 = 12.031 / 13.347 = 0.901.** The loss comes from the second "3" sitting at position 5 instead of 2.

```python
# runnable
import math
def dcg(rels, k):
    return sum((2 ** r - 1) / math.log2(i + 2) for i, r in enumerate(rels[:k]))
ranked, pool = [3, 2, 0, 1, 3], [3, 3, 2, 1, 0, 0]
ndcg5 = dcg(ranked, 5) / dcg(sorted(pool, reverse=True), 5)
assert round(ndcg5, 3) == 0.901
```

## Problem 6 - average precision

Same ranking; "relevant" means label ≥ 3. Compute AP@5.

**Solution.** Relevant at positions 1 and 5. Precision@1 = 1/1, precision@5 = 2/5. There are 2 relevant items in the pool, so \(\mathrm{AP@5} = (1 + 0.4)/2 = 0.7\).

## Problem 7 - compare two skill claims

Candidate P lists "FAISS, expert, 0 months". Candidate Q lists "FAISS, advanced, 48 months, assessed 84". Both have fully relevant titles (credibility 1). Which has stronger skill evidence?

**Solution.** P: \(c = 1.0 \times 0.35 = 0.35\). Q: \(u = 1 - e^{-48/18} = 0.9305\), \(c = 0.75 (0.35 + 0.65 \cdot 0.9305) = 0.7161\), blended with the assessment: \(0.5(0.7161) + 0.5(0.84) = 0.7781\). Q's evidence is more than twice P's. (P would also trigger an integrity warning - and a critical finding if two or more expert skills had zero months.)

## Problem 8 - detect a skill-stuffing profile

A "Sales Executive" lists seven search skills, each "expert, 60 months". No role has a relevant title. What is his skill evidence per requirement, and what flag appears?

**Solution.** Each skill's strength is \(0.35 + 0.65(1 - e^{-60/18}) = 0.9768\). Credibility is \(0.5 + 0.5 \times 0 = 0.5\), so skill evidence is \(0.488\) per requirement - and because each requirement takes the *maximum*, seven skills count no more than one. With four or more job skills claimed at strength ≥ 0.5 and no role of relevance ≥ 0.3, the warning `uncorroborated_skill_claims` appears. (This is exactly Ravi in Book 1, Part 7.)

## Problem 9 - why is a candidate ranked incorrectly?

In Book 1's worked example, Meera (plain-language search work, title "Senior Software Engineer") ranks below Ravi (stuffer). Using the component table (requirements 0.222 vs 0.484; role_fit 0.35 vs 0; semantic 0 vs 0; lexical 0.333 vs 1.0; experience 0.99 vs 0.64; engagement 0.655 vs 0.908; logistics 0.674 vs 0.875), identify the three largest weighted differences.

**Solution.** Weighted differences (Meera − Ravi): requirements \(0.34 \times (0.222 - 0.484) = -0.089\); role_fit \(+0.070\); lexical \(0.05 \times (-0.667) = -0.033\); experience \(+0.035\); engagement \(0.11 \times (-0.253) = -0.028\); logistics \(0.08 \times (-0.201) = -0.016\). The largest are requirements (−0.089), role fit (+0.070) and experience (+0.035), followed closely by lexical (−0.033). Root cause: the generic title lowers her description trust (0.545), so plain-language evidence counts little, while Ravi's halved skill evidence still covers every requirement.

## Problem 10 - a data-quality issue

18,865 of 100,000 records have `expected_salary_range_inr_lpa.min > max`. Should the ranking use salary? What should the system do?

**Solution.** Not as a ranking signal: salary is a negotiation matter, and 18.9% of the values are internally inconsistent. TalentSignal records an *info* finding (`salary_range_inverted`), shows it, and does not use salary in any score. The general lesson: check a field's consistency rate before trusting it as a feature.

## Problem 11 - missing-aware mean

Engagement sub-signals for a candidate: recency 0.42 (w 0.25), response 0.50 (0.25), speed 0.80 (0.10), open 1.0 (0.15), interviews 0.90 (0.15), offers *missing* (0.05), interest 0.55 (0.05). Compute engagement. What would a "missing = 0" implementation give?

**Solution.** Available weights sum to 0.95. Numerator: \(0.105 + 0.125 + 0.08 + 0.15 + 0.135 + 0.0275 = 0.6225\). Engagement = 0.6225 / 0.95 = **0.655**. Treating missing as 0 would give 0.6225 / 1.00 = 0.6225 - a penalty of 0.033 for having no prior offers.
