from __future__ import annotations

import csv
import json
import math
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

Template = Callable[[dict[str, Any], Path], dict[str, Any]]


def run_template(scenario_id: str, task_input: dict[str, Any], result_dir: Path, timeout_seconds: int) -> dict[str, Any]:
    started = time.perf_counter()
    result_dir.mkdir(parents=True, exist_ok=True)
    handler = TEMPLATES.get(scenario_id, generic_template)
    result = handler(task_input, result_dir)
    if time.perf_counter() - started > timeout_seconds:
        raise TimeoutError(f"Task exceeded {timeout_seconds} seconds")
    result["sandbox_runtime"] = {
        "executor": "LocalTemplateExecutor",
        "note": "MVP placeholder. Replace with Docker/Cube Sandbox for production isolation.",
    }
    return result


def s01_accounting(task_input: dict[str, Any], result_dir: Path) -> dict[str, Any]:
    receivables = task_input.get("receivables") or [
        {"customer": "客户A", "amount": 100000, "age_days": 45},
        {"customer": "客户B", "amount": 80000, "age_days": 160},
        {"customer": "客户C", "amount": 30000, "age_days": 420},
    ]
    taxable_profit = float(task_input.get("taxable_profit", 500000))
    rates = [(90, 0.02), (180, 0.05), (365, 0.2), (99999, 0.5)]
    rows = []
    bad_debt_total = 0.0
    for item in receivables:
        rate = next(rate for limit, rate in rates if float(item["age_days"]) <= limit)
        provision = round(float(item["amount"]) * rate, 2)
        bad_debt_total += provision
        rows.append({**item, "provision_rate": rate, "bad_debt_provision": provision})
    return write_result(result_dir, "accounting_estimates", {
        "bad_debt_rows": rows,
        "total_bad_debt_provision": round(bad_debt_total, 2),
        "income_tax_estimate": round(taxable_profit * 0.25, 2),
        "deferred_tax_estimate": round(bad_debt_total * 0.25, 2),
    })


def s02_gross_margin(task_input: dict[str, Any], result_dir: Path) -> dict[str, Any]:
    rows = task_input.get("rows") or [
        {"region": "华南", "product": "A", "customer": "经销商1", "salesperson": "张三", "revenue": 120000, "cost": 85000},
        {"region": "华南", "product": "B", "customer": "经销商2", "salesperson": "李四", "revenue": 90000, "cost": 65000},
        {"region": "华北", "product": "A", "customer": "经销商3", "salesperson": "王五", "revenue": 60000, "cost": 50000},
    ]
    dimensions = task_input.get("dimensions") or ["region", "product", "customer", "salesperson"]
    summary = {}
    for dim in dimensions:
        bucket = defaultdict(lambda: {"revenue": 0.0, "cost": 0.0})
        for row in rows:
            key = str(row.get(dim, "未分类"))
            bucket[key]["revenue"] += float(row.get("revenue", 0))
            bucket[key]["cost"] += float(row.get("cost", 0))
        summary[dim] = []
        for key, value in bucket.items():
            margin = round(value["revenue"] - value["cost"], 2)
            rate = round(margin / value["revenue"], 4) if value["revenue"] else 0
            summary[dim].append({"name": key, **value, "gross_margin": margin, "gross_margin_rate": rate})
    return write_result(result_dir, "gross_margin", {"summary": summary})


def s03_product_cost(task_input: dict[str, Any], result_dir: Path) -> dict[str, Any]:
    formula = task_input.get("formula") or [
        {"material": "原料A", "qty": 0.6, "unit_price": 3800},
        {"material": "原料B", "qty": 0.3, "unit_price": 2200},
        {"material": "助剂C", "qty": 0.1, "unit_price": 9000},
    ]
    processing_cost = float(task_input.get("processing_cost", 350))
    rows = []
    material_total = 0.0
    for item in formula:
        cost = round(float(item["qty"]) * float(item["unit_price"]), 2)
        material_total += cost
        rows.append({**item, "cost": cost})
    return write_result(result_dir, "product_cost", {
        "formula_cost_rows": rows,
        "material_total": round(material_total, 2),
        "processing_cost": processing_cost,
        "unit_cost": round(material_total + processing_cost, 2),
    })


def s04_invoice_matching(task_input: dict[str, Any], result_dir: Path) -> dict[str, Any]:
    invoices = task_input.get("invoices") or [
        {"invoice_no": "INV001", "supplier": "供应商A", "amount": 10000, "tax_rate": 0.13},
        {"invoice_no": "INV002", "supplier": "供应商B", "amount": 8800, "tax_rate": 0.09},
    ]
    receipts = task_input.get("receipts") or [
        {"receipt_no": "IN001", "supplier": "供应商A", "amount": 10000},
        {"receipt_no": "IN002", "supplier": "供应商B", "amount": 9000},
    ]
    matches = []
    for inv in invoices:
        match = next((r for r in receipts if r["supplier"] == inv["supplier"] and abs(float(r["amount"]) - float(inv["amount"])) <= 1), None)
        matches.append({
            "invoice_no": inv["invoice_no"],
            "supplier": inv["supplier"],
            "matched_receipt": match["receipt_no"] if match else None,
            "status": "matched" if match else "exception",
            "message": "金额和供应商匹配" if match else "未找到金额一致的入库单",
        })
    return write_result(result_dir, "invoice_matching", {"matches": matches})


def s05_bom_warning(task_input: dict[str, Any], result_dir: Path) -> dict[str, Any]:
    bom = task_input.get("bom") or {"原料A": 0.6, "原料B": 0.4}
    actual = task_input.get("actual") or {"原料A": 0.72, "原料B": 0.28}
    threshold = float(task_input.get("threshold", 0.08))
    warnings = []
    for material, expected in bom.items():
        actual_ratio = float(actual.get(material, 0))
        delta = round(actual_ratio - float(expected), 4)
        if abs(delta) > threshold:
            warnings.append({"material": material, "expected": expected, "actual": actual_ratio, "delta": delta})
    return write_result(result_dir, "bom_warning", {"warnings": warnings, "status": "warning" if warnings else "ok"})


def s06_pivot(task_input: dict[str, Any], result_dir: Path) -> dict[str, Any]:
    rows = task_input.get("rows") or [
        {"product": "A", "region": "华南", "amount": 120},
        {"product": "A", "region": "华南", "amount": 80},
        {"product": "B", "region": "华北", "amount": 50},
    ]
    row_key = task_input.get("row_key", "product")
    col_key = task_input.get("col_key", "region")
    value_key = task_input.get("value_key", "amount")
    pivot = defaultdict(lambda: defaultdict(float))
    for row in rows:
        pivot[str(row.get(row_key, "未分类"))][str(row.get(col_key, "未分类"))] += float(row.get(value_key, 0))
    return write_result(result_dir, "messy_table_pivot", {"pivot": {k: dict(v) for k, v in pivot.items()}})


def s07_mix(task_input: dict[str, Any], result_dir: Path) -> dict[str, Any]:
    ingredients = set(task_input.get("ingredients") or ["钙", "磷", "微量元素"])
    incompatible_pairs = [("钙", "磷"), ("强酸", "强碱")]
    issues = [pair for pair in incompatible_pairs if pair[0] in ingredients and pair[1] in ingredients]
    return write_result(result_dir, "mix_compatibility", {
        "ingredients": sorted(ingredients),
        "compatible": not issues,
        "issues": [{"pair": list(pair), "message": "建议做小样试验后再混配"} for pair in issues],
    })


def s08_batch_media(task_input: dict[str, Any], result_dir: Path) -> dict[str, Any]:
    files = task_input.get("files") or ["素材1.mp4", "素材2.mp4"]
    plan = [{"file": name, "subtitle": "待生成字幕", "voiceover": "待匹配配音", "clip_plan": "按产品卖点拆分"} for name in files]
    return write_result(result_dir, "batch_media", {"processing_plan": plan, "note": "MVP 只生成执行计划；生产版在沙箱内调用媒体工具。"})


def s09_short_video(task_input: dict[str, Any], result_dir: Path) -> dict[str, Any]:
    topic = task_input.get("topic", "产品推广短视频")
    return write_result(result_dir, "short_video", {
        "topic": topic,
        "workflow": ["素材导入", "自动剪辑", "字幕生成", "配音匹配", "背景音乐匹配", "导出成片"],
        "note": "MVP 返回工作流计划；真实渲染需在代码/浏览器沙箱内执行。",
    })


def s10_market_growth(task_input: dict[str, Any], result_dir: Path) -> dict[str, Any]:
    history = [float(x) for x in task_input.get("history", [100, 115, 132, 150])]
    growth = growth_rate(history)
    return write_result(result_dir, "market_growth", {"history": history, "avg_growth_rate": growth, "next_year_forecast": round(history[-1] * (1 + growth), 2)})


def s11_platform_rules(task_input: dict[str, Any], result_dir: Path) -> dict[str, Any]:
    content = task_input.get("content", "促销文案示例")
    platforms = task_input.get("platforms") or ["抖音", "视频号", "小红书"]
    checks = [{"platform": p, "status": "needs_review", "suggestion": "按平台规则检查敏感词、时长、标题和封面"} for p in platforms]
    return write_result(result_dir, "platform_rules", {"content": content, "checks": checks})


def s12_daily_price(task_input: dict[str, Any], result_dir: Path) -> dict[str, Any]:
    prices = [float(x) for x in task_input.get("prices", [3800, 3820, 3880, 4010, 3980])]
    trend = "up" if prices[-1] > prices[0] else "down"
    abnormal = abs(prices[-1] - prices[-2]) / prices[-2] > 0.03 if len(prices) > 1 and prices[-2] else False
    return write_result(result_dir, "daily_price_trend", {"prices": prices, "trend": trend, "abnormal": abnormal})


def s13_photo_translation(task_input: dict[str, Any], result_dir: Path) -> dict[str, Any]:
    label_text = task_input.get("label_text", "Potassium sulfate, manufacturer ABC, K2O 52%")
    translated = label_text.replace("Potassium sulfate", "硫酸钾").replace("manufacturer", "生产厂家")
    return write_result(result_dir, "material_photo_translation", {
        "recognized_text": label_text,
        "translated_text": translated,
        "note": "MVP 使用文本输入模拟；生产版通过 1.5 调 OCR/视觉/翻译模型。",
    })


def s14_price_forecast(task_input: dict[str, Any], result_dir: Path) -> dict[str, Any]:
    annual_prices = [float(x) for x in task_input.get("annual_prices", [3200, 3600, 3450, 3900, 4100])]
    avg = round(sum(annual_prices) / len(annual_prices), 2)
    volatility = round(stddev(annual_prices) / avg, 4) if avg else 0
    forecast = round(annual_prices[-1] + (annual_prices[-1] - annual_prices[0]) / max(len(annual_prices) - 1, 1), 2)
    return write_result(result_dir, "price_forecast", {"average": avg, "volatility": volatility, "forecast": forecast})


def s15_contract_diff(task_input: dict[str, Any], result_dir: Path) -> dict[str, Any]:
    old = task_input.get("old", "付款期限为30天。交货地点为南宁。")
    new = task_input.get("new", "付款期限为45天。交货地点为南宁。")
    changes = [{"type": "text_changed", "old": old, "new": new}] if old != new else []
    return write_result(result_dir, "contract_diff", {"changes": changes, "archive_suggestion": "盖章版合同应归档到合同库"})


def s16_quality(task_input: dict[str, Any], result_dir: Path) -> dict[str, Any]:
    batch = task_input.get("batch", "BATCH-001")
    metrics = task_input.get("metrics") or {"水分": 0.08, "含量": 0.96, "外观": "合格"}
    status = "pass" if metrics.get("水分", 1) <= 0.1 and metrics.get("含量", 0) >= 0.95 else "review"
    return write_result(result_dir, "quality_trace", {"batch": batch, "metrics": metrics, "status": status})


def s17_stocking(task_input: dict[str, Any], result_dir: Path) -> dict[str, Any]:
    stock = float(task_input.get("stock", 120))
    package_stock = float(task_input.get("package_stock", 90))
    forecast_sales = float(task_input.get("forecast_sales", 180))
    return write_result(result_dir, "stocking_reference", {
        "suggested_finished_goods_qty": max(0, forecast_sales - stock),
        "suggested_package_qty": max(0, forecast_sales - package_stock),
    })


def s18_after_hours(task_input: dict[str, Any], result_dir: Path) -> dict[str, Any]:
    order = task_input.get("order") or {"customer_type": "new", "contract_present": True, "credit_limit_ok": False}
    issues = []
    if order.get("customer_type") == "new":
        issues.append("新增客户需核对准入条件")
    if not order.get("contract_present"):
        issues.append("缺少合同")
    if not order.get("credit_limit_ok"):
        issues.append("授信或额度需人工复核")
    return write_result(result_dir, "after_hours_review", {"issues": issues, "decision": "manual_review" if issues else "auto_pass"})


def s19_over_stock(task_input: dict[str, Any], result_dir: Path) -> dict[str, Any]:
    inventory = float(task_input.get("inventory", 50))
    orders = task_input.get("orders") or [
        {"department": "部门1", "qty": 30},
        {"department": "部门2", "qty": 30},
        {"department": "部门3", "qty": 30},
    ]
    total = sum(float(item.get("qty", 0)) for item in orders)
    return write_result(result_dir, "over_stock_warning", {
        "inventory": inventory,
        "total_order_qty": total,
        "over_qty": max(0, total - inventory),
        "status": "warning" if total > inventory else "ok",
        "orders": orders,
    })


def s20_purchase_plan(task_input: dict[str, Any], result_dir: Path) -> dict[str, Any]:
    history = [float(x) for x in task_input.get("history", [80, 100, 110, 130])]
    current_stock = float(task_input.get("current_stock", 60))
    demand = round(history[-1] * (1 + growth_rate(history)), 2)
    return write_result(result_dir, "purchase_plan", {"forecast_demand": demand, "current_stock": current_stock, "suggested_purchase": max(0, round(demand - current_stock, 2))})


def generic_template(task_input: dict[str, Any], result_dir: Path) -> dict[str, Any]:
    return write_result(result_dir, "generic", {"received_input": task_input})


def write_result(result_dir: Path, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    result_dir.mkdir(parents=True, exist_ok=True)
    json_path = result_dir / f"{name}.json"
    csv_path = result_dir / f"{name}_summary.csv"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["field", "value"])
        for key, value in payload.items():
            writer.writerow([key, json.dumps(value, ensure_ascii=False)])
    return {"payload": payload, "files": [str(json_path), str(csv_path)]}


def growth_rate(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    rates = [(after - before) / before for before, after in zip(values, values[1:]) if before]
    return round(sum(rates) / len(rates), 4) if rates else 0.0


def stddev(values: list[float]) -> float:
    avg = sum(values) / len(values)
    return math.sqrt(sum((item - avg) ** 2 for item in values) / len(values))


TEMPLATES: dict[str, Template] = {
    "s01_accounting_estimates": s01_accounting,
    "s02_gross_margin": s02_gross_margin,
    "s03_product_cost": s03_product_cost,
    "s04_invoice_matching": s04_invoice_matching,
    "s05_bom_warning": s05_bom_warning,
    "s06_messy_table_pivot": s06_pivot,
    "s07_mix_compatibility": s07_mix,
    "s08_batch_media": s08_batch_media,
    "s09_short_video": s09_short_video,
    "s10_market_growth": s10_market_growth,
    "s11_platform_rules": s11_platform_rules,
    "s12_daily_price_trend": s12_daily_price,
    "s13_material_photo_translation": s13_photo_translation,
    "s14_price_forecast": s14_price_forecast,
    "s15_contract_diff": s15_contract_diff,
    "s16_quality_trace": s16_quality,
    "s17_stocking_reference": s17_stocking,
    "s18_after_hours_review": s18_after_hours,
    "s19_over_stock_warning": s19_over_stock,
    "s20_purchase_plan": s20_purchase_plan,
}

