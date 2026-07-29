from dataclasses import dataclass, field
from typing import Literal


CaseCategory = Literal[
    "rule_hit",
    "semantic_hit",
    "complex_llm",
    "missing_parameter",
    "meaningless",
]


@dataclass(frozen=True)
class TaskSpec:
    function_code: str
    function_name: str
    intent_category: str
    target_engine: str
    parameters: dict = field(default_factory=dict)
    dependency: list[str] = field(default_factory=list)
    priority: int = 1
    confidence: float = 0.9


@dataclass(frozen=True)
class E2ECase:
    case_id: str
    category: CaseCategory
    text: str
    expected_level: int
    expected_tasks: list[TaskSpec] = field(default_factory=list)
    expected_success: bool = True
    expected_error_code: str | None = None
    expected_missing_parameters: list[str] = field(default_factory=list)
    confidence: float = 0.9

    @property
    def expected_function(self) -> str | None:
        return self.expected_tasks[0].function_code if self.expected_tasks else None


def task(
    function_code: str,
    function_name: str,
    intent_category: str,
    target_engine: str,
    *,
    confidence: float = 0.9,
    parameters: dict | None = None,
    dependency: list[str] | None = None,
    priority: int = 1,
) -> TaskSpec:
    return TaskSpec(
        function_code=function_code,
        function_name=function_name,
        intent_category=intent_category,
        target_engine=target_engine,
        parameters=parameters or {},
        dependency=dependency or [],
        priority=priority,
        confidence=confidence,
    )


REPORT_TASK = task("REPORT_CREATE", "报告生成", "报告生成型", "report_engine", confidence=0.96)
QA_TASK = task("KNOWLEDGE_QA", "智能问答", "智能问答型", "knowledge_qa_engine", confidence=0.94)
DATA_QUERY_TASK = task("DATA_QUERY", "数据查询", "智能问答型", "knowledge_qa_engine", confidence=0.93)
CALC_TASK = task("CALCULATION", "计算处理", "数据处理型", "calculation_engine", confidence=0.95)
SUMMARY_TASK = task("DATA_SUMMARY", "数据汇总", "数据处理型", "data_engine", confidence=0.94)
CONTENT_TASK = task("CONTENT_CREATE", "内容创作", "内容创作型", "content_engine", confidence=0.92)
DOC_TASK = task("DOCUMENT_PARSE", "文档解析", "数据处理型", "document_engine", confidence=0.9)
WORKFLOW_TASK = task("WORKFLOW_AGENT", "流程编排", "流程处理型", "workflow_engine", confidence=0.88)
IMAGE_TASK = task("IMAGE_RECOGNITION", "图像识别", "图像识别型", "media_engine", confidence=0.86)


RULE_CASES = [
    E2ECase("RULE-001", "rule_hit", "生成报告", 1, [REPORT_TASK], confidence=1.0),
    E2ECase("RULE-002", "rule_hit", "帮我生成一份销售分析报告", 1, [REPORT_TASK], confidence=0.96),
    E2ECase("RULE-003", "rule_hit", "生成经营月报", 1, [REPORT_TASK], confidence=0.95),
    E2ECase("RULE-004", "rule_hit", "请生成财务报告", 1, [REPORT_TASK], confidence=0.95),
    E2ECase("RULE-005", "rule_hit", "生成季度复盘报告", 1, [REPORT_TASK], confidence=0.94),
    E2ECase("RULE-006", "rule_hit", "查询数据", 1, [DATA_QUERY_TASK], confidence=1.0),
    E2ECase("RULE-007", "rule_hit", "帮我查询客户数据", 1, [DATA_QUERY_TASK], confidence=0.95),
    E2ECase("RULE-008", "rule_hit", "查询本月销售数据", 1, [DATA_QUERY_TASK], confidence=0.95),
    E2ECase("RULE-009", "rule_hit", "查询回款明细", 1, [DATA_QUERY_TASK], confidence=0.94),
    E2ECase("RULE-010", "rule_hit", "查询订单数据", 1, [DATA_QUERY_TASK], confidence=0.94),
    E2ECase("RULE-011", "rule_hit", "计算", 1, [CALC_TASK], confidence=1.0),
    E2ECase("RULE-012", "rule_hit", "帮我计算提成", 1, [CALC_TASK], confidence=0.96),
    E2ECase("RULE-013", "rule_hit", "计算各区域费用", 1, [CALC_TASK], confidence=0.95),
    E2ECase("RULE-014", "rule_hit", "计算项目成本", 1, [CALC_TASK], confidence=0.94),
    E2ECase("RULE-015", "rule_hit", "计算本月利润率", 1, [CALC_TASK], confidence=0.94),
    E2ECase("RULE-016", "rule_hit", "汇总", 1, [SUMMARY_TASK], confidence=1.0),
    E2ECase("RULE-017", "rule_hit", "帮我汇总产品销量", 1, [SUMMARY_TASK], confidence=0.96),
    E2ECase("RULE-018", "rule_hit", "汇总各部门预算", 1, [SUMMARY_TASK], confidence=0.95),
    E2ECase("RULE-019", "rule_hit", "汇总销售明细", 1, [SUMMARY_TASK], confidence=0.95),
    E2ECase("RULE-020", "rule_hit", "汇总客户反馈", 1, [SUMMARY_TASK], confidence=0.94),
    E2ECase("RULE-021", "rule_hit", "生成一份运营分析报告", 1, [REPORT_TASK], confidence=0.95),
    E2ECase("RULE-022", "rule_hit", "查询库存数据", 1, [DATA_QUERY_TASK], confidence=0.94),
    E2ECase("RULE-023", "rule_hit", "计算人均产出", 1, [CALC_TASK], confidence=0.93),
    E2ECase("RULE-024", "rule_hit", "汇总区域业绩", 1, [SUMMARY_TASK], confidence=0.94),
    E2ECase("RULE-025", "rule_hit", "生成风险排查报告", 1, [REPORT_TASK], confidence=0.95),
    E2ECase("RULE-026", "rule_hit", "查询合同执行数据", 1, [DATA_QUERY_TASK], confidence=0.94),
    E2ECase("RULE-027", "rule_hit", "计算客户续费率", 1, [CALC_TASK], confidence=0.93),
    E2ECase("RULE-028", "rule_hit", "汇总日报数据", 1, [SUMMARY_TASK], confidence=0.94),
    E2ECase("RULE-029", "rule_hit", "帮我生成市场活动总结报告", 1, [REPORT_TASK], confidence=0.95),
    E2ECase("RULE-030", "rule_hit", "查询员工绩效数据", 1, [DATA_QUERY_TASK], confidence=0.94),
]


SEMANTIC_CASES = [
    E2ECase("SEM-001", "semantic_hit", "帮我整理经营情况", 2, [REPORT_TASK], confidence=0.88),
    E2ECase("SEM-002", "semantic_hit", "做个经营情况总结", 2, [REPORT_TASK], confidence=0.87),
    E2ECase("SEM-003", "semantic_hit", "把业务表现复盘一下", 2, [REPORT_TASK], confidence=0.86),
    E2ECase("SEM-004", "semantic_hit", "整理一份门店表现材料", 2, [REPORT_TASK], confidence=0.86),
    E2ECase("SEM-005", "semantic_hit", "帮我看看销售完成情况", 2, [DATA_QUERY_TASK], confidence=0.87),
    E2ECase("SEM-006", "semantic_hit", "本月回款做到哪里了", 2, [DATA_QUERY_TASK], confidence=0.86),
    E2ECase("SEM-007", "semantic_hit", "看一下客户跟进状态", 2, [DATA_QUERY_TASK], confidence=0.85),
    E2ECase("SEM-008", "semantic_hit", "我想了解库存变化", 2, [DATA_QUERY_TASK], confidence=0.85),
    E2ECase("SEM-009", "semantic_hit", "核一下各区域提成", 2, [CALC_TASK], confidence=0.88),
    E2ECase("SEM-010", "semantic_hit", "费用金额过一遍", 2, [CALC_TASK], confidence=0.86),
    E2ECase("SEM-011", "semantic_hit", "帮我估一下这批成本", 2, [CALC_TASK], confidence=0.84),
    E2ECase("SEM-012", "semantic_hit", "算出每个销售的绩效", 2, [CALC_TASK], confidence=0.86),
    E2ECase("SEM-013", "semantic_hit", "把表格内容归并一下", 2, [SUMMARY_TASK], confidence=0.87),
    E2ECase("SEM-014", "semantic_hit", "按类别收一下金额", 2, [SUMMARY_TASK], confidence=0.86),
    E2ECase("SEM-015", "semantic_hit", "做个数据合计", 2, [SUMMARY_TASK], confidence=0.85),
    E2ECase("SEM-016", "semantic_hit", "整理产品分类金额", 2, [SUMMARY_TASK], confidence=0.84),
    E2ECase("SEM-017", "semantic_hit", "帮我起草一段通知", 2, [CONTENT_TASK], confidence=0.85),
    E2ECase("SEM-018", "semantic_hit", "写个对外说明", 2, [CONTENT_TASK], confidence=0.84),
    E2ECase("SEM-019", "semantic_hit", "生成一段客户回复话术", 2, [CONTENT_TASK], confidence=0.84),
    E2ECase("SEM-020", "semantic_hit", "帮我润色会议纪要", 2, [CONTENT_TASK], confidence=0.83),
    E2ECase("SEM-021", "semantic_hit", "这个制度应该怎么理解", 2, [QA_TASK], confidence=0.86),
    E2ECase("SEM-022", "semantic_hit", "报销规则能不能解释下", 2, [QA_TASK], confidence=0.85),
    E2ECase("SEM-023", "semantic_hit", "这个政策问题答一下", 2, [QA_TASK], confidence=0.84),
    E2ECase("SEM-024", "semantic_hit", "帮我处理报销问题咨询", 2, [QA_TASK], confidence=0.84),
    E2ECase("SEM-025", "semantic_hit", "识别图片里的异常", 2, [IMAGE_TASK], confidence=0.82),
    E2ECase("SEM-026", "semantic_hit", "看一下截图中有什么问题", 2, [IMAGE_TASK], confidence=0.81),
    E2ECase("SEM-027", "semantic_hit", "安排一次自动办理", 2, [WORKFLOW_TASK], confidence=0.82),
    E2ECase("SEM-028", "semantic_hit", "自动帮我跑这个流程", 2, [WORKFLOW_TASK], confidence=0.81),
    E2ECase("SEM-029", "semantic_hit", "读取表格字段并整理", 2, [DOC_TASK], confidence=0.82),
    E2ECase("SEM-030", "semantic_hit", "把这份文件内容抽出来", 2, [DOC_TASK], confidence=0.81),
]


COMPLEX_LLM_CASES = [
    E2ECase("LLM-001", "complex_llm", "先汇总销售数据，再生成月度经营报告", 3, [SUMMARY_TASK, task("REPORT_CREATE", "报告生成", "报告生成型", "report_engine", dependency=["DATA_SUMMARY"], priority=2, confidence=0.86)], confidence=0.86),
    E2ECase("LLM-002", "complex_llm", "查询回款情况并起草客户催收说明", 3, [DATA_QUERY_TASK, task("CONTENT_CREATE", "内容创作", "内容创作型", "content_engine", dependency=["DATA_QUERY"], priority=2, confidence=0.84)], confidence=0.84),
    E2ECase("LLM-003", "complex_llm", "读取费用表，计算各部门占比，然后写结论", 3, [DOC_TASK, task("CALCULATION", "计算处理", "数据处理型", "calculation_engine", dependency=["DOCUMENT_PARSE"], priority=2, confidence=0.86), task("CONTENT_CREATE", "内容创作", "内容创作型", "content_engine", dependency=["CALCULATION"], priority=3, confidence=0.82)], confidence=0.82),
    E2ECase("LLM-004", "complex_llm", "解释报销制度，并生成一段回复给员工", 3, [QA_TASK, task("CONTENT_CREATE", "内容创作", "内容创作型", "content_engine", dependency=["KNOWLEDGE_QA"], priority=2, confidence=0.84)], confidence=0.84),
    E2ECase("LLM-005", "complex_llm", "识别图片问题，再整理成检查报告", 3, [IMAGE_TASK, task("REPORT_CREATE", "报告生成", "报告生成型", "report_engine", dependency=["IMAGE_RECOGNITION"], priority=2, confidence=0.83)], confidence=0.83),
    E2ECase("LLM-006", "complex_llm", "解析合同文件，查询客户历史数据，并输出风险说明", 3, [DOC_TASK, task("DATA_QUERY", "数据查询", "智能问答型", "knowledge_qa_engine", dependency=["DOCUMENT_PARSE"], priority=2, confidence=0.84), task("CONTENT_CREATE", "内容创作", "内容创作型", "content_engine", dependency=["DATA_QUERY"], priority=3, confidence=0.81)], confidence=0.81),
    E2ECase("LLM-007", "complex_llm", "汇总门店销量，计算同比，再生成复盘材料", 3, [SUMMARY_TASK, task("CALCULATION", "计算处理", "数据处理型", "calculation_engine", dependency=["DATA_SUMMARY"], priority=2, confidence=0.85), task("REPORT_CREATE", "报告生成", "报告生成型", "report_engine", dependency=["CALCULATION"], priority=3, confidence=0.82)], confidence=0.82),
    E2ECase("LLM-008", "complex_llm", "查询库存异常并安排后续处理流程", 3, [DATA_QUERY_TASK, task("WORKFLOW_AGENT", "流程编排", "流程处理型", "workflow_engine", dependency=["DATA_QUERY"], priority=2, confidence=0.82)], confidence=0.82),
    E2ECase("LLM-009", "complex_llm", "把客户反馈归类，并写一份改进建议", 3, [SUMMARY_TASK, task("CONTENT_CREATE", "内容创作", "内容创作型", "content_engine", dependency=["DATA_SUMMARY"], priority=2, confidence=0.84)], confidence=0.84),
    E2ECase("LLM-010", "complex_llm", "查看政策问题，生成通知，并发起审批流程", 3, [QA_TASK, task("CONTENT_CREATE", "内容创作", "内容创作型", "content_engine", dependency=["KNOWLEDGE_QA"], priority=2, confidence=0.83), task("WORKFLOW_AGENT", "流程编排", "流程处理型", "workflow_engine", dependency=["CONTENT_CREATE"], priority=3, confidence=0.8)], confidence=0.8),
    E2ECase("LLM-011", "complex_llm", "分析销售下降原因并生成管理层简报", 3, [DATA_QUERY_TASK, task("REPORT_CREATE", "报告生成", "报告生成型", "report_engine", dependency=["DATA_QUERY"], priority=2, confidence=0.85)], confidence=0.85),
    E2ECase("LLM-012", "complex_llm", "解析名单，计算分组人数，并输出汇总", 3, [DOC_TASK, task("CALCULATION", "计算处理", "数据处理型", "calculation_engine", dependency=["DOCUMENT_PARSE"], priority=2, confidence=0.85), task("DATA_SUMMARY", "数据汇总", "数据处理型", "data_engine", dependency=["CALCULATION"], priority=3, confidence=0.82)], confidence=0.82),
    E2ECase("LLM-013", "complex_llm", "检查图片中的设备状态并生成巡检说明", 3, [IMAGE_TASK, task("CONTENT_CREATE", "内容创作", "内容创作型", "content_engine", dependency=["IMAGE_RECOGNITION"], priority=2, confidence=0.82)], confidence=0.82),
    E2ECase("LLM-014", "complex_llm", "查询客户画像，汇总重点客户，并写跟进计划", 3, [DATA_QUERY_TASK, task("DATA_SUMMARY", "数据汇总", "数据处理型", "data_engine", dependency=["DATA_QUERY"], priority=2, confidence=0.84), task("CONTENT_CREATE", "内容创作", "内容创作型", "content_engine", dependency=["DATA_SUMMARY"], priority=3, confidence=0.81)], confidence=0.81),
    E2ECase("LLM-015", "complex_llm", "读取销售表，汇总区域业绩并生成图文说明", 3, [DOC_TASK, task("DATA_SUMMARY", "数据汇总", "数据处理型", "data_engine", dependency=["DOCUMENT_PARSE"], priority=2, confidence=0.84), task("CONTENT_CREATE", "内容创作", "内容创作型", "content_engine", dependency=["DATA_SUMMARY"], priority=3, confidence=0.81)], confidence=0.81),
    E2ECase("LLM-016", "complex_llm", "基于费用明细计算预算差异并生成风险提示", 3, [CALC_TASK, task("CONTENT_CREATE", "内容创作", "内容创作型", "content_engine", dependency=["CALCULATION"], priority=2, confidence=0.83)], confidence=0.83),
    E2ECase("LLM-017", "complex_llm", "先回答制度问题，再整理给管理层看的摘要", 3, [QA_TASK, task("DATA_SUMMARY", "数据汇总", "数据处理型", "data_engine", dependency=["KNOWLEDGE_QA"], priority=2, confidence=0.82)], confidence=0.82),
    E2ECase("LLM-018", "complex_llm", "识别截图里的报错并起草处理流程", 3, [IMAGE_TASK, task("WORKFLOW_AGENT", "流程编排", "流程处理型", "workflow_engine", dependency=["IMAGE_RECOGNITION"], priority=2, confidence=0.81)], confidence=0.81),
    E2ECase("LLM-019", "complex_llm", "把会议纪要提炼任务清单并生成提醒流程", 3, [SUMMARY_TASK, task("WORKFLOW_AGENT", "流程编排", "流程处理型", "workflow_engine", dependency=["DATA_SUMMARY"], priority=2, confidence=0.82)], confidence=0.82),
    E2ECase("LLM-020", "complex_llm", "解析供应商报价，计算差异并写采购建议", 3, [DOC_TASK, task("CALCULATION", "计算处理", "数据处理型", "calculation_engine", dependency=["DOCUMENT_PARSE"], priority=2, confidence=0.84), task("CONTENT_CREATE", "内容创作", "内容创作型", "content_engine", dependency=["CALCULATION"], priority=3, confidence=0.81)], confidence=0.81),
]


MISSING_PARAMETER_CASES = [
    E2ECase("MISS-001", "missing_parameter", "生成一个报告但主题和数据来源都没给", 3, [task("REPORT_CREATE", "报告生成", "报告生成型", "report_engine", parameters={"missing_parameters": ["report_topic", "data_source"]}, confidence=0.78)], expected_missing_parameters=["report_topic", "data_source"], confidence=0.78),
    E2ECase("MISS-002", "missing_parameter", "帮我生成本月报告，但是没说数据来源", 3, [task("REPORT_CREATE", "报告生成", "报告生成型", "report_engine", parameters={"missing_parameters": ["data_source"]}, confidence=0.8)], expected_missing_parameters=["data_source"], confidence=0.8),
    E2ECase("MISS-003", "missing_parameter", "查询一下数据", 3, [task("DATA_QUERY", "数据查询", "智能问答型", "knowledge_qa_engine", parameters={"missing_parameters": ["query_target", "time_range"]}, confidence=0.76)], expected_missing_parameters=["query_target", "time_range"], confidence=0.76),
    E2ECase("MISS-004", "missing_parameter", "帮我计算一下", 3, [task("CALCULATION", "计算处理", "数据处理型", "calculation_engine", parameters={"missing_parameters": ["formula", "input_data"]}, confidence=0.77)], expected_missing_parameters=["formula", "input_data"], confidence=0.77),
    E2ECase("MISS-005", "missing_parameter", "汇总一下这些内容", 3, [task("DATA_SUMMARY", "数据汇总", "数据处理型", "data_engine", parameters={"missing_parameters": ["source_content", "summary_dimension"]}, confidence=0.76)], expected_missing_parameters=["source_content", "summary_dimension"], confidence=0.76),
    E2ECase("MISS-006", "missing_parameter", "写一段说明", 3, [task("CONTENT_CREATE", "内容创作", "内容创作型", "content_engine", parameters={"missing_parameters": ["topic", "audience"]}, confidence=0.75)], expected_missing_parameters=["topic", "audience"], confidence=0.75),
    E2ECase("MISS-007", "missing_parameter", "安排一个流程", 3, [task("WORKFLOW_AGENT", "流程编排", "流程处理型", "workflow_engine", parameters={"missing_parameters": ["workflow_target", "participants"]}, confidence=0.74)], expected_missing_parameters=["workflow_target", "participants"], confidence=0.74),
    E2ECase("MISS-008", "missing_parameter", "看一下文件", 3, [task("DOCUMENT_PARSE", "文档解析", "数据处理型", "document_engine", parameters={"missing_parameters": ["file"]}, confidence=0.74)], expected_missing_parameters=["file"], confidence=0.74),
    E2ECase("MISS-009", "missing_parameter", "识别一下图片", 3, [task("IMAGE_RECOGNITION", "图像识别", "图像识别型", "media_engine", parameters={"missing_parameters": ["image"]}, confidence=0.73)], expected_missing_parameters=["image"], confidence=0.73),
    E2ECase("MISS-010", "missing_parameter", "回答这个问题", 3, [task("KNOWLEDGE_QA", "智能问答", "智能问答型", "knowledge_qa_engine", parameters={"missing_parameters": ["question_context"]}, confidence=0.73)], expected_missing_parameters=["question_context"], confidence=0.73),
]


MEANINGLESS_CASES = [
    E2ECase("NONE-001", "meaningless", "今天天气怎么样", 3, expected_success=False, expected_error_code="need_confirmation"),
    E2ECase("NONE-002", "meaningless", "哈哈哈哈", 3, expected_success=False, expected_error_code="need_confirmation"),
    E2ECase("NONE-003", "meaningless", "随便聊聊", 3, expected_success=False, expected_error_code="need_confirmation"),
    E2ECase("NONE-004", "meaningless", "帮我点一杯咖啡", 3, expected_success=False, expected_error_code="need_confirmation"),
    E2ECase("NONE-005", "meaningless", "播放一首歌", 3, expected_success=False, expected_error_code="need_confirmation"),
    E2ECase("NONE-006", "meaningless", "买一张彩票", 3, expected_success=False, expected_error_code="need_confirmation"),
    E2ECase("NONE-007", "meaningless", "桌面背景换一个", 3, expected_success=False, expected_error_code="need_confirmation"),
    E2ECase("NONE-008", "meaningless", "你是谁", 3, expected_success=False, expected_error_code="need_confirmation"),
    E2ECase("NONE-009", "meaningless", "明天放假吗", 3, expected_success=False, expected_error_code="need_confirmation"),
    E2ECase("NONE-010", "meaningless", "讲个笑话", 3, expected_success=False, expected_error_code="need_confirmation"),
]


CASES = [
    *RULE_CASES,
    *SEMANTIC_CASES,
    *COMPLEX_LLM_CASES,
    *MISSING_PARAMETER_CASES,
    *MEANINGLESS_CASES,
]
