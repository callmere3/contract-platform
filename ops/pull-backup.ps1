<#
ВНИМАНИЕ: файл обязан храниться в UTF-8 С BOM. Windows PowerShell 5.1
читает .ps1 без BOM как ANSI (windows-1251), кириллица превращается в
мусор, и скрипт не парсится вовсе — падает ещё до первой строки кода.
Если правили файл редактором, который BOM снимает, вернуть так:
  $p = "ops\pull-backup.ps1"
  $t = [IO.File]::ReadAllText($p, [Text.Encoding]::UTF8)
  [IO.File]::WriteAllText($p, $t, (New-Object Text.UTF8Encoding $true))

СЛОЙ 2: копия бэкапов за пределами VPS — на ПК, в репозиторий restic.

Запускается планировщиком Windows раз в сутки. БЭКАП НА СЕРВЕРЕ НЕ ХРАНИТСЯ
(решение владельца 26.09.2026: с архивом отчётов Dista база выросла до
гигабайтов, и 14 дампов на сервере не помещаются). Сервер отдаёт всё
ПОТОКОМ по запросу (ops/serve-backup.sh): дамп идёт из pg_dump прямо сюда,
на диск сервера не ложась. Поэтому копии живут ТОЛЬКО здесь, в restic, — и
выключенный ПК значит, что за этот день копии нет.

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
  # Дамп меньше этого — считаем обрезанным: настоящая база весит гигабайты.
  [long]$MinDbBytes    = 50MB
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

  $sshOpts = "-i ""$key"" -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=30 -o Compression=yes"
  # IdentitiesOnly=yes обязателен: без него ssh может подсунуть ключ из
  # агента, и мы незаметно ходили бы полноправным root вместо ограниченного
  # ключа (ровно на это я попался при проверке). Compression=yes — дамп
  # текстовый и по сети сжимается в разы; на диске он остаётся несжатым,
  # иначе restic не смог бы его дедуплицировать.
  $date = Get-Date -Format "yyyy-MM-dd"

  # Три потока, по одному слову-команде на каждый (см. ops/serve-backup.sh).
  # Имена файлов те же, что раньше лежали в /root/backups, — restore.sh их
  # и ждёт.
  function Pull($what, $file) {
    $out = Join-Path $StagingPath $file
    cmd /c "ssh $sshOpts $Server $what > ""$out"" 2>nul"
    if ($LASTEXITCODE -ne 0) { throw "ssh ($what) вернул код $LASTEXITCODE — сервер недоступен или ключ не принят" }
    return $out
  }

  $db = Pull "db" "db-$date.sql"
  if ((Get-Item $db).Length -lt $MinDbBytes) { throw "Дамп базы подозрительно мал: $((Get-Item $db).Length) байт" }
  # pg_dump дописывает эту строку последней: нет её — поток оборвался на
  # полпути, и дамп не развернётся.
  $fs = [IO.File]::OpenRead($db)
  try {
    $n = [Math]::Min(4096, $fs.Length); $fs.Seek(-$n, 'End') | Out-Null
    $buf = New-Object byte[] $n; $fs.Read($buf, 0, $n) | Out-Null
  } finally { $fs.Close() }
  if (-not ([Text.Encoding]::UTF8.GetString($buf) -match 'PostgreSQL database dump complete')) {
    throw "Дамп базы оборван: нет завершающей строки pg_dump"
  }

  $tpl = Pull "templates" "templates-$date.tar"
  if ((Get-Item $tpl).Length -lt 1024) { throw "Архив шаблонов пуст или подозрительно мал" }

  $meta = Pull "meta" "_meta.tar"
  & tar -xf $meta -C $StagingPath
  if ($LASTEXITCODE -ne 0) { throw "Архив .env не распаковался — скорее всего приехал битым" }
  Remove-Item $meta -Force
  Rename-Item (Join-Path $StagingPath "env.txt") "env-$date.txt"
  Rename-Item (Join-Path $StagingPath "templates.txt") "templates-$date.txt"
  $files = (Get-ChildItem $StagingPath -File).Count
  $size  = [math]::Round(((Get-ChildItem $StagingPath -File | Measure-Object Length -Sum).Sum / 1KB))
  & $restic.FullName backup $StagingPath --repo $RepoPath --password-file $pwFile --tag contracts --quiet
  if ($LASTEXITCODE -ne 0) { throw "restic backup вернул код $LASTEXITCODE" }

  & $restic.FullName forget --repo $RepoPath --password-file $pwFile `
      --keep-daily 14 --keep-weekly 8 --keep-monthly 12 --prune --quiet
  if ($LASTEXITCODE -ne 0) { throw "restic forget вернул код $LASTEXITCODE" }

  $snaps = (& $restic.FullName snapshots --repo $RepoPath --password-file $pwFile --json | ConvertFrom-Json).Count
  $repoKB = [math]::Round(((Get-ChildItem $RepoPath -Recurse -File | Measure-Object Length -Sum).Sum / 1KB))
  Write-Log "OK  забрано ${files} файлов (${size} КБ), точек восстановления: ${snaps}, репозиторий ${repoKB} КБ"

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
Проверить сервер: ssh root@64.188.98.101 "cd ~/contract-platform && docker compose ps"
"@
  Set-Content -Path $alert -Value $text -Encoding utf8
  exit 1
}
finally {
  # Плейнтекст не ночует на диске: в репозитории restic всё зашифровано,
  # а в staging лежало как есть.
  if (Test-Path $StagingPath) { Remove-Item "$StagingPath\*" -Recurse -Force -ErrorAction SilentlyContinue }
}
