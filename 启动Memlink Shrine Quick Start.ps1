param()

$root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Resolve-PythonCommand {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python -and $python.Source) {
        return @($python.Source)
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py -and $py.Source) {
        return @($py.Source, "-3")
    }

    throw "Python interpreter was not found."
}

$pythonCommand = @(Resolve-PythonCommand)
$program = $pythonCommand[0]
$args = @()
if ($pythonCommand.Count -gt 1) {
    $args += $pythonCommand[1..($pythonCommand.Count - 1)]
}
$args += @("-m", "memlink_shrine.quick_start_app")

& $program @args
