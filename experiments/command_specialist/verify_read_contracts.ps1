param(
    [Parameter(Mandatory=$true)][string]$Cases,
    [Parameter(Mandatory=$true)][string]$Results
)
$ErrorActionPreference = 'Stop'
$items = Get-Content -LiteralPath $Cases -Raw -Encoding UTF8 | ConvertFrom-Json
$resultsList = [System.Collections.Generic.List[object]]::new()
foreach ($item in $items) {
    try {
        if ($item.op -eq 'read_head') {
            $observed = [string[]]@(Get-Content -LiteralPath $item.path -TotalCount $item.limit -Encoding UTF8)
        } elseif ($item.op -eq 'read_tail') {
            $observed = [string[]]@(Get-Content -LiteralPath $item.path -Tail $item.limit -Encoding UTF8)
        } else {
            throw 'Unsupported verifier operation'
        }
        $resultsList.Add(@{id=$item.id; lines=$observed; error=$null})
    } catch {
        $resultsList.Add(@{id=$item.id; lines=@(); error=$_.Exception.Message})
    }
}
$json = ConvertTo-Json -InputObject @($resultsList.ToArray()) -Compress -Depth 8
[System.IO.File]::WriteAllText($Results, $json, [System.Text.UTF8Encoding]::new($false))
