param(
    [Parameter(Mandatory=$true)][string]$Cases,
    [Parameter(Mandatory=$true)][string]$Results
)
$ErrorActionPreference = 'Stop'

function Get-StaticAstValue($Node) {
    if ($Node -is [System.Management.Automation.Language.StringConstantExpressionAst]) {
        return @{known=$true; value=[string]$Node.Value}
    }
    if ($Node -is [System.Management.Automation.Language.ExpandableStringExpressionAst] -and $Node.NestedExpressions.Count -eq 0) {
        return @{known=$true; value=[string]$Node.Value}
    }
    if ($Node -is [System.Management.Automation.Language.ConstantExpressionAst]) {
        return @{known=$true; value=$Node.Value}
    }
    return @{known=$false; value=$null}
}

function Get-ReadCandidate($Command) {
    $parameters = @{}
    $positionals = [System.Collections.Generic.List[object]]::new()
    $elements = $Command.CommandElements
    for ($index=1; $index -lt $elements.Count; $index++) {
        $element = $elements[$index]
        if ($element -is [System.Management.Automation.Language.CommandParameterAst]) {
            $key = $element.ParameterName.ToLowerInvariant()
            if ($key -notin @('literalpath','path','head','totalcount','tail','encoding')) {
                return @{status='unsupported_parameter'}
            }
            if ($key -eq 'head') {$key='totalcount'}
            if ($parameters.ContainsKey($key)) {return @{status='duplicate_parameter'}}
            $valueNode = $element.Argument
            if ($null -eq $valueNode) {
                $index++
                if ($index -ge $elements.Count) {return @{status='missing_parameter_value'}}
                $valueNode = $elements[$index]
            }
            $value = Get-StaticAstValue $valueNode
            if (-not $value.known) {return @{status='dynamic_parameter'}}
            $parameters[$key] = $value.value
        } else {
            $value = Get-StaticAstValue $element
            if (-not $value.known) {return @{status='dynamic_positional'}}
            $positionals.Add($value.value)
        }
    }
    if ($parameters.ContainsKey('literalpath') -and $parameters.ContainsKey('path')) {
        return @{status='conflicting_path_parameters'}
    }
    $literalPath = $parameters.ContainsKey('literalpath')
    $pathKey = if ($literalPath) {'literalpath'} else {'path'}
    if ($parameters.ContainsKey($pathKey)) {
        if ($positionals.Count) {return @{status='extra_positional'}}
        $pathValue = $parameters[$pathKey]
    } elseif ($positionals.Count -eq 1) {
        $pathValue = $positionals[0]
    } else {
        return @{status='missing_or_multiple_paths'}
    }
    if ($pathValue -isnot [string] -or [string]::IsNullOrEmpty($pathValue)) {return @{status='invalid_path'}}
    if (-not $literalPath -and $pathValue.IndexOfAny([char[]]'*?[]') -ge 0) {return @{status='wildcard_path'}}
    if ($parameters.ContainsKey('tail') -eq $parameters.ContainsKey('totalcount')) {return @{status='missing_or_conflicting_count'}}
    $mode = if ($parameters.ContainsKey('tail')) {'tail'} else {'totalcount'}
    $countValue = $parameters[$mode]
    if ($countValue -isnot [int] -or $countValue -lt 1 -or $countValue -gt 100) {return @{status='unsupported_count'}}
    if ($parameters.ContainsKey('encoding') -and $parameters.encoding -notin @('utf8','utf8bom','utf8nobom')) {return @{status='unsupported_encoding'}}
    $contexts = [System.Collections.Generic.List[string]]::new()
    $ancestor = $Command.Parent
    while ($null -ne $ancestor) {
        $name = $ancestor.GetType().Name
        if ($name -match 'Function|IfStatement|For|While|Switch|TryStatement|ScriptBlockExpression') {$contexts.Add($name)}
        $ancestor = $ancestor.Parent
    }
    return @{
        status='read_candidate'
        plan=@{op=$(if ($mode -eq 'tail') {'read_tail'} else {'read_head'}); path='fixture.txt'; value=''; limit=$countValue}
        original_path=[string]$pathValue
        literal_path=$literalPath
        encoding=$(if ($parameters.ContainsKey('encoding')) {[string]$parameters.encoding} else {'unspecified'})
        control_context=[string[]]$contexts.ToArray()
        execution_observed=$false
    }
}

$reader = [System.IO.StreamReader]::new($Cases, [System.Text.Encoding]::UTF8)
$writer = [System.IO.StreamWriter]::new($Results, $false, [System.Text.UTF8Encoding]::new($false))
try {
    while ($null -ne ($line = $reader.ReadLine())) {
        $caseRecord = $line | ConvertFrom-Json
        $tokens = $null
        $parseErrors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseInput([string]$caseRecord.command, [ref]$tokens, [ref]$parseErrors)
        $candidates = [System.Collections.Generic.List[object]]::new()
        if ($parseErrors.Count -eq 0) {
            foreach ($commandNode in $ast.FindAll({param($node) $node -is [System.Management.Automation.Language.CommandAst]}, $true)) {
                if ($commandNode.GetCommandName() -ne 'Get-Content') {continue}
                $candidate = Get-ReadCandidate $commandNode
                $candidate.span = @{start=$commandNode.Extent.StartOffset; end=$commandNode.Extent.EndOffset}
                $candidates.Add($candidate)
            }
        }
        $result = @{id=$caseRecord.id; status=$(if ($parseErrors.Count) {'parse_error'} else {'parsed'});
            candidates=@($candidates.ToArray()); error_count=$parseErrors.Count;
            span_units='UTF-16 offsets in original command'; parser_version=[string]$PSVersionTable.PSVersion}
        $writer.WriteLine((ConvertTo-Json -InputObject $result -Depth 8 -Compress))
    }
} finally {
    $reader.Dispose()
    $writer.Dispose()
}
