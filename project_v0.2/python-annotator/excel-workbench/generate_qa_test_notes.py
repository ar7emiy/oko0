"""Generate the edge-case note files QA-ACCEPTANCE-WALKTHROUGH.md tests against.

The long-note and split-boundary rows in QA-ACCEPTANCE.md ("32,766 / 32,767 /
32,768 / 100,000+ units", "emoji at split point, CRLF, combining accents,
quote crossing part boundary") describe properties, not files. Hand-typing a
32,768-UTF-16-unit note in Notepad is impractical and error-prone, so this
writes exact, reproducible fixtures instead -- named CLAIM_NOTE.txt so
"Import TXT files" accepts them directly, using claim QA01 so they cannot be
mistaken for the C104/C201/C202 sample data used elsewhere.

Prints the exact stats (length, first/last text, marker offsets) the
walkthrough quotes, so the printed expectations and the files can never
drift apart -- run this again if either changes.
"""
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / 'sample-data' / 'qa-test-notes'
OUT.mkdir(exist_ok=True)


def utf16_len(s):
    return len(s.encode('utf-16-le')) // 2


def padded(total_units, tag):
    """FIRST-<tag>-...x...-LAST-<tag> at exactly total_units UTF-16 units."""
    head, tail = f'FIRST-{tag}-', f'-LAST-{tag}'
    fill = total_units - len(head) - len(tail)
    assert fill > 0
    return head + 'x' * fill + tail


CASES = [(32766, '32766'), (32767, '32767'), (32768, '32768'), (100000, '100000')]
for i, (n, tag) in enumerate(CASES, start=1):
    text = padded(n, tag)
    assert utf16_len(text) == n, (tag, utf16_len(text))
    path = OUT / f'QA01_N{i:02d}.txt'
    path.write_text(text, encoding='utf-8')
    print(f'{path.name}: {n} UTF-16 units. First 20: {text[:20]!r}  Last 20: {text[-20:]!r}')

# Boundary note: SafeTake/tParts chunk at 8000 UTF-16 units. This is the exact
# construction RunCoreSelfTests already exercises and asserts round-trips, so
# it is known-good, not a new case being tried for the first time here.
PREFIX = 'x' * 7990
STRADDLE = 'STRADDLEBOUNDARY'                    # 17 chars: positions 7991-8007, spans the cut
EMOJI = '\U0001F600'                              # 2 UTF-16 units (surrogate pair): 8008-8009
ACCENT = 'é'                                # base + combining acute, 2 code points: 8010-8011
TAIL = '\r\nTAIL-MARKER-END'
boundary_text = PREFIX + STRADDLE + EMOJI + ACCENT + TAIL
straddle_at = len(PREFIX) + 1  # 1-based UTF-16 offset where STRADDLEBOUNDARY starts
path = OUT / 'QA01_N05.txt'
path.write_text(boundary_text, encoding='utf-8')
print(f'{path.name}: {utf16_len(boundary_text)} UTF-16 units. '
      f'STRADDLEBOUNDARY starts at unit {straddle_at}, crossing the 8000-unit part boundary. '
      f'Emoji, then e + combining acute, then CRLF, then TAIL-MARKER-END.')

# Two same-first-name people plus one ambiguous pronoun, for the
# "same name for two people / ambiguous pronoun" acceptance row.
ambiguous_text = ('Mr. John Carter phoned about the claim. Mr. John Reyes is the '
                   'passenger. He agreed to send photos of the damage by Friday.')
path = OUT / 'QA01_N06.txt'
path.write_text(ambiguous_text, encoding='utf-8')
print(f"{path.name}: {utf16_len(ambiguous_text)} UTF-16 units. Two distinct "
      f"'John's, one ambiguous 'He'.")

# Every entry kind on one note: an organization, an address, a TIN whose
# leading zeros must survive, context, a negated statement and an unresolved
# pronoun. The 60-note stress packet has none of these together, and its only
# TIN (STRESS-201) has no leading zeros to lose.
kinds_text = ('Dr. Ada Monroe called regarding the claim. Dr. Ada Monroe is an orthopedic '
              'surgeon with Northstar Orthopedics, the medical provider.\n\n'
              'She confirmed the clinic address as 14 Cedar Lane, Springfield, IL 62704. '
              'Its TIN is 001234567. The clinic did not schedule surgery.\n\n'
              'The caller said they would send a report tomorrow. The note does not '
              'establish who they refers to.')
path = OUT / 'QA01_N07.txt'
path.write_text(kinds_text, encoding='utf-8')
print(f'{path.name}: {utf16_len(kinds_text)} UTF-16 units. Address, TIN 001234567, context, '
      f'negated statement, ambiguous "they".')

# A note whose entire body looks like a formula, to prove it stays literal text.
path = OUT / 'QA01_N08.txt'
path.write_text('=1+1', encoding='utf-8')
print(f'{path.name}: body is the literal text =1+1')

print(f'\n{len(CASES) + 4} files written to {OUT}')
