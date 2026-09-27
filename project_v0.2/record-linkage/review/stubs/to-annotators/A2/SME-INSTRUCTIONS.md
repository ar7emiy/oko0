# Reviewing possible watchlist matches: instructions for reviewers

## What you are doing

Each row of the workbook is one **pair**: on the left, a person or business as it was recorded
in claim data ("extracted"); on the right, a person or business from the watchlist. Your job is
to say whether the two describe **the same real-world party**. You label pairs; you do not
search for matches, and nothing you do changes any live system.

No score or computer judgement is shown, on purpose: we use your labels to measure how well
the matching works, so they must be yours alone.

## The three labels

- **match**: the same person, or the same business.
- **non-match**: different parties, even if they are related (family members, a doctor and
  the clinic she works at, two separately registered branches of one brand, a parent company
  and its subsidiary).
- **unsure**: the values shown do not settle it either way. Use it when you cannot lean either
  way, not as "probably". Always say why (for example "common name, nothing else to compare").

## What counts as the same party

**Persons: the same human being.** These do *not* make a non-match on their own:
nicknames and short forms (Bill / William, Peggy / Margaret), a first initial instead of a first
name, small spelling mistakes, first and last name swapped, a missing middle name, a surname
change (marriage), a different address or phone (people move), empty cells.

These point strongly to a **non-match**: a different date of birth that is not a typo or a
day/month swap; a different SSN, driver licence or NPI that is not a one-digit slip; Jr / Sr or
other generations with different dates of birth.

**Businesses: the same business entity.** These do *not* make a non-match on their own:
"d/b/a" (doing business as) names, a missing or different suffix (LLC, Inc, PC, PLLC),
abbreviations (Ctr / Center, & / And), a move.

These point strongly to a **non-match**: a different TIN; the same brand name in a different
location with a different TIN or clinic NPI ("sibling" businesses); different owners named
alongside.

## Weighing what you see

- **Identifiers** (SSN, TIN, NPI, licence, driver licence, VIN) are the strongest evidence.
  The same identifier is close to decisive; one digit different may be a typing error.
- **Common names alone** (for example "John Smith" with nothing else to compare) are not
  enough for a match: label **unsure** unless something else agrees or conflicts.
- **An empty cell is no information**, not a disagreement.
- **"Same row also lists"** shows the other party recorded on the same row (for example the
  clinic a doctor was recorded with). Use it as context only.
- Values may be written differently (upper/lower case, date formats, spaces in phone
  numbers). Judge the value, not the formatting.

## Confidence

- **high**: you would be surprised to be wrong.
- **medium**: you lean one way but the evidence is not conclusive.
- **low**: a weak lean. If you have no lean at all, choose **unsure** instead.

## Reason

One short line naming the fields that decided it, for example "same SSN and date of birth;
Bill/William". Required for **unsure** and for anything not **high**; welcome for the rest.

## Rules

1. Work alone and do not discuss pairs with other reviewers: some pairs are given to two
   reviewers to measure agreement.
2. Use only the values in the workbook. Do not look the parties up in other systems unless the
   study coordinator tells you otherwise.
3. Do not edit the data cells, add or delete rows, or rename sheets. Only the label, confidence,
   reason and date cells are editable.
4. Label every row, then return the file with its original name to the study coordinator.

## Examples (fictional)

| Extracted | Watchlist | Label | Why |
|---|---|---|---|
| William R. Hart, DOB 1961-03-14, SSN ending 4471 | Bill Hart, DOB 1961-03-14, SSN ending 4471 | match, high | same SSN and DOB; Bill is short for William |
| Maria Lopez, DOB 1979-07-02, Queens NY | Maria Lopez, DOB 1983-11-19, Queens NY | non-match, high | same common name and area, different date of birth |
| John Smith, no other details | John Smith, DOB 1955-01-09, Phoenix AZ | unsure, low | common name, nothing to compare |
| Kaur Anita, DOB 1970-05-06 | Anita Kaur, DOB 1970-06-05 | match, medium | names swapped; DOB day/month swapped |
| Pine Street Family Dental, TIN 12-3456789 | Harbor Dental Group LLC d/b/a Pine Street Family Dental, TIN 12-3456789 | match, high | same TIN; the d/b/a name matches |
| Quick Fix Collision - Newark, TIN 22-1111111 | Quick Fix Collision - Paterson, TIN 22-2222222 | non-match, high | same brand, different TIN and town: sibling businesses |
| Dr. Ana Ruiz, NPI 1234567893 | Ana Ruiz, NPI 1234567839 | match, medium | NPI digits transposed; name agrees; nothing conflicts |
| Robert Nguyen Jr, DOB 1988-02-10 | Robert Nguyen, DOB 1959-08-30, same address | non-match, high | same name and address, a generation apart |

## How to fill in the workbook

1. Open the *Persons* and *Businesses* sheets. Columns A-F are yours: `review_id` (do not
   change), `label`, `confidence`, `reason`, `annotator_id` (already filled in) and
   `labelled_on` (today's date).
2. Pick `label` and `confidence` from the drop-down lists.
3. Save the workbook with its original name and return it.
