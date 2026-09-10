param(
    [Parameter(Mandatory=$true)][string]$Repository,
    [string]$Destination = "$env:USERPROFILE/.local/bin"
)
$ErrorActionPreference = 'Stop'
$repositoryPath = (Resolve-Path -LiteralPath $Repository).Path
$helperDirectory = "$env:USERPROFILE/.local/share/shell-forensics"
New-Item -ItemType Directory -Force -Path $helperDirectory, $Destination | Out-Null
$helper = Join-Path $helperDirectory 'workspace.py'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'workspace.py') -Destination $helper
$wrapper = @'
param([Parameter(ValueFromRemainingArguments=$true)][string[]]$CommandArgs)
$ErrorActionPreference = 'Stop'
$pythonScript = '__HELPER__'
$repository = '__REPOSITORY__'
if ($CommandArgs.Count -gt 0 -and $CommandArgs[0] -eq 'codex') {
    $result = & python $pythonScript --repo $repository new --json
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $workspace = $result | ConvertFrom-Json
    $launchArgs = @('-C', $workspace.path) + @($CommandArgs | Select-Object -Skip 1)
    & codex @launchArgs
    exit $LASTEXITCODE
}
& python $pythonScript --repo $repository @CommandArgs
exit $LASTEXITCODE
'@
$wrapper = $wrapper.Replace('__HELPER__', $helper.Replace("'", "''")).Replace('__REPOSITORY__', $repositoryPath.Replace("'", "''"))
Set-Content -LiteralPath (Join-Path $Destination 'sf.ps1') -Value $wrapper -Encoding utf8
Write-Output "Installed sf in $Destination. This directory must be on PATH."
