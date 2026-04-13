# 创建 GitHub Hosts 自动更新定时任务
# 需要管理员权限运行

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-ExecutionPolicy Bypass -File "c:\Users\nonep\Desktop\news-digest\update-github-hosts.ps1"'
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask -TaskName 'Update GitHub Hosts' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force

Write-Output "Scheduled task created successfully, runs every 5 minutes"
