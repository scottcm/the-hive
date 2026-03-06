param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

$python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Local virtualenv python not found at $python"
}

$defaultArgs = @("-m", "pytest", "-p", "no:cacheprovider")
$allArgs = $defaultArgs + $PytestArgs

& $python @allArgs
exit $LASTEXITCODE
