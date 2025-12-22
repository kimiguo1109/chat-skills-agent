"""
Plan Skill Executor - 计划技能执行器

负责执行 Plan Skill 的串联调用逻辑：
1. 解析执行计划
2. 串联调用多个 skills
3. 管理上下文传递
4. 聚合最终结果
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
import json

from app.core.artifact_storage import ArtifactStorage, generate_session_id

logger = logging.getLogger(__name__)


class PlanSkillExecutor:
    """
    Plan Skill 执行器
    
    核心功能：
    - 串联执行多个 skills
    - 上下文提取和注入
    - Token 成本控制
    - 错误处理和回退
    """
    
    def __init__(self, skill_orchestrator):
        """
        初始化 Plan Skill 执行器
        
        Args:
            skill_orchestrator: SkillOrchestrator 实例（用于调用子 skills）
        """
        self.skill_orchestrator = skill_orchestrator
        self.execution_log = []
        self.token_usage = {
            "total": 0,
            "per_step": {}
        }
        
        # 🆕 Phase 2: Context Offloading 支持（条件初始化）
        self.artifact_storage = None
        self.offloading_enabled = False
        self.current_session_id = None  # 当前执行的 session ID
    
    async def execute_plan(
        self,
        plan_config: Dict[str, Any],
        user_input: Dict[str, Any],
        user_profile: Any,
        session_context: Any
    ) -> Dict[str, Any]:
        """
        执行完整的 Plan
        
        Args:
            plan_config: Plan Skill 的 YAML 配置
            user_input: 用户输入参数
            user_profile: 用户学习画像
            session_context: 会话上下文
        
        Returns:
            聚合后的学习包
        """
        # 🎚️ Phase 2: 检查是否启用 Context Offloading
        cost_control = plan_config.get("cost_control", {})
        self.offloading_enabled = cost_control.get("enable_artifact_offloading", False)
        
        if self.offloading_enabled:
            # 初始化 ArtifactStorage 和 session ID
            self.artifact_storage = ArtifactStorage()
            self.current_session_id = generate_session_id()
            
            # 保存 Plan metadata
            self.artifact_storage.save_plan_metadata(
                self.current_session_id,
                plan_config,
                user_input
            )
            
            logger.info(f"✅ [Offloading] Enabled (session: {self.current_session_id})")
        else:
            logger.debug("ℹ️  [Offloading] Disabled (using legacy context pruning)")
        
        execution_plan = plan_config["execution_plan"]
        all_steps = execution_plan["steps"]
        
        # 🆕 Phase 4.2: 动态步骤选择 - 如果 user_input 中有 required_steps，只执行这些步骤
        required_steps = user_input.get("required_steps")
        if required_steps:
            logger.info(f"🎯 User requested specific steps: {required_steps}")
            # 过滤出需要执行的步骤
            steps = [step for step in all_steps if step.get("step_id") in required_steps]
            logger.info(f"📋 Filtered execution plan: {len(steps)}/{len(all_steps)} steps")
        else:
            steps = all_steps
        
        logger.info(f"\n{'='*60}")
        logger.info(f"🎯 开始执行 Plan Skill: {plan_config['display_name']}")
        logger.info(f"📋 总步骤数: {len(steps)}")
        logger.info(f"🎓 主题: {user_input.get('topic', 'Unknown')}")
        logger.info(f"{'='*60}\n")
        
        # 执行结果存储
        step_results = {}
        step_contexts = {}  # 存储每个 step 提取的上下文
        
        # 串联执行所有 steps
        for actual_index, step in enumerate(steps, 1):  # 🆕 使用实际索引
            step_id = step["step_id"]
            step_name = step["display_name"]
            skill_id = step["skill_id"]
            
            logger.info(f"\n{'─'*60}")
            logger.info(f"📍 Step {actual_index}/{len(steps)}: {step_name}")  # 🆕 显示实际进度
            logger.info(f"🔧 Skill: {skill_id}")
            logger.info(f"📦 依赖: {step['depends_on'] or '无'}")
            
            try:
                # 1. 构建 step 输入
                step_input = self._build_step_input(
                    step=step,
                    user_input=user_input,
                    step_contexts=step_contexts,
                    session_context=session_context  # 🆕 传入 session_context
                )
                logger.info(f"✅ 输入参数构建完成")
                
                # 2. 执行 skill
                result = await self._execute_step(
                    skill_id=skill_id,
                    input_params=step_input,
                    user_profile=user_profile,
                    session_context=session_context
                )
                logger.info(f"✅ Skill 执行成功")
                
                # 3. 提取上下文（用于下游 steps）
                extracted_context = self._extract_context(
                    result=result,
                    extraction_config=step.get("context_extraction", {}),
                    step_id=step_id  # 🆕 Phase 2: 传递 step_id 用于 offloading
                )
                
                # 4. 存储结果
                step_results[step_id] = result
                step_contexts[step_id] = extracted_context
                
                # 5. Token 统计
                tokens_used = self._estimate_tokens(result)
                self.token_usage["per_step"][step_id] = tokens_used
                self.token_usage["total"] += tokens_used
                
                logger.info(f"💾 上下文提取: {len(str(extracted_context))} 字符")
                logger.info(f"💰 Token 消耗: ~{tokens_used}")
                logger.info(f"📊 累计 Token: ~{self.token_usage['total']}")
                logger.info(f"✅ Step {step_id} 完成")
                
            except Exception as e:
                logger.error(f"❌ Step {step_id} 失败: {e}")
                logger.exception(e)
                
                # 错误处理
                error_config = plan_config.get("error_handling", {})
                strategy = error_config.get("on_step_failure", {}).get("strategy", "skip_and_continue")
                
                if strategy == "skip_and_continue":
                    logger.info(f"⏭️  跳过 Step {step_id}，继续执行下一步")
                    continue
                elif strategy == "abort":
                    logger.error(f"🚫 Plan 执行中止")
                    raise
                else:
                    # 默认：跳过
                    logger.info(f"⏭️  跳过 Step {step_id}，继续执行")
                    continue
        
        logger.info(f"\n{'─'*60}")
        logger.info(f"📦 所有步骤执行完成")
        logger.info(f"✅ 成功: {len(step_results)}/{len(steps)} 个步骤")
        logger.info(f"💰 总 Token 消耗: ~{self.token_usage['total']}")
        
        # 检查最小成功步骤数
        min_required = plan_config.get("error_handling", {}).get("min_required_steps", 1)
        if len(step_results) < min_required:
            error_msg = plan_config.get("error_handling", {}).get("fallback", {}).get("on_total_failure", {}).get("message", "学习包生成失败")
            logger.error(f"❌ 成功步骤不足: {len(step_results)} < {min_required}")
            raise Exception(error_msg)
        
        # 聚合结果
        bundle = self._aggregate_results(
            step_results=step_results,
            aggregation_config=plan_config["aggregation"],
            user_input=user_input
        )
        
        logger.info(f"\n{'='*60}")
        logger.info(f"🎊 Plan Skill 执行完成！")
        logger.info(f"📦 学习包 ID: {bundle.get('bundle_id')}")
        logger.info(f"📚 包含组件: {len(bundle.get('components', []))}")
        logger.info(f"⏱️  预计学习时间: {bundle.get('estimated_time_minutes')} 分钟")
        logger.info(f"{'='*60}\n")
        
        return bundle
    
    async def execute_plan_stream(
        self,
        plan_config: Dict[str, Any],
        user_input: Dict[str, Any],
        user_profile: Any,
        session_context: Any
    ):
        """
        🆕 流式执行完整的 Plan（实时展示每个步骤的thinking和进度）
        
        Args:
            plan_config: Plan Skill 的 YAML 配置
            user_input: 用户输入参数
            user_profile: 用户学习画像
            session_context: 会话上下文
        
        Yields:
            Dict: 流式事件 {"type": "plan_progress|thinking|content|step_done|done", ...}
        """
        # 🎚️ Phase 2: 检查是否启用 Context Offloading
        cost_control = plan_config.get("cost_control", {})
        self.offloading_enabled = cost_control.get("enable_artifact_offloading", False)
        
        if self.offloading_enabled:
            # 初始化 ArtifactStorage 和 session ID
            self.artifact_storage = ArtifactStorage()
            self.current_session_id = generate_session_id()
            
            # 保存 Plan metadata
            self.artifact_storage.save_plan_metadata(
                self.current_session_id,
                plan_config,
                user_input
            )
            
            logger.info(f"✅ [Offloading] Enabled (session: {self.current_session_id})")
        else:
            logger.debug("ℹ️  [Offloading] Disabled (using legacy context pruning)")
        
        execution_plan = plan_config["execution_plan"]
        all_steps = execution_plan["steps"]
        
        # 🆕 Phase 4.2: 动态步骤选择 - 如果 user_input 中有 required_steps，只执行这些步骤
        required_steps = user_input.get("required_steps")
        if required_steps:
            logger.info(f"🎯 User requested specific steps: {required_steps}")
            # 过滤出需要执行的步骤
            steps = [step for step in all_steps if step.get("step_id") in required_steps]
            logger.info(f"📋 Filtered execution plan: {len(steps)}/{len(all_steps)} steps (streaming)")
        else:
            steps = all_steps
        
        total_steps = len(steps)
        
        logger.info(f"\n{'='*60}")
        logger.info(f"🌊 开始流式执行 Plan Skill: {plan_config['display_name']}")
        logger.info(f"📋 总步骤数: {total_steps}")
        logger.info(f"🎓 主题: {user_input.get('topic', 'Unknown')}")
        logger.info(f"{'='*60}\n")
        
        # 🆕 准备步骤预览信息
        steps_preview = []
        for idx, step in enumerate(steps, 1):
            steps_preview.append({
                "step_order": idx,
                "step_name": step.get("name", f"步骤 {idx}"),
                "step_description": step.get("description", ""),
                "skill_id": step["skill_id"]
            })
        
        # 发送Plan开始状态（包含步骤预览）
        yield {
            "type": "plan_start",
            "total_steps": total_steps,
            "topic": user_input.get('topic'),
            "subject": user_input.get('subject'),
            "steps_preview": steps_preview  # 🆕 完整步骤列表
        }
        
        # 执行结果存储
        step_results = {}
        step_contexts = {}
        
        # 串联执行所有 steps（流式）
        for actual_index, step in enumerate(steps, 1):  # 🆕 使用实际索引而不是原始order
            step_id = step["step_id"]
            step_name = step["display_name"]
            skill_id = step["skill_id"]
            step_order = actual_index  # 🆕 使用动态索引，而不是原始的step["order"]
            
            logger.info(f"\n{'─'*60}")
            logger.info(f"📍 Step {step_order}/{total_steps}: {step_name}")
            logger.info(f"🔧 Skill: {skill_id}")
            
            # 🆕 发送步骤开始状态
            yield {
                "type": "step_start",
                "step_order": step_order,
                "total_steps": total_steps,
                "step_name": step_name,
                "skill_id": skill_id
            }
            
            try:
                # 1. 构建 step 输入
                step_input = self._build_step_input(
                    step=step,
                    user_input=user_input,
                    step_contexts=step_contexts,
                    session_context=session_context  # 🆕 传入 session_context
                )
                logger.info(f"✅ 输入参数构建完成")
                
                # 2. 🆕 流式执行 skill
                async for chunk in self._execute_step_stream(
                    skill_id=skill_id,
                    input_params=step_input,
                    user_profile=user_profile,
                    session_context=session_context,
                    step_info={
                        "step_order": step_order,
                        "total_steps": total_steps,
                        "step_name": step_name
                    }
                ):
                    # 转发thinking和content chunks
                    if chunk["type"] in ["thinking", "content"]:
                        yield chunk
                    elif chunk["type"] == "done":
                        # Step完成，保存结果
                        result = chunk.get("content", {})  # ✅ 修复：从 content 字段获取结果
                        step_results[step_id] = result
                        
                        # 3. 提取上下文
                        extracted_context = self._extract_context(
                            result=result,
                            extraction_config=step.get("context_extraction", {}),
                            step_id=step_id  # 🆕 Phase 2: 传递 step_id 用于 offloading
                        )
                        step_contexts[step_id] = extracted_context
                        
                        # 4. 🆕 详细Token统计
                        tokens_used = self._estimate_tokens(result)
                        
                        # 尝试从result获取实际的usage信息
                        actual_usage = result.get("_usage", {})
                        
                        # 构建详细的token统计
                        step_token_info = {
                            "estimated_tokens": tokens_used,
                            "actual_usage": actual_usage,
                            "step_name": step_name,
                            "skill_id": skill_id
                        }
                        
                        self.token_usage["per_step"][step_id] = step_token_info
                        self.token_usage["total"] += tokens_used
                        
                        # 🆕 详细日志输出
                        logger.info(f"")
                        logger.info(f"{'─'*60}")
                        logger.info(f"✅ Step {step_order}/{total_steps} 完成: {step_name}")
                        logger.info(f"{'─'*60}")
                        
                        if actual_usage:
                            logger.info(f"💰 Token消耗详情:")
                            logger.info(f"   ├─ Prompt Tokens:     {actual_usage.get('prompt_tokens', 'N/A')}")
                            logger.info(f"   ├─ Completion Tokens: {actual_usage.get('completion_tokens', 'N/A')}")
                            logger.info(f"   ├─ Total Tokens:      {actual_usage.get('total_tokens', 'N/A')}")
                            if "reasoning_tokens" in actual_usage and actual_usage.get("reasoning_tokens", 0) > 0:
                                logger.info(f"   └─ Reasoning Tokens:  {actual_usage.get('reasoning_tokens', 0)}")
                        else:
                            logger.info(f"💰 Token消耗估算: ~{tokens_used} tokens")
                        
                        logger.info(f"📊 累计Token消耗: ~{self.token_usage['total']} tokens")
                        logger.info(f"{'─'*60}")
                        
                        # 🆕 发送步骤完成状态（包含result用于前端即时显示）
                        yield {
                            "type": "step_done",
                            "step_order": step_order,
                            "total_steps": total_steps,
                            "step_name": step_name,
                            "skill_id": skill_id,
                            "tokens_used": tokens_used,
                            "result": result  # 🆕 包含完整结果供前端渲染
                        }
                    elif chunk["type"] == "error":
                        # Step失败
                        raise Exception(chunk.get("message", "Step execution failed"))
                
            except Exception as e:
                logger.error(f"❌ Step {step_id} 失败: {e}")
                logger.exception(e)
                
                # 错误处理
                error_config = plan_config.get("error_handling", {})
                strategy = error_config.get("on_step_failure", {}).get("strategy", "skip_and_continue")
                
                # 🆕 发送步骤错误状态
                yield {
                    "type": "step_error",
                    "step_order": step_order,
                    "step_name": step_name,
                    "error": str(e),
                    "strategy": strategy
                }
                
                if strategy == "skip_and_continue":
                    logger.info(f"⏭️  跳过 Step {step_id}，继续执行下一步")
                    continue
                elif strategy == "abort":
                    logger.error(f"🚫 Plan 执行中止")
                    yield {
                        "type": "error",
                        "message": f"Plan执行中止于Step {step_order}: {str(e)}"
                    }
                    return
        
        # 🆕 生成详细的Token统计报告
        logger.info(f"\n{'━'*60}")
        logger.info(f"📦 Plan Skill 执行完成统计")
        logger.info(f"{'━'*60}")
        logger.info(f"✅ 成功步骤: {len(step_results)}/{total_steps}")
        logger.info(f"")
        logger.info(f"💰 Token消耗详情:")
        logger.info(f"{'─'*60}")
        
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_reasoning_tokens = 0
        
        for step_id, token_info in self.token_usage["per_step"].items():
            step_name = token_info.get("step_name", step_id)
            actual_usage = token_info.get("actual_usage", {})
            
            logger.info(f"")
            logger.info(f"📍 {step_name} ({token_info.get('skill_id', 'unknown')})")
            
            if actual_usage:
                prompt_t = actual_usage.get('prompt_tokens', 0)
                completion_t = actual_usage.get('completion_tokens', 0)
                reasoning_t = actual_usage.get('reasoning_tokens', 0)
                total_t = actual_usage.get('total_tokens', 0)
                
                total_prompt_tokens += prompt_t
                total_completion_tokens += completion_t
                total_reasoning_tokens += reasoning_t
                
                logger.info(f"   ├─ Prompt:     {prompt_t:>6} tokens")
                logger.info(f"   ├─ Completion: {completion_t:>6} tokens")
                if reasoning_t > 0:
                    logger.info(f"   ├─ Reasoning:  {reasoning_t:>6} tokens")
                logger.info(f"   └─ Total:      {total_t:>6} tokens")
            else:
                estimated = token_info.get("estimated_tokens", 0)
                logger.info(f"   └─ 估算:       ~{estimated:>6} tokens")
        
        logger.info(f"")
        logger.info(f"{'─'*60}")
        logger.info(f"📊 总计:")
        
        if total_prompt_tokens > 0 or total_completion_tokens > 0:
            logger.info(f"   ├─ Prompt Tokens:     {total_prompt_tokens:>8}")
            logger.info(f"   ├─ Completion Tokens: {total_completion_tokens:>8}")
            if total_reasoning_tokens > 0:
                logger.info(f"   ├─ Reasoning Tokens:  {total_reasoning_tokens:>8}")
            logger.info(f"   └─ Total Tokens:      {total_prompt_tokens + total_completion_tokens:>8}")
        else:
            logger.info(f"   └─ 估算总计:          ~{self.token_usage['total']:>8} tokens")
        
        logger.info(f"{'─'*60}")
        
        # 检查最小成功步骤数
        min_required = plan_config.get("error_handling", {}).get("min_required_steps", 1)
        if len(step_results) < min_required:
            error_msg = f"学习包生成失败：成功步骤不足 ({len(step_results)}/{min_required})"
            logger.error(f"❌ {error_msg}")
            yield {
                "type": "error",
                "message": error_msg
            }
            return
        
        # 聚合结果
        bundle = self._aggregate_results(
            step_results=step_results,
            aggregation_config=plan_config["aggregation"],
            user_input=user_input
        )
        
        logger.info(f"\n{'='*60}")
        logger.info(f"🎊 Plan Skill 执行完成！")
        logger.info(f"📦 学习包 ID: {bundle.get('bundle_id')}")
        logger.info(f"📚 包含组件: {len(bundle.get('components', []))}")
        logger.info(f"⏱️  预计学习时间: {bundle.get('estimated_time_minutes')} 分钟")
        logger.info(f"{'='*60}\n")
        
        # 🆕 生成Plan的reasoning_summary
        components_summary = []
        for comp in bundle.get('components', []):
            comp_type = comp.get('component_type', 'unknown')  # ✅ 修正字段名
            if comp_type == 'explanation':
                components_summary.append('概念讲解')
            elif comp_type == 'flashcard_set':
                # 兼容新旧格式：cardList (新) 或 cards (旧)
                content = comp.get('content', {})
                cards = content.get('cardList') or content.get('cards', [])
                card_count = len(cards)
                components_summary.append(f'{card_count}张抽认卡')
            elif comp_type == 'quiz_set':
                quiz_count = len(comp.get('content', {}).get('questions', []))
                components_summary.append(f'{quiz_count}道练习题')
        
        plan_reasoning_summary = f"完成学习包生成，包含{len(steps)}个步骤：{' + '.join(components_summary)}"
        
        # 🆕 发送Plan完成状态（包含reasoning_summary）
        yield {
            "type": "done",
            "thinking": "",  # Plan本身没有thinking过程
            "content": {
                **bundle,
                "reasoning_summary": plan_reasoning_summary  # 🆕 添加reasoning_summary
            },
            "content_type": "learning_bundle"
        }
    
    async def _execute_step_stream(
        self,
        skill_id: str,
        input_params: Dict[str, Any],
        user_profile: Any,
        session_context: Any,
        step_info: Dict[str, Any]
    ):
        """
        🆕 流式执行单个 skill（转发thinking和content）
        
        Args:
            skill_id: Skill ID
            input_params: 输入参数
            user_profile: 用户画像
            session_context: 会话上下文
            step_info: 步骤信息（用于显示进度）
        
        Yields:
            Dict: 流式事件
        """
        # 🆕 传递步骤索引，用于智能选择 thinking 模式
        # - 第一步 (explain) → 真思考 (Kimi)，深度理解核心概念
        # - 后续步骤 (flashcard/quiz/notes/mindmap) → 伪思考 (Gemini)，基于已有内容快速生成
        step_order = step_info.get("step_order", 1)
        
        async for chunk in self.skill_orchestrator._execute_single_skill_stream(
            skill_id=skill_id,
            input_params=input_params,
            user_profile=user_profile,
            session_context=session_context,
            step_index=step_order  # 🆕 传递步骤索引
        ):
            # 转发所有chunks
            yield chunk
    
    def _build_step_input(
        self,
        step: Dict[str, Any],
        user_input: Dict[str, Any],
        step_contexts: Dict[str, Any],
        session_context: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        构建 step 的输入参数
        
        支持模板变量：
        - {input.field}: 从用户输入提取
        - {context.step_id.field}: 从上游 step 上下文提取
        - 自动从 session_context 查找缺失的依赖
        
        Args:
            step: Step 配置
            user_input: 用户输入
            step_contexts: 已执行 steps 的上下文
            session_context: 会话上下文 (用于查找 fallback artifacts)
        
        Returns:
            Step 输入参数字典
        """
        logger.debug(f"🔧 Building input for step: {step.get('step_id')}")
        logger.debug(f"📥 Available user_input keys: {list(user_input.keys())}")
        step_input = {}
        
        for key, value_template in step["input_mapping"].items():
            logger.debug(f"🔍 Processing: {key} = {value_template}")
            if isinstance(value_template, str) and "{" in value_template:
                # 解析模板变量
                if value_template.startswith("{input."):
                    # 从用户输入提取: {input.topic} 或 {input.quantity|default:5}
                    field_expr = value_template[7:-1]
                    
                    # 🆕 支持默认值过滤器: {input.quantity|default:5}
                    if "|default:" in field_expr:
                        field, default_val_str = field_expr.split("|default:", 1)
                        field = field.strip()
                        default_val_str = default_val_str.strip()
                        
                        value = user_input.get(field)
                        if value is None:
                            # 尝试转换类型
                            if default_val_str.isdigit():
                                value = int(default_val_str)
                            elif default_val_str.lower() == "true":
                                value = True
                            elif default_val_str.lower() == "false":
                                value = False
                            else:
                                value = default_val_str
                            logger.debug(f"📝 Using default value for {field}: {value}")
                        step_input[key] = value
                    else:
                        # 无默认值
                        value = user_input.get(field_expr)
                        if value is not None:
                            step_input[key] = value
                        else:
                            logger.warning(f"⚠️  Field '{field_expr}' not found in user_input and no default value provided")
                
                elif value_template.startswith("{context."):
                    # 从上游 step 上下文提取
                    # 支持三种模式：
                    # 1. {context.explain.key_terms} - 明确指定 step
                    # 2. {context.previous} - 前一个 step 的完整上下文
                    # 3. {context.previous.summary} - 前一个 step 的 summary
                    parts = value_template[9:-1].split(".", 1)
                    step_id = parts[0]
                    field_path = parts[1] if len(parts) > 1 else None
                    
                    # 🆕 支持 {context.previous} - 自动获取前一个 step
                    if step_id == "previous":
                        # 获取当前已执行的最后一个 step
                        if step_contexts:
                            prev_step_id = list(step_contexts.keys())[-1]
                            prev_context = step_contexts[prev_step_id]
                            
                            if field_path:
                                # 提取特定字段（如 summary）
                                step_input[key] = self._get_nested_value(prev_context, field_path)
                                logger.info(f"📦 传递上下文: {key} <- previous({prev_step_id}).{field_path}")
                            else:
                                # 传递完整上下文（压缩版summary）
                                # 🎯 自动压缩前一步的输出为 summary
                                summary = self._create_context_summary(prev_context, prev_step_id)
                                step_input[key] = summary
                                logger.info(f"📦 传递上下文: {key} <- previous({prev_step_id}) [summary: {len(str(summary))} chars]")
                        else:
                            logger.warning(f"⚠️  No previous step available, passing None")
                            step_input[key] = None
                    
                    # 明确指定 step_id 的情况
                    elif step_id in step_contexts:
                        if field_path:
                            step_input[key] = self._get_nested_value(step_contexts[step_id], field_path)
                            logger.debug(f"📦 传递上下文: {key} <- context.{step_id}.{field_path}")
                        else:
                            # 传递完整上下文
                            context_value = step_contexts[step_id]
                            step_input[key] = context_value
                            logger.info(f"📦 传递上下文: {key} <- context.{step_id} (包含 {len(context_value)} 个字段: {list(context_value.keys()) if isinstance(context_value, dict) else 'non-dict'})")
                    else:
                        # 🆕 Phase 4.3: 从 session_context 查找 fallback artifact
                        fallback_value = self._find_artifact_from_session(
                            session_context=session_context,
                            artifact_type=step_id,  # 例如 "explain"
                            topic=user_input.get("topic")
                        )
                        
                        if fallback_value:
                            # 🎉 找到了 session 中的相关 artifact
                            if field_path:
                                step_input[key] = self._get_nested_value(fallback_value, field_path)
                                logger.info(f"✅ 从 session fallback: {key} <- {step_id}.{field_path} (artifact from history)")
                            else:
                                step_input[key] = fallback_value
                                logger.info(f"✅ 从 session fallback: {key} <- {step_id} (artifact from history)")
                        else:
                            # 仍然找不到，跳过该参数 (不传 None，让 skill 使用默认行为)
                            logger.warning(f"⚠️  依赖的 step {step_id} 不存在，且 session 中无相关 artifact，跳过参数 '{key}'")
                            # 不设置 step_input[key]，让下游自己处理
            else:
                # 直接值
                step_input[key] = value_template
        
        return step_input
    
    async def _execute_step(
        self,
        skill_id: str,
        input_params: Dict[str, Any],
        user_profile: Any,
        session_context: Any
    ) -> Dict[str, Any]:
        """
        执行单个 skill
        
        Args:
            skill_id: Skill ID
            input_params: 输入参数
            user_profile: 用户画像
            session_context: 会话上下文
        
        Returns:
            Skill 执行结果
        """
        # 调用 SkillOrchestrator 执行 skill
        result = await self.skill_orchestrator._execute_single_skill(
            skill_id=skill_id,
            input_params=input_params,
            user_profile=user_profile,
            session_context=session_context
        )
        
        return result
    
    def _extract_context(
        self,
        result: Dict[str, Any],
        extraction_config: Dict[str, Any],
        step_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        从 step 结果中提取上下文（路由器方法）
        
        Phase 2: 根据配置选择提取策略：
        - offload + enabled: 使用文件卸载（_offload_to_file）
        - 其他: 使用传统方式（_extract_context_legacy）
        
        Args:
            result: Step 执行结果
            extraction_config: 提取配置
            step_id: Step 标识符（用于 offloading）
        
        Returns:
            提取的上下文（可能是完整内容或 artifact 引用）
        """
        if not extraction_config:
            return {}
        
        strategy = extraction_config.get("strategy", "key_points")
        
        # 🎚️ Phase 2: 检查是否启用 offloading
        if strategy == "offload" and self.offloading_enabled:
            # 🆕 新路径：文件卸载
            return self._offload_to_file(result, extraction_config, step_id)
        else:
            # ✅ 原路径：传统方式（完全不变）
            return self._extract_context_legacy(result, extraction_config)
    
    def _extract_context_legacy(
        self,
        result: Dict[str, Any],
        extraction_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        从 step 结果中提取上下文（传统方式，保留原有逻辑）
        
        实现上下文卸载（Context Pruning）：
        - 只提取关键信息
        - 压缩数据量
        - 减少下游 token 消耗
        
        Args:
            result: Step 执行结果
            extraction_config: 提取配置
        
        Returns:
            提取的上下文字典
        """
        if not extraction_config:
            return {}
        
        strategy = extraction_config.get("strategy", "key_points")
        fields = extraction_config.get("fields", [])
        max_tokens = extraction_config.get("max_tokens", 500)
        
        extracted = {}
        
        if strategy == "key_points":
            # 提取指定字段
            for field in fields:
                value = self._get_nested_value(result, field)
                if value:
                    extracted[field] = value
        
        elif strategy == "summary":
            # 生成摘要（提取关键信息）
            for field in fields:
                value = self._get_nested_value(result, field)
                if value:
                    # 如果是列表，只保留数量信息
                    if isinstance(value, list):
                        extracted[field] = f"{len(value)} items"
                    else:
                        extracted[field] = value
        
        elif strategy == "full_content":
            # 🆕 传递完整内容（确保下游步骤内容连贯性）
            # 提取所有指定字段的完整内容，不做任何压缩
            for field in fields:
                value = self._get_nested_value(result, field)
                if value:
                    extracted[field] = value
            
            logger.info(f"📦 [full_content策略] 提取了 {len(extracted)} 个字段的完整内容")
            logger.info(f"📊 提取字段: {list(extracted.keys())}")
        
        # Token 限制检查
        extracted_str = json.dumps(extracted, ensure_ascii=False)
        estimated_tokens = len(extracted_str) // 4
        
        if estimated_tokens > max_tokens:
            logger.warning(f"⚠️  提取的上下文超过限制: {estimated_tokens} > {max_tokens}")
            # 进一步压缩（简单实现：截断）
            extracted = self._compress_context(extracted, max_tokens)
        
        logger.debug(f"🔍 上下文提取: {strategy} | {len(extracted_str)} chars | ~{estimated_tokens} tokens")
        
        return extracted
    
    def _offload_to_file(
        self,
        result: Dict[str, Any],
        extraction_config: Dict[str, Any],
        step_id: str
    ) -> Dict[str, Any]:
        """
        🆕 Phase 2: 将 step 结果卸载到文件系统（Context Offloading）
        
        核心优势：
        - Token 节省 > 90%（引用 < 200 bytes vs 完整内容 2000+ bytes）
        - 无信息损失（完整内容保存在文件中）
        - 按需加载（_format_prompt 时才读取）
        
        Args:
            result: Step 执行结果（完整内容）
            extraction_config: 提取配置
            step_id: Step 标识符
        
        Returns:
            Artifact 引用（type="artifact_reference"）
            
        降级机制：
            如果文件操作失败，自动回退到 _extract_context_legacy
        """
        try:
            # 保存完整结果到文件
            artifact_path = self.artifact_storage.save_step_result(
                session_id=self.current_session_id,
                step_id=step_id,
                result=result,
                metadata={
                    "skill_id": extraction_config.get("skill_id"),
                    "timestamp": datetime.now().isoformat()
                }
            )
            
            # 创建轻量级引用
            fields = extraction_config.get("fields")
            reference = self.artifact_storage.create_reference(
                session_id=self.current_session_id,
                step_id=step_id,
                fields=fields
            )
            
            # 统计效果
            result_size = len(json.dumps(result, ensure_ascii=False))
            reference_size = len(json.dumps(reference, ensure_ascii=False))
            savings = 1 - (reference_size / result_size)
            
            logger.info(
                f"💾 [Offloading] {step_id}: "
                f"{result_size} bytes → {reference_size} bytes "
                f"(节省 {savings*100:.1f}%)"
            )
            
            return reference
            
        except Exception as e:
            # 🛡️ 降级：回退到传统方式
            logger.warning(
                f"⚠️  Offloading failed for {step_id}, falling back to legacy: {e}"
            )
            return self._extract_context_legacy(result, extraction_config)
    
    def _aggregate_results(
        self,
        step_results: Dict[str, Dict[str, Any]],
        aggregation_config: Dict[str, Any],
        user_input: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        聚合所有 step 的结果为完整学习包
        
        Args:
            step_results: 各 step 的执行结果
            aggregation_config: 聚合配置
            user_input: 用户输入
        
        Returns:
            完整的学习包
        """
        components = []
        total_time = 0
        
        # 组装 components
        for component_config in aggregation_config["assembly"]["components"]:
            step_id = component_config["step_id"]
            
            if step_id in step_results:
                result = step_results[step_id]
                
                components.append({
                    "component_type": component_config["component_type"],
                    "skill_id": result.get("skill_id", "unknown"),
                    "content": result
                })
                
                # 累加时间
                if "estimated_time_minutes" in result:
                    total_time += result.get("estimated_time_minutes", 0)
        
        # 生成学习路径
        learning_path = aggregation_config["assembly"]["learning_path_template"]
        
        # 生成 bundle_id
        timestamp = int(datetime.now().timestamp())
        bundle_id = f"bundle_{user_input.get('subject', 'general')}_{user_input.get('topic', 'topic')}_{timestamp}"
        
        bundle = {
            "bundle_id": bundle_id,
            "subject": user_input.get("subject", "通用"),
            "topic": user_input.get("topic"),
            "components": components,
            "estimated_time_minutes": total_time if total_time > 0 else 45,  # 默认 45 分钟
            "learning_path": learning_path,
            "execution_summary": {
                "plan_skill_version": "2.0",
                "total_steps": len(step_results),
                "successful_components": len(components),
                "token_usage": self.token_usage
            }
        }
        
        return bundle
    
    def _create_context_summary(
        self,
        context: Dict[str, Any],
        step_id: str
    ) -> Dict[str, Any]:
        """
        🆕 创建前一步上下文的压缩 summary（上下文卸载）
        
        策略：保留关键字段，压缩冗余内容
        - 保留小字段（<100 chars）
        - 压缩大字段（>100 chars）为摘要
        - 数组：保留长度信息
        
        Args:
            context: 完整的前一步上下文
            step_id: 前一步的 step_id
        
        Returns:
            压缩后的 summary
        """
        if not isinstance(context, dict):
            return context
        
        summary = {}
        
        for key, value in context.items():
            if isinstance(value, str):
                if len(value) > 100:
                    # 长文本：保留前80字符 + 长度信息
                    summary[key] = value[:80] + f"... [total: {len(value)} chars]"
                else:
                    summary[key] = value
            
            elif isinstance(value, list):
                # 数组：保留长度 + 第一个元素示例
                if len(value) > 0:
                    summary[key] = {
                        "_type": "array",
                        "_length": len(value),
                        "_sample": value[0] if len(value) > 0 else None
                    }
                else:
                    summary[key] = []
            
            elif isinstance(value, dict):
                # 嵌套字典：递归压缩
                summary[key] = self._create_context_summary(value, step_id)
            
            else:
                # 其他类型（int, bool 等）：直接保留
                summary[key] = value
        
        # 添加元信息
        summary["_context_meta"] = {
            "from_step": step_id,
            "original_size_chars": len(str(context)),
            "summary_size_chars": len(str(summary)),
            "compression_ratio": f"{(1 - len(str(summary)) / max(len(str(context)), 1)) * 100:.1f}%"
        }
        
        logger.debug(
            f"📉 Context compressed: {len(str(context))} → {len(str(summary))} chars "
            f"({summary['_context_meta']['compression_ratio']} reduction)"
        )
        
        return summary
    
    def _find_artifact_from_session(
        self,
        session_context: Optional[Any],
        artifact_type: str,
        topic: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        从 session_context.artifact_history 中查找相关 artifact
        
        当 Plan Skill 的某个步骤被动态跳过时，尝试从会话历史中查找
        该类型的 artifact 作为 fallback。
        
        Args:
            session_context: 会话上下文
            artifact_type: Artifact 类型 (e.g., "explain" → "explanation")
            topic: 可选主题，用于过滤
        
        Returns:
            找到的 artifact content (压缩的 summary)，或 None
        """
        if not session_context or not hasattr(session_context, 'artifact_history'):
            return None
        
        # 类型映射: step_id → artifact_type
        type_mapping = {
            "explain": "explanation",
            "quiz": "quiz_set",
            "flashcard": "flashcard_set",
            "mindmap": "mindmap",
            "notes": "notes"
        }
        
        target_type = type_mapping.get(artifact_type, artifact_type)
        
        # 从后往前查找 (最新的优先)
        for artifact_record in reversed(session_context.artifact_history):
            # 匹配类型
            if artifact_record.artifact_type == target_type:
                # 如果指定了 topic，进一步匹配
                if topic and artifact_record.topic != topic:
                    continue
                
                # 返回 artifact 的 content (压缩的 summary)
                if artifact_record.content:
                    logger.info(f"🔍 Found {target_type} artifact from session history: {artifact_record.artifact_id}")
                    logger.info(f"   Topic: {artifact_record.topic}, Turn: {artifact_record.turn_number}")
                    return artifact_record.content
        
        logger.debug(f"🔍 No {target_type} artifact found in session history")
        return None
    
    def _get_nested_value(self, data: Any, path: str) -> Any:
        """
        获取嵌套字典/对象的值
        
        支持路径: 'field1.field2.field3'
        """
        if not path:
            return data
        
        keys = path.split(".")
        value = data
        
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            elif hasattr(value, key):
                value = getattr(value, key)
            else:
                return None
            
            if value is None:
                return None
        
        return value
    
    def _compress_context(self, context: Dict[str, Any], max_tokens: int) -> Dict[str, Any]:
        """压缩上下文到指定 token 限制"""
        # 简单实现：保留最重要的字段
        compressed = {}
        current_tokens = 0
        
        for key, value in context.items():
            value_str = json.dumps(value, ensure_ascii=False)
            value_tokens = len(value_str) // 4
            
            if current_tokens + value_tokens <= max_tokens:
                compressed[key] = value
                current_tokens += value_tokens
            else:
                break
        
        return compressed
    
    def _estimate_tokens(self, result: Dict[str, Any]) -> int:
        """估算结果的 token 数量（简单估算：字符数 / 4）"""
        result_str = json.dumps(result, ensure_ascii=False)
        return len(result_str) // 4

