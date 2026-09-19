"""Pressure-test the Copilot prompt against the contract the VBA actually enforces.

Three things are checked:

A. Vocabulary agreement. Every closed value list appears in three places -- the
   prompt Copilot reads, the VBA that validates, and the workbook's data
   validation dropdowns. All three must agree exactly or the SME gets told off
   for a value the prompt told the model to produce.

B. Cell-address coverage. SaveQueueSnapshot reads specific cells. If the prompt
   does not name them, Copilot has to guess where to write.

C. Queue admission. A battery of realistic Copilot outputs, valid and
   adversarial, run against a Python model of SaveQueueSnapshot's admission
   rules and ValidateForm's accept rules, over the real sample note.

Part C models the VBA rules; it does not execute them. It proves the prompt
can only produce loadable output and pins the contract so drift is caught. It
is not a substitute for running the VBA in Excel.
"""
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent
NOTE = (ROOT.parent / 'sample-data' / 'stress-packet' / 'notes' / 'C201_N01.txt').read_text(encoding='utf-8')
PROMPT = (ROOT / 'COPILOT-PROMPT.md').read_text(encoding='utf-8')
VBA = '\n'.join(p.read_text(encoding='utf-8-sig') for p in ROOT.glob('*.bas'))
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}

failures = []
passed = []


def check(ok, label, detail=''):
    (passed if ok else failures).append(label if ok else f'{label}\n      {detail}')


# --------------------------------------------------------------------------
# A. Vocabulary agreement across prompt, VBA and workbook dropdowns
# --------------------------------------------------------------------------
def vba_pipe_list(*members):
    """Find the |a|b|c| membership literal the VBA tests against."""
    for m in re.finditer(r'"\|([a-zA-Z_|]+)\|"', VBA):
        values = m.group(1).split('|')
        if set(values) >= set(members):
            return values
    return []


def workbook_dropdown(cell):
    with zipfile.ZipFile(ROOT / 'Entity-Gold-Review-Macro-Free.xlsx') as z:
        for name in z.namelist():
            if not re.match(r'xl/worksheets/sheet\d+\.xml$', name):
                continue
            sheet = ET.fromstring(z.read(name))
            for dv in sheet.findall('.//s:dataValidation', NS):
                if dv.attrib.get('sqref') == cell:
                    f1 = dv.find('s:formula1', NS)
                    if f1 is not None and f1.text:
                        return f1.text.strip('"').split(',')
    return []


def prompt_list(pattern):
    m = re.search(pattern, PROMPT)
    if not m:
        return []
    return [v.strip(' .') for v in re.split(r',\s*|\s+or\s+', m.group(1)) if v.strip(' .')]


VOCABS = [
    ('action', vba_pipe_list('entity', 'reference', 'field'), workbook_dropdown('C9'),
     prompt_list(r'action(?: \(column [A-Z]\))? is ([a-z, ]+or uncertain)')),
    ('reference_form', vba_pipe_list('name', 'alias', 'pronoun'), workbook_dropdown('C15'),
     prompt_list(r'reference_form(?: \(column [A-Z]\))? is ([a-z, ]+or description)')),
    ('field_kind', vba_pipe_list('entity_name', 'address', 'city'), workbook_dropdown('C16'),
     prompt_list(r'field_kind(?: \(column [A-Z]\))? is ([A-Za-z_, ]+or other)')),
]
for name, vba, dropdown, prompt in VOCABS:
    check(bool(vba) and set(vba) == set(dropdown),
          f'A: {name} — VBA matches workbook dropdown',
          f'VBA={sorted(vba)} dropdown={sorted(dropdown)}')
    check(bool(prompt) and set(prompt) == set(vba),
          f'A: {name} — prompt matches VBA',
          f'prompt={sorted(prompt)} VBA={sorted(vba)}')

schema_actions = {'entity', 'reference', 'field', 'context', 'statement', 'uncertain'}
check(set(VOCABS[0][1]) == schema_actions, 'A: action vocabulary is the documented six',
      f'VBA={sorted(VOCABS[0][1])}')

# --------------------------------------------------------------------------
# B. Cell-address coverage: every cell SaveQueueSnapshot reads must be named
# --------------------------------------------------------------------------
snapshot = re.search(r'Public Sub SaveQueueSnapshot[\s\S]*?^End Sub', VBA, re.M).group(0)
read_cells = sorted(set(re.findall(r'ws\.Range\("([A-Z]+\d+)"\)', snapshot)))
check(bool(read_cells), 'B: located the analysis cells the VBA reads', 'none found')
# Scoped to the sentences naming the sheet: the same address used for another
# sheet (Review Desk also has a C4..C6) must not satisfy this check.
ANALYSIS_TEXT = ' '.join(l for l in PROMPT.splitlines() if 'AI Analysis Input' in l)
DESK_TEXT = ' '.join(l for l in PROMPT.splitlines() if 'Review Desk' in l)
for cell in read_cells:
    check(cell in ANALYSIS_TEXT, f'B: prompt names AI Analysis Input cell {cell} in context',
          f'SaveQueueSnapshot reads {cell}; the prompt does not name it where it names that sheet')

with zipfile.ZipFile(ROOT / 'Entity-Gold-Review-Macro-Free.xlsx') as z:
    for name in z.namelist():
        if re.match(r'xl/tables/table\d+\.xml$', name):
            t = ET.fromstring(z.read(name))
            if t.attrib['name'] == 'tInput':
                header_row = int(re.search(r'\d+', t.attrib['ref'].split(':')[0]).group())
check(f'row {header_row + 1}' in PROMPT.lower() or f'A{header_row + 1}' in PROMPT,
      f'B: prompt states where AI Queue rows start (row {header_row + 1})',
      f'tInput headers are on row {header_row}, so Copilot must write from row {header_row + 1}')
for cell in ('C4', 'C5', 'C6'):
    check(cell in DESK_TEXT, f'B: prompt names Review Desk cell {cell} in context',
          'the prompt must say which cells carry claim number, note ID and source version')

# --------------------------------------------------------------------------
# C. Queue admission model, exercised with realistic Copilot outputs
# --------------------------------------------------------------------------
COLUMNS = ['candidate_key', 'action', 'source_quote', 'occurrence', 'entity_key', 'display_name',
           'entity_type', 'reference_form', 'field_kind', 'field_value', 'second_entity_key',
           'open_label', 'reason']
ACTIONS, FORMS, KINDS = set(VOCABS[0][1]), set(VOCABS[1][1]), set(VOCABS[2][1])


def occurrence_start(text, quote, n):
    """VBA OccurrenceStart: 1-based, overlapping matches, 0 when absent."""
    if not quote or n < 1:
        return 0
    pos, start = 0, 0
    for _ in range(n):
        pos = text.find(quote, start)
        if pos < 0:
            return 0
        start = pos + 1
    return pos + 1


def snapshot_queue(rows, label='run 1', complete='yes'):
    """Model SaveQueueSnapshot. Returns (staged_rows, hard_error or None)."""
    if not label.strip():
        return [], 'Give this AI run a label on AI Analysis Input.'
    if complete.lower() not in ('yes', 'no'):
        return [], 'Run complete? must be yes or no.'
    if not rows:
        return [], 'No queue rows.'
    for row in rows:
        if any(str(v).startswith('=') for v in row.values()):
            return [], 'AI Queue contains formulas. Replace them with literal values.'
    seen, staged = set(), []
    for row in rows:
        key = row.get('candidate_key', '')
        if not key:
            if any(row.get(c, '') for c in COLUMNS[1:]):
                return [], 'A populated queue row is missing candidate_key.'
            continue
        if key in seen:
            return [], f'Duplicate candidate key: {key}'
        seen.add(key)
        if row.get('action', '') not in ACTIONS:
            return [], f'Unknown action at candidate {key}'
        if not row.get('source_quote', ''):
            return [], 'Every proposal needs an exact source quote.'
        occ, pos = row.get('occurrence', ''), 0
        if str(occ).strip().isdigit() and 0 < int(occ) < 2147483647:
            pos = occurrence_start(NOTE, row['source_quote'], int(occ))
        if pos == 0 and occurrence_start(NOTE, row['source_quote'], 1) > 0 \
                and occurrence_start(NOTE, row['source_quote'], 2) == 0:
            occ, pos = '1', occurrence_start(NOTE, row['source_quote'], 1)
        staged.append(dict(row, occurrence=occ, start_utf16=pos,
                           status='pending' if pos else 'needs_attention'))
    return staged, None


def accept(row, accepted_entities):
    """Model ValidateForm for one loaded candidate. Returns None or the refusal."""
    action = row['action']
    if not row['start_utf16']:
        return 'Exact evidence was not found at this occurrence. Use Locate evidence.'
    if action != 'entity' and action != 'uncertain':
        if row.get('entity_key', '') not in accepted_entities:
            return 'Create the referenced entity first, or choose an existing accepted reference.'
    if action == 'reference' and row.get('reference_form', '') not in FORMS:
        return 'Choose a valid reference form.'
    if action == 'field':
        if not row.get('field_kind', '') or not row.get('field_value', ''):
            return 'Field kind and field value are required.'
        if row['field_kind'] not in KINDS:
            return 'Choose a valid field kind.'
    if action == 'uncertain' and not row.get('reason', ''):
        return 'Explain why this evidence cannot be resolved.'
    return None


def r(key, action, quote, occ='', **kw):
    row = {c: '' for c in COLUMNS}
    row.update(candidate_key=key, action=action, source_quote=quote, occurrence=str(occ), **kw)
    return row


GOOD = [
    r('R1', 'entity', 'Dr. Ada Monroe', 1, entity_key='P1', display_name='Dr. Ada Monroe', entity_type='person'),
    r('R2', 'statement', 'called regarding the claim', 1, entity_key='P1'),
    r('R3', 'reference', 'Dr. Ada Monroe', 2, entity_key='P1', reference_form='name'),
    r('R4', 'context', 'orthopedic surgeon', 1, entity_key='P1'),
    r('R5', 'entity', 'Northstar Orthopedics', 1, entity_key='O1',
      display_name='Northstar Orthopedics', entity_type='organization'),
    r('R6', 'statement', 'with Northstar Orthopedics', 1, entity_key='P1', second_entity_key='O1',
      reason='Proposed affiliation; verify in context.'),
]

CASES = [
    ('happy path stages every row', GOOD, None, 6),
    ('blank run label refused', GOOD, 'Give this AI run a label on AI Analysis Input.', 0),
    ('non-yes/no completeness refused', GOOD, 'Run complete? must be yes or no.', 0),
    ('empty queue refused', [], 'No queue rows.', 0),
    ('formula injection refused',
     [r('R1', 'entity', '=HYPERLINK("http://x")', 1)], 'AI Queue contains formulas. Replace them with literal values.', 0),
    ('duplicate candidate_key refused',
     [r('R1', 'entity', 'Dr. Ada Monroe', 1), r('R1', 'context', 'orthopedic surgeon', 1)],
     'Duplicate candidate key: R1', 0),
    ('invented action refused',
     [r('R1', 'organization', 'Northstar Orthopedics', 1)], 'Unknown action at candidate R1', 0),
    ('JSON blob as action refused',
     [r('R1', '{"action":"entity"}', 'Dr. Ada Monroe', 1)], 'Unknown action at candidate R1', 0),
    ('missing quote refused', [r('R1', 'entity', '', 1)], 'Every proposal needs an exact source quote.', 0),
    ('orphan explanatory row refused',
     [r('', '', '', '', reason='Here is my analysis of the note.')],
     'A populated queue row is missing candidate_key.', 0),
    ('trailing blank row tolerated',
     GOOD + [{c: '' for c in COLUMNS}], None, 6),
]

for name, rows, expected_error, expected_staged in CASES:
    label = '' if 'blank run label' in name else 'run 1'
    complete = 'partially' if 'non-yes/no' in name else 'yes'
    staged, error = snapshot_queue(rows, label, complete)
    check(error == expected_error and len(staged) == expected_staged,
          f'C: {name}', f'got error={error!r} staged={len(staged)}')

# Quotes the model paraphrased or mis-numbered must survive as reviewable, never silently accepted.
for name, row in [
    ('hallucinated quote', r('R1', 'entity', 'Dr. Ada Munro', 1)),
    ('paraphrase', r('R1', 'statement', 'Ada called about the claim', 1, entity_key='P1')),
    ('occurrence past the end', r('R1', 'reference', 'Dr. Ada Monroe', 9, entity_key='P1', reference_form='name')),
    ('non-numeric occurrence', r('R1', 'reference', 'Dr. Ada Monroe', 'first', entity_key='P1', reference_form='name')),
]:
    staged, error = snapshot_queue([row])
    check(error is None and staged and staged[0]['status'] == 'needs_attention',
          f'C: {name} stages as needs_attention, not pending',
          f'error={error!r} status={staged[0]["status"] if staged else "n/a"}')
    check(staged and accept(staged[0], {'P1'}) is not None,
          f'C: {name} cannot be accepted without correction')

# A single unambiguous occurrence is repaired rather than rejected.
staged, _ = snapshot_queue([r('R1', 'context', 'orthopedic surgeon', '', entity_key='P1')])
check(staged and staged[0]['occurrence'] == '1' and staged[0]['status'] == 'pending',
      'C: blank occurrence on a unique quote is repaired to 1',
      f'{staged[0]["occurrence"]!r} {staged[0]["status"]!r}' if staged else 'nothing staged')

staged, _ = snapshot_queue([r('R1', 'reference', 'Dr. Ada Monroe', '', entity_key='P1', reference_form='name')])
check(staged and staged[0]['status'] == 'needs_attention',
      'C: blank occurrence on a repeated quote is NOT guessed',
      f'{staged[0]["status"]!r}' if staged else 'nothing staged')

# Accept-time value rules.
staged, _ = snapshot_queue(GOOD)
by_key = {row['candidate_key']: row for row in staged}
check(accept(by_key['R1'], set()) is None, 'C: entity accepts with no prior entities')
check(accept(by_key['R2'], set()) is not None, 'C: statement blocked before its entity exists')
check(accept(by_key['R2'], {'P1'}) is None, 'C: statement accepts once its entity exists')
for name, row, ok in [
    ('bad reference_form', r('X', 'reference', 'Dr. Ada Monroe', 2, entity_key='P1', reference_form='nickname'), False),
    ('good reference_form', r('X', 'reference', 'Dr. Ada Monroe', 2, entity_key='P1', reference_form='name'), True),
    ('bad field_kind', r('X', 'field', 'Northstar Orthopedics', 1, entity_key='O1', field_kind='employer', field_value='n'), False),
    ('field without value', r('X', 'field', 'Northstar Orthopedics', 1, entity_key='O1', field_kind='entity_name'), False),
    ('uncertain without reason', r('X', 'uncertain', 'the medical provider', 1), False),
    ('uncertain with reason', r('X', 'uncertain', 'the medical provider', 1, reason='Referent unclear.'), True),
]:
    s, _ = snapshot_queue([row])
    check(bool(s) and (accept(s[0], {'P1', 'O1'}) is None) == ok, f'C: {name}')

# Load order: model LoadNextCandidate, including the dependency promotion that
# pulls a required entity forward when a dependent sits earlier in the note.
def load_sequence(staged):
    """Simulate the SME clicking Load next AI draft and accepting, to exhaustion."""
    rows = [dict(row) for row in staged]
    accepted, order, guard = set(), [], 0
    while guard < 100:
        guard += 1
        pending = [x for x in rows if x['status'] in ('pending', 'needs_attention')]
        if not pending:
            break
        best = min(pending, key=lambda x: (x['start_utf16'] or 10 ** 15, x['action'] != 'entity'))
        if best['action'] != 'entity':
            for column in ('entity_key', 'second_entity_key'):
                key = best.get(column, '')
                if key and key not in accepted:
                    promoted = next((x for x in rows if x['action'] == 'entity'
                                     and x['entity_key'] == key
                                     and x['status'] in ('pending', 'needs_attention')), None)
                    if promoted:
                        best = promoted
                        break
        order.append(best['candidate_key'])
        if best['status'] == 'needs_attention':
            best['status'] = 'dismissed'          # must be corrected; never silently accepted
            continue
        if accept(best, accepted) is None:
            best['status'] = 'accepted'
            if best['action'] == 'entity':
                accepted.add(best['entity_key'])
        else:
            best['status'] = 'dismissed'
    return order


staged, _ = snapshot_queue(GOOD)
order = load_sequence(staged)
check(len(order) == len(GOOD) and set(order) == {x['candidate_key'] for x in GOOD},
      'C: every candidate is offered exactly once across the session', f'order={order}')
check(order.index('R1') < min(order.index(k) for k in ('R2', 'R3', 'R4')),
      'C: P1 entity is offered before every P1 dependent', f'order={order}')
check(order.index('R5') < order.index('R6'),
      'C: O1 entity is promoted ahead of the earlier affiliation statement', f'order={order}')

# The promotion must not re-offer an entity already accepted in a prior run.
staged, _ = snapshot_queue(GOOD)
for row in staged:
    if row['candidate_key'] == 'R5':
        row['status'] = 'accepted'
order = load_sequence(staged)
check('R5' not in order, 'C: an already-accepted entity is not offered again', f'order={order}')

# Reload is idempotent: re-snapshotting the identical run stages identical work.
first, _ = snapshot_queue(GOOD)
second, _ = snapshot_queue(GOOD)
check(all(a['start_utf16'] == b['start_utf16'] and a['status'] == b['status']
          for a, b in zip(first, second)),
      'C: an identical re-snapshot produces identical staging')

# --------------------------------------------------------------------------
print(f'\n{len(passed)} passed, {len(failures)} failed\n')
for f in failures:
    print('  FAIL  ' + f)
if failures:
    print(f'\n{len(failures)} contract gaps. These are prompt/contract defects, not test errors.')
    sys.exit(1)
print('Prompt and queue contract hold for every case. Models the VBA rules; does not execute VBA.')
