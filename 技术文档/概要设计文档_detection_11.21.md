# 附件一：概要设计文档（AASIST_Server）


## 1. 概述
### 1.1 设计目标
- 提供一个稳定、可扩展的后端服务平台，用于托管、部署和调用 AASIST 相关的反假音/语音防伪 模型（或其它模型推理服务）；
- 为上层客户端（例如管理后台、批处理脚本、在线推理 API）提供统一且安全的接口；
- 支持模型管理、数据管理、任务调度、推理请求处理、结果存储与审计日志；
- 易于部署（支持容器化）、便于扩展（水平扩展、模块化）、便于维护（清晰的模块边界与接口规范）；
- 满足基本的安全与权限管理要求，确保推理与数据访问的合规性。

### 1.2 功能需求（高层）
- 用户与权限管理：用户认证、角色与权限控制（管理/开发/审计等）；
- 模型管理：上传、版本管理、启停、元数据管理；
- 数据管理：音频样本或输入数据的上传、标注、查询与批量导入导出；
- 推理 API：对外提供同步和异步推理接口，支持批量请求与单条请求；
- 任务管理：异步任务队列、任务状态查询、重试策略；
- 结果存储与查询：推理结果持久化、结果检索与导出；
- 日志与审计：访问日志、操作审计、异常告警；
- 健康检查与监控：服务健康接口、性能指标上报（可接 Prometheus 等）；
- 运维支持：配置管理、部署脚本、备份与恢复方案。

## 2. 系统结构设计
### 2.1 总体架构（分层）
建议采用典型的分层/微服务风格（可单体部署或微服务拆分）：
- 表现层（Presentation Layer）
  - 对外 REST/HTTP API（用于客户端与第三方系统）
  - Web 管理界面（可选）
- 应用层（Application / Service Layer）
  - 业务服务（用户管理服务、模型管理服务、推理服务、任务调度服务）
- 领域/逻辑层（Domain / Business Logic）
  - 模型载入与推理封装、数据处理与预处理、结果后处理
- 持久层（Persistence）
  - 关系型数据库（元数据、用户、任务、结果）
  - 对象存储（音频文件、模型文件）
  - 缓存层（Redis，用于会话、任务队列、短期缓存）
- 基础设施层（Infrastructure）
  - 消息队列（RabbitMQ / Redis Queue / Celery）
  - 日志与监控（ELK、Prometheus + Grafana）
  - 安全部署（TLS、认证网关、API 网关）

（可根据实际规模将各部分拆分为独立服务）

### 2.2 功能模块划分
- API 网关 / 路由模块
  - 统一入口，做鉴权、限流、日志记录、路由至内部服务
- 用户与权限模块
  - 登录、注册（若需要）、JWT/Session 管理、RBAC 权限校验
- 模型管理模块
  - 模型上传、注册、版本管理、启用/停用、模型元数据（架构、输入输出说明）
- 数据管理模块
  - 音频/样本上传、标注接口、批量导入导出
- 推理模块
  - 模型加载、内存/显存管理、输入预处理、推理调用、输出后处理
- 任务调度与队列模块
  - 异步任务投递、任务执行、回调机制、重试与失败处理
- 结果持久化模块
  - 将推理结果、评分、可信度等信息存入数据库并提供查询接口
- 日志与审计模块
  - 操作审计、异常捕获、统一日志格式与归档
- 监控与健康检查模块
  - 提供 /health、/metrics 等接口

### 2.3 模块之间的调用关系
- 外部客户端 -> API 网关 -> 业务 API（鉴权 -> 路由）
- Push 推理请求 -> 推理模块（若异步：先入队到任务队列 -> 工作进程从队列取任务 -> 调用推理模块 -> 持久化结果 -> 触发回调/通知）
- 模型管理操作（上传/删除）-> 对象存储（模型文件）+ 模型管理模块更新元数据
- 数据上传 -> 对象存储（音频） + 数据管理模块更新索引/元数据
- 日志与审计模块被各服务调用记录操作
- 缓存（Redis）用于会话、短期结果或限流计数

模块调用关系示例（简化）：
API 网关
  ├─ 用户服务
  ├─ 模型服务
  ├─ 推理服务 -> 任务队列 -> 推理工作进程 -> 模型服务（本地/远端模型加载）
  ├─ 数据服务 -> 对象存储
  └─ 审计/日志服务

## 3. 接口设计
接口分为外部接口（对客户端或第三方）和内部接口（模块间调用、队列消息、RPC 等）。

### 3.1 外部接口（建议采用 RESTful 设计；返回 JSON）
- 认证授权
  - POST /api/v1/auth/login
    - 请求：{ "username": "...", "password": "..." }
    - 返回：{ "access_token": "...", "expires_in": 3600, "refresh_token": "..." }
  - POST /api/v1/auth/refresh
- 用户管理
  - GET /api/v1/users/{id}
  - POST /api/v1/users
  - PUT /api/v1/users/{id}
  - DELETE /api/v1/users/{id}
- 模型管理
  - GET /api/v1/models
  - GET /api/v1/models/{model_id}
  - POST /api/v1/models  （multipart/form-data 上传模型文件或提供对象存储地址）
  - PUT /api/v1/models/{model_id}
  - POST /api/v1/models/{model_id}/activate
  - POST /api/v1/models/{model_id}/deactivate
- 数据/样本管理
  - POST /api/v1/samples (上传音频)
  - GET /api/v1/samples/{id}
  - GET /api/v1/samples?query=...
- 推理接口（同步）
  - POST /api/v1/infer
    - 请求：{ "model_id": "...", "input": base64_audio或url, "options": {...} }
    - 返回：{ "job_id": "...", "result": {...}, "status": "success" }
- 推理接口（异步）
  - POST /api/v1/infer/async
    - 返回：{ "job_id": "..." }
  - GET /api/v1/infer/{job_id}/status
  - GET /api/v1/infer/{job_id}/result
- 任务与结果
  - GET /api/v1/tasks
  - GET /api/v1/tasks/{task_id}
- 健康检查与监控
  - GET /health  —— 返回服务状态（UP/DOWN）
  - GET /metrics —— Prometheus 格式指标（或 /metrics/text）

接口安全与约束：
- 所有受限接口必须校验 access_token（JWT）和 RBAC 权限；
- 输入数据应做大小与格式校验（例如音频时长、文件类型、最大 payload）；
- 支持 HTTPS；
- 对上传/下载资源使用预签名 URL（若使用对象存储）。

### 3.2 外部接口 - 错误码与响应格式
- 统一响应结构：
  - 成功：{ "code": 0, "message": "OK", "data": {...} }
  - 失败：{ "code": 1001, "message": "Invalid input", "details": {...} }
- 常用错误码示例（可扩展）
  - 1000: 未知错误
  - 1001: 参数校验错误
  - 1002: 认证失败
  - 1003: 权限不足
  - 1004: 资源不存在
  - 1005: 服务繁忙/限流
  - 2001: 推理任务提交失败

### 3.3 内部接口
- 模块间建议采用轻量 RPC（HTTP/REST 或 gRPC）或内部函数调用（同一进程）：
  - /internal/models/load?model_id=
  - /internal/tasks/push （消息队列或内部 API，格式：{ task_id, model_id, input_url, params }）
  - /internal/metrics/update
- 任务队列消息格式（JSON）：
  - { "task_id": "...", "model_id": "...", "input": { "type": "url/base64", "value": "..." }, "priority": 0, "meta": {...} }
- 对象存储接口：
  - put_object(bucket, key, stream/bytes, metadata)
  - get_presigned_url(bucket, key, expires_in)
- 模型插件接口（若支持多种模型/框架）
  - 定义模型加载器接口（伪代码）
    - load_model(path_or_uri) -> ModelHandle
    - predict(ModelHandle, preprocessed_input) -> raw_output
    - get_metadata(ModelHandle) -> { input_spec, output_spec, version }
  - 所有模型加载器需实现同一接口以便统一管理。



## 4. 编码规范（接口规约与命名规则等）
说明：以下规范以 Python + REST 后端为主（若使用其它语言，例如 Node.js、Go，请按对应语言最佳实践替换相关细则）。主要元素参考“附件五”并做工程化细化。

### 4.1 通用风格
- 代码风格遵循 PEP8（Python）：行长不超过 88（black 默认）或 79；使用 black/flake8/ruff 进行格式化与检查；
- 注释与文档字符串：
  - 所有公共模块、类与函数必须包含 docstring（遵循 Google 或 NumPy 风格）；
  - 复杂逻辑处应有行内注释，注释应说明 why 而非 what。
- 提交信息：
  - 使用简洁的 commit message，遵循 Conventional Commits（如 feat:, fix:, docs:, chore:）；
- 分支策略：
  - main/master：稳定分支，仅合并通过 CI 的 PR；
  - develop：日常集成分支（可选）；
  - feature/bugfix：按功能拆分

### 4.2 命名规则
- 文件与模块：
  - 小写字母与下划线分隔（Python）：e.g., model_loader.py, inference_service.py
- 类名：
  - 使用 CapWords（PascalCase）：e.g., ModelManager, InferenceWorker
- 函数/方法/变量：
  - 小写加下划线（snake_case）：e.g., load_model_from_uri, pre_process_audio
- 常量：
  - 全大写加下划线：e.g., DEFAULT_TIMEOUT_SECONDS
- 数据库表/字段：
  - 表名复数小写（snake_case）：users, models, inference_results
  - 主键统一使用 id（uuid/varchar），外键命名 end_with _id（e.g., model_id）

### 4.3 接口规约
- REST API：
  - 使用语义化 URL（资源导向），使用 HTTP 方法表示动作（GET/POST/PUT/DELETE/PATCH）；
  - 状态码语义化：
    - 200/201 成功，400 Bad Request（参数错误），401 Unauthorized，403 Forbidden，404 Not Found，429 Too Many Requests，500 Internal Server Error；
  - 响应格式一致（见第 3.2）；
  - 输入校验与限流：对所有上传（音频/模型）进行大小限制与类型校验；
- API 版本管理：
  - URL 路径中包含版本号，如 /api/v1/…，向后兼容时新增 /api/v2/
- 安全：
  - 强制使用 HTTPS；
  - 敏感操作需做权限校验与审计记录；
  - 对外接口返回避免泄露内部异常堆栈信息。

### 4.4 错误处理与日志
- 错误处理：
  - 捕获并统一处理未捕获异常，返回标准错误结构；
  - 对外错误信息不可泄露内网细节（堆栈等），但内部日志应完整记录用于排查；
- 日志规范：
  - 使用统一日志库（Python 推荐 logging），日志包括时间、级别、trace_id（或 request_id）、模块、消息体；
  - 业务日志与访问日志分开；错误日志级别 ERROR/CRITICAL；
  - 可将日志输出到 stdout/stderr（适用于容器化）或集中式日志系统（ELK）。

### 4.5 单元测试、集成测试与 CI
- 单元测试覆盖关键模块（推理逻辑、输入校验、模型加载器）；
- 提供端到端集成测试（使用小模型或 mock 推理器）；
- 在 CI（GitHub Actions / GitLab CI）中完成：
  - 代码格式校验（black/ruff/flake8）
  - 单元测试（pytest）
  - 安全扫描（safety / bandit）和依赖审计
- 测试数据与凭据不得提交到仓库（使用 secret 管理）

### 4.6 配置管理
- 配置文件使用环境变量 + 配置文件（YAML/JSON）；敏感信息（密钥、凭证）通过 secrets 管理；
- 推荐使用 Twelve-Factor App 原则：配置与代码分离，按环境注入配置；
- 提供默认配置模板（e.g., config.example.yml）并在 README 中说明必要环境变量。

### 4.7 性能与资源管理
- 模型推理需有显存/内存管理策略：限制并发推理数、复用模型实例、优先级队列；
- 支持批量推理以提升吞吐（视模型支持情况）；
- 对长时间运行的任务设置超时与取消机制。

### 4.8 安全和合规
- 输入文件做病毒/木马检查（可选）；
- 对上传文件做类型校验与大小限制；
- 遵循最小权限原则分配服务账号与访问权限；
- 定期更新依赖并修复安全漏洞。

 
```