from __future__ import annotations

from pathlib import Path

from .db import get_card_by_id, init_db, search_cards, upsert_card
from .models import CatalogCard


PROJECT_DOMAIN = {"enterprise": {"项目": ["Memlink Shrine"]}}
CHAIN_AUTHOR = "codex"
CHAIN_AUTHOR_ROLE = "witness_model"
CHAIN_STATUS = "witness_confirmed"


def _default_governance() -> dict:
    return {
        "shelf_state": "half_open",
        "importance": "normal",
        "pinned": False,
        "confidence": 0.86,
        "promotion_rule_text": "",
        "degradation_rule_text": "",
        "rationale": "",
    }


def _base_facets(memory_type: str, memory_subtype: str = "") -> dict:
    return {
        "entity": ["Memlink Shrine"],
        "topic": ["残影系统", "记忆链"],
        "time": ["2026 4月"],
        "status": ["测试阶段"],
        "memory_type": memory_type,
        "memory_subtype": memory_subtype,
        "relevance_scope_core": ["系统定义", "方法规范", "当前项目"],
        "relevance_scope_extra": ["记忆检索", "链路召回"],
    }


def _support_base(memory_type: str = "method") -> dict:
    data = _base_facets(memory_type)
    data["topic"] = ["Memlink Shrine", "文档支持"]
    return data


def _with_chain(card: CatalogCard, **updates) -> CatalogCard:
    data = card.as_dict()
    data.update(updates)
    return CatalogCard(**data)


def _new_card(
    raw_memory_id: str,
    title: str,
    fact_summary: str,
    meaning_summary: str,
    posture_summary: str,
    emotion_trajectory: str,
    body_text: str,
    memory_type: str,
    main_id: str,
    upstream_main_ids: list[str],
    relation_type: str,
    topology_role: str,
    path_status: str = "active",
    is_landmark: bool = False,
    focus_anchor_main_id: str = "",
    focus_confidence: float = 0.0,
    focus_reason: str = "",
    created_at: str = "2026-04-14T13:30:00+08:00",
) -> CatalogCard:
    return CatalogCard(
        raw_memory_id=raw_memory_id,
        title=title,
        fact_summary=fact_summary,
        meaning_summary=meaning_summary,
        posture_summary=posture_summary,
        emotion_trajectory=emotion_trajectory,
        body_text=body_text,
        raw_text=body_text,
        base_facets=_base_facets(memory_type),
        domain_facets=PROJECT_DOMAIN,
        governance=_default_governance(),
        semantic_facets={"project": ["Memlink Shrine"]},
        main_id=main_id,
        upstream_main_ids=upstream_main_ids,
        downstream_main_ids=[],
        relation_type=relation_type,
        topology_role=topology_role,
        path_status=path_status,
        focus_anchor_main_id=focus_anchor_main_id or (upstream_main_ids[0] if upstream_main_ids else main_id),
        focus_confidence=focus_confidence,
        focus_reason=focus_reason,
        is_landmark=is_landmark,
        chain_author=CHAIN_AUTHOR,
        chain_author_role=CHAIN_AUTHOR_ROLE,
        chain_status=CHAIN_STATUS,
        chain_confidence=max(focus_confidence, 0.88),
        source_type="memlink_shrine_demo",
        confidence_source="witness_model",
        facet_pack_id="enterprise",
        facet_pack_version="v1",
        projection_status="active",
        projection_created_at=created_at,
        raw_memory_created_at=created_at,
        created_at=created_at,
        updated_at=created_at,
    )


def apply_demo_witness_chain(db_path: Path) -> dict[str, int]:
    init_db(db_path)
    cards = search_cards(db_path, query="", limit=500)
    by_title = {card.title: card for card in cards}

    existing_defs = [
        {
            "title": "Memlink Shrine 种子记忆 01：项目起点与动机",
            "main_id": "ML-RET-R00-RT-20260413-2774",
            "upstream": [],
            "relation_type": "unassigned",
            "topology_role": "origin",
            "path_status": "active",
            "focus_anchor_main_id": "ML-RET-R00-RT-20260413-2774",
            "focus_confidence": 1.0,
            "focus_reason": "项目起点，没有更早上游。",
            "is_landmark": False,
            "posture_summary": "项目从普通 memory store 不够自然这一不满出发，正式迈出第一步。",
            "emotion_trajectory": "起点阶段判断清晰，整体情绪偏确定。",
        },
        {
            "title": "Memlink Shrine 种子记忆 02：命名与核心比喻",
            "main_id": "ML-RET-M01-MN-20260413-5128",
            "upstream": ["ML-RET-R00-RT-20260413-2774"],
            "relation_type": "derived_from",
            "topology_role": "node",
            "path_status": "active",
            "focus_anchor_main_id": "ML-RET-R00-RT-20260413-2774",
            "focus_confidence": 0.95,
            "focus_reason": "由项目起点延伸出图书馆前台/编目系统这一核心比喻。",
            "is_landmark": False,
            "posture_summary": "从问题意识推进到整体比喻，系统轮廓开始成形。",
            "emotion_trajectory": "从模糊不满转为兴奋和命名感。",
        },
        {
            "title": "Memlink Shrine 种子记忆 05：Memory Card v1.2 规范",
            "main_id": "ML-RET-M02-LM-20260413-6536",
            "upstream": ["ML-RET-M01-MN-20260413-5128"],
            "relation_type": "refines",
            "topology_role": "node",
            "path_status": "active",
            "focus_anchor_main_id": "ML-RET-M01-MN-20260413-5128",
            "focus_confidence": 0.93,
            "focus_reason": "从比喻进一步落成记忆卡字段与目录规范。",
            "is_landmark": True,
            "posture_summary": "开始从概念收束到可执行字段，进入工程化阶段。",
            "emotion_trajectory": "从兴奋进入更克制的规则化状态。",
        },
        {
            "title": "Memlink Shrine 种子记忆 06：维度体系 v2.0",
            "main_id": "ML-RET-M03-LM-20260413-1681",
            "upstream": ["ML-RET-M02-LM-20260413-6536"],
            "relation_type": "refines",
            "topology_role": "node",
            "path_status": "active",
            "focus_anchor_main_id": "ML-RET-M02-LM-20260413-6536",
            "focus_confidence": 0.92,
            "focus_reason": "继续从字段规则推进到企业维度体系与 RAG 对齐。",
            "is_landmark": True,
            "posture_summary": "系统开始和企业语义本体正面对接，结构层次上升。",
            "emotion_trajectory": "判断更复杂，但方向更稳。",
        },
        {
            "title": "Memlink Shrine 种子记忆 07：模块化维度与 v3 预留",
            "main_id": "ML-RET-M04-MN-20260413-5394",
            "upstream": ["ML-RET-M03-LM-20260413-1681"],
            "relation_type": "refines",
            "topology_role": "node",
            "path_status": "active",
            "focus_anchor_main_id": "ML-RET-M03-LM-20260413-1681",
            "focus_confidence": 0.9,
            "focus_reason": "从 v2 维度体系进一步延伸到模块化和重投影预留。",
            "is_landmark": False,
            "posture_summary": "在保持当前可跑的前提下，开始给未来版本留后手。",
            "emotion_trajectory": "进入工程克制阶段，强调边界感。",
        },
        {
            "title": "Memlink Shrine 种子记忆 08：v1+v2 实现边界",
            "main_id": "ML-RET-M05-MN-20260413-4785",
            "upstream": ["ML-RET-M04-MN-20260413-5394"],
            "relation_type": "refines",
            "topology_role": "node",
            "path_status": "active",
            "focus_anchor_main_id": "ML-RET-M04-MN-20260413-5394",
            "focus_confidence": 0.92,
            "focus_reason": "把系统从概念扩张拉回 v1+v2 先落地的实现边界。",
            "is_landmark": False,
            "posture_summary": "主动收缩战线，避免过度设计。",
            "emotion_trajectory": "从扩张冲动回到冷静收束。",
        },
        {
            "title": "Memlink Shrine 种子记忆 10：已落地系统状态",
            "main_id": "ML-RET-M06-LM-20260413-2806",
            "upstream": ["ML-RET-M05-MN-20260413-4785"],
            "relation_type": "derived_from",
            "topology_role": "node",
            "path_status": "active",
            "focus_anchor_main_id": "ML-RET-M05-MN-20260413-4785",
            "focus_confidence": 0.91,
            "focus_reason": "把边界落实为已落地的代码与界面状态。",
            "is_landmark": True,
            "posture_summary": "开始把纸面结构搬进真实代码底座。",
            "emotion_trajectory": "从设计进入验证，状态更务实。",
        },
        {
            "title": "Memlink Shrine 种子记忆 04：写入与修正原则",
            "main_id": "ML-RET-M07-BR-20260413-0064",
            "upstream": ["ML-RET-M06-LM-20260413-2806"],
            "relation_type": "branches_to",
            "topology_role": "junction",
            "path_status": "active",
            "focus_anchor_main_id": "ML-RET-M06-LM-20260413-2806",
            "focus_confidence": 0.87,
            "focus_reason": "这里成为旧写入规则与新残影写入哲学的分叉口。",
            "is_landmark": False,
            "posture_summary": "原有半自动原则提供了历史起点，但开始暴露局限。",
            "emotion_trajectory": "从顺手可用过渡到不满足现状。",
        },
        {
            "title": "Memlink Shrine 种子记忆 03：读取链路最终结论",
            "main_id": "ML-RET-A01-DD-20260413-7235",
            "upstream": ["ML-RET-M07-BR-20260413-0064"],
            "relation_type": "blocks",
            "topology_role": "node",
            "path_status": "dead_end",
            "focus_anchor_main_id": "ML-RET-M07-BR-20260413-0064",
            "focus_confidence": 0.76,
            "focus_reason": "这条旧读取链在后续讨论中被证明不够准确，作为历史死路保留。",
            "is_landmark": False,
            "posture_summary": "曾经被当作结论推进，后来被证伪为不够贴合残影哲学。",
            "emotion_trajectory": "先确信后回撤，带有明显修正感。",
        },
        {
            "title": "Memlink Shrine 种子记忆 09：CC 的作用",
            "main_id": "ML-RET-S01-LM-20260413-2292",
            "upstream": ["ML-RET-M07-BR-20260413-0064"],
            "relation_type": "refines",
            "topology_role": "node",
            "path_status": "active",
            "focus_anchor_main_id": "ML-RET-M07-BR-20260413-0064",
            "focus_confidence": 0.88,
            "focus_reason": "Claude Code 作为外部评审与结构校准者参与这条分叉口。",
            "is_landmark": True,
            "posture_summary": "外部模型提供结构校准，而不是代替知情者写链。",
            "emotion_trajectory": "从单人思考转为多模型碰撞，张力上升。",
        },
        {
            "title": "文章种子记忆：企业 AI 落地认知基础",
            "main_id": "ML-RET-S02-LM-20260413-3324",
            "upstream": ["ML-RET-M03-LM-20260413-1681"],
            "relation_type": "refines",
            "topology_role": "node",
            "path_status": "active",
            "focus_anchor_main_id": "ML-RET-M03-LM-20260413-1681",
            "focus_confidence": 0.89,
            "focus_reason": "企业 AI 文章观点为维度体系和 RAG 对齐提供底层出发点。",
            "is_landmark": True,
            "posture_summary": "从企业实践回看系统设计，提供现实约束。",
            "emotion_trajectory": "更加务实，也更有长期方向感。",
        },
        {
            "title": "文件内容种子记忆 01：1Memlink Shrine系统设计思路与Memory Card规范_v1.2.md",
            "main_id": "ML-RET-S03-LM-20260413-6550",
            "upstream": ["ML-RET-M02-LM-20260413-6536"],
            "relation_type": "refines",
            "topology_role": "node",
            "path_status": "active",
            "focus_anchor_main_id": "ML-RET-M02-LM-20260413-6536",
            "focus_confidence": 0.84,
            "focus_reason": "对应 v1.2 文档原文支撑。",
            "is_landmark": True,
            "posture_summary": "作为文档支撑节点，不直接改变主线。",
            "emotion_trajectory": "偏稳定归档。",
        },
        {
            "title": "文件内容种子记忆 02：2Memlink Shrine系统设计思路与维度体系规范_v2.0.md",
            "main_id": "ML-RET-S04-LM-20260413-0695",
            "upstream": ["ML-RET-M03-LM-20260413-1681"],
            "relation_type": "refines",
            "topology_role": "node",
            "path_status": "active",
            "focus_anchor_main_id": "ML-RET-M03-LM-20260413-1681",
            "focus_confidence": 0.84,
            "focus_reason": "对应 v2.0 文档原文支撑。",
            "is_landmark": True,
            "posture_summary": "作为文档支撑节点，不直接改变主线。",
            "emotion_trajectory": "偏稳定归档。",
        },
        {
            "title": "文件内容种子记忆 03：3Memlink Shrine系统设计思路与模块化维度及重投影机制_v3.0.md",
            "main_id": "ML-RET-S05-LM-20260413-0858",
            "upstream": ["ML-RET-M04-MN-20260413-5394"],
            "relation_type": "refines",
            "topology_role": "node",
            "path_status": "active",
            "focus_anchor_main_id": "ML-RET-M04-MN-20260413-5394",
            "focus_confidence": 0.84,
            "focus_reason": "对应 v3.0 文档原文支撑。",
            "is_landmark": True,
            "posture_summary": "作为文档支撑节点，不直接改变主线。",
            "emotion_trajectory": "偏稳定归档。",
        },
        {
            "title": "文件内容种子记忆 04：4Memlink Shrine_v1+v2实现边界与v3预留接口清单.md",
            "main_id": "ML-RET-S06-LM-20260413-7757",
            "upstream": ["ML-RET-M05-MN-20260413-4785"],
            "relation_type": "refines",
            "topology_role": "node",
            "path_status": "active",
            "focus_anchor_main_id": "ML-RET-M05-MN-20260413-4785",
            "focus_confidence": 0.84,
            "focus_reason": "对应实现边界文档原文支撑。",
            "is_landmark": True,
            "posture_summary": "作为文档支撑节点，不直接改变主线。",
            "emotion_trajectory": "偏稳定归档。",
        },
    ]

    new_cards = [
        _new_card(
            raw_memory_id="demo-shadow-philosophy",
            title="Memlink Shrine 残影记忆 11：残影不是遗产",
            fact_summary="用户明确提出：Memlink Shrine 不应把意义在写入时打包成遗产。残影只是一个人曾经在这里走过、思考过、挣扎过的事实；意义在后来者看到它并把它放进当前问题时才发生。",
            meaning_summary="这张卡把系统从“经验库”改写成“残影系统”。写入时保存痕迹本身，召回时才生成当下意义，避免成功学式幸存者偏差。",
            posture_summary="这是一次明显的哲学纠偏：从结果导向的经验总结，转回到客观痕迹和后来者解释权。",
            emotion_trajectory="从原始冲动上升到清晰自觉，系统核心哲学在这里被真正想明白。",
            body_text="残影不是遗产。遗产会把用途和意义提前打包；残影只留下当时的事实、姿态和路径位置。后来者如何理解，是召回时的事，不是写入时的事。",
            memory_type="reflection",
            main_id="ML-RET-B01-MN-20260414-1001",
            upstream_main_ids=["ML-RET-M07-BR-20260413-0064"],
            relation_type="refines",
            topology_role="node",
            focus_anchor_main_id="ML-RET-M07-BR-20260413-0064",
            focus_confidence=0.96,
            focus_reason="新哲学直接从旧写入原则分叉口继续深化而来。",
        ),
        _new_card(
            raw_memory_id="demo-auto-writing-protocol",
            title="Memlink Shrine 残影记忆 12：自动残影写入协议",
            fact_summary="默认写入改为由知情者模型自动总结并写入，用户仍可主动插队触发。触发建议优先级为：转向事件 > 用户手动触发 > 时间/轮次/token 兜底。",
            meaning_summary="它修复了“长时间讨论但没说记住就全部丢失”的致命缺口，让失败经验和阶段过程也能留下残影。",
            posture_summary="这里从单点记录转向持续沉淀，系统开始真正承担‘不丢过程’的职责。",
            emotion_trajectory="从对漏记忆的不安，转向更主动的系统补位设计。",
            body_text="默认自动写入，但写入的是阶段残影，不是每句话。用户说“记住”时可以插队强制写入。每次写入不仅落内容，也会编辑链路。",
            memory_type="method",
            main_id="ML-RET-B02-MN-20260414-1002",
            upstream_main_ids=["ML-RET-B01-MN-20260414-1001"],
            relation_type="derived_from",
            topology_role="node",
            focus_anchor_main_id="ML-RET-B01-MN-20260414-1001",
            focus_confidence=0.95,
            focus_reason="残影哲学落地后的第一条工程协议就是自动写入。",
        ),
        _new_card(
            raw_memory_id="demo-parallel-branch-problem",
            title="Memlink Shrine 残影记忆 13：并行分支与挂接问题",
            fact_summary="用户进一步提出：如果 10 和 11 都是 9 分出来的并行支线，新的残影到底该接到哪条线后面，不能靠编号瞎猜。",
            meaning_summary="这张卡把‘并行分支如何挂接’正式抬成一个独立问题，逼出了后面的思考光标机制与断档重连机制。",
            posture_summary="系统从单链思维进入并行分支思维，开始面对真正复杂的路径管理问题。",
            emotion_trajectory="复杂度上升，但问题意识也更清楚。",
            body_text="并行分支里，新记忆不能简单自动接线。必须先判断当前思考到底停在 10、11、两者汇合，还是其实根本不该挂链。",
            memory_type="method",
            main_id="ML-RET-B03-BR-20260414-1003",
            upstream_main_ids=["ML-RET-B02-MN-20260414-1002"],
            relation_type="branches_to",
            topology_role="junction",
            focus_anchor_main_id="ML-RET-B02-MN-20260414-1002",
            focus_confidence=0.91,
            focus_reason="自动写入协议进一步碰到并行分支挂接问题，这里形成新的方法分叉口。",
        ),
        _new_card(
            raw_memory_id="demo-thought-cursor",
            title="Memlink Shrine 残影记忆 14：思考光标机制",
            fact_summary="思考光标机制用于解决并行分支中‘新残影接 10 还是 11’的问题。系统先判断当前思考光标停在哪个节点或哪条路径上，再决定挂接、汇合还是暂不挂链。",
            meaning_summary="它把‘挂接判断’从模糊猜测变成可被解释的结构动作，是并行分支可控的前提。",
            posture_summary="从纯结构图继续推进到会话态里的‘当前站位’识别。",
            emotion_trajectory="从困惑转为精确约束，系统开始有了真正的‘当前光标’概念。",
            body_text="思考光标机制不靠编号猜测，而是依赖当前焦点节点、当前路径和光标置信度。低置信度时宁可不挂，也不要接错。",
            memory_type="method",
            main_id="ML-RET-C01-MN-20260414-1004",
            upstream_main_ids=["ML-RET-B03-BR-20260414-1003"],
            relation_type="derived_from",
            topology_role="node",
            focus_anchor_main_id="ML-RET-B03-BR-20260414-1003",
            focus_confidence=0.94,
            focus_reason="这是并行分支问题的一条明确解决路线：先识别光标，再挂链。",
        ),
        _new_card(
            raw_memory_id="demo-reconnect",
            title="Memlink Shrine 残影记忆 15：断档重连机制",
            fact_summary="用户将‘断档续写’正式更名为‘断档重连’。未完成节点不是废链，而是开放节点；未来的你或别人都可以从这里重新接上新分支。",
            meaning_summary="它让没有出口的链保留为‘未竟之路’，避免系统只接受当场跑通的结果。",
            posture_summary="系统开始承认暂停、未尽和未来重连的合法性，不再要求每条链当场完结。",
            emotion_trajectory="从对未完成的焦虑，转向允许未来继续参与的宽阔感。",
            body_text="断档重连不改写旧节点，而是在旧节点之后重新长出新下游。未完成的节点可以是开放头，也可以是暂停点，等待未来重连。",
            memory_type="method",
            main_id="ML-RET-C02-MN-20260414-1005",
            upstream_main_ids=["ML-RET-B03-BR-20260414-1003"],
            relation_type="derived_from",
            topology_role="node",
            focus_anchor_main_id="ML-RET-B03-BR-20260414-1003",
            focus_confidence=0.94,
            focus_reason="这是并行分支问题的另一条解决路线：给未完成链保留重连能力。",
        ),
        _new_card(
            raw_memory_id="demo-fog-map",
            title="Memlink Shrine 残影记忆 16：局部迷雾图与全图图谱",
            fact_summary="图谱展示规则被定成两档：默认显示当前节点上下游 2 步的局部迷雾图；点击全图时再显示项目累计完整图。完整图不应临时找模型现算，而应读取已保存图谱。",
            meaning_summary="这张卡把残影系统和地图迷雾机制真正连到一起，也为 UI 的性能边界定了规则。",
            posture_summary="从抽象图谱理念进入可交付的交互设计，开始考虑默认轻量与按需展开。",
            emotion_trajectory="设计感与工程约束在这里开始平衡。",
            body_text="默认图只看当前附近，像迷雾中的视野。完整地图是去迷雾后的项目累计图，但应按需打开并允许加载过程，不能每次都让模型现场重算。",
            memory_type="method",
            main_id="ML-RET-D01-IN-20260414-1006",
            upstream_main_ids=["ML-RET-C01-MN-20260414-1004", "ML-RET-C02-MN-20260414-1005"],
            relation_type="merges_to",
            topology_role="merge",
            focus_anchor_main_id="ML-RET-C01-MN-20260414-1004",
            focus_confidence=0.89,
            focus_reason="思考光标和断档重连两条机制最终汇合到图谱展示规则上。",
            is_landmark=True,
        ),
        _new_card(
            raw_memory_id="demo-shared-branches",
            title="Memlink Shrine 残影记忆 17：共享残影与多人分支",
            fact_summary="用户继续提出：如果系统共享，别人能不能从我未完成的节点继续留下残影，我和其他人能不能看见。这件事应像 Git 的分支思想，但不必把 Git 全套复杂机制照搬过来。",
            meaning_summary="这张卡把系统从个人记忆推向共享残影网络，但当前仍未完全定稿，应保留为开放头等待后续继续生长。",
            posture_summary="这是一次面向多人协作和长期演化的主动扩展，但仍处在探索和待补全状态。",
            emotion_trajectory="视野打开了，但系统复杂度也显著抬升，因此暂不强行定死。",
            body_text="共享残影要求系统允许别人从旧节点重连，也要求保留作者信息、并行分支和可见性规则。当前只冻结到‘可以像分支思想那样工作’，细节留待后续继续补齐。",
            memory_type="project",
            main_id="ML-RET-D02-MN-20260414-1007",
            upstream_main_ids=["ML-RET-D01-IN-20260414-1006"],
            relation_type="derived_from",
            topology_role="node",
            path_status="paused",
            focus_anchor_main_id="ML-RET-D01-IN-20260414-1006",
            focus_confidence=0.73,
            focus_reason="这是当前最新开放节点，后续会继续往共享残影和权限机制扩展。",
        ),
        _new_card(
            raw_memory_id="demo-reconnect-visibility",
            title="Memlink Shrine 残影记忆 18：共享可见性与作者规则（断档重连）",
            fact_summary="在共享残影问题暂时断档之后，系统重新从该暂停节点接回，继续讨论作者标记、可见性和他人续写残影时的呈现方式。",
            meaning_summary="这张卡不是覆盖旧节点，而是从暂停节点重新长出新下游，用来演示断档重连如何真实发生。它同时说明共享残影必须保留作者信息与可见性边界。",
            posture_summary="这是一次典型的重连动作：旧节点没有被抹掉，而是在未来重新接上新线索。",
            emotion_trajectory="从开放悬置转入重新接线，状态由停顿变为谨慎推进。",
            body_text="断档重连意味着旧节点可以保持暂停状态，而新的思路从那里继续长出来。共享残影里，后来人的续写要能看见作者、可见范围和来源路径。",
            memory_type="project",
            main_id="ML-RET-D03-LM-20260414-1008",
            upstream_main_ids=["ML-RET-D02-MN-20260414-1007"],
            relation_type="resumes_from",
            topology_role="node",
            path_status="open_head",
            focus_anchor_main_id="ML-RET-D02-MN-20260414-1007",
            focus_confidence=0.82,
            focus_reason="这是从暂停节点重新长出来的第一条新线，用来演示断档重连。",
            is_landmark=True,
        ),
    ]

    managed_cards: list[CatalogCard] = []
    for spec in existing_defs:
        card = by_title.get(spec["title"])
        if not card:
            continue
        managed_cards.append(
            _with_chain(
                card,
                main_id=spec["main_id"],
                upstream_main_ids=spec["upstream"],
                downstream_main_ids=[],
                relation_type=spec["relation_type"],
                topology_role=spec["topology_role"],
                path_status=spec["path_status"],
                focus_anchor_main_id=spec["focus_anchor_main_id"],
                focus_confidence=spec["focus_confidence"],
                focus_reason=spec["focus_reason"],
                is_landmark=spec["is_landmark"],
                posture_summary=spec["posture_summary"],
                emotion_trajectory=spec["emotion_trajectory"],
                chain_author=CHAIN_AUTHOR,
                chain_author_role=CHAIN_AUTHOR_ROLE,
                chain_status=CHAIN_STATUS,
                chain_confidence=0.9,
                confidence_source="witness_model",
            )
        )

    existing_raw_ids = {card.raw_memory_id for card in search_cards(db_path, query="", limit=500)}
    for card in new_cards:
        if card.raw_memory_id in existing_raw_ids:
            old = get_card_by_id(db_path, card.raw_memory_id)
            if old:
                managed_cards.append(_with_chain(old, **card.as_dict()))
        else:
            managed_cards.append(card)

    by_main = {card.main_id: card for card in managed_cards}
    downstream_map: dict[str, list[str]] = {card.main_id: [] for card in managed_cards}
    for card in managed_cards:
        for upstream_id in card.upstream_main_ids:
            if upstream_id in downstream_map and card.main_id not in downstream_map[upstream_id]:
                downstream_map[upstream_id].append(card.main_id)

    for card in managed_cards:
        card.downstream_main_ids = downstream_map.get(card.main_id, [])
        upsert_card(db_path, card)

    return {"managed_cards": len(managed_cards)}



