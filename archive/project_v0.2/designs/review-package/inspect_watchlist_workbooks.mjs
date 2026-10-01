import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';

const directory = path.dirname(fileURLToPath(import.meta.url));
for (const filename of ['watchlist-review-example.xlsx', 'watchlist-review-template.xlsx']) {
  const input = await FileBlob.load(path.join(directory, filename));
  const workbook = await SpreadsheetFile.importXlsx(input);
  const names = workbook.worksheets.items.map(sheet => sheet.name);
  if (names.join('|') !== 'Pair_input|Field_comparison|Pair_review|Source_evidence') throw new Error(`${filename}: sheets mismatch`);
  const summaries = [];
  for (const sheetName of names) {
    const view = await workbook.render({ sheetName, range: 'A1:H9', scale: 1.2, format: 'png' });
    await fs.writeFile(path.join(directory, 'previews', `${filename.replace('.xlsx', '')}-${sheetName}.png`), new Uint8Array(await view.arrayBuffer()));
    summaries.push(await workbook.inspect({ kind: 'table', range: `${sheetName}!A1:H9`, include: 'values', tableMaxRows: 9, tableMaxCols: 8, maxChars: 3000 }));
  }
  await fs.writeFile(path.join(directory, `${filename}.qa.ndjson`), summaries.map(x => x.ndjson).join('\n'));
  console.log(`PASS ${filename}: ${names.length} sheets rendered and inspected`);
}
