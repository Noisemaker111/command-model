param()

$ErrorActionPreference = 'Stop'
while (($line = [Console]::In.ReadLine()) -ne $null) {
    if ([string]::IsNullOrWhiteSpace($line)) { continue }
    $request = $null
    try {
        $request = $line | ConvertFrom-Json
        $tokens = $null
        $parseErrors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseInput(
            [string]$request.command, [ref]$tokens, [ref]$parseErrors
        )
        $nodes = @()
        foreach ($commandAst in $ast.FindAll(
            { param($node) $node -is [System.Management.Automation.Language.CommandAst] }, $true
        )) {
            $name = $commandAst.GetCommandName()
            $nodes += [ordered]@{
                kind = 'command'
                name = $name
                dynamic = ($null -eq $name)
                elements = @($commandAst.CommandElements | ForEach-Object { $_.Extent.Text })
                evidence = $commandAst.Extent.Text
                start = $commandAst.Extent.StartOffset
            }
        }
        $response = [ordered]@{
            id = $request.id
            ok = ($parseErrors.Count -eq 0)
            errors = @($parseErrors | ForEach-Object { $_.Message })
            nodes = @($nodes | Sort-Object start)
        }
    }
    catch {
        $response = [ordered]@{
            id = if ($null -ne $request) { $request.id } else { $null }
            ok = $false
            errors = @($_.Exception.Message)
            nodes = @()
        }
    }
    [Console]::Out.WriteLine(($response | ConvertTo-Json -Compress -Depth 8))
    [Console]::Out.Flush()
}
