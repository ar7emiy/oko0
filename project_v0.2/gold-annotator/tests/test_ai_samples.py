"""Self-prompted Copilot replies, read against their real notes.

Each reply was written by following prompts/copilot-agent-instructions.md
exactly, then checked here through the same parser the app uses. The "sloppy"
replies deliberately do what models actually do instead (chat around the block,
no "before" on repeated names, older record names, curly quotes as JSON quotes,
a raw line break in a string, a trailing comma, one paraphrase). A change to
the prompt or the parser that breaks any of these fails the suite.

These show the format is followable and the parser recovers from real slips.
They are not a substitute for replies from the firm's own Copilot tenant; use
check_answer.py on those.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from annotator.ai_import import read_answer  # noqa: E402
from annotator.notes import parse_name, read  # noqa: E402

SAMPLES = ROOT / "tests" / "ai_samples"
STRESS = ROOT.parent / "python-annotator" / "sample-data" / "stress-packet" / "notes"
QA = ROOT.parent / "python-annotator" / "sample-data" / "qa-test-notes"
PRACTICE = ROOT / "annotator" / "practice"

# reply file, note file, known entity numbers, ready, needs attention, error substring
CASES = [
    ("c201_n01.reply.txt", STRESS / "C201_N01.txt", [], 7, 0, None),
    ("c201_n04.reply.txt", STRESS / "C201_N04.txt", [1, 2], 7, 0, None),
    ("c202_n03.reply.txt", STRESS / "C202_N03.txt", [], 4, 0, None),
    ("c203_n02.reply.txt", STRESS / "C203_N02.txt", [], 5, 0, None),
    ("c203_n09.reply.txt", STRESS / "C203_N09.txt", [1, 2], 3, 0, None),
    ("c204_n05.reply.txt", STRESS / "C204_N05.txt", [], 3, 0, None),
    ("c205_n07.reply.txt", STRESS / "C205_N07.txt", [], 0, 0, "found nothing to record"),
    ("c206_n06.reply.txt", STRESS / "C206_N06.txt", [], 2, 0, None),
    ("c206_n06.sloppy.reply.txt", STRESS / "C206_N06.txt", [], 2, 0, None),
    ("qa01_n06.reply.txt", QA / "QA01_N06.txt", [], 5, 0, None),
    ("practice_n01.reply.txt", PRACTICE / "PRACTICE_N01.txt", [], 20, 0, None),
    ("self_n01.faithful.reply.txt", SAMPLES / "notes" / "SELF_N01.txt", [], 51, 0, None),
    ("self_n01.sloppy.reply.txt", SAMPLES / "notes" / "SELF_N01.txt", [], 34, 1, None),
]


def read_case(reply_text: str, note_path: Path, known):
    claim, note = parse_name(note_path)
    return read_answer(reply_text, read(note_path).text, claim=claim, note=note,
                       existing_entities={k: f"E-{k}" for k in known}, part_size=12000)


class Samples(unittest.TestCase):
    def test_every_sample(self):
        for reply, note_path, known, ready, attention, error in CASES:
            with self.subTest(reply=reply):
                r = read_case((SAMPLES / reply).read_text(encoding="utf-8"), note_path, known)
                c = r.counts()
                if error:
                    self.assertTrue(any(error in e for e in r.errors), r.errors)
                else:
                    self.assertEqual(r.errors, [])
                self.assertEqual(c["rejected"], 0, r.rejected)
                self.assertEqual((c["ready"], c["needs_attention"]), (ready, attention),
                                 [(d.quote, d.problems) for d in r.drafts if d.problems])
                text = read(note_path).text
                for d in r.drafts:
                    if d.start is not None:
                        self.assertEqual(text[d.start:d.end], d.quote)   # stored quote is a verbatim slice

    def test_sloppy_reply_lands_on_the_same_occurrences(self):
        """With no "before" at all, repeated names must still land where the faithful reply put them."""
        note = SAMPLES / "notes" / "SELF_N01.txt"
        good = read_case((SAMPLES / "self_n01.faithful.reply.txt").read_text(encoding="utf-8"), note, [])
        sloppy = read_case((SAMPLES / "self_n01.sloppy.reply.txt").read_text(encoding="utf-8"), note, [])
        truth = {}
        for d in good.drafts:
            truth.setdefault((d.type, (d.key or "").upper(), d.quote), set()).add((d.start, d.end))
        compared = 0
        for d in sloppy.drafts:
            spans = truth.get((d.type, (d.key or "").upper(), d.quote))
            if spans and d.start is not None:
                compared += 1
                self.assertIn((d.start, d.end), spans, f"{d.type} {d.quote!r} landed on the wrong occurrence")
        self.assertGreaterEqual(compared, 30)
        self.assertEqual(set(sloppy.repairs), {"replaced curly quotes used as JSON quotes",
                                               "accepted a line break inside a quote"})

    def test_cut_off_reply_keeps_every_complete_line(self):
        full = (SAMPLES / "self_n01.faithful.reply.txt").read_text(encoding="utf-8")
        cut = full[: int(len(full) * 0.6)]
        complete = sum(1 for ln in cut.splitlines() if ln.startswith("{") and ln.endswith("}")) - 1  # minus meta
        r = read_case(cut, SAMPLES / "notes" / "SELF_N01.txt", [])
        self.assertTrue(r.truncated)
        self.assertEqual(r.counts()["total"], complete)
        self.assertTrue(any("cut off" in w for w in r.warnings))

    def test_pretty_printed_array_instead_of_json_lines(self):
        lines = (SAMPLES / "self_n01.faithful.reply.txt").read_text(encoding="utf-8").splitlines()
        items = [json.loads(ln) for ln in lines if ln.startswith("{")][1:]
        r = read_case("Here you go:\n```json\n" + json.dumps(items, indent=2) + "\n```",
                      SAMPLES / "notes" / "SELF_N01.txt", [])
        self.assertEqual((r.counts()["ready"], r.counts()["rejected"]), (51, 0))

    def test_table_and_refusal_explain_what_to_do(self):
        note = SAMPLES / "notes" / "SELF_N01.txt"
        table = read_case("| type | quote |\n|---|---|\n| entity | Maria Alvarez |", note, [])
        self.assertIn("table", table.errors[0])
        refusal = read_case("I'm sorry, I can't help with that.", note, [])
        self.assertIn("No items found", refusal.errors[0])


if __name__ == "__main__":
    unittest.main()
