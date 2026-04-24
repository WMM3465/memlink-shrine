from __future__ import annotations

import json
import re
from textwrap import dedent
from typing import Any

from google import genai

from .id_schema import build_default_main_id
from .models import CatalogCard, MemoryBrief, QuerySelection, RawMemory
from .writing_spec import format_writing_spec_for_prompt


class GeminiLibrarian:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self._fallback_only = False

    def _generate_json(self, prompt: str) -> dict[str, Any]:
        if self._fallback_only:
            raise RuntimeError("Gemini API previously failed in this process; using fallback librarian.")
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        text = (response.text or "{}").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        return json.loads(text or "{}")

    def _activate_fallback(self) -> None:
        self._fallback_only = True

    @staticmethod
    def _compact_text(text: str, limit: int = 240) -> str:
        compacted = re.sub(r"\s+", " ", text).strip()
        return compacted[:limit] + ("..." if len(compacted) > limit else "")

    @staticmethod
    def _append_unique(values: list[str], value: str) -> None:
        if value and value not in values:
            values.append(value)

    def _fallback_facets(self, text: str) -> tuple[dict[str, Any], dict[str, Any]]:
        entity: list[str] = []
        topic: list[str] = []
        time: list[str] = []
        status: list[str] = []
        core_scope: list[str] = []

        keyword_entities = {
            "Memlink Shrine": "Memlink Shrine",
            "记忆图书馆": "Memlink Shrine",
            "OpenMemory": "OpenMemory",
            "Codex": "Codex",
            "Claude Code": "Claude Code",
            "CC": "Claude Code",
            "Gemini": "Gemini",
            "MemPalace": "MemPalace",
            "RAG": "RAG",
        }
        for keyword, label in keyword_entities.items():
            if keyword in text:
                self._append_unique(entity, label)

        keyword_topics = {
            "读取链路": "读取链路",
            "memory brief": "memory brief",
            "Memory Brief": "memory brief",
            "写入": "写入规则",
            "修正": "人工修正",
            "Memory Card": "Memory Card",
            "目录卡": "目录卡",
            "标签": "标签体系",
            "维度": "维度体系",
            "重投影": "重投影",
            "v3": "v3预留",
            "UI": "中文UI",
            "Web UI": "中文UI",
            "exe": "套壳启动器",
            "知识库": "知识库/RAG",
            "RAG": "知识库/RAG",
            "文章": "理论文章",
        }
        for keyword, label in keyword_topics.items():
            if keyword in text:
                self._append_unique(topic, label)

        for version in ["v1", "v1.2", "v2", "v2.0", "v3", "v3.0", "v1+v2"]:
            if version in text:
                self._append_unique(time, version)

        if any(word in text for word in ["已落地", "已经完成", "能用", "启动器"]):
            status.append("已落地")
        if any(word in text for word in ["预留", "后续", "升级"]):
            status.append("预留升级")
        if any(word in text for word in ["测试", "MVP"]):
            status.append("测试阶段")

        if any(word in text for word in ["命名", "比喻", "定义"]):
            self._append_unique(core_scope, "系统定义")
        if any(word in text for word in ["读取链路", "写入", "Memory Card", "目录卡", "维度", "重投影"]):
            self._append_unique(core_scope, "方法规范")
        if any(word in text for word in ["已落地", "UI", "exe", "接口", "代码"]):
            self._append_unique(core_scope, "当前项目")
        if any(word in text for word in ["企业", "客户", "产品", "知识库", "RAG"]):
            self._append_unique(core_scope, "企业AI落地")
        if not core_scope:
            core_scope.append("历史决策")

        base_facets = {
            "entity": entity or ["Memlink Shrine"],
            "topic": topic or ["记忆图书馆"],
            "time": time,
            "status": status or ["已编目"],
            "memory_type": self._fallback_memory_type(text),
            "memory_subtype": "",
            "relevance_scope_core": core_scope,
            "relevance_scope_extra": [],
        }
        enterprise = {
            "客户": [],
            "项目": ["Memlink Shrine"] if "Memlink Shrine" in text or "记忆图书馆" in text else [],
            "产品/品类": [],
            "风格": [],
            "主题": [],
            "风格/主题": [],
            "时间/季节/节庆": [],
            "流程节点": [],
            "部门/角色": [],
            "目标/约束": [],
            "文档/资产类型": [],
        }
        if "客户" in text:
            enterprise["客户"].append("客户研究")
        if "知识库" in text or "RAG" in text:
            enterprise["项目"].append("知识库/RAG")
        if "文章" in text or "文档" in text or ".md" in text:
            enterprise["文档/资产类型"].append("设计文档")
        return base_facets, {"enterprise": enterprise}

    @staticmethod
    def _fallback_memory_type(text: str) -> str:
        if any(word in text for word in ["决定", "最终结论", "链路应为", "边界"]):
            return "decision"
        if any(word in text for word in ["规则", "规范", "Memory Card", "维度", "重投影"]):
            return "method"
        if any(word in text for word in ["项目", "已落地", "实现", "系统"]):
            return "project"
        if any(word in text for word in ["反思", "评价", "自信"]):
            return "reflection"
        return "method"

    @staticmethod
    def _fallback_title(content: str) -> str:
        first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
        bracket = re.search(r"【(.+?)】", first_line)
        if bracket:
            return bracket.group(1)
        return (first_line or "Memlink Shrine 记忆卡")[:60]

    def _fallback_governance(self, text: str, title: str, error: str) -> dict[str, Any]:
        core = any(
            word in title + text
            for word in ["项目起点", "命名", "核心比喻", "读取链路", "写入", "Memory Card", "维度体系", "v1+v2", "已落地"]
        )
        document = any(word in title + text for word in ["文档", "文件内容", ".md", "文章"])
        return {
            "shelf_state": "open" if core else "half_open",
            "importance": "high" if core else "normal",
            "pinned": bool(core and not document),
            "confidence": 0.62,
            "promotion_rule_text": "降级馆员生成：若被频繁检索、用户确认或重新编目成功，可提升为 open/high。",
            "promotion_signals": {
                "repeated_access": False,
                "recent_reinforcement": False,
                "high_current_relevance": core,
                "user_pin_override": False,
            },
            "degradation_rule_text": "若长期不再被使用，且不是核心系统定义，可降为 half_open 或 closed。",
            "degradation_signals": {
                "long_inactive": False,
                "low_current_relevance": False,
                "not_pinned": not core,
                "not_core_anymore": False,
            },
            "reactivation_rule": {
                "explicit_trigger_required": not core,
                "reactivation_signals": ["Memlink Shrine", "记忆图书馆", "OpenMemory", "目录卡"],
                "threshold": 0.7,
            },
            "rationale": f"Gemini API 暂不可用时由规则馆员临时编目；后续可用高能力模型重投影。原始错误：{self._compact_text(error, 120)}",
        }

    def _fallback_create_card(self, memory: RawMemory, error: Exception) -> CatalogCard:
        title = self._fallback_title(memory.content)
        body = re.sub(r"^【.+?】", "", memory.content.strip(), count=1).strip()
        fact_summary = self._compact_text(body or memory.content, 320)
        meaning_summary = (
            f"这条记忆用于恢复和测试 Memlink Shrine 的设计上下文：{self._compact_text(body or memory.content, 260)}"
        )
        base_facets, domain_facets = self._fallback_facets(memory.content)
        created_at = CatalogCard.to_beijing_iso(memory.created_at)
        topology_role = "node"
        path_status = "active"
        is_landmark = False
        return CatalogCard(
            raw_memory_id=memory.id,
            title=title,
            fact_summary=fact_summary,
            meaning_summary=meaning_summary,
            base_facets=base_facets,
            domain_facets=domain_facets,
            body_text=self._compact_text(body or memory.content, 900),
            raw_text=memory.content,
            semantic_facets={},
            main_id=build_default_main_id(
                memory.id,
                created_at,
                subgraph="PEND",
                position="U00",
                topology_role=topology_role,
                path_status=path_status,
                is_landmark=is_landmark,
            ),
            upstream_main_ids=[],
            downstream_main_ids=[],
            relation_type="unassigned",
            topology_role=topology_role,
            path_status=path_status,
            is_landmark=is_landmark,
            chain_author="",
            chain_author_role="none",
            chain_status="unassigned",
            chain_confidence=0.0,
            source_id=memory.id,
            source_type=memory.app_name or "openmemory",
            governance=self._fallback_governance(memory.content, title, str(error)),
            raw_memory_created_at=created_at,
            projection_created_at=CatalogCard.now_iso(),
            projection_based_on="raw_memory:fallback_librarian",
        )

    @staticmethod
    def _fallback_score(question: str, card: CatalogCard) -> int:
        haystack = " ".join(
            [
                card.title,
                card.main_id,
                card.fact_summary,
                card.meaning_summary,
                card.body_text,
                json.dumps(card.base_facets, ensure_ascii=False),
                json.dumps(card.domain_facets, ensure_ascii=False),
                json.dumps(card.semantic_facets, ensure_ascii=False),
                " ".join(card.upstream_main_ids + card.downstream_main_ids),
                card.relation_type,
                card.topology_role,
                card.path_status,
            ]
        ).lower()
        question_lower = question.lower()
        score = 0
        for token in re.findall(r"[\w\u4e00-\u9fff]+", question_lower):
            if len(token) >= 2 and token in haystack:
                score += 3
        for keyword in ["memory library", "记忆图书馆", "openmemory", "目录卡", "维度", "读取链路", "memory brief"]:
            if keyword in question_lower and keyword in haystack:
                score += 10
        if card.shelf_state == "open":
            score += 2
        if card.importance in {"pinned", "high"}:
            score += 2
        return score

    def _fallback_select_candidate_cards(
        self,
        question: str,
        cards: list[CatalogCard],
        error: Exception,
    ) -> QuerySelection:
        scored = sorted(
            ((self._fallback_score(question, card), card) for card in cards),
            key=lambda item: item[0],
            reverse=True,
        )
        broad_query = any(
            keyword in question.lower()
            for keyword in ["整个", "一步步", "全过程", "memory library", "记忆图书馆", "v1+v2"]
        )
        selected = [card for score, card in scored if score > 0]
        if broad_query:
            selected = [card for _, card in scored]
        if not selected:
            selected = [card for _, card in scored[: min(6, len(scored))]]
        else:
            selected = selected[: min(12, len(selected))]
        return QuerySelection(
            question=question,
            reasoning=f"Gemini API 暂不可用，规则馆员根据标题、摘要、标签、开合状态和重要性临时选卡。原始错误：{self._compact_text(str(error), 120)}",
            candidate_scope="规则降级选出的候选记忆集合",
            selected_raw_memory_ids=[card.raw_memory_id for card in selected],
            selected_titles=[card.title for card in selected],
        )

    def _fallback_memory_brief(
        self,
        question: str,
        cards: list[CatalogCard],
        raw_memories: list[RawMemory],
        routing_reason: str,
        error: Exception,
    ) -> MemoryBrief:
        lines = []
        for index, card in enumerate(cards, 1):
            lines.append(f"{index}. {card.title}：{card.meaning_summary}")
        brief = (
            "当前为规则馆员生成的降级简报，适合用于确认链路和基础检索；"
            "等 Gemini API 配额恢复后，可以重新生成更强的语义归纳。\n"
            + "\n".join(lines)
        )
        snippets = [self._compact_text(memory.content, 180) for memory in raw_memories[:5]]
        if not snippets:
            snippets = [self._compact_text(card.body_text or card.fact_summary, 180) for card in cards[:5]]
        return MemoryBrief(
            question=question,
            brief=brief,
            relevance_reason="候选记忆由目录卡标题、摘要、标签、open/half_open 状态和重要性综合匹配。",
            applied_raw_memory_ids=[memory.id for memory in raw_memories] or [card.raw_memory_id for card in cards],
            applied_titles=[card.title for card in cards],
            confidence=0.58,
            evidence_snippets=snippets,
            routing_reason=f"{routing_reason}；Gemini API 降级原因：{self._compact_text(str(error), 120)}",
        )

    def create_card(self, memory: RawMemory) -> CatalogCard:
        prompt = dedent(
            f"""
            你是 Memlink Shrine 的图书馆馆员。你的任务不是改写原始记忆，而是为原始记忆生成一张可调度的记忆卡。

            请严格输出 JSON，对象必须包含以下字段：
            {{
              "title": "短标题",
              "fact_summary": "这条记忆客观说了什么",
              "meaning_summary": "这条记忆为什么重要、什么时候该用",
              "base_facets": {{
                "entity": ["对象标签"],
                "topic": ["主题标签"],
                "time": ["时间标签"],
                "status": ["状态标签"],
                "memory_type": "identity|project|client|decision|method|reflection",
                "memory_subtype": "可为空字符串",
                "relevance_scope_core": ["身份背景|当前项目|客户历史|系统架构|方法规范|阶段路线|自我判断|历史决策"],
                "relevance_scope_extra": ["可扩展场景"]
              }},
              "domain_facets": {{
                "enterprise": {{
                  "客户": [],
                  "项目": [],
                  "产品/品类": [],
                  "风格": [],
                  "主题": [],
                  "风格/主题": [],
                  "时间/季节/节庆": [],
                  "流程节点": [],
                  "部门/角色": [],
                  "目标/约束": [],
                  "文档/资产类型": []
                }}
              }},
              "governance": {{
                "shelf_state": "open|half_open|closed",
                "importance": "pinned|high|normal|low",
                "pinned": true,
                "confidence": 0.0,
                "promotion_rule_text": "升级规则说明",
                "promotion_signals": {{
                  "repeated_access": false,
                  "recent_reinforcement": false,
                  "high_current_relevance": false,
                  "user_pin_override": false
                }},
                "degradation_rule_text": "降级规则说明",
                "degradation_signals": {{
                  "long_inactive": false,
                  "low_current_relevance": false,
                  "not_pinned": false,
                  "not_core_anymore": false
                }},
                "reactivation_rule": {{
                  "explicit_trigger_required": false,
                  "reactivation_signals": [],
                  "threshold": 0.75
                }},
                "rationale": "为什么这么编目"
              }}
            }}

            编目原则：
            1. 原始记忆是事实源，不要篡改其本义。
            2. fact_summary 写客观事实，meaning_summary 写调用意义。
            3. base_facets 是通用维度；domain_facets.enterprise 只在有企业业务语义时填写。
            4. 如果内容不是公司业务语义，不要硬塞 enterprise 字段，留空数组即可；其中“风格”和“主题”要分开写，“风格/主题”只是兼容旧字段的合并备份。
            5. 所有事件记录与时间理解以北京时间（Asia/Shanghai, UTC+08:00）为准，不要根据电脑系统时区推断。
            6. base_facets.time 填“内容时间线索”，例如正文提到的去年圣诞、7月测试、2026年4月，不等于系统创建时间。
            7. shelf_state:
               - open: 对当前和未来大量对话都高复用
               - half_open: 常有帮助，但不适合默认常驻
               - closed: 需明确线索才激活
            8. confidence 取 0 到 1。

            原始记忆：
            - raw_memory_id: {memory.id}
            - user_id: {memory.user_id}
            - app_name: {memory.app_name}
            - created_at_beijing: {CatalogCard.to_beijing_iso(memory.created_at)}

            正文：
            {memory.content}
            """
        )
        prompt += dedent(
            f"""

            Memlink Shrine v2 额外要求：
            - 你是外部辅助馆员，不是正在对话现场的知情者模型。
            - 你只允许补充 body_text、id_schema_id、confidence_source 这类内容层/标签层字段。
            - 你不得决定 main_id、upstream_main_ids、downstream_main_ids、relation_type、topology_role、path_status、is_landmark。
            - 这些链路字段只能由知情者模型或人工修理台写入。
            - body_text 是正文层浓缩，不是原文复制；raw_text 由系统保存，不需要你返回。

            四摘要和残影写入规范：
            {format_writing_spec_for_prompt()}
            """
        )

        try:
            data = self._generate_json(prompt)
        except Exception as exc:
            self._activate_fallback()
            return self._fallback_create_card(memory, exc)
        created_at = CatalogCard.to_beijing_iso(memory.created_at)
        topology_role = "node"
        path_status = "active"
        is_landmark = False
        main_id = build_default_main_id(
            memory.id,
            created_at,
            subgraph="PEND",
            position="U00",
            topology_role=topology_role,
            path_status=path_status,
            is_landmark=is_landmark,
        )
        return CatalogCard(
            raw_memory_id=memory.id,
            title=data["title"],
            fact_summary=data["fact_summary"],
            meaning_summary=data["meaning_summary"],
            base_facets=data["base_facets"],
            domain_facets=data["domain_facets"],
            body_text=data.get("body_text", self._compact_text(memory.content, 900)),
            raw_text=memory.content,
            semantic_facets={},
            main_id=main_id,
            upstream_main_ids=[],
            downstream_main_ids=[],
            relation_type="unassigned",
            topology_role=topology_role,
            path_status=path_status,
            is_landmark=is_landmark,
            id_schema_id=data.get("id_schema_id", "memlink_shrine_default_v2"),
            chain_author="",
            chain_author_role="none",
            chain_status="unassigned",
            chain_confidence=0.0,
            source_id=memory.id,
            source_type=memory.app_name or "openmemory",
            confidence_source=data.get("confidence_source", "ai_generated"),
            governance=data["governance"],
            raw_memory_created_at=created_at,
            projection_created_at=CatalogCard.now_iso(),
            projection_based_on="raw_memory",
        )

    def select_candidate_cards(
        self,
        question: str,
        cards: list[CatalogCard],
    ) -> QuerySelection:
        card_payload = [
            {
                "raw_memory_id": card.raw_memory_id,
                "main_id": card.main_id,
                "title": card.title,
                "fact_summary": card.fact_summary,
                "meaning_summary": card.meaning_summary,
                "semantic_facets": card.semantic_facets,
                "base_facets": card.base_facets,
                "domain_facets": card.domain_facets,
                "relation": {
                    "upstream_main_ids": card.upstream_main_ids,
                    "downstream_main_ids": card.downstream_main_ids,
                    "relation_type": card.relation_type,
                    "topology_role": card.topology_role,
                    "path_status": card.path_status,
                    "is_landmark": card.is_landmark,
                },
                "governance": {
                    "shelf_state": card.shelf_state,
                    "importance": card.importance,
                    "pinned": card.pinned,
                    "confidence": card.confidence,
                },
            }
            for card in cards
        ]
        prompt = dedent(
            f"""
            你是 Memlink Shrine 的检索馆员。你的任务是根据用户当前问题，从记忆卡目录中快速缩小到一个“候选记忆集合”。

            这一步不是最终回答，也不是只看标签就结束。
            这一步的目的，是利用标题、摘要、facets 和治理信息，找出后续“必须全文读取和统一理解”的候选记忆集合。

            请严格输出 JSON：
            {{
              "question": "{question}",
              "reasoning": "为什么选这些卡",
              "candidate_scope": "一句话说明这次缩圈后的候选集合范围",
              "selected_raw_memory_ids": ["raw id 1", "raw id 2"],
              "selected_titles": ["标题1", "标题2"]
            }}

            规则：
            1. 一旦进入候选集合，后续系统会对候选记忆全文统一理解，因此你这里宁可略宽，也不要漏掉关键记忆。
            2. 优先考虑：
               - 当前问题的主题匹配
               - 对象标签匹配
               - 时间线索匹配
               - open / half_open 状态
               - pinned / high 重要性
            3. 如果问题明显在问历史结论、身份背景、系统定义、项目路线，不要只选一条，应该返回能支撑完整理解的相关集合。

            当前问题：
            {question}

            可选记忆卡：
            {json.dumps(card_payload, ensure_ascii=False, indent=2)}
            """
        )
        try:
            data = self._generate_json(prompt)
        except Exception as exc:
            self._activate_fallback()
            return self._fallback_select_candidate_cards(question, cards, exc)
        return QuerySelection(
            question=question,
            reasoning=data.get("reasoning", ""),
            candidate_scope=data.get("candidate_scope"),
            selected_raw_memory_ids=data.get("selected_raw_memory_ids", []),
            selected_titles=data.get("selected_titles", []),
        )

    def create_memory_brief(
        self,
        question: str,
        cards: list[CatalogCard],
        raw_memories: list[RawMemory],
        routing_reason: str,
    ) -> MemoryBrief:
        payload = []
        raw_index = {memory.id: memory for memory in raw_memories}
        for card in cards:
            item = {
                "raw_memory_id": card.raw_memory_id,
                "main_id": card.main_id,
                "title": card.title,
                "fact_summary": card.fact_summary,
                "meaning_summary": card.meaning_summary,
                "body_text": card.body_text,
                "semantic_facets": card.semantic_facets,
                "base_facets": card.base_facets,
                "domain_facets": card.domain_facets,
                "relation": {
                    "upstream_main_ids": card.upstream_main_ids,
                    "downstream_main_ids": card.downstream_main_ids,
                    "relation_type": card.relation_type,
                    "topology_role": card.topology_role,
                    "path_status": card.path_status,
                    "is_landmark": card.is_landmark,
                },
            }
            memory = raw_index.get(card.raw_memory_id)
            if memory:
                item["raw_content"] = memory.content
            payload.append(item)

        prompt = dedent(
            f"""
            你是 Memlink Shrine 的总馆员。你已经拿到一组经过缩圈后的候选记忆。

            现在你的任务是：
            1. 阅读这组候选记忆的全文与卡片信息；
            2. 统一理解它们在当前问题下的意义；
            3. 输出一个给 Codex 使用的 memory brief。

            请注意：
            - 你不是把原文复制回去；
            - 你要输出“这批记忆在当前问题里的含义和背景结论”；
            - 必要时可以附少量证据片段；
            - 输出应能自然融入后续对话。

            请严格输出 JSON：
            {{
              "question": "{question}",
              "brief": "这批记忆对于当前问题的综合理解",
              "relevance_reason": "为什么这些记忆与当前问题相关",
              "applied_raw_memory_ids": ["..."],
              "applied_titles": ["..."],
              "confidence": 0.0,
              "evidence_snippets": ["少量必要证据片段"],
              "routing_reason": "{routing_reason}"
            }}

            当前问题：
            {question}

            候选记忆集合：
            {json.dumps(payload, ensure_ascii=False, indent=2)}
            """
        )
        prompt += dedent(
            """

            Memlink Shrine v2 简报约束：
            - 默认只使用 fact_summary、meaning_summary、body_text 和 relation；不要假设一定有 raw_content。
            - 简报要回答三件事：这条/这组记忆是什么、从哪里拐进来、往哪里去。
            - 如果 payload 中有 topology_role=origin 的卡片，要把它作为原点锚定简短说明。
            - 不要把原文整段复制给 Codex；只有用户显式要求原文/全文时 raw_content 才会进入 payload。
            """
        )
        try:
            data = self._generate_json(prompt)
        except Exception as exc:
            self._activate_fallback()
            return self._fallback_memory_brief(
                question=question,
                cards=cards,
                raw_memories=raw_memories,
                routing_reason=routing_reason,
                error=exc,
            )
        return MemoryBrief(
            question=question,
            brief=data.get("brief", ""),
            relevance_reason=data.get("relevance_reason", ""),
            applied_raw_memory_ids=data.get(
                "applied_raw_memory_ids",
                [memory.id for memory in raw_memories] or [card.raw_memory_id for card in cards],
            ),
            applied_titles=data.get(
                "applied_titles",
                [card.title for card in cards],
            ),
            confidence=float(data.get("confidence", 0.0)),
            evidence_snippets=data.get("evidence_snippets", []),
            routing_reason=data.get("routing_reason", routing_reason),
        )

