"""
Skill Registry - 技能注册表

负责加载、管理和查询所有可用的 Skills。
从 YAML 配置文件和 skill.md 元数据中加载 Skill 定义。

Phase 4: 实现 0-token 意图匹配功能
"""
import logging
import os
import re
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import yaml

from ..models.skill import SkillDefinition
from ..config import settings

logger = logging.getLogger(__name__)


@dataclass
class SkillMatch:
    """技能匹配结果"""
    skill_id: str
    confidence: float
    parameters: Dict[str, Any]
    matched_keywords: List[str]


class SkillRegistry:
    """技能注册表 - 管理所有可用的 Skills"""
    
    def __init__(self, config_dir: Optional[str] = None):
        """
        初始化 Skill Registry
        
        Args:
            config_dir: Skills 配置文件目录（默认为 skills_config/）
        """
        if config_dir is None:
            # 默认配置目录在项目根目录的 skills_config/
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            config_dir = os.path.join(base_dir, "skills_config")
            self.skills_metadata_dir = os.path.join(base_dir, "skills")
        else:
            self.skills_metadata_dir = os.path.join(os.path.dirname(config_dir), "skills")
        
        self.config_dir = config_dir
        self._skills: Dict[str, SkillDefinition] = {}
        self._intent_map: Dict[str, List[str]] = {}  # intent -> [skill_ids]
        
        # 🆕 Phase 4: 加载 skill.md 元数据
        self._skill_metadata: Dict[str, Dict[str, Any]] = {}  # skill_id -> metadata
        
        # 加载所有 skills
        self._load_skills()
        
        # 🆕 加载 skill.md 元数据（用于 0-token 匹配）
        self._load_skill_metadata()
        
        logger.info(f"✅ SkillRegistry initialized with {len(self._skills)} skills ({len(self._skill_metadata)} with metadata)")
    
    def _load_skills(self):
        """从配置目录加载所有 Skill 定义"""
        if not os.path.exists(self.config_dir):
            logger.warning(f"Skills config directory not found: {self.config_dir}")
            return
        
        yaml_files = [f for f in os.listdir(self.config_dir) if f.endswith('.yaml') or f.endswith('.yml')]
        
        for filename in yaml_files:
            filepath = os.path.join(self.config_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                
                # 使用 Pydantic 模型验证
                skill_def = SkillDefinition(**config)
                
                # 🆕 保存原始配置
                skill_def.raw_config = config
                
                # 注册 skill
                self._skills[skill_def.id] = skill_def
                
                # 建立 intent 映射
                for intent_tag in skill_def.intent_tags:
                    if intent_tag not in self._intent_map:
                        self._intent_map[intent_tag] = []
                    self._intent_map[intent_tag].append(skill_def.id)
                
                logger.info(f"✅ Loaded skill: {skill_def.id} ({skill_def.display_name})")
            
            except Exception as e:
                logger.error(f"❌ Failed to load skill from {filename}: {e}")
    
    def get_skill(self, skill_id: str) -> Optional[SkillDefinition]:
        """
        根据 ID 获取 Skill 定义
        
        Args:
            skill_id: Skill ID
        
        Returns:
            SkillDefinition 或 None（如果不存在）
        """
        return self._skills.get(skill_id)
    
    def get_skills_by_intent(self, intent: str) -> List[SkillDefinition]:
        """
        根据意图获取匹配的 Skills
        
        Args:
            intent: 用户意图标签
        
        Returns:
            匹配的 Skill 定义列表
        """
        skill_ids = self._intent_map.get(intent, [])
        return [self._skills[sid] for sid in skill_ids if sid in self._skills]
    
    def list_all_skills(self) -> List[SkillDefinition]:
        """
        列出所有已注册的 Skills
        
        Returns:
            所有 Skill 定义的列表
        """
        return list(self._skills.values())
    
    def get_skill_ids(self) -> List[str]:
        """
        获取所有 Skill ID
        
        Returns:
            Skill ID 列表
        """
        return list(self._skills.keys())
    
    def get_all_intents(self) -> List[str]:
        """
        获取所有支持的意图标签
        
        Returns:
            意图标签列表
        """
        return list(self._intent_map.keys())
    
    def validate_skill_dependencies(self, skill_id: str) -> bool:
        """
        验证 Skill 的依赖是否都已注册
        
        Args:
            skill_id: Skill ID
        
        Returns:
            True 如果所有依赖都满足，否则 False
        """
        skill = self.get_skill(skill_id)
        if not skill:
            return False
        
        for dep_id in skill.dependencies:
            if dep_id not in self._skills:
                logger.warning(f"⚠️  Skill {skill_id} depends on {dep_id}, but it's not registered")
                return False
        
        return True
    
    def get_composable_skills(self) -> List[SkillDefinition]:
        """
        获取所有可组合的 Skills
        
        Returns:
            可组合的 Skill 列表
        """
        return [skill for skill in self._skills.values() if skill.composable]
    
    # ==================== Phase 4: 0-Token Matching ====================
    
    def _load_skill_metadata(self):
        """
        加载所有 skill.md 元数据文件
        用于 0-token 意图匹配
        """
        if not os.path.exists(self.skills_metadata_dir):
            logger.warning(f"Skills metadata directory not found: {self.skills_metadata_dir}")
            return
        
        for skill_dir in os.listdir(self.skills_metadata_dir):
            skill_path = os.path.join(self.skills_metadata_dir, skill_dir)
            if not os.path.isdir(skill_path):
                continue
            
            skill_md_path = os.path.join(skill_path, "skill.md")
            if not os.path.exists(skill_md_path):
                logger.debug(f"No skill.md found for {skill_dir}")
                continue
            
            try:
                metadata = self._parse_skill_md(skill_md_path)
                skill_id = metadata.get("id", skill_dir)
                self._skill_metadata[skill_id] = metadata
                logger.info(f"✅ Loaded metadata for: {skill_id}")
            except Exception as e:
                logger.error(f"❌ Failed to load metadata from {skill_md_path}: {e}")
    
    def _parse_skill_md(self, filepath: str) -> Dict[str, Any]:
        """
        解析 skill.md 文件，提取意图触发规则
        
        Returns:
            metadata dict with:
                - id: skill_id
                - primary_keywords: List[str]
                - quantity_patterns: List[str]
                - topic_patterns: List[str]
                - context_patterns: List[str]
        """
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        metadata = {}
        
        # 提取 Skill ID
        id_match = re.search(r'\*\*技能ID\*\*:\s*`(.+?)`', content)
        if id_match:
            metadata['id'] = id_match.group(1)
        
        # 提取 Primary Keywords
        keywords_section = re.search(
            r'### Primary Keywords.*?```\n(.*?)\n```',
            content,
            re.DOTALL
        )
        if keywords_section:
            keywords_text = keywords_section.group(1).strip()
            # 分割并清理关键词（支持逗号分隔）
            keywords = [kw.strip() for kw in re.split(r'[,，\s]+', keywords_text) if kw.strip()]
            metadata['primary_keywords'] = keywords
        else:
            metadata['primary_keywords'] = []
        
        # 提取 Quantity Patterns
        quantity_section = re.search(
            r'### Quantity Patterns.*?```(?:regex)?\n(.*?)\n```',
            content,
            re.DOTALL
        )
        if quantity_section:
            patterns_text = quantity_section.group(1).strip()
            patterns = [p.strip() for p in patterns_text.split('\n') if p.strip() and not p.strip().startswith('_N/A')]
            metadata['quantity_patterns'] = patterns
        else:
            metadata['quantity_patterns'] = []
        
        # 提取 Topic Patterns
        topic_section = re.search(
            r'### Topic Patterns.*?```(?:regex)?\n(.*?)\n```',
            content,
            re.DOTALL
        )
        if topic_section:
            patterns_text = topic_section.group(1).strip()
            patterns = [p.strip() for p in patterns_text.split('\n') if p.strip()]
            metadata['topic_patterns'] = patterns
        else:
            metadata['topic_patterns'] = []
        
        # 提取 Context Patterns
        context_section = re.search(
            r'### Context Patterns.*?```\n(.*?)\n```',
            content,
            re.DOTALL
        )
        if context_section:
            patterns_text = context_section.group(1).strip()
            patterns = [p.strip() for p in patterns_text.split('\n') if p.strip()]
            metadata['context_patterns'] = patterns
        else:
            metadata['context_patterns'] = []
        
        return metadata
    
    def match_message(
        self, 
        message: str, 
        current_topic: Optional[str] = None
    ) -> Optional[SkillMatch]:
        """
        匹配用户消息到技能（0 tokens）
        
        核心方法：实现 Phase 4 的 0-token 意图识别
        
        Args:
            message: 用户消息
            current_topic: 当前对话主题（从 session_context 获取）
        
        Returns:
            SkillMatch 或 None（未匹配）
        """
        if not self._skill_metadata:
            logger.warning("⚠️ No skill metadata loaded, falling back to LLM")
            return None
        
        # 🆕 Phase 4.1: 先检测混合意图
        mixed_match = self._detect_mixed_intent(message, current_topic)
        if mixed_match:
            logger.info(f"🔀 Detected mixed intent, matched to: {mixed_match.skill_id}")
            return mixed_match
        
        best_match: Optional[SkillMatch] = None
        best_confidence = 0.0
        
        # 遍历所有技能，计算匹配度
        for skill_id, metadata in self._skill_metadata.items():
            # 检查主要关键词
            matched_keywords = self._check_keywords(message, metadata.get('primary_keywords', []))
            if not matched_keywords:
                continue  # 没有匹配关键词，跳过
            
            # 提取参数（传递 current_topic）
            parameters = self._extract_parameters(message, metadata, skill_id, current_topic)
            
            # 计算置信度
            confidence = self._calculate_confidence(
                message,
                metadata,
                matched_keywords,
                parameters
            )
            
            # 更新最佳匹配
            if confidence > best_confidence:
                best_confidence = confidence
                best_match = SkillMatch(
                    skill_id=skill_id,
                    confidence=confidence,
                    parameters=parameters,
                    matched_keywords=matched_keywords
                )
        
        # 只返回置信度 >= 0.7 的匹配
        if best_match and best_match.confidence >= 0.7:
            logger.info(f"✅ Matched skill: {best_match.skill_id} (confidence: {best_match.confidence:.2f})")
            return best_match
        
        logger.debug(f"⚠️ No confident match found (best: {best_confidence:.2f})")
        return None
    
    def _check_keywords(self, message: str, keywords: List[str]) -> List[str]:
        """检查消息中是否包含关键词"""
        message_lower = message.lower()
        matched = []
        for keyword in keywords:
            if keyword.lower() in message_lower:
                matched.append(keyword)
        return matched
    
    def _extract_parameters(
        self,
        message: str,
        metadata: Dict[str, Any],
        skill_id: str,
        current_topic: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        从消息中提取参数
        
        Args:
            message: 用户消息
            metadata: 技能元数据
            skill_id: 技能 ID
            current_topic: 当前对话主题（从 session_context）
        
        Returns:
            parameters dict (topic, quantity, use_last_artifact, etc.)
        """
        params = {}
        
        # 1. 提取数量参数 - 支持阿拉伯数字和中文数字
        # 中文数字映射
        chinese_numbers = {
            '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
            '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
            '两': 2
        }
        
        quantity_value = None
        
        # 优先匹配阿拉伯数字
        arabic_match = re.search(r'(\d+)\s*[道个张份题卡]', message)
        if arabic_match:
            quantity_value = int(arabic_match.group(1))
        else:
            # 匹配中文数字
            chinese_match = re.search(r'([一二三四五六七八九十两])\s*[道个张份题卡]', message)
            if chinese_match:
                chinese_char = chinese_match.group(1)
                quantity_value = chinese_numbers.get(chinese_char)
        
        if quantity_value:
            # 根据 skill_id 设置正确的参数名
            if skill_id == 'quiz_skill':
                params['num_questions'] = quantity_value
            elif skill_id == 'flashcard_skill':
                params['num_cards'] = quantity_value
            elif skill_id == 'learning_plan_skill':
                # 学习包可能包含多个数量参数
                if '闪卡' in message or '卡片' in message:
                    params['flashcard_quantity'] = quantity_value
                elif '题' in message:
                    params['quiz_quantity'] = quantity_value
            
            logger.debug(f"📊 Extracted quantity: {quantity_value}")
        
        # 2. 提取主题
        topic = self._extract_topic(message, metadata)
        
        # 🔥 如果消息中没有明确主题，但有 current_topic，使用它
        if not topic and current_topic:
            topic = current_topic
            logger.info(f"📚 Using current_topic from context: {topic}")
        
        if topic:
            params['topic'] = topic
            # 对于 explain_skill，topic 应该设置为 concept_name
            if skill_id == 'explain_skill':
                params['concept_name'] = topic
        
        # 3. 检测上下文引用 - 使用简单的关键词检测
        context_keywords = ['根据', '基于', '刚才', '这些', '这道', '上面', '第一', '第二', '第三', '第', '再来', '再给']
        if any(kw in message for kw in context_keywords):
            params['use_last_artifact'] = True
            logger.debug(f"🔗 Detected context reference")
        
        return params
    
    def _extract_topic(self, message: str, metadata: Dict[str, Any]) -> Optional[str]:
        """从消息中提取主题 - 使用简单直接的方法"""
        
        # 优化的主题提取模式（按优先级排序）
        topic_patterns = [
            # 🆕 最高优先级：明确的"XXX的解释/说明"结构
            r'(.+?)的(?:解释|讲解|说明|介绍|定义)',          # "二战起因的解释"
            
            # 高优先级：明确的主题词
            r'什么是(.+?)(?:[，。！？]|$)',              # "什么是光合作用"
            r'解释(?:一?下?)?(.+?)(?:[，。！？]|$)',     # "解释光合作用"
            r'讲解(?:一?下?)?(.+?)(?:[，。！？]|$)',     # "讲解光合作用"
            r'理解(?:一?下?)?(.+?)(?:[，。！？]|$)',     # "理解光合作用"
            r'了解(?:一?下?)?(.+?)(?:[，。！？]|$)',     # "了解光合作用"
            r'学习(?:一?下?)?(.+?)(?:[，。！？]|$)',     # "学习光合作用"
            r'关于(.+?)的',                             # "关于光合作用的"
            
            # 中优先级：带数量词的模式
            r'(?:\d+|[一二三四五六七八九十两])[道个张份题卡](.+?)(?:的)?[题笔闪导卡图记]',  # "3道光合作用的题"
            
            # 低优先级：宽松匹配
            r'(.+?)[的]?[题笔闪导卡图记]',             # "光合作用的题"
        ]
        
        for pattern in topic_patterns:
            match = re.search(pattern, message)
            if match:
                # 提取第一个捕获组
                topic = match.group(1).strip()
                # 清理主题
                topic = self._clean_topic(topic)
                
                # 验证提取的主题有效性
                # 排除一些明显无效的结果
                invalid_topics = [
                    '我需要', '帮我', '给我', '我要', '再来', '再给', '再出', '出',
                    '选择', '判断', '填空', '简答',  # 题目类型，不是主题
                    '学习', '复习', '练习', '测试',  # 动作词，不是主题
                ]
                if topic and len(topic) >= 2 and topic not in invalid_topics:
                    logger.debug(f"📝 Extracted topic: {topic} (pattern: {pattern})")
                    return topic
        
        return None
    
    def _clean_topic(self, topic: str) -> str:
        """清理主题文本，移除填充词"""
        # 移除常见填充词和上下文引用词
        filler_words = [
            "的", "了", "吗", "呢", "啊", "吧",
            "给我", "帮我", "我要", "我需要", "生成", "创建",
            "出", "做", "写",
            "关于", "有关",
            "根据", "刚刚", "刚才", "上面", "这个", "那个",
            " 思维", " 导图", " 笔记", " 题目", " 闪卡", " 卡片"  # 技能相关的词
        ]
        for filler in filler_words:
            topic = topic.replace(filler, " ")
        
        # 移除数量词（阿拉伯数字 + 中文数字）
        topic = re.sub(r'\d+\s*[个道张份题卡]', '', topic)
        topic = re.sub(r'[一二三四五六七八九十两]\s*[个道张份题卡]', '', topic)
        
        # 移除多余空格
        topic = ' '.join(topic.split())
        
        return topic.strip()
    
    def _calculate_confidence(
        self,
        message: str,
        metadata: Dict[str, Any],
        matched_keywords: List[str],
        parameters: Dict[str, Any]
    ) -> float:
        """
        计算匹配置信度
        
        Returns:
            confidence score (0.0 - 1.0)
        """
        confidence = 0.5  # 基础分
        
        # 1. 关键词匹配（+0.3）
        if matched_keywords:
            confidence += 0.3
        
        # 2. 有明确主题（+0.15）
        if parameters.get('topic') or parameters.get('concept_name'):
            confidence += 0.15
        
        # 3. 有数量参数（+0.05）
        if any(k in parameters for k in ['num_questions', 'num_cards', 'flashcard_quantity', 'quiz_quantity']):
            confidence += 0.05
        
        # 4. 简短明确的请求（+0.1）
        if len(message) < 20 and matched_keywords:
            confidence += 0.05
        
        return min(confidence, 1.0)  # 最大 1.0
    
    def _detect_mixed_intent(
        self, 
        message: str, 
        current_topic: Optional[str] = None
    ) -> Optional[SkillMatch]:
        """
        检测混合意图（多个技能关键词）
        
        如果检测到多个技能的关键词，返回 learning_plan_skill
        
        Args:
            message: 用户消息
            current_topic: 当前对话主题（从 session_context）
        
        Returns:
            SkillMatch for learning_plan_skill or None
        """
        # 定义各技能的关键词集合
        skill_keywords = {
            'explain': ['解释', '讲解', '说明', '理解', '了解', '学习', '什么是', 'explain', 'what is', 'understand'],
            'quiz': ['题', '题目', '练习', '测试', 'quiz', 'test', 'question'],
            'flashcard': ['闪卡', '卡片', '记忆卡', 'flashcard', 'card'],
            'notes': ['笔记', '总结', '归纳', 'notes', 'summary'],
            'mindmap': ['思维导图', '导图', '知识图', 'mindmap', 'mind map', 'concept map'],
            'learning_bundle': ['学习包', '学习资料', '学习材料', '完整', '学习套装', '学习计划', 'learning bundle', 'study package']
        }
        
        # 检测消息中包含哪些技能的关键词
        matched_skills = []
        for skill_name, keywords in skill_keywords.items():
            if any(kw in message for kw in keywords):
                matched_skills.append(skill_name)
        
        # 🔥 特殊情况：如果明确提到 learning_bundle 关键词，直接返回 learning_plan_skill
        if 'learning_bundle' in matched_skills:
            logger.info(f"📦 Detected explicit learning_bundle keywords")
            
            # 提取参数
            params = {}
            topic = self._extract_topic(message, {})
            if not topic and current_topic:
                topic = current_topic
            if topic:
                params['topic'] = topic
            
            # 返回 learning_plan_skill 匹配
            return SkillMatch(
                skill_id='learning_plan_skill',
                confidence=0.95,  # 高置信度
                parameters=params,
                matched_keywords=['learning_bundle']
            )
        
        # 如果检测到 2 个或以上的技能关键词（不包括 learning_bundle），判定为混合意图
        # 过滤掉 learning_bundle，因为它已经在上面处理了
        matched_skills_filtered = [s for s in matched_skills if s != 'learning_bundle']
        if len(matched_skills_filtered) >= 2:
            logger.info(f"🔀 Mixed intent detected: {matched_skills_filtered}")
            
            # 提取参数
            params = {}
            
            # 🆕 Phase 4.2: 添加 required_steps，让 Plan Skill 知道要执行哪些步骤
            step_mapping = {
                'explain': 'explain',
                'quiz': 'quiz',
                'flashcard': 'flashcard',
                'notes': 'notes',
                'mindmap': 'mindmap'
            }
            params['required_steps'] = [step_mapping[skill] for skill in matched_skills_filtered if skill in step_mapping]
            logger.info(f"📋 Required steps: {params['required_steps']}")
            
            # 提取主题 - 使用更智能的方法
            # 尝试从常见模式中提取主题
            topic = None
            topic_patterns = [
                r'解释(?:一?下?)?(.+?)(?:，|并|然后|再)',       # "解释牛顿第二定律，并..."
                r'讲解(?:一?下?)?(.+?)(?:，|并|然后|再)',       # "讲解牛顿第二定律，并..."
                r'理解(?:一?下?)?(.+?)(?:，|并|然后|再)',       # "理解牛顿第二定律，并..."
                r'了解(?:一?下?)?(.+?)(?:，|并|然后|再)',       # "了解牛顿第二定律，并..."
                r'学习(?:一?下?)?(.+?)(?:，|并|然后|再)',       # "学习牛顿第二定律，并..."
                r'关于(.+?)(?:的|，)',                         # "关于牛顿第二定律的..."
                r'(.+?)(?:的|，)(?:讲解|解释|理解|题目|闪卡)',  # "牛顿第二定律的讲解..."
            ]
            
            for pattern in topic_patterns:
                match = re.search(pattern, message)
                if match:
                    topic = match.group(1).strip()
                    topic = self._clean_topic(topic)
                    if len(topic) >= 2:
                        params['topic'] = topic
                        break
            
            # 🔥 如果没有提取到主题，使用 current_topic
            if not topic and current_topic:
                topic = current_topic
                params['topic'] = topic
                logger.info(f"📚 Using current_topic for mixed intent: {topic}")
            
            # 提取数量参数
            quantity_match = re.search(r'(\d+)\s*[道个张份]', message)
            if quantity_match:
                quantity_value = int(quantity_match.group(1))
                # 根据消息中的关键词判断数量属于哪个技能
                if 'quiz' in matched_skills_filtered:
                    params['quiz_quantity'] = quantity_value
                if 'flashcard' in matched_skills_filtered:
                    params['flashcard_quantity'] = quantity_value
            
            # 返回 learning_plan_skill 匹配
            return SkillMatch(
                skill_id='learning_plan_skill',
                confidence=0.90,  # 高置信度
                parameters=params,
                matched_keywords=matched_skills_filtered
            )
        
        return None
    
    def reload(self):
        """重新加载所有 Skills（用于热更新）"""
        logger.info("🔄 Reloading skills...")
        self._skills.clear()
        self._intent_map.clear()
        self._skill_metadata.clear()
        self._load_skills()
        self._load_skill_metadata()
        logger.info(f"✅ Reloaded {len(self._skills)} skills ({len(self._skill_metadata)} with metadata)")


# 全局单例
_registry_instance: Optional[SkillRegistry] = None


def get_skill_registry() -> SkillRegistry:
    """
    获取全局 SkillRegistry 实例（单例模式）
    
    Returns:
        SkillRegistry 实例
    """
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = SkillRegistry()
    return _registry_instance

