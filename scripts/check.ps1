param(
    [ValidateSet("Local", "Limits")]
    [string] $Mode = "Local",
    [ValidateSet("All", "Backend", "Frontend")]
    [string] $Scope = "All",
    [switch] $CheckOnly
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$config = Get-Content -LiteralPath (Join-Path $PSScriptRoot "validation.json") -Raw |
    ConvertFrom-Json -AsHashtable

function Invoke-Step {
    param([string] $Name, [scriptblock] $Command)
    Write-Host "`n==> $Name" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Name failed with exit code $LASTEXITCODE." }
}

function Get-BackendPython {
    foreach ($path in @("backend/.venv/Scripts/python.exe", "backend/.venv/bin/python")) {
        $candidate = Join-Path $repoRoot $path
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    throw "Backend virtual environment missing. Run 'uv sync --extra dev' in backend/."
}

function Test-CodeLimits([string] $SelectedScope) {
    $failures = [Collections.Generic.List[string]]::new()
    $roots = @()
    if ($SelectedScope -ne "Frontend") { $roots += $config.backendRoots }
    if ($SelectedScope -ne "Backend") { $roots += $config.frontendRoots }
    foreach ($root in $roots) {
        $absoluteRoot = Join-Path $repoRoot $root
        if (-not (Test-Path -LiteralPath $absoluteRoot)) { continue }
        foreach ($file in Get-ChildItem -LiteralPath $absoluteRoot -Recurse -File |
            Where-Object { $_.Extension -in ".py", ".ts", ".tsx", ".js", ".jsx" }) {
            $relativePath = [IO.Path]::GetRelativePath($repoRoot, $file.FullName).Replace("\", "/")
            $lineCount = [IO.File]::ReadAllLines($file.FullName).Length
            $allowed = if ($config.legacyLineBaselines.ContainsKey($relativePath)) {
                [int] $config.legacyLineBaselines[$relativePath]
            } else { [int] $config.maxLines }
            if ($lineCount -gt $allowed) { $failures.Add("$relativePath has $lineCount lines; allowed $allowed.") }
        }
    }

    if ($SelectedScope -ne "Frontend") {
        $python = Get-BackendPython
        Push-Location (Join-Path $repoRoot "backend")
        try {
            $radonOutput = & $python -m radon cc app -j
            if ($LASTEXITCODE -ne 0) { throw "Radon failed with exit code $LASTEXITCODE." }
        } finally { Pop-Location }
        $complexityByFile = $radonOutput | ConvertFrom-Json -AsHashtable
        foreach ($path in $complexityByFile.Keys) {
            foreach ($block in $complexityByFile[$path]) {
                $repositoryPath = "backend/$($path.Replace('\', '/'))"
                $key = "$repositoryPath::$($block.name)"
                $allowed = if ($config.legacyComplexityBaselines.ContainsKey($key)) {
                    [int] $config.legacyComplexityBaselines[$key]
                } else { [int] $config.maxPythonComplexity }
                if ([int] $block.complexity -gt $allowed) {
                    $failures.Add("$key has complexity $($block.complexity); allowed $allowed.")
                }
            }
        }
    }

    if ($failures.Count -gt 0) {
        $failures | ForEach-Object { Write-Host " - $_" -ForegroundColor Red }
        throw "LOC or complexity limits failed."
    }
    Write-Host "LOC and complexity limits passed." -ForegroundColor Green
}

function Invoke-StaticChecks([string] $SelectedScope) {
    $mode = if ($CheckOnly) { "check" } else { "fix" }
    $qualityScope = $SelectedScope.ToLowerInvariant()
    Invoke-Step "Shared quality gates" {
        Push-Location $repoRoot
        try { & node scripts/quality.mjs --mode $mode --scope $qualityScope }
        finally { Pop-Location }
    }
    Invoke-Step "LOC and complexity" { Test-CodeLimits $SelectedScope }
}

switch ($Mode) {
    "Limits" { Test-CodeLimits $Scope }
    "Local" { Invoke-StaticChecks $Scope }
}

Write-Host "`n$Mode validation passed." -ForegroundColor Green
