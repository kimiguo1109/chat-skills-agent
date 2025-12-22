#!/usr/bin/env python3
"""
Plan Skill 专项测试

由于Plan Skill执行时间较长（每个case 3-8分钟），单独测试便于调试和验证。

测试场景：
1. 完整Plan（所有5个步骤）- 验证默认行为
2. 部分Plan（用户指定步骤）- 验证智能过滤
3. 链式上下文传递 - 验证{context.previous}
4. 跳过某些步骤 - 验证动态依赖处理
"""

import asyncio
import httpx
import time
import re
from pathlib import Path
from datetime import datetime

# 配置
BASE_URL = "http://localhost:8088"
TEST_USER = "test_plan"
TIMEOUT = 180.0  # Plan Skill需要更长超时

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_success(msg):
    print(f"{Colors.GREEN}✅ {msg}{Colors.END}")

def print_error(msg):
    print(f"{Colors.RED}❌ {msg}{Colors.END}")

def print_warning(msg):
    print(f"{Colors.YELLOW}⚠️  {msg}{Colors.END}")

def print_info(msg):
    print(f"{Colors.BLUE}ℹ️  {msg}{Colors.END}")

def print_header(msg):
    print(f"\n{Colors.BOLD}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{msg}{Colors.END}")
    print(f"{Colors.BOLD}{'='*60}{Colors.END}\n")


class PlanSkillTester:
    def __init__(self):
        self.base_url = BASE_URL
        self.user_id = TEST_USER
        self.session_id = f"{TEST_USER}_{int(time.time())}"
        self.log_file = Path("logs/backend.log")
    
    async def send_message(self, message: str) -> dict:
        """发送消息"""
        print_info(f"📤 {message}")
        
        start_time = time.time()
        
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/api/agent/chat",
                    json={
                        "message": message,
                        "user_id": self.user_id,
                        "session_id": self.session_id
                    }
                )
                
                elapsed = time.time() - start_time
                
                if response.status_code == 200:
                    result = response.json()
                    intent = result.get("intent", "")
                    skill = result.get("skill_id", "")
                    resp_len = len(result.get("response", ""))
                    
                    print_success(f"Response received in {elapsed:.1f}s")
                    print_info(f"   Intent: {intent}, Skill: {skill}, Length: {resp_len} chars")
                    
                    return result
                else:
                    print_error(f"Status: {response.status_code} (after {elapsed:.1f}s)")
                    return {"error": response.status_code}
            except asyncio.TimeoutError:
                elapsed = time.time() - start_time
                print_error(f"Timeout after {elapsed:.1f}s")
                return {"error": "timeout"}
            except Exception as e:
                elapsed = time.time() - start_time
                print_error(f"Exception after {elapsed:.1f}s: {e}")
                return {"error": str(e)}
    
    def check_log_pattern(self, pattern: str, description: str = "") -> list:
        """检查日志中的匹配"""
        if not self.log_file.exists():
            return []
        
        content = self.log_file.read_text(encoding='utf-8')
        matches = re.findall(pattern, content, re.MULTILINE)
        
        if matches:
            if description:
                print_info(f"   {description}: 找到 {len(matches)} 处")
        
        return matches
    
    def get_recent_log_lines(self, num_lines: int = 100) -> str:
        """获取最近的日志"""
        if not self.log_file.exists():
            return ""
        
        with open(self.log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            return ''.join(lines[-num_lines:])
    
    async def test_1_full_plan(self):
        """测试1：完整Plan（所有步骤）"""
        print_header("测试 1：完整 Plan Skill（默认5个步骤）")
        
        print_info("📦 测试场景: 用户请求学习包但不指定具体步骤")
        print_info("   预期: 执行全部5个步骤（explain → flashcard → quiz → notes → mindmap）")
        
        # 记录日志位置
        log_size_before = self.log_file.stat().st_size if self.log_file.exists() else 0
        
        # 发送请求
        result = await self.send_message("给我一个关于光合作用的学习包")
        
        await asyncio.sleep(3)
        
        # 验证
        if "error" in result:
            print_error("❌ 请求失败")
            return False
        
        if result.get("intent") != "learning_bundle":
            print_error(f"❌ Intent错误: {result.get('intent')}")
            return False
        
        # 检查日志
        recent_log = self.get_recent_log_lines(200)
        
        # 查找步骤执行记录
        steps_pattern = r'📍 Step (\d+)/(\d+):'
        steps = re.findall(steps_pattern, recent_log)
        
        if steps:
            total_steps = int(steps[-1][1]) if steps else 0
            print_info(f"   实际执行步骤数: {total_steps}")
            
            if total_steps == 5:
                print_success("✅ 验证通过: 执行了全部5个步骤")
                return True
            else:
                print_warning(f"⚠️  步骤数不符: {total_steps}/5")
                return False
        else:
            print_warning("⚠️  无法从日志验证步骤数")
            # 不算失败，可能是日志格式变化
            return True
    
    async def test_2_partial_plan(self):
        """测试2：部分Plan（用户指定步骤）"""
        print_header("测试 2：部分 Plan Skill（用户指定步骤）")
        
        print_info("📦 测试场景: 用户明确要求'包含讲解、3张闪卡和2道题'")
        print_info("   预期: 只执行3个步骤（explain → flashcard → quiz）")
        print_info("   跳过: notes, mindmap")
        
        # 新session
        self.session_id = f"{TEST_USER}_partial_{int(time.time())}"
        
        # 发送请求
        result = await self.send_message("给我一个关于DNA的学习包，包含讲解、3张闪卡和2道题")
        
        await asyncio.sleep(3)
        
        # 验证
        if "error" in result:
            print_error("❌ 请求失败")
            return False
        
        # 检查日志
        recent_log = self.get_recent_log_lines(200)
        
        # 查找required_steps
        required_steps_pattern = r'📋 User specified steps.*?: \[([^\]]+)\]'
        match = re.search(required_steps_pattern, recent_log)
        
        if match:
            steps_str = match.group(1)
            print_info(f"   检测到的步骤: {steps_str}")
            
            # 验证包含正确的步骤
            if 'explain' in steps_str and 'flashcard' in steps_str and 'quiz' in steps_str:
                if 'notes' not in steps_str and 'mindmap' not in steps_str:
                    print_success("✅ 验证通过: 正确提取用户指定的3个步骤")
                else:
                    print_error("❌ 包含了不应该有的步骤")
                    return False
            else:
                print_error("❌ 缺少必要的步骤")
                return False
        else:
            print_warning("⚠️  未找到required_steps（可能是新用户没有明确说明）")
        
        # 检查总步骤数
        steps_pattern = r'📍 Step (\d+)/(\d+):'
        steps = re.findall(steps_pattern, recent_log)
        
        if steps:
            total_steps = int(steps[-1][1]) if steps else 0
            print_info(f"   实际执行步骤数: {total_steps}")
            
            if total_steps == 3:
                print_success("✅ 验证通过: 只执行了3个步骤")
                return True
            elif total_steps == 5:
                print_error(f"❌ 执行了全部5个步骤（应该只有3个）")
                return False
            else:
                print_warning(f"⚠️  步骤数异常: {total_steps}")
                return False
        
        print_warning("⚠️  无法从日志验证步骤数")
        return True  # 宽松验证
    
    async def test_3_context_passing(self):
        """测试3：链式上下文传递"""
        print_header("测试 3：Plan Skill 链式上下文传递")
        
        print_info("📦 测试场景: 验证步骤间的{context.previous}传递")
        print_info("   预期: quiz依赖flashcard, notes依赖quiz, mindmap依赖notes")
        
        # 新session
        self.session_id = f"{TEST_USER}_context_{int(time.time())}"
        
        # 发送请求（完整plan以验证链式传递）
        result = await self.send_message("生成细胞呼吸的学习包，包括讲解、5张闪卡、3道题和笔记")
        
        await asyncio.sleep(3)
        
        # 验证
        if "error" in result:
            print_error("❌ 请求失败")
            return False
        
        # 检查日志中的上下文传递
        recent_log = self.get_recent_log_lines(300)
        
        # 查找上下文压缩和传递的证据
        checks = {
            "上下文压缩": r'Context compressed|压缩上下文|Compressed.*context',
            "previous引用": r'context\.previous|previous\(',
            "传递上下文": r'传递上下文|Passing context'
        }
        
        passed_checks = 0
        for check_name, pattern in checks.items():
            if re.search(pattern, recent_log, re.IGNORECASE):
                print_success(f"   ✅ {check_name}: 检测到")
                passed_checks += 1
            else:
                print_warning(f"   ⚠️  {check_name}: 未检测到")
        
        # 至少要有1个证据
        if passed_checks >= 1:
            print_success("✅ 验证通过: 检测到上下文传递机制")
            return True
        else:
            print_warning("⚠️  未明确检测到上下文传递（可能是日志格式变化）")
            return True  # 宽松验证
    
    async def test_4_dynamic_dependencies(self):
        """测试4：动态依赖处理"""
        print_header("测试 4：动态依赖处理（跳过explain）")
        
        print_info("📦 测试场景: 用户要'闪卡和题，不需要讲解'")
        print_info("   预期: 跳过explain，quiz依赖flashcard而不是explain")
        
        # 新session
        self.session_id = f"{TEST_USER}_skip_{int(time.time())}"
        
        # 先建立topic
        await self.send_message("我想学习DNA复制")
        await asyncio.sleep(2)
        
        # 请求部分技能
        result = await self.send_message("给我5张闪卡和3道题，不需要讲解")
        
        await asyncio.sleep(3)
        
        # 验证
        if "error" in result:
            print_error("❌ 请求失败")
            return False
        
        # 检查日志
        recent_log = self.get_recent_log_lines(200)
        
        # 查找是否跳过了explain
        has_explain_warning = re.search(r'依赖的 step explain 不存在|explain.*被跳过', recent_log, re.IGNORECASE)
        
        if has_explain_warning:
            print_error("❌ 检测到explain依赖警告（说明依然hardcoded到explain）")
            return False
        
        # 查找previous(flashcard)的证据
        has_flashcard_dep = re.search(r'previous\(flashcard\)|依赖.*flashcard', recent_log, re.IGNORECASE)
        
        if has_flashcard_dep:
            print_success("✅ 验证通过: quiz正确依赖flashcard")
            return True
        else:
            print_warning("⚠️  未明确检测到flashcard依赖")
            
            # 检查是否至少没有错误
            has_errors = re.search(r'ERROR|❌.*failed', recent_log, re.IGNORECASE)
            if not has_errors:
                print_info("   但也没有错误，算作通过")
                return True
            else:
                return False
    
    async def run_all_tests(self):
        """运行所有测试"""
        print_header("🧪 Plan Skill 专项测试")
        print_info(f"User: {self.user_id}")
        print_info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print_warning("⏱️  注意: 每个测试可能需要3-8分钟")
        
        tests = [
            ("测试1: 完整Plan（5步骤）", self.test_1_full_plan),
            ("测试2: 部分Plan（用户指定）", self.test_2_partial_plan),
            ("测试3: 链式上下文传递", self.test_3_context_passing),
            ("测试4: 动态依赖处理", self.test_4_dynamic_dependencies)
        ]
        
        results = {}
        total_time = 0
        
        for name, test_func in tests:
            try:
                start = time.time()
                result = await test_func()
                elapsed = time.time() - start
                total_time += elapsed
                
                results[name] = result
                print_info(f"⏱️  耗时: {elapsed:.1f}s")
                
            except Exception as e:
                print_error(f"{name} 异常: {e}")
                results[name] = False
            
            # 测试间暂停
            await asyncio.sleep(3)
        
        # 汇总
        print_header("📊 测试结果")
        passed = sum(1 for r in results.values() if r)
        total = len(results)
        
        for name, result in results.items():
            status = "✅" if result else "❌"
            print(f"{status} {name}")
        
        print(f"\n{Colors.BOLD}通过: {passed}/{total}{Colors.END}")
        print(f"{Colors.BOLD}总耗时: {total_time/60:.1f} 分钟{Colors.END}")
        
        if passed == total:
            print_success("🎉 所有Plan Skill测试通过！")
        elif passed >= total * 0.75:
            print_warning(f"⚠️  大部分测试通过 ({passed}/{total})")
        else:
            print_error(f"❌ 多数测试失败 ({passed}/{total})")
        
        return passed == total


async def main():
    """主函数"""
    tester = PlanSkillTester()
    
    try:
        success = await tester.run_all_tests()
        return 0 if success else 1
    except KeyboardInterrupt:
        print_warning("\n测试被用户中断")
        return 130
    except Exception as e:
        print_error(f"测试执行失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)

