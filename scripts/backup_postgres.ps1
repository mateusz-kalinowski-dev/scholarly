# Backup bazy v1 (papers_db) — uruchom PRZED migracją na postgres_v2
param(
    [string]$Container = "postgres_db",
    [string]$DbName = "papers_db",
    [string]$User = "admin",
    [string]$OutDir = "backups"
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$out = Join-Path $root $OutDir
New-Item -ItemType Directory -Force -Path $out | Out-Null

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$dumpPath = Join-Path $out "${DbName}_${ts}.dump"
$metaPath = Join-Path $out "${DbName}_${ts}_meta.txt"

Write-Host "Backup $DbName z kontenera $Container -> $dumpPath"
$remote = "/tmp/${DbName}_${ts}.dump"
docker exec $Container pg_dump -U $User -Fc $DbName -f $remote
docker cp "${Container}:${remote}" $dumpPath
docker exec $Container rm -f $remote

@"
backup_time=$ts
database=$DbName
container=$Container
format=custom_pg_dump_Fc
note=MinIO bucket papers pozostaje bez zmian — źródła PDF/txt tam są
restore=docker exec -i $Container pg_restore -U $User -d ${DbName}_restore --clean $dumpPath
"@ | Set-Content -Path $metaPath -Encoding UTF8

Write-Host "OK: $dumpPath"
Write-Host "Meta: $metaPath"
