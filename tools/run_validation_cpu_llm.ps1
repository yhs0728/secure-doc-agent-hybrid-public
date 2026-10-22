param(
    [string]$ListenAddress = '127.0.0.1',
    [ValidateRange(1024, 65535)][int]$Port = 11435,
    [string]$ModelsDirectory = (Join-Path $env:USERPROFILE '.ollama\models')
)
$ErrorActionPreference = 'Stop'
$null = [System.Net.IPAddress]::Parse($ListenAddress)
$ollamaExecutable = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
if (-not (Test-Path -LiteralPath $ollamaExecutable -PathType Leaf)) {
    throw 'Ollama executable is not installed in the standard user location.'
}
if (-not (Test-Path -LiteralPath $ModelsDirectory -PathType Container)) {
    throw 'ModelsDirectory must point to an existing Ollama model cache.'
}
$settings = @{
    OLLAMA_HOST = "${ListenAddress}:$Port"
    OLLAMA_MODELS = $ModelsDirectory
    CUDA_VISIBLE_DEVICES = '-1'
    ROCR_VISIBLE_DEVICES = '-1'
    GGML_VK_VISIBLE_DEVICES = '-1'
    OLLAMA_VULKAN = '0'
    OLLAMA_NUM_PARALLEL = '1'
    OLLAMA_MAX_LOADED_MODELS = '1'
    OLLAMA_CONTEXT_LENGTH = '2048'
    OLLAMA_NOPRUNE = '1'
    OLLAMA_NO_CLOUD = '1'
}
$previous = @{}
try {
    foreach ($key in $settings.Keys) {
        $previous[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
        [Environment]::SetEnvironmentVariable($key, $settings[$key], 'Process')
    }
    # Foreground server: Ctrl+C stops this helper. Existing Ollama stays separate.
    & $ollamaExecutable serve
    if ($LASTEXITCODE -ne 0) { throw "Validation Ollama exited with code $LASTEXITCODE" }
}
finally {
    foreach ($key in $previous.Keys) {
        [Environment]::SetEnvironmentVariable($key, $previous[$key], 'Process')
    }
}
