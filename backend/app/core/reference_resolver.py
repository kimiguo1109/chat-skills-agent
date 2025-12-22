"""
Reference Resolver - 引用解析器

功能：解析用户消息中对历史 artifacts 的引用
例如：
- "把第二题的相关内容帮我生成解释" → 提取 quiz_set 中第 2 题的内容
- "把第三张闪卡帮我出一道题" → 提取 flashcard_set 中第 3 张卡的内容

设计原则：
- 作为增量功能，不影响现有逻辑
- 只有检测到引用时才调用 LLM
- 使用低成本模型 (Gemini Flash)
"""

import re
import json
import logging
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ============= 引用模式定义 =============

# 中文数字映射
CHINESE_NUMBERS = {
    '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
    '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
    '第一': 1, '第二': 2, '第三': 3, '第四': 4, '第五': 5,
    '第六': 6, '第七': 7, '第八': 8, '第九': 9, '第十': 10,
}

# 引用类型映射 - 索引引用
INDEX_REFERENCE_PATTERNS = [
    # 题目引用：第X题、第X道题
    (r'第([一二三四五六七八九十\d]+)道?题', 'quiz', 'question'),
    # 闪卡引用：第X张闪卡、第X张卡、第X张卡片
    (r'第([一二三四五六七八九十\d]+)张[闪]?卡片?', 'flashcard', 'card'),
    # 例子引用：第X个例子、例X（支持 explain 和 explanation 类型）
    (r'第([一二三四五六七八九十\d]+)个?例[子]?', 'explain', 'example'),
    (r'例([一二三四五六七八九十\d]+)', 'explain', 'example'),
    # 概念引用：第X个概念
    (r'第([一二三四五六七八九十\d]+)个概念', 'explain', 'concept'),
]

# 🆕 关键词引用模式 - 匹配"根据 XXX 的例子"、"XXX 那道题"等
KEYWORD_REFERENCE_PATTERNS = [
    # 根据/基于 XXX 的例子/题目/闪卡
    (r'(?:根据|基于)[「『""]?(.{2,20}?)[」』""]?[的那个这个]?(?:例子?|例[子儿])', 'explain', 'example_keyword'),
    (r'(?:根据|基于)[「『""]?(.{2,20}?)[」』""]?[的那个这个]?(?:题目?|题)', 'quiz', 'question_keyword'),
    (r'(?:根据|基于)[「『""]?(.{2,20}?)[」』""]?[的那个这个]?(?:闪卡|卡片)', 'flashcard', 'card_keyword'),
    # XXX 的例子/那个例子
    (r'[「『""]?(.{2,20}?)[」』""]?[的那个这个]例子?', 'explain', 'example_keyword'),
    # 刚才/之前提到的 XXX
    (r'(?:刚才|之前|前面)[提说讲]?[到的]?[「『""]?(.{2,20}?)[」』""]?', 'any', 'keyword'),
]


@dataclass
class ResolvedReference:
    """解析后的引用"""
    original_text: str  # 原始引用文本，如 "第二题"
    artifact_type: str  # 引用的 artifact 类型：quiz, flashcard, explanation
    item_type: str      # 引用的项目类型：question, card, example
    index: int          # 引用的索引（1-based）
    content: Optional[Dict[str, Any]] = None  # 解析后的内容
    context: Optional[str] = None  # 提取的上下文文本
    source_topic: Optional[str] = None  # 🆕 来源 artifact 的 topic（用于正确设置 intent topic）


class ReferenceResolver:
    """
    引用解析器
    
    使用流程：
    1. detect_references() - 检测消息中的引用（本地正则，0 token）
    2. resolve_references() - 从 artifacts 中提取内容（本地查找）
    3. 如果需要 LLM 辅助理解复杂引用，调用 resolve_with_llm()
    
    支持两种引用类型：
    - 索引引用：第X题、第X张卡
    - 关键词引用：根据凡尔赛条约的例子、XXX那道题
    """
    
    def __init__(self):
        """初始化引用解析器"""
        self.index_patterns = INDEX_REFERENCE_PATTERNS
        self.keyword_patterns = KEYWORD_REFERENCE_PATTERNS
        logger.info("✅ ReferenceResolver initialized (supports index + keyword references)")
    
    def detect_references(self, message: str) -> List[Tuple[str, str, str, int]]:
        """
        检测消息中的索引引用（本地正则匹配，0 token）
        
        Args:
            message: 用户消息
        
        Returns:
            List of (original_text, artifact_type, item_type, index)
        """
        references = []
        
        for pattern, artifact_type, item_type in self.index_patterns:
            matches = re.finditer(pattern, message)
            for match in matches:
                original_text = match.group(0)
                number_str = match.group(1)
                
                # 转换数字
                if number_str in CHINESE_NUMBERS:
                    index = CHINESE_NUMBERS[number_str]
                else:
                    try:
                        index = int(number_str)
                    except ValueError:
                        continue
                
                references.append((original_text, artifact_type, item_type, index))
                logger.info(f"🔍 Detected index reference: '{original_text}' → {artifact_type}.{item_type}[{index}]")
        
        return references
    
    def detect_keyword_references(self, message: str) -> List[Tuple[str, str, str, str]]:
        """
        🆕 检测消息中的关键词引用（本地正则匹配，0 token）
        
        Args:
            message: 用户消息
        
        Returns:
            List of (original_text, artifact_type, item_type, keyword)
        """
        references = []
        
        for pattern, artifact_type, item_type in self.keyword_patterns:
            matches = re.finditer(pattern, message)
            for match in matches:
                original_text = match.group(0)
                keyword = match.group(1).strip()
                
                # 过滤掉太短或无意义的关键词
                if len(keyword) < 2 or keyword in ['的', '这个', '那个', '什么']:
                    continue
                
                references.append((original_text, artifact_type, item_type, keyword))
                logger.info(f"🔍 Detected keyword reference: '{original_text}' → {artifact_type}.{item_type} keyword='{keyword}'")
        
        return references
    
    def has_references(self, message: str) -> bool:
        """快速检查消息是否包含引用（0 token）"""
        has_index = len(self.detect_references(message)) > 0
        has_keyword = len(self.detect_keyword_references(message)) > 0
        return has_index or has_keyword
    
    def resolve_references(
        self, 
        message: str, 
        artifact_history: List[Any]
    ) -> List[ResolvedReference]:
        """
        解析引用并从 artifacts 中提取内容（本地查找，0 token）
        
        支持：
        - 索引引用：第X题、第X张卡
        - 关键词引用：根据凡尔赛条约的例子
        
        Args:
            message: 用户消息
            artifact_history: artifact 历史列表
        
        Returns:
            解析后的引用列表
        """
        resolved = []
        
        # 1. 处理索引引用
        index_refs = self.detect_references(message)
        for original_text, artifact_type, item_type, index in index_refs:
            ref = self._resolve_index_reference(
                original_text, artifact_type, item_type, index, artifact_history
            )
            if ref:
                resolved.append(ref)
        
        # 2. 处理关键词引用
        keyword_refs = self.detect_keyword_references(message)
        for original_text, artifact_type, item_type, keyword in keyword_refs:
            ref = self._resolve_keyword_reference(
                original_text, artifact_type, item_type, keyword, artifact_history
            )
            if ref:
                resolved.append(ref)
        
        return resolved
    
    def _resolve_index_reference(
        self,
        original_text: str,
        artifact_type: str,
        item_type: str,
        index: int,
        artifact_history: List[Any]
    ) -> Optional[ResolvedReference]:
        """解析索引引用（第X题）"""
        content = None
        context = None
        source_topic = None
        
        for artifact_record in reversed(artifact_history):
            artifact_content = artifact_record.content
            
            if not artifact_content or not isinstance(artifact_content, dict):
                continue
            
            record_type = artifact_record.artifact_type if hasattr(artifact_record, 'artifact_type') else None
            
            if artifact_type == 'quiz' and item_type == 'question':
                # 🔥 支持多种 quiz 类型名称
                if record_type and not any(t in record_type for t in ['quiz', 'quiz_set']):
                    # 也检查 content 结构
                    if 'questions' not in artifact_content:
                        continue
                content, context = self._extract_quiz_question(artifact_content, index)
            elif artifact_type == 'flashcard' and item_type == 'card':
                # 🔥 支持多种 flashcard 类型名称
                if record_type and not any(t in record_type for t in ['flashcard', 'flashcard_set']):
                    if 'cardList' not in artifact_content and 'cards' not in artifact_content:
                        continue
                content, context = self._extract_flashcard(artifact_content, index)
            elif artifact_type == 'explain' and item_type == 'example':
                # 🔥 支持多种 explain 类型名称
                if record_type and not any(t in record_type for t in ['explain', 'explanation']):
                    if 'examples' not in artifact_content:
                        continue
                content, context = self._extract_example(artifact_content, index)
            
            if content:
                source_topic = artifact_record.topic if hasattr(artifact_record, 'topic') else None
                logger.info(f"✅ Found matching artifact: {artifact_record.artifact_id} (topic: {source_topic})")
                break
        
        if content:
            logger.info(f"✅ Resolved index reference: '{original_text}' → found content")
        else:
            logger.warning(f"⚠️  Failed to resolve index reference: '{original_text}'")
        
        return ResolvedReference(
            original_text=original_text,
            artifact_type=artifact_type,
            item_type=item_type,
            index=index,
            content=content,
            context=context,
            source_topic=source_topic
        )
    
    def _resolve_keyword_reference(
        self,
        original_text: str,
        artifact_type: str,
        item_type: str,
        keyword: str,
        artifact_history: List[Any]
    ) -> Optional[ResolvedReference]:
        """
        🆕 解析关键词引用（根据凡尔赛条约的例子）
        
        策略：在 artifacts 中搜索包含关键词的内容
        """
        content = None
        context = None
        source_topic = None
        
        logger.info(f"🔍 Resolving keyword reference: '{keyword}' in {artifact_type}")
        
        for artifact_record in reversed(artifact_history):
            artifact_content = artifact_record.content
            
            if not artifact_content or not isinstance(artifact_content, dict):
                continue
            
            record_type = artifact_record.artifact_type if hasattr(artifact_record, 'artifact_type') else None
            
            # 根据引用类型在对应的 artifact 中搜索关键词
            # 🔥 优化：如果 artifact 包含对应的数据结构，直接搜索，不仅仅依赖 artifact_type
            
            if artifact_type in ['explain', 'any'] and 'example_keyword' in item_type:
                # 搜索 explanation 中的 examples
                # 🔥 如果 artifact 有 examples 字段，直接搜索
                if 'examples' in artifact_content:
                    content, context = self._search_examples_by_keyword(artifact_content, keyword)
                elif record_type and 'explain' in record_type:
                    content, context = self._search_examples_by_keyword(artifact_content, keyword)
                
            elif artifact_type in ['quiz', 'any'] and 'question_keyword' in item_type:
                # 搜索 quiz 中的题目
                if 'questions' in artifact_content:
                    content, context = self._search_questions_by_keyword(artifact_content, keyword)
                elif record_type and 'quiz' in record_type:
                    content, context = self._search_questions_by_keyword(artifact_content, keyword)
                
            elif artifact_type in ['flashcard', 'any'] and 'card_keyword' in item_type:
                # 搜索 flashcard 中的卡片
                if 'cardList' in artifact_content or 'cards' in artifact_content:
                    content, context = self._search_cards_by_keyword(artifact_content, keyword)
                elif record_type and 'flashcard' in record_type:
                    content, context = self._search_cards_by_keyword(artifact_content, keyword)
            
            elif item_type == 'keyword':
                # 通用关键词搜索 - 在所有类型的 artifact 中搜索
                content, context = self._search_any_by_keyword(artifact_content, keyword)
            
            if content:
                source_topic = artifact_record.topic if hasattr(artifact_record, 'topic') else None
                logger.info(f"✅ Found keyword match in artifact: {artifact_record.artifact_id} (topic: {source_topic})")
                break
        
        if content:
            logger.info(f"✅ Resolved keyword reference: '{original_text}' → found content for '{keyword}'")
            return ResolvedReference(
                original_text=original_text,
                artifact_type=artifact_type,
                item_type=item_type,
                index=0,  # 关键词引用没有索引
                content=content,
                context=context,
                source_topic=source_topic
            )
        else:
            logger.warning(f"⚠️  Failed to resolve keyword reference: '{original_text}' → keyword '{keyword}' not found")
            return None
    
    def _search_examples_by_keyword(
        self,
        artifact_content: Dict[str, Any],
        keyword: str
    ) -> Tuple[Optional[Dict], Optional[str]]:
        """在 explanation artifact 中搜索包含关键词的 example"""
        examples = artifact_content.get('examples', [])
        
        # 🔥 清理关键词（去掉书名号等）
        clean_keyword = self._clean_keyword(keyword)
        
        for i, example in enumerate(examples):
            example_text = example.get('example', '')
            explanation_text = example.get('explanation', '')
            
            # 🔥 清理待搜索文本
            clean_example = self._clean_keyword(example_text)
            clean_explanation = self._clean_keyword(explanation_text)
            
            # 检查关键词是否出现在 example 或 explanation 中
            if clean_keyword in clean_example or clean_keyword in clean_explanation:
                context = f"例子: {example_text}\n解释: {explanation_text}"
                logger.info(f"🎯 Found keyword '{keyword}' in example {i+1}")
                return example, context
        
        return None, None
    
    def _clean_keyword(self, text: str) -> str:
        """清理文本中的书名号、引号等符号，用于模糊匹配"""
        # 去掉书名号、引号等
        chars_to_remove = ['《', '》', '「', '」', '『', '』', '"', '"', "'", "'", '"', "'"]
        result = text
        for char in chars_to_remove:
            result = result.replace(char, '')
        return result
    
    def _search_questions_by_keyword(
        self,
        artifact_content: Dict[str, Any],
        keyword: str
    ) -> Tuple[Optional[Dict], Optional[str]]:
        """在 quiz artifact 中搜索包含关键词的题目"""
        questions = artifact_content.get('questions', [])
        
        for i, question in enumerate(questions):
            question_text = question.get('question', '') or question.get('question_text', '')
            
            if keyword in question_text:
                context = f"题目: {question_text}"
                logger.info(f"🎯 Found keyword '{keyword}' in question {i+1}")
                return question, context
        
        return None, None
    
    def _search_cards_by_keyword(
        self,
        artifact_content: Dict[str, Any],
        keyword: str
    ) -> Tuple[Optional[Dict], Optional[str]]:
        """在 flashcard artifact 中搜索包含关键词的卡片"""
        cards = artifact_content.get('cardList') or artifact_content.get('cards', [])
        
        for i, card in enumerate(cards):
            front = card.get('front', '')
            back = card.get('back', '')
            
            if keyword in front or keyword in back:
                context = f"正面: {front}\n背面: {back}"
                logger.info(f"🎯 Found keyword '{keyword}' in card {i+1}")
                return card, context
        
        return None, None
    
    def _search_any_by_keyword(
        self,
        artifact_content: Dict[str, Any],
        keyword: str
    ) -> Tuple[Optional[Dict], Optional[str]]:
        """在任意 artifact 中搜索关键词"""
        # 先尝试 examples
        result = self._search_examples_by_keyword(artifact_content, keyword)
        if result[0]:
            return result
        
        # 再尝试 questions
        result = self._search_questions_by_keyword(artifact_content, keyword)
        if result[0]:
            return result
        
        # 最后尝试 cards
        result = self._search_cards_by_keyword(artifact_content, keyword)
        if result[0]:
            return result
        
        return None, None
    
    def _extract_quiz_question(
        self, 
        artifact_content: Dict[str, Any], 
        index: int
    ) -> Tuple[Optional[Dict], Optional[str]]:
        """从 quiz_set 中提取指定题目"""
        # 检查是否是 quiz_set 类型
        if 'questions' not in artifact_content and 'quiz_set_id' not in artifact_content:
            return None, None
        
        questions = artifact_content.get('questions', [])
        if not questions or index < 1 or index > len(questions):
            return None, None
        
        question = questions[index - 1]  # 转换为 0-based index
        
        # 构建上下文文本
        context_parts = []
        context_parts.append(f"题目: {question.get('question_text', '')}")
        if question.get('options'):
            context_parts.append(f"选项: {', '.join(question.get('options', []))}")
        if question.get('correct_answer'):
            context_parts.append(f"答案: {question.get('correct_answer', '')}")
        if question.get('explanation'):
            context_parts.append(f"解释: {question.get('explanation', '')}")
        if question.get('related_concepts'):
            context_parts.append(f"相关概念: {', '.join(question.get('related_concepts', []))}")
        
        context = '\n'.join(context_parts)
        
        return question, context
    
    def _extract_flashcard(
        self, 
        artifact_content: Dict[str, Any], 
        index: int
    ) -> Tuple[Optional[Dict], Optional[str]]:
        """从 flashcard_set 中提取指定闪卡 - 🔥 兼容新格式 (cardList) 和旧格式 (cards)"""
        # 检查是否是 flashcard_set 类型
        # 兼容新格式 (cardList, title) 和旧格式 (cards, flashcard_set_id)
        if 'cardList' not in artifact_content and 'cards' not in artifact_content and 'flashcard_set_id' not in artifact_content:
            return None, None
        
        # 优先使用新格式 cardList，否则使用旧格式 cards
        cards = artifact_content.get('cardList') or artifact_content.get('cards', [])
        if not cards or index < 1 or index > len(cards):
            return None, None
        
        card = cards[index - 1]  # 转换为 0-based index
        
        # 构建上下文文本
        context_parts = []
        context_parts.append(f"正面: {card.get('front', '')}")
        context_parts.append(f"背面: {card.get('back', '')}")
        # 新格式不再包含 hints 和 related_concepts，但保留向后兼容
        if card.get('hints'):
            context_parts.append(f"提示: {', '.join(card.get('hints', []))}")
        if card.get('related_concepts'):
            context_parts.append(f"相关概念: {', '.join(card.get('related_concepts', []))}")
        
        context = '\n'.join(context_parts)
        
        return card, context
    
    def _extract_example(
        self, 
        artifact_content: Dict[str, Any], 
        index: int
    ) -> Tuple[Optional[Dict], Optional[str]]:
        """从 explanation 中提取指定例子"""
        # 🔍 调试：输出 artifact_content 的键
        logger.debug(f"🔍 _extract_example: artifact_content keys = {list(artifact_content.keys()) if artifact_content else 'None'}")
        
        # 检查是否是 explanation 类型
        if 'examples' not in artifact_content and 'concept' not in artifact_content:
            logger.debug(f"⚠️  _extract_example: no 'examples' or 'concept' key found")
            return None, None
        
        examples = artifact_content.get('examples', [])
        logger.debug(f"🔍 _extract_example: found {len(examples)} examples, requesting index {index}")
        
        if not examples or index < 1 or index > len(examples):
            logger.debug(f"⚠️  _extract_example: index {index} out of range (1-{len(examples)})")
            return None, None
        
        example = examples[index - 1]  # 转换为 0-based index
        
        # 构建上下文文本
        context_parts = []
        if isinstance(example, dict):
            context_parts.append(f"例子: {example.get('example', '')}")
            if example.get('explanation'):
                context_parts.append(f"说明: {example.get('explanation', '')}")
        else:
            context_parts.append(f"例子: {example}")
        
        context = '\n'.join(context_parts)
        
        return example, context
    
    def format_resolved_content(self, resolved_refs: List[ResolvedReference]) -> str:
        """
        格式化解析后的内容，用于传递给 Skill
        
        Args:
            resolved_refs: 解析后的引用列表
        
        Returns:
            格式化的上下文字符串
        """
        if not resolved_refs:
            return ""
        
        parts = []
        for ref in resolved_refs:
            if ref.context:
                parts.append(f"【{ref.original_text}的内容】\n{ref.context}")
        
        return "\n\n".join(parts)


# 全局单例
_resolver_instance = None

def get_reference_resolver() -> ReferenceResolver:
    """获取引用解析器单例"""
    global _resolver_instance
    if _resolver_instance is None:
        _resolver_instance = ReferenceResolver()
    return _resolver_instance

