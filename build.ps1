python -m pip install -e ".[build]"
if ($LASTEXITCODE) { exit $LASTEXITCODE }

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name MingteTechServiceTool `
    --paths src `
    src\mtservice\__main__.py
exit $LASTEXITCODE
