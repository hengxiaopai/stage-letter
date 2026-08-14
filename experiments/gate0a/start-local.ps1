$ErrorActionPreference = 'Stop'

if (-not $env:TIKHUB_API_KEY) {
  $secure = Read-Host 'Enter TIKHUB_API_KEY (input hidden)' -AsSecureString
  $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try {
    $env:TIKHUB_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
  }
  finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
  }
}

if (-not $env:STAGE_LETTER_GATE0A_HOST) { $env:STAGE_LETTER_GATE0A_HOST = '127.0.0.1' }
if (-not $env:STAGE_LETTER_GATE0A_PORT) { $env:STAGE_LETTER_GATE0A_PORT = '8765' }

Write-Host "Starting Stage Letter Gate 0A local proxy on http://$($env:STAGE_LETTER_GATE0A_HOST):$($env:STAGE_LETTER_GATE0A_PORT)"
Write-Host 'The API key remains in this PowerShell process environment only.'
python "$PSScriptRoot/local_proxy.py"
