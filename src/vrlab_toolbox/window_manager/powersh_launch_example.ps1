$python_path = "$HOME\powershell_scripts\power_sh\Scripts\python.exe"
$launch_window_script = "$HOME\powershell_scripts\example_window.py"

#Write-Host "Starting $launch_window_script"
$p = Start-Process -FilePath $python_path -ArgumentList $launch_window_script -PassThru
#$ProcessName = $p.ProcessName
$ID = $p.Id
#Write-Host "PS OUT - ProcessName:  $ProcessName with ID: $ID"
Write-Host $ID