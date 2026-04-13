# GitHub Hosts 自动更新脚本
# 用途：定期从 GitHub 下载最新的 hosts 配置并更新系统 hosts 文件

$hostsUrl = "https://raw.githubusercontent.com/maxiaof/github-hosts/master/hosts"
$hostsFile = "C:\Windows\System32\drivers\etc\hosts"
$backupFile = "$env:USERPROFILE\hosts.backup"

# 备份原 hosts 文件
Copy-Item $hostsFile $backupFile -Force

# 下载最新 hosts 内容
try {
    $newHosts = Invoke-RestMethod -Uri $hostsUrl -ErrorAction Stop
    
    # 读取原 hosts 文件内容（移除旧的 GitHub hosts 配置）
    $originalContent = Get-Content $hostsFile -Raw
    
    # 移除旧的 GitHub hosts 配置（如果有）
    $cleanedContent = $originalContent -replace "#Github Hosts Start.*#Github Hosts End", ""
    
    # 添加新的 GitHub hosts 配置
    $updatedContent = $cleanedContent.TrimEnd() + "`r`n`r`n" + $newHosts + "`r`n"
    
    # 写入 hosts 文件
    Set-Content -Path $hostsFile -Value $updatedContent -Force -Encoding UTF8
    
    # 刷新 DNS 缓存
    ipconfig /flushdns | Out-Null
    
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Output "[$timestamp] GitHub hosts 更新成功"
    
} catch {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Output "[$timestamp] GitHub hosts 更新失败: $_"
    # 恢复备份
    Copy-Item $backupFile $hostsFile -Force
}
