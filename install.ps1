# Setup only: venv, both requirement files, .env. No models, no committee logic, no secrets.
$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
Set-Location $repo

$MIN_MAJOR = 3
$MIN_MINOR = 11

function Find-Python {
    foreach ($candidate in @("py -3.11", "py -3", "python3", "python")) {
        $parts = $candidate.Split(" ")
        $exe = Get-Command $parts[0] -ErrorAction SilentlyContinue
        if (-not $exe) { continue }
        $args = @()
        if ($parts.Length -gt 1) { $args += $parts[1] }
        $args += @("-c", "import sys; print('%d %d' % sys.version_info[:2])")
        $out = & $parts[0] @args 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { continue }
        $nums = $out.Trim().Split(" ")
        $major = [int]$nums[0]
        $minor = [int]$nums[1]
        if ($major -gt $MIN_MAJOR -or ($major -eq $MIN_MAJOR -and $minor -ge $MIN_MINOR)) {
            return @{ Command = $parts[0]; Args = @(if ($parts.Length -gt 1) { $parts[1] }) ; Version = "$major.$minor" }
        }
    }
    return $null
}

$found = Find-Python
if (-not $found) {
    Write-Error "Python $MIN_MAJOR.$MIN_MINOR or newer is required and was not found on PATH. Install it from https://www.python.org/downloads/ and re-run this script."
    exit 1
}
Write-Host "Using Python $($found.Version)"

$venv = Join-Path $repo ".venv"
if (-not (Test-Path $venv)) {
    Write-Host "Creating .venv"
    & $found.Command @($found.Args + @("-m", "venv", $venv))
} else {
    Write-Host ".venv already exists; reusing it"
}

$py = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Error "The virtual environment is incomplete: $py is missing. Delete .venv and re-run."
    exit 1
}

Write-Host "Installing requirements.txt and requirements-inference.txt"
& $py -m pip install --upgrade pip
& $py -m pip install -r (Join-Path $repo "requirements.txt") -r (Join-Path $repo "requirements-inference.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Error "Dependency install failed (runtime or llama-cpp-python). See requirements.txt and requirements-inference.txt."
    exit 1
}

$envFile = Join-Path $repo ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $repo ".env.example") $envFile
    Write-Host "Created .env from .env.example"
} else {
    Write-Host ".env already exists; left untouched"
}

Write-Host ""
Write-Host "Edit .env before the first real run:"
Write-Host "  HF_TOKEN            Hugging Face *Read* token (needed for gated Llama/Gemma)"
Write-Host "  BACKUP_MODELS_DIR   where the small GGUF set lives, e.g. models"
Write-Host "  MODELS_DIR          the USB library, if you have one"
Write-Host "  ID10T_WORKSPACE     read root for source documents (default input)"
Write-Host "  ID10T_OUTPUTS       write root for results (default outputs)"
Write-Host "  GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / MS_CLIENT_ID   only for mail and calendar"
Write-Host ""
Write-Host "Models are not downloaded by this script. Accept the gated licenses on Hugging Face first"
Write-Host "(see README > Gated models), then run:"
Write-Host "  .\.venv\Scripts\python.exe downloader-scripts\download_models_local.py --path models"
Write-Host ""
Write-Host "Then run it:"
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "  python main.py --no-model `"hi`"     # no weights needed"
Write-Host "  python main.py `"hi`"                # loads the router GGUF"
