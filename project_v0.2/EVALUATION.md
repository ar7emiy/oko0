# How we grade the firm's entity extraction

The firm uses GenAI that reads claim notes and pulls out the people and companies mentioned, along with details about them: addresses, phone numbers and tax IDs (TINs). The firm also checks those names against a watchlist. This document explains how we find out how often it gets these right.

## What we want to know

1. **Does it find the people and companies in the notes?**
2. **Does it report their details correctly?** Addresses, phone numbers, TINs.
3. **Does it attach each detail to the right person or company?**
4. **Does it put each one in the right category?** For example medical provider, legal, or claimant.
5. **When it flags a watchlist match, is it really the same person or company?**

## How the grading works

Grading a test needs an answer key. Ours is built by subject-matter experts (SMEs):

1. An SME reads every note on a claim.
2. They record every person and company the notes mention, and every detail the notes state about them.
3. For each one, they mark exactly where in the note it appears, so anyone can check it later.

That record is the **answer key**. Data scientists call it the *gold data*. We compare the firm's output for the same claim against it, one item at a time.

**One step connects the two: pairing.** The firm's GenAI tool and the SME don't always write a name the same way, for example "Dr. Monroe" and "Dr. Ada Monroe". So when an SME finishes a claim, they go through the firm's output row by row and say which person or company on their list each row is, or that it isn't in the notes at all. It takes one decision per row. Most of the scores below depend on it.

## The proposed SME workflow

This proposal gives the SME one focused job at a time. The firm’s output stays hidden until the SME's answer key is complete.

1. The SME reads each note and records only what it says: people and companies, later references, descriptions, actions and details. Each record keeps the exact words and where they came from.
2. A custom Copilot agent can optionally prepare suggested records from the note. The SME checks, corrects, accepts or dismisses each suggestion. The workflow works just as well when there are no AI suggestions.
3. After every note in a claim is complete, the SME sees one claim-level evidence card for each person or company. It gathers the evidence already recorded across all of that claim's notes. The SME can open any quote in its original note if they need context.
4. The SME reviews the complete evidence card and assigns a broad claim role, or chooses **insufficient evidence** or **conflicting evidence**. They identify the records that support, conflict with or merely repeat the conclusion. A short reason is recorded. This review is finished and frozen before the firm's output appears.
5. Only then does the SME pair the firm's rows and review its watchlist flags. The scores compare the firm with the frozen answer key.

This sequence reduces rework: the SME does not have to make a category decision from one isolated sentence, and they do not need to re-read every note to compare the firm's output later.

## The scores

Every score is a simple fraction. Each one comes with a small made-up example.

### 1. Found rate and right rate: does it find the people and companies?

- **Found rate** = people and companies both the firm and the SME found ÷ everyone the SME found
- **Right rate** = firm rows that match someone on the SME's list ÷ all firm rows

Example: an SME finds 10 people and companies on a claim. The firm's output lists 8. Seven of them are on the SME's list; one isn't in the notes at all.

- Found rate = 7 ÷ 10 = **70%**, so it missed 3.
- Right rate = 7 ÷ 8 = **88%**, so 1 of its 8 was wrong.

You need both. A tool that listed every name in the phone book would find everyone, and be mostly wrong. These metrics are also known as *recall* and *precision*.

### 2. Detail accuracy: does it report the details correctly?

- **Detail accuracy** = details the firm got exactly right ÷ details the firm reported
- **Missed-detail rate** = details in the notes the firm didn't report ÷ details the SME found
- **Made-up rate** = details the firm reported that no note states ÷ details the firm reported

Example: the firm reports 20 details. Seventeen match the notes exactly, 2 have a typo, and 1 appears in no note.

- Detail accuracy = 17 ÷ 20 = **85%**
- Made-up rate = 1 ÷ 20 = **5%**

Close doesn't count. A TIN of `001234567` reported as `1234567` is wrong.

### 3. Right-owner rate: is each detail on the right person or company?

- **Right-owner rate** = correct details sitting on the correct person or company ÷ all correct details

Example: a note says *"Dr. Monroe works at Northstar Orthopedics, 14 Cedar Lane."* The address belongs to the clinic. If the firm puts it on Dr. Monroe, the address itself is right but the owner is wrong. If 2 of 17 correct details are on the wrong owner, the right-owner rate = 15 ÷ 17 = **88%**.

### Linking and corroborating evidence across a claim

The answer key is built across the whole claim, not one note at a time. An SME creates a person or company once, then links later names, shortened names, pronouns, descriptions, actions and details to that same person or company only when the notes make the link clear.

Every item keeps its original note, exact quote and location. Linking two references is **coreference**: deciding that two ways of referring to someone mean the same person or company. **Corroboration** is different: two or more linked statements can support the same possible fact or category, even when they appear in different notes. Neither one permits guessing. If the notes do not make a link clear, the SME records it as unresolved rather than merging it with another person or company.

Example: Note 001 names *"Dr. Ada Monroe."* Note 002 says *"Dr. Monroe assessed the claimant's injury,"* and another note calls someone *"the orthopedic surgeon."* If the claim makes clear that these references are to Ada, all three are linked to her claim-level entry. The action and description remain evidence from their own notes; they do not become unsourced facts on Ada's record.

### 4. Category accuracy: is each one in the right category?

- **Category accuracy** = firm rows with the right category ÷ firm rows the SME could judge

The SME does **not** assign a category while reading each individual note. Their first job is to record exactly what the notes say: names, references, descriptions, actions and details. That keeps the answer key grounded in evidence rather than an immediate interpretation of a vague sentence.

After the SME completes every note for a claim, they review one claim-level entry for each person or company. That entry shows the exact evidence linked to them across the claim, alongside a short guide defining the study's broad categories. The SME assigns a category, or marks **insufficient evidence** or **conflicting evidence**, and identifies the evidence behind that decision. This happens before the SME sees the firm's output.

For example, *"Dr. Monroe assessed the claimant's injury"* may point toward a medical-provider category, but it does not prove it on its own. The claim-level review may have other evidence, such as *"the orthopedic surgeon."* If the evidence remains too weak or conflicting, the entry is set aside rather than counted as right or wrong.

Subcategories are optional. The answer key preserves a stated description such as *"orthopedic surgeon,"* but does not force the SME to choose a subcategory when the notes do not state one. This score matters more than it looks; see [Why category matters](#why-category-matters).

We also report **category coverage** = paired firm rows with an assigned category ÷ all paired firm rows. It shows how much of the firm's output had enough evidence for a fair category comparison. Rows with insufficient or conflicting evidence are not counted as right or wrong.

### 5. Watchlist accuracy: are the flags real?

The firm flags watchlist matches two ways:

- an **exact search** for watchlist names in the notes, and
- **GenAI**, which compares each name it extracted against the watchlist and gives a similarity score from 0 to 100 (RapidFuzz token sort).

For every flag, the SME decides: **same** person or company, **different**, or **can't tell** from the notes.

- **Watchlist accuracy** = flags the SME confirmed as the same ÷ flags the SME could decide, reported separately for exact search and for GenAI
- **Can't-tell rate** = flags the SME couldn't decide ÷ all flags

**Checking the similarity score.** Group GenAI's flags by score and work out the accuracy of each group:

| Similarity score | Flags | Confirmed same | Accuracy |
|---|---|---|---|
| 95–100 | 40 | 36 | 90% |
| 85–94 | 30 | 18 | 60% |
| 75–84 | 20 | 6 | 30% |

*Made-up numbers.* A table like this shows the firm where to set its cut-off score.

**What this can't show.** Checking flags tells us how many flags were wrong. It can't tell us how many real matches were never flagged. To measure that, SMEs also check a random sample of people and companies that weren't flagged.

## Why category matters

GenAI only calculates a similarity score when the category it gave a person or company matches the watchlist entry's category. So a wrong category doesn't just produce a wrong label. It can quietly switch the watchlist check off.

- If GenAI files a doctor under "legal", that doctor is never compared with the watchlist's doctors. A real match can be missed without anyone noticing.
- If GenAI files someone under a category that happens to match a watchlist entry, a comparison runs that never should have.

So category accuracy is part of measuring the watchlist, not a side question. A wrong-category count is useful, but it is not automatically the number of **blocked checks**. To measure blocked checks, the firm must also supply the complete categorized watchlist and enough search information to reconstruct which comparisons would have run under the correct category. To measure real matches missed because of category, those newly eligible comparisons must then be reviewed.

## An example: claim C201

*Fictional test data.*

The notes describe Dr. Ada Monroe as an orthopedic surgeon with Northstar Orthopedics, and call Northstar "the medical provider". A letterhead in another note gives Northstar's street address, city, state, ZIP code, phone number and TIN.

**Northstar Orthopedics.** The firm reported all 6 details. All 6 match the notes, and all 6 are on Northstar, not on Dr. Monroe.

- Detail accuracy = 6 ÷ 6 = **100%**
- Right-owner rate = 6 ÷ 6 = **100%**

**Dr. Ada Monroe.** The firm found her and flagged a watchlist match also named "Dr. Ada Monroe", with a similarity score of 96. That score was only calculated because GenAI filed her under the same category as the watchlist entry, "medical provider". The notes give her name and her job, but no address, phone number or TIN that would confirm she's the same person. That's exactly the kind of flag an SME may mark **can't tell**. The firm may well be right, but a 96 on a name alone isn't proof. Grading many flags like this one is what shows how much a 96 is worth.

## What the proposed workflow will score

*Answer key* means the evidence and decisions SMEs record through the proposed workflow. A score is only calculated after the claim-level review is frozen and the firm's rows have been paired.

| Question | Does the answer key record it? | Can the proposed workflow score it? | What's missing |
|---|---|---|---|
| Found rate, right rate | Yes | Yes | Complete claim, frozen answer key and pairing |
| Detail accuracy, missed-detail rate | Yes | Yes | Complete claim, frozen answer key and pairing |
| Made-up rate | Yes | Yes | Nothing |
| Right-owner rate | Yes | Yes | Pairing |
| Category accuracy and category coverage | Yes. The claim-level review records a category or an unresolved outcome, its evidence and a reason | Yes | A study-approved broad-category guide |
| Wrong-category risk to watchlist checks | Partly. We can identify firm rows that disagree with the frozen category | No | Complete categorized watchlist and a reconstruction of comparisons that should have run |
| Watchlist accuracy, similarity-score check | Yes | Yes | Each flag needs an SME decision and supporting reason |
| Real matches never flagged | No | No | SMEs check a random sample of unflagged people and companies |

## Can we trust the answer key?

A grade is only as good as its answer key. Three checks:

- **Did the SME read every note?** SMEs mark a note complete only after reading all of it. Found rate is only calculated on complete notes. Otherwise a note the SME never finished would look like a miss by the firm.
- **Would a second SME agree?** Give some notes to two SMEs separately.
  **Agreement rate** = items both SMEs recorded the same way ÷ items either SME recorded.
  Low agreement usually means the instructions are unclear, not that SMEs are careless.
- **Do AI drafts sway the SMEs?** SMEs may get AI-drafted suggestions to check. If they tend to accept whatever is suggested, the answer key starts to look like the AI. Keeping some notes draft-free and comparing the two groups shows whether that's happening.

## Later

The same answer key can grade any future tool, including the redesigned Entity Intelligence system, without SMEs redoing their work. It can also check things the firm's tool does not attempt today: whether it links *"she"* or *"the clinic"* to the right entity; whether it carries metadata across notes without losing its source; and whether its category conclusion is supported by the linked evidence.
