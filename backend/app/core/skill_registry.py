"""
Skill Registry - 技能注册表

负责加载、管理和查询所有可用的 Skills。
从 YAML 配置文件中加载 Skill 定义。
"""
import logging
import os
from typing import Dict, List, Optional
import yaml

from ..models.skill import SkillDefinition
from ..config import settings

logger = logging.getLogger(__name__)


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
        
        self.config_dir = config_dir
        self._skills: Dict[str, SkillDefinition] = {}
        self._intent_map: Dict[str, List[str]] = {}  # intent -> [skill_ids]
        
        # 加载所有 skills
        self._load_skills()
        
        logger.info(f"✅ SkillRegistry initialized with {len(self._skills)} skills")
    
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
    
    def reload(self):
        """重新加载所有 Skills（用于热更新）"""
        logger.info("🔄 Reloading skills...")
        self._skills.clear()
        self._intent_map.clear()
        self._load_skills()
        logger.info(f"✅ Reloaded {len(self._skills)} skills")


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

