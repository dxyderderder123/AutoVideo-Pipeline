if (-not (Test-Path "v:\Default\Desktop\Self-media\workspace\covers")) { mkdir "v:\Default\Desktop\Self-media\workspace\covers" }
$files = Get-ChildItem "v:\Default\Desktop\Self-media\workspace\input\*.md"
foreach ($file in $files) {
    Write-Host "Processing $($file.Name)..."
    & "v:\Default\Desktop\Self-media\venv\Scripts\python.exe" "v:\Default\Desktop\Self-media\src_english\step8_cover.py" --input_file $file.FullName --output_dir "v:\Default\Desktop\Self-media\workspace\covers"
}
