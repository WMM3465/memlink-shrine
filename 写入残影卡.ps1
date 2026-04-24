param(
    [string]$InputPath = "-",
    [string]$AuthorRole = "witness_model",
    [string]$Author = "codex"
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $env:MEMLINK_SHRINE_DB) {
    $env:MEMLINK_SHRINE_DB = Join-Path $root "data\memlink_shrine.db"
}
$env:PYTHONPATH = $root

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if (-not $py) {
        throw "Python interpreter was not found."
    }
    $program = $py.Source
    $prefixArgs = @("-3")
}
else {
    $program = $python.Source
    $prefixArgs = @()
}

$args = @()
$args += $prefixArgs
$args += @(
    "-m",
    "memlink_shrine.cli",
    "write-card",
    "--input",
    $InputPath,
    "--author-role",
    $AuthorRole,
    "--author",
    $Author
)

& $program @args


