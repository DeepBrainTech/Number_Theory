# Proof Lab

A correctness-first math proving workbench: Next.js frontend, FastAPI backend, PostgreSQL, plus isolated SageMath / Lean 4 services. Chat and Auto Prove use the model with web search, literature tools (arXiv / Crossref / Semantic Scholar / OEIS), Sage, and optional Lean formalization.

Production site: https://proof-lab.deepbrainacademy.org

## Start

Docker Desktop required. Copy the env template and put your OpenAI API key in local `.env`:

```powershell
Copy-Item .env.example .env
```

```dotenv
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5.6-sol
```

`.env` is gitignored. Do not commit real secrets. Without a key the stack still starts, but chat cannot answer.

```powershell
docker compose up -d --build
```

Local URLs:

- Frontend: http://localhost:3000
- FastAPI: http://localhost:8000
- API docs: http://localhost:8000/docs
- PostgreSQL: `localhost:5433`
- SageMath: http://localhost:8011/health
- Lean 4 + mathlib: http://localhost:8012/health

Status:

```powershell
docker compose ps
Invoke-RestMethod http://localhost:8000/api/tools/status
```

Stop while keeping the database (chats, memories, notebook):

```powershell
docker compose down
```

`docker compose down -v` deletes the PostgreSQL volume — only use that when you really want a wipe.

## Production notes

For https://proof-lab.deepbrainacademy.org set:

```dotenv
CORS_ORIGINS=https://proof-lab.deepbrainacademy.org,http://localhost:3000
COOKIE_SECURE=1
COOKIE_SAMESITE=none
GOOGLE_CLIENT_ID=...
NEXT_PUBLIC_GOOGLE_CLIENT_ID=...
```

Set these on the **backend** service. `COOKIE_SAMESITE=none` is required when the
frontend origin differs from the API host (cross-site cookies); browsers also
require `COOKIE_SECURE=1` in that mode.

In Google Cloud Console, add authorized JavaScript origins:

- `https://proof-lab.deepbrainacademy.org`
- `http://localhost:3000` (local dev)

## API

Health:

```text
GET /health
```

Chat:

```http
POST /api/chat
Content-Type: application/json

{
  "message": "Prove that there are infinitely many primes."
}
```

## Model config

Backend uses the OpenAI Responses API with function calling. Default model: `gpt-5.6-sol`. The model can call:

- SageMath: gcd, factorization, primality, modular inverse, CRT, and related exact ops
- Lean 4 + mathlib: compile formal proofs; rejects `sorry`, `admit`, new axioms, and exec
- Literature tools: arXiv, Crossref, Semantic Scholar, OEIS
- OpenAI `web_search` for public web pages

First Lean checks load full mathlib and may take 30–60s on constrained Docker Desktop; timeouts are set accordingly.

Rebuild after changing model config:

```powershell
docker compose up -d --build
```

Answers carry correctness levels `V0`–`V4` (legacy fields `model_unverified` / `sage_verified` / `lean_verified` remain). `V2`/`V4` only mean the corresponding Sage check or Lean statement passed alignment — not that the whole natural-language writeup is certified.

Tool smoke tests:

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/api/tools/sage `
  -ContentType application/json -Body '{"operation":"gcd","arguments":["391","299"],"split":null}'

$proof = @{ code = "import Mathlib`nexample : Nat.gcd 391 299 = 23 := by norm_num" } | ConvertTo-Json
Invoke-RestMethod -Method Post http://localhost:8000/api/tools/lean `
  -ContentType application/json -Body $proof
```

## Local checks

Backend:

```powershell
Set-Location backend
python -m unittest discover -s tests -v
```

Frontend:

```powershell
Set-Location frontend
pnpm install
pnpm lint
pnpm build
```

## Correctness

V0–V4 gating applies. Sage/Lean success does not verify every natural-language step; Lean also needs statement alignment with the user’s question.
