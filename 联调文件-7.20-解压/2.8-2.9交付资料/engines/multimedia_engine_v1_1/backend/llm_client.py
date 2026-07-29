from __future__ import annotations

from typing import Any
import json
import re
import urllib.error
import urllib.request

CAPABILITY_GUIDES = {
    "text_to_image": "面向图片/海报/商品图/版式设计图，输出画面方案、版式、素材使用、正向提示词和反向提示词。",
    "video_editing": "面向视频剪接，输出素材拆分、筛选、拼接、混剪、长转短节奏、字幕与转场建议。",
    "fixed_short_video": "面向固定类别短视频制作，输出分镜、镜头顺序、画面素材、字幕口播、成片结构和生成/组装提示词。",
    "text_to_speech": "面向文字转语音，输出朗读文本、音色要求、语速情绪、停顿重音、合规和真人音色确认要求。",
    "media_processing": "面向音画合成与媒体处理，输出字幕、抠像、音频清理、格式转换、合成成片流程和质量核查点。",
    "text_to_video": "预留文生视频/图生视频接口位，只说明所需输入输出，不承诺当前可生成。",
    "digital_human": "预留数字人接口位，只说明形象、口型、真人分身所需输入输出，不承诺当前可生成。",
    "music_sound": "预留音乐音效生成接口位，只说明所需输入输出，不承诺当前可生成。",
    "multilingual_version": "预留多语种翻译版本接口位，只说明所需输入输出，不承诺当前可生成。",
}


def normalize_chat_endpoint(base: str) -> str:
    base = base.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def normalize_anthropic_endpoint(base: str) -> str:
    base = base.rstrip("/")
    if base.endswith("/messages"):
        return base
    if base.endswith("/v1"):
        return base + "/messages"
    return base + "/v1/messages"


def build_messages(requirement: str, xml_context: str, capability_id: str, output_type: str) -> list[dict[str, str]]:
    guide = CAPABILITY_GUIDES.get(capability_id, "按传入能力接口位生成制作方案，不能编造当前接口未支持的能力。")
    system = f"""你是企业 AI 平台中的多媒体生成引擎联调助手。
你不会直接生成真实图片、视频或音频文件，而是根据检索到的知识库素材，生成可交给后续能力接口使用的制作方案、脚本、处理步骤或模型提示词。

当前能力接口位办理口径：
{guide}

以下是知识库检索到的信息，已按 documents/context 形式给出。你只能依据这些资料写方案，不要编造资料中没有的产品参数、效果承诺、法规或出处。

{xml_context}

输出要求：
1. 用中文。
2. 输出 JSON，不要输出 Markdown。
3. JSON 字段包含：title、capability_id、output_type、production_brief、visual_brief、positive_prompt、negative_prompt、material_usage、compliance_notes、human_review_required、citations。
4. production_brief 写该能力接口位的制作/处理方案；visual_brief 对图片或视频写画面方案，对语音或媒体处理可写声音/处理方案摘要。
5. material_usage 要说明用了哪些 context_id。
6. citations 必须引用 context_id、document_id、title、citation。"""
    user = f"""[Runtime Context]
当前任务能力接口位：{capability_id}
期望输出类型：{output_type}

用户任务：
{requirement}

请按当前能力接口位生成多媒体制作方案和模型提示词。"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def call_llm(config: dict[str, str], messages: list[dict[str, str]], use_llm: bool, timeout: int = 60) -> dict[str, Any]:
    if not use_llm:
        return mock_response(messages, "用户关闭真实 LLM 调用。")
    if not (config.get("LITELLM_BASE") and config.get("KIMI_MODEL") and config.get("LITELLM_KEY")):
        return mock_response(messages, "LLM 配置不完整，已降级 mock。")
    protocol = (config.get("LLM_PROTOCOL") or "openai_compatible").strip().lower()
    if protocol == "anthropic":
        return call_anthropic_compatible(config, messages, timeout)
    if protocol != "openai_compatible":
        raise RuntimeError(f"暂不支持的 LLM_PROTOCOL：{protocol}")
    return call_openai_compatible(config, messages, timeout)


def call_openai_compatible(config: dict[str, str], messages: list[dict[str, str]], timeout: int) -> dict[str, Any]:
    endpoint = normalize_chat_endpoint(config["LITELLM_BASE"])
    payload = {
        "model": config["KIMI_MODEL"],
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 3200,
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config['LITELLM_KEY']}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8-sig"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM 接口不可用：{exc.reason}") from exc
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    return {
        "mode": "real_llm",
        "protocol": "openai_compatible",
        "endpoint": endpoint,
        "model": config["KIMI_MODEL"],
        "raw_response": data,
        "content": content,
        "parsed_json": try_parse_json(content),
    }


def call_anthropic_compatible(config: dict[str, str], messages: list[dict[str, str]], timeout: int) -> dict[str, Any]:
    endpoint = normalize_anthropic_endpoint(config["LITELLM_BASE"])
    system_parts = [item.get("content", "") for item in messages if item.get("role") == "system"]
    anthropic_messages = [
        {"role": item.get("role", "user"), "content": item.get("content", "")}
        for item in messages
        if item.get("role") != "system"
    ]
    if not anthropic_messages:
        anthropic_messages = [{"role": "user", "content": "请返回 JSON 格式的结果。"}]
    payload = {
        "model": config["KIMI_MODEL"],
        "system": "\n\n".join(system_parts),
        "messages": anthropic_messages,
        "temperature": 0.2,
        "max_tokens": 3200,
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": config["LITELLM_KEY"],
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8-sig"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM 接口不可用：{exc.reason}") from exc
    content = extract_anthropic_text(data)
    return {
        "mode": "real_llm",
        "protocol": "anthropic",
        "endpoint": endpoint,
        "model": config["KIMI_MODEL"],
        "raw_response": data,
        "content": content,
        "parsed_json": try_parse_json(content),
    }


def extract_anthropic_text(data: dict[str, Any]) -> str:
    blocks = data.get("content") or []
    texts: list[str] = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            texts.append(block.get("text", ""))
    return "\n".join(item for item in texts if item)


def test_llm_connection(config: dict[str, str]) -> dict[str, Any]:
    messages = [
        {"role": "system", "content": "你是接口连通性测试助手，只返回 JSON。"},
        {"role": "user", "content": "请只回复：{\"ok\":true,\"message\":\"connected\"}"},
    ]
    result = call_llm(config, messages, True, timeout=15)
    return {
        "ok": True,
        "endpoint": result.get("endpoint"),
        "model": result.get("model"),
        "protocol": result.get("protocol"),
        "mode": result.get("mode"),
        "content": result.get("content"),
        "parsed_json": result.get("parsed_json"),
    }


def try_parse_json(content: str) -> Any:
    text = _clean_json_text(content)
    for candidate in [text, _repair_json_text(text)]:
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return _extract_partial_json_fields(text)


def _clean_json_text(content: str) -> str:
    text = (content or "").strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)(?:```|$)", text, flags=re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    if "{" in text:
        text = text[text.find("{") :]
    if "}" in text:
        text = text[: text.rfind("}") + 1]
    return text.strip()


def _repair_json_text(text: str) -> str:
    repaired = text.strip().rstrip(",")
    stack: list[str] = []
    in_string = False
    escaped = False
    for char in repaired:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char in "{[":
            stack.append("}" if char == "{" else "]")
        elif char in "}]" and stack and stack[-1] == char:
            stack.pop()
    return repaired + "".join(reversed(stack))


def _extract_partial_json_fields(text: str) -> dict[str, Any] | None:
    fields = {}
    for key in ["title", "capability_id", "output_type", "production_brief", "visual_brief", "positive_prompt", "negative_prompt"]:
        value = _extract_json_string_field(text, key)
        if value:
            fields[key] = value
    compliance = _extract_json_array_strings(text, "compliance_notes")
    if compliance:
        fields["compliance_notes"] = compliance
    material_usage = _extract_json_array_objects(text, "material_usage")
    if material_usage:
        fields["material_usage"] = material_usage
    return fields or None


def _extract_json_string_field(text: str, key: str) -> str | None:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"', text, flags=re.S)
    if not match:
        return None
    try:
        return json.loads(f'"{match.group(1)}"')
    except Exception:
        return match.group(1)


def _extract_json_array_strings(text: str, key: str) -> list[str]:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*\[([\s\S]*?)(?:\]|\Z)', text)
    if not match:
        return []
    return [item for item in re.findall(r'"((?:\\.|[^"\\])*)"', match.group(1)) if item]


def _extract_json_array_objects(text: str, key: str) -> list[dict[str, str]]:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*\[([\s\S]*?)(?:\]\s*,\s*"|\]\s*\}}|\Z)', text)
    if not match:
        return []
    objects = []
    for raw_obj in re.findall(r"\{([\s\S]*?)\}", match.group(1)):
        item: dict[str, str] = {}
        for field, value in re.findall(r'"([^"]+)"\s*:\s*"((?:\\.|[^"\\])*)"', raw_obj):
            item[field] = value
        if item:
            objects.append(item)
    return objects


def mock_response(messages: list[dict[str, str]], reason: str) -> dict[str, Any]:
    parsed = {
        "title": "智能监测设备宣传海报制作方案",
        "capability_id": "text_to_image",
        "output_type": "poster_plan",
        "production_brief": "围绕智能监测设备，使用产品资料、品牌规范、产品图和爆款海报案例，生成专业克制的多媒体制作方案。",
        "visual_brief": "围绕智能监测设备，使用产品资料、品牌规范、产品图和爆款海报案例，生成专业克制的宣传海报方案。",
        "positive_prompt": "农业种植基地场景，智能监测设备作为主体，画面专业清晰，突出远程监测、异常提醒、巡检辅助，版式包含标题、三条卖点和行动提示，品牌表达克制可信。",
        "negative_prompt": "避免绝对化承诺，避免夸张收益，避免虚构参数，避免杂乱文字，避免过度科技感。",
        "material_usage": [{"context_id": "1", "usage": "产品卖点依据"}, {"context_id": "2", "usage": "品牌表达约束"}],
        "compliance_notes": ["对外发布前需品牌负责人确认。", "不要使用第一、唯一、保证、绝对等表达。"],
        "human_review_required": True,
        "citations": [],
    }
    return {
        "mode": "mock",
        "reason": reason,
        "content": json.dumps(parsed, ensure_ascii=False, indent=2),
        "parsed_json": parsed,
        "messages_preview": [{"role": m["role"], "content_length": len(m["content"])} for m in messages],
    }
