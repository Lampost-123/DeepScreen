# Downloads Depth Anything 3 Mono Large (1.34 GB) into iw3's checkpoint folder, with curl's progress bar.
$dst = "D:\nunif\iw3\pretrained_models\hub\checkpoints\da3mono-large.safetensors"
$url = "https://huggingface.co/depth-anything/DA3MONO-LARGE/resolve/main/model.safetensors?download=true"
if (Test-Path $dst) { Write-Host "Already downloaded: $dst"; exit 0 }
curl.exe -L --fail -C - -o "$dst.part" $url
if ($LASTEXITCODE -ne 0) { Write-Host "DOWNLOAD FAILED (curl exit $LASTEXITCODE); run again to resume" -ForegroundColor Red; exit 1 }
Move-Item -Force "$dst.part" $dst
Write-Host ("DOWNLOAD DONE: {0:N0} bytes" -f (Get-Item $dst).Length) -ForegroundColor Green
