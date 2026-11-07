Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
  Where-Object { $_.CommandLine -like '*bot/api.py*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep 2
Start-Process -FilePath 'C:\Users\Tiger\AppData\Local\Programs\Python\Python312\pythonw.exe' -ArgumentList 'bot/api.py' -WorkingDirectory 'C:\Users\Tiger\.config\freebuff-desktop\local-projects\e7fb6b62-82b5-46cd-9a18-143f3e374fd2'
