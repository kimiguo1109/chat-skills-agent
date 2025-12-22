#!/usr/bin/env python3
"""
完整场景测试脚本

场景 1: 单个 Skill 测试 + 上下文管理
场景 2: 混合意图测试 + 上下文管理
场景 3: 真伪思考测试 + 上下文管理
场景 4: 全功能综合测试 + 上下文管理
"""
import asyncio
import httpx
import json
import sys
from datetime import datetime
from pathlib import Path

# 配置
BASE_URL = "http://localhost:8088"
API_ENDPOINT = f"{BASE_URL}/api/agent/chat-stream"
TIMEOUT = 600.0  # 10 分钟超时

# 输出目录
OUTPUT_DIR = Path(__file__).parent.parent / "artifacts" / "test_full_scenarios"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def print_header(title):
    """打印大标题"""
    print("\n" + "=" * 80)
    print(f"  🎯 {title}")
    print("=" * 80 + "\n")


def print_section(title):
    """打印小节标题"""
    print(f"\n{'─' * 70}")
    print(f"  {title}")
    print(f"{'─' * 70}\n")


def print_step(step_num, message, expected):
    """打印测试步骤"""
    print(f"\n📍 步骤 {step_num}")
    print(f"   输入: {message}")
    print(f"   预期: {expected}")


async def send_message(message: str, user_id: str, session_id: str) -> dict:
    """发送消息并收集流式响应"""
    print(f"\n📤 发送: {message}")
    
    payload = {
        "message": message,
        "user_id": user_id,
        "session_id": session_id
    }
    
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            thinking_chars = 0
            content_chars = 0
            content_type = None
            final_content = None
            usage_summary = None
            start_time = datetime.now()
            first_chunk_time = None
            last_progress_time = datetime.now()
            thinking_started = False
            content_started = False
            
            async with client.stream("POST", API_ENDPOINT, json=payload) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    if not line.strip() or not line.startswith("data: "):
                        continue
                    
                    data_str = line[6:]
                    try:
                        chunk = json.loads(data_str)
                        chunk_type = chunk.get("type")
                        
                        if first_chunk_time is None:
                            first_chunk_time = datetime.now()
                            elapsed = (first_chunk_time - start_time).total_seconds()
                            print(f"   ✅ 首个响应 ({elapsed:.1f}s)")
                        
                        if chunk_type == "status":
                            msg = chunk.get("message", "")
                            print(f"   📊 {msg}")
                        
                        elif chunk_type == "thinking":
                            if not thinking_started:
                                print(f"   🧠 开始 Thinking...")
                                thinking_started = True
                            thinking_chars += len(chunk.get("text", ""))
                            # 每 5 秒或每 500 字符打印进度
                            now = datetime.now()
                            if (now - last_progress_time).total_seconds() >= 5 or thinking_chars % 500 == 0:
                                elapsed = (now - start_time).total_seconds()
                                print(f"   🧠 Thinking... {thinking_chars} chars ({elapsed:.0f}s)")
                                last_progress_time = now
                        
                        elif chunk_type == "content":
                            if not content_started:
                                elapsed = (datetime.now() - start_time).total_seconds()
                                print(f"   📝 开始 Content 输出... (Thinking完成: {thinking_chars} chars, {elapsed:.0f}s)")
                                content_started = True
                            content_chars += len(chunk.get("text", ""))
                            # 每 3 秒打印进度
                            now = datetime.now()
                            if (now - last_progress_time).total_seconds() >= 3:
                                print(f"   📝 Content... {content_chars} chars")
                                last_progress_time = now
                        
                        elif chunk_type == "done":
                            end_time = datetime.now()
                            total_time = (end_time - start_time).total_seconds()
                            content_type = chunk.get("content_type")
                            final_content = chunk.get("content")
                            usage_summary = chunk.get("usage_summary", {})
                            
                            print(f"   ✅ 完成 | 类型: {content_type} | 耗时: {total_time:.1f}s")
                            print(f"      Thinking: {thinking_chars} chars | Content: {content_chars} chars")
                            
                            return {
                                "success": True,
                                "content_type": content_type,
                                "content": final_content,
                                "thinking_chars": thinking_chars,
                                "content_chars": content_chars,
                                "total_time": total_time,
                                "usage": usage_summary
                            }
                        
                        elif chunk_type == "error":
                            print(f"   ❌ 错误: {chunk.get('message')}")
                            return {"success": False, "error": chunk.get("message")}
                    
                    except json.JSONDecodeError:
                        continue
            
            return {"success": False, "error": "No done event received"}
        
        except Exception as e:
            print(f"   ❌ 请求失败: {e}")
            return {"success": False, "error": str(e)}


async def wait_and_continue(seconds=2):
    """等待并继续"""
    print(f"\n⏳ 等待 {seconds}s...")
    await asyncio.sleep(seconds)


# ============================================================================
# 场景 1: 单个 Skill 测试 + 上下文管理
# ============================================================================
async def scenario_1_single_skills():
    """场景 1: 单个 Skill 测试"""
    print_header("场景 1: 单个 Skill 测试 + 上下文管理")
    
    user_id = "test_scenario_1"
    session_id = f"scenario1_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    results = []
    
    steps = [
        ("1.1", "什么是光合作用", "explain_skill → 概念讲解"),
        ("1.2", "生成5张闪卡", "flashcard_skill → 继承主题"),
        ("1.3", "出3道选择题", "quiz_skill → 继承主题"),
        ("1.4", "画个思维导图", "mindmap_skill → 继承主题"),
        ("1.5", "帮我做笔记", "notes_skill → 继承主题"),
        ("1.6", "解释一下细胞呼吸", "explain_skill → 主题切换"),
        ("1.7", "再来3道题", "quiz_skill → 多主题澄清"),
    ]
    
    for step_num, message, expected in steps:
        print_step(step_num, message, expected)
        result = await send_message(message, user_id, session_id)
        results.append({
            "step": step_num,
            "message": message,
            "expected": expected,
            **result
        })
        await wait_and_continue(3)
    
    # 如果触发澄清，回复选择 - 使用明确的格式让 Intent Router 能正确解析
    if results[-1].get("content_type") == "clarification_needed":
        # 发送明确的消息，包含动作和主题
        clarification_reply = "出关于光合作用的3道题"
        print_step("1.8", clarification_reply, "选择主题 → 生成题目")
        result = await send_message(clarification_reply, user_id, session_id)
        results.append({
            "step": "1.8",
            "message": clarification_reply,
            "expected": "选择主题后生成题目",
            **result
        })
        await wait_and_continue(3)
    
    # 🆕 引用解析测试
    print("\n" + "=" * 60)
    print("  📎 引用解析测试")
    print("=" * 60 + "\n")
    
    reference_tests = [
        ("1.9", "把第二道题帮我详细解释一下", "reference → quiz[2] → explain"),
        ("1.10", "把第一张闪卡出一道题", "reference → flashcard[1] → quiz"),
    ]
    
    for step_num, message, expected in reference_tests:
        print_step(step_num, message, expected)
        result = await send_message(message, user_id, session_id)
        results.append({
            "step": step_num,
            "message": message,
            "expected": expected,
            **result
        })
        await wait_and_continue(3)
    
    return results


# ============================================================================
# 场景 2: 混合意图测试 + 上下文管理
# ============================================================================
async def scenario_2_mixed_intent():
    """场景 2: 混合意图测试"""
    print_header("场景 2: 混合意图测试 + 上下文管理")
    
    user_id = "test_scenario_2"
    session_id = f"scenario2_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    results = []
    
    steps = [
        ("2.1", "给我一份牛顿第二定律的学习资料", "learning_plan_skill → 完整学习包"),
        ("2.2", "讲解动量守恒然后出题", "learning_plan_skill → 混合意图"),
        ("2.3", "3张闪卡加2道题", "learning_plan_skill → 继承主题或澄清"),
    ]
    
    for step_num, message, expected in steps:
        print_step(step_num, message, expected)
        result = await send_message(message, user_id, session_id)
        results.append({
            "step": step_num,
            "message": message,
            "expected": expected,
            **result
        })
        await wait_and_continue(5)
        
        # 如果触发澄清，回复（使用明确格式避免被解析为新请求）
        if result.get("content_type") == "clarification_needed":
            clarify_msg = "关于动量守恒的学习资料"
            print_step(f"{step_num}b", clarify_msg, "选择主题后继续")
            result2 = await send_message(clarify_msg, user_id, session_id)
            results.append({
                "step": f"{step_num}b",
                "message": clarify_msg,
                "expected": "选择主题后生成",
                **result2
            })
            await wait_and_continue(3)
    
    # 带数量和主题的学习包
    print_step("2.4", "生成5张卡和5道题，关于能量守恒", "learning_plan_skill → 数量+主题提取")
    result = await send_message("生成5张卡和5道题，关于能量守恒", user_id, session_id)
    results.append({
        "step": "2.4",
        "message": "生成5张卡和5道题，关于能量守恒",
        "expected": "数量提取 + 主题提取",
        **result
    })
    
    return results


# ============================================================================
# 场景 3: 真伪思考测试 + 上下文管理
# ============================================================================
async def scenario_3_thinking_modes():
    """场景 3: 真伪思考测试"""
    print_header("场景 3: 真伪思考测试 + 上下文管理")
    
    user_id = "test_scenario_3"
    session_id = f"scenario3_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    results = []
    
    print("📌 验证方法: 查看日志中的模型选择")
    print("   🧠 Real Thinking → 'Using Real Thinking (Kimi)'")
    print("   ⚡ Fake Thinking → 'Using Fake Thinking (Gemini)'")
    
    steps = [
        ("3.1", "什么是相对论", "Real Thinking → 全新 topic"),
        ("3.2", "再来5张闪卡", "Fake Thinking → 重复 topic"),
        ("3.3", "出3道题", "Fake Thinking → 重复 topic"),
        ("3.4", "解释一下量子力学", "Real Thinking → 新 topic"),
        ("3.5", "基于相对论出3道题", "Fake Thinking → 旧 topic (明确主题避免澄清)"),
    ]
    
    for step_num, message, expected in steps:
        print_step(step_num, message, expected)
        result = await send_message(message, user_id, session_id)
        results.append({
            "step": step_num,
            "message": message,
            "expected": expected,
            **result
        })
        await wait_and_continue(3)
    
    return results


# ============================================================================
# 场景 4: 全功能综合测试
# ============================================================================
async def scenario_4_full_test():
    """场景 4: 全功能综合测试"""
    print_header("场景 4: 全功能综合测试 + 上下文管理")
    
    user_id = "test_scenario_4"
    session_id = f"scenario4_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    results = []
    
    # 新用户 Onboarding
    print_section("4.A 新用户 Onboarding")
    print_step("4.1", "出题", "无主题 → 触发 onboarding")
    result = await send_message("出题", user_id, session_id)
    results.append({"step": "4.1", "message": "出题", **result})
    await wait_and_continue(2)
    
    if result.get("content_type") in ["onboarding", "clarification_needed"]:
        print_step("4.2", "二战历史", "选择主题")
        result = await send_message("二战历史", user_id, session_id)
        results.append({"step": "4.2", "message": "二战历史", **result})
        await wait_and_continue(3)
    
    # 单主题深度学习
    print_section("4.B 单主题深度学习")
    
    deep_steps = [
        ("4.3", "详细讲解二战历史", "explain_skill"),
        ("4.4", "做5张闪卡", "flashcard_skill"),
        ("4.5", "出5道选择题", "quiz_skill"),
        ("4.6", "把第2道题详细解释一下", "reference → quiz[2] → explain (引用解析)"),
        ("4.7", "做个思维导图", "mindmap_skill"),
        ("4.8", "整理笔记", "notes_skill"),
    ]
    
    for step_num, message, expected in deep_steps:
        print_step(step_num, message, expected)
        result = await send_message(message, user_id, session_id)
        results.append({"step": step_num, "message": message, "expected": expected, **result})
        await wait_and_continue(3)
    
    # 主题切换
    print_section("4.C 主题切换与澄清")
    
    print_step("4.9", "讲讲珍珠港事件", "主题切换")
    result = await send_message("讲讲珍珠港事件", user_id, session_id)
    results.append({"step": "4.9", "message": "讲讲珍珠港事件", **result})
    await wait_and_continue(3)
    
    print_step("4.10", "出3道题", "多主题澄清测试")
    result = await send_message("出3道题", user_id, session_id)
    results.append({"step": "4.10", "message": "出3道题", **result})
    await wait_and_continue(2)
    
    # 如果触发澄清，回复选择主题
    if result.get("content_type") == "clarification_needed":
        print_step("4.10b", "出关于珍珠港事件的3道题", "选择主题后生成")
        result = await send_message("出关于珍珠港事件的3道题", user_id, session_id)
        results.append({"step": "4.10b", "message": "珍珠港事件3道题", **result})
        await wait_and_continue(3)
    
    # 学习包
    print_section("4.D 学习包测试")
    
    print_step("4.11", "给我一份冷战的完整学习资料，5张卡3道题", "learning_plan_skill")
    result = await send_message("给我一份冷战的完整学习资料，5张卡3道题", user_id, session_id)
    results.append({"step": "4.11", "message": "冷战学习资料", **result})
    
    return results


# ============================================================================
# 主函数
# ============================================================================
async def main():
    """主函数"""
    print("\n" + "🚀" * 40)
    print("\n  Skill Agent Demo - 完整场景测试")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("\n" + "🚀" * 40)
    
    # 选择要运行的场景
    if len(sys.argv) > 1:
        scenario = sys.argv[1]
    else:
        print("\n请选择测试场景:")
        print("  1 - 单个 Skill 测试 + 上下文管理")
        print("  2 - 混合意图测试 + 上下文管理")
        print("  3 - 真伪思考测试 + 上下文管理")
        print("  4 - 全功能综合测试")
        print("  all - 运行所有场景")
        print()
        scenario = input("输入选项 (1/2/3/4/all): ").strip()
    
    all_results = {}
    
    if scenario in ["1", "all"]:
        all_results["scenario_1"] = await scenario_1_single_skills()
    
    if scenario in ["2", "all"]:
        all_results["scenario_2"] = await scenario_2_mixed_intent()
    
    if scenario in ["3", "all"]:
        all_results["scenario_3"] = await scenario_3_thinking_modes()
    
    if scenario in ["4", "all"]:
        all_results["scenario_4"] = await scenario_4_full_test()
    
    # 保存结果
    output_file = OUTPUT_DIR / f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)
    
    print_header("📊 测试完成")
    print(f"📁 结果已保存: {output_file}")
    print(f"\n💡 下一步:")
    print(f"   1. 查看 logs/backend.log 检查 Token 统计")
    print(f"   2. 查看 artifacts/ 目录检查生成的 MD 文件")
    print(f"   3. 将日志和产物发给我进行分析")


if __name__ == "__main__":
    asyncio.run(main())

