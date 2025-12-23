"""
Markdown Formatter - 将 agent responses 格式化为 Markdown

支持的类型：
- explanation
- quiz_set
- flashcard_set
- notes
- mindmap
- learning_bundle (plan skill)
"""

import json
import logging
from typing import Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class MarkdownFormatter:
    """将 artifact 转换为 Markdown 格式"""
    
    def format_turn(self, turn_data: Dict[str, Any]) -> str:
        """
        格式化一个完整的 Turn
        
        Args:
            turn_data: {
                "turn_number": int,
                "timestamp": datetime,
                "user_query": str,
                "agent_response": Dict[str, Any],
                "response_type": str,
                "intent": Dict[str, Any],
                "metadata": Dict[str, Any]
            }
        
        Returns:
            Markdown 格式的 turn
        """
        turn_num = turn_data["turn_number"]
        timestamp = turn_data["timestamp"]
        if isinstance(timestamp, datetime):
            timestamp_str = timestamp.strftime("%H:%M:%S")
        else:
            timestamp_str = timestamp
        
        user_query = turn_data["user_query"]
        response_type = turn_data["response_type"]
        agent_response = turn_data.get("agent_response", {})
        intent = turn_data.get("intent", {})
        
        # Turn 头部
        md = f"""## Turn {turn_num} - {timestamp_str}

### 👤 User Query
{user_query}

### 🤖 Agent Response
"""
        
        # 添加响应元信息
        # 🆕 优先从 agent_response 获取 topic（实际 API 返回的），再 fallback 到 intent
        topic = agent_response.get("topic") or intent.get("topic") or "N/A"
        skill = agent_response.get("skill", "unknown")
        
        md += f"**Type**: {response_type} | **Topic**: {topic} | **Skill**: {skill}"
        
        # 添加数量信息（如果有）
        if response_type == "quiz_set" and "num_questions" in intent:
            md += f" | **Quantity**: {intent['num_questions']} questions"
        elif response_type == "flashcard_set" and "num_cards" in intent:
            md += f" | **Quantity**: {intent['num_cards']} cards"
        
        # 添加上下文引用（如果有）
        if intent.get("use_last_artifact"):
            md += f"  \n**Context**: 📎 Based on previous content"
        
        md += "\n\n"
        
        # 根据类型格式化内容
        content = agent_response.get("content", {})
        
        if response_type == "explanation":
            md += self._format_explanation(content)
        elif response_type == "quiz_set":
            md += self._format_quiz(content)
        elif response_type == "flashcard_set":
            md += self._format_flashcard(content)
        elif response_type == "notes":
            md += self._format_notes(content)
        elif response_type == "mindmap":
            md += self._format_mindmap(content)
        elif response_type == "learning_bundle":
            md += self._format_learning_bundle(content)
        else:
            md += f"```json\n{json.dumps(content, ensure_ascii=False, indent=2)}\n```\n\n"
        
        # 嵌入 JSON 结构化数据
        md += self._embed_json(turn_data)
        
        return md
    
    def _format_explanation(self, content: Dict[str, Any]) -> str:
        """格式化 explanation"""
        md = ""
        
        # 直觉理解
        if "intuition" in content:
            md += f"#### 📚 直觉理解\n{content['intuition']}\n\n"
        
        # 正式定义
        if "formal_definition" in content:
            md += f"#### 📖 正式定义\n{content['formal_definition']}\n\n"
        
        # 为什么重要
        if "why_it_matters" in content:
            md += f"#### 💡 为什么重要\n{content['why_it_matters']}\n\n"
        
        # 实例
        if "examples" in content and content["examples"]:
            md += "#### 🌟 实例\n"
            for i, example in enumerate(content["examples"], 1):
                if isinstance(example, dict):
                    md += f"{i}. **{example.get('example', 'Example')}**：{example.get('explanation', '')}\n\n"
                else:
                    md += f"{i}. {example}\n\n"
        
        # 常见误区
        if "common_mistakes" in content and content["common_mistakes"]:
            md += "#### ⚠️ 常见误区\n"
            for i, mistake in enumerate(content["common_mistakes"], 1):
                if isinstance(mistake, dict):
                    md += f"{i}. **误区**：{mistake.get('mistake', '')}\n"
                    md += f"   **纠正**：{mistake.get('correction', '')}\n\n"
                else:
                    md += f"{i}. {mistake}\n\n"
        
        # 相关概念
        if "related_concepts" in content and content["related_concepts"]:
            md += "#### 🔗 相关概念\n"
            for concept in content["related_concepts"]:
                md += f"- {concept}\n"
            md += "\n"
        
        return md
    
    def _format_quiz(self, content: Dict[str, Any]) -> str:
        """格式化 quiz - 🔥 兼容新格式 (外部API) 和旧格式 (LLM)"""
        md = ""
        
        # 标题（新格式使用 title，旧格式使用 subject）
        title = content.get("title") or content.get("subject", "")
        if title:
            md += f"### 📝 {title}\n\n"
        
        questions = content.get("questions", [])
        
        for i, q in enumerate(questions, 1):
            # 🔥 兼容新旧格式：question (新) vs question_text (旧)
            question_text = q.get("question") or q.get("question_text", "N/A")
            
            # 🔥 兼容新旧格式：answer_options (新) vs options (旧)
            answer_options = q.get("answer_options") or q.get("options", [])
            
            # 检测是否是新格式（answer_options 包含 is_correct）
            is_new_format = answer_options and isinstance(answer_options[0], dict) and "is_correct" in answer_options[0]
            
            # 获取题目类型
            question_type = q.get("question_type", "choice" if answer_options else "unknown")
            
            md += f"#### Question {i}\n"
            md += f"**题目**：{question_text}\n\n"
            
            if is_new_format:
                # 🆕 新格式：外部 API 返回的格式
                md += "**选项**：\n"
                for opt_idx, opt in enumerate(answer_options):
                    label = chr(65 + opt_idx)  # A, B, C, D...
                    text = opt.get("text", "")
                    is_correct = opt.get("is_correct", False)
                    rationale = opt.get("rationale", "")
                    
                    if is_correct:
                        md += f"- **{label}. {text}** ✅\n"
                    else:
                        md += f"- {label}. {text}\n"
                md += "\n"
                
                # 显示提示（如果有）
                hint = q.get("hint", "")
                if hint:
                    md += f"**💡 提示**：{hint}\n\n"
                
                # 显示正确答案和解析
                for opt_idx, opt in enumerate(answer_options):
                    if opt.get("is_correct"):
                        label = chr(65 + opt_idx)
                        md += f"**正确答案**：{label}\n\n"
                        if opt.get("rationale"):
                            md += f"**解析**：{opt['rationale']}\n\n"
                        break
            
            elif answer_options:
                # 旧格式：LLM 返回的格式
                md += "**选项**：\n"
                correct_answer = q.get("correct_answer", "")
                
                for option in answer_options:
                    if isinstance(option, str):
                        label = option[0] if len(option) > 0 and option[0] in "ABCDEFGH" else ""
                        is_correct = label == correct_answer
                        md += f"- {option} {'✅' if is_correct else ''}\n"
                    else:
                        label = option.get("label", "")
                        text = option.get("text", "")
                        is_correct = label == correct_answer
                        md += f"- {label}. {text} {'✅' if is_correct else ''}\n"
                md += "\n"
                md += f"**答案**：{correct_answer}\n\n"
            
            elif question_type == "true_false":
                correct = q.get("correct_answer", None)
                if correct is True or correct == "正确":
                    md += "**答案**：正确 ✅\n\n"
                elif correct is False or correct == "错误":
                    md += "**答案**：错误 ❌\n\n"
                else:
                    md += f"**答案**：{correct}\n\n"
            
            elif question_type in ["short_answer", "fill_in"]:
                md += f"**参考答案**：{q.get('correct_answer', 'N/A')}\n\n"
            
            # 解析（旧格式）
            if "explanation" in q:
                md += f"**解析**：{q['explanation']}\n\n"
            
            md += "---\n\n"
        
        return md
    
    def _translate_question_type(self, qtype: str) -> str:
        """翻译题型"""
        mapping = {
            # 标准格式
            "multiple_choice": "选择题",
            "true_false": "判断题",
            "short_answer": "简答题",
            "fill_in_blank": "填空题",
            # LLM 实际返回的格式（兼容）
            "choice": "选择题",
            "fill_in": "填空题"
        }
        return mapping.get(qtype, qtype)
    
    def _format_flashcard(self, content: Dict[str, Any]) -> str:
        """格式化 flashcard - 🔥 新格式 (title + cardList)"""
        md = ""
        
        # 标题（新格式使用 title，旧格式使用 topic）
        title = content.get("title") or content.get("topic", "闪卡集合")
        md += f"### 📚 {title}\n\n"
        
        # 兼容新旧格式
        cards = content.get("cardList") or content.get("cards", [])
        
        for i, card in enumerate(cards, 1):
            md += f"#### 🃏 Flashcard {i}\n\n"
            
            # 正面
            md += f"**正面**：\n```\n{card.get('front', 'N/A')}\n```\n\n"
            
            # 背面
            md += f"**背面**：\n```\n{card.get('back', 'N/A')}\n```\n\n"
            
            md += "---\n\n"
        
        return md
    
    def _translate_difficulty(self, difficulty: str) -> str:
        """翻译难度"""
        mapping = {
            "easy": "简单",
            "medium": "中等",
            "hard": "困难"
        }
        return mapping.get(difficulty, difficulty)
    
    def _format_notes(self, content: Dict[str, Any]) -> str:
        """格式化 notes"""
        md = ""
        
        # 主题
        if "topic" in content:
            md += f"**主题**: {content['topic']}\n\n"
        
        # 核心要点
        if "core_points" in content and content["core_points"]:
            md += "#### 📌 核心要点\n"
            for point in content["core_points"]:
                md += f"- {point}\n"
            md += "\n"
        
        # 详细笔记
        if "detailed_notes" in content:
            md += f"#### 📝 详细笔记\n{content['detailed_notes']}\n\n"
        
        # 关键术语
        if "key_terms" in content and content["key_terms"]:
            md += "#### 📚 关键术语\n"
            for term, definition in content["key_terms"].items():
                md += f"- **{term}**: {definition}\n"
            md += "\n"
        
        return md
    
    def _format_mindmap(self, content: Dict[str, Any]) -> str:
        """格式化 mindmap"""
        md = ""
        
        # 中心主题
        if "central_topic" in content:
            md += f"#### 🌳 中心主题\n**{content['central_topic']}**\n\n"
        
        # 分支结构（简化展示）
        if "branches" in content and content["branches"]:
            md += "#### 🌿 主要分支\n"
            for branch in content["branches"]:
                if isinstance(branch, dict):
                    md += f"- **{branch.get('label', 'N/A')}**"
                    if "children" in branch and branch["children"]:
                        md += f" ({len(branch['children'])} 个子节点)"
                    md += "\n"
                else:
                    md += f"- {branch}\n"
            md += "\n"
        
        md += "> 💡 完整的思维导图可在前端交互式查看\n\n"
        
        return md
    
    def _format_learning_bundle(self, content: Dict[str, Any]) -> str:
        """格式化 learning bundle (plan skill)"""
        md = ""
        
        # 显示学习包标题
        topic = content.get("topic", "学习内容")
        md += f"#### 📦 学习包: {topic}\n\n"
        
        # 显示学习时间
        time_mins = content.get("estimated_time_minutes", 0)
        if time_mins:
            md += f"⏱️ 预计学习时间: {time_mins} 分钟\n\n"
        
        # 🔥 兼容两种格式：steps (旧) 和 components (新)
        components = content.get("components", content.get("steps", []))
        
        for i, comp in enumerate(components, 1):
            # 兼容两种键名：component_type (新) 和 type (旧)
            comp_type = comp.get("component_type", comp.get("type", "unknown"))
            # 兼容两种键名：content (新) 和 result (旧)
            comp_content = comp.get("content", comp.get("result", {}))
            
            md += f"##### {i}. {self._translate_step_type(comp_type)}\n\n"
            
            # 根据组件类型格式化
            if comp_type in ["explain", "explanation"]:
                md += self._format_explanation(comp_content)
            elif comp_type in ["quiz", "quiz_set"]:
                md += self._format_quiz(comp_content)
            elif comp_type in ["flashcard", "flashcard_set"]:
                md += self._format_flashcard(comp_content)
            elif comp_type == "notes":
                md += self._format_notes(comp_content)
            elif comp_type == "mindmap":
                md += self._format_mindmap(comp_content)
            else:
                # 未知类型，显示 JSON
                md += f"```json\n{json.dumps(comp_content, ensure_ascii=False, indent=2)[:500]}...\n```\n"
            
            md += "\n---\n\n"
        
        # 显示学习路径
        learning_path = content.get("learning_path", [])
        if learning_path:
            md += "#### 📚 学习建议\n"
            for step in learning_path[:3]:  # 只显示前3条
                md += f"- {step}\n"
            md += "\n"
        
        return md
    
    def _translate_step_type(self, step_type: str) -> str:
        """翻译步骤类型"""
        mapping = {
            "explain": "概念讲解",
            "quiz": "练习题",
            "flashcard": "记忆卡片",
            "notes": "学习笔记",
            "mindmap": "思维导图"
        }
        return mapping.get(step_type, step_type)
    
    def _embed_json(self, turn_data: Dict[str, Any]) -> str:
        """
        嵌入 JSON 结构化数据（使用 <details> 折叠）
        
        Args:
            turn_data: 完整的 turn 数据
        
        Returns:
            <details> + JSON 代码块
        """
        # 构建 JSON 数据
        json_data = {
            "turn_number": turn_data["turn_number"],
            "timestamp": turn_data["timestamp"].isoformat() if isinstance(turn_data["timestamp"], datetime) else turn_data["timestamp"],
            "user_query": turn_data["user_query"],
            "intent": turn_data.get("intent", {}),
            "agent_response": turn_data.get("agent_response", {}),
            "metadata": turn_data.get("metadata", {}),
            # 🆕 添加附件信息（包含 referenced_text、files 等）
            "attachments": turn_data.get("attachments")
        }
        
        json_str = json.dumps(json_data, ensure_ascii=False, indent=2)
        
        embedded = f"""
<details>
<summary>📦 <b>结构化数据（JSON）</b> - 点击展开</summary>

```json
{json_str}
```

</details>
"""
        
        return embedded

