# Gold Dataset Workbench QA

The reviewer interface is intentionally narrow: it is a source-note reader and annotation surface. Excel output is generated in the background.

## Automated checks completed

Run the same checks with `./run-sample.ps1 -SelfTest`.

| Area | Check | Result |
|---|---|---|
| Source span | Named-entity text preserves its note ID and character start/end offsets | Pass |
| UTF-8 | Accented Latin and CJK source text round-trip as an exact selected span | Pass |
| Field evidence | A field has an entity reference, exact source text, source note, and offsets | Pass |
| Coreference | A linked pronoun is exported both as a Gold mention and a coreference link | Pass |
| Claim completion | A claim cannot seal until every loaded note is marked read | Pass |
| Undo | The most recent annotation or seal can be reversed | Pass |
| Session restore | A saved session restores source text and annotations | Pass |
| Client input | The supplied client schema and all four sample rows validate | Pass |
| Workbook contract | The exported workbook has the expected tabs in the correct order | Pass |
| Empty case | A valid workbook exports before any annotation is made | Pass |
| First-word selection | Native Tk selection beginning at character `1.0` captures `Maya Chen` at offset `0` | Pass |
| Watchlist review UI | A sealed, reviewed note with a cited flagged record enables and opens its review window | Pass |

## Manual visual acceptance check

Run `./run-sample.ps1`, then complete this sequence. It is designed to catch issues that automated checks cannot see: window size, actual mouse selection, control visibility, and dialog flow.

1. Click **Load notes** and choose `C104_N01.txt` and `C104_N02.txt`. Confirm that the centre note is readable, cannot be typed into, and all five centre actions are visible.
2. In `N01`, drag across the first words, `Maya Chen`. The line above the note should say `Selected: “Maya Chen”`. Click **New named entity**. The dialog should open with `Maya Chen` as the display name; save it as a person.
3. Drag across `She`. Click **Link mention / pronoun**. Select `E1 · Maya Chen`, retain `pronoun`, and save. Confirm green highlighting on `She` and two entries under Maya Chen in the left panel.
4. Drag across `555-0199`. Click **Record field value**. Select Maya Chen and `phone`; save. Confirm blue highlighting and a phone entry in the evidence panel.
5. Drag across text you cannot resolve. Click **Mark uncertain**, enter a reason, and confirm orange highlighting.
6. Click **Undo last change**. Confirm the orange highlight disappears. Repeat the action if desired.
7. Check **I have read this whole note**, switch to `N02`, and complete it. Attempt to seal before checking N02; the app should tell you which note is incomplete. Then mark N02 read and seal.
8. Load `client-export.csv`, enable **Show client proposals after sealing**, and confirm that the right panel shows the records only after seal.
9. Close and reopen the app. Click **Restore saved work**, choose `.gold-workbench-session.json` beside the notes, and confirm the highlights and evidence return.
10. Export the workbook and confirm it opens in Excel with `06_Coreference_links` before `07_Blind_gold_mentions`.
11. Hover over each centre action. Confirm that the reminder explains when to use it. In particular, **Link mention / pronoun** should say it is for an alias, pronoun, repeated name, or description referring to an existing entity.
12. With the client export loaded, seal C104 and return to N01 or N02. The right panel should flag any cited watchlist matches and open **Review watchlist matches for this note**. Record a decision and reason; confirm the exported `09_Phase1_pair_review` tab contains it.
13. In the stress packet’s C201 N01, create Dr. Ada Monroe and Northstar Orthopedics. Select `orthopedic surgeon`, choose **Record context**, attach it to Dr. Ada Monroe, and leave the optional open label blank. Confirm purple highlighting, source evidence in the entity panel, and a row in `15_Blind_gold_context` after export. The reviewer is not asked to choose a category or subcategory.

## Scale packet

`sample-data/stress-packet/notes` contains 60 fictional UTF-8 notes across six claims, with ten notes per claim. Load all of them to test selection, navigation, progress, autosave, and claim-scoped entity lists at a more realistic volume. The accompanying `client-export.csv` has twelve rows using the supplied client schema. It is a usability and scale fixture, not Gold truth.
