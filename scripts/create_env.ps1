$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Example = Join-Path $Root '.env.example'
$Target = Join-Path $Root '.env'
if (Test-Path $Target) { throw '.env уже существует. Не перезаписываю, чтобы не потерять секреты.' }
$Token = Read-Host 'Вставь токен Telegram-бота от BotFather'
$Admin = Read-Host 'Твой Telegram ID (число; можно несколько через запятую)'
if ([string]::IsNullOrWhiteSpace($Token) -or [string]::IsNullOrWhiteSpace($Admin)) { throw 'BOT_TOKEN и ADMINS обязательны.' }
function New-Secret { $bytes = New-Object byte[] 32; $rng = [Security.Cryptography.RandomNumberGenerator]::Create(); $rng.GetBytes($bytes); return ([BitConverter]::ToString($bytes) -replace '-', '').ToLower() }
$Text = [System.IO.File]::ReadAllText($Example)
$Text = $Text.Replace('BOT_TOKEN=PASTE_TELEGRAM_BOT_TOKEN_HERE', "BOT_TOKEN=$Token")
$Text = $Text.Replace('ADMINS=123456789', "ADMINS=$Admin")
$PgPass = New-Secret
$Text = $Text.Replace('DB_URL=postgresql+asyncpg://cashback:CHANGE_ME@localhost:5432/cashback', "DB_URL=postgresql+asyncpg://cashback:$PgPass@localhost:5432/cashback")
$Text = $Text.Replace('HASH_SALT=GENERATE_64_HEX_CHARS', "HASH_SALT=$(New-Secret)")
$Text = $Text.Replace('PHONE_ENCRYPTION_KEY=GENERATE_64_HEX_CHARS_AND_BACKUP_IT', "PHONE_ENCRYPTION_KEY=$(New-Secret)")
$Text = $Text.Replace('POSTBACK_SECRET=GENERATE_64_HEX_CHARS', "POSTBACK_SECRET=$(New-Secret)")
$Text = $Text.Replace('POSTGRES_PASSWORD=GENERATE_64_HEX_CHARS', "POSTGRES_PASSWORD=$PgPass")
[System.IO.File]::WriteAllText($Target, $Text, [System.Text.UTF8Encoding]::new($false))
Write-Host '.env создан. Сделай резервную копию PHONE_ENCRYPTION_KEY и не отправляй .env в Git.' -ForegroundColor Green
