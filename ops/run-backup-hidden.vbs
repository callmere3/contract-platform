' run-backup-hidden.vbs — невидимый запуск pull-backup.ps1 из планировщика.
'
' Зачем нужен. Действие задачи "powershell.exe -WindowStyle Hidden" всё равно
' на миг создаёт окно консоли и ворует фокус (сворачивает другие окна) — это
' известное поведение powershell.exe. wscript через .Run(cmd, 0, True) окна
' не показывает вообще: второй аргумент 0 = скрыто, третий True = дождаться
' завершения и вернуть код выхода (чтобы "последний результат" задачи
' отражал успех/ошибку самого бэкапа, а не запускалку).
'
' Путь к .ps1 берём рядом с этим .vbs (ScriptFullName) — не хардкодим, чтобы
' переезд папки проекта ничего не ломал. Кириллица в пути ("Сервис создания
' документов") обрабатывается корректно: строки WScript всегда Unicode и не
' зависят от кодировки самого .vbs.
Option Explicit
Dim shell, ps1, rc
Set shell = CreateObject("WScript.Shell")
ps1 = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\")) & "pull-backup.ps1"
rc = shell.Run("powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File """ & ps1 & """", 0, True)
WScript.Quit rc
