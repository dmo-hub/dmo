param(
    [string]$Path = "",
    [int]$Count = 10,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$gbk = [System.Text.Encoding]::GetEncoding(936)

if (-not $Path) {
    # auto-detect: first .txt in this folder whose GBK-decoded content has version lines (vXX.XX)
    foreach ($f in (Get-ChildItem -Path $scriptDir -Filter *.txt -File)) {
        $t = $gbk.GetString([System.IO.File]::ReadAllBytes($f.FullName))
        if ($t -match "(?m)^v\d+\.\d+" -and $t -match "^/{10,}") { $Path = $f.FullName; break }
    }
}
if (-not $Path -or -not (Test-Path $Path)) {
    Write-Host "Changelog .txt not found. Usage: translate_latest10.bat [path-to-changelog.txt]"
    exit 1
}

$text = $gbk.GetString([System.IO.File]::ReadAllBytes($Path))

# blocks are delimited by ///////// separator lines
$blocks = @()
$cur = New-Object System.Collections.Generic.List[string]
foreach ($line in ($text -split "\r?\n")) {
    if ($line -match "^/{10,}") {
        if ($cur.Count -gt 0) { $blocks += ,($cur -join "`n"); $cur.Clear() }
    } else {
        $cur.Add($line)
    }
}
if ($cur.Count -gt 0) { $blocks += ,($cur -join "`n") }

# newest updates are at the top of the file
$verBlocks = @($blocks | Where-Object { $_ -match "(?m)^v\d+\.\d+" } | Select-Object -First $Count)
if ($verBlocks.Count -eq 0) { Write-Host "No version blocks found in $Path"; exit 1 }

$sep = "`n=============================`n"
$zh = ($verBlocks | ForEach-Object { $_.Trim() }) -join $sep
Write-Host ("Extracted {0} latest update blocks from: {1}" -f $verBlocks.Count, $Path)

if ($DryRun) { Write-Host $zh; exit 0 }

# resolve claude CLI: PATH -> native install -> newest VSCode extension bundle
$claude = $null
$cmd = Get-Command claude -ErrorAction SilentlyContinue
if ($cmd) { $claude = $cmd.Source }
if (-not $claude) {
    $candidates = @("$env:USERPROFILE\.local\bin\claude.exe") +
        @(Get-ChildItem "$env:USERPROFILE\.vscode\extensions\anthropic.claude-code-*\resources\native-binary\claude.exe" -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending | Select-Object -ExpandProperty FullName)
    $claude = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $claude) {
    Write-Host "claude CLI not found (PATH / .local\bin / VSCode extension). Install Claude Code CLI first."
    exit 1
}

# UTF-8 both directions: stdin pipe to claude + stdout capture
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$OutputEncoding = [System.Text.Encoding]::UTF8

$prompt = "Translate this Chinese game changelog to Thai. Keep version numbers, item numbering and ===== block separators exactly as-is. Output only the Thai translation, no commentary."
$result = $zh | & $claude -p $prompt
if ($LASTEXITCODE -ne 0 -or -not $result) {
    Write-Host "claude CLI failed (exit $LASTEXITCODE). Is Claude Code installed and logged in?"
    exit 1
}

$outFile = Join-Path $scriptDir "latest10_th.txt"
[System.IO.File]::WriteAllText($outFile, ($result -join "`n"), (New-Object System.Text.UTF8Encoding($true)))
Write-Host ""
Write-Host ($result -join "`n")
Write-Host ""
Write-Host "Saved: $outFile"
