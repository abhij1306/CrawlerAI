param(
    [ValidateSet("Affected", "Local", "Limits")]
    [string] $Mode = "Local",
    [ValidateSet("All", "Backend", "Frontend")]
    [string] $Scope = "All",
    [string] $BaseRef,
    [switch] $CheckOnly,
    [switch] $ListOnly
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$config = Get-Content -LiteralPath (Join-Path $PSScriptRoot "validation.json") -Raw |
    ConvertFrom-Json -AsHashtable
if (-not $BaseRef) { $BaseRef = $config.baseRef }

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

function Invoke-BackendPython {
    param([Parameter(ValueFromRemainingArguments = $true)] [string[]] $Arguments)
    $python = Get-BackendPython
    Push-Location (Join-Path $repoRoot "backend")
    try { & $python @Arguments } finally { Pop-Location }
}

function Invoke-FrontendVp {
    param([Parameter(ValueFromRemainingArguments = $true)] [string[]] $Arguments)
    if (-not (Get-Command vp -ErrorAction SilentlyContinue)) { throw "VitePlus ('vp') missing from PATH." }
    Push-Location (Join-Path $repoRoot "frontend")
    try { & vp @Arguments } finally { Pop-Location }
}

function Get-ChangedPaths {
    $paths = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    function Add-Paths([string[]] $Arguments) {
        $output = & git -C $repoRoot @Arguments 2>$null
        if ($LASTEXITCODE -eq 0) {
            foreach ($path in $output) {
                if ($path) { [void] $paths.Add($path.Replace("\", "/")) }
            }
        }
    }
    & git -C $repoRoot rev-parse --verify --quiet $BaseRef *> $null
    if ($LASTEXITCODE -ne 0) { throw "Base ref '$BaseRef' cannot be resolved." }
    Add-Paths @("diff", "--name-only", "--diff-filter=ACMR", "$BaseRef...HEAD")
    Add-Paths @("diff", "--name-only", "--diff-filter=ACMR")
    Add-Paths @("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    Add-Paths @("ls-files", "--others", "--exclude-standard")
    return @($paths | Sort-Object)
}

function Resolve-TestPatterns([string] $Root, [string[]] $Patterns, [string[]] $Extensions) {
    $files = Get-ChildItem -LiteralPath $Root -Recurse -File |
        Where-Object { $_.Extension -in $Extensions } |
        ForEach-Object { [IO.Path]::GetRelativePath($Root, $_.FullName).Replace("\", "/") }
    $selected = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($pattern in $Patterns) {
        foreach ($file in $files) {
            if ($file -like $pattern) { [void] $selected.Add($file) }
        }
    }
    return @($selected | Sort-Object)
}

function Invoke-AffectedTests {
    $changedPaths = @(Get-ChangedPaths)
    if ($changedPaths.Count -eq 0) {
        Write-Host "No changed paths. No affected tests selected." -ForegroundColor Green
        return
    }

    Write-Host "Changed paths:" -ForegroundColor Cyan
    $changedPaths | ForEach-Object { Write-Host " - $_" }
    $backendPatterns = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $frontendPatterns = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $e2ePatterns = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $backendChanged = $false
    $frontendChanged = $false
    $globalTriggered = $false

    foreach ($path in $changedPaths) {
        if ($path -like "backend/app/*.py" -or $path -like "backend/app/**/*.py") { $backendChanged = $true }
        if ($path -like "frontend/app/**" -or $path -like "frontend/components/**" -or
            $path -like "frontend/lib/**" -or $path -like "frontend/src/**") { $frontendChanged = $true }
        if ($path -like "backend/tests/test_*.py" -or $path -like "backend/tests/**/test_*.py") {
            [void] $backendPatterns.Add($path.Substring("backend/".Length))
        }
        if ($path -like "frontend/*.test.*" -or $path -like "frontend/**/*.test.*" -or
            $path -like "frontend/*.spec.*" -or $path -like "frontend/**/*.spec.*") {
            [void] $frontendPatterns.Add($path.Substring("frontend/".Length))
        }
        foreach ($trigger in $config.globalTriggers) {
            if ($path -like $trigger) { $globalTriggered = $true }
        }
    }

    if ($globalTriggered) {
        $config.backendGlobalTests | ForEach-Object { [void] $backendPatterns.Add($_) }
        $config.frontendGlobalTests | ForEach-Object { [void] $frontendPatterns.Add($_) }
    }
    else {
        foreach ($rule in $config.rules) {
            $ruleMatched = $false
            foreach ($sourcePattern in $rule.sources) {
                if ($changedPaths | Where-Object { $_ -like $sourcePattern }) { $ruleMatched = $true; break }
            }
            if (-not $ruleMatched) { continue }
            if ($rule.backendTests) { $rule.backendTests | ForEach-Object { [void] $backendPatterns.Add($_) } }
            if ($rule.frontendTests) { $rule.frontendTests | ForEach-Object { [void] $frontendPatterns.Add($_) } }
            if ($rule.frontendE2E) { $rule.frontendE2E | ForEach-Object { [void] $e2ePatterns.Add($_) } }
        }
    }

    if ($backendChanged -and $backendPatterns.Count -eq 0) {
        $config.backendFallbackTests | ForEach-Object { [void] $backendPatterns.Add($_) }
    }
    if ($frontendChanged -and $frontendPatterns.Count -eq 0) {
        $config.frontendFallbackTests | ForEach-Object { [void] $frontendPatterns.Add($_) }
    }

    $backendTests = @(Resolve-TestPatterns (Join-Path $repoRoot "backend") @($backendPatterns) @(".py"))
    $frontendTests = @(Resolve-TestPatterns (Join-Path $repoRoot "frontend") @($frontendPatterns) @(".ts", ".tsx", ".js", ".jsx"))
    $frontendE2E = @(Resolve-TestPatterns (Join-Path $repoRoot "frontend") @($e2ePatterns) @(".ts", ".tsx", ".js", ".jsx"))

    Write-Host "`nSelected affected tests:" -ForegroundColor Cyan
    $backendTests | ForEach-Object { Write-Host " - backend/$_" }
    $frontendTests | ForEach-Object { Write-Host " - frontend/$_" }
    $frontendE2E | ForEach-Object { Write-Host " - frontend/$_ (E2E)" }
    if ($backendTests.Count + $frontendTests.Count + $frontendE2E.Count -eq 0) { Write-Host " - none (non-code change)" }
    if ($ListOnly) { return }

    if ($backendTests.Count -gt 0) {
        Invoke-Step "Affected backend tests" { Invoke-BackendPython -m pytest @backendTests -q }
    }
    if ($frontendTests.Count -gt 0) {
        Invoke-Step "Affected frontend tests" { Invoke-FrontendVp test @frontendTests }
    }
    if ($frontendE2E.Count -gt 0) {
        Invoke-Step "Mapped frontend E2E" { Invoke-FrontendVp exec playwright test --config playwright.config.ts @frontendE2E }
    }
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
    if ($SelectedScope -ne "Frontend") {
        if ($CheckOnly) {
            Invoke-Step "Ruff lint" { Invoke-BackendPython -m ruff check . }
            Invoke-Step "Ruff format" { Invoke-BackendPython -m ruff format --check . }
        } else {
            Invoke-Step "Ruff lint fixes" { Invoke-BackendPython -m ruff check . --fix }
            Invoke-Step "Ruff format fixes" { Invoke-BackendPython -m ruff format . }
        }
        Invoke-Step "Mypy" { Invoke-BackendPython -m mypy app }
    }
    if ($SelectedScope -ne "Backend") {
        if ($CheckOnly) {
            Invoke-Step "Frontend format, lint, and types" { Invoke-FrontendVp check }
        } else {
            Invoke-Step "Frontend format, lint, and types with fixes" { Invoke-FrontendVp check --fix }
        }
    }
    Invoke-Step "LOC and complexity" { Test-CodeLimits $SelectedScope }
}

switch ($Mode) {
    "Affected" { Invoke-AffectedTests }
    "Limits" { Test-CodeLimits $Scope }
    "Local" {
        Invoke-StaticChecks $Scope
        Invoke-AffectedTests
    }
}

Write-Host "`n$Mode validation passed." -ForegroundColor Green
