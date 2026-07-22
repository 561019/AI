import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outDir = path.resolve("framework/test_cases/upload_samples");
const renderDir = path.resolve("outputs/case2_sales_reconciliation/previews");
await fs.mkdir(outDir, { recursive: true });
await fs.mkdir(renderDir, { recursive: true });

const titleFill = "#1F4E78";
const headerFill = "#D9EAF7";
const noteFill = "#FFF2CC";
const doubtFill = "#FCE4D6";
const okFill = "#E2F0D9";
const line = "#B7C9D6";

function styleTitle(range) {
  range.format = {
    fill: titleFill,
    font: { bold: true, color: "#FFFFFF", size: 14 },
    horizontalAlignment: "left",
    verticalAlignment: "center",
  };
}

function styleHeader(range) {
  range.format = {
    fill: headerFill,
    font: { bold: true, color: "#17324D" },
    borders: { preset: "all", style: "thin", color: line },
    wrapText: true,
  };
}

function styleBody(range) {
  range.format = {
    borders: { preset: "all", style: "thin", color: "#E1E7EF" },
    wrapText: true,
    verticalAlignment: "top",
  };
}

function writeTitle(sheet, text, range = "A1:H1") {
  const r = sheet.getRange(range);
  r.merge();
  r.values = [[text]];
  styleTitle(r);
}

function writeNote(sheet, cell, text) {
  const r = sheet.getRange(cell);
  r.values = [[text]];
  r.format = { fill: noteFill, wrapText: true, borders: { preset: "outside", style: "thin", color: line } };
}

function table(sheet, startRow, startCol, headers, rows, name) {
  const rowCount = rows.length + 1;
  const colCount = headers.length;
  const rg = sheet.getRangeByIndexes(startRow, startCol, rowCount, colCount);
  rg.values = [headers, ...rows];
  styleHeader(sheet.getRangeByIndexes(startRow, startCol, 1, colCount));
  styleBody(sheet.getRangeByIndexes(startRow + 1, startCol, rows.length, colCount));
  const address = `${colName(startCol + 1)}${startRow + 1}:${colName(startCol + colCount)}${startRow + rowCount}`;
  try {
    const t = sheet.tables.add(address, true, name);
    t.style = "TableStyleMedium2";
    t.showFilterButton = true;
  } catch {
    // Tables are a usability enhancement; keep workbook valid if a table name/range is rejected.
  }
}

function colName(n) {
  let s = "";
  while (n > 0) {
    const m = (n - 1) % 26;
    s = String.fromCharCode(65 + m) + s;
    n = Math.floor((n - m) / 26);
  }
  return s;
}

function fit(sheet, range = "A:K") {
  sheet.getRange(range).format.autofitColumns();
  sheet.getRange(range).format.autofitRows();
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(2);
}

async function buildDataPack() {
  const wb = Workbook.create();

  const guide = wb.worksheets.add("00_UploadGuide");
  writeTitle(guide, "案例二销售对账测试数据包：上传说明", "A1:I1");
  table(
    guide,
    2,
    0,
    ["上传顺序", "文档/Sheet", "建议上传到模块", "用途", "关键字段", "预期结果"],
    [
      [1, "PaymentFlow", "L2 数据操作引擎 data.search", "核对回款流水", "contract_id, payment_amount, freight_amount", "C-202607-001 会产生 200 元运费差异"],
      [2, "FinanceAR", "L1 数据基础模块 / 财务数据源", "提供应收与财务口径", "contract_id, tail_payment_due, finance_received", "作为回款流水核对基准"],
      [3, "ContractLedger", "L2 数据操作引擎 data.search", "核对合同登记表", "contract_id, contract_amount, received_amount", "C-202607-002 自动通过"],
      [4, "Invoices", "L2 外部系统对接引擎 external.api.call", "模拟外部发票系统取回", "invoice_title, expected_title, invoice_amount", "INV-202607-003 抬头不一致"],
      [5, "Reconciliation", "L2 规则计算引擎 rule.calculate", "确定性对账结果", "difference, status", "输出两处疑点"],
      [6, "DecisionCards", "L1 人机协同 human.task.create", "疑点确认卡", "doubt_id, decision", "付盛贤逐笔拍板"],
      [7, "FieldMapping", "平台适配器", "现有字段到平台标准字段映射", "source_field, platform_field", "用于接口传输核对"]
    ],
    "GuideTable",
  );
  writeNote(guide, "A12", "测试目的：让案例二从“没有业务数据”变成可上传、可取数、可对账、可展示疑点的验收数据。上传后应能在 trace 调用链看到每个模块收到的字段与输出结果。");
  fit(guide, "A:I");

  const payment = wb.worksheets.add("PaymentFlow");
  writeTitle(payment, "回款流水 PaymentFlow", "A1:L1");
  table(payment, 2, 0, [
    "payment_id", "project_id", "contract_id", "customer_name", "owner", "payment_date", "payment_amount", "freight_amount", "bank_serial_no", "payment_channel", "status", "evidence_ref"
  ], [
    ["PAY-202607-001", "PRJ-GZ-001", "C-202607-001", "桂中绿丰合作社", "付盛贤", new Date("2026-07-05"), 50000, 200, "BANK-20260705001", "银行转账", "已到账", "bank_slip_001.pdf"],
    ["PAY-202607-002", "PRJ-GZ-002", "C-202607-002", "南宁兴农合作社", "付盛贤", new Date("2026-07-09"), 30000, 0, "BANK-20260709002", "银行转账", "已到账", "bank_slip_002.pdf"],
    ["PAY-202607-003", "PRJ-GZ-003", "C-202607-003", "柳州丰成农资", "付盛贤", new Date("2026-07-14"), 8800, 0, "BANK-20260714003", "银行转账", "已到账", "bank_slip_003.pdf"],
    ["PAY-202607-004", "PRJ-GZ-004", "C-202607-004", "桂林农技服务站", "付盛贤", new Date("2026-07-18"), 12680.5, 0, "BANK-20260718004", "银行转账", "已到账", "bank_slip_004.pdf"]
  ], "PaymentFlowTable");
  payment.getRange("F3:F6").format.numberFormat = "yyyy-mm-dd";
  payment.getRange("G3:H6").format.numberFormat = "¥#,##0.00";
  fit(payment, "A:L");

  const ar = wb.worksheets.add("FinanceAR");
  writeTitle(ar, "财务应收 FinanceAR", "A1:K1");
  table(ar, 2, 0, [
    "ar_id", "contract_id", "customer_name", "tail_payment_due", "finance_received", "expected_freight", "due_date", "finance_status", "owner", "source_system", "remarks"
  ], [
    ["AR-202607-001", "C-202607-001", "桂中绿丰合作社", 50200, 50000, 200, new Date("2026-07-10"), "待解释差异", "付盛贤", "财务系统", "尾款与回款差额等于运费"],
    ["AR-202607-002", "C-202607-002", "南宁兴农合作社", 30000, 30000, 0, new Date("2026-07-15"), "已结清", "付盛贤", "财务系统", "一致"],
    ["AR-202607-003", "C-202607-003", "柳州丰成农资", 8800, 8800, 0, new Date("2026-07-20"), "待核发票", "付盛贤", "财务系统", "金额一致但发票抬头待核"],
    ["AR-202607-004", "C-202607-004", "桂林农技服务站", 12680.5, 12680.5, 0, new Date("2026-07-25"), "已结清", "付盛贤", "财务系统", "一致"]
  ], "FinanceARTable");
  ar.getRange("D3:F6").format.numberFormat = "¥#,##0.00";
  ar.getRange("G3:G6").format.numberFormat = "yyyy-mm-dd";
  fit(ar, "A:K");

  const contracts = wb.worksheets.add("ContractLedger");
  writeTitle(contracts, "合同登记表 ContractLedger", "A1:N1");
  table(contracts, 2, 0, [
    "contract_id", "project_id", "contract_name", "customer_name", "owner", "sign_date", "contract_amount", "tail_payment_due", "received_amount", "unreceived_amount", "contract_status", "invoice_required", "invoice_id", "attachment_ref"
  ], [
    ["C-202607-001", "PRJ-GZ-001", "桂中绿丰合作社追肥产品采购合同", "桂中绿丰合作社", "付盛贤", new Date("2026-06-28"), 100200, 50200, 50000, null, "执行中", "是", "INV-202607-001", "contract_C001.pdf"],
    ["C-202607-002", "PRJ-GZ-002", "南宁兴农合作社土壤改良剂采购合同", "南宁兴农合作社", "付盛贤", new Date("2026-07-01"), 30000, 30000, 30000, null, "已结清", "是", "INV-202607-002", "contract_C002.pdf"],
    ["C-202607-003", "PRJ-GZ-003", "柳州丰成农资补货合同", "柳州丰成农资", "付盛贤", new Date("2026-07-03"), 8800, 8800, 8800, null, "待核发票", "是", "INV-202607-003", "contract_C003.pdf"],
    ["C-202607-004", "PRJ-GZ-004", "桂林农技服务站智能巡检终端试销合同", "桂林农技服务站", "付盛贤", new Date("2026-07-06"), 12680.5, 12680.5, 12680.5, null, "已结清", "否", "", "contract_C004.pdf"]
  ], "ContractLedgerTable");
  contracts.getRange("J3:J6").values = [[200], [0], [0], [0]];
  contracts.getRange("F3:F6").format.numberFormat = "yyyy-mm-dd";
  contracts.getRange("G3:J6").format.numberFormat = "¥#,##0.00";
  fit(contracts, "A:N");

  const invoices = wb.worksheets.add("Invoices");
  writeTitle(invoices, "发票清单 Invoices", "A1:L1");
  table(invoices, 2, 0, [
    "invoice_id", "contract_id", "customer_name", "invoice_title", "expected_title", "invoice_amount", "expected_amount", "issue_date", "external_system", "title_match", "amount_match", "status"
  ], [
    ["INV-202607-001", "C-202607-001", "桂中绿丰合作社", "桂中绿丰合作社", "桂中绿丰合作社", 50200, 50200, new Date("2026-07-06"), "税务发票系统", null, null, null],
    ["INV-202607-002", "C-202607-002", "南宁兴农合作社", "南宁兴农合作社", "南宁兴农合作社", 30000, 30000, new Date("2026-07-10"), "税务发票系统", null, null, null],
    ["INV-202607-003", "C-202607-003", "柳州丰成农资", "广西绿丰农业科技有限公司", "柳州丰成农资", 8800, 8800, new Date("2026-07-15"), "税务发票系统", null, null, null],
    ["INV-202607-004", "C-202607-004", "桂林农技服务站", "桂林农技服务站", "桂林农技服务站", 12680.5, 12680.5, new Date("2026-07-19"), "税务发票系统", null, null, null]
  ], "InvoicesTable");
  invoices.getRange("J3:L6").values = [
    [true, true, "一致"],
    [true, true, "一致"],
    [false, true, "疑点"],
    [true, true, "一致"],
  ];
  invoices.getRange("F3:G6").format.numberFormat = "¥#,##0.00";
  invoices.getRange("H3:H6").format.numberFormat = "yyyy-mm-dd";
  invoices.getRange("L5").format = { fill: doubtFill, font: { bold: true, color: "#9C0006" } };
  fit(invoices, "A:L");

  const recon = wb.worksheets.add("Reconciliation");
  writeTitle(recon, "对账结果 Reconciliation", "A1:J1");
  table(recon, 2, 0, [
    "check_id", "check_name", "contract_id", "expected_value", "actual_value", "difference", "status", "doubt_id", "suggested_action", "module_route"
  ], [
    ["CHK-001", "回款流水 vs 财务应收", "C-202607-001", null, null, null, null, "case2-doubt-001", "确认差异成立并标记为运费差异", "data.search -> rule.calculate"],
    ["CHK-002", "合同登记表应收 vs 实收", "C-202607-002", null, null, null, null, "", "自动通过", "data.search -> rule.calculate"],
    ["CHK-003", "发票抬头与金额一致性", "C-202607-003", null, null, null, null, "case2-doubt-002", "确认疑点成立并退回发票修正", "external.api.call -> rule.calculate"]
  ], "ReconciliationTable");
  recon.getRange("D3:F5").format.numberFormat = "¥#,##0.00";
  recon.getRange("D3:G5").values = [
    [50200, 50000, 200, "疑点"],
    [30000, 30000, 0, "一致"],
    [8800, 8800, 0, "疑点"],
  ];
  recon.getRange("G3").format = { fill: doubtFill, font: { bold: true, color: "#9C0006" } };
  recon.getRange("G4").format = { fill: okFill, font: { bold: true, color: "#006100" } };
  recon.getRange("G5").format = { fill: doubtFill, font: { bold: true, color: "#9C0006" } };
  fit(recon, "A:J");

  const cards = wb.worksheets.add("DecisionCards");
  writeTitle(cards, "疑点确认卡 DecisionCards", "A1:J1");
  table(cards, 2, 0, [
    "doubt_id", "source_check", "title", "detail", "assignee", "decision", "decision_options", "write_back_capability", "current_state", "trace_note"
  ], [
    ["case2-doubt-001", "CHK-001", "回款金额与合同尾款相差一笔运费", "C-202607-001：财务尾款 50,200，实际回款 50,000，差额 200，与运费一致。", "付盛贤", "待确认", "确认差异成立并标记为运费差异|判定为正常放行|退回复核", "data.update", "待拍板", "同一 trace_id 下写回"],
    ["case2-doubt-002", "CHK-003", "一张发票抬头不一致", "INV-202607-003：发票抬头为广西绿丰农业科技有限公司，期望抬头为柳州丰成农资。", "付盛贤", "待确认", "确认疑点成立并退回发票修正|判定为正常放行|退回复核", "data.update", "待拍板", "同一 trace_id 下写回"]
  ], "DecisionCardsTable");
  cards.getRange("F3:F4").format = { fill: noteFill, font: { bold: true, color: "#7F6000" } };
  fit(cards, "A:J");

  const mapping = wb.worksheets.add("FieldMapping");
  writeTitle(mapping, "现有字段 → 平台标准字段 FieldMapping", "A1:H1");
  table(mapping, 2, 0, [
    "source_sheet", "source_field", "platform_layer", "target_module", "platform_capability", "platform_payload_field", "field_type", "remark"
  ], [
    ["PaymentFlow", "payment_amount", "L2", "data-operation", "data.search", "payload.records[].payment_amount", "currency", "回款流水实收金额"],
    ["FinanceAR", "tail_payment_due", "L1/L2", "foundation-data/data-operation", "data.search", "payload.records[].tail_payment_due", "currency", "财务口径应收尾款"],
    ["ContractLedger", "received_amount", "L2", "data-operation", "data.search", "payload.records[].received_amount", "currency", "合同登记表实收"],
    ["Invoices", "invoice_title", "L2", "external-system-integration", "external.api.call", "payload.invoice.title", "text", "外部系统发票抬头"],
    ["Reconciliation", "status", "L2", "rule-adapter", "rule.calculate", "payload.checks[].status", "enum", "一致/疑点"],
    ["DecisionCards", "decision", "L1", "human-collaboration", "human.task.create", "payload.cards[].decision", "enum", "关键动作确认"]
  ], "FieldMappingTable");
  fit(mapping, "A:H");

  const summary = wb.worksheets.add("Summary");
  writeTitle(summary, "案例二销售对账验收摘要", "A1:H1");
  summary.getRange("A3:B8").values = [
    ["指标", "公式结果"],
    ["回款流水记录数", null],
    ["合同登记记录数", null],
    ["发票记录数", null],
    ["疑点数量", null],
    ["自动通过数量", null],
  ];
  styleHeader(summary.getRange("A3:B3"));
  styleBody(summary.getRange("A4:B8"));
  summary.getRange("B4:B8").values = [[4], [4], [4], [2], [1]];
  writeNote(summary, "D3", "预期：疑点数量 = 2；自动通过数量 = 1。疑点来自：1）C-202607-001 运费差异；2）INV-202607-003 发票抬头不一致。");
  fit(summary, "A:H");

  const sheets = [summary, guide, payment, ar, contracts, invoices, recon, cards, mapping];
  for (const sh of sheets) {
    const preview = await wb.render({ sheetName: sh.name, autoCrop: "all", scale: 1, format: "png" });
    await fs.writeFile(path.join(renderDir, `${sh.name}.png`), new Uint8Array(await preview.arrayBuffer()));
  }
  const scan = await wb.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 300 },
    summary: "formula error scan",
  });
  console.log(scan.ndjson);
  const file = await SpreadsheetFile.exportXlsx(wb);
  const out = path.join(outDir, "案例二_销售对账测试数据包.xlsx");
  await file.save(out);
  return out;
}

async function buildContractWorkbook() {
  const wb = Workbook.create();
  const guide = wb.worksheets.add("UploadGuide");
  writeTitle(guide, "合同登记表上传版：使用说明", "A1:H1");
  table(guide, 2, 0, ["项目", "说明"], [
    ["用途", "用于案例二中“核对本人名下合同登记表”的上传测试。"],
    ["上传模块", "建议上传到 L2 数据操作引擎，能力 data.search / data.read。"],
    ["关键疑点", "C-202607-001 尾款 50,200，实际回款 50,000，后续应由规则计算识别差异。"],
    ["字段约定", "contract_id 是主键；owner 用于按本人范围取数；received_amount 用于对账。"]
  ], "ContractGuideTable");
  fit(guide, "A:H");

  const ledger = wb.worksheets.add("ContractLedger");
  writeTitle(ledger, "合同登记表", "A1:O1");
  table(ledger, 2, 0, [
    "contract_id", "project_id", "contract_name", "customer_name", "owner", "region", "sign_date", "contract_amount", "tail_payment_due", "received_amount", "unreceived_amount", "invoice_id", "contract_status", "risk_note", "attachment_ref"
  ], [
    ["C-202607-001", "PRJ-GZ-001", "桂中绿丰合作社追肥产品采购合同", "桂中绿丰合作社", "付盛贤", "桂中", new Date("2026-06-28"), 100200, 50200, 50000, null, "INV-202607-001", "执行中", "尾款与回款差额等于运费", "contract_C001.pdf"],
    ["C-202607-002", "PRJ-GZ-002", "南宁兴农合作社土壤改良剂采购合同", "南宁兴农合作社", "付盛贤", "南宁", new Date("2026-07-01"), 30000, 30000, 30000, null, "INV-202607-002", "已结清", "无", "contract_C002.pdf"],
    ["C-202607-003", "PRJ-GZ-003", "柳州丰成农资补货合同", "柳州丰成农资", "付盛贤", "柳州", new Date("2026-07-03"), 8800, 8800, 8800, null, "INV-202607-003", "待核发票", "发票抬头待核", "contract_C003.pdf"],
    ["C-202607-004", "PRJ-GZ-004", "桂林农技服务站智能巡检终端试销合同", "桂林农技服务站", "付盛贤", "桂林", new Date("2026-07-06"), 12680.5, 12680.5, 12680.5, null, "", "已结清", "无", "contract_C004.pdf"],
    ["C-202607-005", "PRJ-GZ-005", "百色合作社土壤检测服务合同", "百色合作社", "付盛贤", "百色", new Date("2026-07-11"), 16800, 16800, 0, null, "", "待回款", "本月未到账，不纳入已到账核对", "contract_C005.pdf"]
  ], "UploadContractLedger");
  ledger.getRange("K3:K7").values = [[200], [0], [0], [0], [16800]];
  ledger.getRange("G3:G7").format.numberFormat = "yyyy-mm-dd";
  ledger.getRange("H3:K7").format.numberFormat = "¥#,##0.00";
  fit(ledger, "A:O");

  const detail = wb.worksheets.add("ContractDetail");
  writeTitle(detail, "合同明细", "A1:H1");
  table(detail, 2, 0, ["contract_id", "line_no", "product_or_service", "quantity", "unit", "unit_price", "line_amount", "remark"], [
    ["C-202607-001", 1, "追肥产品 A", 100, "袋", 502, null, "尾款批次"],
    ["C-202607-002", 1, "土壤改良剂 B", 60, "箱", 500, null, "已结清"],
    ["C-202607-003", 1, "补货产品 C", 40, "箱", 220, null, "发票抬头待核"],
    ["C-202607-004", 1, "智能巡检终端试销", 1, "套", 12680.5, null, "已结清"],
    ["C-202607-005", 1, "土壤检测服务", 1, "项", 16800, null, "待回款"]
  ], "ContractDetailTable");
  detail.getRange("G3:G7").values = [[50200], [30000], [8800], [12680.5], [16800]];
  detail.getRange("F3:G7").format.numberFormat = "¥#,##0.00";
  fit(detail, "A:H");

  const attachments = wb.worksheets.add("AttachmentIndex");
  writeTitle(attachments, "附件索引", "A1:H1");
  table(attachments, 2, 0, ["attachment_ref", "contract_id", "file_name", "file_type", "upload_status", "parse_required", "expected_module", "remark"], [
    ["contract_C001.pdf", "C-202607-001", "桂中绿丰合作社追肥产品采购合同.pdf", "PDF", "待上传", "否", "data-operation", "合同主件"],
    ["bank_slip_001.pdf", "C-202607-001", "C001银行回单.pdf", "PDF", "待上传", "否", "data-operation", "回款凭证"],
    ["invoice_INV003.pdf", "C-202607-003", "INV003发票.pdf", "PDF", "待上传", "是", "external-system-integration", "发票抬头疑点"]
  ], "AttachmentIndexTable");
  fit(attachments, "A:H");

  for (const sh of [guide, ledger, detail, attachments]) {
    const preview = await wb.render({ sheetName: sh.name, autoCrop: "all", scale: 1, format: "png" });
    await fs.writeFile(path.join(renderDir, `contract_${sh.name}.png`), new Uint8Array(await preview.arrayBuffer()));
  }
  const scan = await wb.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 300 },
    summary: "formula error scan",
  });
  console.log(scan.ndjson);
  const file = await SpreadsheetFile.exportXlsx(wb);
  const out = path.join(outDir, "案例二_合同登记表_上传版.xlsx");
  await file.save(out);
  return out;
}

const created = [await buildDataPack(), await buildContractWorkbook()];
console.log(JSON.stringify({ created }, null, 2));
