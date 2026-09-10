"""Portable structure/reference tests. Not a VBA interpreter or Excel runtime test."""
import csv
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
schema = json.loads((ROOT / 'workbench-schema.json').read_text())
known = {v['table']:v['headers'] for v in schema.values()}
modules = list(ROOT.glob('*.bas'))
source = '\n'.join(p.read_text(encoding='utf-8-sig') for p in modules)
checks = []
def check(ok, label):
    if not ok: raise AssertionError(label)
    checks.append(label)

check(len(modules) == 8, 'Eight VBA modules supplied')
for p in modules:
    body=p.read_text(encoding='utf-8-sig')
    check('Option Explicit' in body, p.name + ': explicit declarations')
    starts=re.findall(r'^\s*(?:Public |Private )?(?:Sub|Function)\s+(\w+)\s*\(',body,re.M)
    ends=re.findall(r'^\s*End (?:Sub|Function)\s*$',body,re.M)
    check(len(starts)==len(ends), p.name + ': balanced procedures')
    check(max(map(len,body.splitlines())) < 1024,p.name + ': VBA physical line limit')
    globals_=set(re.findall(r'^(?:Public|Private) (?!Sub |Function |Declare |Type )(\w+)\b',body,re.M)) | set(re.findall(r'^Public (?!Sub |Function |Declare |Type )(\w+)\b',source,re.M))
    for proc in re.finditer(r'^\s*(?:Public |Private )?(?:Sub|Function)\s+(\w+)\s*\(([^\n]*)\)([^\n]*)\n([\s\S]*?)^\s*End (?:Sub|Function)\s*$',body,re.M):
        name,params,_,block=proc.groups()
        block=re.sub(r'"(?:[^"]|"")*"','""',block)
        block=re.sub(r"'.*",'',block)
        declared=set(re.findall(r'(?:ByVal |ByRef )?(\w+)\s+As ',params))|globals_|{name}
        for declaration in re.findall(r'^\s*Dim (.+)$',block,re.M):
            declared.update(re.findall(r'(?:^|,)\s*(\w+)',declaration))
        assigned=set(re.findall(r'(?:^|:)\s*(?:Set )?(\w+)\s*=',block,re.M))
        assigned.update(re.findall(r'\bFor (?:Each )?(\w+)\b',block))
        check(not assigned-declared,p.name+': declared assignment targets in '+name+' '+str(assigned-declared))
procedures=set(re.findall(r'^\s*(?:Public |Private )?(?:Sub|Function)\s+(\w+)\s*\(',source,re.M))
for table in re.findall(r'T\("(t\w+)"\)',source): check(table in known,'Known table '+table)
columns={h for headers in known.values() for h in headers}
for module in modules:
    body=re.sub(r"'.*",'',module.read_text(encoding='utf-8-sig'))
    used={m.group(1) for m in re.finditer(r'\b(?:SetV|V)\s*\(?\s*\w+\s*,\s*\w+\s*,\s*"([a-z_]+)"',body)}
    check(not used-columns,module.name+': column names exist in the schema '+str(sorted(used-columns)))
# A procedure named after a VBA statement keyword parses as that statement at the call
# site, not as a call, and fails to compile. This is invisible until Excel runs the code.
VBA_STATEMENTS={'put','get','close','open','print','write','input','line','name','kill','seek','lock',
 'unlock','width','reset','erase','load','unload','beep','chdir','chdrive','mkdir','rmdir','filecopy',
 'setattr','randomize','sendkeys','appactivate','deletesetting','savesetting','error','date','time',
 'stop','let','set','call','end','exit','next','loop','wend','resume','return','circle','pset','scale',
 'option','declare','type','const','dim','redim','static','with','on','goto','gosub','select','case','if'}
for module in modules:
    for name in re.findall(r'^\s*(?:Public |Private )?(?:Sub|Function)\s+(\w+)\s*\(',module.read_text(encoding='utf-8-sig'),re.M):
        check(name.lower() not in VBA_STATEMENTS,module.name+': '+name+' is not a VBA statement keyword')
for macro in re.findall(r'^\s*Button "[^"]+", "[^"]+", "[^"]+", "([^"]+)"',source,re.M):
    check(macro in procedures,'Wired procedure '+macro)
for t in ['tEntries','tQueue','tDrafts']:
    check(known[t][4:16]==['action','source_quote','occurrence','entity_ref' if t!='tQueue' else 'entity_key','display_name','entity_type','reference_form','field_kind','field_value','second_entity_ref' if t!='tQueue' else 'second_entity_key','open_label','reason'],t+' form column contract')
check(not re.search(r'\.(?:Merge|UnMerge)\b',source),'No VBA merge mutations')
prompt_text=(ROOT/'COPILOT-PROMPT.md').read_text(encoding='utf-8')
prompt_version=re.search(r'prompt version (\d+)',prompt_text).group(1)
check('"prompt-v'+prompt_version+'"' in source,'Archived prompt version matches COPILOT-PROMPT.md (v'+prompt_version+')')
snapshot_sub=re.search(r'Public Sub SaveQueueSnapshot[\s\S]*?^End Sub',source,re.M).group(0)
# Scoped to the sentences that name the sheet: the same address on another sheet must not satisfy this.
analysis_text=' '.join(l for l in prompt_text.splitlines() if 'AI Analysis Input' in l)
for cell in sorted(set(re.findall(r'ws\.Range\("([A-Z]+\d+)"\)',snapshot_sub))):
    check(cell in analysis_text,'Prompt names AI Analysis Input cell '+cell+' where it names that sheet')
check('LastRow' not in re.search(r'Public Function NewID.*?End Function',source,re.S).group(0),'IDs independent of worksheet row')

with zipfile.ZipFile(ROOT/'Entity-Gold-Review-Macro-Free.xlsx') as z:
    workbook=ET.fromstring(z.read('xl/workbook.xml'))
    sheets=[s.attrib['name'] for s in workbook.find('s:sheets',NS)]
    check(set(schema).issubset(sheets),'All backend pages exported')
    names={}
    for name in z.namelist():
        if re.match(r'xl/tables/table\d+\.xml$',name):
            table=ET.fromstring(z.read(name)); names[table.attrib['name']]=[x.attrib['name'] for x in table.find('s:tableColumns',NS)]
        if re.match(r'xl/worksheets/sheet\d+\.xml$',name):
            sheet=ET.fromstring(z.read(name));check(sheet.find('s:mergeCells',NS) is None,name+': unmerged')
            check(not any(c.attrib.get('t')=='e' for c in sheet.findall('.//s:c',NS)),name+': no Excel error cells')
    check(names==known,'Exported table names and columns match VBA contract')
    check(not any('vbaProject' in n for n in z.namelist()),'Delivered template is macro-free')

# Independent reference behavior for the exact-match / storage contract.
def split_utf16(s):
    data=s.encode('utf-16-le'); chunks=[]
    while data:
        n=min(len(data),16000)
        if n<len(data) and 0xD800<=int.from_bytes(data[n-2:n],'little')<=0xDBFF:n-=2
        chunks.append(data[:n].decode('utf-16-le'));data=data[n:]
    return chunks
for n in [32766,32767,32768,100000]:
    s='x'*7999+'😀'+'e\u0301\r\n'+'y'*n
    parts=split_utf16(s)
    check(''.join(parts)==s and all(len(p.encode('utf-16-le'))<=16000 for p in parts),'Unicode/long-note reference round trip '+str(n))
    check(s.index('x😀e')==7998,'Cross-part evidence location '+str(n))
sample='Dr. Ada Monroe called. Dr. Ada Monroe replied.'
check(sample.index('Dr. Ada Monroe')==0,'First word reference offset')
check(sample.index('Dr. Ada Monroe',1)>0,'Repeated mention reference offset')
check(next(csv.reader(['"001234567","=literal","Dr, Ada"']))==['001234567','=literal','Dr, Ada'],'Literal CSV reference values')

html=(ROOT/'EXCEL-ANNOTATION-WORKBENCH-TUTORIAL.html').read_text(encoding='utf-8')
check('fetch(' not in html and '<script src=' not in html,'Tutorial has no network dependencies')
(ROOT/'tutorial-script.check.js').write_text(re.search(r'<script>([\s\S]*?)</script>',html).group(1),encoding='utf-8')
report={'checks_passed':len(checks),'scope':'Workbook XML, VBA structure/contracts, independent algorithm references; NOT VBA runtime execution','runtime_status':'Windows Excel and Copilot acceptance pending','checks':checks}
(ROOT/'verification-results.json').write_text(json.dumps(report,indent=2))
print(f"PASS: {len(checks)} portable checks. Windows Excel execution remains unverified.")
