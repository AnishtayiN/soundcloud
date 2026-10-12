param(
    [Parameter(Mandatory=$true)][string]$Exe,
    [Parameter(Mandatory=$true)][string]$Report
)
$ErrorActionPreference = 'Stop'
$Exe = (Resolve-Path $Exe).Path
$Report = [IO.Path]::GetFullPath($Report)
$clean = Join-Path $env:RUNNER_TEMP ('SoundCloud X clean user آزمون ' + [guid]::NewGuid())
New-Item -ItemType Directory -Force $clean | Out-Null
$names = @('PATH','PYTHONHOME','PYTHONPATH','TCL_LIBRARY','TK_LIBRARY','APPDATA','LOCALAPPDATA')
$saved = @{}
foreach ($name in $names) { $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
try {
    # No build Python, pip, ffmpeg, Tcl or application folder in PATH.
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    foreach ($name in @('PYTHONHOME','PYTHONPATH','TCL_LIBRARY','TK_LIBRARY')) {
        [Environment]::SetEnvironmentVariable($name, $null, 'Process')
    }
    $env:APPDATA = Join-Path $clean 'Roaming'
    $env:LOCALAPPDATA = Join-Path $clean 'Local'
    Write-Host 'Launching the actual EXE with no Python/Tcl on PATH, from an empty Unicode directory.'
    $process = Start-Process -FilePath $Exe -ArgumentList @('--self-test', '--report', ('"' + $Report + '"')) -WorkingDirectory $clean -PassThru
    if (-not $process.WaitForExit(150000)) {
        $process.Kill()
        throw 'Packaged EXE did not finish its startup/UI/audio checks within 150 seconds'
    }
    $process.Refresh()
    if (-not (Test-Path $Report)) { throw "EXE produced no report (exit=$($process.ExitCode))" }
    $result = Get-Content -Raw -Encoding UTF8 $Report | ConvertFrom-Json
    Write-Host $result.output
    if ($process.ExitCode -ne 0 -or -not $result.ok -or -not $result.frozen -or -not $result.checks.embedded_python_dll) {
        Write-Host $result.error
        throw 'The distributed EXE is not self-contained or did not pass its real runtime checks'
    }
    # Also exercise ordinary double-click startup, not just diagnostic mode.
    $normal = Start-Process -FilePath $Exe -WorkingDirectory $clean -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    do {
        Start-Sleep -Milliseconds 200
        $normal.Refresh()
        if ($normal.HasExited) { throw "Normal startup exited unexpectedly ($($normal.ExitCode))" }
    } while ($normal.MainWindowHandle -eq 0 -and [DateTime]::UtcNow -lt $deadline)
    if ($normal.MainWindowHandle -eq 0) { $normal.Kill(); throw 'Normal startup created no window' }
    if (-not $normal.CloseMainWindow()) { $normal.Kill(); throw 'App window did not accept Close' }
    if (-not $normal.WaitForExit(60000)) { $normal.Kill(); throw 'Application did not shut down cleanly' }
    $normal.Refresh()
    if ($normal.ExitCode -ne 0) { throw "Normal window exited with $($normal.ExitCode)" }
    $result | Add-Member -NotePropertyName normal_startup_and_close -NotePropertyValue $true
    $result | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 $Report
    Write-Host 'PASS: embedded runtime, actual themed window, images, audio, normal launch and shutdown.'
} finally {
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
    Remove-Item -Recurse -Force $clean -ErrorAction SilentlyContinue
}
