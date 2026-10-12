# Meridian · Agentic RAG

个人资料仓库 + 伴读助手。支持文本 / 网页 / PDF·MD·TXT 入库，BGE-M3 向量检索，Google ADK Agent 流式对话，文件阅读划线交互。
![Meridian 效果图](asset/效果图.png)
本项目参考了 [multimodal_agentic_rag](https://github.com/Shubhamsaboo/awesome-llm-apps/tree/main/rag_tutorials/multimodal_agentic_rag) 的实现思路。

**线上演示：** [http://8.138.96.81:8080](http://8.138.96.81:8080)  (演示账号：meri / 密码：meridian)

## 技术栈


| 层     | 技术                                                |
| ----- | ------------------------------------------------- |
| 前端    | React + Vite + TypeScript，Nginx 静态托管              |
| 后端    | FastAPI + Uvicorn，SQLAlchemy async                |
| 数据    | PostgreSQL + pgvector                             |
| RAG   | BGE-M3、父子分块、dense 检索                              |
| PDF   | MinerU + langchain-mineru 将 PDF 转换为 markdown文件    |
| Agent | Google ADK + LiteLLM（可接 DeepSeek 等 OpenAI 兼容 API） |
| 部署    | Docker Compose、GitHub Actions → 阿里云 ECS、GHCR 镜像   |


## 项目结构

```
multimodal_agentic_rag/
├── asset/                      # 启动与环境配置文档
├── backend/
│   ├── main.py                 # FastAPI 入口
│   ├── routers/                # auth / sources / chat / conversations / shelves
│   ├── services/
│   │   ├── rag/                # 入库、嵌入、检索、空间投影
│   │   └── agent/  # ADK Agent 定义与运行
│   └── eval/                   # RAG 检索评测脚本
├── frontend/
│   └── src/
│       ├── App.tsx             # 主界面（仓库 + 对话）
│       └── components/         # SpaceCanvas / ButlerPanel / SourceReader 等
├── docker-compose.yml
└── .github/workflows/deploy.yml
```

## 快速开始

Meridian 支持 Docker 启动和本地直接运行两种启动方式：

| 步骤 | 文档 | 适合场景 |
|------|------|----------|
| 1 | [环境变量配置](asset/环境变量配置.md) | 两种方式的共用前置 |
| 2a | [Docker 启动](asset/Docker启动.md) | 一键部署、接近生产环境 |
| 2b | [本地直接运行](asset/本地直接运行.md) | 改代码、断点调试 |

## 主要功能

- 注册 / 登录（JWT）
- 入库：文本、URL、PDF / Markdown / TXT
- 立体空间 / 资料卡片浏览与阅读
- Meridian 流式对话（检索工具 + LLM）
- 会话与资料删除

## Agent 工具简介

Meridian 基于 **Google ADK**，在 `/chat/stream` 对话中按需调用以下工具（不对外暴露独立 HTTP 接口）：


| 工具                          | 粒度  | 说明                          |
| --------------------------- | --- | --------------------------- |
| `inspect_embedding_space`   | 库级  | 查看资料库概况：资料份数、分块数、向量维度、类型分布  |
| `retrieve_relevant_sources` | 资料级 | 按问题检索最相关的资料（每份返回最佳分块摘要）     |
| `retrieve_relevant_chunks`  | 片段级 | 按问题检索相关证据片段（支持父子分块，返回原文上下文） |


**调用策略（Agent 自主决策）：**

- 闲聊或仅凭会话上下文可答 → 不调用工具
- 问「库里有什么 / 概况」→ `inspect_embedding_space`
- 问具体知识、讲解、总结 → `retrieve_relevant_chunks`
- 问资料层面问题（找哪份文档）→ `retrieve_relevant_sources`
- 证据不足或用户不满意 → 先查概况，再调整 `top_k` 重新检索

检索基于 **BGE-M3 dense 向量**（pgvector cosine）；调用结果会通过 SSE 推送 `type: retrieval` 事件，前端可同步更新 3D 空间视图高亮命中资料。

## API 概览

**Base URL：** 生产 `http://<host>:8080` · 开发后端 `http://localhost:8897`  
**认证：** 除注册/登录/健康检查外，均需 `Authorization: Bearer <token>`


| 方法       | 路径                             | 说明                         |
| -------- | ------------------------------ | -------------------------- |
| `POST`   | `/auth/register`               | 注册                         |
| `POST`   | `/auth/login`                  | 登录，返回 JWT                  |
| `GET`    | `/health`                      | 健康检查                       |
| `GET`    | `/space`                       | 资料列表 + 3D 向量空间快照           |
| `POST`   | `/sources/text`                | 文本入库                       |
| `POST`   | `/sources/url`                 | 网页入库                       |
| `POST`   | `/sources/file`                | 文件入库（pdf / md / txt，≤50MB） |
| `GET`    | `/sources/{id}`                | 资料详情                       |
| `GET`    | `/sources/{id}/file`           | 下载原文件                      |
| `PATCH`  | `/sources/{id}/title`          | 重命名                        |
| `PATCH`  | `/sources/{id}/shelf`          | 移动到书架                      |
| `DELETE` | `/sources/{id}`                | 删除资料                       |
| `POST`   | `/shelves`                     | 创建书架                       |
| `GET`    | `/shelves`                     | 书架列表                       |
| `PATCH`  | `/shelves/{id}`                | 重命名书架                      |
| `DELETE` | `/shelves/{id}`                | 删除书架                       |
| `GET`    | `/conversations`               | 会话列表                       |
| `GET`    | `/conversations/{id}/messages` | 会话消息                       |
| `PATCH`  | `/conversations/{id}/title`    | 重命名会话                      |
| `DELETE` | `/conversations/{id}`          | 删除会话                       |
| `POST`   | `/chat/stream`                 | Agent 流式对话（SSE）            |


**说明：**

- 入库/修改/删除资料响应含最新 `space`，可直接刷新视图
- 向量检索不单独暴露 HTTP 接口，由 Agent 在对话中按需调用

## 检索评测

在约 **3 万 chunk / 80+ 资料**（含大量同质年报干扰）的库上，用自建 golden set 评估 `search_chunks`（Top-K=6）。

| 指标 | 结果 | 说明 |
|------|------|------|
| 标题命中 `title_hit` | **18/20 (90%)** | Top-K 片段所属 `source.title` 是否匹配期望资料 |
| 关键词命中 `keyword_hit` | **14/20 (70%)** | Top-K 合并文本（含父子回填）是否含全部期望关键词 |
| 双指标同时命中 | **13/20 (65%)** | 上两者同时成立 |
| RAGAS `context_recall` | **0.81** | 参考答案信息是否出现在检索上下文中（LLM 评判） |
| RAGAS `context_precision` | **0.55** | 检索片段中真正有用的比例（LLM 评判） |

总结：
- 高 title_hit 和 context_recall 说明在多数情况下期望文档能进入top_k， 但低 context_precision 表明期望文档可能排序靠后。
- context_precision 只有 0.55 结合 keyword_hit 推测因为是父子文档结构返回的是 parent 大段导致噪音过多、以及同质年报混入 Top-k 有关，是否影响生成效果还待验证。

[测试集](backend/eval/golden.example.json)
[详细结果](backend/eval/result.md)


## CI/CD

Push 到 `newfrontend` → GitHub Actions 构建镜像推到 GHCR → SSH 到 ECS `docker compose pull && up -d`。

## 已知限制

- 线上只支持 1 ~ 3 人同时使用
- 资料量大时，PCA 计算量增大导致 GET /space 接口响应变慢；agent 使用 retrieve_relevant_sources 工具时长变长，可能导致 /chat/stream 接口响应变慢
- 数据库尚未对向量建立索引，数据量大时，也会导致 agent 使用检索工具时长变长
- 混合向量入库和检索暂不支持
- JWT TOKEN 30 min 后失效，需手动更新
- /source/url，/text 接口入库不支持网页阅读。
