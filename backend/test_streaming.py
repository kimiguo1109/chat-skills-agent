"""
测试流式生成功能
"""
import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(__file__))

from app.services.gemini import GeminiClient
from app.core.intent_router import IntentRouter
from app.core.skill_orchestrator import SkillOrchestrator
from app.dependencies import get_memory_manager, get_gemini_client

async def test_gemini_stream():
    """测试 Gemini 流式 API"""
    print("\n" + "="*60)
    print("🧪 测试 1: Gemini 流式生成")
    print("="*60 + "\n")
    
    client = GeminiClient()
    
    prompt = """请生成5道关于光合作用的选择题。

在思考后，必须输出完整的JSON格式内容。

要求的JSON格式：
{
  "quiz_set_id": "quiz_biology_001",
  "topic": "光合作用",
  "questions": [
    {
      "question_text": "题目",
      "options": ["A选项", "B选项", "C选项", "D选项"],
      "correct_answer": "A",
      "explanation": "解释"
    }
  ]
}

请在思考完毕后，立即输出上述JSON格式的内容。不要只输出思考过程。
"""
    
    print("📝 Prompt:", prompt[:100] + "...")
    print("\n🌊 开始流式生成...\n")
    
    thinking_parts = []
    content_parts = []
    
    try:
        async for chunk in client.generate_stream(
            prompt=prompt,
            thinking_budget=256  # 🔧 降低thinking预算，确保有内容输出
        ):
            chunk_type = chunk['type']
            
            if chunk_type == 'thinking':
                text = chunk.get('text', '')
                thinking_parts.append(text)
                print(f"💭 [思考] {text[:80]}...")
                
            elif chunk_type == 'content':
                text = chunk.get('text', '')
                content_parts.append(text)
                print(f"📝 [内容] {text[:80]}...")
                
            elif chunk_type == 'done':
                print(f"\n✅ 完成！")
                print(f"  - 思考长度: {len(''.join(thinking_parts))} 字符")
                print(f"  - 内容长度: {len(''.join(content_parts))} 字符")
                
            elif chunk_type == 'error':
                print(f"\n❌ 错误: {chunk.get('error', 'Unknown')}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_orchestrator_stream():
    """测试 Orchestrator 流式编排"""
    print("\n" + "="*60)
    print("🧪 测试 2: Orchestrator 流式编排")
    print("="*60 + "\n")
    
    # 初始化组件
    gemini_client = get_gemini_client()
    memory_manager = get_memory_manager()
    orchestrator = SkillOrchestrator(
        gemini_client=gemini_client,
        memory_manager=memory_manager
    )
    intent_router = IntentRouter(gemini_client=gemini_client)
    
    # 模拟用户请求
    user_message = "给我5道光合作用的题"
    user_id = "test-user"
    session_id = "test-session"
    
    print(f"👤 用户消息: {user_message}\n")
    
    # Step 1: 意图识别
    print("🔍 Step 1: 意图识别...")
    intent_results = await intent_router.parse(user_message)
    
    if not intent_results:
        print("❌ 意图识别失败")
        return False
    
    intent_result = intent_results[0]
    print(f"✅ 意图: {intent_result.intent}, 主题: {intent_result.topic}\n")
    
    # Step 2: 流式执行
    print("🌊 Step 2: 流式执行...\n")
    
    event_count = 0
    
    try:
        async for event in orchestrator.execute_stream(
            intent_result=intent_result,
            user_id=user_id,
            session_id=session_id
        ):
            event_count += 1
            event_type = event.get('type')
            
            if event_type == 'status':
                print(f"📊 [状态] {event.get('message')}")
                
            elif event_type == 'thinking':
                text = event.get('text', '')
                print(f"💭 [思考] {text[:80]}...")
                
            elif event_type == 'content':
                text = event.get('text', '')
                print(f"📝 [内容] {text[:80]}...")
                
            elif event_type == 'done':
                print(f"\n✅ 完成！")
                content = event.get('content', {})
                print(f"  - 内容类型: {event.get('content_type')}")
                # 🔧 修复：检查content类型
                if isinstance(content, dict):
                    questions = content.get('questions', [])
                    print(f"  - 生成题目数: {len(questions)}")
                elif isinstance(content, str):
                    print(f"  - 内容是字符串: {len(content)} 字符")
                else:
                    print(f"  - 内容类型: {type(content)}")
                
            elif event_type == 'error':
                print(f"\n❌ 错误: {event.get('message')}")
                return False
        
        print(f"\n📊 总事件数: {event_count}")
        return True
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """运行所有测试"""
    print("\n" + "="*60)
    print("🚀 流式生成功能测试")
    print("="*60)
    
    results = []
    
    # 测试 1: Gemini Stream
    result1 = await test_gemini_stream()
    results.append(("Gemini 流式生成", result1))
    
    await asyncio.sleep(1)
    
    # 测试 2: Orchestrator Stream
    result2 = await test_orchestrator_stream()
    results.append(("Orchestrator 流式编排", result2))
    
    # 总结
    print("\n" + "="*60)
    print("📊 测试总结")
    print("="*60)
    
    for name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {status} - {name}")
    
    all_passed = all(r[1] for r in results)
    
    if all_passed:
        print("\n🎉 所有测试通过！")
        return 0
    else:
        print("\n⚠️  部分测试失败")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

