# How we grade the firm's entity extraction

The firm uses a tool called GenAI that reads claim notes and pulls out the people and companies mentioned, along with details about them: addresses, phone numbers and tax IDs (TINs). The firm also checks those names against a watchlist. This document explains how we find out how often it gets these right.

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

**One step connects the two: pairing.** The firm's tool and the SME don't always write a name the same way, for example "Dr. Monroe" and "Dr. Ada Monroe". So when an SME finishes a claim, they go through the firm's output row by row and say which person or company on their list each row is, or that it isn't in the notes at all. It takes one decision per row. Most of the scores below depend on it.

## The scores

Every score is a simple fraction. Each one comes with a small made-up example.

### 1. Found rate and right rate: does it find the people and companies?

- **Found rate** = people and companies both the firm and the SME found ÷ everyone the SME found
- **Right rate** = firm rows that match someone on the SME's list ÷ all firm rows

Example: an SME finds 10 people and companies on a claim. The firm's output lists 8. Seven of them are on the SME's list; one isn't in the notes at all.

- Found rate = 7 ÷ 10 = **70%**, so it missed 3.
- Right rate = 7 ÷ 8 = **88%**, so 1 of its 8 was wrong.

You need both. A tool that listed every name in the phone book would find everyone, and be mostly wrong. Data scientists call these two *recall* and *precision*.

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

### 4. Category accuracy: is each one in the right category?

- **Category accuracy** = firm rows with the right category ÷ firm rows the SME could judge

When the notes don't say enough to tell, the row is set aside rather than counted as right or wrong. This score matters more than it looks; see [Why category matters](#why-category-matters).

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

So category accuracy is part of measuring the watchlist, not a side question. We also count **blocked checks**: people and companies the SME says were filed under the wrong category, and so were never compared with the watchlist entries in their real category.

To grade category properly, the SME judges the firm's category during pairing: right, wrong (and what it should be), or the notes don't say.

## An example: claim C201

*Fictional test data.*

The notes describe Dr. Ada Monroe as an orthopedic surgeon with Northstar Orthopedics, and call Northstar "the medical provider". A letterhead in another note gives Northstar's street address, city, state, ZIP code, phone number and TIN.

**Northstar Orthopedics.** The firm reported all 6 details. All 6 match the notes, and all 6 are on Northstar, not on Dr. Monroe.

- Detail accuracy = 6 ÷ 6 = **100%**
- Right-owner rate = 6 ÷ 6 = **100%**

**Dr. Ada Monroe.** The firm found her and flagged a watchlist match also named "Dr. Ada Monroe", with a similarity score of 96. That score was only calculated because GenAI filed her under the same category as the watchlist entry, "medical provider". The notes give her name and her job, but no address, phone number or TIN that would confirm she's the same person. That's exactly the kind of flag an SME may mark **can't tell**. The firm may well be right, but a 96 on a name alone isn't proof. Grading many flags like this one is what shows how much a 96 is worth.

## What we can score today

*Answer key* means what SMEs record in the annotation workbench. *Today* means with the workbench as it stands now.

| Question | Does the answer key record it? | Can we score it today? | What's missing |
|---|---|---|---|
| Found rate, right rate | Yes | Roughly, by matching names | Pairing |
| Detail accuracy, missed-detail rate | Yes | Roughly | Pairing |
| Made-up rate | Yes | Yes | Nothing |
| Right-owner rate | Yes | No | Pairing |
| Category accuracy, blocked checks | No. SMEs record the note's own words ("orthopedic surgeon"), not the firm's category | No | The SME judges the firm's category during pairing |
| Watchlist accuracy, similarity-score check | Yes | Yes | Whether the note supports each decision. The workbench records a fixed value there today |
| Real matches never flagged | No | No | SMEs check a random sample of unflagged people and companies |

## Can we trust the answer key?

A grade is only as good as its answer key. Three checks:

- **Did the SME read every note?** SMEs mark a note complete only after reading all of it. Found rate is only calculated on complete notes. Otherwise a note the SME never finished would look like a miss by the firm.
- **Would a second SME agree?** Give some notes to two SMEs separately.
  **Agreement rate** = items both SMEs recorded the same way ÷ items either SME recorded.
  Low agreement usually means the instructions are unclear, not that SMEs are careless.
- **Do AI drafts sway the SMEs?** SMEs may get AI-drafted suggestions to check. If they tend to accept whatever is suggested, the answer key starts to look like the AI. Keeping some notes draft-free and comparing the two groups shows whether that's happening.

## Later

The same answer key can grade any future tool, including the redesigned system in [ARCHITECTURE.md](ARCHITECTURE.md), without SMEs redoing their work. It can also check things the firm's tool doesn't attempt, such as whether a tool understands who "she" or "the clinic" refers to.
