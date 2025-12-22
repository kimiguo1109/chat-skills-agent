"""
Thinking Mode Selector - 智能思考模式选择器

负责：
1. 根据意图和上下文选择思考模式（真思考 vs 伪思考）
2. 优化成本：在保证质量的前提下使用最便宜的模型
3. 智能判断：是否需要深度 reasoning

🆕 修复的逻辑冲突：
- 规则顺序重新设计，避免"截断"问题
- explain_request 的定义统一
- 引用检查逻辑统一
"""
import logging
from typing import Dict, Any, Optional, Literal
from enum import Enum

from ..models.intent import IntentResult
from ..models.memory import SessionContext

logger = logging.getLogger(__name__)


class ThinkingMode(str, Enum):
    """思考模式枚举"""
    REAL = "real_thinking"      # 真思考：Kimi k2-thinking
    FAKE = "fake_thinking"      # 伪思考：Gemini 2.0 Flash Exp
    

class ThinkingModeSelector:
    """
    智能思考模式选择器
    
    核心逻辑（按优先级排序）：
    
    🧠 真思考触发条件：
    1. 强制真思考的 intent（learning_bundle, plan_skill, mindmap）
    2. 多技能组合请求（required_steps > 1）
    3. 全新 Topic（不在 session 历史中）
    4. explain_request + 全新 topic（需要深度教学结构）
    
    ⚡ 伪思考触发条件：
    1. Follow-up 问题（topic 在历史中）
    2. 引用特定内容（reference_index, use_last_artifact）
    3. 单一技能请求（quiz, flashcard, notes）且非新 topic
    """
    
    def __init__(self):
        """初始化选择器"""
        # 强制使用真思考的 intent（这些永远用真思考）
        self.force_real_thinking_intents = {
            "learning_bundle",      # 学习包（多技能组合）
            "plan_skill",           # 规划类技能
            "mindmap",              # 思维导图（需要全局视角）
        }
        
        # 单一技能 intent（可以用伪思考，但需要判断 topic）
        self.single_skill_intents = {
            "quiz_request",         # 题目生成
            "flashcard_request",    # 闪卡生成
            "notes",                # 笔记整理
        }
        
        # explain_request 特殊处理：新 topic → 真思考，follow-up → 伪思考
        
        logger.info("✅ ThinkingModeSelector initialized (v2 - conflict fixed)")
    
    def select_mode(
        self,
        intent_result: IntentResult,
        session_context: Optional[SessionContext] = None
    ) -> Dict[str, Any]:
        """
        选择思考模式
        
        🆕 重构后的逻辑顺序：
        1. 检查强制真思考的 intent
        2. 检查多技能组合
        3. 检查是否引用特定内容 → 伪思考
        4. 判断 topic 是否为新：新 → 真思考，旧 → 伪思考
        5. 根据 intent 类型决定默认模式
        """
        intent = intent_result.intent
        topic = intent_result.topic
        parameters = intent_result.parameters or {}
        
        logger.debug(f"🔍 Selecting mode: intent={intent}, topic={topic}, params={list(parameters.keys())}")
        
        # ============= 第 1 优先级：强制真思考 =============
        # 这些 intent 无论什么情况都用真思考
        if intent in self.force_real_thinking_intents:
            return self._use_real_thinking(
                reason=f"强制真思考 intent: '{intent}'（多主题/规划类）"
            )
        
        # ============= 第 2 优先级：多技能组合 =============
        required_steps = parameters.get("required_steps", [])
        if required_steps and len(required_steps) > 1:
            return self._use_real_thinking(
                reason=f"多技能组合请求（{len(required_steps)} steps），需要深度规划"
            )
        
        # ============= 第 3 优先级：引用特定内容 → 伪思考 =============
        # 这个检查要在 topic 判断之前，因为引用内容不需要深度理解
        if self._is_reference_request(parameters):
            return self._use_fake_thinking(
                reason="引用特定内容（题目/知识点），局部推理即可"
            )
        
        # ============= 第 4 优先级：判断 topic 新旧 =============
        is_new_topic = self._is_new_topic(topic, session_context)
        is_follow_up = not is_new_topic and topic is not None
        
        # ============= 第 5 优先级：根据 intent 类型决定 =============
        
        # explain_request 特殊处理
        if intent == "explain_request":
            if is_new_topic:
                return self._use_real_thinking(
                    reason=f"概念讲解 + 全新 topic '{topic}'，需要深度理解和教学结构"
                )
            else:
                return self._use_fake_thinking(
                    reason=f"概念讲解 + follow-up topic '{topic}'，局部补充即可"
                )
        
        # 单一技能 intent
        if intent in self.single_skill_intents:
            if is_new_topic:
                # 🆕 单一技能 + 新 topic：还是用真思考（需要理解主题）
                return self._use_real_thinking(
                    reason=f"单一技能 '{intent}' + 全新 topic '{topic}'，需要理解主题"
                )
            else:
                return self._use_fake_thinking(
                    reason=f"单一技能 '{intent}' + 已知 topic，无需深度推理"
                )
        
        # other intent（闲聊）
        if intent == "other":
            if is_follow_up:
                return self._use_fake_thinking(
                    reason="闲聊 + 有上下文，简单对话即可"
                )
            else:
                return self._use_fake_thinking(
                    reason="闲聊，无需深度推理"
                )
        
        # ============= 默认策略 =============
        # 无法判断时，保守使用真思考
        return self._use_real_thinking(
            reason=f"无法判断 intent='{intent}'，使用真思考保证质量"
        )
    
    def _is_reference_request(self, parameters: Dict[str, Any]) -> bool:
        """
        🆕 统一的引用检查逻辑
        
        检查是否引用特定内容（如 "第3题"、"上一个例子"）
        """
        # 检查所有可能的引用参数
        reference_indicators = [
            "use_last_artifact",    # 使用上一轮产出
            "reference_index",      # 引用特定索引（如第3题）
            "reference_type",       # 引用类型（question/example/content）
            "needs_last_artifact",  # 需要上一轮内容
        ]
        
        for indicator in reference_indicators:
            if parameters.get(indicator):
                logger.debug(f"✅ Reference detected: {indicator}={parameters[indicator]}")
                return True
        
        return False
    
    def _is_new_topic(
        self,
        topic: Optional[str],
        session_context: Optional[SessionContext]
    ) -> bool:
        """
        🆕 判断 topic 是否为全新的
        
        新 topic 的定义：
        - 不等于 current_topic
        - 不在最近 5 个 artifact 的 topics 中
        - 不在 session_topics 中
        
        Returns:
            True = 全新 topic，False = 已知 topic
        """
        # 没有 topic 时，视为新 topic（需要真思考来理解）
        if not topic:
            return True
        
        # 没有 session_context 时，视为新 topic
        if not session_context:
            return True
        
        # 检查 1: 是否等于 current_topic
        if session_context.current_topic:
            if topic.lower() == session_context.current_topic.lower():
                logger.debug(f"📌 Topic matches current_topic: {topic}")
                return False
        
        # 检查 2: 是否在 artifact_history 的 topics 中
        if session_context.artifact_history:
            recent_topics = [
                artifact.topic.lower() if artifact.topic else ""
                for artifact in session_context.artifact_history[-5:]
            ]
            if topic.lower() in recent_topics:
                logger.debug(f"📌 Topic in recent artifacts: {topic}")
                return False
        
        # 检查 3: 是否在 recent_intents 相关的 topics 中（通过 artifact_history 已覆盖）
        # SessionContext 没有 session_topics 属性，跳过此检查
        
        # 所有检查都没命中，是新 topic
        logger.debug(f"🆕 New topic detected: {topic}")
        return True
    
    def _use_real_thinking(self, reason: str) -> Dict[str, Any]:
        """
        使用真思考模式
        
        🔧 当前配置：全部使用 Gemini 2.5 Flash（关闭 Kimi 真思考以提升速度）
        """
        logger.info(f"🧠 Real Thinking (→ Gemini): {reason}")
        # 🔧 临时关闭 Kimi，全部使用 Gemini 2.5 Flash
        return {
            "mode": ThinkingMode.FAKE,  # 统一用 FAKE 模式
            "model": "gemini-2.5-flash",
            "reasoning": f"[Gemini模式] {reason}",
            "thinking_budget": 0,  # 🔧 禁用思考以确保完整输出
            "temperature": 1.0,
            "estimated_cost_multiplier": 0.05
        }
    
    def _use_fake_thinking(self, reason: str) -> Dict[str, Any]:
        """使用伪思考模式（Gemini 2.5 Flash）"""
        logger.info(f"⚡ Fake Thinking (Gemini): {reason}")
        return {
            "mode": ThinkingMode.FAKE,
            "model": "gemini-2.5-flash",
            "reasoning": reason,
            "thinking_budget": 0,  # 🔧 禁用思考以确保完整输出
            "temperature": 1.0,
            "estimated_cost_multiplier": 0.05  # 约 1/20 成本
        }
    
    def get_model_client(self, mode: ThinkingMode):
        """
        根据模式获取对应的模型客户端
        
        Args:
            mode: 思考模式
        
        Returns:
            模型客户端（GeminiClient - 当前全部使用 Gemini）
        
        🔧 当前配置：全部使用 Gemini（关闭 Kimi）
        """
        # 🔧 统一使用 Gemini
        from ..services.gemini import GeminiClient
        return GeminiClient()
