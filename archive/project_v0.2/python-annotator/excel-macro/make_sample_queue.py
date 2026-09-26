"""Create a literal TSV queue for an existing fictional sample note; no AI needed."""
import csv,json
from pathlib import Path
p=Path(__file__).resolve().parent
headers=json.loads((p/'workbench-schema.json').read_text())['AI Queue']['headers']
rows=[
 dict(candidate_key='R1',action='entity',source_quote='Dr. Ada Monroe',occurrence='1',entity_key='P1',display_name='Dr. Ada Monroe',entity_type='person'),
 dict(candidate_key='R2',action='statement',source_quote='called regarding the claim',occurrence='1',entity_key='P1'),
 dict(candidate_key='R3',action='reference',source_quote='Dr. Ada Monroe',occurrence='2',entity_key='P1',reference_form='name'),
 dict(candidate_key='R4',action='context',source_quote='orthopedic surgeon',occurrence='1',entity_key='P1'),
 dict(candidate_key='R5',action='entity',source_quote='Northstar Orthopedics',occurrence='1',entity_key='O1',display_name='Northstar Orthopedics',entity_type='organization'),
 dict(candidate_key='R6',action='statement',source_quote='with Northstar Orthopedics',occurrence='1',entity_key='P1',second_entity_key='O1',reason='Proposed affiliation; verify in context.'),
 dict(candidate_key='R7',action='reference',source_quote='the medical provider',occurrence='1',entity_key='O1',reference_form='description'),
 dict(candidate_key='R8',action='context',source_quote='medical provider',occurrence='1',entity_key='O1')]
with (p/'SAMPLE-C201-N01-QUEUE.tsv').open('w',newline='',encoding='utf-8') as f:
 w=csv.DictWriter(f,fieldnames=headers,delimiter='\t');w.writeheader();w.writerows(rows)
print('Sample queue written for existing C201_N01.txt; affiliation dependency requires organization first.')
