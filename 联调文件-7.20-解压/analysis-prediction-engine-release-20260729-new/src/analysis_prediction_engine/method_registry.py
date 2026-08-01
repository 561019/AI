"""
分析方法注册表 — 集中登记本引擎全部四类分析方法。

每个方法在此登记：名称、分类、版本号、描述、输入输出字段。
服务模块引用此注册表取版本号，不再各自硬编码。
"""

from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet


class MethodCategory(str, Enum):
    COMPARISON = "comparison"          # 对比分析
    DECOMPOSITION = "decomposition"    # 拆解分析
    CAUSE_ANALYSIS = "cause_analysis"  # 原因分析
    PREDICTION = "prediction"          # 预测分析


@dataclass(frozen=True)
class AnalysisMethod:
    method_id: str              # 唯一标识，如 "METH-001"
    name: str                   # 中文名称，如 "同比增长率"
    category: MethodCategory    # 所属分析类型
    version: str                # 当前版本号
    description: str            # 一句话描述公式/算法
    source_module: str          # 实现所在模块，如 "calculators.core"


# ──────────────────────────────────────────────────────────────
# 已登记的全部分析方法
# ──────────────────────────────────────────────────────────────

REGISTERED_METHODS: tuple[AnalysisMethod, ...] = (
    # ── 对比分析 ──
    AnalysisMethod(
        method_id="METH-001",
        name="同比增长率",
        category=MethodCategory.COMPARISON,
        version="financial-v1",
        description="(本期值 - 去年同期值) / |去年同期值| × 100%",
        source_module="calculators.core",
    ),
    AnalysisMethod(
        method_id="METH-002",
        name="环比增长率",
        category=MethodCategory.COMPARISON,
        version="financial-v1",
        description="(本期值 - 上期值) / |上期值| × 100%",
        source_module="calculators.core",
    ),
    AnalysisMethod(
        method_id="METH-003",
        name="占比率",
        category=MethodCategory.COMPARISON,
        version="financial-v1",
        description="部分值 / 整体值 × 100%",
        source_module="calculators.core",
    ),
    AnalysisMethod(
        method_id="METH-004",
        name="目标阈值对比",
        category=MethodCategory.COMPARISON,
        version="business-metrics-v1",
        description="实际值与目标值比较，输出差异与是否超标标记",
        source_module="calculators.core",
    ),
    AnalysisMethod(
        method_id="METH-005",
        name="Z-score异常检测",
        category=MethodCategory.COMPARISON,
        version="financial-v1",
        description="(值 - 均值) / 标准差，超过阈值标记为异常",
        source_module="calculators.trend",
    ),

    # ── 拆解分析 ──
    AnalysisMethod(
        method_id="METH-006",
        name="杜邦分解",
        category=MethodCategory.DECOMPOSITION,
        version="financial-v1",
        description="ROE = 净利率 × 资产周转率 × 权益乘数，逐层拆解",
        source_module="calculators.dupont",
    ),
    AnalysisMethod(
        method_id="METH-007",
        name="成本结构拆解",
        category=MethodCategory.DECOMPOSITION,
        version="business-metrics-v1",
        description="按利润公式拆解：营收-销售成本-交付成本-运营成本=净利润，计算各成本占比",
        source_module="services.business_metrics",
    ),

    AnalysisMethod(
        method_id="METH-008",
        name="线性趋势方向判定",
        category=MethodCategory.COMPARISON,
        version="financial-v1",
        description="对时间序列做简单线性回归，判定趋势方向（上升/下降/稳定），供对比分析和原因解读使用",
        source_module="calculators.trend",
    ),

    # ── 原因分析 ──
    AnalysisMethod(
        method_id="METH-009",
        name="LLM结论解读",
        category=MethodCategory.CAUSE_ANALYSIS,
        version="llm-narrative-v1",
        description="调用大模型对已算好的数值做自然语言解读，指出趋势方向与显著异常项。模型只读已算数值，不参与计算",
        source_module="services.llm_narrative",
    ),
    AnalysisMethod(
        method_id="METH-011",
        name="经营诊断",
        category=MethodCategory.CAUSE_ANALYSIS,
        version="diagnostic-v1",
        description="定位主要贡献实体并基于证据生成根因假设。两层逻辑：确定性贡献度排序定位 + LLM读取证据找共因，每个假设必须引用证据",
        source_module="services.diagnostic",
    ),

    # ── 预测分析 ──
    AnalysisMethod(
        method_id="METH-010",
        name="线性趋势预测",
        category=MethodCategory.PREDICTION,
        version="linear-trend-v1",
        description="对连续月度数据做线性回归拟合，外推1~24期预测值，附95%残差带",
        source_module="forecasting.price_trend",
    ),
)

# ──────────────────────────────────────────────────────────────
# 按分析类型聚合的版本号（供服务模块引用）
# ──────────────────────────────────────────────────────────────

FINANCIAL_VERSION = "financial-v1"
BUSINESS_METRICS_VERSION = "business-metrics-v1"
PRICE_FORECAST_VERSION = "linear-trend-v1"
LLM_NARRATIVE_VERSION = "llm-narrative-v1"
DIAGNOSTIC_VERSION = "diagnostic-v1"

# ──────────────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────────────

def methods_by_category(category: MethodCategory) -> tuple[AnalysisMethod, ...]:
    """返回指定分类下的所有已登记方法。"""
    return tuple(m for m in REGISTERED_METHODS if m.category is category)


def get_method(version: str) -> AnalysisMethod | None:
    """按版本号查找方法。"""
    for m in REGISTERED_METHODS:
        if m.version == version:
            return m
    return None


def method_versions_by_category(category: MethodCategory) -> FrozenSet[str]:
    """返回指定分类下用到的全部版本号。"""
    return frozenset(m.version for m in methods_by_category(category))
