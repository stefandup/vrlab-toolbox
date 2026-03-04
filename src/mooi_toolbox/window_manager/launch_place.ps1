# Define Windows API functions
if (-not ([System.Management.Automation.PSTypeName]'Win32').Type) {
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;

public class Win32 {
    [DllImport("user32.dll")]
    public static extern bool EnumWindows(EnumWindowsProc enumProc, IntPtr lParam);
    
    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);
    
    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
    
    [DllImport("user32.dll")]
    public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, 
        int X, int Y, int cx, int cy, uint uFlags);
    
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }
    
    public const uint SWP_NOSIZE = 0x0001;
    public const uint SWP_NOMOVE = 0x0002;
    public const uint SWP_NOZORDER = 0x0004;
}
"@}

$callback = {
    param($hwnd, $lParam)
    $windowProcessId = 0
    [Win32]::GetWindowThreadProcessId($hwnd, [ref]$windowProcessId)
    
    Write-Host "Looking at process ID $process_id"

    if ($windowProcessId -eq $process_id) {
        $windows += $hwnd
        Write-Host "Found window $hwnd"
    }
    return $true
}

$python_path =  "C:\Users\stefan\powershell_scripts\power_sh\Scripts\python.exe"
$launch_window_script = "C:\Users\stefan\powershell_scripts\example_window.py"

$process_id = Start-Process -FilePath $python_path -ArgumentList $launch_window_script -PassThru
$process_id = $process_id.Id

$targetX = 100
$targetY = 100
$targetWidth = 800
$targetHeight = 600

# Initialize windows array
$windows = @()

Write-Host "Process ID is $process_id"

Write-Host "Waiting"
Start-Sleep -Milliseconds 2000
Write-Host "Getting "
[Win32]::EnumWindows($callback, [IntPtr]::Zero)
Write-Host "Found $($windows.Count) window(s)"

# After starting the process and waiting
$allProcessIds = @($process_id)  # Start with parent

# Get all child processes
$childProcesses = Get-Process | Where-Object { 
    try { $_.Parent.Id -eq $process_id } catch { $false }
}

foreach ($child in $childProcesses) {
    $allProcessIds += $child.Id
    Write-Host "Found child process: $($child.Id) - $($child.ProcessName)"
}

Write-Host "Total process IDs to check: $($allProcessIds.Count)"