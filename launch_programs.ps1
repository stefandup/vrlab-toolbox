# Launch multiple programs simultaneously
# LabRecorder, AxioBiofeedback, and Python graphomotor script

Write-Host "Launching programs simultaneously..." -ForegroundColor Green

# Launch LabRecorder
Start-Process -FilePath "C:\Users\stefan\Downloads\LabRecorder-1.16.4-Win_amd64\LabRecorder\LabRecorder.exe"

# Launch AxioBiofeedback
Start-Process -FilePath "C:\Users\stefan\Documents\Unreal Projects\FOH_withTargetPhilani\FOH_Packaged\Windows\AxioBiofeedback.exe"

# Launch Python script using CMI_env virtual environment
Start-Process -FilePath "C:\home\stefan\graphomotor_cmi\CMI_env\Scripts\python.exe" -ArgumentList "C:\home\stefan\graphomotor_cmi\src\graphomotor_protocol\graphomotor_older_mooi.py"

Write-Host "All programs launched!" -ForegroundColor Green
