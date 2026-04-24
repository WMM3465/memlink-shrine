param(
    [Parameter(Mandatory = $true)]
    [string]$Query,
    [int]$Limit = 8
)

$ErrorActionPreference = "SilentlyContinue"

function Shorten {
    param([string]$Text, [int]$Length = 360)
    if (-not $Text) { return "" }
    $clean = ($Text -replace "\s+", " ").Trim()
    if ($clean.Length -le $Length) { return $clean }
    return $clean.Substring(0, $Length) + "..."
}

function Invoke-Json {
    param([string]$Url)
    try {
        $client = New-Object System.Net.WebClient
        $client.Encoding = [System.Text.Encoding]::UTF8
        $text = $client.DownloadString($Url)
        return $text | ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function Build-Queries {
    param([string]$Text)
    $queries = New-Object System.Collections.Generic.List[string]
    $queries.Add($Text)
    $queries.Add("Memlink Shrine")
    $queries.Add("memory library")
    $queries.Add("OpenMemory")
    $queries.Add("Codex")
    $queries.Add("")
    return @($queries | Where-Object { $_ -ne $null } | Select-Object -Unique)
}

Write-Host "=== Memlink Shrine cards ==="
$cardsById = @{}
$usedLibraryQuery = ""
foreach ($candidate in (Build-Queries $Query)) {
    if ($candidate -eq "") {
        $libraryUrl = "http://127.0.0.1:7861/api/cards?limit=$Limit"
    }
    else {
        $encoded = [System.Uri]::EscapeDataString($candidate)
        $libraryUrl = "http://127.0.0.1:7861/api/cards?query=$encoded&limit=$Limit"
    }
    $cards = Invoke-Json $libraryUrl
    foreach ($card in @($cards)) {
        if ($card -and $card.raw_memory_id -and -not $cardsById.ContainsKey($card.raw_memory_id)) {
            $cardsById[$card.raw_memory_id] = $card
            if (-not $usedLibraryQuery) { $usedLibraryQuery = if ($candidate -eq "") { "(recent cards fallback)" } else { $candidate } }
        }
    }
    if ($cardsById.Count -gt 0) { break }
}

$cards = @($cardsById.Values)
if (-not $cards -or $cards.Count -eq 0) {
    Write-Host "No Memlink Shrine cards found after fallback queries."
}
else {
    Write-Host "query_used: $usedLibraryQuery"
    $index = 0
    foreach ($card in $cards) {
        $index += 1
        Write-Host ""
        Write-Host "[$index] $($card.title)"
        Write-Host "raw_memory_id: $($card.raw_memory_id)"
        Write-Host "main_id: $($card.main_id)"
        Write-Host "summary: $(Shorten $card.fact_summary)"
        Write-Host "meaning: $(Shorten $card.meaning_summary 260)"
        if ($card.upstream_main_ids -or $card.downstream_main_ids) {
            Write-Host "upstream: $($card.upstream_main_ids -join ', ')"
            Write-Host "downstream: $($card.downstream_main_ids -join ', ')"
        }
    }
}

Write-Host ""
Write-Host "=== OpenMemory memories ==="
$memoriesById = @{}
$usedOpenMemoryQuery = ""
foreach ($candidate in (Build-Queries $Query)) {
    if ($candidate -eq "") {
        $openMemoryUrl = "http://127.0.0.1:8765/api/v1/memories/?user_id=administrator-main&size=$Limit&page=1"
    }
    else {
        $encoded = [System.Uri]::EscapeDataString($candidate)
        $openMemoryUrl = "http://127.0.0.1:8765/api/v1/memories/?user_id=administrator-main&search_query=$encoded&size=$Limit&page=1"
    }
    $memories = Invoke-Json $openMemoryUrl
    foreach ($memory in @($memories.items)) {
        if ($memory -and $memory.id -and -not $memoriesById.ContainsKey($memory.id)) {
            $memoriesById[$memory.id] = $memory
            if (-not $usedOpenMemoryQuery) { $usedOpenMemoryQuery = if ($candidate -eq "") { "(recent memories fallback)" } else { $candidate } }
        }
    }
    if ($memoriesById.Count -gt 0) { break }
}

$items = @($memoriesById.Values)
if (-not $items -or $items.Count -eq 0) {
    Write-Host "No OpenMemory memories found after fallback queries."
}
else {
    Write-Host "query_used: $usedOpenMemoryQuery"
    $index = 0
    foreach ($memory in $items) {
        $index += 1
        Write-Host ""
        Write-Host "[$index] id: $($memory.id)"
        Write-Host "app: $($memory.app_name)"
        Write-Host "content: $(Shorten $memory.content)"
    }
}

