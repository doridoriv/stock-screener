# register_task.ps1
# 장마감 후 백그라운드 자동 수집을 위한 Windows 작업 스케줄러 등록 스크립트

$PythonPath = "python.exe"
$ScriptPath = "D:\차트\백업\깃허브\02 새폴더\cron_job.py"
$WorkDir = "D:\차트\백업\깃허브\02 새폴더"

# 1. 실행할 동작(Action) 정의
# 큰따옴표가 포함된 문자열을 New-ScheduledTaskAction의 -Argument로 안전하게 넘기기 위해 PowerShell 이스케이프 사용
$Action = New-ScheduledTaskAction -Execute $PythonPath -Argument "`"$ScriptPath`"" -WorkingDirectory $WorkDir

# 2. 실행 시간(Trigger) 정의
# 트리거 1: 매일 오후 4:00 (한국 코스피/코스닥 장마감 반영)
$Trigger1 = New-ScheduledTaskTrigger -Daily -At 4:00PM

# 트리거 2: 매일 오전 7:00 (미국 주식 장마감 반영)
$Trigger2 = New-ScheduledTaskTrigger -Daily -At 7:00AM

# 3. 추가 실행 설정 (노트북 배터리 환경에서도 작동 지원 등)
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

$TaskName = "StockScreenerDailyUpdate"

# 4. 스케줄러 등록 진행 (기존 동일 작업이 존재할 경우 덮어씌움)
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger @($Trigger1, $Trigger2) -Settings $Settings -Description "장마감 후 한국 및 미국 주식 스크리너 자동 백그라운드 수집 데몬" -Force

Write-Host "========================================================="
Write-Host "Scheduled task '$TaskName' registered successfully!"
Write-Host "KR Market Trigger: Daily at 04:00 PM KST"
Write-Host "US Market Trigger: Daily at 07:00 AM KST"
Write-Host "========================================================="
