<#
ВНИМАНИЕ: файл обязан храниться в UTF-8 С BOM. Windows PowerShell 5.1
читает .ps1 без BOM как ANSI (windows-1251), кириллица превращается в
мусор, и скрипт не парсится вовсе — падает ещё до первой строки кода.
Если правили файл редактором, который BOM снимает, вернуть так:
  $p = "ops\pull-backup.ps1"
  $t = [IO.File]::ReadAllText($p, [Text.Encoding]::UTF8)
  [IO.File]::WriteAllText($p, $t, (New-Object Text.UTF8Encoding $true))

СЛОЙ 2: копия бэкапов за пределами VPS — на ПК, в репозиторий restic.

Запускается планировщиком Windows раз в сутки. Слой 1 (ops/backup.sh, cron
на сервере) к этому моменту уже сложил свежие файлы в /root/backups; здесь
мы их только забираем.

ПОЧЕМУ ТЯНЕМ, А НЕ ТОЛКАЕМ. Сервер не знает ни адреса копии, ни ключа к
ней. Взломавший сервер не сможет стереть бэкапы — а стереть их первым делом
пробует любой шифровальщик. Ключ ограничен одной командой (см.
ops/serve-backup.sh), поэтому он и не пароль от сервера: прочитать бэкапы
может, зайти — нет.

ПОЧЕМУ restic, А НЕ ПРОСТО КОПИЯ ФАЙЛОВ. Перезапись одной и той же копии
защищает ровно от одного случая: «сервер умер прямо сейчас, и я это вижу».
Беду обычно замечают позже — удалили карточку (DELETE у контрагента
физический, мягкого удаления нет), сломала данные миграция, поработал
шифровальщик. Перезапись такое честно скопирует поверх последней живой
копии. Плюс сама перезапись — это окно: оборвалась сеть, и на месте
единственного бэкапа лежит обрезанный файл. restic вместо этого хранит
30+ точек восстановления, а благодаря дедупликации весь репозиторий весит
как одна копия: неизменившиеся шаблоны не ложатся заново.

ПОЧЕМУ cmd /c ДЛЯ СКАЧИВАНИЯ. PowerShell при перенаправлении '>' пишет
UTF-16 и портит бинарный поток; cmd перенаправляет сырые байты. Это не
украшательство — без него tar приезжает битым.
#>
param(
  [string]$Server      = "root@64.188.98.101",
  [string]$RepoPath    = "D:\Backups\contract-platform",
  [string]$StagingPath = "D:\Backups\staging",
  [string]$LogPath     = "D:\Backups\pull.log",
  # Старше этого — считаем, что cron на сервере сломался и молчит.
  [int]$MaxAgeHours    = 48
)

$ErrorActionPreference = "Stop"
$cfg      = Join-Path $env:USERPROFILE ".contracts-backup"
$key      = Join-Path $cfg "backup_key"
$pwFile   = Join-Path $cfg "restic-password.txt"
# Пока файл существует — последний запуск упал. Тихо сломавшийся бэкап
# обнаруживают в худший день, поэтому отказ должен быть видимым.
$alert    = "D:\Backups\БЭКАП-СЛОМАН.txt"

function Write-Log($msg) {
  $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
  Add-Content -Path $LogPath -Value $line -Encoding utf8
  Write-Output $line
}

try {
  # restic ставится winget'ом, а тот кладёт бинарник с версией в имени
  # (restic_0.19.1_windows_amd64.exe) и рабочего псевдонима не создаёт —
  # проверено, команда `restic` не резолвится. Ищем по маске, чтобы
  # обновление restic не сломало бэкап сменой имени файла.
  $restic = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\restic.restic_*\restic_*_windows_amd64.exe" -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending | Select-Object -First 1
  if (-not $restic) { throw "restic не найден. Поставить: winget install restic.restic" }
  foreach ($f in @($key, $pwFile)) { if (-not (Test-Path $f)) { throw "Нет файла: $f" } }

  # Плейнтекста на диске быть не должно дольше, чем нужно: в staging лежат
  # паспортные данные контрагентов и .env с секретами. Чистим до и после.
  if (Test-Path $StagingPath) { Remove-Item "$StagingPath\*" -Recurse -Force }
  else { New-Item -ItemType Directory -Path $StagingPath -Force | Out-Null }

  $tar = Join-Path $StagingPath "_pull.tar"
  $sshOpts = "-i ""$key"" -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=30"
  # IdentitiesOnly=yes обязателен: без него ssh может подсунуть ключ из
  # агента, и мы незаметно ходили бы полноправным root вместо ограниченного
  # ключа (ровно на это я попался при проверке).
  cmd /c "ssh $sshOpts $Server > ""$tar"" 2>nul"
  if ($LASTEXITCODE -ne 0) { throw "ssh вернул код $LASTEXITCODE — сервер недоступен или ключ не принят" }
  if (-not (Test-Path $tar) -or (Get-Item $tar).Length -lt 1024) { throw "Скачанный архив пуст или подозрительно мал" }

  & tar -xf $tar -C $StagingPath
  if ($LASTEXITCODE -ne 0) { throw "Архив не распаковался — скорее всего приехал битым" }
  Remove-Item $tar -Force

  # Свежесть. Слой 1 кладёт db-ГГГГ-ММ-ДД.sql; если самый свежий старше
  # MaxAgeHours, cron на сервере молчит — а молчание тут и есть авария.
  $newest = Get-ChildItem "$StagingPath\db-*.sql" | Sort-Object Name -Descending | Select-Object -First 1
  if (-not $newest) { throw "В бэкапе нет ни одного дампа db-*.sql" }
  $stamp = [datetime]::ParseExact($newest.BaseName.Substring(3), "yyyy-MM-dd", $null)
  $ageH  = [math]::Round(((Get-Date) - $stamp).TotalHours)
  if ($ageH -gt $MaxAgeHours) { throw "Свежему дампу $ageH ч (порог $MaxAgeHours) — cron на сервере сломался" }

  $files = (Get-ChildItem $StagingPath -File).Count
  $size  = [math]::Round(((Get-ChildItem $StagingPath -File | Measure-Object Length -Sum).Sum / 1KB))
  & $restic.FullName backup $StagingPath --repo $RepoPath --password-file $pwFile --tag contracts --quiet
  if ($LASTEXITCODE -ne 0) { throw "restic backup вернул код $LASTEXITCODE" }

  & $restic.FullName forget --repo $RepoPath --password-file $pwFile `
      --keep-daily 14 --keep-weekly 8 --keep-monthly 12 --prune --quiet
  if ($LASTEXITCODE -ne 0) { throw "restic forget вернул код $LASTEXITCODE" }

  $snaps = (& $restic.FullName snapshots --repo $RepoPath --password-file $pwFile --json | ConvertFrom-Json).Count
  $repoKB = [math]::Round(((Get-ChildItem $RepoPath -Recurse -File | Measure-Object Length -Sum).Sum / 1KB))
  Write-Log "OK  забрано ${files} файлов (${size} КБ), дампу ${ageH} ч, точек восстановления: ${snaps}, репозиторий ${repoKB} КБ"

  if (Test-Path $alert) { Remove-Item $alert -Force }
  exit 0
}
catch {
  Write-Log "ОШИБКА: $_"
  $text = @"
Бэкап contract-platform НЕ СДЕЛАН.

Когда: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Что:   $_

Пока этот файл лежит здесь, свежих копий нет.
Подробности: $LogPath
Проверить сервер: ssh root@64.188.98.101 "tail /var/log/contracts-backup.log"
"@
  Set-Content -Path $alert -Value $text -Encoding utf8
  exit 1
}
finally {
  # Плейнтекст не ночует на диске: в репозитории restic всё зашифровано,
  # а в staging лежало как есть.
  if (Test-Path $StagingPath) { Remove-Item "$StagingPath\*" -Recurse -Force -ErrorAction SilentlyContinue }
}
