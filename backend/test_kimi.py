"""
测试 Kimi (Moonshot AI) API
通过 Novita AI 代理
"""
import asyncio
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.kimi import KimiClient


async def test_non_streaming():
    """测试非流式 API"""
    print("\n" + "="*70)
    print("🧪 测试 1: 非流式生成 (Text)")
    print("="*70)
    
    client = KimiClient()
    
    prompt = "请用一句话解释什么是光合作用。"
    
    result = await client.generate(
        prompt=prompt,
        response_format="text",
        temperature=0.6,
        max_tokens=256,
        return_thinking=True
    )
    
    print(f"\n📝 Content ({len(result['content'])} chars):")
    print(result['content'])
    
    if result['thinking']:
        print(f"\n🧠 Thinking ({len(result['thinking'])} chars):")
        print(result['thinking'][:500] + "..." if len(result['thinking']) > 500 else result['thinking'])
    
    print(f"\n📊 Usage:")
    print(f"  - Prompt tokens: {result['usage']['prompt_tokens']}")
    print(f"  - Completion tokens: {result['usage']['completion_tokens']}")
    print(f"  - Total tokens: {result['usage']['total_tokens']}")


async def test_json_generation():
    """测试 JSON 生成"""
    print("\n" + "="*70)
    print("🧪 测试 2: JSON 格式生成")
    print("="*70)
    
    client = KimiClient()
    
    prompt = """请生成一个关于"牛顿第二定律"的练习题，使用以下 JSON 格式：

{
  "question_id": "q1",
  "question_text": "题目文本",
  "question_type": "choice",
  "options": ["A. 选项1", "B. 选项2", "C. 选项3", "D. 选项4"],
  "correct_answer": "A",
  "explanation": "答案解释"
}

请只返回 JSON，不要有其他文字。"""
    
    result = await client.generate(
        prompt=prompt,
        response_format="json",
        temperature=0.3,
        max_tokens=512
    )
    
    print(f"\n📝 Content (JSON):")
    import json
    if isinstance(result['content'], dict):
        print(json.dumps(result['content'], indent=2, ensure_ascii=False))
    else:
        print(result['content'])


async def test_streaming():
    """测试流式 API"""
    print("\n" + "="*70)
    print("🧪 测试 3: 流式生成 + Reasoning")
    print("="*70)
    
    client = KimiClient()
    
    prompt = "请详细解释什么是牛顿第二定律，包括公式、含义和应用。"
    
    print("\n🌊 开始流式生成...")
    print("-" * 70)
    
    thinking_parts = []
    content_parts = []
    
    async for chunk in client.generate_stream(
        prompt=prompt,
        temperature=0.6,
        max_tokens=1024,
        return_thinking=True
    ):
        if chunk["type"] == "thinking":
            thinking_parts.append(chunk["text"])
            print(f"🧠 Thinking: {chunk['text'][:50]}...")
        
        elif chunk["type"] == "content":
            content_parts.append(chunk["text"])
            print(chunk["text"], end="", flush=True)
        
        elif chunk["type"] == "done":
            print("\n" + "-" * 70)
            print(f"\n✅ 生成完成！")
            print(f"📊 Final thinking: {len(chunk['thinking'])} chars")
            print(f"📊 Final content: {len(chunk['content'])} chars")
        
        elif chunk["type"] == "error":
            print(f"\n❌ 错误: {chunk['error']}")


async def main():
    """运行所有测试"""
    print("\n" + "="*70)
    print("🚀 Kimi (Moonshot AI) API 测试套件")
    print("📍 Provider: Novita AI")
    print("🤖 Model: moonshotai/kimi-k2-thinking")
    print("="*70)
    
    try:
        # 测试 1: 非流式
        await test_non_streaming()
        
        # 等待一下
        await asyncio.sleep(2)
        
        # 测试 2: JSON 生成
        await test_json_generation()
        
        # 等待一下
        await asyncio.sleep(2)
        
        # 测试 3: 流式
        await test_streaming()
        
        print("\n" + "="*70)
        print("✅ 所有测试完成！")
        print("="*70 + "\n")
    
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())

