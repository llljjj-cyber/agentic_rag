# Docker 启动

适合一键部署、接近生产环境的场景。前端、后端、PostgreSQL 均由 Docker Compose 管理。

> 启动前请先完成 [环境变量配置](./环境变量配置.md)。

## 前置

- Docker + Docker Compose
- 已配置根目录 `.env` 与 `backend/.env`

## 启动

在项目根目录执行：

```bash
docker compose up -d --build
```

首次构建可能较慢（后端需安装 PyTorch 与依赖）。

## 访问

| 服务 | 地址 |
|------|------|
| 前端 | [http://localhost:8080](http://localhost:8080) |
| 健康检查 | [http://localhost:8080/health](http://localhost:8080/health) |

后端 API 不单独暴露端口，经 Nginx 反代访问（如 `/auth`、`/sources`、`/chat/stream` 等）。

## 架构说明

```
浏览器 :8080
    ↓
frontend (Nginx)
    ↓ 反代
backend :8897
    ↓
postgres-db (pgvector)
```

- 数据库连接串由 compose 注入：`DATABASE_URL=postgresql+asyncpg://...@postgres-db:5432/...`
- 本地 BGE 模型挂载：`${BGE_MODEL_PATH_HOST}` → 容器内 `/models/bge-m3`
- 上传文件持久化：`./backend/infrastructure/rag/temp/uploads`（容器内 `/app/backend/infrastructure/rag/temp/uploads`）

## 启动后验证

1. 打开 [http://localhost:8080](http://localhost:8080)，注册 / 登录
2. 入库一段文本或 Markdown 文件
3. 在对话中提问，确认 Agent 能检索并流式回复

## 常见问题

**构建 backend 失败（torch / 依赖）**

- 检查网络，Dockerfile 默认使用清华 / 阿里云 PyPI 镜像
- 可重试：`docker compose build --no-cache backend`

**入库或对话报 Embedding 错误**

- API 模式：检查 `backend/.env` 中 `SILICONFLOW_API_KEY`
- 本地模式：检查 `BGE_MODEL_PATH_HOST` 路径是否存在，且容器内 `BGE_MODEL_PATH=/models/bge-m3`

**PDF 入库失败**

- 检查 `backend/.env` 中 `MINERU_TOKEN` 是否有效
