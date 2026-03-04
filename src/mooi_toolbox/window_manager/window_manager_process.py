import psutil
import subprocess
import ctypes

ps_command=r"C:\Users\stefan\powershell_scripts\powersh_launch_example.ps1"

proc = subprocess.Popen(
    ["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File",ps_command],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)

std_st_out = proc.stdout.readline()  # The ID number
ps_pid = int(std_st_out.strip())
print(f"Python process ID: {ps_pid}")
py_pid = proc.pid
print(f"PowerShell PID: {py_pid}")

child_processes = psutil.Process(ps_pid).children(recursive=True)

print(f"Child processes found: {child_processes}")

p_es = [p for p in psutil.process_iter(['pid', 'name']) if 'python' in p.info['name'].lower()]

print(f"Found {len(p_es)} processes")
#print(p)

for p in p_es:
    
    #print(f"Name: {p.name} found")
    child_processes = psutil.Process(ps_pid).children(recursive=True)

    if child_processes:
        print(f"Children of {p.name}: ")
        print(child_processes)


