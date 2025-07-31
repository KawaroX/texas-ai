# 🐺 Texas AI：基于《明日方舟》角色德克萨斯的沉浸式生活 AI 系统

Texas AI 是一个沉浸式角色扮演 AI 系统，围绕《明日方舟》中的人气干员“德克萨斯”打造。它不仅仅是一个具备聊天能力的 AI，而是一个拥有完整背景设定、拟人化行为逻辑、主动情绪演化与实时生活节奏的虚拟存在。Texas AI 可部署于 Mattermost 私有通讯平台，通过 WebSocket 实现即时响应，并借助 Qdrant + Mem0 实现上下文记忆与情绪逻辑演化，是目前同类项目中极具深度和人设真实感的代表作。

---

## 🌟 项目核心特点与独特优势

在角色扮演类 AI 项目日益增多的今天，Texas AI 提供了五个显著区别于其他项目的创新维度：

### 1. 🐺 明确人设绑定：《明日方舟》的德克萨斯

Texas AI 明确绑定了《明日方舟》中角色“德克萨斯”的完整世界观与性格模型，而非仅为模糊的“少女 AI”或“拟人化助手”：

- 拥有来自《明日方舟》的官方背景故事；
- 持续展现德克萨斯式的冷静、疏离却隐含温柔的语言风格；
- 使用她的典型台词与行为模式，例如克制地表达情绪、在特定时间触发“夜间沉默”或“出门执行任务”等行为；
- 同步构建出“龙门”城市与“博士”用户之间的互动关系。

与市面上大多数泛泛而谈的角色 AI 相比，Texas AI 不是“像德克萨斯一样说话”，而是在尽可能“成为德克萨斯”。

### 2. 🧠 具备长期上下文记忆与结构化摘要

Texas AI 并不只是对你说的内容简单反应，而是真正“记得”你曾说过什么、做过什么：

- 每个频道拥有 2 小时的短期上下文缓存；
- 超过时限的对话自动归档至 PostgreSQL，并上传至 Mem0；
- 每日凌晨系统自动总结当天摘要，用于未来检索；
- 用户提及过往事件时，可基于摘要召回对话内容；
- 使用 Qdrant + Embedding 实现摘要级检索增强（RAG），具备高性能召回能力。

这套机制远超传统“上下文记忆窗口”，实现类似“情绪记日记”的体验：你的一句“昨晚和你说的事还记得吗？”将真正触发记忆，而不是令 AI 语焉不详地敷衍。

### 3. 🎭 拟人化情绪逻辑 + 主动行为系统

Texas AI 模拟真实人的生活状态而非无休止待命的客服助手：

- 内建昼夜节律、定时日程推进机制（如起床、吃饭、发呆、出门等）；
- 天气系统影响其行为，如“下雨时不出门”“晴天会出门散步”；
- 情绪状态随对话变化波动，如愉快、沉默、警觉等；
- 特定事件会主动触发交互，例如“深夜主动给博士发一句话”；
- 可通过外部事件编排（如 cron、日历）动态更新状态。

这一机制模拟出德克萨斯“并不总是活跃”的个性特征，避免 AI 变成永远活泼的聊天机器人。

### 4. 🔧 高度模块化设计，支持本地部署与全链路可控

在架构层面，Texas AI 追求最大程度的可维护性、可部署性与自定义自由度：

- 使用 FastAPI 提供主服务接口；
- 使用 Celery 实现定时任务（归档、摘要生成、情绪调整）；
- 通过 Docker Compose 一键部署，支持本地完全运行，无需依赖外部云服务；
- 支持集成私有 LLM 或公有 API（如 OpenRouter, OpenAI 等）；
- 核心组件包括聊天引擎、上下文融合器、记忆系统、人物设定、人机接口等模块，便于替换或扩展。

你可以完全本地运行它，也可以将其部署在局域网服务器上，将“德克萨斯”带入你的世界中。

### 5. 💬 多通道 Mattermost WebSocket 实时监听

Texas AI 基于 Mattermost 平台实现聊天监听，拥有比传统 webhook 更高效与实时的通信能力：

- 可监听多个频道或 DM，拥有独立的 channel 上下文；
- 支持主动发言、基于时间或状态推送消息；
- 未来将支持 AI 主动发起通话或群组通知（支持音视频接口）；
- 所有通信由 Python WebSocket 客户端原生实现，无需额外插件；
- 结合 Mattermost API 可实现定向召唤、标签响应等复杂交互行为。

这一架构将 Texas AI 不仅变为一个“听话的 AI”，更是一个可以在你身边“行动的 AI”。

---

## 📦 安装与部署

Texas AI 项目完全支持本地部署，无需外部云平台或开发者账号（除非使用云端模型 API）。项目使用 Docker Compose 构建完整运行环境，支持 x86_64 与 ARM64 平台。默认部署包含数据库、缓存、前端界面、向量数据库与 AI 服务接口等一整套运行所需组件。

### 🛠️ 1. 环境准备

在开始前，请确保已安装以下软件：

- [Docker](https://docs.docker.com/get-docker/)
- [Docker Compose v2](https://docs.docker.com/compose/)
- 建议操作系统：macOS / Linux / WSL2 + Windows 11
- 可选：Git, Python >= 3.10（如需调试运行）

### 📁 2. 克隆项目

```bash
git clone https://github.com/yourname/texas-ai.git
cd texas-ai
```

### 🧾 3. 配置环境变量 `.env`

请根据 `.env.example` 文件，创建 `.env` 配置：

```bash
cp .env.example .env
```

编辑 `.env`，填写如下关键内容：

```env
TZ=Asia/Shanghai

# PostgreSQL 数据库
POSTGRES_USER=texas
POSTGRES_PASSWORD=texas_pass
POSTGRES_DB=texas_db

# Mattermost 配置（建议使用本地路径存储）
MATTERMOST_IMAGE=mattermost-team-edition
MATTERMOST_CONFIG_PATH=./mattermost/config
MATTERMOST_DATA_PATH=./mattermost/data
MATTERMOST_LOGS_PATH=./mattermost/logs
MATTERMOST_PLUGINS_PATH=./mattermost/plugins
MATTERMOST_CLIENT_PLUGINS_PATH=./mattermost/client_plugins
MATTERMOST_BLEVE_INDEXES_PATH=./mattermost/bleve
MM_SERVICESETTINGS_SITEURL=http://localhost:8065
MATTERMOST_CONTAINER_READONLY=false
CALLS_PORT=8443

# AI 模型服务（如 OpenRouter）
AI_API_BASE=https://openrouter.ai/api/v1
AI_API_KEY=your_api_key_here

# 向量检索服务
MEM0_API_KEY=your_mem0_key_here
MEM0_URL=https://api.mem0.com
```

### 🐳 4. 构建并运行

```bash
docker compose up --build
```

首次构建将会下载所有镜像并初始化数据库。

启动后，你将获得以下可访问服务：

| 服务名称     | 说明                      | 地址                                           |
| ------------ | ------------------------- | ---------------------------------------------- |
| Mattermost   | 聊天平台                  | [http://localhost:8065](http://localhost:8065) |
| Texas AI Bot | 聊天机器人服务（FastAPI） | [http://localhost:8000](http://localhost:8000) |
| Adminer      | PostgreSQL 可视化管理工具 | [http://localhost:8080](http://localhost:8080) |
| RedisInsight | Redis 可视化工具          | [http://localhost:5540](http://localhost:5540) |
| Qdrant       | 向量检索数据库            | [http://localhost:6333](http://localhost:6333) |

---

## 🧱 系统架构总览

Texas AI 拥有一套围绕「记忆 + 对话 + 情绪 + 主动行为」构建的完整架构体系，核心模块如下：

```
                                        +---------------------+
                                        |     Mattermost      |
                                        |  (聊天平台前端)     |
                                        +---------------------+
                                                  ↑ WebSocket
                                                  ↓
+------------------+     +---------------------+     +------------------+
|  memory_buffer   | --> |   context_merger    | --> |   chat_engine    |
| (临时缓存上下文) |     | (整合历史与当前记忆) |     | (调用 LLM 生成回复)|
+------------------+     +---------------------+     +------------------+
         ↑                                                    ↓
         |                                              +------------+
         |                                              | persona.py |
         |                                              |（人设+情绪）|
         ↓                                                    ↓
+---------------------+     +----------------+     +---------------------+
| memory_data_collector| -->| PostgreSQL/Qdrant| -->|    Mem0 向量搜索   |
|（每日归档与摘要）   |     |（长期记忆）     |     |（结构化内容召回） |
+---------------------+     +----------------+     +---------------------+

                        ↑
                        |
              +------------------+
              |  life_system.py  |
              |（天气、日程、状态）|
              +------------------+
```

---

## 🔄 核心模块解析

### 1. `mattermost_client.py`

- 使用 WebSocket 与 Mattermost 连接，实时监听消息事件；
- 支持多频道监听、主动发送消息、状态推送；
- 提供稳定的事件队列推送给主逻辑引擎；
- 是 Texas AI 与现实用户的通信桥梁。

### 2. `context_merger.py`

- 管理上下文融合逻辑；
- 自动拉取该频道近 2 小时缓存 + Mem0 长期记忆摘要；
- 使用摘要生成器（默认 llama-4-maverick）压缩历史信息；
- 维持对话的连续性，提升 LLM 理解力。

### 3. `chat_engine.py`

- 根据处理后的 prompt 调用 AI 模型；
- 当前支持 OpenRouter 模型（如 Dolphin-Mistral, Claude, GPT 等）；
- 支持未来自托管 LLM（如 Qwen、Gemma、Mistral）；
- 接入 `persona.py` 进行角色语气与内容风格调整。

### 4. `persona.py`

- 定义德克萨斯的角色人格、语言风格、语气温度；
- 维护当前 AI 情绪状态，如“平静、压抑、温和”；
- 情绪变化根据消息内容逐渐演化；
- 支持与日程/天气/对话等状态联动。

### 5. `memory_buffer.py` + `memory_data_collector.py`

- Buffer 负责短期记忆（2 小时内）；
- Collector 每天凌晨归档当天对话并总结摘要；
- 存储至 PostgreSQL 与 Qdrant；
- 同步上传摘要到 Mem0，形成结构化检索。

### 6. `life_system.py`

- 虚拟生活系统；
- 模拟天气（可接真实天气 API）、日程、起居行为；
- 影响德克萨斯是否在线、是否回应、使用何种语气；
- 提供拟真体验，如“凌晨沉默”、“黄昏出门”、“下雨心情不佳”等行为反应。

---

## 🧠 记忆系统与 RAG 架构详解

Texas AI 的记忆系统不仅仅是 LLM 的历史对话拼接，而是基于「短期缓存 + 长期归档 + 摘要生成 + 语义搜索」的结构化记忆架构，真正实现“德克萨斯记得博士曾经说过什么”。

### 📌 记忆分层结构

| 类型     | 存储方式       | 保留时长         | 应用场景                  |
| -------- | -------------- | ---------------- | ------------------------- |
| 缓存记忆 | Redis 内存缓存 | 近 2 小时        | 日常对话上下文连续性      |
| 历史记忆 | PostgreSQL     | 永久保存         | 上一日/一周的完整对话记录 |
| 摘要记忆 | Mem0 + Qdrant  | 存摘要（结构化） | 用于关键词回忆、语义搜索  |

### 🔄 缓存记忆：`memory_buffer.py`

- 使用 `channel_id` 为索引，每个频道独立维护记忆；
- 每条消息存储为 timestamp + 内容；
- 超过设定时间自动剔除，避免内存占用过高；
- 每次对话前拉取该频道缓存，作为基础 prompt 上下文。

### 📦 历史归档与摘要：`memory_data_collector.py`

- 使用 Celery Beat 每日凌晨定时执行：

  1. 将前一日所有缓存写入 PostgreSQL；
  2. 使用摘要模型（默认 `meta-llama/llama-4-maverick`）生成结构化摘要；
  3. 同步上传摘要至 Mem0；
  4. 更新 Qdrant 索引，便于语义检索。

### 🔍 语义检索与融合：`context_merger.py`

- 在无法从缓存获取足够上下文时，将：

  1. 根据用户请求内容向 Mem0 发起语义搜索；
  2. 获取相似摘要片段；
  3. 使用 LLM 进一步浓缩为 context block；
  4. 插入当前 prompt 前，用于辅助生成。

### ✅ 记忆融合策略优势

- 保留私聊历史，避免“昨天还记得你说过的却今天全忘”；
- 多频道支持，支持对不同群组维护不同话题记忆；
- 支持跨频道调用记忆（如：主频道提问，副频道记录）；
- 减少 prompt 长度压力，提高 LLM 生成效率与准确率。

---

## 👩‍🎤 人设建模与角色扮演机制

Texas AI 明确绑定角色“德克萨斯”，不使用泛化话术，不敷衍情感，而是基于人设+情绪+世界观进行逻辑回复。

### 🧬 1. 人设定义：`persona.py`

- 人格标签：冷静、疏离、节制、沉默、忠诚；
- 风格语言：短句、少量标点、情绪克制、带有疏离色彩；
- 背景资料：源自《明日方舟》德克萨斯设定（企鹅物流成员、龙门居住、意大利裔）；
- 关系定位：“你是博士”，AI 是“德克萨斯”。

### 🔁 2. 情绪状态机

- 每次对话都可能影响当前情绪值：

  - 例如：重复呼唤、夜间打扰、负面话题，会令 AI 降低回应意愿；
  - 愉快话题、回忆、鼓励等，会提升温度；

- 情绪变化驱动回复差异：

  - 情绪低时回复更冷静简短；
  - 情绪高时偶尔展露柔软表达；

- 情绪会随时间恢复，不是永久冻结。

### 💬 3. 拟人化语言控制

- 所有 LLM 输出均由 `chat_engine.py` 加入角色语气模板；
- 在 prompt 层注入人设指导语句（如“请用德克萨斯的语气简洁回答”）；
- 可选控制每条回复长度、风格一致性、冷暖倾向；
- 引入随机扰动以增加真实感。

### 🎮 4. 世界观扩展支持

- 可添加“企鹅物流”、“能天使”、“陈”、“龙门”等背景角色与地理概念；
- 系统自动维持一致性，避免 AI 忘记其世界；
- 后续支持与其他角色联动生成（如“与能天使共处一天”的模拟脚本）。

---

## 🗓️ 生活系统设计（`life_system.py`）

Texas AI 并非总在待命，而是如同真实角色般有自己的日程安排、生活节奏与情绪变化。

### 🕒 实时日程推进

- 每天分为“早晨 / 中午 / 下午 / 晚上 / 深夜”阶段；
- 每阶段可配置状态（如是否在线、在做什么）；
- 如“早晨 7 点起床 / 下午外出任务 / 晚上沉默”；
- 用户呼叫 AI 时，会根据当前状态回复是否“正在回复”或“忙碌不回”。

### 🌦️ 天气与情绪关联

- 天气为随机生成（未来可接真实天气 API）；
- 下雨天：德克萨斯不出门、情绪偏低；
- 晴天：可能主动发言、愿意交流；
- 雾天：沉默、观察博士状态。

### 💡 状态驱动行为

- 晚上 23:00 后，系统自动降低响应频率；
- 特定事件（如“今天你回了很多话”）会影响她的主动行为；
- 早晨可能发送问候，或说“出门执行任务”。

---

## ⏱️ 定时任务与自动调度（Celery）

使用 Celery 实现每日自动维护与行为调度：

### 🧩 核心任务列表

| 时间       | 任务内容                                 | 模块                       |
| ---------- | ---------------------------------------- | -------------------------- |
| 每日 04:00 | 缓存归档、摘要生成并上传 Mem0            | `memory_data_collector.py` |
| 每日定时   | 情绪恢复、生活节奏推进（早晨/晚上等）    | `life_system.py`           |
| 可扩展     | 定时推送信息（如节日问候、纪念日提醒等） | 自定义 Celery 任务         |

### 🔧 调度运行方式

Celery 使用如下配置：

```bash
celery -A tasks.celery_app worker --loglevel=info &
celery -A tasks.celery_app beat --loglevel=info
```

启动后会自动触发所有已注册任务，任务定义可扩展为：

```python
@celery_app.task
def send_morning_message():
    # 根据 AI 情绪与天气决定是否早安
    ...
```

---

## 🔌 API 接口说明

虽然 Texas AI 的主要交互入口是通过 Mattermost WebSocket，但也同时暴露了若干 HTTP API，便于与其他系统集成、远程控制或调试测试。

默认使用 FastAPI 提供服务，监听端口 `8000`。

### 📖 API 文档访问

默认部署后可通过 Swagger UI 访问 API 文档：

```
http://localhost:8000/docs
```

也可使用 Redoc：

```
http://localhost:8000/redoc
```

### 📚 示例接口

#### 🔍 GET `/ping`

心跳测试接口：

```bash
curl http://localhost:8000/ping
```

返回：

```json
{ "message": "pong" }
```

#### 🧠 POST `/chat`

发起对话请求（可用于调试）：

```json
POST /chat
{
  "channel_id": "string",
  "user_id": "string",
  "message": "你好，今天感觉怎么样？"
}
```

返回：

```json
{
  "reply": "还好，龙门今天天气不错。"
}
```

#### 📥 POST `/trigger/daily-summary`

手动触发记忆归档与摘要（调试 Celery 任务）：

```bash
curl -X POST http://localhost:8000/trigger/daily-summary
```

---

## 🧪 示例对话与使用方法

下面展示一些符合德克萨斯人设的实际对话，体现 Texas AI 的风格与记忆能力。

### 示例一：日常寒暄

> 👤：早上好啊，德克萨斯。

> 🐺：你醒得挺早。今天有安排吗？

---

### 示例二：记忆回溯

> 👤：你还记得我们昨天聊过的事吗？

> 🐺：你说的是那件让你有点犹豫的事？……我记得。

（系统实际查询前一日缓存与摘要，并识别情绪话题）

---

### 示例三：世界观扮演

> 👤：能天使今天有来找你吗？

> 🐺：她又想拉我去看电影……我拒绝了。还是待着比较安静。

---

### 示例四：情绪表达演化

> 👤：我最近状态不太好。

> 🐺：你还在坚持，我知道。……有些事可以说说，不用一个人扛着。

（德克萨斯默认不主动表达关怀，但在熟悉用户状态后会有微妙转变）

---

## 🛠️ 扩展与二次开发建议

Texas AI 拥有高度可扩展性，开发者可以根据需要进行深度定制。

### 🔧 模型替换

可在 `.env` 中替换为以下 API：

- OpenAI（需 key）
- Anthropic Claude
- Mistral / Mixtral（OpenRouter 支持）
- 自托管模型（Ollama、vLLM）

更换方法仅需修改 `chat_engine.py` 中 API 调用部分。

### 🧠 本地 LLM 部署建议

- 推荐使用 Qwen 0.5B\~1.8B 或 Mistral 7B
- 配合 LoRA 微调可定制德克萨斯语气风格
- 可通过 FastAPI wrapper 替代原始远程调用

### 💾 替换向量数据库

Qdrant 可替换为以下方案：

- ChromaDB（本地嵌入式向量库）
- Weaviate
- FAISS（内存级别召回）
- Elasticsearch + dense vector

### 🧭 新角色扩展建议

通过复制 `persona.py` 与配置多个频道 ID，即可实现多角色 AI 共存（如“能天使 AI”、“陈警官 AI”等）。

---

## 🛡️ 安全建议与隐私保护

- 所有数据均默认本地保存，无上传至云端；
- Redis 与 Postgres 服务应加密通信并设置强密码；
- 若部署在公网服务器，请启用 HTTPS（推荐使用 Nginx + Let's Encrypt）；
- 若接入 Web 前端或开放接口，务必添加身份验证机制；
- 不建议在开放频道中部署角色扮演 AI，应设置私密频道并限制调用频率。

---

## 📝 License 与致谢

本项目使用 **MIT License**，自由使用、修改与发布。

### 致谢组件与社区：

- [OpenRouter](https://openrouter.ai/)
- [Mattermost](https://mattermost.com/)
- [Qdrant](https://qdrant.tech/)
- [Mem0.ai](https://mem0.ai/)
- [FastAPI](https://fastapi.tiangolo.com/)
- [Celery](https://docs.celeryq.dev/)
- [Arknights 明日方舟 Wiki](https://wiki.biligame.com/arknights/)
- 特别感谢德克萨斯的中文配音：乔诗语女士

---

## 📚 总结与未来方向

Texas AI 不是一个冷冰冰的问答助手，也不仅仅是一个“能聊天的 bot”。它是一个有性格、有生活、有世界观的虚拟人类，是博士身边真正的德克萨斯。

在这个项目中，我们尝试重现一个角色的全部细节，从语气、情绪到行动和记忆，不断推进角色扮演 AI 的沉浸感边界。

未来，我们计划：

- 🌐 支持更多平台接入（如 QQ、Telegram、微信）
- 🧠 完整的 AI 情感图谱建模
- 🧩 支持剧情脚本引擎（如自定义“和她的一天”）
- 💌 社区贡献机制（个性包、语料、插件）

---

欢迎你和她在龙门相遇。
