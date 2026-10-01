import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const outputDir = path.dirname(fileURLToPath(import.meta.url));
const fields = ['Entity Name', 'category', 'address', 'city', 'state', 'zip', 'phone number', 'TIN'];
const rawPairs = [
  ['W01', 'C104', 'Harbor Legal', ['Harbor Legal', 'legal', '10 Bay Street', 'Exampleton', 'IL', '00000', '555-0101', 'TRAINING-001'], 'Harbor Legal', ['Harbor Legal', 'legal', '', '', '', '', '', ''], '100'],
  ['W02', 'C104', 'Harbor Legal', ['Harbor Legal', 'legal', '10 Bay Street', 'Exampleton', 'IL', '00000', '555-0101', 'TRAINING-001'], 'Harbor Legal', ['Harbor Legal', 'legal', '10 Bay Street', 'Exampleton', 'IL', '00000', '', 'TRAINING-001'], '100'],
  ['W03', 'C104', 'Maya Chen', ['Maya Chen', 'person', '', '', '', '', '', 'TRAINING-002'], 'Maya Chen', ['Maya Chen', 'person', '', '', '', '', '', 'TRAINING-003'], '100'],
];
const pairHeaders = ['pair_id', 'Claim number', 'watchlist entity name', ...fields.map(x => `watchlist ${x}`), 'system identified entity name', ...fields.map(x => `system ${x}`), 'Similarity Score'];
const pairs = rawPairs.map(([id, claim, watchName, watch, systemName, system, score]) => [id, claim, watchName, ...watch, systemName, ...system, score]);
const comparisons = rawPairs.flatMap(([id, , , watch, , system]) => fields.map((field, i) => [id, field, watch[i] || '', system[i] || '', watch[i] && system[i] ? (watch[i] === system[i] ? 'agrees' : 'differs') : 'missing', id === 'W01' ? (i < 2 ? 'Values agree' : 'System field blank') : id === 'W02' ? (i === 6 ? 'System phone blank' : (watch[i] ? 'Values agree' : 'Both blank')) : (i === 7 ? 'Different fictional TIN values; verify comparability before identity decision' : (watch[i] ? 'Values agree' : 'Both blank'))]));
const pairReviews = [
  ['W01', 'C104', 'insufficient_evidence', 'not_checked', '100', 'Name and category agree; all other system values are missing. Score does not establish real-world identity.', 'SME-A'],
  ['W02', 'C104', 'same_entity', 'not_checked', '100', 'Training assumption: matching name, category, address, city, state, ZIP and TIN identify the same entity; record level is comparable. Phone is missing.', 'SME-A'],
  ['W03', 'C104', 'insufficient_evidence', 'not_checked', '100', 'Names agree but supplied fictional TIN values differ. Confirm identifier validity and record level before deciding.', 'SME-A'],
];
const sourceEvidence = [['W01', 'C104', '', '', '', '', 'not_checked', 'Pair input has no note ID or source quotation'], ['W02', 'C104', '', '', '', '', 'not_checked', 'Pair input has no note ID or source quotation'], ['W03', 'C104', '', '', '', '', 'not_checked', 'Pair input has no note ID or source quotation']];
const defs = [
  ['Pair_input', pairHeaders, pairs, [12, 14, 26, ...Array(8).fill(22), 28, ...Array(8).fill(22), 16]],
  ['Field_comparison', ['pair_id', 'field', 'watchlist value', 'system value', 'comparison', 'review_note'], comparisons, [12, 20, 30, 30, 16, 70]],
  ['Pair_review', ['pair_id', 'Claim number', 'identity_decision', 'source_verification', 'Similarity Score', 'review_reason', 'reviewer'], pairReviews, [12, 14, 24, 22, 16, 78, 16]],
  ['Source_evidence', ['pair_id', 'Claim number', 'note_id', 'exact_text', 'occurrence', 'entity_ref', 'source_verification', 'review_note'], sourceEvidence, [12, 14, 14, 30, 14, 14, 22, 70]],
];
function col(n) { let s = ''; for (n++; n; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + (n - 1) % 26) + s; return s; }
for (const [filename, template] of [['watchlist-review-example.xlsx', false], ['watchlist-review-template.xlsx', true]]) {
  const workbook = Workbook.create();
  for (const [sheetName, headers, data, widths] of defs) {
    const sheet = workbook.worksheets.add(sheetName); sheet.showGridLines = false;
    const source = sheetName === 'Pair_input';
    const body = template ? Array.from({ length: 5 }, () => headers.map(() => null)) : data;
    const end = col(headers.length - 1);
    sheet.getRange(`A1:${end}${body.length + 4}`).format.font = { name: 'Arial', size: 11, color: '#172B42' };
    sheet.getRange('A1').values = [[template ? 'Blank watchlist review form' : 'Fictional completed example']];
    sheet.getRange('A1').format.font = { name: 'Arial', size: 15, bold: true };
    sheet.getRange('A2').values = [[template ? (source ? 'Coordinator pastes the unaltered pair data. Preserve it.' : 'SME fills amber cells. Follow the HTML tutorial.') : (source ? 'Training data only. Values are fictional.' : 'Completed training example only. Do not distribute answers to independent reviewers.')]];
    sheet.getRange('A2').format.font = { name: 'Arial', size: 10, italic: true, color: '#526170' };
    sheet.getRange(`A4:${end}${body.length + 4}`).values = [headers, ...body];
    sheet.getRange(`A4:${end}4`).format = { fill: '#243E59', font: { name: 'Arial', size: 11, bold: true, color: '#FFFFFF' }, wrapText: true, rowHeight: 38 };
    sheet.getRange(`A5:${end}${body.length + 4}`).format = { wrapText: true, verticalAlignment: 'top', rowHeight: 46, fill: template && !source ? '#FFF1CC' : '#FFFFFF' };
    widths.forEach((width, i) => sheet.getRange(`${col(i)}4:${col(i)}${body.length + 4}`).format.columnWidth = width);
    sheet.getRange(`A4:${end}${body.length + 4}`).setNumberFormat('@');
    sheet.freezePanes.freezeRows(4); sheet.freezePanes.freezeColumns(2);
    sheet.tables.add(`A4:${end}${body.length + 4}`, true, `${filename.replaceAll(/[^a-z]/gi, '')}${sheetName.replaceAll('_', '')}`);
    if (sheetName === 'Field_comparison') sheet.getRange(`E5:E${body.length + 4}`).dataValidation = { rule: { type: 'list', values: ['agrees', 'differs', 'missing', 'unclear'] } };
    if (sheetName === 'Pair_review') {
      sheet.getRange(`C5:C${body.length + 4}`).dataValidation = { rule: { type: 'list', values: ['same_entity', 'different_entity', 'insufficient_evidence', 'needs_context'] } };
      sheet.getRange(`D5:D${body.length + 4}`).dataValidation = { rule: { type: 'list', values: ['not_checked', 'supported', 'ambiguous', 'unsupported', 'needs_context'] } };
    }
  }
  workbook.recalculate();
  await (await SpreadsheetFile.exportXlsx(workbook)).save(path.join(outputDir, filename));
}
