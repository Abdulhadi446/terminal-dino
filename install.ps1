param(
    [switch]$Silent = $false
)

$ErrorActionPreference = "Stop"

function Info($m) { if (-not $Silent) { Write-Host ("install: $m") } }
function Fail($m) { Write-Host ("install: error: $m") -ForegroundColor Red; exit 1 }

# Resolve where this script lives
$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$SourcePy = Join-Path $ScriptDir "dino.py"

if (-not (Test-Path $SourcePy)) {
    # Try a download
    $tmp = Join-Path $env:TEMP "terminal-dino.py"
    try {
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri "https://raw.githubusercontent.com/Abdulhadi446/terminal-dino/main/dino.py" -OutFile $tmp -UseBasicParsing
    } catch { Fail "dino.py missing and download failed." }
    if (-not (Test-Path $tmp)) { Fail "download did not produce dino.py" }
    $SourcePy = $tmp
}

# Locate Python
$PythonExe = $null
foreach ($candidate in @("python", "py")) {
    try { $p = Get-Command $candidate -ErrorAction Stop; $PythonExe = $p.Source; break } catch { }
}
if (-not $PythonExe) { Fail "Python 3 is not installed. Install from python.org and reopen PowerShell." }

# Verify curses (Windows needs windows-curses)
$cursesOk = & $PythonExe -c "import sys,curses; sys.exit(0)" 2>$null
if ($LASTEXITCODE -ne 0) {
    Info "No curses found. On Windows try: $PythonExe -m pip install windows-curses"
    Info "Or use WSL (recommended) to get native curses."
}

$InstallDir = Join-Path $env:LOCALAPPDATA "terminal-dino"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item -Force $SourcePy (Join-Path $InstallDir "dino.py")

$Shim = Join-Path $InstallDir "dino.cmd"
$ShimContent = "@echo off`r`n`"$PythonExe`" `"%~dp0dino.py`" %*`r`n"
Set-Content -Path $Shim -Value $ShimContent -Encoding ascii

# Add to user PATH if missing
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$has = $false
foreach ($p in ($userPath -split ';')) { if ($p -ieq $InstallDir) { $has = $true; break } }
if (-not $has) {
    $newPath = "$InstallDir;$userPath"
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    Info "added $InstallDir to user PATH (open a new terminal)"
}

# Start Menu shortcut
try {
    $shell = New-Object -ComObject WScript.Shell
    $programs = [Environment]::GetFolderPath('StartMenu') + "\Programs"
    $scDir = $programs
    if (-not (Test-Path $scDir)) { New-Item -ItemType Directory -Force -Path $scDir | Out-Null }
    $lnk = $shell.CreateShortcut("$scDir\Terminal Dino.lnk")
    $lnk.TargetPath = $PythonExe
    $lnk.Arguments = "`"$InstallDir\dino.py`""
    $lnk.WorkingDirectory = $InstallDir
    $lnk.WindowStyle = 1
    $lnk.Description = "Chrome's offline dinosaur in your terminal"
    $lnk.Save()
} catch {
    Info "could not create Start Menu shortcut: $($_.Exception.Message)"
}

Info "Terminal Dino installed in $InstallDir"
Info "Run: dino   (new shell)  or  $PythonExe `"$InstallDir\dino.py`""
EOF
echo ready