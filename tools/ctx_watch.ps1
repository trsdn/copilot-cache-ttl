$dir = "C:\Users\torstenmahr\dev\cache_token\results"
$snap = Join-Path $dir "snapshots"
New-Item -ItemType Directory -Force -Path $snap | Out-Null
$last = ""
for ($i = 0; $i -lt 480; $i++) {
    $rc = Join-Path $dir "run_context.json"
    if (Test-Path $rc) {
        $mt = (Get-Item $rc).LastWriteTimeUtc.ToString("o")
        if ($mt -ne $last) {
            $last = $mt
            $stamp = (Get-Date).ToString("yyyyMMdd-HHmmss")
            Copy-Item $rc (Join-Path $snap "run_context-$stamp.json") -Force
            Copy-Item (Join-Path $dir "results.csv") (Join-Path $snap "results-$stamp.csv") -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Seconds 15
}
