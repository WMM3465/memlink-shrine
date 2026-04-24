from __future__ import annotations

from dataclasses import dataclass


WRITING_SPEC_VERSION = "shadow_writing_spec_v1"


@dataclass(frozen=True)
class SummaryFieldSpec:
    field: str
    chinese_name: str
    question: str
    perspective: str
    length: str
    must_not: str


SUMMARY_FIELD_SPECS: tuple[SummaryFieldSpec, ...] = (
    SummaryFieldSpec(
        field="fact_summary",
        chinese_name="事实摘要",
        question="发生了什么、做了什么决定、出现了什么结果。",
        perspective="第三者客观叙述。",
        length="1 到 3 句。",
        must_not="不要写评价、教训、未来用途。",
    ),
    SummaryFieldSpec(
        field="meaning_summary",
        chinese_name="意义摘要",
        question="这张卡让系统理解方式、结构、协议或路线发生了什么改变。",
        perspective="系统结构视角。",
        length="1 到 2 句。",
        must_not="不要写成这条记忆的终极含义，也不要替未来场景预设用途。",
    ),
    SummaryFieldSpec(
        field="posture_summary",
        chinese_name="姿态摘要",
        question="这段路是怎么被走出来的，是坚定推进、试探摸索、反复拉扯，还是被迫转向。",
        perspective="知情者模型的第三者观察视角。",
        length="1 句。",
        must_not="不要写成文学化自白，也不要直接裁判对错。",
    ),
    SummaryFieldSpec(
        field="emotion_trajectory",
        chinese_name="情绪轨迹",
        question="这一阶段的信心、张力、犹豫、不甘、释然等如何变化。",
        perspective="可观察的情绪和决策张力轨迹。",
        length="1 句。",
        must_not="不要夸张渲染，不要写成戏剧台词。",
    ),
)


CORE_WRITING_RULES: tuple[str, ...] = (
    "残影不是遗产：写入时保存痕迹，召回时才生成当下意义。",
    "事实摘要回答发生了什么；意义摘要回答系统结构被改变了哪一块。",
    "意义摘要是结构级差异，不是语义级终局结论。",
    "死路、推翻、放弃、犹豫和高成本试错必须允许被保存，用来避免成功学式幸存者偏差。",
    "姿态摘要和情绪轨迹由知情者模型以第三者观察角度书写，不是作者自白，也不是未来用途说明。",
    "非知情者模型只能辅助摘要、校验和建议，不能默认决定主 ID、上下游、关系类型和路径状态。",
)


FORBIDDEN_WRITING_RULES: tuple[str, ...] = (
    "禁止把记忆写成成功学教训。",
    "禁止删除或弱化死路、被推翻的旧方案和失败经验。",
    "禁止在写入时替未来用户规定唯一用途。",
    "禁止把意义摘要写成这条记忆最终应该怎么被理解。",
    "禁止把姿态摘要写成主观抒情，把情绪轨迹写成文学渲染。",
)


def summary_field_specs_as_dict() -> list[dict[str, str]]:
    return [
        {
            "field": item.field,
            "chinese_name": item.chinese_name,
            "question": item.question,
            "perspective": item.perspective,
            "length": item.length,
            "must_not": item.must_not,
        }
        for item in SUMMARY_FIELD_SPECS
    ]


def writing_spec_as_dict() -> dict[str, object]:
    return {
        "version": WRITING_SPEC_VERSION,
        "core_rules": list(CORE_WRITING_RULES),
        "forbidden_rules": list(FORBIDDEN_WRITING_RULES),
        "summary_fields": summary_field_specs_as_dict(),
    }


def format_writing_spec_for_prompt() -> str:
    lines = [
        f"Memlink Shrine 残影写入规范版本：{WRITING_SPEC_VERSION}",
        "核心规则：",
    ]
    lines.extend(f"- {rule}" for rule in CORE_WRITING_RULES)
    lines.append("四摘要字段：")
    for item in SUMMARY_FIELD_SPECS:
        lines.extend(
            [
                f"- {item.field}（{item.chinese_name}）：",
                f"  回答：{item.question}",
                f"  视角：{item.perspective}",
                f"  长度：{item.length}",
                f"  禁止：{item.must_not}",
            ]
        )
    lines.append("禁止项：")
    lines.extend(f"- {rule}" for rule in FORBIDDEN_WRITING_RULES)
    return "\n".join(lines)

