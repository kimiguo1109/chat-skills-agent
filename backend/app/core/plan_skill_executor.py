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
        execution_plan = plan_config["execution_plan"]
        steps = execution_plan["steps"]
        
        logger.info(f"\n{'='*60}")
        logger.info(f"🎯 开始执行 Plan Skill: {plan_config['display_name']}")
        logger.info(f"📋 总步骤数: {len(steps)}")
        logger.info(f"🎓 主题: {user_input.get('topic', 'Unknown')}")
        logger.info(f"{'='*60}\n")
        
        # 执行结果存储
        step_results = {}
        step_contexts = {}  # 存储每个 step 提取的上下文
        
        # 串联执行所有 steps
        for step in steps:
            step_id = step["step_id"]
            step_name = step["display_name"]
            skill_id = step["skill_id"]
            
            logger.info(f"\n{'─'*60}")
            logger.info(f"📍 Step {step['order']}: {step_name}")
            logger.info(f"🔧 Skill: {skill_id}")
            logger.info(f"📦 依赖: {step['depends_on'] or '无'}")
            
            try:
                # 1. 构建 step 输入
                step_input = self._build_step_input(
                    step=step,
                    user_input=user_input,
                    step_contexts=step_contexts
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
                    extraction_config=step.get("context_extraction", {})
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
        execution_plan = plan_config["execution_plan"]
        steps = execution_plan["steps"]
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
        for step in steps:
            step_id = step["step_id"]
            step_name = step["display_name"]
            skill_id = step["skill_id"]
            step_order = step["order"]
            
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
                    step_contexts=step_contexts
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
                        result = chunk.get("data", {})
                        step_results[step_id] = result
                        
                        # 3. 提取上下文
                        extracted_context = self._extract_context(
                            result=result,
                            extraction_config=step.get("context_extraction", {})
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
        
        # 🆕 发送Plan完成状态
        yield {
            "type": "done",
            "content": bundle,
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
        # 调用 SkillOrchestrator 的流式执行方法
        async for chunk in self.skill_orchestrator._execute_single_skill_stream(
            skill_id=skill_id,
            input_params=input_params,
            user_profile=user_profile,
            session_context=session_context
        ):
            # 转发所有chunks
            yield chunk
    
    def _build_step_input(
        self,
        step: Dict[str, Any],
        user_input: Dict[str, Any],
        step_contexts: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        构建 step 的输入参数
        
        支持模板变量：
        - {input.field}: 从用户输入提取
        - {context.step_id.field}: 从上游 step 上下文提取
        
        Args:
            step: Step 配置
            user_input: 用户输入
            step_contexts: 已执行 steps 的上下文
        
        Returns:
            Step 输入参数字典
        """
        step_input = {}
        
        for key, value_template in step["input_mapping"].items():
            if isinstance(value_template, str) and "{" in value_template:
                # 解析模板变量
                if value_template.startswith("{input."):
                    # 从用户输入提取: {input.topic}
                    field = value_template[7:-1]
                    step_input[key] = user_input.get(field)
                
                elif value_template.startswith("{context."):
                    # 从上游 step 上下文提取: {context.explain.key_terms}
                    parts = value_template[9:-1].split(".", 1)
                    step_id = parts[0]
                    field_path = parts[1] if len(parts) > 1 else None
                    
                    if step_id in step_contexts:
                        if field_path:
                            step_input[key] = self._get_nested_value(step_contexts[step_id], field_path)
                        else:
                            step_input[key] = step_contexts[step_id]
                    else:
                        logger.warning(f"⚠️  依赖的 step {step_id} 不存在或未执行")
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
        extraction_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        从 step 结果中提取上下文
        
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

