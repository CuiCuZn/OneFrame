param(
    [string]$Path = "D:\0Z\ai-pose-gallery-zh",
    [string]$Repo = "https://github.com/anhao/ai-pose-gallery-zh.git",
    [string]$BaseUrl = "http://127.0.0.1:8787"
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  OneFrame - import pose gallery" -ForegroundColor Cyan
Write-Host "  target: $Path"
Write-Host ""

try {
    Invoke-RestMethod "$BaseUrl/api/health" -TimeoutSec 3 | Out-Null
} catch {
    Write-Host "[x] OneFrame is not running at $BaseUrl. Start it first (start.bat)." -ForegroundColor Red
    exit 1
}

if (Test-Path (Join-Path $Path "data\pose-zh.json")) {
    Write-Host "[1/2] Using existing checkout."
} else {
    Write-Host "[1/2] Cloning ai-pose-gallery-zh (about 1.1 GB, first run only)..."
    if (Test-Path $Path) {
        Write-Host "[x] $Path exists but is not a pose gallery checkout. Remove it or pass -Path." -ForegroundColor Red
        exit 1
    }
    git clone --depth 1 $Repo $Path
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[x] git clone failed. Check network/proxy and retry." -ForegroundColor Red
        exit 1
    }
}

$settings = Invoke-RestMethod "$BaseUrl/api/settings"
$roots = [string]$settings.library_roots
if ($roots -notlike "*$Path*") {
    $newRoots = if ($roots.Trim()) { "$roots;$Path" } else { $Path }
    $body = @{ values = @{ library_roots = $newRoots } } | ConvertTo-Json -Depth 4
    Invoke-RestMethod "$BaseUrl/api/settings" -Method Put -Body $body -ContentType "application/json" | Out-Null
    Write-Host "      Added library root: $Path"
}

Write-Host "[2/2] Indexing metadata and thumbnails..."
$importBody = @{ mode = "pose_gallery"; path = $Path; kind = "other" } | ConvertTo-Json
$result = Invoke-RestMethod "$BaseUrl/api/library/import" -Method Post -Body $importBody -ContentType "application/json"
Write-Host ""
Write-Host "Done. scanned=$($result.scanned) added=$($result.added)" -ForegroundColor Green
Write-Host "Open $BaseUrl/#/library to browse."
