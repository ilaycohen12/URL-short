# PowerShell entry point for setup-k8s.sh (same steps, same logic).
# Runs the .sh through Git Bash explicitly: a bare `bash` in PowerShell may
# resolve to WSL's bash.exe, which can't see Windows-installed kind/helm/kubectl.
$ErrorActionPreference = 'Stop'

$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) { throw "git not found on PATH - install Git for Windows (it provides Git Bash)." }

# git.exe lives in <Git>\cmd\ ; Git Bash lives in <Git>\bin\
$gitBash = Join-Path (Split-Path (Split-Path $git.Source)) 'bin\bash.exe'
if (-not (Test-Path $gitBash)) { throw "Git Bash not found at $gitBash" }

& $gitBash (Join-Path $PSScriptRoot 'setup-k8s.sh') @args
exit $LASTEXITCODE
