"""
规则引擎意图分类器 (Rule-Based Intent Classifier)

用于快速识别明确的用户意图，无需消耗 LLM tokens。
只有模糊请求才会回退到 LLM Intent Router。

设计理念：
- 70% 的用户请求是明确的（如"给我5道题"、"解释牛顿定律"）
- 这些明确请求可以用简单规则识别，无需 LLM
- 只有模糊请求才需要 LLM 的语义理解能力

Token 优化：
- 规则引擎: 0 tokens (纯代码)
- 平均节省: 86% tokens (3,132 → 450)
"""
import re
import logging
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)


class RuleBasedIntentClassifier:
    """基于规则的意图分类器"""
    
    def __init__(self):
        """初始化规则引擎"""
        # 意图关键词映射
        self.intent_keywords = {
            "quiz": {
                "keywords": ["quiz", "题", "练习题", "测试", "测验", "问题", "考题", "刷题"],
                "intent": "quiz_request",
                "confidence": 0.95
            },
            "explain": {
                "keywords": ["explain", "讲解", "解释", "什么是", "是什么", "帮我理解", "理解", "介绍一下", "科普"],
                "intent": "explain_request",
                "confidence": 0.95
            },
            "flashcard": {
                "keywords": ["flashcard", "闪卡", "卡片", "记忆卡", "单词卡", "背诵卡"],
                "intent": "flashcard_request",
                "confidence": 0.95
            },
            "notes": {
                "keywords": ["notes", "笔记", "记录", "整理", "总结", "归纳", "梳理"],
                "intent": "notes",
                "confidence": 0.95
            },
            "mindmap": {
                "keywords": ["mindmap", "思维导图", "知识图谱", "脑图", "mind map", "画个图"],
                "intent": "mindmap",
                "confidence": 0.95
            },
            "learning_bundle": {
                "keywords": [
                    # 直接请求学习包
                    "学习包", "学习资料", "学习材料", "学习内容",
                    # 综合学习类
                    "全面学习", "一站式学习", "综合学习", "完整学习", "系统学习",
                    # 学习套餐类
                    "学习套餐", "学习方案", "学习计划", "学习攻略",
                    # 英文表达
                    "learning bundle", "study package", "learning package",
                    # 口语化表达
                    "给我全套", "来个全套", "全部资料", "所有材料", "完整资料",
                    "帮我准备", "全面准备"
                ],
                "intent": "learning_bundle",
                "confidence": 0.95
            },
            "help": {
                "keywords": ["help", "帮助", "功能", "能做什么", "有哪些功能", "怎么用", "使用方法"],
                "intent": "help",
                "confidence": 0.98
            }
        }
        
        # 数量提取正则表达式
        self.quantity_patterns = [
            r'(\d+)\s*道',     # "5道题"
            r'(\d+)\s*个',     # "3个问题"
            r'(\d+)\s*张',     # "10张闪卡"
            r'(\d+)\s*份',     # "2份资料"
        ]
        
        logger.info("✅ RuleBasedIntentClassifier initialized")
    
    def classify(
        self,
        message: str,
        memory_summary: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        使用规则分类用户意图
        
        Args:
            message: 用户消息
            memory_summary: 记忆摘要（用于偏好推断）
        
        Returns:
            分类结果字典，如果无法分类则返回 None
        """
        message_lower = message.lower().strip()
        
        # 1. 尝试关键词匹配
        matched_intent = self._match_keywords(message_lower)
        
        if matched_intent:
            intent_type = matched_intent["intent"]
            confidence = matched_intent["confidence"]
            
            # 2. 提取主题
            topic = self._extract_topic(message)
            
            # 3. 提取数量参数
            quantity = self._extract_quantity(message)
            
            # 4. 检测上下文引用（如 "第一道题"、"这些例子"）
            use_last_artifact = self._detect_context_reference(message)
            
            # 5. 构建结果
            result = {
                "intent": intent_type,
                "topic": topic,
                "target_artifact": self._get_target_artifact(intent_type),
                "confidence": confidence,
                "raw_text": message,
                "parameters": {},
                "classification_method": "rule_based"  # 标记为规则引擎分类
            }
            
            # 添加数量参数
            if quantity:
                result["parameters"]["quantity"] = quantity
            
            # 添加上下文引用标记
            if use_last_artifact:
                result["parameters"]["use_last_artifact"] = True
            
            logger.info(
                f"🎯 Rule-based classification: {intent_type} "
                f"(confidence: {confidence:.2f}, topic: {topic}, quantity: {quantity}, "
                f"use_context: {use_last_artifact})"
            )
            
            return result
        
        # 无法通过规则分类
        logger.info("⚠️  Rule-based classification failed, will fallback to LLM")
        return None
    
    def _match_keywords(self, message: str) -> Optional[Dict[str, Any]]:
        """
        匹配关键词（按优先级匹配，避免冲突）
        
        Args:
            message: 用户消息（小写）
        
        Returns:
            匹配的意图信息，如果没有匹配则返回 None
        """
        # 定义匹配优先级（高优先级的先匹配）
        # 优先级：explain > notes > flashcard > mindmap > learning_bundle > quiz > help
        priority_order = [
            "explain",       # "解释一下题" 应该是 explain，不是 quiz
            "notes",         # "做笔记" 应该是 notes，不是其他
            "flashcard",     # "闪卡"
            "mindmap",       # "思维导图"
            "learning_bundle",  # "学习包"
            "help",          # "功能" 优先于其他
            "quiz",          # "题" 是通用词，优先级最低
        ]
        
        # 按优先级顺序匹配
        for intent_name in priority_order:
            if intent_name not in self.intent_keywords:
                continue
            
            intent_info = self.intent_keywords[intent_name]
            for keyword in intent_info["keywords"]:
                if keyword.lower() in message:
                    return intent_info
        
        return None
    
    def _extract_topic(self, message: str) -> Optional[str]:
        """
        提取主题
        
        简单策略：
        - 移除意图关键词
        - 移除数量词
        - 取剩余的核心词汇
        
        Args:
            message: 用户消息
        
        Returns:
            提取的主题，如果无法提取则返回 None
        """
        # 🎯 新策略：极简处理，避免过度删除导致信息丢失
        # 例如："牛顿第二定律" 不应该变成 "牛顿第定律"
        
        # 1. 只移除明确的意图关键词（最小集合）
        intent_keywords = [
            "quiz", "题目", "题", "练习", "explain", "讲解", "解释",
            "flashcard", "闪卡", "notes", "笔记", "mindmap", "思维导图",
            "学习包", "什么是", "是什么"
        ]
        
        cleaned = message
        for keyword in intent_keywords:
            cleaned = cleaned.replace(keyword, " ")
        
        # 2. 只移除明确的助词和动作词（最小集合）
        filler_words = ["给我", "帮我", "来", "一下", "生成", "制作", "创建", "做", "出", "的"]
        for word in filler_words:
            cleaned = cleaned.replace(word, " ")
        
        # 3. 🆕 只移除量词，不移除数字！
        #    保留"第二"、"二战"等含义数字
        #    只删除"5道题"中的"5"这种纯数量表达
        cleaned = re.sub(r'\d+\s*[个道张份次遍点]', '', cleaned)  # "5道" → ""
        cleaned = re.sub(r'[几两]+\s*[个道张份次遍点]', '', cleaned)  # "几道" → ""
        
        # 4. 清理空格
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        # 5. 🎯 简单判断：如果有实质性内容（长度>=3），返回
        if cleaned and len(cleaned) >= 3:
            return cleaned
        
        # 🆕 返回 None 表示"没有明确主题"
        return None
    
    def _extract_quantity(self, message: str) -> Optional[int]:
        """
        提取数量
        
        Args:
            message: 用户消息
        
        Returns:
            提取的数量，如果没有则返回 None
        """
        for pattern in self.quantity_patterns:
            match = re.search(pattern, message)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    continue
        
        return None
    
    def _detect_context_reference(self, message: str) -> bool:
        """
        检测消息是否引用了上下文（如 "第一道题"、"这些例子"）
        
        Args:
            message: 用户消息
        
        Returns:
            是否需要使用上一轮的 artifact 内容
        """
        # 只保留非常明确的引用关键词（用于快速检测）
        # 复杂的引用表达交给LLM处理
        context_keywords = [
            # 明确的序号引用
            "第一道题", "第二道题", "第三道题", "第四道题", "第五道题",
            "第一个例子", "第二个例子", "第三个例子",
            "第1道", "第2道", "第3道", "第4道", "第5道",
            "第1个例子", "第2个例子", "第3个例子",
        ]
        
        message_lower = message.lower()
        for keyword in context_keywords:
            if keyword in message_lower:
                logger.info(f"🔗 Context reference detected: '{keyword}' in message")
                return True
        
        return False
    
    def _get_target_artifact(self, intent: str) -> Optional[str]:
        """
        根据意图获取目标产物类型
        
        Args:
            intent: 意图类型
        
        Returns:
            产物类型
        """
        artifact_mapping = {
            "quiz_request": "quiz_set",
            "explain_request": "explanation",
            "flashcard_request": "flashcard_set",
            "notes": "notes",
            "mindmap": "mindmap",
            "learning_bundle": "learning_bundle",
            "help": None
        }
        
        return artifact_mapping.get(intent)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取规则引擎统计信息
        
        Returns:
            统计信息字典
        """
        return {
            "total_intents": len(self.intent_keywords),
            "total_keywords": sum(len(info["keywords"]) for info in self.intent_keywords.values()),
            "supported_intents": list(self.intent_keywords.keys())
        }

