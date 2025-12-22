"""
Semantic Skill Matcher - 基于 Embedding 的语义技能匹配器

使用 Sentence Transformers 进行语义相似度匹配，解决关键词匹配的局限性：
1. 理解语义而非表面词汇
2. 支持多语言（中英日韩等）
3. 对用户表达方式的变化更鲁棒
4. 0-token 匹配（本地计算）

核心思路：
- 预定义每个技能的语义描述（正例 + 反例）
- 将用户消息编码为向量
- 计算与各技能描述的相似度
- 返回最佳匹配

Author: AI Agent
Date: 2025-12-19
"""

import logging
import os
import json
import hashlib
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import numpy as np

logger = logging.getLogger(__name__)

# 延迟导入，避免启动时加载模型
_model = None
_model_name = "paraphrase-multilingual-MiniLM-L12-v2"


def get_embedding_model():
    """延迟加载 Embedding 模型"""
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"🔄 Loading embedding model: {_model_name}")
            _model = SentenceTransformer(_model_name)
            logger.info(f"✅ Embedding model loaded successfully")
        except ImportError:
            logger.warning("⚠️ sentence-transformers not installed, semantic matching disabled")
            return None
        except Exception as e:
            logger.error(f"❌ Failed to load embedding model: {e}")
            return None
    return _model


@dataclass
class SemanticMatch:
    """语义匹配结果"""
    skill_id: str
    confidence: float
    matched_description: str
    is_negative_match: bool = False  # 是否匹配到反例


class SemanticSkillMatcher:
    """
    基于语义向量的技能匹配器
    
    特点：
    1. 使用多语言 Sentence Transformer 模型
    2. 预计算技能描述的向量（缓存）
    3. 支持正例和反例匹配
    4. 置信度阈值控制
    """
    
    # 🔥 核心：技能的语义描述
    # 每个技能有正例（应该匹配）和反例（不应该匹配）
    SKILL_DESCRIPTIONS = {
        "quiz": {
            "positive": [
                # 中文正例
                "给我出几道练习题",
                "帮我出3道关于光合作用的选择题",
                "出两道牛顿定律的测验题",
                "做一些练习题来测试我",
                "生成5道考试题",
                "帮我做几道题目",
                "出题测试一下",
                "来几道练习",
                "给我一些测验题",
                "帮我出几道选择题",
                # 英文正例
                "Generate practice questions about photosynthesis",
                "Give me 3 quiz questions on Newton's laws",
                "Create some test questions for me",
                "Make a quiz about DNA",
                "I want some practice problems",
                "Generate exercises for this topic",
            ],
            "negative": [
                # 不应该匹配为 quiz 的消息
                "学生通常在这类问题中犯什么错误",
                "这个问题怎么解",
                "这道题的答案是什么",
                "这类问题有什么技巧",
                "关于这个问题我有疑问",
                "What mistakes do students make on this problem",
                "How to solve this question",
                "What is the answer to this problem",
            ],
            "weight": 1.0,  # 权重（可调整优先级）
        },
        
        "flashcard": {
            "positive": [
                # 中文正例
                "帮我做几张闪卡",
                "生成3张关于化学键的记忆卡",
                "做5张单词卡片",
                "帮我制作闪卡来复习",
                "生成一些背诵卡",
                "做几张复习卡片",
                "帮我做抽认卡",
                "生成关于DNA的记忆卡",  # 🆕
                "给我做几张卡片",  # 🆕
                "来几张闪卡",  # 🆕
                "制作记忆卡",  # 🆕
                # 英文正例
                "Create flashcards for vocabulary",
                "Make 5 flash cards about chemistry",
                "Generate memory cards for studying",
                "I need some flashcards to review",
                "Create study cards for me",
                "Generate memory cards about DNA",  # 🆕
            ],
            "negative": [
                "这张卡片上写的是什么",
                "卡片的内容是什么意思",
                "What does this card say",
                "解释这个概念",  # 🆕 防止与 explain 混淆
                "讲解一下",  # 🆕
            ],
            "weight": 1.1,  # 🆕 略微提高权重
        },
        
        "explain": {
            "positive": [
                # 中文正例
                "详细讲解一下光合作用",
                "解释什么是牛顿第二定律",
                "帮我理解细胞呼吸",
                "讲一讲这个概念",
                "教我DNA的结构",
                "科普一下量子力学",
                "给我介绍一下这个知识点",
                "解读一下这个定理",
                # 英文正例
                "Explain photosynthesis in detail",
                "What is Newton's second law",
                "Help me understand cell respiration",
                "Teach me about DNA structure",
                "Explain this concept to me",
            ],
            "negative": [
                "出几道题来测试这个概念",
                "做几张闪卡",
                "Generate questions about this",
            ],
            "weight": 1.0,
        },
        
        "notes": {
            "positive": [
                # 中文正例
                "帮我做笔记",
                "整理这个章节的要点",
                "总结一下这些内容",
                "归纳这个主题",
                "帮我梳理知识点",
                "提炼重点",
                # 英文正例
                "Take notes on this topic",
                "Summarize the key points",
                "Outline this chapter",
                "Create a summary for me",
            ],
            "negative": [],
            "weight": 0.9,
        },
        
        "mindmap": {
            "positive": [
                # 中文正例
                "画一张思维导图",
                "生成知识图谱",
                "做一个概念图",
                "帮我做脑图",
                "画结构图",
                # 英文正例
                "Create a mind map",
                "Generate a concept map",
                "Make a knowledge graph",
                "Draw a structure diagram",
            ],
            "negative": [],
            "weight": 0.9,
        },
        
        "learning_bundle": {
            "positive": [
                # 中文正例
                "帮我制定学习计划",
                "生成一个完整的学习包",
                "做一套学习资料",
                "帮我规划学习路线",
                "先讲解再出题",
                "讲解+闪卡+测验",
                "给我一套完整的学习材料",  # 🆕
                "包含闪卡和测验的学习包",  # 🆕
                # 英文正例
                "Create a study plan",
                "Generate a learning bundle",
                "Make a complete study package",
                "Plan my learning path",
                "Give me a complete study set",  # 🆕
            ],
            "negative": [
                # 🆕 简单的继续/对话不应该匹配
                "继续讲",
                "继续",
                "然后呢",
                "接着讲",
                "Go on",
                "Continue",
            ],
            "weight": 0.9,
        },
        
        "other": {
            "positive": [
                # 中文正例 - 对话/讨论类
                "学生通常在这类问题中犯什么错误",
                "这个问题有哪些常见误区",
                "这道题怎么解",
                "答案是什么",
                "能举个例子吗",
                "继续讲",
                "继续",  # 🆕
                "然后呢",  # 🆕
                "接着讲",  # 🆕
                "再说说",  # 🆕
                "你好",
                "谢谢",
                "我想学习物理",
                "帮我解答这道题",
                "这个公式怎么用",
                "有什么技巧",
                "为什么是这样",
                "好的",  # 🆕
                "明白了",  # 🆕
                "懂了",  # 🆕
                # 英文正例
                "What mistakes do students make",
                "How to solve this problem",
                "What is the answer",
                "Can you give an example",
                "Continue please",
                "Go on",  # 🆕
                "Then what",  # 🆕
                "Hello",
                "Thanks",
                "I want to learn physics",
                "Help me solve this",
                "How to use this formula",
                "I see",  # 🆕
                "Got it",  # 🆕
            ],
            "negative": [
                # 明确的技能请求不应该匹配为 other
                "出几道题",
                "做几张闪卡",
                "详细讲解光合作用",  # 🆕 注意：需要有具体主题才是明确的讲解请求
                "Generate questions",
                "Create flashcards",
                "帮我制定学习计划",  # 🆕
                "做一个学习包",  # 🆕
            ],
            "weight": 0.85,  # 🆕 略微提高权重
        },
    }
    
    def __init__(self, cache_dir: Optional[str] = None):
        """
        初始化语义匹配器
        
        Args:
            cache_dir: 向量缓存目录
        """
        self.model = None
        self._embeddings_cache: Dict[str, np.ndarray] = {}
        self._initialized = False
        
        # 缓存目录
        if cache_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            cache_dir = os.path.join(base_dir, ".embedding_cache")
        self.cache_dir = cache_dir
        
        # 预计算的技能向量
        self._skill_embeddings: Dict[str, Dict[str, np.ndarray]] = {}
        
    def initialize(self) -> bool:
        """
        初始化模型和预计算向量
        
        Returns:
            是否初始化成功
        """
        if self._initialized:
            return True
            
        self.model = get_embedding_model()
        if self.model is None:
            logger.warning("⚠️ Semantic matcher disabled: model not available")
            return False
        
        # 预计算技能描述的向量
        logger.info("🔄 Pre-computing skill description embeddings...")
        
        for skill_id, descriptions in self.SKILL_DESCRIPTIONS.items():
            self._skill_embeddings[skill_id] = {
                "positive": self._encode_texts(descriptions["positive"]),
                "negative": self._encode_texts(descriptions.get("negative", [])),
                "weight": descriptions.get("weight", 1.0),
            }
        
        logger.info(f"✅ Semantic matcher initialized with {len(self._skill_embeddings)} skills")
        self._initialized = True
        return True
    
    def _encode_texts(self, texts: List[str]) -> Optional[np.ndarray]:
        """编码文本列表为向量"""
        if not texts or self.model is None:
            return None
        return self.model.encode(texts, convert_to_numpy=True)
    
    def _compute_similarity(self, query_embedding: np.ndarray, target_embeddings: np.ndarray) -> float:
        """计算查询向量与目标向量组的最大相似度"""
        if target_embeddings is None or len(target_embeddings) == 0:
            return 0.0
        
        # 计算余弦相似度
        similarities = np.dot(target_embeddings, query_embedding) / (
            np.linalg.norm(target_embeddings, axis=1) * np.linalg.norm(query_embedding) + 1e-8
        )
        return float(np.max(similarities))
    
    def match(
        self, 
        message: str, 
        threshold: float = 0.65,  # 🆕 提高阈值，更严格
        negative_threshold: float = 0.6,  # 🆕 降低反向阈值，更容易排除
        confidence_gap: float = 0.15  # 🆕 最高分和次高分的差距要求
    ) -> Optional[SemanticMatch]:
        """
        语义匹配用户消息到技能
        
        🆕 严格匹配策略：
        1. 提高正向阈值到 0.65（之前 0.5）
        2. 降低反向阈值到 0.6（更容易排除）
        3. 要求最高分和次高分有明显差距（0.15）
        4. 对于不确定的情况，返回 None 让 LLM 处理
        
        Args:
            message: 用户消息
            threshold: 正向匹配阈值（0-1），更高 = 更严格
            negative_threshold: 反向匹配阈值（高于此值时排除）
            confidence_gap: 最高分和次高分的最小差距
            
        Returns:
            SemanticMatch 或 None（不确定时返回 None）
        """
        if not self._initialized:
            if not self.initialize():
                return None
        
        # 编码用户消息
        query_embedding = self.model.encode([message], convert_to_numpy=True)[0]
        
        # 计算与各技能的相似度
        results: List[Tuple[str, float, float, str]] = []  # (skill_id, positive_score, negative_score, best_desc)
        
        for skill_id, embeddings in self._skill_embeddings.items():
            positive_emb = embeddings["positive"]
            negative_emb = embeddings["negative"]
            weight = embeddings["weight"]
            
            # 计算正向相似度
            positive_score = self._compute_similarity(query_embedding, positive_emb) * weight
            
            # 计算反向相似度（如果有反例）
            negative_score = 0.0
            if negative_emb is not None and len(negative_emb) > 0:
                negative_score = self._compute_similarity(query_embedding, negative_emb)
            
            results.append((skill_id, positive_score, negative_score, ""))
        
        # 排序：优先正向分数高，同时排除反向分数高的
        results.sort(key=lambda x: x[1], reverse=True)
        
        best_skill, best_positive, best_negative, _ = results[0]
        second_skill, second_positive, second_negative, _ = results[1] if len(results) > 1 else (None, 0, 0, "")
        
        # 日志
        logger.info(f"🔍 Semantic matching: '{message[:50]}...'")
        for skill_id, pos, neg, _ in results[:3]:
            logger.info(f"   • {skill_id}: positive={pos:.3f}, negative={neg:.3f}")
        
        # 🆕 严格检查 1: 最高分必须超过阈值
        if best_positive < threshold:
            logger.info(f"⚠️ No confident match: best={best_skill}({best_positive:.3f}) < threshold({threshold})")
            return None
        
        # 🆕 严格检查 2: 最高分和次高分要有明显差距
        score_gap = best_positive - second_positive
        if score_gap < confidence_gap and best_skill != "other":
            logger.info(f"⚠️ Ambiguous match: gap={score_gap:.3f} < {confidence_gap} between {best_skill} and {second_skill}")
            # 🆕 如果差距不够，且最佳不是 other，返回 None 让 LLM 决定
            return None
        
        # 🆕 严格检查 3: 检查反向匹配
        if best_negative > negative_threshold:
            logger.info(f"⚠️ Rejected {best_skill}: negative score {best_negative:.3f} > {negative_threshold}")
            return None
        
        # 🆕 严格检查 4: 检查是否有其他技能的强反向匹配
        for skill_id, pos, neg, _ in results:
            if skill_id == best_skill:
                continue
            if neg > negative_threshold:
                logger.info(f"⚠️ Strong negative match for {skill_id}: {neg:.3f}")
        
        # 🆕 严格检查 5: 如果最佳匹配是非 other 的生成技能，但分数不够高（<0.75），也返回 None
        generation_skills = {"quiz", "flashcard", "explain", "notes", "mindmap", "learning_bundle"}
        if best_skill in generation_skills and best_positive < 0.75:
            logger.info(f"⚠️ Generation skill {best_skill} needs higher confidence: {best_positive:.3f} < 0.75")
            return None
        
        logger.info(f"✅ Confident match: {best_skill} (score={best_positive:.3f}, gap={score_gap:.3f})")
        return SemanticMatch(
            skill_id=best_skill,
            confidence=best_positive,
            matched_description="",
        )
    
    def get_all_scores(self, message: str) -> Dict[str, float]:
        """获取消息与所有技能的相似度分数（用于调试）"""
        if not self._initialized:
            if not self.initialize():
                return {}
        
        query_embedding = self.model.encode([message], convert_to_numpy=True)[0]
        
        scores = {}
        for skill_id, embeddings in self._skill_embeddings.items():
            positive_emb = embeddings["positive"]
            weight = embeddings["weight"]
            scores[skill_id] = self._compute_similarity(query_embedding, positive_emb) * weight
        
        return scores


# 全局实例（懒加载）
_semantic_matcher: Optional[SemanticSkillMatcher] = None


def get_semantic_matcher() -> Optional[SemanticSkillMatcher]:
    """获取全局语义匹配器实例"""
    global _semantic_matcher
    if _semantic_matcher is None:
        _semantic_matcher = SemanticSkillMatcher()
    return _semantic_matcher


