# VN3D (stable) launcher: pick a Ren'Py game and play it in 3D on the headset (depth mode).
# Start from the desktop shortcut, or:
#   powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File D:\vn3d-stable\vn3d_launcher.ps1
# The game list is kept in %APPDATA%\VN3D-stable\games.json.
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

Add-Type -Namespace VN3D -Name Win -MemberDefinition @'
[StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
[DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
[DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hWnd, uint msg, IntPtr w, IntPtr l);
[DllImport("user32.dll")] public static extern int GetWindowLong(IntPtr hWnd, int index);
'@

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$dataDir = Join-Path $env:APPDATA "VN3D-stable"
$listFile = Join-Path $dataDir "games.json"
New-Item -ItemType Directory -Force $dataDir | Out-Null

function Test-RenPyFolder([string]$dir) {
    (Test-Path (Join-Path $dir "renpy")) -and (Test-Path (Join-Path $dir "game"))
}

function Get-GameExe([string]$dir) {
    # Ren'Py ships "<name>.exe" and often "<name>-32.exe"; the .py next to it names the main one.
    $py = Get-ChildItem $dir -Filter *.py -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($py) {
        $exe = Join-Path $dir ($py.BaseName + ".exe")
        if (Test-Path $exe) { return $exe }
    }
    $exes = Get-ChildItem $dir -Filter *.exe -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -notlike "*-32.exe" }
    if ($exes) { return ($exes | Select-Object -First 1).FullName }
    return $null
}

function Get-GameName([string]$dir, [string]$exe) {
    # Ren'Py writes the game's title on line 6 or so of log.txt ("My Visual Novel").
    $log = Join-Path $dir "log.txt"
    if (Test-Path $log) {
        $lines = Get-Content $log -TotalCount 12
        for ($i = 0; $i -lt $lines.Count - 1; $i++) {
            if ($lines[$i] -like "Ren'Py *" -and $lines[$i + 1] -eq "" -and $lines[$i + 2]) { return $lines[$i + 2].Trim() }
        }
    }
    return [System.IO.Path]::GetFileNameWithoutExtension($exe)
}

function Load-Games {
    $games = @()
    if (Test-Path $listFile) {
        try { $games = @(Get-Content $listFile -Raw | ConvertFrom-Json) } catch { $games = @() }
    }
    # Pick up Ren'Py games in Downloads that aren't in the list yet.
    $downloads = Join-Path $env:USERPROFILE "Downloads"
    foreach ($d in Get-ChildItem $downloads -Directory -ErrorAction SilentlyContinue) {
        if (-not (Test-RenPyFolder $d.FullName)) { continue }
        $exe = Get-GameExe $d.FullName
        if (-not $exe -or ($games | Where-Object { $_.exe -eq $exe })) { continue }
        $games += [pscustomobject]@{ name = (Get-GameName $d.FullName $exe); exe = $exe }
    }
    return @($games | Sort-Object name)
}

function Save-Games($games) {
    ConvertTo-Json -InputObject @($games) -Depth 3 | Set-Content -Path $listFile -Encoding UTF8
}

function Wait-GameWindow([string]$dir, [int]$seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        $p = Get-Process | Where-Object { $_.MainWindowTitle -and $_.Path -and $_.Path.StartsWith($dir, [StringComparison]::OrdinalIgnoreCase) } | Select-Object -First 1
        if ($p) { return $p }
        Start-Sleep -Milliseconds 500
        [System.Windows.Forms.Application]::DoEvents()
    }
    return $null
}

function Test-Fullscreen([IntPtr]$hwnd) {
    $r = New-Object VN3D.Win+RECT
    [void][VN3D.Win]::GetWindowRect($hwnd, [ref]$r)
    $b = [System.Windows.Forms.Screen]::FromHandle($hwnd).Bounds
    return ($r.Left -le $b.Left -and $r.Top -le $b.Top -and $r.Right -ge $b.Right -and $r.Bottom -ge $b.Bottom)
}

function Set-Windowed([IntPtr]$hwnd) {
    # A fullscreen game skips the desktop compositor, and window capture then only gets a new
    # frame on Alt-Tab (the picture freezes). Ren'Py toggles fullscreen with F and remembers it.
    if (-not (Test-Fullscreen $hwnd)) { return $true }
    # Post the F key straight to the game window (WM_KEYDOWN/UP, scancode 0x21): works without
    # focus, which Windows won't hand to a background process.
    $down = [IntPtr](1 -bor (0x21 -shl 16))
    $up = [IntPtr]([long](1 -bor (0x21 -shl 16) -bor (1 -shl 30)) -bor 0x80000000L)
    [void][VN3D.Win]::PostMessage($hwnd, 0x100, [IntPtr]0x46, $down)
    Start-Sleep -Milliseconds 50
    [void][VN3D.Win]::PostMessage($hwnd, 0x101, [IntPtr]0x46, $up)
    $deadline = (Get-Date).AddSeconds(5)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 300
        [System.Windows.Forms.Application]::DoEvents()
        # Ren'Py first shrinks the window, then adds the title bar; the 3D crop is measured
        # from the title bar, so wait for it (WS_CAPTION) before going on.
        $hasCaption = ([VN3D.Win]::GetWindowLong($hwnd, -16) -band 0x00C00000) -eq 0x00C00000
        if (-not (Test-Fullscreen $hwnd) -and $hasCaption) { Start-Sleep -Milliseconds 500; return $true }
    }
    return (-not (Test-Fullscreen $hwnd))
}

$script:games = Load-Games
Save-Games $script:games
if ($env:VN3D_LAUNCHER_TEST) {
    # Self-check without the window: print the detected games.
    $script:games | ForEach-Object { "{0} | {1}" -f $_.name, $_.exe }
    return
}

# ---- window ----
$form = New-Object System.Windows.Forms.Form
$form.Text = "DeepScreen - games and videos in 3D"
$form.Size = New-Object System.Drawing.Size(560, 540)
$form.StartPosition = "CenterScreen"
$form.Font = New-Object System.Drawing.Font("Segoe UI", 11)

$label = New-Object System.Windows.Forms.Label
$label.Text = "Pick a game:"
$label.Location = New-Object System.Drawing.Point(16, 12)
$label.AutoSize = $true
$form.Controls.Add($label)

$list = New-Object System.Windows.Forms.ListBox
$list.Location = New-Object System.Drawing.Point(16, 40)
$list.Size = New-Object System.Drawing.Size(510, 240)
$form.Controls.Add($list)

function Refresh-List {
    $list.Items.Clear()
    foreach ($g in $script:games) { [void]$list.Items.Add($g.name) }
    if ($list.Items.Count -gt 0) { $list.SelectedIndex = 0 }
}
Refresh-List

$strengthLabel = New-Object System.Windows.Forms.Label
$strengthLabel.Text = "3D strength:"
$strengthLabel.Location = New-Object System.Drawing.Point(16, 296)
$strengthLabel.AutoSize = $true
$form.Controls.Add($strengthLabel)

$strength = New-Object System.Windows.Forms.NumericUpDown
$strength.Location = New-Object System.Drawing.Point(120, 292)
$strength.Size = New-Object System.Drawing.Size(70, 28)
$strength.DecimalPlaces = 1
$strength.Increment = 0.1
$strength.Minimum = 0.2
$strength.Maximum = 5.0
$strength.Value = 1.5
$form.Controls.Add($strength)

# The VR viewer saves the strength you set in the headset per game; start from that next time.
$strengthFile = Join-Path $dataDir "strength.json"
function Load-Strength {
    if ($list.SelectedIndex -lt 0 -or -not (Test-Path $strengthFile)) { return }
    try { $saved = Get-Content $strengthFile -Raw | ConvertFrom-Json } catch { return }
    $exe = $script:games[$list.SelectedIndex].exe
    $v = $saved.PSObject.Properties | Where-Object { $_.Name -eq $exe } | Select-Object -ExpandProperty Value -First 1
    if ($v) { $strength.Value = [decimal][math]::Min(5.0, [math]::Max(0.2, [double]$v)) }
    $s = $saved.PSObject.Properties | Where-Object { $_.Name -eq "shape:$exe" } | Select-Object -ExpandProperty Value -First 1
    if ($null -ne $s -and $shapeBox) { $shapeBox.Value = [decimal][math]::Min(3.0, [math]::Max(0.0, [double]$s)) }
}
$list.Add_SelectedIndexChanged({ Load-Strength })
Load-Strength

$add = New-Object System.Windows.Forms.Button
$add.Text = "Add game..."
$add.Location = New-Object System.Drawing.Point(300, 290)
$add.Size = New-Object System.Drawing.Size(110, 34)
$form.Controls.Add($add)

$remove = New-Object System.Windows.Forms.Button
$remove.Text = "Remove"
$remove.Location = New-Object System.Drawing.Point(416, 290)
$remove.Size = New-Object System.Drawing.Size(110, 34)
$form.Controls.Add($remove)

$shapeLabel = New-Object System.Windows.Forms.Label
$shapeLabel.Text = "Shape boost:"
$shapeLabel.Location = New-Object System.Drawing.Point(16, 336)
$shapeLabel.AutoSize = $true
$form.Controls.Add($shapeLabel)

$shapeBox = New-Object System.Windows.Forms.NumericUpDown
$shapeBox.Location = New-Object System.Drawing.Point(120, 332)
$shapeBox.Size = New-Object System.Drawing.Size(70, 28)
$shapeBox.DecimalPlaces = 1
$shapeBox.Increment = 0.1
$shapeBox.Minimum = 0.0
$shapeBox.Maximum = 3.0
$shapeBox.Value = 0.0
$form.Controls.Add($shapeBox)

$shapeHint = New-Object System.Windows.Forms.Label
$shapeHint.Text = "rounder bodies/objects; 0 = off"
$shapeHint.Location = New-Object System.Drawing.Point(200, 336)
$shapeHint.AutoSize = $true
$shapeHint.ForeColor = [System.Drawing.Color]::Gray
$form.Controls.Add($shapeHint)
Load-Strength  # again, now that the shape box exists

$play = New-Object System.Windows.Forms.Button
$play.Text = "Play in VR"
$play.Location = New-Object System.Drawing.Point(16, 376)
$play.Size = New-Object System.Drawing.Size(300, 44)
$play.Font = New-Object System.Drawing.Font("Segoe UI", 13, [System.Drawing.FontStyle]::Bold)
$form.Controls.Add($play)

$video = New-Object System.Windows.Forms.Button
$video.Text = "Watch video..."
$video.Location = New-Object System.Drawing.Point(326, 376)
$video.Size = New-Object System.Drawing.Size(200, 44)
$form.Controls.Add($video)

$vlcExe = "C:\Program Files\VideoLAN\VLC\vlc.exe"
$vlcPort = 8190  # VLC's remote control (localhost only), used by the viewer's seek bar

$upscale = New-Object System.Windows.Forms.CheckBox
$upscale.Text = "Upscale videos (RTX Super Resolution)"
$upscale.Location = New-Object System.Drawing.Point(16, 426)
$upscale.AutoSize = $true
$upscale.Checked = $true
$form.Controls.Add($upscale)

# Video size: VLC window height and 3D stream height (bigger = sharper in a big VR screen, slower).
$sizeLabel = New-Object System.Windows.Forms.Label
$sizeLabel.Text = "Video size:"
$sizeLabel.Location = New-Object System.Drawing.Point(330, 428)
$sizeLabel.AutoSize = $true
$form.Controls.Add($sizeLabel)
$videoSize = New-Object System.Windows.Forms.ComboBox
$videoSize.DropDownStyle = "DropDownList"
[void]$videoSize.Items.AddRange(@("720p", "1080p", "1440p", "2160p (exp.)"))
$videoSize.Location = New-Object System.Drawing.Point(420, 424)
$videoSize.Size = New-Object System.Drawing.Size(106, 28)
$launcherFile = Join-Path $dataDir "launcher.json"
$savedSize = "1080p"
try { if (Test-Path $launcherFile) { $savedSize = (Get-Content $launcherFile -Raw | ConvertFrom-Json).video_size } } catch { }
$videoSize.SelectedItem = if ($videoSize.Items -contains $savedSize) { $savedSize } else { "1080p" }
$videoSize.Add_SelectedIndexChanged({
    try { @{ video_size = $videoSize.SelectedItem } | ConvertTo-Json | Set-Content $launcherFile -Encoding UTF8 } catch { }
})
$form.Controls.Add($videoSize)

function Prepare-VR {
    # ComfyUI fills the GPU and makes VR stutter or crash; offer to close it.
    $comfy = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'ComfyUI\\main\.py' }
    if ($comfy) {
        $r = [System.Windows.Forms.MessageBox]::Show("ComfyUI is running and uses most of the GPU memory, which makes VR choppy.`n`nClose ComfyUI now?", "VN3D", "YesNo")
        if ($r -eq "Yes") { $comfy | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } }
    }
    if (-not (Get-Process vrserver -ErrorAction SilentlyContinue)) {
        $status.Text = "Starting SteamVR (turn the headset on)..."
        Start-Process "steam://rungameid/250820"
        $deadline = (Get-Date).AddSeconds(60)
        while ((Get-Date) -lt $deadline -and -not (Get-Process vrcompositor -ErrorAction SilentlyContinue)) {
            Start-Sleep -Milliseconds 500; [System.Windows.Forms.Application]::DoEvents()
        }
    }
}

function Get-Saved([string]$key, $default) {
    if (-not (Test-Path $strengthFile)) { return $default }
    try { $saved = Get-Content $strengthFile -Raw | ConvertFrom-Json } catch { return $default }
    $v = $saved.PSObject.Properties | Where-Object { $_.Name -eq $key } | Select-Object -ExpandProperty Value -First 1
    if ($null -eq $v) { return $default }
    return $v
}

function Get-VlcVideoSize([string]$pass) {
    # Video_resolution from VLC's remote control (e.g. "640x360"); $null if not known within 5 s.
    $auth = @{ Authorization = "Basic " + [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes(":$pass")) }
    $deadline = (Get-Date).AddSeconds(5)
    while ((Get-Date) -lt $deadline) {
        try {
            $st = Invoke-RestMethod "http://127.0.0.1:$vlcPort/requests/status.json" -Headers $auth -TimeoutSec 2
            foreach ($c in $st.information.category.PSObject.Properties) {
                $r = $c.Value.Video_resolution
                if ($r -match '^(\d+)x(\d+)$') { return @([int]$Matches[1], [int]$Matches[2]) }
            }
        } catch { }
        Start-Sleep -Milliseconds 300
        [System.Windows.Forms.Application]::DoEvents()
    }
    return $null
}

function Start-3D([string]$title, [string]$key, $div, $shape, [bool]$media, [string]$vlcPass = "", [int]$streamHeight = 1080) {
    $status.Text = "3D starting for '$title': picture appears in the headset in a few minutes."
    # -NoExit keeps the console open after the 3D view stops, so errors stay readable.
    $a = @("-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$here\vn3d_vr.ps1`"",
           "-Window", "`"$title`"", "-Divergence", ([string]$div).Replace(",", "."),
           "-GameKey", "`"$key`"", "-Shape", ([string]$shape).Replace(",", "."))
    if ($media) { $a += "-Media" }
    if ($vlcPass) { $a += @("-VlcPass", $vlcPass) }
    if ($streamHeight -ne 1080) { $a += @("-StreamHeight", $streamHeight) }
    Start-Process powershell -ArgumentList $a
}

$status = New-Object System.Windows.Forms.Label
$status.Location = New-Object System.Drawing.Point(16, 458)
$status.Size = New-Object System.Drawing.Size(510, 24)
$form.Controls.Add($status)

$add.Add_Click({
    $dlg = New-Object System.Windows.Forms.OpenFileDialog
    $dlg.Filter = "Game (*.exe)|*.exe"
    $dlg.Title = "Pick the Ren'Py game's .exe"
    if ($dlg.ShowDialog() -ne "OK") { return }
    $dir = Split-Path -Parent $dlg.FileName
    if (-not (Test-RenPyFolder $dir)) {
        $r = [System.Windows.Forms.MessageBox]::Show("This doesn't look like a Ren'Py game (no renpy and game folders). Add it anyway?", "VN3D", "YesNo")
        if ($r -ne "Yes") { return }
    }
    if (-not ($script:games | Where-Object { $_.exe -eq $dlg.FileName })) {
        $script:games = @($script:games) + [pscustomobject]@{ name = (Get-GameName $dir $dlg.FileName); exe = $dlg.FileName }
        $script:games = @($script:games | Sort-Object name)
        Save-Games $script:games
    }
    Refresh-List
})

$remove.Add_Click({
    if ($list.SelectedIndex -lt 0) { return }
    $g = $script:games[$list.SelectedIndex]
    $script:games = @($script:games | Where-Object { $_.exe -ne $g.exe })
    Save-Games $script:games
    Refresh-List
    $status.Text = "Removed $($g.name) from the list (the game itself is untouched)."
})

$play.Add_Click({
    if ($list.SelectedIndex -lt 0) { return }
    $g = $script:games[$list.SelectedIndex]
    if (-not (Test-Path $g.exe)) { $status.Text = "Game not found: $($g.exe)"; return }
    $dir = Split-Path -Parent $g.exe
    $play.Enabled = $false
    try {
        Prepare-VR
        $proc = Wait-GameWindow $dir 0
        if (-not $proc) {
            $status.Text = "Starting $($g.name)..."
            Start-Process -FilePath $g.exe -WorkingDirectory $dir
            $proc = Wait-GameWindow $dir 90
        }
        if (-not $proc) { $status.Text = "The game window didn't appear within 90 s."; return }
        if (-not (Set-Windowed $proc.MainWindowHandle)) {
            $r = [System.Windows.Forms.MessageBox]::Show("$($g.name) is fullscreen, and couldn't be switched to a window. Fullscreen makes the 3D picture freeze until you Alt-Tab.`n`nPress F in the game to switch to a window, then click OK. Or Cancel to stop.", "VN3D", "OKCancel")
            if ($r -ne "OK") { $status.Text = "Stopped."; return }
        }
        Start-3D $proc.MainWindowTitle $g.exe $strength.Value $shapeBox.Value $false
    }
    finally {
        $play.Enabled = $true
    }
})

$video.Add_Click({
    $dlg = New-Object System.Windows.Forms.OpenFileDialog
    $dlg.Filter = "Videos and pictures|*.mp4;*.mkv;*.webm;*.avi;*.mov;*.wmv;*.m4v;*.jpg;*.jpeg;*.png;*.webp|All files|*.*"
    $dlg.Title = "Pick a video or picture to watch in 3D"
    if ($dlg.ShowDialog() -ne "OK") { return }
    if (-not (Test-Path $vlcExe)) { $status.Text = "VLC not found at $vlcExe"; return }
    if (Get-Process vlc -ErrorAction SilentlyContinue | Where-Object MainWindowTitle) {
        $r = [System.Windows.Forms.MessageBox]::Show("VLC is already open. Close it so the 3D view picks the right window?", "VN3D", "YesNo")
        if ($r -ne "Yes") { return }
        Get-Process vlc | Stop-Process -Force
        Start-Sleep -Milliseconds 500
    }
    $video.Enabled = $false
    try {
        Prepare-VR
        $status.Text = "Starting VLC..."
        $started = Get-Date
        # Minimal view: no menus or controls in the picture; jumps are 10 s on the arrow keys
        # (the VR controller sends those); closes when the video ends.
        # Remote control for the VR seek bar: localhost only, new random password each time.
        $vlcPass = -join ((1..16) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })
        # --no-qt-video-autoresize: otherwise VLC snaps its window back to the video's own size right
        # after we set the chosen Video size (720p-2160p), and the 3D gets the small window.
        $vlcArgs = @("--qt-minimal-view", "--no-qt-video-autoresize", "--no-qt-fs-controller", "--no-qt-privacy-ask", "--qt-continue=0",
                     "--no-video-title-show", "--play-and-exit", "--image-duration=-1",
                     "--short-jump-size=10", "--key-jump+short=Right", "--key-jump-short=Left",
                     "--extraintf=http", "--http-host=127.0.0.1", "--http-port=$vlcPort", "--http-password=$vlcPass")
        # RTX Video Super Resolution (needs it switched on in the NVIDIA App; otherwise normal scaling).
        if ($upscale.Checked) { $vlcArgs += "--d3d11-upscale-mode=super" }
        $vlcArgs += "`"$($dlg.FileName)`""
        Start-Process $vlcExe -ArgumentList $vlcArgs
        $proc = $null
        $deadline = (Get-Date).AddSeconds(20)
        while (-not $proc -and (Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 300; [System.Windows.Forms.Application]::DoEvents()
            $proc = Get-Process vlc -ErrorAction SilentlyContinue |
                Where-Object { $_.StartTime -ge $started.AddSeconds(-1) -and $_.MainWindowTitle -like "* - VLC media player" } |
                Select-Object -First 1
        }
        if (-not $proc) { $status.Text = "VLC's window didn't appear within 20 s."; return }
        # Size the video window to the chosen height (720/1080/1440, also the 3D stream height) at the
        # video's aspect ratio: VLC then scales (or RTX-upscales) small videos up and big ones down.
        $res = Get-VlcVideoSize $vlcPass
        $h = [int](("$($videoSize.SelectedItem)" -split 'p')[0])
        if ($res) {
            $w = [int]([math]::Round($h * $res[0] / $res[1] / 2) * 2)
            $resizeArgs = @("-I", "$here\window_crop.py", $proc.MainWindowTitle, "--resize-client", "${w}x${h}")
            # 2160p is as tall as the monitor: hang the title bar off-screen so it stays a normal
            # window (a screen-filling one would be treated as fullscreen and freeze the capture).
            if ($h -ge 2160) { $resizeArgs += "--frame-offscreen" }
            & "D:\nunif\venv\Scripts\python.exe" @resizeArgs | Out-Null
        }
        # Videos share one remembered strength / shape boost, saved by the viewer under "video".
        $s = Get-Saved "video" $strength.Value
        $k = Get-Saved "shape:video" $shapeBox.Value
        Start-3D $proc.MainWindowTitle "video" $s $k $true $vlcPass $h
    }
    finally {
        $video.Enabled = $true
    }
})

[void]$form.ShowDialog()
