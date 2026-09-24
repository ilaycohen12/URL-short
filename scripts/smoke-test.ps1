# PowerShell entry point for smoke-test.sh (same steps, same logic).
# Runs the .sh through Git Bash explicitly: a bare `bash` in PowerShell may
# resolve to WSL's bash.exe, which can't see Windows-installed kind/helm/kubectl.
$ErrorActionPreference = 'Stop'

$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) { throw "git not found on PATH - install Git for Windows (it provides Git Bash)." }

# git.exe lives in <Git>\cmd\ ; Git Bash lives in <Git>\bin\
$gitBash = Join-Path (Split-Path (Split-Path $git.Source)) 'bin\bash.exe'
if (-not (Test-Path $gitBash)) { throw "Git Bash not found at $gitBash" }

# Tools like docker write normal progress to stderr; with 'Stop' in effect, PowerShell 5.1
# would turn that into a fatal error if the caller redirects it (2>&1). The exit code below
# is what signals real failure.
$ErrorActionPreference = 'Continue'
& $gitBash (Join-Path $PSScriptRoot 'smoke-test.sh') @args
exit $LASTEXITCODE
