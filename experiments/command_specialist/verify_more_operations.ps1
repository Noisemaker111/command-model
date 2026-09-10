param(
    [Parameter(Mandatory=$true)][string]$Cases,
    [Parameter(Mandatory=$true)][string]$Results
)
$ErrorActionPreference = 'Stop'
$casesList = Get-Content -LiteralPath $Cases -Raw -Encoding UTF8 | ConvertFrom-Json
$observations = [System.Collections.Generic.List[object]]::new()
foreach ($caseRecord in $casesList) {
    try {
        switch ($caseRecord.op) {
            'find_literal' {
                $value = [string[]]@(Select-String -LiteralPath $caseRecord.path -Encoding UTF8 -SimpleMatch -Pattern $caseRecord.value |
                    Select-Object -First $caseRecord.limit -ExpandProperty Line)
            }
            'list_files' {
                $value = [string[]]@(Get-ChildItem -LiteralPath $caseRecord.path -File | Where-Object { $_.Name -like $caseRecord.value } |
                    Sort-Object Name | Select-Object -First $caseRecord.limit -ExpandProperty Name)
            }
            'json_field' {
                $document = Get-Content -LiteralPath $caseRecord.path -Raw -Encoding UTF8 | ConvertFrom-Json
                $value = $document.PSObject.Properties[$caseRecord.value].Value
            }
            default {throw 'Unsupported verifier operation'}
        }
        $observations.Add(@{id=$caseRecord.id; value=$value; error=$null})
    } catch {
        $observations.Add(@{id=$caseRecord.id; value=$null; error=$_.Exception.Message})
    }
}
$json = ConvertTo-Json -InputObject @($observations.ToArray()) -Depth 10 -Compress
[System.IO.File]::WriteAllText($Results, $json, [System.Text.UTF8Encoding]::new($false))
