<#
deploy.ps1 - Sends the tool from this PC to the client's server (v0.29.0)
=========================================================================

WHAT THIS DOES
--------------
Run it on Brinda's PC, in PowerShell, from the project folder:

    powershell -ExecutionPolicy Bypass -File deploy\deploy.ps1

It does the first install and every later update - the same command:

  1. builds the screens (web\frontend, "npm run build"). The server has no
     Node.js, and does not need it: the screens go there already built.
  2. packs the code EXACTLY AS COMMITTED in Git (the last commit), so what
     runs on the server is always a version that is in version control.
     Changes you have not committed are NOT sent - it tells you if any.
  3. copies the two packs to the server and runs deploy/install.sh there,
     which installs / updates and checks that the tool answers.

No client data leaves this PC: /data, invoices and reports are not in Git
and so are not in the pack. The server's own data is never overwritten.

OTHER USES
    -Status
        Is the tool running, which version, disk space, backups.

    -Backup
        Makes a fresh backup on the server and fetches it to
        data\server-backups\ on this PC (database + payment proofs).
        Do this from time to time: the nightly backups stay on the server.

    -Database desktop            (or  -Database "D:\copy\drivenstyle.db")
        Copies a desktop tool's database into the web tool, once.
        "desktop" = this PC's own desktop tool. Add -Replace if the web
        tool already has masters (its present database is kept as a
        backup file first; its users are kept).

SETTINGS
    -Server  ubuntu@35.154.161.180        the server's sign-in
    -Key     ...\key\Printapp_KEY.pem     the key file. It stays OUTSIDE
             the project folder and is never committed or copied.
    The web address, Google client ID and admins are in deploy\server.conf.
#>
param(
    [string]$Server = "ubuntu@35.154.161.180",
    [string]$Key = "C:\Official\Coding\Personal Coding Projects\key\Printapp_KEY.pem",
    [switch]$Status,
    [switch]$Backup,
    [string]$Database = "",
    [switch]$Replace,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Remote = "sudo bash /opt/drivenstyle/app/deploy/install.sh"

function Step($text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }

function Check($what) {
    # Stops at the first command that fails, saying which one.
    if ($LASTEXITCODE -ne 0) { throw "STOPPED: $what failed (see the message above)." }
}

function On-Server($command, $what) {
    & ssh -i $Key $Server $command
    Check $what
}

if (-not (Test-Path $Key)) { throw "Key file not found: $Key  (give it with -Key)" }

# ---------------------------------------------------------------- -Status
if ($Status) {
    On-Server "$Remote --status" "Asking the server"
    exit 0
}

# ---------------------------------------------------------------- -Backup
if ($Backup) {
    $folder = Join-Path $Root "data\server-backups"
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    $stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
    Step "Making a backup on the server"
    On-Server "$Remote --make-backup" "The backup on the server"
    Step "Fetching it to $folder"
    & scp -i $Key "${Server}:/tmp/dns-backup.db.gz" (Join-Path $folder "drivenstyle-$stamp.db.gz")
    Check "Fetching the database copy"
    & scp -i $Key "${Server}:/tmp/dns-proofs.tgz" (Join-Path $folder "proofs-$stamp.tgz")
    Check "Fetching the proofs"
    On-Server "rm -f /tmp/dns-backup.db.gz /tmp/dns-proofs.tgz" "Tidying up on the server"
    Write-Host ""
    Write-Host "Backup saved in $folder" -ForegroundColor Green
    exit 0
}

# -------------------------------------------------------------- -Database
if ($Database -ne "") {
    if ($Database -eq "desktop") {
        $Database = Join-Path $env:LOCALAPPDATA "Drive N Style Reports\drivenstyle.db"
    }
    if (-not (Test-Path $Database)) { throw "Database not found: $Database" }
    Step "Copying $Database to the server"
    & scp -i $Key $Database "${Server}:/tmp/dns-desktop.db"
    Check "Copying the database"
    $flag = ""
    if ($Replace) { $flag = " --replace" }
    On-Server "$Remote --bring-across /tmp/dns-desktop.db$flag" "Bringing the data across"
    exit 0
}

# --------------------------------------------------------- install / update
Set-Location $Root

Step "1. What will be sent"
$version = (& git log -1 --format="%h %s")
Check "Reading Git"
Write-Host "   Last commit: $version"
$changed = (& git status --porcelain --untracked-files=no)
if ($changed) {
    Write-Host "   NOTE: these changes are NOT committed and will NOT be sent:" -ForegroundColor Yellow
    $changed | ForEach-Object { Write-Host "     $_" -ForegroundColor Yellow }
}

if (-not $SkipBuild) {
    Step "2. Building the screens"
    Push-Location (Join-Path $Root "web\frontend")
    try {
        if (-not (Test-Path "node_modules")) {
            & npm ci
            Check "npm ci"
        }
        & npm run build
        Check "Building the screens"
    } finally { Pop-Location }
}
if (-not (Test-Path (Join-Path $Root "web\frontend\dist\index.html"))) {
    throw "The built screens are missing (web\frontend\dist). Run without -SkipBuild."
}

Step "3. Packing"
$pack = Join-Path $env:TEMP "dns-release"
if (Test-Path $pack) { Remove-Item -Recurse -Force $pack }
New-Item -ItemType Directory -Path $pack | Out-Null
$code = Join-Path $pack "dns-code.tar"
$screens = Join-Path $pack "dns-dist.tgz"
& git archive --format=tar -o $code HEAD
Check "Packing the code"
& tar -czf $screens -C (Join-Path $Root "web\frontend") dist
Check "Packing the screens"

Step "4. Copying to the server"
& scp -i $Key $code $screens "${Server}:/tmp/"
Check "Copying to the server"

Step "5. Installing on the server"
# Single quotes: PowerShell must leave the $ signs for the server's shell.
$install = 'rm -rf /tmp/dns-release && mkdir -p /tmp/dns-release && ' +
           'tar -xf /tmp/dns-code.tar -C /tmp/dns-release && ' +
           'tar -xzf /tmp/dns-dist.tgz -C /tmp/dns-release/web/frontend && ' +
           'sudo bash /tmp/dns-release/deploy/install.sh /tmp/dns-release; rc=$?; ' +
           'sudo rm -rf /tmp/dns-release /tmp/dns-code.tar /tmp/dns-dist.tgz; exit $rc'
& ssh -i $Key $Server $install
$result = $LASTEXITCODE
Remove-Item -Recurse -Force $pack
if ($result -ne 0) { throw "STOPPED: the server reported a problem (see above)." }

Write-Host ""
Write-Host "Finished." -ForegroundColor Green
