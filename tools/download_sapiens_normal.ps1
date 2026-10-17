# Downloads Meta Sapiens Normal 0.3B (1.36 GB, CC-BY-NC 4.0) for the surface-normal 3D experiment.
$dst = "D:\nunif\iw3\pretrained_models\hub\checkpoints\sapiens_0.3b_normal_render_people_epoch_66_torchscript.pt2"
$url = "https://huggingface.co/facebook/sapiens-normal-0.3b-torchscript/resolve/main/sapiens_0.3b_normal_render_people_epoch_66_torchscript.pt2"
if (Test-Path $dst) { Write-Host "Already downloaded: $dst"; exit 0 }
curl.exe -L --fail -C - -o "$dst.part" $url
if ($LASTEXITCODE -ne 0) { Write-Host "DOWNLOAD FAILED (curl exit $LASTEXITCODE); run again to resume" -ForegroundColor Red; exit 1 }
Move-Item -Force "$dst.part" $dst
Write-Host ("DOWNLOAD DONE: {0:N0} bytes" -f (Get-Item $dst).Length) -ForegroundColor Green
