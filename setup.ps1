$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$utf8 = New-Object System.Text.UTF8Encoding($false)
$armed = $false
$backupMade = $false
try {
    Write-Host 'RASPBERRY PI WI-FI REPAIR - Windows setup'
    Write-Host 'Disconnect Pi power and insert its microSD card into your laptop.'
    Write-Host 'Use a WPA2-Personal Wi-Fi network, as shown in your report.'
    Write-Host 'This adds a saved Wi-Fi connection and sets up one repair boot.'
    Write-Host ''
    $letter = (Read-Host 'SD card bootfs drive letter, for example F').Trim().TrimEnd(':', '\')
    if ($letter -notmatch '^[A-Za-z]$') { throw 'Enter only a drive letter, for example F.' }
    $root = $letter.ToUpper() + ':\'
    if ($root -eq $env:SystemDrive + '\') { throw 'The Windows system drive cannot be used.' }
    $cmdline = Join-Path $root 'cmdline.txt'
    if (!(Test-Path -LiteralPath $cmdline) -or !(Test-Path -LiteralPath (Join-Path $root 'config.txt'))) {
        throw 'This is not the Pi boot folder. It must contain both cmdline.txt and config.txt.'
    }
    $original = [IO.File]::ReadAllText($cmdline).Trim()
    if ($original -notmatch '(^|\s)root=PARTUUID=' -or $original -match '[\r\n]') {
        throw 'cmdline.txt is not the expected single-line Pi boot configuration. No boot change made.'
    }
    if ($original -match '(^|\s)(systemd\.run[^\s=]*=|systemd\.unit=|init=)') {
        throw 'A special boot is already configured. Do not stack repairs. Send a copy of cmdline.txt for checking.'
    }
    Write-Host ('Selected Pi boot folder: ' + $root)
    $ssid = Read-Host 'Exact Wi-Fi name (press Enter for Saikiran)'
    if ($ssid.Length -eq 0) { $ssid = 'Saikiran' }
    $ssidBytes = $utf8.GetBytes($ssid)
    if ($ssidBytes.Length -lt 1 -or $ssidBytes.Length -gt 32 -or $ssid -match '[\x00-\x1f\x7f]') {
        throw 'Wi-Fi name must be 1-32 UTF-8 bytes, without control characters.'
    }
    $secure = Read-Host 'Wi-Fi password (hidden while typing)' -AsSecureString
    $credential = New-Object System.Net.NetworkCredential('', $secure)
    $passwordText = $credential.Password
    if (!(($passwordText -match '^[\x20-\x7e]{8,63}$') -or ($passwordText -match '^[0-9a-fA-F]{64}$'))) {
        throw 'Use the WPA2 password: 8-63 ordinary characters, or a 64-digit hexadecimal key.'
    }
    $settings = @{ssid = $ssid; password = $passwordText} | ConvertTo-Json -Compress
    $backup = Join-Path $root 'cmdline-before-wifi-repair.txt'
    [IO.File]::Copy($cmdline, $backup, $true)
    $backupMade = $true
    $hash = (Get-FileHash -LiteralPath $backup -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText((Join-Path $root 'cmdline-before-wifi-repair.sha256'), $hash + '  cmdline-before-wifi-repair.txt' + "`n", $utf8)
    foreach ($name in @('robot-wifi-repair.sh', 'install-profile.py')) {
        [IO.File]::Copy((Join-Path $PSScriptRoot $name), (Join-Path $root $name), $true)
    }
    [IO.File]::WriteAllText((Join-Path $root 'robot-wifi-settings.json'), $settings, $utf8)
    $suffix = ' systemd.run="/usr/bin/timeout --signal=TERM --kill-after=5s 150s /bin/bash /boot/firmware/robot-wifi-repair.sh" systemd.run_success_action=poweroff systemd.run_failure_action=poweroff systemd.unit=kernel-command-line.target'
    [IO.File]::WriteAllText($cmdline, $original + $suffix + "`n", $utf8)
    $armed = $true
    Write-Host ''
    Write-Host 'READY. Safely eject the SD card and put it back in the Pi.' -ForegroundColor Green
    Write-Host ('Keep Wi-Fi ON: ' + $ssid)
    Write-Host 'Keep robot motor power disconnected during this repair.'
    Write-Host 'Power the Pi, wait 4 minutes, then unplug Pi power.'
    Write-Host 'Wait 5 seconds, reconnect power, and allow 2 minutes for normal boot.'
    Write-Host 'Check the hotspot/router connected-device list for robot.'
    Write-Host 'If needed, the SD card will contain PI-WIFI-FIX.txt. Share that report only.'
    Write-Host 'Do not share robot-wifi-settings.json: it temporarily contains your password.'
} catch {
    Write-Host ('SETUP STOPPED: ' + $_.Exception.Message) -ForegroundColor Red
    if ($backupMade -and !$armed) {
        try { [IO.File]::Copy($backup, $cmdline, $true) } catch { Write-Host 'Restore cmdline-before-wifi-repair.txt as cmdline.txt before booting.' }
        $settingsPath = Join-Path $root 'robot-wifi-settings.json'
        if (Test-Path -LiteralPath $settingsPath) { Remove-Item -LiteralPath $settingsPath -Force }
    }
    exit 1
} finally {
    $passwordText = $null
    $settings = $null
    $credential = $null
    $secure = $null
}
