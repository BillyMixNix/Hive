param(
    [string]$Save = "saves\hive-world.json",
    [int]$NpcLimit = 0,
    [ValidateSet("local", "all")]
    [string]$NpcScope = "local",
    [string]$Model = "qwen2.5:3b",
    [switch]$New,
    [switch]$LlmNarration
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo ".venv\Scripts\python.exe"
$pythonFallback = "D:\Codex\AI\text-generation-webui-main\installer_files\env\python.exe"
$pythonWorks = $false
$venvConfig = Join-Path $repo ".venv\pyvenv.cfg"
if (
    (Test-Path -LiteralPath $python) -and
    (Test-Path -LiteralPath $venvConfig)
) {
    $baseExecutable = (
        Get-Content -LiteralPath $venvConfig |
        Where-Object { $_ -match "^executable\s*=" } |
        Select-Object -First 1
    ) -replace "^executable\s*=\s*", ""
    $pythonWorks = (
        $baseExecutable -and
        (Test-Path -LiteralPath $baseExecutable)
    )
}
if (-not $pythonWorks) {
    if (-not (Test-Path -LiteralPath $pythonFallback)) {
        throw (
            "The project virtual environment is broken and no fallback Python " +
            "was found. Reinstall Python, then recreate .venv."
        )
    }
    $python = $pythonFallback
    Write-Host "[System] Project .venv is broken; using fallback Python at $python"
}
$server = $env:LLAMA_SERVER_EXE
if (-not $server) {
    $server = "D:\Codex\AI\text-generation-webui-main\installer_files\env\Lib\site-packages\llama_cpp_binaries\bin\llama-server.exe"
}
if (-not (Test-Path -LiteralPath $server)) {
    throw "llama-server.exe was not found. Set LLAMA_SERVER_EXE to its full path."
}

$modelParts = $Model.Split(":", 2)
$modelName = $modelParts[0]
$modelTag = if ($modelParts.Length -gt 1) { $modelParts[1] } else { "latest" }
$manifest = Join-Path $env:USERPROFILE (
    ".ollama\models\manifests\registry.ollama.ai\library\" +
    $modelName + "\" + $modelTag
)
if (-not (Test-Path -LiteralPath $manifest)) {
    throw "The $Model Ollama manifest was not found at $manifest."
}
$modelDigest = (
    Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
).layers | Where-Object {
    $_.mediaType -eq "application/vnd.ollama.image.model"
} | Select-Object -First 1 -ExpandProperty digest
$model = Join-Path $env:USERPROFILE (
    ".ollama\models\blobs\" + $modelDigest.Replace(":", "-")
)
if (-not (Test-Path -LiteralPath $model)) {
    throw "The model blob was not found at $model."
}

$psi = [System.Diagnostics.ProcessStartInfo]::new()
$psi.FileName = $server
$psi.Arguments = "-m `"$model`" --host 127.0.0.1 --port 11435 -c 4096 -ngl 99"
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$process = [System.Diagnostics.Process]::Start($psi)

try {
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:11435/health" -TimeoutSec 2
            if ($health.status -eq "ok") {
                $ready = $true
                break
            }
        } catch {
        }
    }
    if (-not $ready) {
        throw "The local model server did not become ready."
    }

    $arguments = @(
        "-m", "twin_realms",
        "--tier", "3",
        "--mode", "hive_learning",
        "--npc-scope", $NpcScope,
        "--npc-limit", "$NpcLimit",
        "--hive-url", "http://127.0.0.1:11435/v1/chat/completions",
        "--hive-model", $Model,
        "--save", $Save
    )
    if ($New) {
        $arguments += "--new"
    }
    if ($LlmNarration) {
        $arguments += "--llm"
    }
    & $python @arguments
} finally {
    if ($process -and -not $process.HasExited) {
        $process.Kill()
        $process.WaitForExit()
    }
}
