"""Quote location and Copilot-answer parsing."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from annotator.ai_import import extract_objects, load_object, read_answer, split_parts  # noqa: E402
from annotator.spans import locate  # noqa: E402

NOTE = ("Dr. Ada Monroe called regarding the claim. Dr. Ada Monroe is an orthopedic surgeon with "
        "Northstar Orthopedics, the medical provider.\r\n\r\nShe confirmed the clinic address as 14 Cedar Lane, "
        "Springfield, IL 62704. Its TIN is 001234567. The clinic did not schedule surgery.\r\n\r\n"
        "The caller said they would send a report tomorrow. The note does not establish who they refers to.")


def answer(*lines):
    return "\n".join(lines)


META = '{"type":"meta","claim":"C1","note":"N1","part":1,"parts":1,"read_all":true,"summary":"x"}'


class Locate(unittest.TestCase):
    def test_exact_first_word(self):
        r = locate(NOTE, "Dr. Ada Monroe", occurrence=1)
        self.assertEqual((r.status, r.start, r.end), ("exact", 0, 14))

    def test_repeat_needs_disambiguation(self):
        self.assertEqual(locate(NOTE, "Dr. Ada Monroe").status, "ambiguous")

    def test_repeat_by_occurrence(self):
        r = locate(NOTE, "Dr. Ada Monroe", occurrence=2)
        self.assertEqual(r.start, 43)

    def test_repeat_by_words_before(self):
        r = locate(NOTE, "Dr. Ada Monroe", before="regarding the claim.")
        self.assertEqual((r.start, r.how), (43, "the words before it"))

    def test_curly_quotes_and_dashes_map_back_to_exact_text(self):
        text = "He said “they” would call — tomorrow."
        r = locate(text, '"they" would call - tomorrow')
        self.assertEqual(r.status, "normalized")
        self.assertEqual(text[r.start:r.end], "“they” would call — tomorrow")

    def test_whitespace_and_crlf_differences(self):
        r = locate(NOTE, "medical provider. She confirmed")
        self.assertEqual(r.status, "normalized")
        self.assertEqual(NOTE[r.start:r.end], "medical provider.\r\n\r\nShe confirmed")

    def test_case_fallback(self):
        r = locate(NOTE, "northstar orthopedics")
        self.assertEqual((r.status, NOTE[r.start:r.end]), ("case", "Northstar Orthopedics"))

    def test_not_found_and_empty(self):
        self.assertEqual(locate(NOTE, "Dr. Ada Munro").status, "not_found")
        self.assertEqual(locate(NOTE, "   ").status, "not_found")

    def test_stray_spaces_are_not_stored(self):
        r = locate(NOTE, " 001234567 ")
        self.assertEqual(NOTE[r.start:r.end], "001234567")

    def test_emoji_and_combining_accents_are_code_points(self):
        text = "a\U0001F600b é Ada"      # emoji is 1 code point; e + combining acute is 2
        r = locate(text, "Ada")
        self.assertEqual(text[r.start:r.end], "Ada")
        self.assertEqual(r.start, 7)


class Extract(unittest.TestCase):
    def test_braces_inside_strings_do_not_split_objects(self):
        objs, truncated, _ = extract_objects('{"quote":"a } b { c"}\n{"x":1}')
        self.assertEqual(len(objs), 2)
        self.assertFalse(truncated)

    def test_truncated_answer_keeps_complete_lines(self):
        objs, truncated, _ = extract_objects('{"a":1}\n{"b":2}\n{"c":"cut of')
        self.assertEqual(len(objs), 2)
        self.assertTrue(truncated)

    def test_repairs(self):
        self.assertEqual(load_object('{"a":1,}'), ({"a": 1}, "removed a trailing comma"))
        self.assertEqual(load_object("{“a”:“b”}")[0], {"a": "b"})
        self.assertEqual(load_object("{'a': 'it is true', 'b': true}")[0], {"a": "it is true", "b": True})
        self.assertEqual(load_object("{nonsense"), (None, None))


class ReadAnswer(unittest.TestCase):
    def read(self, text, existing=None, **kw):
        return read_answer(text, NOTE, claim="C1", note="N1", existing_entities=existing or {}, **kw)

    def test_clean_answer(self):
        r = self.read(answer(
            "```", META,
            '{"type":"entity","key":"P1","quote":"Dr. Ada Monroe","name":"Dr. Ada Monroe","kind":"person"}',
            '{"type":"mention","key":"P1","quote":"Dr. Ada Monroe","before":"regarding the claim.","form":"name"}',
            '{"type":"detail","key":"O1","quote":"001234567","field":"TIN","value":"001234567"}',
            '{"type":"entity","key":"O1","quote":"Northstar Orthopedics","name":"Northstar Orthopedics","kind":"organization"}',
            '{"type":"unclear","quote":"they","reason":"Not stated who."}', "```"))
        self.assertEqual(r.errors, [])
        entity, mention, detail, org, unclear = r.drafts
        # The first "Dr. Ada Monroe" has no words before it; reading order pins it to occurrence 1.
        self.assertEqual((entity.start, entity.end), (0, 14))
        self.assertIn("order", entity.notes[-1])
        self.assertEqual((mention.start, mention.end), (43, 57))
        self.assertEqual(detail.fields["value"], "001234567")
        # "they" appears twice and Copilot didn't say which: that one really is the SME's call.
        self.assertEqual([p["code"] for p in unclear.problems], ["ambiguous"])
        self.assertEqual(r.counts()["ready"], 4)

    def test_entity_takes_first_free_occurrence_when_counts_differ(self):
        r = self.read(answer(META, '{"type":"entity","key":"P1","quote":"Dr. Ada Monroe","kind":"person"}'))
        self.assertEqual((r.drafts[0].start, r.drafts[0].problems), (0, []))
        self.assertIn("first time", r.drafts[0].notes[-1])

    def test_chat_text_around_the_block_is_ignored(self):
        r = self.read("Sure! Here are the records {as requested}:\n```json\n" + META +
                      '\n{"type":"entity","key":"P1","quote":"Dr. Ada Monroe","kind":"person"}\n```\nLet me know!')
        self.assertEqual(r.counts()["total"], 1)
        self.assertEqual(r.rejected, [])
        self.assertGreaterEqual(r.ignored_lines, 2)

    def test_pretty_printed_items_wrapper(self):
        r = self.read('{\n  "meta": {"claim": "C1"},\n  "items": [\n    {"type": "entity", "key": "O1",\n'
                      '     "quote": "Northstar Orthopedics", "kind": "organization"}\n  ]\n}')
        self.assertEqual(r.counts()["ready"], 1)

    def test_synonyms_are_understood(self):
        r = self.read(answer(META,
                             '{"type":"organization","key":"O1","quote":"Northstar Orthopedics","kind":"company"}',
                             '{"type":"field","key":"O1","quote":"62704","field":"zip"}',
                             '{"type":"statement","key":"O1","quote":"did not schedule surgery"}'))
        self.assertEqual([d.type for d in r.drafts], ["entity", "detail", "action"])
        self.assertEqual(r.drafts[0].fields["kind"], "organization")
        self.assertEqual(r.drafts[1].fields["field"], "zip_code")

    def test_problems_are_specific(self):
        r = self.read(answer(META,
                             '{"type":"mention","key":"P9","quote":"She","form":"pronoun"}',
                             '{"type":"detail","key":"E4","quote":"001234567","field":"shoe size"}',
                             '{"type":"unclear","quote":"they"}',
                             '{"type":"entity","key":"P1","quote":"Dr. Ada Munro"}',
                             '{"type":"banana","quote":"x"}'))
        codes = [[p["code"] for p in d.problems] for d in r.drafts]
        self.assertEqual(codes, [["unknown_key"], ["bad_field", "unknown_key"], ["no_reason", "ambiguous"],
                                 ["not_found"]])
        self.assertEqual(len(r.rejected), 1)

    def test_existing_entity_keys(self):
        r = self.read(answer(META, '{"type":"mention","key":"E1","quote":"She","form":"pronoun"}'),
                      existing={1: "E-abc"})
        self.assertEqual(r.drafts[0].problems, [])

    def test_new_entity_may_not_take_an_E_key(self):
        r = self.read(answer(META, '{"type":"entity","key":"E7","quote":"Northstar Orthopedics"}'))
        self.assertEqual(r.drafts[0].problems[0]["code"], "bad_key")

    def test_forward_reference_to_a_later_entity_is_fine(self):
        r = self.read(answer(META, '{"type":"action","key":"P1","key2":"O1","quote":"with Northstar Orthopedics"}',
                             '{"type":"entity","key":"P1","quote":"Dr. Ada Monroe","before":"","occurrence":1}',
                             '{"type":"entity","key":"O1","quote":"Northstar Orthopedics"}'))
        self.assertEqual(r.drafts[0].problems, [])

    def test_wrong_note_and_partial_read_are_warned(self):
        r = self.read('{"type":"meta","claim":"C9","note":"N4","read_all":false}\n'
                      '{"type":"entity","key":"P1","quote":"Dr. Ada Monroe","occurrence":1}')
        self.assertEqual(len(r.warnings), 2)

    def test_table_answer_gets_a_useful_error(self):
        r = self.read("| type | quote |\n|---|---|\n| entity | Dr. Ada Monroe |")
        self.assertIn("table", r.errors[0])

    def test_empty_answer(self):
        self.assertIn("empty", self.read("   ").errors[0])

    def test_cut_off_answer_keeps_what_it_can(self):
        r = self.read(answer(META, '{"type":"entity","key":"O1","quote":"Northstar Orthopedics"}',
                             '{"type":"detail","key":"O1","quote":"0012'))
        self.assertTrue(r.truncated)
        self.assertEqual(r.counts()["total"], 1)
        self.assertIn("cut off", r.warnings[0])

    def test_duplicate_lines_within_one_answer(self):
        line = '{"type":"description","key":"P1","quote":"orthopedic surgeon"}'
        r = self.read(answer(META, '{"type":"entity","key":"P1","quote":"Dr. Ada Monroe","occurrence":1}', line, line))
        self.assertEqual(r.drafts[2].status, "duplicate")

    def test_part_preference_resolves_repeats(self):
        parts = split_parts(NOTE, 60)
        self.assertGreater(len(parts), 1)
        self.assertEqual(parts[0][0], 0)
        self.assertEqual(parts[-1][1], len(NOTE))
        self.assertTrue(all(a[1] == b[0] for a, b in zip(parts, parts[1:])))


if __name__ == "__main__":
    unittest.main()
