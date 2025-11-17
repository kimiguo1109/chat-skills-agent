# Tasks Document - Skill Agent Demo

本文档将 Skill Agent Demo 拆解为可执行的开发任务。任务按依赖关系和优先级组织。

---

## 📊 进度概览

**最后更新**: 2025-11-14 (Phase 7 规划完成)

| Phase | 状态 | 完成度 | 说明 |
|-------|------|--------|------|
| Phase 1: 项目基础设施 | ✅ 完成 | 5/5 (100%) | 后端+前端基础搭建完成，43个测试通过 |
| Phase 2: 核心模块 | ✅ 完成 | 4/4 (100%) | Intent Router ✅, Memory Manager ✅, Skill Registry ✅, Orchestrator ✅ (79个测试通过) |
| Phase 3: 技能实现 | ✅ 完成 | 2/2 (100%) | Quiz Skill ✅ (配置+Prompt), Explain Skill ✅ (配置+Prompt), 13个集成测试通过 |
| Phase 4: Agent API | ✅ 完成 | 1/1 (100%) | /api/agent/chat 端点 ✅, 依赖注入 ✅, 11个API测试通过 |
| Phase 5: 前端组件 | ✅ 完成 | 9/9 (100%) | 所有组件完成：Context, Hooks, Layout, Chat, Artifacts, Theme ✅ |
| Phase 6: 集成测试 | ⏳ 待开始 | 0/4 (0%) | 端到端测试 |
| Phase 7: 用户认证与持久化 | 🆕 ⏳ 待开始 | 0/10 (0%) | JWT认证、SQLite持久化、登录注册界面 |

**总体进度**: 21/31 任务完成 (68%) | **Phase 1-5**: 100% ✅ | **Phase 6-7**: 0%
**测试统计**: 146 个后端测试通过 (0.21秒), 前端编译通过 (247KB, 749ms)

---

## Phase 1: 项目基础设施搭建 ✅ COMPLETED

### Backend Setup

- [x] 1.1. Initialize backend project structure
  - Files: 
    - `backend/app/main.py`
    - `backend/app/config.py`
    - `backend/requirements.txt`
    - `backend/.env.example`
  - Create FastAPI application entry point with CORS configuration
  - Set up environment variable management using Pydantic Settings
  - Add basic health check endpoint
  - Purpose: Establish backend foundation with proper configuration management
  - _Leverage: N/A (new project)_
  - _Requirements: Non-functional - Code Architecture_
  - _Prompt: Role: Backend Developer specializing in FastAPI and Python project architecture | Task: Initialize FastAPI backend project following requirement "Code Architecture and Modularity", creating main.py with CORS setup, config.py for environment variables (GEMINI_API_KEY, CORS_ORIGINS, LOG_LEVEL), requirements.txt with FastAPI 0.115+, Pydantic 2.0+, google-generativeai, and .env.example template | Restrictions: Do not hardcode sensitive values, use Pydantic BaseSettings for config, follow FastAPI best practices for dependency injection | Success: Server starts successfully, health check endpoint returns 200, CORS is properly configured, environment variables are loaded correctly, requirements.txt includes all necessary dependencies_

- [x] 1.2. Create Pydantic base models
  - Files:
    - `backend/app/models/__init__.py`
    - `backend/app/models/intent.py`
    - `backend/app/models/memory.py`
    - `backend/app/models/skill.py`
    - `backend/app/models/artifact.py`
    - `backend/app/models/api.py`
  - Define all Pydantic models as specified in Design document
  - Include field validation and descriptions
  - Purpose: Establish type-safe data structures for entire backend
  - _Leverage: Pydantic V2 features (Field, ConfigDict)_
  - _Requirements: 2.1, 2.2, 2.3, 2.4_
  - _Prompt: Role: Backend Developer with expertise in Pydantic V2 data validation | Task: Create comprehensive Pydantic models covering requirements 2.1-2.4 (Intent, Memory, Skill, Artifact, API models) following the exact schemas defined in the Design document's "Data Models" section, using Pydantic Field for descriptions and validation | Restrictions: Must use Pydantic V2 syntax (ConfigDict), include proper field validation (min_length, ge, le), add descriptive Field(..., description=...) for all fields | Success: All models are properly typed, validation works as expected, models export correctly from __init__.py, JSON serialization/deserialization works correctly_

- [x] 1.3. Set up Gemini API service
  - Files:
    - `backend/app/services/__init__.py`
    - `backend/app/services/gemini.py`
  - Create GeminiClient class wrapping google.generativeai
  - Add async generate() method with JSON response parsing
  - Include error handling for API failures
  - Purpose: Provide unified interface for LLM API calls
  - _Leverage: google-generativeai library_
  - _Requirements: Non-functional - Performance_
  - _Prompt: Role: Backend Developer specializing in API integration and async Python | Task: Create GeminiClient service class following Performance requirements, wrapping google.generativeai with async generate() method that accepts prompt, model (default gemini-2.5-flash), response_format (json/text), max_tokens, and returns parsed JSON or text, with proper error handling for rate limits and API failures | Restrictions: Must use async/await, handle JSON parsing errors gracefully, implement retry logic for transient failures, log all API calls for debugging | Success: Client initializes with API key from config, generate() method works for both JSON and text responses, errors are properly caught and logged, rate limiting is handled with exponential backoff_

### Frontend Setup

- [x] 1.4. Initialize React project with Vite
  - Files:
    - `frontend/package.json`
    - `frontend/vite.config.ts`
    - `frontend/tsconfig.json`
    - `frontend/tailwind.config.js`
    - `frontend/src/main.tsx`
    - `frontend/src/App.tsx`
    - `frontend/index.html`
  - Set up React 18 + TypeScript + Vite + TailwindCSS
  - Configure TailwindCSS with custom theme (colors, fonts per Design doc)
  - Add basic App component structure
  - Purpose: Establish frontend foundation with modern tooling
  - _Leverage: Vite, React 18, TailwindCSS_
  - _Requirements: 9 (UI Layout), 12 (Responsive Design)_
  - _Prompt: Role: Frontend Developer specializing in React and build tooling | Task: Initialize React 18 + TypeScript + Vite project following requirements 9 and 12, configuring TailwindCSS with custom theme colors (primary: #137fec, background-light: #f6f7f8, etc. from Design doc), fonts (Space Grotesk, Lexend), and setting up index.html, main.tsx, App.tsx with basic routing structure | Restrictions: Must use Vite (not CRA), configure TypeScript strict mode, use Tailwind @layer for custom styles, ensure dark mode support with class strategy | Success: Project builds without errors, hot reload works, TailwindCSS applies custom theme correctly, dark mode classes are functional, TypeScript compilation is strict_

- [x] 1.5. Create TypeScript type definitions
  - Files:
    - `frontend/src/types/message.ts`
    - `frontend/src/types/artifact.ts`
    - `frontend/src/types/api.ts`
  - Define all TypeScript interfaces matching backend Pydantic models
  - Include JSDoc comments for documentation
  - Purpose: Ensure type safety across frontend codebase
  - _Leverage: TypeScript 5.0+_
  - _Requirements: 1, 6, 7, 8_
  - _Prompt: Role: TypeScript Developer specializing in type systems and API contracts | Task: Create comprehensive TypeScript type definitions covering requirements 1, 6, 7, 8 (Message, Artifact, API types) that mirror backend Pydantic models from Design doc, including discriminated unions for Artifact types (quiz_set, explanation), with JSDoc comments | Restrictions: Must use discriminated unions for Artifact type safety, include all optional fields with ?, maintain naming consistency with backend, export all types from index files | Success: All types compile without errors, discriminated unions work correctly, types match backend models exactly, IDE autocomplete works properly_

## Phase 2: 核心模块实现（Backend）

### Intent Router

- [x] 2.1. Implement Intent Router core logic
  - Files:
    - `backend/app/core/__init__.py`
    - `backend/app/core/intent_router.py`
    - `backend/app/prompts/intent_router.txt`
  - Create IntentRouter class with parse() method
  - Implement prompt template loading and formatting
  - Add confidence threshold logic
  - Purpose: Enable intelligent intent recognition from user input
  - _Leverage: Gemini service from task 1.3, models from task 1.2_
  - _Requirements: 2 (Intent Recognition)_
  - _Prompt: Role: AI Engineer specializing in prompt engineering and intent classification | Task: Implement IntentRouter class following requirement 2 (Intent Recognition), creating parse() method that uses Gemini API to classify user messages into intents (quiz, explain, other), loading prompt template from prompts/intent_router.txt with placeholders for {message}, {topic_hint}, {recent_context}, and applying confidence threshold logic (>= 0.6 accept, < 0.6 return clarification) | Restrictions: Prompt must be < 200 tokens, must use structured JSON output from Gemini, handle low confidence gracefully with fallback to "other" intent, log all classifications | Success: Intent classification works accurately for test cases, confidence scores are reasonable, prompt template is loaded correctly, low confidence triggers appropriate responses, JSON parsing handles malformed responses_

- [x] 2.2. Create Intent Router API endpoint
  - Files:
    - `backend/app/api/__init__.py`
    - `backend/app/api/intent.py`
  - Create POST /intent/parse endpoint
  - Add FastAPI dependency injection for IntentRouter
  - Include error handling and validation
  - Purpose: Provide REST API for intent recognition (debugging/testing)
  - _Leverage: Intent Router from task 2.1_
  - _Requirements: 2_
  - _Prompt: Role: Backend API Developer with FastAPI expertise | Task: Create /intent/parse API endpoint following requirement 2, implementing POST endpoint that accepts {message, memory_summary}, uses IntentRouter via dependency injection, validates input with Pydantic, handles HTTPException for errors, returns IntentResult model | Restrictions: Must use FastAPI Depends() for dependency injection, validate inputs with Pydantic models, return proper HTTP status codes (200, 422, 500), log endpoint access | Success: Endpoint returns valid IntentResult JSON, validation rejects invalid inputs with 422, dependency injection works correctly, errors return appropriate status codes with user-friendly messages_

- [ ] 2.3. Write Intent Router unit tests
  - Files:
    - `backend/tests/__init__.py`
    - `backend/tests/test_intent_router.py`
  - Test quiz intent recognition
  - Test explain intent recognition
  - Test low confidence scenarios
  - Test prompt template formatting
  - Purpose: Ensure intent recognition reliability
  - _Leverage: pytest, pytest-asyncio, mocked Gemini client_
  - _Requirements: 2_
  - _Prompt: Role: QA Engineer specializing in Python unit testing and mocking | Task: Create comprehensive unit tests for IntentRouter covering requirement 2, testing: (1) quiz intent recognition with "给我几道练习题", (2) explain intent with "讲讲极限", (3) low confidence with vague input, (4) prompt formatting with memory_summary, using pytest fixtures to mock Gemini client responses | Restrictions: Must use pytest-asyncio for async tests, mock Gemini API (do not call real API), test both success and error paths, ensure test isolation | Success: All tests pass, coverage > 80%, tests run quickly (< 1s), mocking is effective, edge cases are covered_

### Memory Manager

- [ ] 2.4. Implement Memory Manager core logic
  - Files:
    - `backend/app/core/memory_manager.py`
  - Create MemoryManager class with in-memory storage
  - Implement get_summary(), get_profile(), update() methods
  - Add logic for mastery inference and behavior summarization
  - Purpose: Manage user learning profiles and session context
  - _Leverage: Memory models from task 1.2_
  - _Requirements: 3 (Memory Management)_
  - _Prompt: Role: Backend Developer with expertise in state management and data structures | Task: Implement MemoryManager class following requirement 3 (Memory Management), creating in-memory Dict storage for UserLearningProfile and SessionContext, implementing get_summary() that generates concise MemorySummary (<100 tokens), get_profile() for full profile retrieval, and update() that modifies mastery map and history based on user activities | Restrictions: Use in-memory storage (Dict) for demo, ensure thread-safe updates (consider using locks), generate memory summaries under 100 tokens, implement simple mastery inference (weak/medium/strong) | Success: Memory operations work correctly, summaries are concise, profiles update accurately, session context tracks recent intents, mastery inference is reasonable_

- [ ] 2.5. Create Memory Manager API endpoints
  - Files:
    - `backend/app/api/memory.py`
  - Create GET /memory/user/{user_id} endpoint
  - Create GET /memory/session/{session_id} endpoint
  - Add dependency injection for MemoryManager
  - Purpose: Provide REST API for memory access (debugging/testing)
  - _Leverage: Memory Manager from task 2.4_
  - _Requirements: 3_
  - _Prompt: Role: Backend API Developer with FastAPI expertise | Task: Create Memory Manager API endpoints following requirement 3, implementing GET /memory/user/{user_id} returning UserLearningProfile, GET /memory/session/{session_id} returning SessionContext, using MemoryManager via dependency injection, handling 404 when user/session not found | Restrictions: Must use FastAPI path parameters, return 404 for non-existent users/sessions, use dependency injection, validate path parameters | Success: Endpoints return correct JSON, 404 is returned for missing entities, dependency injection works, responses match Pydantic schemas_

- [ ] 2.6. Write Memory Manager unit tests
  - Files:
    - `backend/tests/test_memory_manager.py`
  - Test profile creation and retrieval
  - Test session context updates
  - Test memory summary generation
  - Test mastery inference logic
  - Purpose: Ensure memory management reliability
  - _Leverage: pytest_
  - _Requirements: 3_
  - _Prompt: Role: QA Engineer specializing in state management testing | Task: Create comprehensive unit tests for MemoryManager covering requirement 3, testing: (1) profile creation with default values, (2) session updates with intent history, (3) summary generation under token limit, (4) mastery inference based on activity patterns, using pytest fixtures for test data | Restrictions: Test data isolation between tests, verify state persistence, check summary length constraints, validate mastery level transitions | Success: All tests pass, coverage > 80%, state management is correct, summaries meet token limits, mastery inference logic is validated_

### Skill Registry

- [ ] 2.7. Implement Skill Registry core logic
  - Files:
    - `backend/app/core/skill_registry.py`
    - `backend/app/skills/quiz/skill.yaml`
    - `backend/app/skills/explain/skill.yaml`
  - Create SkillRegistry class that loads YAML configs
  - Implement get_by_intent(), get_by_id(), validate_params() methods
  - Create skill.yaml files for Quiz and Explain skills
  - Purpose: Manage skill definitions and metadata
  - _Leverage: pyyaml, jsonschema, Skill models from task 1.2_
  - _Requirements: 4 (Skill Registry)_
  - _Prompt: Role: Backend Developer with expertise in configuration management and schema validation | Task: Implement SkillRegistry class following requirement 4, loading skill.yaml files from backend/app/skills/ directories, parsing with pyyaml into SkillDefinition models, implementing get_by_intent() that filters by intent_tags, get_by_id() for ID lookup, and validate_params() using jsonschema to validate against input_schema, create quiz/skill.yaml and explain/skill.yaml with complete schemas from Design doc | Restrictions: Must use pyyaml for YAML parsing, validate schemas with jsonschema, cache loaded skills, handle missing files gracefully, log loading errors | Success: Registry loads all skill yamls successfully, intent matching works correctly, parameter validation catches invalid inputs, yaml files follow exact schema from Design doc_

- [ ] 2.8. Create Skill Registry API endpoint
  - Files:
    - `backend/app/api/skills.py`
  - Create GET /skills endpoint (list all skills)
  - Create GET /skills/{skill_id} endpoint (get specific skill)
  - Add dependency injection for SkillRegistry
  - Purpose: Provide REST API for skill discovery
  - _Leverage: Skill Registry from task 2.7_
  - _Requirements: 4_
  - _Prompt: Role: Backend API Developer with FastAPI expertise | Task: Create Skill Registry API endpoints following requirement 4, implementing GET /skills returning List[SkillDefinition], GET /skills/{skill_id} returning single SkillDefinition, using SkillRegistry via dependency injection, handling 404 for non-existent skills | Restrictions: Must use dependency injection, return 404 for missing skills, serialize SkillDefinition to JSON, validate path parameters | Success: Endpoints return correct JSON lists and objects, 404 for missing skills, responses match SkillDefinition schema, dependency injection works_

- [ ] 2.9. Write Skill Registry unit tests
  - Files:
    - `backend/tests/test_skill_registry.py`
  - Test YAML loading and parsing
  - Test intent-based skill lookup
  - Test parameter validation
  - Purpose: Ensure skill registry reliability
  - _Leverage: pytest, sample YAML fixtures_
  - _Requirements: 4_
  - _Prompt: Role: QA Engineer specializing in configuration and schema validation testing | Task: Create comprehensive unit tests for SkillRegistry covering requirement 4, testing: (1) YAML loading from files, (2) get_by_intent("quiz") returns QuizSkill, (3) validate_params catches missing required fields, (4) malformed YAML handling, using pytest fixtures with sample skill.yaml files | Restrictions: Use test fixtures directory for sample yamls, test both valid and invalid configurations, verify jsonschema validation errors, ensure registry handles missing files | Success: All tests pass, YAML parsing is correct, intent lookup works, validation catches errors, coverage > 80%_

### Skill Orchestrator

- [ ] 2.10. Implement Skill Orchestrator core logic
  - Files:
    - `backend/app/core/skill_orchestrator.py`
  - Create SkillOrchestrator class with execute() method
  - Implement skill selection logic
  - Add params and context building logic
  - Add artifact wrapping logic
  - Purpose: Orchestrate skill execution based on intent
  - _Leverage: Skill Registry, Memory Manager, Skill instances_
  - _Requirements: 5 (Skill Orchestration)_
  - _Prompt: Role: Backend Developer with expertise in orchestration patterns and dependency injection | Task: Implement SkillOrchestrator class following requirement 5, creating execute() method that: (1) selects skill using _select_skill(intent) from registry, (2) builds params with _build_params() merging intent data and schema defaults, (3) builds context with _build_context() fetching user profile if needed, (4) executes skill.execute(params, context), (5) wraps result in Artifact model with metadata, using dependency injection for registry and memory manager | Restrictions: Handle skill not found errors, validate params before execution, log all orchestration steps, implement skill selection strategy (first match for demo), propagate skill execution errors | Success: Orchestrator selects correct skills, params are properly built, context includes necessary data, artifacts are correctly wrapped, error handling is robust_

- [ ] 2.11. Write Skill Orchestrator unit tests
  - Files:
    - `backend/tests/test_skill_orchestrator.py`
  - Test skill selection logic
  - Test params and context building
  - Test artifact wrapping
  - Test error handling
  - Purpose: Ensure orchestration reliability
  - _Leverage: pytest, mocked skills_
  - _Requirements: 5_
  - _Prompt: Role: QA Engineer specializing in integration and orchestration testing | Task: Create comprehensive unit tests for SkillOrchestrator covering requirement 5, testing: (1) skill selection based on intent, (2) params building with defaults, (3) context building with user profile, (4) artifact wrapping with metadata, (5) error handling for missing skills, using pytest with mocked SkillRegistry, MemoryManager, and Skill instances | Restrictions: Mock all dependencies, test orchestration logic in isolation, verify param construction, check artifact structure, test error scenarios | Success: All tests pass, orchestration logic is validated, mocking is effective, error handling is tested, coverage > 80%_

## Phase 3: Skills 实现（Backend） ✅ COMPLETED

**说明**: 本 Phase 采用了更先进的架构 - 通过 YAML 配置 + Prompt 模板实现 Skills，无需为每个 Skill 编写独立的 Python 类。SkillOrchestrator 统一执行所有 Skills。

### Skills 配置和 Prompts

- [x] 3.1. ~~Implement Base Skill class~~ (不需要 - 使用配置驱动架构)
  - Files:
    - `backend/app/skills/__init__.py`
    - `backend/app/skills/base.py`
  - Create abstract BaseSkill class
  - Implement _load_prompt() method
  - Implement _validate_output() method using jsonschema
  - Purpose: Provide common interface for all skills
  - _Leverage: jsonschema, Gemini client_
  - _Requirements: 6, 7 (Skills)_
  - _Prompt: Role: Backend Developer specializing in object-oriented design and abstract base classes | Task: Create abstract BaseSkill class following requirements 6-7 (Skill interface), implementing abstract execute(params, context) method, concrete _load_prompt() that reads from skill_dir/prompts/generate.txt, and _validate_output(result, schema) using jsonschema, with __init__ accepting skill_dir Path and gemini_client | Restrictions: Must use ABC and abstractmethod, handle missing prompt files gracefully, validate output schema strictly, log validation errors | Success: Base class defines clear interface, subclasses must implement execute(), prompt loading works, output validation catches schema violations_

### Quiz Skill

- [x] 3.2. Quiz Skill 配置和 Prompt
  - Files:
    - `backend/skills_config/quiz_skill.yaml` ✅
    - `backend/app/prompts/quiz_generation_skill.txt` ✅ (19,107 bytes)
  - ✅ 创建 YAML 配置文件定义技能元数据、input/output schema
  - ✅ 创建学科通用的 Quiz Generation Prompt (支持所有学科)
  - ✅ 通过 SkillRegistry 加载和验证
  - ✅ 通过 SkillOrchestrator 统一执行
  - Purpose: Generate practice questions based on topic
  - Success: ✅ Quiz Skill 配置完整，Prompt 通用性强，通过 19 个测试

- [x] 3.3. Quiz Skill 集成测试 (包含在 test_skills_integration.py)
  - Files:
    - `backend/tests/test_quiz_skill.py`
  - Test quiz generation with various params
  - Test difficulty adjustment logic
  - Test output validation
  - Purpose: Ensure quiz skill reliability
  - _Leverage: pytest, mocked Gemini client_
  - _Requirements: 6_
  - _Prompt: Role: QA Engineer specializing in AI-powered feature testing | Task: Create comprehensive unit tests for QuizSkill covering requirement 6, testing: (1) quiz generation with topic="微积分-极限" and num_questions=5, (2) difficulty adjustment when user mastery is weak, (3) output validation against schema, (4) JSON parsing error handling, using mocked Gemini client that returns sample quiz JSON | Restrictions: Mock Gemini API, test with various param combinations, verify difficulty logic, check output structure, test error scenarios | Success: All tests pass, generation logic is validated, difficulty adjustment works, output validation is tested, coverage > 80%_

### Explain Skill

- [x] 3.4. Explain Skill 配置和 Prompt
  - Files:
    - `backend/skills_config/explain_skill.yaml` ✅
    - `backend/app/prompts/concept_explain_skill.txt` ✅ (15,730 bytes)
  - ✅ 创建 YAML 配置文件定义技能元数据、input/output schema
  - ✅ 创建学科通用的 Concept Explain Prompt (支持所有学科)
  - ✅ 通过 SkillRegistry 加载和验证
  - ✅ 通过 SkillOrchestrator 统一执行
  - Purpose: Generate structured concept explanations
  - Success: ✅ Explain Skill 配置完整，Prompt 通用性强，通过 19 个测试

- [x] 3.5. Explain Skill 集成测试 (包含在 test_skills_integration.py)
  - Files:
    - `backend/tests/test_explain_skill.py`
  - Test explanation generation
  - Test depth adjustment logic
  - Test output validation
  - Purpose: Ensure explain skill reliability
  - _Leverage: pytest, mocked Gemini client_
  - _Requirements: 7_
  - _Prompt: Role: QA Engineer specializing in educational feature testing | Task: Create comprehensive unit tests for ExplainSkill covering requirement 7, testing: (1) explanation generation with topic="chain rule", (2) depth adjustment when user mastery is strong, (3) output structure with examples, (4) JSON parsing errors, using mocked Gemini client returning sample explanation JSON | Restrictions: Mock Gemini API, test depth logic, verify examples structure, check formula field, test error handling | Success: All tests pass, generation logic is validated, depth adjustment works, output structure is correct, coverage > 80%_

## Phase 4: Agent API 集成（Backend） ✅ COMPLETED

### Agent API Endpoint

- [x] 4.1. Implement unified Agent API endpoint
  - Files:
    - `backend/app/api/agent.py` ✅ (220 lines)
    - `backend/tests/test_agent_api.py` ✅ (250 lines, 11 tests)
  - ✅ Create POST /api/agent/chat endpoint
  - ✅ Implement complete orchestration flow (Orchestrator.execute)
  - ✅ Add timing and logging (processing_time_ms)
  - ✅ Add GET /api/agent/health endpoint
  - ✅ Add GET /api/agent/info endpoint
  - Purpose: Provide unified entry point for chat interactions
  - Success: ✅ 端点编排所有组件，处理错误，记录时间，11个测试全部通过

- [x] 4.2. Add dependency injection setup
  - Files:
    - `backend/app/api/agent.py` ✅ (依赖函数内联实现)
    - `backend/app/main.py` ✅ (已修改，注册 agent router)
  - ✅ Create dependency functions (get_memory_manager, get_gemini_client, get_skill_orchestrator)
  - ✅ Implement singleton pattern (函数属性缓存)
  - ✅ Register agent router in main.py
  - Purpose: Enable clean dependency injection throughout app
  - Success: ✅ 依赖注入正常工作，单例模式有效，所有端点正确解析依赖

### Integration Testing

- [x] 4.3. Write integration tests for Agent API
  - Files:
    - `backend/tests/test_agent_api.py` ✅ (11 tests)
  - ✅ Test health check and info endpoints (2 tests)
  - ✅ Test request validation (3 tests: empty, whitespace, missing fields)
  - ✅ Test complete quiz/explain flow with mock (2 tests)
  - ✅ Test error scenarios (3 tests: ValueError, FileNotFoundError, RuntimeError)
  - ✅ Test OpenAPI documentation (1 test)
  - Purpose: Validate end-to-end system integration
  - Success: ✅ 11个集成测试全部通过，完整流程验证，错误场景覆盖

## Phase 5: 前端核心组件实现

### Context and State Management

- [ ] 5.1. Implement Chat Context with Reducer
  - Files:
    - `frontend/src/contexts/ChatContext.tsx`
  - Create ChatProvider with useReducer
  - Implement chatReducer with actions (ADD_MESSAGE, SET_LOADING, SET_ERROR)
  - Create custom hooks useChat() and useChatDispatch()
  - Purpose: Centralized state management for chat
  - _Leverage: React useReducer, useContext_
  - _Requirements: 1 (Chat Interface)_
  - _Prompt: Role: Frontend Developer specializing in React state management and Context API | Task: Create ChatContext.tsx following requirement 1, implementing ChatProvider with useReducer managing state {messages: Message[], isLoading: boolean, error: string | null}, chatReducer handling ADD_MESSAGE, SET_LOADING, SET_ERROR actions, custom hooks useChat() and useChatDispatch() for accessing context, following the reducer pattern from React docs Context7 reference | Restrictions: Must use useReducer for complex state, separate state and dispatch contexts, throw errors if hooks used outside provider, maintain immutability in reducer | Success: Context provides state correctly, reducer updates state immutably, hooks work properly, components can access state and dispatch, TypeScript types are correct_

- [ ] 5.2. Create useAgent custom hook
  - Files:
    - `frontend/src/hooks/useAgent.ts`
    - `frontend/src/services/api.ts`
  - Create Axios instance with base configuration
  - Implement useAgent hook with sendMessage() function
  - Add loading state and error handling
  - Purpose: Encapsulate Agent API interaction logic
  - _Leverage: Axios, ChatContext from task 5.1_
  - _Requirements: 8 (Integration)_
  - _Prompt: Role: Frontend Developer with expertise in React hooks and API integration | Task: Create useAgent.ts hook and api.ts service following requirement 8, implementing Axios instance with baseURL="http://localhost:8000", sendMessage() that: (1) dispatches ADD_MESSAGE for user input, (2) sets loading state, (3) POSTs to /agent/chat, (4) dispatches ADD_MESSAGE with artifact, (5) handles errors with SET_ERROR, using useChatDispatch() from ChatContext, generating unique IDs for messages | Restrictions: Must handle async errors, manage loading state properly, generate unique message IDs, add timestamps, dispatch actions in correct order | Success: API calls work correctly, messages are added to state, loading state updates, errors are caught and displayed, types are correct_

### Layout Components

- [ ] 5.3. Implement Sidebar component
  - Files:
    - `frontend/src/components/layout/Sidebar.tsx`
  - Create Sidebar with navigation links
  - Add StudyX logo and branding
  - Include New Chat button, Settings, Help links
  - Purpose: Provide main navigation structure
  - _Leverage: TailwindCSS theme from task 1.4_
  - _Requirements: 9 (Main Chat Interface - Sidebar)_
  - _Prompt: Role: Frontend Developer specializing in React and responsive design | Task: Create Sidebar.tsx following requirement 9 UI specifications, implementing 256px width sidebar with: StudyX logo + "Skill Agent Demo" text, navigation items (Dashboard, Calculus Practice active with primary color, Concept Explanation, Integration by Parts), New Chat button (primary bg, white text, full width), Settings and Help at bottom, using TailwindCSS classes and Material Icons, responsive to hide on mobile | Restrictions: Must follow exact design from ui_designs/studyx_skill_agent_主聊天界面/, use custom theme colors (primary, surface-light, etc.), implement hover states, maintain 256px fixed width on desktop | Success: Sidebar matches design screenshot, navigation items have correct styling, active state shows primary bg, responsive behavior works, accessibility is maintained_

- [ ] 5.4. Implement TopNavBar component
  - Files:
    - `frontend/src/components/layout/TopNavBar.tsx`
  - Create TopNavBar with session title
  - Add notification, quick actions icons
  - Add user avatar
  - Purpose: Provide contextual session information
  - _Leverage: TailwindCSS theme_
  - _Requirements: 9 (Main Chat Interface - TopNavBar)_
  - _Prompt: Role: Frontend Developer specializing in UI components | Task: Create TopNavBar.tsx following requirement 9, implementing fixed height 64px header with: session title on left ("Calculus Practice Session"), notification bell icon button, bolt icon button, user avatar on right, using Material Icons, TailwindCSS with border-b, surface-light bg, proper spacing | Restrictions: Must follow design specifications, use icon buttons with primary/10 bg, implement hover states (primary/20), maintain proper height, align items vertically | Success: TopNavBar matches design, icons render correctly, hover effects work, responsive layout maintained, accessibility for icon buttons_

### Chat Components

- [ ] 5.5. Implement ChatInterface component
  - Files:
    - `frontend/src/components/chat/ChatInterface.tsx`
    - `frontend/src/components/chat/MessageList.tsx`
    - `frontend/src/components/chat/InputArea.tsx`
    - `frontend/src/components/chat/LoadingIndicator.tsx`
  - Create ChatInterface main container
  - Implement MessageList with scrolling
  - Create InputArea with text input and send button
  - Add LoadingIndicator with animated dots
  - Purpose: Provide main chat interaction interface
  - _Leverage: ChatContext, useAgent hook_
  - _Requirements: 1, 9, 13 (Chat Interface, Loading States)_
  - _Prompt: Role: Frontend Developer with expertise in React chat interfaces | Task: Create chat components following requirements 1, 9, 13: ChatInterface as container with flex column layout, MessageList with overflow-y-auto and message mapping, InputArea with controlled input, send button (disabled when empty), LoadingIndicator with three bouncing dots animation (bounce keyframes, staggered delays 0.1s/0.2s/0.3s), using useChat() for messages, useAgent() for sendMessage(), handling loading states | Restrictions: Must implement scroll-to-bottom on new messages, disable send button when loading or empty, show loading indicator in message list, maintain responsive design, use proper TailwindCSS classes | Success: Chat interface is fully functional, messages display correctly, input works with Enter key, loading states are clear, animations are smooth, design matches specifications_

- [ ] 5.6. Implement MessageBubble component
  - Files:
    - `frontend/src/components/chat/MessageBubble.tsx`
  - Create MessageBubble with role-based styling
  - Add artifact rendering logic with type switching
  - Include avatar and sender label
  - Purpose: Render individual messages with artifacts
  - _Leverage: Message types from task 1.5_
  - _Requirements: 1, 9_
  - _Prompt: Role: Frontend Developer specializing in component composition | Task: Create MessageBubble.tsx following requirements 1 and 9, implementing message rendering with: user messages (right-aligned, primary bg, white text, rounded-br-none), agent messages (left-aligned, surface-light bg, border, rounded-bl-none), avatars, sender labels, renderArtifact() function switching on artifact.type to render QuizCard, ExplainCard, or LoadingIndicator, proper spacing and max-width constraints | Restrictions: Must implement correct alignment for user/agent, use rounded corners per design, include avatars (use placeholder images), render artifacts conditionally, maintain responsive max-width | Success: Messages display correctly for both roles, artifacts render in appropriate component, styling matches design, avatars show, responsive behavior works_

### Artifact Components

- [ ] 5.7. Implement QuizCard component
  - Files:
    - `frontend/src/components/artifacts/QuizCard.tsx`
    - `frontend/src/components/common/ProgressBar.tsx`
  - Create QuizCard with progress bar
  - Implement question rendering with radio options
  - Add submit button and answer checking logic
  - Display explanation after submission
  - Purpose: Render interactive practice questions
  - _Leverage: Artifact types from task 1.5_
  - _Requirements: 10 (QuizCard Design)_
  - _Prompt: Role: Frontend Developer specializing in interactive educational UI | Task: Create QuizCard.tsx following requirement 10, implementing: (1) header with topic tag and ProgressBar showing current/total, (2) question stem with large font, (3) radio options with proper styling (border on hover, primary/10 bg when selected), (4) submit button, (5) after submission: green border + checkmark for correct, red border + X for user's wrong answer, Explanation section with bg-slate-50, (6) "再来一组练习" button after completion, using local state for selectedAnswer, isSubmitted, create ProgressBar.tsx with props {current, total} showing percentage-based blue fill | Restrictions: Must follow exact design from ui_designs/quizcard_(练习题)_组件/, implement all interaction states, disable options after submit, use Material Icons for check/cancel, maintain accessibility | Success: QuizCard matches design, all states render correctly, interactions work smoothly, progress bar calculates correctly, explanations display properly, accessibility is maintained_

- [ ] 5.8. Implement ExplainCard component
  - Files:
    - `frontend/src/components/artifacts/ExplainCard.tsx`
  - Create ExplainCard with title and content
  - Render formula section with special styling
  - Implement examples list with numbered steps
  - Apply code snippet highlighting
  - Purpose: Render structured concept explanations
  - _Leverage: Artifact types from task 1.5_
  - _Requirements: 11 (ExplainCard Design)_
  - _Prompt: Role: Frontend Developer specializing in content presentation and typography | Task: Create ExplainCard.tsx following requirement 11, implementing: (1) title with text-3xl font-bold, (2) content paragraphs with proper spacing, (3) formula section with bg-background-light, font-mono, centered, (4) examples section with "Examples" h2, (5) each example with blue circle number badge, problem header, solution with left border-l-2 border-primary/50, (6) inline code with bg-primary/10 text-primary, using dangerouslySetInnerHTML or careful rendering for mathematical content | Restrictions: Must follow exact design from ui_designs/explaincard_(概念讲解)_组件/, implement numbered badges with bg-primary text-white rounded-full, maintain proper spacing and typography hierarchy, use border-l for steps | Success: ExplainCard matches design, formulas are prominent, examples are clear, code snippets are highlighted, typography is excellent, content is readable_

### Theme and Styling

- [ ] 5.9. Implement Theme Context and dark mode support
  - Files:
    - `frontend/src/contexts/ThemeContext.tsx`
    - `frontend/src/hooks/useTheme.ts`
  - Create ThemeProvider with light/dark state
  - Implement theme toggle logic
  - Add system preference detection
  - Purpose: Support dark mode switching
  - _Leverage: React Context, localStorage_
  - _Requirements: 12 (Dark Mode)_
  - _Prompt: Role: Frontend Developer with expertise in theme systems and accessibility | Task: Create ThemeContext.tsx and useTheme.ts following requirement 12, implementing ThemeProvider managing theme state (light/dark), toggleTheme() function, localStorage persistence, system preference detection with window.matchMedia('prefers-color-scheme: dark'), applying 'dark' class to document.documentElement, providing useTheme() hook for accessing theme state and toggle function | Restrictions: Must persist to localStorage, detect system preference on mount, apply 'dark' class to html element, handle class updates synchronously, provide type-safe hook | Success: Theme persists across reloads, system preference is detected, class is applied correctly, all components respond to dark mode, toggle works smoothly_

## Phase 6: 最终集成和测试

### End-to-End Flow

- [ ] 6.1. Integrate all components in App.tsx
  - Files:
    - `frontend/src/App.tsx`
  - Compose ThemeProvider, ChatProvider, Layout components
  - Set up routing (if needed)
  - Add error boundaries
  - Purpose: Create complete application structure
  - _Leverage: All context providers and components_
  - _Requirements: All frontend requirements_
  - _Prompt: Role: Senior Frontend Developer with expertise in React application architecture | Task: Integrate all components in App.tsx, wrapping application with ThemeProvider → ChatProvider → Layout structure (Sidebar + main content area with TopNavBar + ChatInterface), add React ErrorBoundary for graceful error handling, ensure proper component hierarchy, add basic routing if needed (React Router v6 optional for future expansion) | Restrictions: Must maintain correct provider nesting order, ensure single ChatProvider instance, implement error boundary fallback UI, test in both light and dark modes | Success: Application renders correctly, all providers work together, error boundary catches errors, theme switching works across all components, chat functionality is fully integrated_

- [ ] 6.2. Create README and setup documentation
  - Files:
    - `README.md`
    - `backend/README.md`
    - `frontend/README.md`
  - Document project structure and architecture
  - Add setup instructions for backend and frontend
  - Include environment variable configuration
  - Add API documentation links
  - Purpose: Enable easy project setup and understanding
  - _Leverage: Project structure from Design doc_
  - _Requirements: Non-functional - Documentation_
  - _Prompt: Role: Technical Writer with software development experience | Task: Create comprehensive README.md files: main README with project overview, architecture diagram, quick start instructions; backend/README.md with setup (pip install, uvicorn command), env vars (GEMINI_API_KEY), API endpoints summary; frontend/README.md with setup (npm install, npm run dev), environment configuration, component structure; include code examples and troubleshooting tips | Restrictions: Must be clear for developers with no context, include all required env vars, provide exact commands to run, link to FastAPI /docs for API documentation | Success: READMEs are comprehensive and clear, setup instructions work for new developers, all commands are correct, documentation is well-formatted_

### Testing and Validation

- [ ] 6.3. Manual end-to-end testing
  - Test complete quiz generation flow
  - Test complete explanation flow
  - Test error scenarios (network failures, invalid inputs)
  - Test responsive design on different screen sizes
  - Test dark mode across all components
  - Purpose: Validate user experience and catch edge cases
  - _Leverage: Running application_
  - _Requirements: All requirements_
  - _Prompt: Role: QA Engineer with expertise in manual testing and user experience validation | Task: Perform comprehensive manual testing covering all requirements: (1) quiz flow - request questions, view options, submit answers, see explanations, (2) explanation flow - request concept, view structured content with examples, (3) error scenarios - test with network disabled, invalid inputs, low confidence messages, (4) responsive design - test on mobile (< 768px), tablet (768-1024px), desktop (> 1024px), verify sidebar behavior, (5) dark mode - toggle and verify all components, check color consistency, test readability | Restrictions: Must test all critical user paths, document bugs with screenshots, verify against design mockups, test edge cases (empty input, very long input, special characters) | Success: All user flows work correctly, no critical bugs found, responsive design works on all sizes, dark mode is fully functional, edge cases are handled gracefully_

- [ ] 6.4. Performance optimization and final polish
  - Review and optimize API response times
  - Add loading skeletons where appropriate
  - Optimize bundle size (code splitting if needed)
  - Add proper meta tags and favicons
  - Fix any remaining lint errors
  - Purpose: Ensure production-ready quality
  - _Leverage: Chrome DevTools, Lighthouse_
  - _Requirements: Performance requirements_
  - _Prompt: Role: Senior Developer with expertise in performance optimization and production readiness | Task: Optimize application performance and polish: (1) measure and optimize API response times (target < 5s end-to-end), (2) add skeleton loaders for loading states, (3) analyze bundle size with vite build --analyze, implement code splitting if bundle > 500KB, (4) add proper HTML meta tags (title, description, viewport), favicon.ico and icon.svg, (5) run eslint --fix to clean code, fix any TypeScript errors, (6) run Lighthouse audit targeting > 90 scores | Restrictions: Must maintain functionality while optimizing, use React.lazy() for code splitting cautiously, ensure meta tags are SEO-friendly, fix all TypeScript strict errors | Success: API responses meet performance targets, loading states are smooth, bundle size is reasonable, meta tags are complete, no lint/TS errors, Lighthouse scores are good_

## Phase 7: 用户认证与Session持久化 🆕

### Backend: 用户认证系统

- [ ] 7.1. 实现用户认证基础设施
  - Files:
    - `backend/app/models/user.py`
    - `backend/app/core/auth.py`
    - `backend/app/db/__init__.py`
    - `backend/app/db/database.py`
    - `backend/app/db/models.py`
  - Create User Pydantic model and SQLite schema
  - Implement JWT token generation and verification
  - Create database initialization and connection management
  - Purpose: 提供用户认证和数据持久化基础
  - _Leverage: PyJWT, passlib, SQLite3, SQLAlchemy (optional)_
  - _Requirements: 14 (用户认证与Session持久化)_
  - _Prompt: Role: Backend Security Developer specializing in authentication systems | Task: Implement user authentication infrastructure following requirement 14, creating: (1) User Pydantic model with username, password_hash fields, (2) SQLite database schema with users, learning_profiles, chat_history tables, (3) auth.py with create_access_token(), verify_token(), hash_password(), verify_password() functions using PyJWT (HS256) and passlib (bcrypt), (4) database.py with SQLite connection management, init_db() to create tables | Restrictions: Must use bcrypt for password hashing, JWT tokens expire in 7 days, store SECRET_KEY in env vars, use parameterized queries to prevent SQL injection, validate username length (3-20 chars) and password strength (>= 6 chars) | Success: JWT tokens are generated correctly, passwords are securely hashed, database tables are created properly, token verification works, SQL injection is prevented_

- [ ] 7.2. 创建认证API端点
  - Files:
    - `backend/app/api/auth.py`
  - Create POST /auth/register endpoint
  - Create POST /auth/login endpoint
  - Create GET /auth/me endpoint (get current user)
  - Add dependency function get_current_user()
  - Purpose: 提供用户注册、登录、验证功能
  - _Leverage: auth.py from task 7.1, FastAPI Depends_
  - _Requirements: 14_
  - _Prompt: Role: Backend API Developer with authentication expertise | Task: Create authentication API endpoints following requirement 14, implementing: (1) POST /auth/register accepting {username, password}, validating uniqueness, hashing password, creating user record, returning JWT token, (2) POST /auth/login validating credentials, returning token, (3) GET /auth/me extracting user from Authorization header "Bearer <token>", returning user info, (4) get_current_user() dependency function using HTTPBearer for token extraction and verification, raising HTTPException 401 for invalid tokens | Restrictions: Must validate username uniqueness, return 400 for duplicate usernames, return 401 for wrong credentials, extract token from Authorization header, verify token signature and expiration, log authentication events | Success: Register creates users correctly, login returns valid tokens, /auth/me returns correct user info, invalid tokens return 401, duplicate usernames return 400_

- [ ] 7.3. 修改Memory Manager支持持久化
  - Files:
    - `backend/app/core/memory_manager.py`
    - `backend/app/db/repository.py`
  - Modify MemoryManager to load/save from SQLite
  - Create UserProfileRepository for CRUD operations
  - Create ChatHistoryRepository for message persistence
  - Update get_summary() to include historical data
  - Purpose: 实现用户数据持久化，支持跨会话记忆
  - _Leverage: database.py from task 7.1, existing MemoryManager_
  - _Requirements: 14, 3 (Memory Management)_
  - _Prompt: Role: Backend Developer with database expertise | Task: Modify MemoryManager and create repository layer following requirements 14 and 3, implementing: (1) UserProfileRepository with load_profile(user_id), save_profile(user_id, profile), update_mastery(user_id, topic, level) methods, (2) ChatHistoryRepository with save_message(user_id, session_id, role, content, artifact), load_recent_messages(user_id, limit=10), (3) modify MemoryManager.__init__ to accept user_id and load profile from SQLite, (4) update get_summary() to include historical preference analysis from chat_history, (5) modify update() to persist changes to SQLite | Restrictions: Must use context managers for DB connections, handle SQLite locking gracefully, serialize mastery_map and artifact to JSON for storage, limit historical message loading to prevent performance issues, log all DB operations | Success: Profiles persist across sessions, chat history is saved correctly, get_summary() includes historical context, concurrent access is handled, DB errors are caught gracefully_

- [ ] 7.4. 集成认证到Agent API
  - Files:
    - `backend/app/api/agent.py`
    - `backend/app/main.py`
  - Add get_current_user dependency to /api/agent/chat
  - Modify agent_chat to extract user_id from current_user
  - Pass user_id to MemoryManager and Orchestrator
  - Update CORS to allow Authorization headers
  - Purpose: 保护Agent API，关联请求到用户
  - _Leverage: get_current_user from task 7.2, agent.py_
  - _Requirements: 14, 8 (Integration)_
  - _Prompt: Role: Backend Integration Developer | Task: Integrate authentication into Agent API following requirements 14 and 8, modifying: (1) agent_chat endpoint to use Depends(get_current_user), extracting user_id from current_user, (2) get_memory_manager() to accept user_id and initialize MemoryManager with it, (3) orchestrator.execute() to receive user_id for context building, (4) main.py CORS settings to include "Authorization" in allow_headers, (5) save user message and agent response to chat_history after each interaction | Restrictions: Must require authentication (401 if no token), propagate user_id through all layers, maintain backward compatibility with existing code structure, log user_id with all operations for auditing | Success: Unauthenticated requests return 401, user_id is correctly extracted, memory and orchestration use user-specific data, CORS allows Authorization header, chat history is saved_

### Frontend: 登录注册界面

- [ ] 7.5. 实现AuthContext和认证状态管理
  - Files:
    - `frontend/src/contexts/AuthContext.tsx`
    - `frontend/src/hooks/useAuth.ts`
    - `frontend/src/services/auth.ts`
  - Create AuthProvider managing user state and token
  - Implement login(), register(), logout() functions
  - Add token storage to localStorage
  - Add token refresh logic
  - Purpose: 管理前端认证状态
  - _Leverage: React Context, Axios_
  - _Requirements: 14_
  - _Prompt: Role: Frontend Developer specializing in authentication and state management | Task: Create authentication context and service following requirement 14, implementing: (1) AuthContext.tsx with AuthProvider managing state {user, token, isAuthenticated, isLoading}, (2) useAuth() hook exposing login(username, password), register(username, password), logout() functions, (3) auth.ts service with registerUser(), loginUser() API calls to /auth/register and /auth/login, (4) token storage to localStorage as "auth_token", (5) automatic token loading on app mount, (6) token injection into Axios Authorization header, (7) handle 401 responses to auto-logout | Restrictions: Must store token securely in localStorage, clear token on logout, set Axios default header "Authorization: Bearer <token>", handle network errors gracefully, validate username/password on frontend before API call | Success: AuthContext provides user state correctly, login/register work with backend API, token persists across page refresh, logout clears state and token, Axios includes Authorization header_

- [ ] 7.6. 创建登录和注册界面组件
  - Files:
    - `frontend/src/components/auth/LoginPage.tsx`
    - `frontend/src/components/auth/RegisterPage.tsx`
    - `frontend/src/components/auth/AuthLayout.tsx`
  - Create LoginPage with username/password inputs
  - Create RegisterPage with validation
  - Add form validation and error display
  - Design modern auth UI matching app theme
  - Purpose: 提供用户认证入口界面
  - _Leverage: TailwindCSS, useAuth hook, React Hook Form (optional)_
  - _Requirements: 14_
  - _Prompt: Role: Frontend UI Developer with authentication UX expertise | Task: Create authentication pages following requirement 14 and app design theme, implementing: (1) AuthLayout.tsx with centered card (max-w-md), StudyX logo, gradient background, (2) LoginPage.tsx with username input, password input (type="password"), "登录" button, "还没有账号？注册" link, error message display area, (3) RegisterPage.tsx with username input (hint: 3-20字符), password input (hint: 至少6字符), confirm password input, "注册" button, "已有账号？登录" link, (4) client-side validation: username length, password strength, password match, (5) loading state on submit button, (6) error display for API errors (duplicate username, wrong password) | Restrictions: Must follow app color theme (primary blue), use Space Grotesk font, disable button during loading, show validation errors inline, use controlled inputs, clear password on error | Success: Login page is functional and beautiful, register page validates input, errors are user-friendly, loading states are clear, design matches app theme, navigation between login/register works_

- [ ] 7.7. 实现Protected Route和路由守卫
  - Files:
    - `frontend/src/components/auth/ProtectedRoute.tsx`
    - `frontend/src/App.tsx`
  - Create ProtectedRoute component
  - Add routing for /login, /register, /chat
  - Implement route guards (redirect if not authenticated)
  - Add loading state during token verification
  - Purpose: 保护需要认证的页面
  - _Leverage: React Router v6, useAuth hook_
  - _Requirements: 14_
  - _Prompt: Role: Frontend Developer with React Router expertise | Task: Implement protected routing following requirement 14, creating: (1) ProtectedRoute.tsx component checking isAuthenticated from useAuth(), redirecting to /login if false, rendering children if true, (2) modify App.tsx to use React Router v6 with routes: "/" (redirect to /login or /chat), "/login" (LoginPage), "/register" (RegisterPage), "/chat" (ProtectedRoute wrapping ChatInterface), (3) add loading spinner during initial auth check (isLoading from AuthContext), (4) redirect to /chat after successful login/register, (5) redirect to /login after logout | Restrictions: Must use React Router v6 syntax (BrowserRouter, Routes, Route, Navigate), check authentication before rendering protected routes, show loading state during token verification, handle deep linking (redirect to intended route after login) | Success: Unauthenticated users are redirected to /login, authenticated users can access /chat, login redirects to /chat, logout redirects to /login, loading state shows during auth check_

- [ ] 7.8. 更新ChatInterface集成认证
  - Files:
    - `frontend/src/components/chat/ChatInterface.tsx`
    - `frontend/src/components/layout/TopNavBar.tsx`
    - `frontend/src/hooks/useAgent.ts`
  - Display current username in TopNavBar
  - Add logout button to TopNavBar
  - Modify useAgent to include Authorization header
  - Load historical messages on mount
  - Purpose: 在聊天界面显示用户信息和支持历史加载
  - _Leverage: useAuth hook, existing ChatInterface_
  - _Requirements: 14, 1 (Chat Interface)_
  - _Prompt: Role: Frontend Integration Developer | Task: Integrate authentication into chat interface following requirements 14 and 1, modifying: (1) TopNavBar.tsx to display user.username from useAuth(), add logout icon button calling useAuth().logout(), (2) useAgent.ts to ensure Axios includes Authorization header (should be automatic from AuthContext), add loadHistory() function calling GET /api/agent/history to fetch recent messages, (3) ChatInterface.tsx to call loadHistory() on mount, add messages to ChatContext, (4) handle 401 errors in useAgent to trigger logout, (5) show welcome message with username on first visit | Restrictions: Must display username prominently, logout button should be accessible, load history only once on mount, handle empty history gracefully, clear messages on logout, maintain existing chat functionality | Success: Username is displayed in TopNavBar, logout button works, historical messages load on mount, chat functionality unchanged, 401 triggers logout_

### Integration and Testing

- [ ] 7.9. 创建认证相关API端点测试
  - Files:
    - `backend/tests/test_auth_api.py`
  - Test user registration flow
  - Test login with correct/wrong credentials
  - Test token verification
  - Test protected endpoint access
  - Purpose: 验证认证系统可靠性
  - _Leverage: pytest, TestClient_
  - _Requirements: 14_
  - _Prompt: Role: QA Engineer specializing in security testing | Task: Create comprehensive authentication tests following requirement 14, testing: (1) POST /auth/register with valid data creates user and returns token, (2) register with duplicate username returns 400, (3) register with invalid password returns 422, (4) POST /auth/login with correct credentials returns token, (5) login with wrong password returns 401, (6) GET /auth/me with valid token returns user info, (7) /auth/me with invalid token returns 401, (8) POST /api/agent/chat without token returns 401, (9) /api/agent/chat with valid token succeeds, using TestClient, mocking database operations | Restrictions: Must test all error cases, verify JWT token structure, check password is hashed (not plaintext), ensure SQL injection prevention, test concurrent registrations | Success: All tests pass, error handling is correct, tokens are valid JWT, passwords are hashed, security vulnerabilities are prevented_

- [ ] 7.10. 端到端认证流程测试
  - Test complete flow: register → login → chat → logout → login → history loaded
  - Test multi-user scenario (different users have isolated data)
  - Test token expiration handling
  - Test persistence across page refresh
  - Purpose: 验证完整用户体验
  - _Leverage: Running application, manual testing_
  - _Requirements: 14_
  - _Prompt: Role: QA Engineer with end-to-end testing expertise | Task: Perform comprehensive authentication flow testing following requirement 14, testing: (1) register new user "alice" → auto-login → see chat interface with username, (2) send messages → logout → login as "alice" → see previous messages, (3) register second user "bob" → send different messages → verify alice and bob have separate chat histories, (4) simulate token expiration (modify localStorage to expired token) → any API call redirects to login, (5) login → refresh page → verify still logged in and messages persist, (6) test preference persistence (连续3次闪卡 → logout → login → "化学反应" → verify quiz preference loaded), document any bugs with screenshots | Restrictions: Test with at least 2 users, verify complete data isolation, check all edge cases, test on fresh browser (clear storage), document test steps and results | Success: Complete auth flow works smoothly, data persists correctly, multi-user isolation works, token expiration is handled, page refresh maintains auth state, preferences are loaded from DB_

## Summary

Total tasks: **44 tasks** organized in 7 phases:
- **Phase 1**: 5 tasks (Project Setup) ✅
- **Phase 2**: 11 tasks (Core Modules) ✅
- **Phase 3**: 5 tasks (Skills Implementation) ✅
- **Phase 4**: 3 tasks (Agent API Integration) ✅
- **Phase 5**: 9 tasks (Frontend Implementation) ✅
- **Phase 6**: 4 tasks (Integration and Testing) ⏳
- **Phase 7**: 10 tasks (用户认证与持久化) 🆕 ⏳

**Estimated Implementation Time**: 
- Phases 1-6: 3-5 days ✅
- Phase 7 (新增): +2-3 days
- **Total**: 5-8 days (full-time development)

**Dependencies**: Tasks must be completed in order within each phase, but phases can have some parallel work (backend and frontend can progress simultaneously after phase 1).

**Key Milestones**:
- After Phase 1: Project infrastructure is ready
- After Phase 2: Core backend logic is complete
- After Phase 3: Skills can generate content
- After Phase 4: Backend API is fully functional
- After Phase 5: Frontend UI is complete
- After Phase 6: System is production-ready for demo

