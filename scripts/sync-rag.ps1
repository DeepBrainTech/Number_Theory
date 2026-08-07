param(
    [ValidateSet("prod", "dev")]
    [string]$Mode = "dev",
    [string]$Book = ""
)

$ErrorActionPreference = "Stop"
$composeFile = if ($Mode -eq "dev") { "docker-compose.dev.yml" } else { "docker-compose.yml" }

Write-Host "== RAG sync ($Mode) ==" -ForegroundColor Cyan

try {
    $before = Invoke-RestMethod http://localhost:8000/api/library/stats
    Write-Host ("Before: documents={0} chunks={1}" -f $before.documents, $before.chunks)
} catch {
    Write-Warning "Backend not reachable yet; ingest will still run against Postgres."
}

if ($Book) {
    docker compose -f $composeFile run --rm ingest python -m app.ingest --book $Book
} else {
    docker compose -f $composeFile --profile ingest run --rm ingest
}

try {
    $after = Invoke-RestMethod http://localhost:8000/api/library/stats
    Write-Host (
        "After: documents={0} chunks={1} pages={2}-{3}" -f
        $after.documents, $after.chunks, $after.page_start, $after.page_end
    ) -ForegroundColor Green
} catch {
    Write-Host "Ingest finished. Start backend and check GET /api/library/stats" -ForegroundColor Yellow
}
