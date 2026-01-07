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
        从 YAML 配置加载 skill 元数据（primary_keywords）
        用于 0-token 意图匹配
        
        🆕 优先从 YAML 文件的 primary_keywords 字段读取
        """
        for skill_id, skill_def in self._skills.items():
            metadata = {
                'id': skill_id,
                'primary_keywords': [],
                'quantity_patterns': [],
                'topic_patterns': [],
                'context_patterns': []
            }
            
            # 🔥 从 YAML 配置读取 primary_keywords
            if hasattr(skill_def, 'raw_config') and skill_def.raw_config:
                yaml_keywords = skill_def.raw_config.get('primary_keywords', [])
                if yaml_keywords:
                    metadata['primary_keywords'] = yaml_keywords
                    logger.debug(f"📝 Loaded {len(yaml_keywords)} keywords for {skill_id} from YAML")
            
            # 如果 YAML 没有 primary_keywords，使用硬编码的默认值
            if not metadata['primary_keywords']:
                metadata['primary_keywords'] = self._get_default_keywords(skill_id)
                logger.debug(f"📝 Using default keywords for {skill_id}")
            
            self._skill_metadata[skill_id] = metadata
            logger.info(f"✅ Loaded metadata for: {skill_id}")
    
    def _get_default_keywords(self, skill_id: str) -> List[str]:
        """
        获取 skill 的默认关键词（YAML 未配置时使用）
        
        🔥 关键词选择原则：
        1. 只包含【明确的】skill 触发词
        2. 排除日常对话常用词（如"学习"、"什么是"）
        3. 这些宽泛词汇应由 is_inquiry_message + LLM fallback 处理
        """
        default_keywords = {
            # 🔥 explain_skill: 移除 "学习"、"什么是"、"教我"、"告诉我" 等宽泛词
            # 这些词在对话中太常见，应该让 LLM 判断是否是概念讲解请求
            'explain_skill': ['解释一下', '详细讲解', '详细解释', '深入讲解', '系统讲解', '科普一下', 
                             '讲讲', '讲一下', '简单讲讲', '简单讲解', '给我讲讲', '帮我讲讲',
                             'explain', 'explain in detail'],
            
            # 🔥 quiz_skill: 移除单字 "题"（太宽泛，如"问题"、"话题"）
            # 保留明确的出题触发词
            'quiz_skill': ['道题', '出题', '做题', '刷题', '练习题', '测验', '测试题', '考题', 
                          '习题', '试题', '选择题', '判断题', '填空题', '简答题',  # 🆕 添加题型
                          'quiz', 'test questions', 'exam questions'],
            
            # flashcard_skill: 这些词比较明确
            'flashcard_skill': ['闪卡', '记忆卡', '抽认卡', '背诵卡', '复习卡', '单词卡', '卡片',
                               '生成闪卡', '做闪卡', '制作卡', 
                               'flashcard', 'flash card', 'anki'],
            
            # notes_skill: 移除 "总结"（太宽泛）
            'notes_skill': ['做笔记', '整理笔记', '学习笔记', '课堂笔记', 'notes', 'take notes'],
            
            # mindmap_skill: 这些词比较明确
            'mindmap_skill': ['思维导图', '知识导图', '脑图', '知识图谱', '概念图', '结构图', 
                             'mindmap', 'mind map'],
            
            # learning_plan_skill: 学习计划/规划
            'learning_plan_skill': ['学习计划', '学习规划', '复习计划', '学习方案', '学习路线',
                                   '制定计划', '制定方案', '规划一下', '安排一下学习',
                                   '帮我制定', '给我制定', '帮我规划', '给我规划',
                                   'learning plan', 'study plan', 'make a plan'],
            
            # learning_bundle_skill: 学习包（综合）
            'learning_bundle_skill': ['学习包', '学习套装', '学习套餐', '全套资料', '学习材料包',
                                     'learning bundle', 'study pack', 'learning package']
        }
        return default_keywords.get(skill_id, [])
    
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
    
    def is_inquiry_message(self, message: str) -> bool:
        """
        🆕 检测是否为"询问类"或"对话类"消息（应该返回纯 Chat 而非触发技能）
        
        对话类消息特征：
        - 问候/闲聊（"你好"、"谢谢"）
        - 简单追问（"讲讲"、"继续"、"然后呢"）
        - 学习讨论（"我想学习X"、"教我Y"）- 不是明确的"出题/生成闪卡"
        
        询问类消息特征：
        - 询问内容/描述（"这是什么"、"讲了什么"）
        - 请求解答/解释（"帮我解答"、"怎么做"）
        - 比较/分析（"比较一下"、"有什么不同"）
        - 追问/澄清（"不太懂"、"能详细说吗"）
        
        这些消息应该由 LLM 直接回答，而不是生成 Quiz/Flashcard
        """
        message_lower = message.lower()
        
        # 🆕 Step 1: 检测是否有明确的 skill 触发词（如果有，不算询问类）
        explicit_skill_triggers = [
            # Quiz 明确触发
            r'\d+\s*道题',        # "三道题"、"5道题"
            r'[一二三四五六七八九十两]\s*道题',
            r'出\s*\d*\s*[道个]?题',  # "出题"、"出三道题"
            r'做\s*\d*\s*[道个]?题',  # "做题"
            r'刷题',
            r'练习题',
            r'测验',
            r'考[试题]',
            
            # Flashcard 明确触发
            r'\d+\s*张.*?[闪卡片]',   # "三张闪卡"
            r'[一二三四五六七八九十两]\s*张.*?[闪卡片]',
            r'(做|生成|制作|创建).*?闪卡',
            r'(做|生成|制作|创建).*?卡片',
            
            # Mindmap 明确触发
            r'(画|生成|制作|做).*?(思维导图|导图|脑图)',
            
            # Notes 明确触发
            r'(做|整理|写).*?笔记',
            r'(总结|归纳).*?(要点|内容)',
            
            # Learning Bundle 明确触发
            r'学习包',
            r'学习套[装餐]',
            r'(给我|来个).*?全套',
            
            # 🆕 Plan 明确触发
            r'制定.*?(计划|方案|规划)',  # "制定学习计划"
            r'规划.*(学习|复习|备考)',  # "规划一下学习"
            r'(学习|复习|备考).*(计划|方案|规划|路线)',  # "学习计划"
        ]
        
        for pattern in explicit_skill_triggers:
            if re.search(pattern, message_lower, re.IGNORECASE):
                logger.info(f"🎯 Explicit skill trigger detected: '{pattern}', NOT inquiry")
                return False  # 有明确触发词，不是询问类
        
        # 🆕 Step 2: 检测对话/询问类模式
        inquiry_patterns = [
            # 🆕 问候/闲聊（高优先级）
            r'^(你好|您好|hi|hello|hey)',
            r'(谢谢|感谢|多谢|thanks)',
            r'^(好的|行|可以|没问题|OK)',
            
            # 🆕 简单学习请求（不是生成类）- 移除 ^ 限制
            r'我想(学习?|了解|知道)',
            r'我们(来|一起)?(学习|了解|看看)',  # "我们来学习X"、"我们一起学习"
            r'(教我|告诉我)',
            r'(先|再)?(讲讲|说说|聊聊)',  # 匹配 "先讲讲"、"讲讲"
            r'讲一?下',  # "讲下"、"讲一下"
            
            # 🆕 追问/继续（移除 ^ 限制）
            r'(继续|然后呢|接着|还有呢)',
            r'(再|继续)(讲|说|解释)',
            r'(能|可以).*?(举.*?例|详细.*?说)',
            r'能.*?吗[？?]?$',  # "能举个例子吗"
            
            # 询问内容/描述
            r'(这|那|文件|图片|材料)[^的]*?(讲|说|是|描述|介绍)[的了]?(什么|内容)',
            r'(什么|哪些?)[^的]*?(内容|主题|知识点)',
            
            # 请求解答/解释（不是"帮我出题"）
            r'帮我(解答|解决|做|算|算出)',
            r'(怎么|如何)(做|解|算|求|证明|用|使用)',
            r'(这道|那道)题[^出生成]*?(怎么|如何|答案)',
            r'怎么用',  # "这个公式怎么用"
            
            # 比较/分析
            r'比较一下|对比一下|有什么不同|有什么区别|有什么联系|有什么关系|有什么影响|有什么作用',
            r'(这|那)(两个?|几个?|些)[^出生成]*?(比较|不同|区别|联系)',
            
            # 追问/澄清
            r'(不太?|没太?|还是不)(懂|理解|明白|清楚)',  # "不太懂"、"没太懂"
            r'能[^出生成]*?(详细|简单|再)[^出生成]*?(说|讲|解释)',
            r'(再|更)(详细|简单|具体)一点',
            r'举个?(例子|例|栗子)',
            
            # 请求提示
            r'给[我一]?[些点个]?(提示|线索|思路|方向)',
            r'(有|给)[^出生成]*?(提示|线索|思路)',
            
            # 🆕 概念询问（"什么是X" 但不是 "什么是X，出三道题"）
            r'^什么是[^，,。.？?!！]*$',  # 单独的"什么是X"
            r'^.*?是什么[？?]?$',  # "X是什么？"
            r'是.{0,10}呢[？?]?$',  # "那细胞呼吸是什么呢"
            
            # 🆕 简单事实性问题（不需要详细讲解）
            r'.{2,10}是(哪|什么|多少|几).{0,2}(年|时候|个|种)',  # "X是哪一年"、"X是什么时候"
            r'(有哪些|有几个|有多少|哪些)',  # "有哪些国家"、"哪些国家参战"
            r'.{2,10}(开始|结束|发生)(于|在|的)',  # "X开始于"、"X发生在"
            
            # 🆕 简短追问（"X呢"、"那Y呢"）
            r'^.{2,15}呢[？?]?$',  # "第三定律呢"、"化学键呢"、"那个呢"
            r'^那.{1,10}呢[？?]?$',  # "那细胞呼吸呢"
            
            # 🆕 回忆/检索类（不是出题！）
            r'回到.*(开始|最初|最早|之前)',  # "回到最开始"
            r'我们(聊|讲|说|学|讨论)了(什么|哪些|几个)',  # "我们聊了什么"
            r'(今天|刚才|之前).*(学|聊|讲|讨论)了.*(什么|哪些|几个|内容)',  # "今天学了什么"
            r'(一共|总共).*(学|聊|讲)了.*(几|多少|什么)',  # "一共学了几个主题"
            r'(文档|文件|材料|图片).*(提到|说|讲|介绍|描述)了?.*(什么|哪些|内容)',  # "文档中提到了什么"
            r'(文档|文件).*(中|里).*(重要|主要|关键)',  # "文档中提到了哪些重要事件"
            
            # 🆕 总结/回顾类（区分于 notes skill 的"总结知识点"）
            r'(帮我|给我)?做.*(完整|全面).*总结',  # "做一个完整的学习总结"
            r'(回顾|复盘).*(今天|刚才|之前)',  # "回顾一下今天"
            
            # 🆕 常见错误/问题讨论类（快捷按钮 common_mistakes）
            # "学生通常在这类问题中犯什么错误" - 这是讨论，不是出题
            r'(这类|这种|这个|这些|此类)问题',  # "这类问题"、"这个问题"
            r'犯(什么|哪些)(错误?|错|mistake)',  # "犯什么错误"
            r'(常见|容易|经常|通常).*(错误|错|mistake|error)',  # "常见错误"
            r'(错误|误区|陷阱|坑).*(有哪些|是什么)',  # "常见误区有哪些"
            r'(学生|同学|大家|人们?).*(犯|出).*(错|错误)',  # "学生常犯的错误"
            r'common.*(mistake|error)',  # "common mistakes"
            r'(mistake|error).*(make|do)',  # "mistakes students make"
        ]
        
        for pattern in inquiry_patterns:
            if re.search(pattern, message_lower, re.IGNORECASE):
                logger.info(f"🔍 Detected inquiry/conversation message: pattern='{pattern}'")
                return True
        
        return False
    
    def match_message(
        self, 
        message: str, 
        current_topic: Optional[str] = None,
        session_topics: Optional[List[str]] = None,
        has_files: bool = False
    ) -> Optional[SkillMatch]:
        """
        匹配用户消息到技能（0 tokens）
        
        核心方法：实现 Phase 4 的 0-token 意图识别
        
        匹配优先级：
        1. Plan Skill 特殊模式（高优先级）
        2. 🆕 语义匹配（Embedding，高置信度时使用）
        3. 询问类消息检测
        4. 关键词匹配（原有逻辑）
        
        Args:
            message: 用户消息
            current_topic: 当前对话主题（从 session_context 获取）
            session_topics: 历史topics列表（从 session_context）
            has_files: 是否有文件附件
        
        Returns:
            SkillMatch 或 None（未匹配）
        """
        if not self._skill_metadata:
            logger.warning("⚠️ No skill metadata loaded, falling back to LLM")
            return None
        
        # 🆕 Step 0: 先检查 Plan Skill 的特殊模式（高优先级）
        # "帮我制定一个学习物理的计划" 这种模式需要特殊处理
        plan_match = self._check_plan_skill_patterns(message, current_topic)
        if plan_match:
            logger.info(f"📋 Plan skill pattern matched: {plan_match.matched_keywords}")
            return plan_match
        
        # 🆕 Step 0.5: 尝试语义匹配（Embedding）
        # 高置信度时直接使用，避免关键词误匹配
        semantic_match = self._try_semantic_match(message, current_topic)
        if semantic_match:
            return semantic_match
        
        # 🆕 Step 1: 检测询问类/对话类消息
        # 对话类消息应该直接返回 "other" intent，不走 LLM fallback
        is_inquiry = self.is_inquiry_message(message)
        if is_inquiry:
            # 🔥 关键修复：对话类消息直接返回 "other" skill，不走 LLM
            # 这样可以避免 LLM 错误地将对话识别为 quiz/flashcard
            # 🆕 即使有文件附件（如"帮我解答这道几何题"），也应该返回 other 让 LLM 处理
            logger.info(f"💬 Conversation message detected (has_files={has_files}), returning 'other' skill directly")
            return SkillMatch(
                skill_id="other",  # 直接标记为对话
                confidence=0.95,   # 高置信度
                parameters={
                    'topic': current_topic,  # 继承当前主题
                    'is_conversation': True,
                    'has_files': has_files  # 🆕 传递文件标记
                },
                matched_keywords=['conversation']
            )
        
        # 🆕 Step 0.5: 先清理引用模式，避免把引用当作关键词
        message_for_matching = self._clean_reference_patterns(message)
        
        # 🆕 Phase 4.1: 先检测混合意图（使用清理后的消息）
        mixed_match = self._detect_mixed_intent(message, current_topic)
        if mixed_match:
            logger.info(f"🔀 Detected mixed intent, matched to: {mixed_match.skill_id}")
            return mixed_match
        
        best_match: Optional[SkillMatch] = None
        best_confidence = 0.0
        
        # 遍历所有技能，计算匹配度（使用清理后的消息）
        for skill_id, metadata in self._skill_metadata.items():
            # 检查主要关键词（使用清理后的消息）
            matched_keywords = self._check_keywords(message_for_matching, metadata.get('primary_keywords', []))
            if not matched_keywords:
                continue  # 没有匹配关键词，跳过
            
            # 提取参数（传递 current_topic 和 session_topics）
            parameters = self._extract_parameters(message, metadata, skill_id, current_topic, session_topics)
            
            # 🔥 如果参数中标记需要 clarification，立即返回
            if parameters.get('needs_clarification'):
                return SkillMatch(
                    skill_id="clarification_needed",
                    confidence=1.0,
                    parameters=parameters,
                    matched_keywords=['clarification']
                )
            
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
        
        # 🆕 询问类消息特殊处理：降低置信度，让 LLM fallback 进行意图分析
        is_inquiry = self.is_inquiry_message(message)
        if is_inquiry and best_match:
            # 询问类消息：强制降低置信度到 0.5，触发 LLM fallback
            original_confidence = best_match.confidence
            best_match = SkillMatch(
                skill_id=best_match.skill_id,
                confidence=min(0.5, best_match.confidence),  # 最高 0.5
                parameters=best_match.parameters,
                matched_keywords=best_match.matched_keywords
            )
            logger.info(f"📝 Inquiry message: lowered confidence {original_confidence:.2f} → {best_match.confidence:.2f}")
        
        # 只返回置信度 >= 0.7 的匹配
        if best_match and best_match.confidence >= 0.7:
            logger.info(f"✅ Matched skill: {best_match.skill_id} (confidence: {best_match.confidence:.2f})")
            return best_match
        
        # 返回低置信度匹配（让 Intent Router 决定是否使用 LLM fallback）
        if best_match and best_match.confidence > 0:
            logger.info(f"⚠️ Low confidence match: {best_match.skill_id} ({best_match.confidence:.2f}), suggesting LLM fallback")
            return best_match
        
        logger.debug(f"⚠️ No confident match found (best: {best_confidence:.2f})")
        return None
    
    def _try_semantic_match(
        self, 
        message: str, 
        current_topic: Optional[str] = None
    ) -> Optional[SkillMatch]:
        """
        🆕 尝试使用语义匹配（Embedding）
        
        使用 Sentence Transformer 进行语义相似度匹配。
        
        🔥 严格匹配策略（支持30+语言）：
        1. 只有在非常确定时才返回匹配结果
        2. 对于生成类技能（quiz/flashcard/explain等），需要更高置信度
        3. 不确定时返回 None，让 LLM 处理（作为 other 意图）
        
        Args:
            message: 用户消息
            current_topic: 当前主题
            
        Returns:
            SkillMatch 或 None（不确定时返回 None，交给 LLM 处理）
        """
        try:
            from .semantic_skill_matcher import get_semantic_matcher
            
            matcher = get_semantic_matcher()
            if matcher is None:
                return None
            
            # 🆕 使用更严格的阈值
            # - threshold=0.65: 基础阈值
            # - negative_threshold=0.6: 更容易排除
            # - confidence_gap=0.15: 要求明显差距
            semantic_result = matcher.match(
                message, 
                threshold=0.65, 
                negative_threshold=0.6,
                confidence_gap=0.15
            )
            
            if semantic_result is None:
                # 🆕 语义匹配不确定，返回 None 让后续逻辑处理
                logger.info(f"🧠 Semantic match: uncertain, deferring to other methods")
                return None
            
            # 将语义匹配结果转换为 SkillMatch
            skill_id = semantic_result.skill_id
            confidence = semantic_result.confidence
            
            # 技能 ID 映射
            skill_id_mapping = {
                "quiz": "quiz_skill",
                "flashcard": "flashcard_skill",
                "explain": "explain_skill",
                "notes": "notes_skill",
                "mindmap": "mindmap_skill",
                "learning_bundle": "learning_plan_skill",
                "other": "other",
            }
            
            mapped_skill_id = skill_id_mapping.get(skill_id, skill_id)
            
            # 🆕 更严格的置信度检查
            # 生成类技能需要更高置信度（0.80），other 可以稍低（0.70）
            generation_skills = {"quiz_skill", "flashcard_skill", "explain_skill", "notes_skill", "mindmap_skill", "learning_plan_skill"}
            
            if mapped_skill_id in generation_skills:
                # 🔥 生成类技能需要 0.80+ 的置信度
                if confidence >= 0.80:
                    logger.info(f"🧠 Semantic match (high confidence): {mapped_skill_id} ({confidence:.3f})")
                    return SkillMatch(
                        skill_id=mapped_skill_id,
                        confidence=confidence,
                        parameters={"topic": current_topic} if current_topic else {},
                        matched_keywords=["[semantic]"],
                    )
                else:
                    # 置信度不够，不使用语义匹配结果
                    logger.info(f"🧠 Semantic match (insufficient for generation): {mapped_skill_id} ({confidence:.3f}) < 0.80")
                    return None
            elif mapped_skill_id == "other":
                # 🆕 other 意图可以稍低置信度（0.65）- 降低阈值，让更多对话被正确识别
                if confidence >= 0.65:
                    logger.info(f"🧠 Semantic match: {mapped_skill_id} ({confidence:.3f})")
                    return SkillMatch(
                        skill_id=mapped_skill_id,
                        confidence=confidence,
                        parameters={},
                        matched_keywords=["[semantic]"],
                    )
            
            # 默认不返回匹配
            logger.info(f"🧠 Semantic match (deferred): {mapped_skill_id} ({confidence:.3f})")
            return None
            
        except ImportError:
            # sentence-transformers 未安装
            logger.debug("⚠️ Semantic matching disabled: sentence-transformers not installed")
            return None
        except Exception as e:
            logger.warning(f"⚠️ Semantic matching failed: {e}")
            return None
    
    def _check_plan_skill_patterns(
        self, 
        message: str, 
        current_topic: Optional[str] = None
    ) -> Optional[SkillMatch]:
        """
        🆕 检查 Plan Skill 的特殊模式
        
        处理 "帮我制定一个学习物理的计划" 这类分散关键词的情况
        """
        message_lower = message.lower()
        
        # Plan skill 的模式列表
        plan_patterns = [
            # "帮我制定一个...计划/方案/规划"
            r'(帮我|给我|请)?制定.{0,15}(计划|方案|规划|路线)',
            # "帮我规划一下..."
            r'(帮我|给我|请)?规划.{0,10}(学习|复习|备考)',
            # "做一个...学习计划"
            r'做.{0,10}(学习|复习|备考).{0,5}(计划|方案|规划)',
            # "如何规划..."
            r'(如何|怎么|怎样).{0,5}(规划|安排|制定).{0,10}(学习|复习|备考)',
            # "学习路线/路径"
            r'(学习|复习|备考).{0,5}(路线|路径|规划|安排)',
        ]
        
        for pattern in plan_patterns:
            match = re.search(pattern, message_lower)
            if match:
                logger.info(f"📋 Plan skill pattern matched: '{pattern}'")
                
                # 提取 topic
                topic = None
                # 尝试从消息中提取学科/主题
                topic_patterns = [
                    r'学习(.{2,10}?)的?(计划|方案|规划)',  # "学习物理的计划"
                    r'(物理|化学|数学|生物|历史|地理|英语|语文|编程|python)',
                    r'复习(.{2,10}?)的?(计划|方案)',  # "复习牛顿定律的计划"
                ]
                for tp in topic_patterns:
                    topic_match = re.search(tp, message_lower)
                    if topic_match:
                        topic = topic_match.group(1) if topic_match.lastindex else topic_match.group(0)
                        break
                
                if not topic:
                    topic = current_topic  # 使用当前主题
                
                return SkillMatch(
                    skill_id='learning_plan_skill',
                    confidence=0.95,
                    parameters={
                        'topic': topic,
                        'plan_type': 'learning_plan'
                    },
                    matched_keywords=['plan_pattern']
                )
        
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
        current_topic: Optional[str] = None,
        session_topics: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        从消息中提取参数
        
        Args:
            message: 用户消息
            metadata: 技能元数据
            skill_id: 技能 ID
            current_topic: 当前对话主题（从 session_context）
            session_topics: 历史topics列表（从 session_context）
        
        Returns:
            parameters dict (topic, quantity, use_last_artifact, etc.)
        """
        params = {}
        
        # 🔥 Step 0: 先清理引用模式，避免 "第一道题" 中的 "一道" 被错误提取为数量
        # 例如："根据第一道题，帮我出三张闪卡" → 清理后用于数量提取的消息是 "根据，帮我出三张闪卡"
        message_for_quantity = self._clean_reference_patterns(message)
        
        # 1. 提取数量参数 - 支持阿拉伯数字和中文数字
        # 中文数字映射
        chinese_numbers = {
            '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
            '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
            '两': 2
        }
        
        quantity_value = None
        
        # 优先匹配阿拉伯数字（使用清理后的消息）
        arabic_match = re.search(r'(\d+)\s*[道个张份题卡]', message_for_quantity)
        if arabic_match:
            quantity_value = int(arabic_match.group(1))
        else:
            # 匹配中文数字（使用清理后的消息）
            chinese_match = re.search(r'([一二三四五六七八九十两])\s*[道个张份题卡]', message_for_quantity)
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
        
        # 🔥 2. 检测多 topic 引用（如"刚刚两个topic的知识导图"）
        multi_topic_patterns = [
            r'(两个|2个|三个|3个|多个)[的]?(topic|主题)',
            r'(刚刚|刚才|前面|上面)[的]?(两个|2个|三个|3个|所有)[的]?(topic|主题)',
            r'(所有|全部)[的]?(topic|主题)',
        ]
        
        for pattern in multi_topic_patterns:
            if re.search(pattern, message):
                # 用户要求多个 topics
                if session_topics and len(session_topics) > 1:
                    # 提取最近的2-3个 topics
                    recent_topics = session_topics[-3:] if len(session_topics) >= 3 else session_topics
                    combined_topic = " + ".join(recent_topics)
                    params['topic'] = combined_topic
                    params['multi_topic'] = True
                    params['topic_list'] = recent_topics
                    logger.info(f"🔀 Detected multi-topic request: {recent_topics}")
                    return params
                else:
                    # 历史 topics 不足，需要 clarification
                    params['needs_clarification'] = True
                    params['clarification_reason'] = "multi_topic_insufficient"
                    logger.warning(f"⚠️  User requested multiple topics but session history insufficient")
                    return params
        
        # 3. 提取主题
        # 🆕 先清理引用模式，避免从引用中错误提取 topic
        message_for_topic = self._clean_reference_patterns(message)
        
        # 🔧 检查消息是否主要是引用（清理后几乎没剩什么内容）
        # 例如："把第二道题帮我详细解释一下" → "把帮我详细解释一下"
        # 这种情况下不应该从清理后的消息提取 topic，因为真正的 topic 在引用的 artifact 中
        cleaned_has_content = len(message_for_topic.replace('把', '').replace('帮我', '').replace('详细', '').replace('一下', '').strip()) > 3
        
        if cleaned_has_content:
            topic = self._extract_topic(message_for_topic, metadata)
        else:
            # 清理后几乎没有内容，说明这是一个纯引用请求，使用 current_topic
            topic = None
            logger.info(f"🔗 Reference-heavy message, skipping topic extraction from cleaned message")
        
        # 🔥 验证提取的 topic 是否有效（不是填充词、不是太短）
        if topic:
            invalid_topic_patterns = [
                '好', '嗯', '是', '行', '那', '可以', 'ok', 'OK',
                '好的', '是的', '行的', '那就', '那么', '可以的',
                '测验', '测试', '练习', '选择', '判断', '填空', '简答',  # 题目类型
                '学习', '复习', '预习',  # 动作词
            ]
            # 检查是否是无效 topic
            if topic.strip() in invalid_topic_patterns or len(topic.strip()) < 2:
                logger.info(f"⚠️ Extracted topic '{topic}' is invalid, falling back to current_topic")
                topic = None
        
        # 🔥 如果消息中没有明确主题，但有 current_topic，使用它
        if not topic and current_topic:
            topic = current_topic
            logger.info(f"📚 Using current_topic from context: {topic}")
        
        # 🔥 如果仍然没有 topic，检查是否需要 clarification
        if not topic:
            # 检查是否是需要 topic 的 skill
            needs_topic_skills = ['explain_skill', 'quiz_skill', 'flashcard_skill', 'notes_skill', 'mindmap_skill']
            if skill_id in needs_topic_skills:
                params['needs_clarification'] = True
                params['clarification_reason'] = "topic_missing"
                logger.warning(f"⚠️  Topic required for {skill_id} but not found")
                return params
        
        if topic:
            params['topic'] = topic
            # 对于 explain_skill，topic 应该设置为 concept_name
            if skill_id == 'explain_skill':
                params['concept_name'] = topic
        
        # 4. 检测上下文引用 - 使用简单的关键词检测
        context_keywords = ['根据', '基于', '刚才', '这些', '这道', '上面', '第一', '第二', '第三', '第', '再来', '再给']
        if any(kw in message for kw in context_keywords):
            params['use_last_artifact'] = True
            logger.debug(f"🔗 Detected context reference")
        
        return params
    
    def _extract_topic(self, message: str, metadata: Dict[str, Any]) -> Optional[str]:
        """从消息中提取主题 - 使用简单直接的方法"""
        
        # 🔥 Step 0: 检测 follow-up 修饰请求（这些消息应使用 current_topic，不提取新主题）
        # "解释得简单些"、"讲得详细点"、"说清楚一点" 等都是追问请求
        followup_modifier_patterns = [
            r'解释得.{0,4}[简单详细清楚明白]',  # "解释得简单些"、"解释得详细一点"
            r'讲得.{0,4}[简单详细清楚明白]',    # "讲得简单点"
            r'说得.{0,4}[简单详细清楚明白]',    # "说得清楚些"
            r'再.{0,2}[简单详细清楚]',          # "再简单一点"
            r'更[简单详细清楚明白]',             # "更简单"、"更详细"
            r'[简单详细清楚][一点些]',           # "简单一点"、"详细些"
            r'不太[懂理解明白清楚]',             # "不太懂"、"不太理解"
            r'没[懂理解明白清楚]',               # "没懂"、"没理解"
            r'还是不[懂理解明白清楚]',           # "还是不懂"
        ]
        
        for pattern in followup_modifier_patterns:
            if re.search(pattern, message):
                logger.info(f"🔗 Follow-up modifier detected: '{pattern}' in message, skipping topic extraction")
                return None
        
        # 🔥 Step 0.5: 常见的 follow-up 响应词（这些消息应使用 current_topic）
        # "好的，给我三张闪卡" / "嗯，再来几道题" / "是的，帮我做笔记"
        followup_starters = [
            '好的', '好', '嗯', '是的', '可以', '行', '那', '那就', '那么',
            '没问题', '当然', 'ok', 'OK', '好啊', '好呀', '行啊', '行吧',
            '可以的', '没事', '对', '对的', '是', '确定', '确认'
        ]
        
        # 检查消息是否以 follow-up 词开头
        message_stripped = message.strip()
        for starter in followup_starters:
            if message_stripped.startswith(starter):
                # 移除开头的 follow-up 词和标点
                remaining = message_stripped[len(starter):].lstrip('，,。.！!、 ')
                # 如果剩余部分是纯动作请求（没有明确 topic），返回 None
                if self._is_pure_action_request(remaining):
                    logger.debug(f"🔗 Follow-up message detected: '{starter}...' → using current_topic")
                    return None
        
        # 🔥 Step 1: 检测隐式上下文引用（这些情况应返回 None，由 current_topic 填充）
        # 📌 注意：只有当消息中没有明确 topic 时才算隐式引用
        #    "给我三张闪卡" → 隐式引用（没有 topic）
        #    "我需要光合作用三张闪卡" → 不是隐式引用（有 topic "光合作用"）
        implicit_reference_patterns = [
            # 只匹配纯动作请求，不包含额外内容（topic）
            r'^(需要|想要|给我|来|要|生成|创建)\s*(?:\d+|[一二三四五六七八九十两])?\s*[道个张份]?(?:知识导图|闪卡|题目|笔记|卡片|题|卡)$',  # "给我三张闪卡"（完全匹配，结尾）
            r'^(不对|再|继续|还要|刚刚|刚才|这个|那个)',           # "再来几道"、"刚刚的"
            r'(刚刚|刚才|上面|前面|这些)[的]?(topic|主题)',      # "刚刚两个topic"
            r'^(出|做|写|画)\s*(?:\d+|[一二三四五六七八九十两])?\s*[道个张份]?(?:题|闪卡|导图|笔记|卡)$',  # "出3道题"（完全匹配，结尾）
        ]
        
        for pattern in implicit_reference_patterns:
            if re.search(pattern, message):
                logger.debug(f"🔗 Detected implicit context reference, will use current_topic")
                return None  # 明确返回 None，让调用者使用 current_topic
        
        # 🔥 Step 2: 优化的主题提取模式（按优先级排序）
        topic_patterns = [
            # 🆕 最高优先级：明确的"主题是XXX"结构
            r'主题是(.+?)(?:[，。！？]|$)',                   # "主题是光合作用"
            r'(?:关于|主题[为是]?)(.+?)(?:的)?(?:学习计划|计划|规划)',  # "关于光合作用的学习计划"
            
            # 🆕 最高优先级：明确的"XXX的解释/说明"结构
            r'(.+?)的(?:解释|讲解|说明|介绍|定义)',          # "二战起因的解释"
            
            # 🔥 新增：topic在前，动作词+数量词在后（如"二战的起因给我三张闪卡"）
            r'^(.+?)(给我|来|帮我|生成|创建)(?:\d+|[一二三四五六七八九十两])[道个张份题卡]',  # "XXX给我N张闪卡"
            
            # 🔥 新增：flashcard 专用模式
            r'(?:根据|关于)?(.+?)(?:出|生成|做|来)(?:\d+|[一二三四五六七八九十两])[道个张份]?(?:闪卡|卡片|卡)',  # "二战起因出三张闪卡"、"根据二战起因出三张闪卡"
            r'(?:我需要|需要|想要|要)(.+?)(?:\d+|[一二三四五六七八九十两])[道个张份]?(?:闪卡|卡片|题|卡)',  # "我需要光合作用三张闪卡"
            r'(?:帮我)?(?:根据|关于)(.+?)(?:出|生成|做|来)(?:\d+|[一二三四五六七八九十两])?',  # "帮我根据二战起因出三张闪卡"
            
            # 🔥 新增：无数量词的模式（如 "生成光合作用的闪卡"）
            r'(?:生成|创建|做|出|来)(.+?)(?:的)?(?:闪卡|卡片|题目|练习题|笔记|思维导图|导图)',  # "生成光合作用的闪卡"
            r'(.+?)(?:的)?(?:闪卡|卡片|题目|练习题|笔记|思维导图|导图)(?:[，。！？]|$)',  # "光合作用的闪卡"
            
            # 高优先级：明确的主题词
            r'什么是(.+?)(?:[，。！？]|$)',              # "什么是光合作用"
            r'解释(?:一下)?(.+?)(?:[，。！？]|$)',     # "解释光合作用"、"解释一下光合作用"
            r'讲(?:述(?:一下)?|解(?:一下)?|讲|一下)(.+?)(?:[，。！？]|$)',  # "讲述好莱坞历史"、"讲解光合作用"、"讲解一下光合作用"、"讲讲光合作用"、"讲一下光合作用"
            r'理解(?:一下)?(.+?)(?:[，。！？]|$)',     # "理解光合作用"
            r'了解(?:一下)?(.+?)(?:[，。！？]|$)',     # "了解光合作用"
            r'学习(?:一下)?(.+?)(?:[，。！？]|$)',     # "学习光合作用"
            r'关于(.+?)的',                             # "关于光合作用的"
            
            # 中优先级：带数量词的模式
            r'(?:\d+|[一二三四五六七八九十两])[道个张份题卡](.+?)(?:的)?[题笔闪导卡图记]',  # "3道光合作用的题"
        ]
        
        for pattern in topic_patterns:
            match = re.search(pattern, message)
            if match:
                # 提取第一个捕获组
                topic = match.group(1).strip()
                # 清理主题
                topic = self._clean_topic(topic)
                
                # 🔥 Step 3: 更严格的验证 - 排除动作词和明显无效的主题
                invalid_topics = [
                    '我需要', '帮我', '给我', '我要', '再来', '再给', '再出', '出', '需要', '想要',
                    '选择', '判断', '填空', '简答',  # 题目类型，不是主题
                    '学习', '复习', '练习', '测试',  # 动作词，不是主题
                    '知识', 'topic', '主题', '内容',  # 太泛化
                    '文件', '文件内容', '这文件', '那文件', '这个文件', '那个文件',  # 🆕 文件相关无效 topic
                    '这两个文件', '这些文件', '附件', '上传的文件',  # 🆕 文件相关无效 topic
                ]
                
                # 🔥 检查是否以动作词开头（这些不是有效主题）
                action_prefixes = ['需要', '想要', '给我', '帮我', '我要', '再来', '再给', '这', '那', '文件', '根据']
                starts_with_action = any(topic.startswith(prefix) for prefix in action_prefixes)
                
                # 🆕 检查是否包含文件相关词汇（整体无效）
                file_related = any(word in topic for word in ['文件', '附件', '上传'])
                
                if topic and len(topic) >= 2 and topic not in invalid_topics and not starts_with_action and not file_related:
                    logger.debug(f"📝 Extracted topic: {topic} (pattern: {pattern})")
                    return topic
        
        return None
    
    def _clean_reference_patterns(self, message: str) -> str:
        """
        清理消息中的引用模式，用于关键词匹配
        
        Args:
            message: 原始消息
        
        Returns:
            清理后的消息
        """
        reference_patterns = [
            r'第[一二三四五六七八九十\d]+道?题',       # 第X题、第X道题
            r'第[一二三四五六七八九十\d]+张[闪]?卡片?', # 第X张闪卡、第X张卡、第X张卡片
            r'第[一二三四五六七八九十\d]+个?例[子]?',  # 第X个例子
            r'那道题',                                 # 那道题
            r'这道题',                                 # 这道题
            r'那张[闪]?卡',                            # 那张卡
            r'这张[闪]?卡',                            # 这张卡
        ]
        
        message_cleaned = message
        for pattern in reference_patterns:
            message_cleaned = re.sub(pattern, '', message_cleaned)
        
        if message_cleaned != message:
            logger.info(f"📎 Reference detected, cleaned message for intent: '{message_cleaned}'")
        
        return message_cleaned
    
    def _is_pure_action_request(self, text: str) -> bool:
        """
        检查文本是否是纯动作请求（没有明确的学习主题）
        
        Args:
            text: 清理后的文本
            
        Returns:
            True 如果是纯动作请求，False 如果包含明确主题
        """
        if not text or len(text.strip()) < 2:
            return True
        
        # 纯动作请求的模式
        pure_action_patterns = [
            r'^(给我|帮我|来|要|生成|创建|出|做|写|画)\s*(?:\d+|[一二三四五六七八九十两])?\s*[道个张份]?[题闪卡导图笔记卡片思维]',
            r'^(?:\d+|[一二三四五六七八九十两])\s*[道个张份][题闪卡导图笔记卡片]',  # "3道题"、"五张闪卡"
            r'^[题闪卡导图笔记卡片思维]+$',  # 只有技能词
        ]
        
        for pattern in pure_action_patterns:
            if re.search(pattern, text):
                return True
        
        # 如果剩余文本只包含动作词和数量词，也是纯动作请求
        action_words = ['给我', '帮我', '来', '要', '生成', '创建', '出', '做', '写', '画', 
                        '再来', '再给', '再出', '继续', '还要']
        skill_words = ['题', '闪卡', '卡片', '导图', '思维导图', '笔记', '解释', '讲解']
        quantity_pattern = r'(?:\d+|[一二三四五六七八九十两])\s*[道个张份]?'
        
        # 移除所有动作词、技能词和数量词后，看还剩什么
        remaining = text
        for word in action_words + skill_words:
            remaining = remaining.replace(word, '')
        remaining = re.sub(quantity_pattern, '', remaining)
        remaining = remaining.strip('，,。.！!、 ')
        
        # 如果剩余部分太短（< 2 字），认为是纯动作请求
        return len(remaining) < 2
    
    def _clean_topic(self, topic: str) -> str:
        """清理主题文本，移除填充词"""
        
        # 🔥 Step 1: 只从开头移除的词（可能是专有名词的一部分）
        # "好的，给我..." → 移除 "好的"
        # "好莱坞历史" → 保留 "好"（因为是专有名词的一部分）
        prefix_only_words = [
            "好的", "好啊", "好呀", "嗯", "是的", "可以", "行", "那", "那就", "那么", "ok", "OK",
            "没问题", "当然", "对的", "对", "确定", "确认"
        ]
        for prefix in prefix_only_words:
            if topic.startswith(prefix):
                topic = topic[len(prefix):].lstrip("，,、 ")
        
        # 🔥 Step 2: 可以在任意位置移除的词（不会是专有名词的一部分）
        filler_words = [
            # 语气词和标点
            "的", "了", "吗", "呢", "啊", "吧", "，", ",", "。", ".", "！", "!", "+", "＋",
            # 动作词
            "给我", "帮我", "我要", "我需要", "生成", "创建", "出", "做", "写", "画",
            "来", "要", "需要", "想要", "再来", "再给", "再出", "继续", "还要",
            # 上下文引用
            "关于", "有关", "根据", "刚刚", "刚才", "上面", "这个", "那个", "这些", "那些",
            # 技能相关词（会在 learning_bundle 消息中出现）
            "思维导图", "导图", "笔记", "题目", "闪卡", "卡片", "测验", "测试",
            "解释", "讲解", "学习包", "学习资料", "学习材料", "学习套装",
            # 其他无意义词
            "一下", "详细", "简单", "完整", "全部", "所有", "包含", "包括"
        ]
        for filler in filler_words:
            topic = topic.replace(filler, " ")
        
        # 移除数量词（阿拉伯数字 + 中文数字）
        topic = re.sub(r'\d+\s*[个道张份题卡]', '', topic)
        topic = re.sub(r'[一二三四五六七八九十两]\s*[个道张份题卡]', '', topic)
        
        # 移除多余空格
        topic = ' '.join(topic.split())
        
        # 🔥 最后检查：如果清理后的 topic 太短或是纯数字/标点/符号，返回空
        cleaned = topic.strip()
        if len(cleaned) < 2 or re.match(r'^[\d\s，,。.！!、+＋\-－]+$', cleaned):
            return ""
        
        return cleaned
    
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
        # 🆕 Step -1: 检测续问模式，跳过混合意图检测
        # 用户请求简化、详细说明、再说一遍等，都是续问，不是新的意图
        followup_patterns = [
            # 英文续问模式
            r'\bsimpler\b',           # "explain ... simpler"
            r'\bsimplify\b',          # "simplify that"
            r'\bmore detail\b',       # "more detail"
            r'\bmore details\b',      # "more details"
            r'\bmore specifically\b', # "more specifically"
            r'\bin detail\b',         # "in detail"
            r'\bagain\b',             # "explain again"
            r'\bone more time\b',     # "one more time"
            r'\belaborate\b',         # "elaborate on that"
            r'\bclarify\b',           # "clarify"
            r'\beasier\b',            # "make it easier"
            r'\bshorter\b',           # "shorter version"
            r'\bcontinue\b',          # "continue"
            r'\bgo on\b',             # "go on"
            # 中文续问模式
            r'简单[点些一]',          # "简单点"
            r'更简单',                # "更简单"
            r'详细[点些一]',          # "详细点"
            r'更详细',                # "更详细"
            r'再说[一]?遍',          # "再说一遍"
            r'重新[说讲解释]',       # "重新说"
            r'换[一个]?[种]?方式',   # "换一种方式"
            r'继续',                  # "继续"
            r'接着说',                # "接着说"
        ]
        
        message_lower = message.lower()
        for pattern in followup_patterns:
            if re.search(pattern, message_lower, re.IGNORECASE):
                logger.info(f"⏩ Followup pattern detected: '{pattern}' in message, skipping mixed intent")
                return None  # 让后续逻辑处理为 other intent
        
        # 🆕 Step 0: 移除引用模式，避免把引用当作 intent
        # "把第二道题帮我解释" 中的 "第二道题" 是引用，不是要出题
        reference_patterns = [
            r'第[一二三四五六七八九十\d]+道?题',      # 第X题、第X道题
            r'第[一二三四五六七八九十\d]+张[闪]?卡片?', # 第X张闪卡、第X张卡、第X张卡片
            r'第[一二三四五六七八九十\d]+个?例[子]?', # 第X个例子
            r'那道题',                                # 那道题
            r'这道题',                                # 这道题
            r'那张[闪]?卡',                           # 那张卡
            r'这张[闪]?卡',                           # 这张卡
        ]
        
        # 从消息中移除引用部分后再检测
        message_cleaned = message
        for pattern in reference_patterns:
            message_cleaned = re.sub(pattern, '', message_cleaned)
        
        # 如果清理后消息有变化，说明有引用
        has_reference = message_cleaned != message
        if has_reference:
            logger.info(f"📎 Reference detected, cleaned message for intent: '{message_cleaned}'")
            
            # 🆕 进一步清理：移除引用相关的修饰词
            # "给出题目解释" 中的 "题目" 是指被引用的题目，不是要出新题
            reference_modifiers = [
                (r'这个?题目?', ''),          # 这题目、这个题目
                (r'那个?题目?', ''),          # 那题目、那个题目
                (r'上面的?', ''),              # 上面的
                (r'刚才的?', ''),              # 刚才的
                (r'前面的?', ''),              # 前面的
            ]
            for pattern, replacement in reference_modifiers:
                message_cleaned = re.sub(pattern, replacement, message_cleaned)
            
            # 🆕 当有引用时，如果清理后剩余内容很少，说明这是纯引用操作
            # 例如："可以帮我根据，给出解释吗" → 只剩 "解释" 动作，不应触发 quiz
            remaining_content = re.sub(r'[，。？！,.\?!]', '', message_cleaned).strip()
            remaining_content = re.sub(r'^(可以|能不能|帮我|请|给我|根据)', '', remaining_content).strip()
            if len(remaining_content) < 10:
                logger.info(f"📎 Reference-heavy message: '{remaining_content}', likely single intent")
        
        # 定义各技能的关键词集合
        # 🔧 注意：某些词如 "理解"、"了解" 在特定上下文中不应触发 explain
        #    例如 "加深理解" 不是 explain 请求，而是修饰语
        skill_keywords = {
            'explain': ['解释', '讲解', '讲述', '说明', '什么是', '介绍', '定义', '教我', '告诉我', '科普', '解读', 'explain', 'what is', 'understand', 'teach me'],
            # 🔧 移除单独的 'test'（会误匹配 "tested"、"contest" 等），保留 'test questions'、'test me'
            'quiz': ['题', '题目', '练习', '测试', '考题', '测验', '做题', '刷题', '习题', '试题', '出题', 'quiz', 'test me', 'test questions', 'exam', 'exercise'],
            'flashcard': ['闪卡', '卡片', '记忆卡', '抽认卡', '背诵卡', '复习卡', '生成闪卡', '做闪卡', 'flashcard', 'card', 'anki'],
            'notes': ['笔记', '总结', '归纳', '整理', '提炼', '梳理', '要点', 'notes', 'summary', 'outline'],
            'mindmap': ['思维导图', '导图', '脑图', '知识图谱', '知识图', '概念图', '结构图', 'mindmap', 'mind map', 'concept map', 'knowledge graph'],
            'learning_bundle': ['学习包', '学习资料', '学习材料', '完整', '学习套装', '学习计划', 'learning bundle', 'study package']
        }
        
        # 🆕 需要特殊处理的关键词（只在特定上下文中匹配 explain）
        # "理解" 和 "了解" 只有在动作语境中才匹配 explain
        explain_contextual_keywords = ['理解', '了解', '学习']
        explain_exclude_prefixes = ['加深', '深入', '更好', '为了', '帮助']  # 这些前缀后的 "理解" 不是 explain 请求
        
        # 🆕 quiz 关键词的排除模式
        # "问题" 在这些上下文中不应该触发 quiz（是在讨论问题，而不是请求出题）
        quiz_exclude_patterns = [
            '这类问题',      # "学生在这类问题中犯什么错误" → 讨论，不是出题
            '这个问题',      # "这个问题怎么理解" → 讨论
            '什么问题',      # "这有什么问题" → 询问问题
            '常见问题',      # "有哪些常见问题" → 讨论
            '问题中',        # "在问题中犯的错误" → 讨论
            '问题里',        # "问题里的概念" → 讨论
            '问题上',        # "在这个问题上" → 讨论
            '的问题',        # "学生的问题" → 讨论
            '犯什么错',      # "犯什么错误" → 询问错误，不是出题
            '解答',          # "帮我解答" → 请求解答，不是出题
            '帮我做',        # "帮我做这道题" → 请求帮做，不是出题
            '回答',          # "回答问题" → 请求回答，不是出题
            'common mistake', # "common mistakes" → 讨论错误
            'this problem',   # "this problem" → 讨论
            'this question',  # "this question" → 讨论
            'that question',  # "that question" → 讨论/指代现有题目
            'the question',   # "the question" → 讨论/指代现有题目
            'solve',          # "solve that question" → 请求解答
            'answer',         # "answer that question" → 请求解答
            'help me with',   # "help me with this question" → 请求帮助
            'work out',       # "work out this question" → 请求计算
            'figure out',     # "figure out this question" → 请求解答
            'explain',        # "explain this question" → 请求解释
        ]
        
        # 🆕 使用清理后的消息检测关键词
        matched_skills = []
        for skill_name, keywords in skill_keywords.items():
            # 🔥 quiz 特殊处理：检查排除模式
            if skill_name == 'quiz':
                # 先检查是否命中排除模式
                if any(exc in message_cleaned.lower() for exc in quiz_exclude_patterns):
                    logger.debug(f"⚠️ Quiz excluded: message contains exclusion pattern")
                    continue
            
            if any(kw in message_cleaned for kw in keywords):
                matched_skills.append(skill_name)
        
        # 🔥 特殊处理 explain 的上下文关键词
        if 'explain' not in matched_skills:
            for kw in explain_contextual_keywords:
                if kw in message_cleaned:
                    # 检查是否有排除前缀
                    kw_index = message_cleaned.find(kw)
                    if kw_index > 0:
                        prefix = message_cleaned[max(0, kw_index-2):kw_index]
                        if any(exc in prefix for exc in explain_exclude_prefixes):
                            logger.debug(f"⚠️ '{kw}' has exclude prefix '{prefix}', not matching explain")
                            continue
                    # 检查是否是动作语境（如 "帮我理解"、"我要理解"）
                    action_patterns = [f'帮我{kw}', f'我要{kw}', f'想{kw}', f'来{kw}', f'去{kw}']
                    if any(p in message_cleaned for p in action_patterns):
                        matched_skills.append('explain')
                        logger.debug(f"✅ '{kw}' in action context, matching explain")
                        break
        
        # 🔥 特殊情况：如果明确提到 learning_bundle 关键词，直接返回 learning_plan_skill
        if 'learning_bundle' in matched_skills:
            logger.info(f"📦 Detected explicit learning_bundle keywords")
            
            # 提取参数
            params = {}
            
            # 🔥 使用增强的topic提取（支持"关于X的学习包"等模式）
            topic = None
            topic_patterns = [
                # 🆕 最高优先级：明确的"主题是XXX"结构
                r'主题是(.+?)(?:[，。！？]|$)',                      # "主题是量子力学"
                r'关于(.+?)(?:的|，)',                              # "关于DNA的学习包"
                r'(.+?)(?:的|，)(?:学习包|学习资料|学习材料|学习计划)', # "DNA的学习包" / "DNA的学习计划"
                r'给我(?:一?个)?(.+?)(?:的|，)?(?:学习包|学习资料|学习计划)', # "给我DNA学习包"
            ]
            
            # 🔥 技能相关词，如果 topic 包含这些词，说明提取错误
            skill_keywords_in_topic = ['闪卡', '测验', '笔记', '题', '导图', '解释', '讲解', '学习包']
            
            for pattern in topic_patterns:
                match = re.search(pattern, message)
                if match:
                    topic_candidate = match.group(1).strip()
                    topic_candidate = self._clean_topic(topic_candidate)
                    # 🔥 验证 topic 不包含技能关键词（否则说明提取错误）
                    if len(topic_candidate) >= 2 and not any(kw in topic_candidate for kw in skill_keywords_in_topic):
                        topic = topic_candidate
                        break
            
            # 🔥 如果上面的pattern没匹配到或提取的topic无效，优先使用 current_topic
            # 因为 learning_bundle 消息通常是纯动作请求（如"帮我生成闪卡+测验+笔记的学习包"）
            if not topic and current_topic:
                topic = current_topic
                logger.info(f"📦 Using current_topic for learning_bundle: {current_topic}")
            
            # 最后尝试通用的topic提取（不太可能成功，但作为兜底）
            if not topic:
                extracted = self._extract_topic(message, {})
                if extracted and len(extracted) >= 2:
                    topic = extracted
            
            if topic:
                params['topic'] = topic
            
            # 🆕 检查是否指定了具体的步骤（如"包含讲解、3张闪卡和2道题"）
            matched_skills_filtered = [s for s in matched_skills if s != 'learning_bundle']
            if matched_skills_filtered:
                step_mapping = {
                    'explain': 'explain',
                    'quiz': 'quiz',
                    'flashcard': 'flashcard',
                    'notes': 'notes',
                    'mindmap': 'mindmap'
                }
                params['required_steps'] = [step_mapping[skill] for skill in matched_skills_filtered if skill in step_mapping]
                logger.info(f"📋 User specified steps in learning bundle: {params['required_steps']}")
            
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
        
        # 🆕 当有引用时，不应轻易触发混合意图
        # 例如："根据第五道题，给出解释" → 只是解释那道题，不是要生成新题+解释
        if has_reference and len(matched_skills_filtered) >= 2:
            # 检查是否有明确的生成动作词（需要更精确的匹配，避免 "给出" 被误识别）
            generation_patterns = [
                r'(?<!给)出\d*[道张个]',  # "出三道" 但不是 "给出"
                r'生成',
                r'创建',
                r'做\d*[道张个]',   # "做三道"
                r'写\d*[道张个]',   # "写三张"
                r'画',
                r'来\d*[道张个]',   # "来三道"
                r'再来',
                r'再出',
            ]
            has_generation_action = any(re.search(p, message_cleaned) for p in generation_patterns)
            
            if not has_generation_action:
                logger.info(f"📎 Reference with no generation action, skipping mixed intent: {matched_skills_filtered}")
                return None  # 不触发混合意图，让后续的单一意图检测处理
        
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

