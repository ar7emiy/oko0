import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const html=fs.readFileSync('EXCEL-ANNOTATION-WORKBENCH-TUTORIAL.html','utf8');
const elements=new Map();
function el(id){if(!elements.has(id))elements.set(id,{id,value:'',textContent:'',innerHTML:'',children:[],classList:{toggle(){}},append(x){this.children.push(x);}});return elements.get(id);}
const sandbox={document:{getElementById:el,createElement:()=>({textContent:'',onclick:null,classList:{toggle(){}}}),querySelectorAll:()=>el('nav').children},confirm:()=>true,location:{reload(){}}};
vm.createContext(sandbox);vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],sandbox);
assert.equal(el('nav').children.length,11);
assert.match(el('note').innerHTML,/<mark>Dr\. Ada Monroe<\/mark>/);
for(let i=0;i<10;i++){el('nav').children[i].onclick();el('save').onclick();assert.match(el('status').textContent,/Saved A/);}
assert.match(el('rows').innerHTML,/001234567/);
assert.match(el('rows').innerHTML,/did not schedule/);
el('previous').onclick();assert.equal(el('quote').value,'The clinic did not schedule surgery');
el('reason').value='Confirmed negation against full text.';el('save').onclick();assert.match(el('rows').innerHTML,/Confirmed negation/);
el('manual').onclick();el('quote').value='hallucinated quote';el('save').onclick();assert.match(el('status').textContent,/Cannot save/);
el('manual').onclick();el('kind').value='context';el('quote').value='medical provider';el('entity').value='E2';el('save').onclick();assert.match(el('status').textContent,/Saved A11/);
el('complete').onclick();assert.match(el('status').textContent,/read every paragraph/);
console.log('PASS: tutorial event handlers, highlights, ten guided saves, revision, hallucinated evidence rejection, manual entry and completeness guidance. DOM simulation, not browser rendering.');
