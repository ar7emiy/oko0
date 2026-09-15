import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const input = await FileBlob.load("Entity-Gold-Review-Macro-Free.xlsx");
const workbook = await SpreadsheetFile.importXlsx(input);
await workbook.recalculate();
const checks = await Promise.all([
  workbook.inspect({ kind: "table", range: "Review Desk!B2:M43", include: "values,formulas", tableMaxRows: 43, tableMaxCols: 12 }),
  workbook.inspect({ kind: "table", range: "Context!A2:I8", include: "values", tableMaxRows: 8, tableMaxCols: 9 }),
  workbook.inspect({ kind: "table", range: "Statements!A2:J8", include: "values", tableMaxRows: 8, tableMaxCols: 10 }),
  workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 100 }, summary: "formula error scan" }),
]);
await fs.writeFile("Entity-Gold-Review-Macro-Free.checks.ndjson", checks.map(check => check.ndjson).join("\n"));
await fs.mkdir("macro-free-preview", { recursive: true });
const preview = await workbook.render({ sheetName: "Review Desk", range: "A1:M60", scale: 1.25, format: "png" });
await fs.writeFile("macro-free-preview/Review-Desk.png", new Uint8Array(await preview.arrayBuffer()));
console.log(checks.map(check => check.ndjson).join("\n"));
