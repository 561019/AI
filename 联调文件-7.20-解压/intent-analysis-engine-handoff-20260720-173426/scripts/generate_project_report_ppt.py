from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile


EMU_PER_INCH = 914400
SLIDE_W = 12192000
SLIDE_H = 6858000

FONT = "Microsoft YaHei"
NAVY = "172C3C"
TEAL = "19788A"
TEAL_DARK = "0E6674"
GOLD = "D8A23A"
GREEN = "1E8A5A"
RED = "B84A3A"
BG = "F4F7F9"
CARD = "FFFFFF"
TEXT = "172026"
MUTED = "60707A"
BORDER = "D6E0E6"


@dataclass
class Shape:
    xml: str


class SlideBuilder:
    def __init__(self, index: int, title: str | None = None) -> None:
        self.index = index
        self.shape_id = 2
        self.shapes: list[Shape] = []
        self.background(BG)
        if title:
            self.header(title)
            self.footer()

    def next_id(self) -> int:
        value = self.shape_id
        self.shape_id += 1
        return value

    def background(self, color: str) -> None:
        self.rect(0, 0, 13.333, 7.5, fill=color, line=color)

    def header(self, title: str, subtitle: str | None = None) -> None:
        self.rect(0, 0, 13.333, 0.72, fill=NAVY, line=NAVY)
        self.text(title, 0.52, 0.18, 9.5, 0.36, size=21, bold=True, color="FFFFFF")
        if subtitle:
            self.text(subtitle, 9.65, 0.2, 3.1, 0.28, size=9, bold=False, color="CFE1E8", align="r")

    def footer(self) -> None:
        self.text("Intent Analysis Engine | 2026-07-10", 0.55, 7.12, 4.0, 0.22, size=8, color=MUTED)
        self.text(str(self.index).zfill(2), 12.35, 7.08, 0.45, 0.25, size=9, bold=True, color=MUTED, align="r")

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        fill: str = CARD,
        line: str = BORDER,
        radius: bool = False,
    ) -> None:
        shape_id = self.next_id()
        prst = "roundRect" if radius else "rect"
        self.shapes.append(
            Shape(
                f"""
<p:sp>
  <p:nvSpPr><p:cNvPr id="{shape_id}" name="Shape {shape_id}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
  <p:spPr>
    <a:xfrm><a:off x="{emu(x)}" y="{emu(y)}"/><a:ext cx="{emu(w)}" cy="{emu(h)}"/></a:xfrm>
    <a:prstGeom prst="{prst}"><a:avLst/></a:prstGeom>
    <a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>
    <a:ln w="9525"><a:solidFill><a:srgbClr val="{line}"/></a:solidFill></a:ln>
  </p:spPr>
</p:sp>
"""
            )
        )

    def line(self, x: float, y: float, w: float, *, color: str = BORDER) -> None:
        self.rect(x, y, w, 0.02, fill=color, line=color)

    def pill(self, text: str, x: float, y: float, w: float, *, fill: str = "E9F5F7", color: str = TEAL) -> None:
        self.rect(x, y, w, 0.38, fill=fill, line=fill, radius=True)
        self.text(text, x + 0.1, y + 0.09, w - 0.2, 0.18, size=8, bold=True, color=color, align="c")

    def text(
        self,
        text: str,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        size: int = 14,
        bold: bool = False,
        color: str = TEXT,
        align: str = "l",
        valign: str = "top",
    ) -> None:
        shape_id = self.next_id()
        body = paragraphs(text, size=size, bold=bold, color=color, align=align)
        anchor = {"top": "t", "mid": "ctr", "bottom": "b"}.get(valign, "t")
        self.shapes.append(
            Shape(
                f"""
<p:sp>
  <p:nvSpPr><p:cNvPr id="{shape_id}" name="Text {shape_id}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>
  <p:spPr>
    <a:xfrm><a:off x="{emu(x)}" y="{emu(y)}"/><a:ext cx="{emu(w)}" cy="{emu(h)}"/></a:xfrm>
    <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
    <a:noFill/><a:ln><a:noFill/></a:ln>
  </p:spPr>
  <p:txBody>
    <a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" anchor="{anchor}"><a:spAutoFit/></a:bodyPr>
    <a:lstStyle/>
    {body}
  </p:txBody>
</p:sp>
"""
            )
        )

    def card(self, title: str, body: str, x: float, y: float, w: float, h: float, *, accent: str = TEAL) -> None:
        self.rect(x, y, w, h, fill=CARD, line=BORDER, radius=True)
        self.rect(x, y, 0.08, h, fill=accent, line=accent)
        self.text(title, x + 0.28, y + 0.24, w - 0.44, 0.3, size=14, bold=True, color=TEXT)
        self.text(body, x + 0.28, y + 0.68, w - 0.44, h - 0.85, size=10, color=MUTED)

    def metric(self, value: str, label: str, x: float, y: float, w: float, *, color: str = TEAL) -> None:
        self.rect(x, y, w, 1.15, fill=CARD, line=BORDER, radius=True)
        self.text(value, x + 0.18, y + 0.24, w - 0.36, 0.4, size=25, bold=True, color=color, align="c")
        self.text(label, x + 0.18, y + 0.74, w - 0.36, 0.22, size=9, bold=True, color=MUTED, align="c")

    def flow_box(self, label: str, x: float, y: float, w: float, *, fill: str = CARD, color: str = TEXT) -> None:
        self.rect(x, y, w, 0.72, fill=fill, line=BORDER, radius=True)
        self.text(label, x + 0.12, y + 0.22, w - 0.24, 0.2, size=10, bold=True, color=color, align="c")

    def arrow(self, x: float, y: float) -> None:
        self.text("→", x, y, 0.32, 0.2, size=18, bold=True, color=TEAL, align="c")

    def xml(self) -> str:
        shapes_xml = "\n".join(shape.xml for shape in self.shapes)
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
      <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
      {shapes_xml}
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>
"""


def emu(value: float) -> int:
    return int(round(value * EMU_PER_INCH))


def paragraphs(text: str, *, size: int, bold: bool, color: str, align: str) -> str:
    lines = text.split("\n")
    return "\n".join(paragraph(line, size=size, bold=bold, color=color, align=align) for line in lines)


def paragraph(text: str, *, size: int, bold: bool, color: str, align: str) -> str:
    algn = {"l": "l", "c": "ctr", "r": "r"}.get(align, "l")
    b_attr = ' b="1"' if bold else ""
    safe = escape(text)
    return f"""
<a:p>
  <a:pPr algn="{algn}"/>
  <a:r>
    <a:rPr lang="zh-CN" sz="{size * 100}"{b_attr}>
      <a:solidFill><a:srgbClr val="{color}"/></a:solidFill>
      <a:latin typeface="{FONT}"/><a:ea typeface="{FONT}"/><a:cs typeface="{FONT}"/>
    </a:rPr>
    <a:t>{safe}</a:t>
  </a:r>
  <a:endParaRPr lang="zh-CN" sz="{size * 100}"/>
</a:p>
"""


def build_slides() -> list[SlideBuilder]:
    slides: list[SlideBuilder] = []

    s = SlideBuilder(1)
    s.rect(0, 0, 13.333, 7.5, fill=NAVY, line=NAVY)
    s.rect(0, 6.95, 13.333, 0.55, fill=TEAL, line=TEAL)
    s.text("自然语言意图分析引擎", 0.85, 1.45, 8.8, 0.62, size=32, bold=True, color="FFFFFF")
    s.text("Intent Analysis Engine 项目汇报", 0.88, 2.15, 6.2, 0.34, size=17, color="CFE1E8")
    s.line(0.9, 2.75, 3.3, color=GOLD)
    s.text("从用户自然语言到标准 TaskList 的意图分析中枢", 0.9, 3.18, 8.2, 0.35, size=18, bold=True, color="FFFFFF")
    s.text("范围：意图识别、任务拆解、目标引擎匹配、缺失输入澄清\n边界：不开发业务执行引擎，不默认、不补全、不猜测", 0.92, 3.78, 8.8, 0.76, size=14, color="D7E7EC")
    s.pill("Rule + BGE + LLM", 0.92, 5.15, 1.75, fill="E8F4F6", color=TEAL_DARK)
    s.pill("TaskList Contract", 2.9, 5.15, 1.95, fill="FFF4DB", color="835208")
    s.pill("Input Validator", 5.1, 5.15, 1.8, fill="EAF6EF", color=GREEN)
    s.text("2026-07-10", 10.1, 6.98, 2.3, 0.22, size=10, bold=True, color="FFFFFF", align="r")
    slides.append(s)

    s = SlideBuilder(2, "项目定位与边界")
    s.card("项目定位", "自然语言意图分析引擎是下游流程管控模块之前的理解层。\n负责把用户请求转为结构化任务，而不是直接执行业务。", 0.65, 1.15, 5.85, 2.0, accent=TEAL)
    s.card("严格边界", "不开发、不调用业务执行引擎；不查询真实业务数据；不执行计算、文件处理或流程动作。", 6.83, 1.15, 5.85, 2.0, accent=RED)
    s.card("输出对象", "统一输出 IntentAnalysisResult / TaskList。\n下游模块不需要再次解析用户原始文本。", 0.65, 3.55, 5.85, 2.0, accent=GOLD)
    s.card("核心原则", "确定性优先、语义增强、LLM 兜底。\n所有路径最终都经过输入校验，不默认、不补全、不猜测。", 6.83, 3.55, 5.85, 2.0, accent=GREEN)
    slides.append(s)

    s = SlideBuilder(3, "建设目标")
    s.card("目标 1：理解用户请求", "识别用户要做什么，判断属于查询、统计、计算、分析、问答、内容生成、流程等哪类任务。", 0.55, 1.05, 3.95, 1.58, accent=TEAL)
    s.card("目标 2：拆解多动作任务", "把复合表达拆成多个有顺序、有依赖的标准任务。", 4.7, 1.05, 3.95, 1.58, accent=TEAL)
    s.card("目标 3：选择目标引擎", "只输出 engine_code 作为路由标识，不在本项目内调用业务引擎。", 8.85, 1.05, 3.95, 1.58, accent=TEAL)
    s.card("目标 4：校验输入完整性", "根据 task_type 检查 required_inputs，缺失则生成澄清问题。", 0.55, 3.05, 3.95, 1.58, accent=GOLD)
    s.card("目标 5：保持输出契约", "所有识别来源统一进入 Task Builder 与 Input Validator，最终输出标准 TaskList。", 4.7, 3.05, 3.95, 1.58, accent=GOLD)
    s.card("目标 6：支持持续评测", "用标准评测集验证规则、语义、拆解、澄清和引擎选择准确率。", 8.85, 3.05, 3.95, 1.58, accent=GOLD)
    slides.append(s)

    s = SlideBuilder(4, "核心建设任务")
    tasks = [
        ("01", "规则匹配优化", "增加 rule_priority，明确高精度业务动作规则优先。"),
        ("02", "BGE 语义匹配", "接入 BAAI/bge-base-zh-v1.5 与 Milvus 能力向量库。"),
        ("03", "输入校验层", "独立 Task Input Validator，统一检查 required_inputs。"),
        ("04", "能力库配置化", "semantic_capabilities.yaml 管理描述、样例、关键词、必填项。"),
        ("05", "评测体系", "100 条真实业务表达 + 回归案例，持续验证准确率。"),
        ("06", "汇报演示平台", "在线可视化与离线演示，适配项目汇报场景。"),
    ]
    for i, (no, title, body) in enumerate(tasks):
        x = 0.62 + (i % 2) * 6.25
        y = 1.03 + (i // 2) * 1.72
        s.rect(x, y, 5.85, 1.32, fill=CARD, line=BORDER, radius=True)
        s.text(no, x + 0.25, y + 0.34, 0.56, 0.3, size=18, bold=True, color=TEAL, align="c")
        s.text(title, x + 1.0, y + 0.24, 4.55, 0.25, size=13, bold=True)
        s.text(body, x + 1.0, y + 0.62, 4.45, 0.28, size=9, color=MUTED)
    slides.append(s)

    s = SlideBuilder(5, "总体技术方案")
    labels = [
        ("用户自然语言", 0.55, TEAL),
        ("Question Fast Path", 2.05, CARD),
        ("Task Decomposer", 3.85, CARD),
        ("Level1 Rule Matcher", 5.55, CARD),
        ("Level2 BGE + Milvus", 7.55, CARD),
        ("Level3 LLM Matcher", 9.6, CARD),
        ("TaskList 输出", 11.35, GREEN),
    ]
    for idx, (label, x, fill) in enumerate(labels):
        text_color = "FFFFFF" if fill in {TEAL, GREEN} else TEXT
        s.flow_box(label, x, 1.32, 1.42 if idx else 1.25, fill=fill, color=text_color)
        if idx < len(labels) - 1:
            s.arrow(x + (1.34 if idx else 1.18), 1.5)
    s.rect(2.75, 3.05, 7.95, 0.72, fill="EAF6EF", line="B8DCC9", radius=True)
    s.text("Task Builder → Input Validator → Clarification Questions", 3.0, 3.28, 7.45, 0.18, size=13, bold=True, color=GREEN, align="c")
    s.text("设计重点", 0.8, 4.38, 1.2, 0.28, size=14, bold=True)
    s.text("• 规则命中直接进入 Task Builder，不被 BGE 替代\n• 规则未命中才调用 BGE 语义检索\n• 所有来源统一经过输入校验\n• 缺失输入必须澄清，禁止自动补全", 0.82, 4.83, 5.7, 1.0, size=11, color=MUTED)
    s.text("BGE 只负责语义匹配，不负责补全业务信息。", 6.95, 4.85, 4.9, 0.3, size=15, bold=True, color=TEAL)
    s.text("这保证系统既能处理口语化表达，又不会越界执行业务决策。", 6.95, 5.35, 4.9, 0.3, size=11, color=MUTED)
    slides.append(s)

    s = SlideBuilder(6, "标准输出契约")
    s.card("IntentAnalysisResult", "request_id\noriginal_text\nintent_category\ntasks[]\nclarification_required\nclarification_questions\nanalysis_level\noverall_confidence", 0.75, 1.08, 4.0, 4.45, accent=TEAL)
    s.card("TaskItem", "task_id\ntask_name\ntask_type\ntarget_engine\nengine_code\nrequired_inputs\nmissing_inputs\ndependencies\nexecution_order\nconfidence", 4.98, 1.08, 4.0, 4.45, accent=GOLD)
    s.card("契约价值", "1. 下游系统只消费结构化 TaskList\n2. 不再重复解析自然语言\n3. 多任务可通过 dependencies 与 execution_order 编排\n4. 缺失项通过 missing_inputs 与 clarification_questions 显式表达", 9.2, 1.08, 3.35, 4.45, accent=GREEN)
    slides.append(s)

    s = SlideBuilder(7, "BGE 语义分析方案")
    s.card("Embedding Provider 抽象", "embedding/base.py\nembedding/bge_provider.py\nembedding/embedding_service.py\n\n默认模型：BAAI/bge-base-zh-v1.5\n配置项：EMBEDDING_MODEL_NAME", 0.65, 1.05, 3.85, 4.85, accent=TEAL)
    s.card("Milvus 向量库", "Collection：intent_capability_vectors\n\n保存字段：\nengine_code\ntask_type\nintent_description\nexamples\nkeywords\nembedding_vector", 4.78, 1.05, 3.85, 4.85, accent=GOLD)
    s.card("能力配置化", "semantic_capabilities.yaml\n\n每个 task_type 管理：\ndescription\nexamples\nkeywords\nrequired_inputs\n\nsemantic_matcher.py 不再硬编码业务描述。", 8.9, 1.05, 3.85, 4.85, accent=GREEN)
    slides.append(s)

    s = SlideBuilder(8, "输入校验与澄清机制")
    s.flow_box("Rule / BGE / LLM", 1.0, 1.35, 1.8, fill=TEAL, color="FFFFFF")
    s.arrow(2.95, 1.53)
    s.flow_box("Task Builder", 3.35, 1.35, 1.65)
    s.arrow(5.18, 1.53)
    s.flow_box("Input Validator", 5.6, 1.35, 1.85)
    s.arrow(7.62, 1.53)
    s.flow_box("TaskList", 8.05, 1.35, 1.5, fill=GREEN, color="FFFFFF")
    s.arrow(9.72, 1.53)
    s.flow_box("Clarification", 10.12, 1.35, 1.75, fill=GOLD, color="FFFFFF")
    s.card("统一校验", "所有来源的任务都必须进入 TaskInputValidator。\n不允许任一匹配层直接返回最终任务。", 0.9, 3.0, 3.55, 1.55, accent=TEAL)
    s.card("缺失判断", "根据 task_type 查 required_inputs。\n用户未明确提供的数据，写入 missing_inputs。", 4.9, 3.0, 3.55, 1.55, accent=GOLD)
    s.card("澄清输出", "例如“销售提成”会识别任务，但缺失计算规则、销售数据来源、统计范围。", 8.9, 3.0, 3.55, 1.55, accent=GREEN)
    s.text("关键原则：不默认、不补全、不猜测。", 2.3, 5.35, 8.8, 0.38, size=20, bold=True, color=NAVY, align="c")
    slides.append(s)

    s = SlideBuilder(9, "自然语言评测体系")
    s.metric("100", "标准评测样本", 0.8, 1.08, 2.15, color=TEAL)
    s.metric("100%", "engine 准确率", 3.25, 1.08, 2.15, color=GREEN)
    s.metric("100%", "task_type 准确率", 5.7, 1.08, 2.15, color=GREEN)
    s.metric("100%", "澄清准确率", 8.15, 1.08, 2.15, color=GREEN)
    s.metric("0", "失败案例", 10.6, 1.08, 2.15, color=GREEN)
    s.card("覆盖场景", "规则明确请求：35\n语义表达变化：20\n信息缺失请求：15\n多任务请求：10\n智能问答请求：10\n未知请求：5\n错误表达：5", 0.9, 3.0, 4.05, 2.55, accent=TEAL)
    s.card("优化前后对比", "优化前：96 / 100 通过\nengine：97%\ntask_type：96%\nclarification：99%\n\n优化后：100 / 100 通过", 5.2, 3.0, 3.45, 2.55, accent=GOLD)
    s.card("评测价值", "后续规则、BGE、LLM 调整后，可以重新运行评测集和回归案例，避免旧问题反复出现。", 8.9, 3.0, 3.45, 2.55, accent=GREEN)
    slides.append(s)

    s = SlideBuilder(10, "典型识别案例")
    cases = [
        ("销售提成", "规则计算任务\n缺失：计算规则、销售数据来源、统计范围\n触发澄清"),
        ("帮我看看销售人员奖金怎么算", "BGE 语义匹配\n识别为销售提成计算\n进入输入校验"),
        ("最近经营情况怎么样", "经营分析任务\n匹配分析预测引擎\n根据缺失项澄清"),
        ("把上个月各区域销售数据整理出来，算提成，再生成凭证", "拆解 3 个任务：获取销售明细 → 计算销售提成 → 生成计提凭证"),
    ]
    for i, (query, result) in enumerate(cases):
        x = 0.72 + (i % 2) * 6.25
        y = 1.08 + (i // 2) * 2.18
        s.rect(x, y, 5.82, 1.72, fill=CARD, line=BORDER, radius=True)
        s.text(f"“{query}”", x + 0.28, y + 0.28, 5.25, 0.28, size=13, bold=True, color=NAVY)
        s.text(result, x + 0.28, y + 0.75, 5.25, 0.48, size=10, color=MUTED)
    slides.append(s)

    s = SlideBuilder(11, "当前实现情况")
    s.card("后端能力", "StandardIntentAnalyzer\nOperationRuleMatcher\nTaskDecomposer\nSemanticMatcher\nTaskInputValidator\nDebug 模式\n标准 API 输出", 0.65, 1.0, 3.85, 4.9, accent=TEAL)
    s.card("配置与基础设施", "semantic_capabilities.yaml\nintent_capability_vectors\nDocker profiles\nPIP_NO_CACHE_DIR=1\n默认仅启动 backend + postgres", 4.76, 1.0, 3.85, 4.9, accent=GOLD)
    s.card("演示与验证", "在线可视化平台\n离线演示平台\n100 条评测集\n回归案例\n当前容器：backend / frontend / postgres 运行中", 8.88, 1.0, 3.85, 4.9, accent=GREEN)
    slides.append(s)

    s = SlideBuilder(12, "汇报演示入口与后续计划")
    s.card("在线演示", "http://127.0.0.1:5173/\n\n适合展示真实前后端 API 链路。\n当前 frontend、backend、postgres 已运行。", 0.65, 1.05, 5.85, 2.0, accent=TEAL)
    s.card("离线演示", "offline-demo/intent-offline-demo.html\n\n适合无 Docker、无网络、无模型环境下汇报演示。", 6.83, 1.05, 5.85, 2.0, accent=GOLD)
    s.card("后续计划", "1. 扩充真实业务语料\n2. 持续调优规则优先级\n3. 恢复并稳定 Milvus 语义 profile\n4. 严格约束 LLM 输出只使用登记库\n5. 增加更多回归测试", 0.65, 3.55, 12.03, 1.85, accent=GREEN)
    s.text("阶段结论：当前系统已经形成可演示、可评测、可扩展的 Intent Analysis Engine 闭环。", 1.05, 6.03, 11.2, 0.36, size=18, bold=True, color=NAVY, align="c")
    slides.append(s)

    return slides


def write_pptx(output_path: Path, slides: Iterable[SlideBuilder]) -> None:
    slide_list = list(slides)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output_path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types(len(slide_list)))
        archive.writestr("_rels/.rels", root_rels())
        archive.writestr("docProps/core.xml", core_props())
        archive.writestr("docProps/app.xml", app_props(len(slide_list)))
        archive.writestr("ppt/presentation.xml", presentation_xml(len(slide_list)))
        archive.writestr("ppt/_rels/presentation.xml.rels", presentation_rels(len(slide_list)))
        archive.writestr("ppt/slideMasters/slideMaster1.xml", slide_master_xml())
        archive.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", slide_master_rels())
        archive.writestr("ppt/slideLayouts/slideLayout1.xml", slide_layout_xml())
        archive.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", slide_layout_rels())
        archive.writestr("ppt/theme/theme1.xml", theme_xml())
        for slide in slide_list:
            archive.writestr(f"ppt/slides/slide{slide.index}.xml", slide.xml())
            archive.writestr(f"ppt/slides/_rels/slide{slide.index}.xml.rels", slide_rels())


def content_types(slide_count: int) -> str:
    slide_overrides = "\n".join(
        f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        for i in range(1, slide_count + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
  <Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
  <Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
  {slide_overrides}
</Types>
"""


def root_rels() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""


def presentation_xml(slide_count: int) -> str:
    slide_ids = "\n".join(
        f'<p:sldId id="{255 + i}" r:id="rId{i + 1}"/>' for i in range(1, slide_count + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
                xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
                xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>
  <p:sldIdLst>{slide_ids}</p:sldIdLst>
  <p:sldSz cx="{SLIDE_W}" cy="{SLIDE_H}" type="wide"/>
  <p:notesSz cx="6858000" cy="9144000"/>
  <p:defaultTextStyle>
    <a:defPPr><a:defRPr lang="zh-CN"><a:latin typeface="{FONT}"/><a:ea typeface="{FONT}"/></a:defRPr></a:defPPr>
  </p:defaultTextStyle>
</p:presentation>
"""


def presentation_rels(slide_count: int) -> str:
    rels = ['<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>']
    for i in range(1, slide_count + 1):
        rels.append(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i}.xml"/>')
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  {' '.join(rels)}
</Relationships>
"""


def slide_rels() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
</Relationships>
"""


def slide_master_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
             xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
             xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>
  <p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
  <p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>
  <p:txStyles>
    <p:titleStyle><a:lvl1pPr algn="l"><a:defRPr sz="3200"><a:latin typeface="{FONT}"/><a:ea typeface="{FONT}"/></a:defRPr></a:lvl1pPr></p:titleStyle>
    <p:bodyStyle><a:lvl1pPr algn="l"><a:defRPr sz="1800"><a:latin typeface="{FONT}"/><a:ea typeface="{FONT}"/></a:defRPr></a:lvl1pPr></p:bodyStyle>
    <p:otherStyle><a:lvl1pPr algn="l"><a:defRPr sz="1800"><a:latin typeface="{FONT}"/><a:ea typeface="{FONT}"/></a:defRPr></a:lvl1pPr></p:otherStyle>
  </p:txStyles>
</p:sldMaster>
"""


def slide_master_rels() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>
"""


def slide_layout_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
             xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
             xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
             type="blank" preserve="1">
  <p:cSld name="Blank"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sldLayout>
"""


def slide_layout_rels() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>
</Relationships>
"""


def theme_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="IntentTheme">
  <a:themeElements>
    <a:clrScheme name="IntentColors">
      <a:dk1><a:srgbClr val="{TEXT}"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>
      <a:dk2><a:srgbClr val="{NAVY}"/></a:dk2><a:lt2><a:srgbClr val="{BG}"/></a:lt2>
      <a:accent1><a:srgbClr val="{TEAL}"/></a:accent1><a:accent2><a:srgbClr val="{GOLD}"/></a:accent2>
      <a:accent3><a:srgbClr val="{GREEN}"/></a:accent3><a:accent4><a:srgbClr val="{RED}"/></a:accent4>
      <a:accent5><a:srgbClr val="60707A"/></a:accent5><a:accent6><a:srgbClr val="D6E0E6"/></a:accent6>
      <a:hlink><a:srgbClr val="{TEAL}"/></a:hlink><a:folHlink><a:srgbClr val="{TEAL_DARK}"/></a:folHlink>
    </a:clrScheme>
    <a:fontScheme name="IntentFonts">
      <a:majorFont><a:latin typeface="{FONT}"/><a:ea typeface="{FONT}"/><a:cs typeface="{FONT}"/></a:majorFont>
      <a:minorFont><a:latin typeface="{FONT}"/><a:ea typeface="{FONT}"/><a:cs typeface="{FONT}"/></a:minorFont>
    </a:fontScheme>
    <a:fmtScheme name="IntentFormat"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst><a:lnStyleLst><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst><a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst><a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme>
  </a:themeElements>
  <a:objectDefaults/><a:extraClrSchemeLst/>
</a:theme>
"""


def core_props() -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                   xmlns:dc="http://purl.org/dc/elements/1.1/"
                   xmlns:dcterms="http://purl.org/dc/terms/"
                   xmlns:dcmitype="http://purl.org/dc/dcmitype/"
                   xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>自然语言意图分析引擎项目汇报</dc:title>
  <dc:creator>Codex</dc:creator>
  <cp:lastModifiedBy>Codex</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>
</cp:coreProperties>
"""


def app_props(slide_count: int) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
            xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Codex</Application>
  <PresentationFormat>On-screen Show (16:9)</PresentationFormat>
  <Slides>{slide_count}</Slides>
  <Company>Intent Analysis Engine</Company>
</Properties>
"""


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    output = repo_root / "docs" / "reports" / "intent-analysis-engine-report-20260710.pptx"
    write_pptx(output, build_slides())
    print(output)


if __name__ == "__main__":
    main()
