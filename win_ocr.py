import subprocess
import os

def run_win_ocr(image_path):
    abs_path = os.path.abspath(image_path).replace("'", "''")
    ps_script = f"""
$ErrorActionPreference = 'Stop'
[void][System.Reflection.Assembly]::LoadWithPartialName("System.Runtime.WindowsRuntime")
$path = '{abs_path}'
$asyncOp = [Windows.Storage.StorageFile]::GetFileFromPathAsync($path)
$file = [System.WindowsRuntimeSystemExtensions]::GetAwaiter($asyncOp).GetResult()

$streamOp = $file.OpenAsync([Windows.Storage.FileAccessMode]::Read)
$stream = [System.WindowsRuntimeSystemExtensions]::GetAwaiter($streamOp).GetResult()

$decOp = [Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)
$decoder = [System.WindowsRuntimeSystemExtensions]::GetAwaiter($decOp).GetResult()

$bmpOp = $decoder.GetSoftwareBitmapAsync()
$bmp = [System.WindowsRuntimeSystemExtensions]::GetAwaiter($bmpOp).GetResult()

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
$ocrOp = $engine.RecognizeAsync($bmp)
$result = [System.WindowsRuntimeSystemExtensions]::GetAwaiter($ocrOp).GetResult()
Write-Output $result.Text
"""
    try:
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, text=True, timeout=15)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception as e:
        pass
    return None
