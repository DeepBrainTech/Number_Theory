# Number Theory Agent

一个正确性优先的数论助手原型。当前版本使用 Next.js 前端、FastAPI 后端和 PostgreSQL/pgvector，并已导入 Richard Michael Hill 的 *Introduction to Number Theory* 第 1 章。

## 当前知识范围

- PDF：`1017984325-Introduction-to-Number-Theory-2026 (1).pdf`
- 范围：PDF 第 16～41 页，共 26 页
- 章节：Chapter 1, Euclid's Algorithm
- 小节：
  - 1.1 Some Examples of Rings
  - 1.2 Euclid's Algorithm
  - 1.3 Invertible Elements Modulo n
  - 1.4 Solving Linear Congruences
  - 1.5 The Chinese Remainder Theorem
  - 1.6 Prime Numbers

当前入库结果为 1 份文档、128 个结构化知识块。入库命令是幂等的，重复执行会替换该章已有数据，不会制造重复内容。

## 启动

需要 Docker Desktop。先复制环境变量模板，并把自己的 OpenAI API Key 填入本地 `.env`：

```powershell
Copy-Item .env.example .env
```

```dotenv
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5.6-sol
```

`.env` 已被 Git 忽略，不要把真实密钥写进 Dockerfile、源码或提交记录。未填写密钥时系统仍可启动，但聊天会退回 `retrieval_only`。

```powershell
docker compose up -d --build
```

服务地址：

- 前端：http://localhost:3000
- FastAPI：http://localhost:8000
- API 文档：http://localhost:8000/docs
- PostgreSQL：`localhost:5433`
- SageMath：http://localhost:8011/health
- Lean 4 + mathlib：http://localhost:8012/health

查看状态：

```powershell
docker compose ps
Invoke-RestMethod http://localhost:8000/api/library/stats
Invoke-RestMethod http://localhost:8000/api/tools/status
```

停止服务但保留数据库：

```powershell
docker compose down
```

`docker compose down -v` 会删除 PostgreSQL volume 和已入库数据，除非确实需要清空数据库，否则不要使用。

## 重新导入第一章

确保数据库和后端已经启动，然后运行：

```powershell
docker compose exec backend python -m app.ingest `
  --pdf "/data/pdf/1017984325-Introduction-to-Number-Theory-2026 (1).pdf" `
  --start-page 16 `
  --end-page 41
```

成功时应输出：

```text
Ingested document=hill-intro-nt-4499c3cfb4c9-ch1 chunks=128
```

## API

健康检查：

```text
GET /health
```

知识库统计：

```text
GET /api/library/stats
```

检索：

```http
POST /api/search
Content-Type: application/json

{
  "query": "如何使用欧几里得算法求最大公因数？",
  "limit": 5
}
```

聊天：

```http
POST /api/chat
Content-Type: application/json

{
  "message": "如何使用欧几里得算法求最大公因数？",
  "limit": 5
}
```

## 模型配置

后端使用 OpenAI Responses API 和函数调用，默认模型为 `gpt-5.6-sol`。模型可根据问题调用两个隔离服务：

- SageMath：`gcd`、扩展 gcd、因数分解、素性判定、模逆与中国剩余定理的精确运算。
- Lean 4 + mathlib：编译完整形式化证明，并拒绝 `sorry`、`admit`、新增公理和执行指令。

首次 Lean 检查需要加载完整 mathlib，在资源受限的 Docker Desktop 上可能耗时 30～60 秒；默认超时已相应设为 60 秒。

官方 OpenAI API 只需配置：

```dotenv
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5.6-sol
```

配置模型后重新创建服务：

```powershell
docker compose up -d --build
```

回答会标记为 `model_unverified`、`sage_verified` 或 `lean_verified`。后两者只说明相应计算或提交给 Lean 的形式命题已通过；自然语言题意到形式命题的翻译仍需审查，不能把标签理解为整段回答绝对正确。

可直接测试工具：

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/api/tools/sage `
  -ContentType application/json -Body '{"operation":"gcd","arguments":["391","299"],"split":null}'

$proof = @{ code = "import Mathlib`nexample : Nat.gcd 391 299 = 23 := by norm_num" } | ConvertTo-Json
Invoke-RestMethod -Method Post http://localhost:8000/api/tools/lean `
  -ContentType application/json -Body $proof
```

## 本地开发检查

后端：

```powershell
Set-Location backend
python -m unittest discover -s tests -v
```

前端：

```powershell
Set-Location frontend
pnpm install
pnpm lint
pnpm build
```

## 数据与正确性说明

- 页面范围和原始页码在后台保存，但前端默认不显示教材引用。
- 首版向量是零配置的可复现词法投影 `local-hash-v1`，并与 PostgreSQL 全文检索做融合；它不是高质量语义 embedding。
- 中英文基础数论术语通过受控词表扩展，因此首章的中文查询可以检索英文教材。
- Sage/Lean 显著提高可验证问题的可靠性，但并非所有数论研究问题都可自动形式化；工具失败或覆盖不到的结论必须保持未验证标记。
