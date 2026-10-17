# Play a game window in 3D in VR.
#   iw3 (D:\nunif) streams full-SBS frames on 127.0.0.1:1303
#   input_bridge.py turns controller clicks into mouse/keys on the game (127.0.0.1:1304)
#   the Godot viewer shows the stream in SteamVR
# Usage: .\vn3d_vr.ps1 "Part of the game window title" [-Divergence 1.5] [-StreamHeight 1080]
#        .\vn3d_vr.ps1 "Part of the game window title" -Layers
#   -Layers: no iw3; the game's Ren'Py hook (renpy_hook\vn3d_hook.rpy) sends separate
#            background / sprite / UI layers on 127.0.0.1:1305.
# Start SteamVR and the game first. Ctrl-C stops everything.
param(
    [Parameter(Mandatory = $true)][string]$Window,
    [double]$Divergence = 1.5,
    [int]$StreamHeight = 1080,
    [int]$StreamFps = 120,
    [int]$DepthResolution = 518,  # depth model input height (multiple of 14); 0 = model default (392). 518 = finer detail, ~14 ms
    [string]$GameKey = "",      # launcher's key for the game (its .exe); the viewer saves 3D strength under it
    [double]$Shape = 0.0,       # shape boost (rounder local shapes), 0-3; 0 = off
    [switch]$Media,             # video in VLC: trigger = play/pause, A/grip = jump back/forward
    [string]$VlcPass = "",      # VLC remote-control password (127.0.0.1:8190) for the viewer's seek bar
    [string]$DepthModel = "Any_V2_S",  # Any_V2_S (per image, fast) or VDA_Stream_S (video model: steadier in motion, ~28 ms)
    [switch]$Layers
)
$ErrorActionPreference = "Stop"
$python = "D:\nunif\venv\Scripts\python.exe"
# Windowless builds, so no console windows pop up next to the game.
$pythonw = "D:\nunif\venv\Scripts\pythonw.exe"
$godot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages\GodotEngine.GodotEngine_Microsoft.Winget.Source_8wekyb3d8bbwe\Godot_v4.7.2-stable_win64.exe"

# Leftovers from a previous run (e.g. its console was closed instead of Ctrl-C) hold the ports.
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'input_bridge\.py|vn3d(-stable)?\\viewer|iw3\.desktop|iw3_fast\.py' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# Escape [ ] etc.: video file names in VLC's title often contain them ("[1080p]").
$pattern = "*" + [System.Management.Automation.WildcardPattern]::Escape($Window) + "*"
$game = Get-Process | Where-Object { $_.MainWindowTitle -like $pattern } | Select-Object -First 1
if (-not $game) {
    Write-Host "No window with '$Window' in its title. Start the game first." -ForegroundColor Red
    exit 1
}
Write-Host "Game window: $($game.MainWindowTitle) ($($game.ProcessName))"
if (-not (Get-Process vrserver -ErrorAction SilentlyContinue)) {
    Write-Host "SteamVR is not running: the viewer will open as a flat window." -ForegroundColor Yellow
}

$bridge = Start-Process $pythonw -ArgumentList "-I", "`"$PSScriptRoot\input_bridge.py`"", "`"$Window`"" -PassThru -WindowStyle Minimized
if ($Layers) {
    $viewer = Start-Process $godot -ArgumentList "--path", "`"$PSScriptRoot\viewer`"", "--", "--mode=layers" -PassThru -WindowStyle Minimized
    try {
        Write-Host "Layers mode: close the viewer or press Ctrl-C to stop."
        Wait-Process -Id $viewer.Id
    }
    finally {
        foreach ($p in @($viewer, $bridge)) {
            if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
        }
        Write-Host "Stopped viewer and input bridge."
    }
    exit 0
}

$viewerArgs = @("--path", "`"$PSScriptRoot\viewer`"", "--", "--divergence=$Divergence", "--shape=$Shape")
if ($GameKey) { $viewerArgs += "`"--game=$GameKey`"" }
if ($Media) { $viewerArgs += "--media" }
if ($VlcPass) { $viewerArgs += "--vlc-pass=$VlcPass" }
$viewer = Start-Process $godot -ArgumentList $viewerArgs -PassThru -WindowStyle Minimized
# Cut the title bar and borders: capture covers the whole window frame, the game only its client area.
$crop = (& $python -I "$PSScriptRoot\window_crop.py" $Window) -split " " | Where-Object { $_ }
Write-Host "Crop: $($crop -join ' ')"
$depthRes = if ($DepthResolution -gt 0) { @("--resolution", $DepthResolution) } else { @() }
try {
    Push-Location D:\nunif
    # iw3_fast.py = iw3.desktop with the depth model replayed via CUDA graphs (~2x faster).
    & $python "$PSScriptRoot\iw3_fast.py" --bind-addr 127.0.0.1 --window-name $Window --full-sbs `
        --depth-model $DepthModel --divergence $Divergence --stream-height $StreamHeight `
        --stream-fps $StreamFps @depthRes --stream-quality 90 --gpu-jpeg --screenshot wc_cuda --disable-draw-cursor --preserve-screen-border @crop --vn3d-shape $Shape
}
finally {
    Pop-Location
    foreach ($p in @($viewer, $bridge)) {
        if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    }
    Write-Host "Stopped viewer and input bridge."
}
