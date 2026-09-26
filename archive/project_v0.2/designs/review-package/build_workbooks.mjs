import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const out = path.dirname(fileURLToPath(import.meta.url));
const notes = [
 ['C104','N01',1,'TEXT-1','Maya Chen called. She said Elena Ruiz of Harbor Legal represents her.'],
 ['C104','N02',2,'TEXT-1','Harbor Legal emailed Maya Chen. Harbor Legal requested a reply. The firm asked Elena Ruiz to respond.'],
];
const mentionSpecs = [
 ['M01','N01','Maya Chen',1,'E1','name','resolved','', 'Named caller'],
 ['M02','N01','She',1,'E1','pronoun','resolved','', 'Same speaker as Maya Chen'],
 ['M03','N01','Elena Ruiz',1,'E2','name','resolved','', 'Named representative'],
 ['M04','N01','Harbor Legal',1,'E3','name','resolved','', 'Named organization'],
 ['M05','N01','her',1,'E1','pronoun','resolved','', 'Maya reports her representation'],
 ['M06','N02','Harbor Legal',1,'E3','name','resolved','', 'Same named firm in claim context'],
 ['M07','N02','Maya Chen',1,'E1','name','resolved','', 'Same addressee in claim context'],
 ['M08','N02','Harbor Legal',2,'E3','name','resolved','', 'Second literal occurrence in this note'],
 ['M09','N02','The firm',1,'E3','description','resolved','', 'Refers to Harbor Legal in preceding sentences'],
 ['M10','N02','Elena Ruiz',1,'E2','name','resolved','', 'Same representative in claim context'],
];
const mentions = mentionSpecs.map(([id,note,text,nth,ent,form,status,candidates,reason])=>[id,'C104',note,text,nth,ent,form,status,candidates,reason,'SME-A']);
const entities = [
 ['E1','Maya Chen','person','caller / represented party','M01; M02; M05; M07'],
 ['E2','Elena Ruiz','person','representative','M03; M10'],
 ['E3','Harbor Legal','organization','firm','M04; M06; M08; M09'],
];
const records = [
 ['C104','N01','Maya Chen','exact_text_search','R01'],
 ['C104','N01','Harbor Legal','exact_text_search','R02'],
 ['C104','N02','Harbor Legal','exact_text_search','R03'],
 ['C104','N02','Harbor Legal','exact_text_search','R04'],
 ['C104','N02','Maya Chen','exact_text_search','R05'],
 ['C104','N01','Maya Chen','genAI','R06'],
 ['C104','N01','Elena Ruiz','genAI','R07'],
 ['C104','N01','Harbor Legal','genAI','R08'],
 ['C104','N02','Maya Chen','genAI','R09'],
 ['C104','N02','Elena Ruiz','genAI','R10'],
 ['C104','N02','Harbor Legal','genAI','R11'],
];
const evidence = mentionSpecs.map(([id,note,text,nth,ent])=>['S'+id.slice(1),'C104',note,text,nth,ent]);
const silver = [
 ['R01','supported','E1','S01','literal','One unique literal source location','SME-A'],
 ['R02','supported','E3','S04','literal','One unique literal source location','SME-A'],
 ['R03','supported_multiple_locations','E3','S06; S08','candidate_locations','Presence supported; row cannot be assigned to one occurrence from the four source fields','SME-A'],
 ['R04','supported_multiple_locations','E3','S06; S08','candidate_locations','Presence supported; do not invent a one-to-one allocation using row order','SME-A'],
 ['R05','supported','E1','S07','literal','One unique literal source location','SME-A'],
 ['R06','supported','E1','S01; S02; S05','referent','One entity-note row linked to a name and two resolved pronouns','SME-A'],
 ['R07','supported','E2','S03','referent','Entity supported by exact source wording','SME-A'],
 ['R08','supported','E3','S04','referent','Entity supported by exact source wording','SME-A'],
 ['R09','supported','E1','S07','referent','Unique entity in this note','SME-A'],
 ['R10','supported','E2','S10','referent','Unique entity in this note','SME-A'],
 ['R11','supported','E3','S06; S08; S09','referent','One entity-note row covers two names and the resolved description The firm','SME-A'],
];
const reviews = [
 ['C104','N01','SME-A','complete','blind','No unresolved references in this training note'],
 ['C104','N02','SME-A','complete','blind','Firm and named parties linked using the full two-note claim context'],
];
const goldDefs=[
 ['Mentions',['mention_id','claim_number','note_id','exact_text','occurrence','entity_ref','mention_form','resolution','candidates','reason','reviewer'],mentions,[12,14,12,24,12,12,15,14,18,45,14]],
 ['Entities',['entity_ref','display_name','entity_type','contextual_role','supporting_mentions'],entities,[14,25,18,30,38]],
 ['Claim_notes',['claim_number','note_id','note_order','source_version','full_note_text'],notes,[14,12,14,18,110]],
 ['Review_log',['claim_number','note_id','reviewer','completion','review_stage','review_note'],reviews,[14,12,16,20,18,65]],
];
const silverDefs=[
 ['Record_review',['record_id','review_result','entity_ref','evidence_ids','evidence_relation','review_reason','reviewer'],silver,[14,30,14,25,25,78,14]],
 ['Evidence',['evidence_id','claim_number','note_id','exact_text','occurrence','entity_ref'],evidence,[14,14,12,28,14,14]],
 ['Client_records',['claim_number','note_id','entity_record','Identification_type','record_id'],records,[14,12,28,26,14]],
 ['Claim_notes',['claim_number','note_id','note_order','source_version','full_note_text'],notes,[14,12,14,18,110]],
];
function col(n){let s='';for(n++;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;}
await fs.mkdir(path.join(out,'previews'),{recursive:true});
for(const [name,defs,template] of [['gold-annotation-example',goldDefs,false],['gold-annotation-template',goldDefs,true],['silver-review-example',silverDefs,false],['silver-review-template',silverDefs,true]]){
 const wb=Workbook.create();
 for(const [sn,headers,data,widths] of defs){
  const sh=wb.worksheets.add(sn); sh.showGridLines=false;
  const rows=template?Array.from({length:5},()=>headers.map(()=>null)):data;
  const end=col(headers.length-1);
  sh.getRange(`A1:${end}${rows.length+4}`).format.font={name:'Arial',size:11,color:'#172B42'};
  sh.getRange('A1').values=[[template?'Blank review form': 'Fictional completed example']];
  sh.getRange('A1').format.font={name:'Arial',size:15,bold:true};
  const source=sn==='Claim_notes'||sn==='Client_records';
  sh.getRange('A2').values=[[template?(source?'Coordinator fills source rows. Preserve supplied wording and identifiers.':'SME fills amber cells. Keep unresolved judgments explicit. See the printed guide.'):(source?'Training data only. Claim C104 contains both notes shown here.':'Completed example only. Do not distribute answer tabs in a blind annotation assignment.')]];
  sh.getRange('A2').format.font={name:'Arial',size:10,italic:true,color:'#526170'};
  sh.getRange(`A4:${end}${rows.length+4}`).values=[headers,...rows];
  sh.getRange(`A4:${end}4`).format={fill:'#243E59',font:{name:'Arial',size:11,bold:true,color:'#FFFFFF'},wrapText:true,rowHeight:34};
  sh.getRange(`A5:${end}${rows.length+4}`).format={wrapText:true,verticalAlignment:'top',rowHeight:sn==='Claim_notes'?52:40,fill:template&&!source?'#FFF1CC':'#FFFFFF'};
  widths.forEach((w,i)=>sh.getRange(`${col(i)}4:${col(i)}${rows.length+4}`).format.columnWidth=w);
  sh.getRange(`A4:${end}${rows.length+4}`).setNumberFormat('@');
  sh.getRange(`A4:${end}4`).format.verticalAlignment='center';
  const num=headers.indexOf('occurrence')>=0?headers.indexOf('occurrence'):headers.indexOf('note_order');
  if(num>=0)sh.getRange(`${col(num)}5:${col(num)}${rows.length+4}`).setNumberFormat('0');
  sh.freezePanes.freezeRows(4); sh.freezePanes.freezeColumns(sn==='Mentions'?3:1);
  sh.tables.add(`A4:${end}${rows.length+4}`,true,name.replaceAll('-','')+sn.replaceAll('_',''));
  const validation = sn==='Mentions'?['H',['resolved','ambiguous','unknown']]:sn==='Record_review'?['B',['supported','supported_multiple_locations','ambiguous','unsupported','needs_context']]:sn==='Review_log'?['D',['complete','no_findings','needs_context','blocked']]:null;
  if(validation)sh.getRange(`${validation[0]}5:${validation[0]}${rows.length+4}`).dataValidation={rule:{type:'list',values:validation[1]}};
 }
 wb.recalculate();
 console.log((await wb.inspect({kind:'table',range:`${defs[0][0]}!A4:F7`,include:'values',tableMaxRows:4,tableMaxCols:6,maxChars:1800})).ndjson);
 for(const [sn,headers,data]of defs){
   const last=Math.min(headers.length-1,5);
   const preview=await wb.render({sheetName:sn,range:`A1:${col(last)}${Math.min((template?5:data.length)+4,9)}`,scale:1,format:'png'});
   await fs.writeFile(path.join(out,'previews',`${name}-${sn}.png`),new Uint8Array(await preview.arrayBuffer()));
 }
 await(await SpreadsheetFile.exportXlsx(wb)).save(path.join(out,name+'.xlsx'));
}
// Source-level address example for analysts; no system chunk IDs are used.
const manifest=mentionSpecs.map(([id,note,text,nth])=>{
 const raw=notes.find(r=>r[1]===note)[4];let start=-1;for(let i=0;i<nth;i++)start=raw.indexOf(text,start+1);
 if(start<0)throw Error('Unlocatable example '+id);
 return {mention_id:id,claim_number:'C104',note_id:note,source_version:'TEXT-1',text,start_character:start,end_character:start+text.length};
});
await fs.writeFile(path.join(out,'source-evidence-example.json'),JSON.stringify(manifest,null,2)+'\n');
for(const [claim,note,,,text]of notes)await fs.writeFile(path.join(out,`${claim}_${note}.txt`),text,'utf8');
