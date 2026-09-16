param(
    [Parameter(Mandatory, Position=0)][string]$CommandName,
    [Parameter(ValueFromRemainingArguments=$true)][string[]]$TaskArguments,
    [Parameter(ValueFromPipeline=$true)][string]$Payload
)

begin {
    # Native hook stdin is UTF-8 even when Windows starts PowerShell in a legacy code page.
    [Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
    $OutputEncoding = [Text.UTF8Encoding]::new($false)
    $taskInput = [System.Collections.Generic.List[string]]::new()
    if (($CommandName -eq 'hook' -or $CommandName -eq 'record') -and [Console]::IsInputRedirected) {
        $nativePayload = [Console]::In.ReadToEnd()
        if (-not [string]::IsNullOrWhiteSpace($nativePayload)) { $taskInput.Add($nativePayload) }
    }
    $taskPython = (Get-Command python -ErrorAction Stop).Source
}
process {
    if ($null -ne $Payload) { $taskInput.Add($Payload) }
}
end {
    if ($CommandName -eq 'hook') {
        ($taskInput -join "`n") | & $taskPython -X utf8 -B (Join-Path $PSScriptRoot 'knowledge_hook.py')
    }
    elseif ($CommandName -eq 'record') {
        ($taskInput -join "`n") | & $taskPython -X utf8 -B (Join-Path $PSScriptRoot 'wiki.py') record
    }
    else {
        & $taskPython -X utf8 -B (Join-Path $PSScriptRoot 'wiki.py') $CommandName @TaskArguments
    }
    exit $LASTEXITCODE
}
