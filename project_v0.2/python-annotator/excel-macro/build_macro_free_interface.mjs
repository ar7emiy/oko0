import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const workbook = Workbook.create();
const outputPath = "Entity-Gold-Review-Macro-Free.xlsx";
const NAVY = "#18344C";
const TEAL = "#08766A";
const YELLOW = "#FFF8D8";
const WHITE = "#FFFFFF";
const GRAY = "#E7EEF2";
const MINT = "#DFF5ED";
const BLUE = "#E6EFFF";
const PURPLE = "#EADCFF";
const PEACH = "#FFD9C7";
const ORANGE = "#FFE2B7";
const ROWS = 205;

function setColumns(sheet, widths) {
  widths.forEach((width, index) => sheet.getRangeByIndexes(0, index, 1, 1).format.columnWidth = width);
}

function heading(sheet, range, text, color = NAVY) {
  sheet.getRange(range).merge();
  sheet.getRange(range.split(":")[0]).values = [[text]];
  sheet.getRange(range.split(":")[0]).format = { fill: color, font: { name: "Segoe UI", size: 11, bold: true, color: WHITE }, verticalAlignment: "center" };
}

function input(sheet, range, text = "") {
  sheet.getRange(range).merge();
  sheet.getRange(range.split(":")[0]).values = [[text]];
  sheet.getRange(range).format = { fill: YELLOW, font: { name: "Segoe UI", size: 10, color: NAVY }, wrapText: true, verticalAlignment: "top", borders: { preset: "all", style: "thin", color: "#AABBC5" } };
}

function actionCell(sheet, range, label, color, note) {
  sheet.getRange(range).merge();
  sheet.getRange(range.split(":")[0]).values = [[label]];
  sheet.getRange(range).format = { fill: color, font: { name: "Segoe UI", size: 10, bold: true, color: NAVY }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true, borders: { preset: "all", style: "thin", color: WHITE } };
  sheet.getRange(range.split(":")[0]).note = note;
}

function backendSheet(name, headers, instructions, color) {
  const sheet = workbook.worksheets.add(name);
  sheet.showGridLines = false;
  sheet.getRangeByIndexes(1, 0, 1, headers.length).merge();
  sheet.getRange("A2").values = [[name]];
  sheet.getRange("A2").format = { font: { name: "Segoe UI", size: 15, bold: true, color: NAVY } };
  sheet.getRangeByIndexes(2, 0, 1, headers.length).merge();
  sheet.getRange("A3").values = [[instructions]];
  sheet.getRange("A3").format = { font: { name: "Segoe UI", size: 10, italic: true, color: "#486273" }, wrapText: true };
  sheet.getRangeByIndexes(4, 0, 1, headers.length).values = [headers];
  sheet.getRangeByIndexes(4, 0, 1, headers.length).format = { fill: color, font: { name: "Segoe UI", size: 10, bold: true, color: NAVY }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true, borders: { preset: "all", style: "thin", color: WHITE } };
  sheet.getRangeByIndexes(4, 0, 1, headers.length).format.rowHeight = 32;
  const body = sheet.getRangeByIndexes(5, 0, ROWS - 5, headers.length);
  body.format = { fill: YELLOW, font: { name: "Segoe UI", size: 10, color: NAVY }, verticalAlignment: "top", wrapText: true, borders: { preset: "insideHorizontal", style: "thin", color: "#E2E9ED" } };
  for (let col = 0; col < headers.length; col += 1) sheet.getRangeByIndexes(0, col, 1, 1).format.columnWidth = col === headers.length - 1 ? 34 : 18;
  sheet.freezePanes.freezeRows(5);
  return sheet;
}

const desk = workbook.worksheets.add("Review Desk");
desk.showGridLines = false;
setColumns(desk, [2, 20, 20, 13, 13, 13, 3, 18, 3, 15, 24, 16, 12, 2]);
heading(desk, "B2:M2", "Gold Annotation Workbench");
desk.getRange("B2").format.font = { name: "Segoe UI", size: 18, bold: true, color: WHITE };
desk.getRange("B2:M2").format.rowHeight = 34;
desk.getRange("B3:M3").merge();
desk.getRange("B3").values = [["Macro-free interface preview. Once ReviewWorkflow.bas is imported into this workbook as an .xlsm file, the action cells become automated buttons and the output tabs can be hidden."]];
desk.getRange("B3").format = { font: { name: "Segoe UI", size: 10, italic: true, color: "#486273" }, wrapText: true };
desk.getRange("B3:M3").format.rowHeight = 28;

desk.getRange("B4").values = [["Claim number"]]; desk.getRange("B5").values = [["Note ID"]];
desk.getRange("B4:B5").format.font = { name: "Segoe UI", size: 10, bold: true, color: NAVY };
input(desk, "C4:F4"); input(desk, "C5:F5");
heading(desk, "B7:F7", "Paste exact source text from Notepad here");
input(desk, "B8:F12"); desk.getRange("B8:F12").format.rowHeight = 25;

heading(desk, "B14:F14", "Tell Excel what the selected wording means", TEAL);
const fields = [["B15", "Entity reference"], ["B16", "Display name"], ["B17", "Entity type"], ["B18", "Reference form"], ["B19", "Field kind"], ["B21", "Second entity"], ["B22", "Optional open label"], ["B23", "Notes / reason"]];
fields.forEach(([cell, label]) => { desk.getRange(cell).values = [[label]]; desk.getRange(cell).format.font = { name: "Segoe UI", size: 10, bold: true, color: NAVY }; });
["C15:F15", "C16:F16", "C17:F17", "C18:F18", "C19:F20", "C21:F21", "C22:F22", "C23:F24"].forEach(range => input(desk, range));
desk.getRange("C17").dataValidation = { rule: { type: "list", values: ["person", "organization", "location", "other", "unknown"] } };
desk.getRange("C18").dataValidation = { rule: { type: "list", values: ["name", "alias", "pronoun", "description"] } };
desk.getRange("C19").dataValidation = { rule: { type: "list", values: ["entity_name", "address", "city", "state", "zip_code", "phone", "TIN", "other"] } };

heading(desk, "H4:H4", "Actions");
actionCell(desk, "H6:H7", "New entity", "#FFF0A8", "Creates an E-number and the first named mention.");
actionCell(desk, "H8:H9", "Link reference", MINT, "Links a repeated name, alias, pronoun, or description to an existing E-number.");
actionCell(desk, "H10:H11", "Record field", BLUE, "Captures a directly stated field value for the selected entity.");
actionCell(desk, "H12:H13", "Record context", PURPLE, "Preserves exact descriptive wording. No category or subcategory bucket is required.");
actionCell(desk, "H14:H15", "Record statement", PEACH, "Captures source wording, one entity, and an optional second entity.");
actionCell(desk, "H16:H17", "Mark uncertain", ORANGE, "Preserves ambiguity and the reason it cannot be resolved.");
actionCell(desk, "H19:H20", "Refresh entity list", TEAL, "Shows current entities and evidence after VBA wiring.");
actionCell(desk, "H21:H22", "Seal claim", "#D9E3E8", "Enables post-Gold watchlist review after all notes are reviewed.");

heading(desk, "J4:M4", "Entities and evidence");
desk.getRange("J6:M6").values = [["Entity ref", "Display name", "Type", "Mentions"]];
desk.getRange("J6:M6").format = { fill: GRAY, font: { name: "Segoe UI", size: 10, bold: true, color: NAVY }, horizontalAlignment: "center" };
heading(desk, "J38:M38", "Evidence for selected entity", "#D9E3E8");
desk.getRange("J39:M55").merge(); desk.getRange("J39").values = [["After VBA wiring, this panel summarizes the selected entity's mentions, fields, source context, and statements."]];
desk.getRange("J39:M55").format = { fill: "#F7FAFC", font: { name: "Segoe UI", size: 10, color: NAVY }, wrapText: true, verticalAlignment: "top", borders: { preset: "all", style: "thin", color: "#AABBC5" } };

heading(desk, "B27:F27", "After Gold is sealed: review watchlist matches for this note");
[["B28", "Client row ID"], ["B29", "Identity decision"], ["B30", "Source support"], ["B31", "Reason"]].forEach(([cell, label]) => { desk.getRange(cell).values = [[label]]; desk.getRange(cell).format.font = { name: "Segoe UI", size: 10, bold: true, color: NAVY }; });
["C28:F28", "C29:F29", "C30:F30", "C31:F33"].forEach(range => input(desk, range));
desk.getRange("C29").dataValidation = { rule: { type: "list", values: ["same_entity", "different_entity", "insufficient_evidence"] } };
desk.getRange("C30").dataValidation = { rule: { type: "list", values: ["direct_note_support", "partial_note_support", "no_note_support", "ambiguous_note_support"] } };
actionCell(desk, "H27:H28", "Import client output", TEAL, "Imports the supplied client output after VBA wiring.");
actionCell(desk, "H29:H30", "Load note matches", "#D9E3E8", "Shows only watchlist pairs cited by the current claim and note.");
actionCell(desk, "H31:H32", "Save decision", TEAL, "Saves the identity decision with its evidence reason.");
heading(desk, "J57:M57", "Watchlist candidates for this note", "#D9E3E8");
desk.getRange("J58:M58").values = [["Client row", "System entity", "Watchlist candidate", "Similarity"]];
desk.getRange("J58:M58").format = { fill: GRAY, font: { name: "Segoe UI", size: 10, bold: true, color: NAVY }, horizontalAlignment: "center", wrapText: true };

heading(desk, "B36:F36", "Progress", TEAL);
desk.getRange("B37:C43").values = [["Entities", null], ["References", null], ["Fields", null], ["Context", null], ["Statements", null], ["Uncertain", null], ["Watchlist decisions", null]];
desk.getRange("C37:C43").formulas = [["=COUNTA(Entities!A6:A205)"], ["=COUNTA(Mentions!A6:A205)"], ["=COUNTA(Fields!A6:A205)"], ["=COUNTA(Context!A6:A205)"], ["=COUNTA(Statements!A6:A205)"], ["=COUNTA(Uncertain!A6:A205)"], ["=COUNTIF('Watchlist Review'!H6:H205,\"complete\")"]];
desk.getRange("B37:C43").format = { font: { name: "Segoe UI", size: 10, color: NAVY }, borders: { preset: "all", style: "thin", color: "#AABBC5" } };
desk.getRange("B37:B43").format.font = { name: "Segoe UI", size: 10, bold: true, color: NAVY };
desk.freezePanes.freezeRows(3);

backendSheet("Entities", ["entity_ref", "claim_number", "display_label", "entity_type", "first_note_id", "first_source_text", "decision"], "VBA writes entities here. The macro version hides this sheet from reviewers.", "#FFF0A8");
backendSheet("Mentions", ["mention_id", "claim_number", "note_id", "source_text", "start_character", "end_character", "entity_ref", "mention_form", "reason"], "VBA writes names, aliases, descriptions, and pronouns here.", MINT);
backendSheet("Fields", ["field_id", "claim_number", "note_id", "entity_ref", "field_name", "value", "source_text", "start_character", "end_character", "decision"], "VBA writes directly stated entity values here.", BLUE);
backendSheet("Context", ["context_id", "claim_number", "note_id", "entity_ref", "source_characterization", "start_character", "end_character", "optional_open_label", "notes"], "VBA writes exact entity-characterizing wording here. No taxonomy is required.", PURPLE);
backendSheet("Statements", ["statement_id", "claim_number", "note_id", "predicate_source_text", "start_character", "end_character", "primary_entity_ref", "second_entity_ref", "optional_open_label", "notes"], "VBA writes source-supported action and relationship wording here.", PEACH);
backendSheet("Uncertain", ["uncertain_id", "claim_number", "note_id", "source_text", "start_character", "end_character", "reason", "candidate_entity_ref"], "VBA writes unresolved source wording here.", ORANGE);
backendSheet("Watchlist Review", ["pair_review_id", "client_row_id", "claim_number", "note_id", "identity_decision", "source_support", "reason", "review_status"], "VBA writes post-Gold watchlist decisions here.", "#F9E2B7");
backendSheet("Watchlist Candidates", ["client_row_id", "claim_number", "note_id", "system_entity_name", "watchlist_entity_name", "similarity_score"], "VBA stages client watchlist records that cite the current note here.", "#D9E3E8");
backendSheet("Sealed Claims", ["claim_number", "sealed_at"], "VBA records when Gold annotation is sealed for a claim.", "#D9E3E8");
backendSheet("Raw Client Output", ["Paste or import the supplied client export with its original headers"], "The VBA import action replaces this content with the client export.", "#D9E3E8");

workbook.recalculate();
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
