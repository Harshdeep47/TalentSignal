# Understanding the Problem

Before we look at a single line of code, we need to understand the job TalentSignal is trying to do and why that job is harder than it first appears. Every design decision later in this book is an answer to one of the difficulties described in this part.

## What TalentSignal is, in one paragraph

TalentSignal is a software system that helps a recruiter decide **which candidates to look at first** for a particular job. The recruiter gives it two things: a *job description* (the text an employer writes to describe a role) and a *candidate pool* (a file containing many candidate profiles - in the reference dataset, 100,000 of them). TalentSignal reads the job description, turns it into a list of requirements the recruiter can review and edit, then scores every candidate against those requirements and returns an **ordered list** - a *ranking* - with an explanation for every position.

Three words in that paragraph matter a great deal:

- **Decide** - TalentSignal does not hire anyone. It is a *decision-support* tool. A human makes the decision.
- **Ordered** - the output is a ranking, not a yes/no filter. Rank 1 is the candidate the system believes deserves attention first.
- **Explanation** - every score comes with the evidence that produced it, taken from the candidate's own record.

!!! note "Where this lives in the code"
    The whole system sits in the `TalentSignal/` folder. The ranking logic is a Python library in `engine/`, the web server is in `backend/app/`, and the user interface is in `frontend/src/`. You do not need to open any of them yet.

## A recruiter's day without a ranking system

Imagine Priya, a recruiter at a fast-growing product company. Her manager asks her to find a *Senior Search Engineer*. She posts the job, buys access to a candidate database, and is now looking at 100,000 profiles. If she spends just 30 seconds per profile, reading all of them takes

\[
100{,}000 \times 30 \text{ s} = 3{,}000{,}000 \text{ s} \approx 833 \text{ hours} \approx 21 \text{ working weeks.}
\]

That is obviously impossible. So in practice recruiters do one of three things:

1. **Read the first few hundred** profiles in whatever order the database returns them - which is effectively random with respect to fit.
2. **Search by keywords** such as "Elasticsearch" or "ranking" and read whatever matches.
3. **Use filters** such as "5-9 years of experience, located in Pune".

Each of these helps a little and fails in predictable ways. Understanding those failures is the best way to understand TalentSignal.

## Why keyword search is not enough

Keyword search answers the question *"does this text contain these words?"*. A ranking system needs to answer a different question: *"how strong is the evidence that this person can do this job?"*. Those two questions diverge in at least four ways.

### Failure 1: keywords can be added by anyone

A candidate profile is mostly *self-reported*: the candidate typed it. Nothing stops someone from listing "Elasticsearch, Pinecone, RAG, LoRA, Learning to Rank" as expert skills. A keyword search rewards this behaviour, which is called **keyword stuffing**.

The reference dataset contains this trap on purpose. In the 100,000 records, **4,179** candidates whose job title has nothing to do with machine learning (for example *Civil Engineer* or *Sales Executive*) list five or more core AI skills. A naive "count matching skills" ranker puts them at the top. TalentSignal's evaluation measured exactly this: a baseline that ranks by the number of job-relevant skills listed achieved a quality score of **0.006** out of 1, because its top 100 consisted almost entirely of non-technical people with stuffed skill lists (98 of the 100 had non-technical titles).

### Failure 2: the right people may not use the right words

The opposite problem is just as real. Consider this role description, taken from the reference dataset:

> *"Built systems that understand what users are looking for and connect them to the most relevant matches across a large dataset."*

That person built a search and matching system. Yet the sentence contains none of the words a keyword search for "search engine ranking retrieval" would use: no "search", no "ranking", no "retrieval". The job description the dataset was built around explicitly warns that such "plain-language" candidates exist and should be found.

To find them, a system must compare **meaning**, not spelling. That is what *semantic matching* means, and it is why TalentSignal uses an embedding model (explained in Part 6).

### Failure 3: the same word means different things in different places

"Python" in the skills list of a data scientist and "Python" in the skills list of an accountant who once automated a spreadsheet are the same word. They are not the same evidence. Context - especially the person's actual job titles - changes how much a claim should be believed.

TalentSignal encodes this idea directly: evidence found in a role's description is **trusted in proportion to how relevant that role's job title is** to the position. Part 6 shows the formula.

### Failure 4: keyword matches ignore whether a person is available

The job description behind the reference dataset says it plainly: a perfect-on-paper candidate who has not logged in for six months and replies to 5% of recruiter messages is, for hiring purposes, not available. Keyword search knows nothing about behaviour. TalentSignal uses behavioural signals - last activity, response rate, interview attendance - as one component of the score.

## Why many matching keywords is not the same as the best candidate

Let us make the point concrete with three people applying for the Senior Search Engineer role. (These are the same three hypothetical candidates used in the full worked example of Part 7, where every number is produced by the real engine.)

| Candidate | Current title | What their profile says | Keyword matches |
|---|---|---|---|
| **Asha** | Search Engineer | Built a learning-to-rank search system in production; Elasticsearch skill verified by a platform assessment (84/100) | Many |
| **Ravi** | Sales Executive | Sells cloud software; lists seven search and ranking skills, all "expert" | The most |
| **Meera** | Senior Software Engineer | Describes rebuilding "which listings each shopper sees first" - search ranking in plain language - but lists only Python and Java | Few |

A keyword ranker orders them Ravi, Asha, Meera. A thoughtful recruiter orders them Asha, then probably Meera, and treats Ravi with suspicion. Part 7 shows how TalentSignal orders them, and - importantly - where it agrees with the recruiter and where it does not.

## What "ranking" actually means

A **ranking** is an ordering of items by estimated relevance to a need. Web search, product search, music recommendations and candidate shortlists are all rankings. Three properties make ranking different from classification:

1. **Only the order matters at the top.** Nobody reads rank 9,000. A ranking that gets the first 10 right and the rest wrong is far more useful than one that is mediocre everywhere. This is why ranking quality is measured with metrics such as *NDCG@10* that weight the top positions heavily (Part 6 and Book 3 explain NDCG from scratch).
2. **Scores are relative.** A score of 0.82 means "more relevant than 0.71 for this job", not "82% chance of being hired". TalentSignal deliberately uses absolute, interpretable scales for most components, but the overall score is still an evidence summary, **not a probability**.
3. **Ties must be broken deterministically.** If two candidates have identical scores, the system must still put one first, and it must do so the same way every time. TalentSignal breaks ties by mandatory-requirement coverage, then engagement, then candidate ID.

## What "understanding a job description" means

A job description is written for humans. It mixes requirements with marketing, history and logistics. Consider these sentences from the reference job description:

- *"Production experience with embeddings-based retrieval systems ... deployed to real users."* - a **must-have** requirement.
- *"LLM fine-tuning experience (LoRA, QLoRA, PEFT)"* under the heading *"Things we'd like you to have but won't reject you for"* - a **nice-to-have**.
- *"People who have only worked at consulting firms ... in their entire career."* - a **declared exclusion**.
- *"We work async-first and write a lot."* - culture, not something a profile can evidence.
- The closing note mentions "Pinecone" and "RAG" only as *examples of a trap* - mentioning them must **not** create a requirement.

"Understanding" the JD therefore means turning that text into a structured object - which requirements, how important, which conditions, what experience band, which locations - and doing it in a way the recruiter can check. TalentSignal's parser records, for every extracted item, **the sentence it came from**, so the recruiter can verify it. Part 5 walks through the whole process.

## Search engine, ATS, recommender, candidate intelligence platform

People often confuse these four kinds of system. The table compares them.

| | Search engine | Applicant Tracking System (ATS) | Recommendation system | Candidate intelligence platform (TalentSignal) |
|---|---|---|---|---|
| Main question | Which documents match my query? | Where is each applicant in our hiring process? | What might this user like next? | Who should I look at first for this job, and why? |
| Input | A short query | Applications to posted jobs | A user's history of clicks/purchases | A job description and a candidate pool |
| Output | Matching documents | Pipeline stages, schedules, emails | Suggested items | An explained, filterable ranking |
| Core technique | Lexical matching (e.g. BM25) | Workflow / database software | Learned models from behaviour data | Evidence aggregation over skills, history, meaning, signals |
| Explains decisions? | Rarely | Not applicable | Rarely | Yes - evidence for every requirement |

TalentSignal deliberately does **not** implement ATS features such as interview scheduling, job posting or email pipelines. It borrows *techniques* from search (BM25) and from recommendation and semantic search (embeddings), but its purpose is decision support for one hiring decision at a time.

## The five difficulties, and where this book answers them

| Difficulty | Answered in |
|---|---|
| The JD means more than it says | Part 5 - Job description intelligence |
| Profiles are self-reported and can be stuffed | Part 6 - bounded skill evidence, title trust, credibility |
| Right people use different words | Part 6 - semantic embeddings |
| Availability and logistics matter | Part 6 - engagement and logistics components |
| Some records are impossible or incomplete | Part 4 (data) and Part 8 (integrity) |

!!! tip "How to read the rest of this book"
    Part 2 gives you the map of the whole system. Part 3 teaches just enough programming to read the code. Parts 4-8 are the heart of the book: data, job understanding, ranking, a full worked example, and explanations. Parts 9-11 cover performance, responsibility and a complete walkthrough. If you already program, skim Part 3.
