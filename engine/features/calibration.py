"""Calibration constants, kept in one place so they are easy to audit.

Semantic similarity
-------------------
Raw cosine similarities from bge-small-en-v1.5 are not probabilities and do
not start at 0 for unrelated text: two unrelated English sentences typically
score around 0.4-0.5. We therefore map cosine ``c`` linearly onto [0, 1]:

    s = clip((c - SEM_LO) / (SEM_HI - SEM_LO), 0, 1)

The constants were set empirically with ``scripts/calibrate_semantic.py`` on
the reference index (5,802 unique segments, 44 distinct role descriptions).
Across nine concepts, unrelated descriptions scored 0.41-0.55 (accounting vs.
"embeddings retrieval": 0.415) and clearly matching ones 0.75-0.85 (a semantic
search description vs. "embeddings retrieval": 0.831); the overall p50 was
0.583 and p90 0.716. SEM_LO = 0.62 suppresses generic same-domain similarity
and SEM_HI = 0.80 is reached only by explicit matches. Re-run the script when
changing the embedding model.

Text-evidence trust
-------------------
Evidence found in a role description is weighted by how relevant that role's
*title* is to the job: ``trust = TRUST_FLOOR + (1 - TRUST_FLOOR) * relevance``.
The principle -- claims are more credible when the job title is consistent
with them -- generalises beyond this dataset; in the reference dataset it also
neutralises descriptions that are shuffled across unrelated titles.
"""

SEM_LO = 0.62
SEM_HI = 0.80

TRUST_FLOOR = 0.3

# Phrase hits are binary and can be passing mentions, so on their own they
# count as strong-but-not-complete evidence.
PHRASE_HIT_STRENGTH = 0.75

# Self-description (headline / summary) is a claim, not a record of work.
SELF_DESCRIPTION_WEIGHT = 0.6

# Recency: evidence from a role that ended m months ago keeps
# 0.5 + 0.5 * exp(-m / RECENCY_MONTHS) of its value.
RECENCY_MONTHS = 48.0

# Skill evidence: usage saturates with months of use.
SKILL_USAGE_MONTHS = 18.0
# Weight of a platform assessment versus the self-reported claim.
ASSESSMENT_WEIGHT = 0.5
# Skill claims are discounted when no role in the career is related to the
# job: credibility = SKILL_CREDIBILITY_FLOOR + (1 - floor) * max_role_relevance.
SKILL_CREDIBILITY_FLOOR = 0.5

# Per-query calibration for the free-form JD "focus" text (holistic semantic
# component). Long query texts have a different similarity scale from the
# one-sentence requirement prototypes above, so their window is set relative
# to the query's median similarity to these unrelated anchors:
#     lo = median(anchor sims) + ADAPTIVE_MARGIN,  hi = lo + ADAPTIVE_WIDTH
ADAPTIVE_MARGIN = 0.08
ADAPTIVE_WIDTH = 0.18
ANCHOR_TEXTS = (
    "Managed enterprise sales accounts and quarterly revenue targets.",
    "Handled month-end accounting close and financial reporting.",
    "Led customer support operations for a consumer product.",
    "Designed mechanical components and production tooling.",
    "Planned civil construction projects and site safety.",
    "Created brand identity and marketing campaigns.",
    "Recruited and onboarded employees as an HR generalist.",
    "Wrote articles and SEO content for a publication.",
    "Built responsive web pages with React and CSS.",
    "Maintained cloud infrastructure and CI/CD pipelines.",
    "Ran warehouse logistics and supply chain operations.",
    "Taught mathematics to high-school students.",
)
