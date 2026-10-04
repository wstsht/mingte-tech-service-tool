$ErrorActionPreference = "Stop"

python -m pip install -e ".[build]"
python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name MingteTechServiceTool `
    --paths src `
    src\mtservice\__main__.py
