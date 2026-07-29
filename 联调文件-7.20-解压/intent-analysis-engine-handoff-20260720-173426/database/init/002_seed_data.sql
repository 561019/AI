INSERT INTO function_registry (
    function_code,
    function_name,
    intent_category,
    target_engine,
    description,
    required_parameters,
    example_sentences,
    status
) VALUES
(
    'FUNC_REPORT_GENERATION',
    U&'\62A5\544A\751F\6210',
    U&'\62A5\544A\751F\6210\578B',
    U&'\5185\5BB9\4EA7\51FA\5F15\64CE',
    'Generate a business report after data source, period, and report type are clear.',
    '["report_type", "data_source", "period"]'::jsonb,
    '["\u751f\u6210\u62a5\u544a", "\u505a\u4e00\u4efd\u7ecf\u8425\u5206\u6790\u62a5\u544a"]'::jsonb,
    'active'
),
(
    'FUNC_INTELLIGENT_QA',
    U&'\667A\80FD\95EE\7B54',
    U&'\667A\80FD\95EE\7B54\578B',
    U&'\77E5\8BC6\5E93\95EE\7B54\5F15\64CE',
    'Answer business questions that are covered by platform capabilities.',
    '["question"]'::jsonb,
    '["\u67e5\u8be2\u6570\u636e", "\u8fd9\u4e2a\u95ee\u9898\u600e\u4e48\u5904\u7406"]'::jsonb,
    'active'
),
(
    'FUNC_DATA_PROCESSING',
    U&'\6570\636E\5904\7406',
    U&'\6570\636E\5904\7406\578B',
    U&'\6570\636E\5F52\96C6\805A\5408\5F15\64CE',
    'Process explicit data sources with aggregation, grouping, or cleanup operations.',
    '["data_source", "operation"]'::jsonb,
    '["\u6c47\u603b\u8fd9\u5f20\u8868", "\u6309\u4ea7\u54c1\u5206\u7c7b\u6c42\u548c"]'::jsonb,
    'active'
),
(
    'FUNC_CONTENT_CREATION',
    U&'\5185\5BB9\521B\4F5C',
    U&'\5185\5BB9\521B\4F5C\578B',
    U&'\5185\5BB9\4EA7\51FA\5F15\64CE',
    'Create business content after topic and content type are clear.',
    '["topic", "content_type"]'::jsonb,
    '["\u5199\u4e00\u6bb5\u8bf4\u660e", "\u751f\u6210\u4e00\u4efd\u901a\u77e5"]'::jsonb,
    'active'
)
ON CONFLICT (function_code) DO NOTHING;

INSERT INTO function_registry (
    function_code,
    function_name,
    intent_category,
    target_engine,
    description,
    required_parameters,
    example_sentences,
    status
) VALUES
(
    'ENG_DOCUMENT_TABLE_PARSING',
    '文档表格解析引擎',
    '数据查询型',
    '文档表格解析引擎',
    'Registered downstream engine for document and spreadsheet parsing tasks. Intent analysis only routes tasks to this engine.',
    '{"supported_intents":["数据查询型","数据分析型"],"supported_tasks":["DOCUMENT_TABLE_PARSE","FILE_STRUCTURE_EXTRACT"],"required_inputs":["file"]}'::jsonb,
    '["解析这份Excel", "读取上传表格结构"]'::jsonb,
    'active'
),
(
    'ENG_EXTERNAL_SYSTEM_CONNECTOR',
    '外部系统对接引擎',
    '外部系统操作型',
    '外部系统对接引擎',
    'Registered downstream engine for external system fetch and submit tasks.',
    '{"supported_intents":["数据查询型","外部系统操作型"],"supported_tasks":["EXTERNAL_DATA_FETCH","EXTERNAL_SYSTEM_SUBMIT"],"required_inputs":["external_system","operation"]}'::jsonb,
    '["从CRM获取客户信息", "提交到财务系统"]'::jsonb,
    'active'
),
(
    'ENG_DATA_COLLECTION_AGGREGATION',
    '数据归集聚合引擎',
    '数据分析型',
    '数据归集聚合引擎',
    'Registered downstream engine for data fetch, aggregation, filtering, sorting, and pivot tasks.',
    '{"supported_intents":["数据查询型","数据分析型"],"supported_tasks":["DATA_QUERY_FETCH","DATA_AGGREGATION_SUMMARY","DATA_ANALYSIS_GROUP_SUM","DATA_ANALYSIS_PIVOT","DATA_FILTER","DATA_SORT","COMPLAINT_INFORMATION_ORGANIZE"],"required_inputs":["data_source","operation"],"legacy_function_codes":["FUNC_DATA_PROCESSING"]}'::jsonb,
    '["统计销售金额", "生成销售数据透视表"]'::jsonb,
    'active'
),
(
    'ENG_RULE_CALCULATION',
    '规则计算引擎',
    '规则计算型',
    '规则计算引擎',
    'Registered downstream engine for policy, rule, and formula based calculation tasks.',
    '{"supported_intents":["规则计算型"],"supported_tasks":["RULE_CALCULATION_GENERAL","RULE_CALCULATION_COMMISSION"],"required_inputs":["calculation_policy","calculation_basis"]}'::jsonb,
    '["计算销售提成", "根据政策计算奖金"]'::jsonb,
    'active'
),
(
    'ENG_ANALYTICS_FORECASTING',
    '分析预测引擎',
    '数据分析型',
    '分析预测引擎',
    'Registered downstream engine for issue analysis, trend analysis, year-over-year, month-over-month, and forecast tasks.',
    '{"supported_intents":["数据分析型"],"supported_tasks":["DATA_ANALYSIS_PROBLEM","DATA_ANALYSIS_YOY","DATA_ANALYSIS_MOM","DATA_ANALYSIS_FORECAST"],"required_inputs":["analysis_object","analysis_method"]}'::jsonb,
    '["分析客户投诉原因", "做同比分析"]'::jsonb,
    'active'
),
(
    'ENG_KNOWLEDGE_QA',
    '知识库问答引擎',
    '智能问答型',
    '知识库问答引擎',
    'Registered downstream engine for simple knowledge question answering tasks.',
    '{"supported_intents":["智能问答型"],"supported_tasks":["QUESTION_ANSWER"],"required_inputs":["question"],"legacy_function_codes":["FUNC_INTELLIGENT_QA"]}'::jsonb,
    '["公司的报销政策是什么？", "什么是销售政策？"]'::jsonb,
    'active'
),
(
    'ENG_CONTENT_OUTPUT',
    '内容产出引擎',
    '内容生成型',
    '内容产出引擎',
    'Registered downstream engine for report, document, explanation, and plan generation tasks.',
    '{"supported_intents":["文档生成型","内容生成型"],"supported_tasks":["DOCUMENT_GENERATE","CONTENT_GENERATE","IMPROVEMENT_PLAN_GENERATE"],"required_inputs":["topic","content_type"],"legacy_function_codes":["FUNC_REPORT_GENERATION","FUNC_CONTENT_CREATION"]}'::jsonb,
    '["生成经营分析报告", "生成改进方案"]'::jsonb,
    'active'
),
(
    'ENG_MULTIMEDIA_GENERATION',
    '多媒体生成引擎',
    '内容生成型',
    '多媒体生成引擎',
    'Registered downstream engine for image, audio, and video generation tasks.',
    '{"supported_intents":["内容生成型"],"supported_tasks":["MULTIMEDIA_GENERATE"],"required_inputs":["media_type","topic"]}'::jsonb,
    '["生成宣传图片", "制作讲解视频"]'::jsonb,
    'active'
),
(
    'ENG_WORKFLOW_EXECUTION',
    '流程执行引擎',
    '流程办理型',
    '流程执行引擎',
    'Registered downstream engine for workflow initiation and process handling tasks.',
    '{"supported_intents":["流程办理型"],"supported_tasks":["PROCESS_HANDLE","WORKFLOW_START"],"required_inputs":["process_name","initiator"]}'::jsonb,
    '["发起审批流程", "办理报销流程"]'::jsonb,
    'active'
),
(
    'ENG_MONITORING_REMINDER',
    '监控提醒引擎',
    '流程办理型',
    '监控提醒引擎',
    'Registered downstream engine for monitoring, alerting, and reminder tasks.',
    '{"supported_intents":["流程办理型"],"supported_tasks":["MONITORING_REMINDER"],"required_inputs":["monitoring_object","trigger_condition"]}'::jsonb,
    '["到期提醒我", "监控库存低于阈值"]'::jsonb,
    'active'
),
(
    'ENG_DIGITAL_ASSET',
    '数字资产引擎',
    '外部系统操作型',
    '数字资产引擎',
    'Registered downstream engine for voucher, document, and digital asset creation tasks.',
    '{"supported_intents":["外部系统操作型","文档生成型"],"supported_tasks":["DIGITAL_ASSET_ACCRUAL_VOUCHER"],"required_inputs":["asset_type","source_result"]}'::jsonb,
    '["生成计提凭证", "创建业务单据"]'::jsonb,
    'active'
)
ON CONFLICT (function_code) DO NOTHING;

INSERT INTO rule_mapping (
    keyword,
    pattern,
    function_code,
    priority,
    status
) VALUES
(U&'\751F\6210\62A5\544A', U&'\751F\6210\62A5\544A', 'FUNC_REPORT_GENERATION', 10, 'active'),
(U&'\67E5\8BE2\6570\636E', U&'\67E5\8BE2\6570\636E', 'FUNC_INTELLIGENT_QA', 20, 'active'),
(U&'\8BA1\7B97', U&'\8BA1\7B97', 'FUNC_DATA_PROCESSING', 30, 'active'),
(U&'\6C47\603B', U&'\6C47\603B', 'FUNC_DATA_PROCESSING', 40, 'active')
ON CONFLICT DO NOTHING;
