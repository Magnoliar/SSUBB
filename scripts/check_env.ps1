# =============================================================================
# SSUBB 环境检查脚本 (Windows PowerShell)
# 用法: powershell -ExecutionPolicy Bypass -File scripts\check_env.ps1
# =============================================================================

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  SSUBB Environment Check" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

$errors = 0
$warnings = 0

# --- Python ---
Write-Host "[检查] Python..." -NoNewline
try {
    $pyVersion = python --version 2>&1
    if ($pyVersion -match "Python (\d+)\.(\d+)") {
        $major = [int]$Matches[1]
        $minor = [int]$Matches[2]
        if ($major -ge 3 -and $minor -ge 10) {
            Write-Host " OK ($pyVersion)" -ForegroundColor Green
        } else {
            Write-Host " WARN ($pyVersion, 建议 3.10+)" -ForegroundColor Yellow
            $warnings++
        }
    }
} catch {
    Write-Host " FAIL (未找到 Python)" -ForegroundColor Red
    $errors++
}

# --- pip ---
Write-Host "[检查] pip..." -NoNewline
try {
    $pipVersion = pip --version 2>&1
    Write-Host " OK" -ForegroundColor Green
} catch {
    Write-Host " FAIL (未找到 pip)" -ForegroundColor Red
    $errors++
}

# --- FFmpeg ---
Write-Host "[检查] FFmpeg..." -NoNewline
try {
    $ffmpegVersion = ffmpeg -version 2>&1 | Select-Object -First 1
    Write-Host " OK ($ffmpegVersion)" -ForegroundColor Green
} catch {
    Write-Host " FAIL (未找到 FFmpeg)" -ForegroundColor Red
    $errors++
}

# --- FFprobe ---
Write-Host "[检查] FFprobe..." -NoNewline
try {
    $null = ffprobe -version 2>&1
    Write-Host " OK" -ForegroundColor Green
} catch {
    Write-Host " FAIL (未找到 FFprobe)" -ForegroundColor Red
    $errors++
}

# --- CUDA ---
Write-Host "[检查] NVIDIA GPU (nvidia-smi)..." -NoNewline
try {
    $smiOutput = nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host " OK ($smiOutput)" -ForegroundColor Green
    } else {
        Write-Host " WARN (nvidia-smi 返回错误)" -ForegroundColor Yellow
        $warnings++
    }
} catch {
    Write-Host " SKIP (无 NVIDIA GPU 或未安装驱动)" -ForegroundColor Yellow
    $warnings++
}

# --- PyTorch CUDA ---
Write-Host "[检查] PyTorch CUDA 支持..." -NoNewline
try {
    $torchCuda = python -c "import torch; print(f'torch={torch.__version__}, cuda={torch.cuda.is_available()}, device={torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\"}')" 2>&1
    if ($torchCuda -match "cuda=True") {
        Write-Host " OK ($torchCuda)" -ForegroundColor Green
    } elseif ($torchCuda -match "cuda=False") {
        Write-Host " WARN (PyTorch 已安装但 CUDA 不可用: $torchCuda)" -ForegroundColor Yellow
        $warnings++
    } else {
        Write-Host " WARN ($torchCuda)" -ForegroundColor Yellow
        $warnings++
    }
} catch {
    Write-Host " SKIP (PyTorch 未安装)" -ForegroundColor Yellow
    $warnings++
}

# --- 关键 Python 包 ---
$packages = @("fastapi", "uvicorn", "httpx", "pydantic", "yaml", "openai", "json_repair")
foreach ($pkg in $packages) {
    Write-Host "[检查] Python 包: $pkg..." -NoNewline
    $importName = $pkg
    if ($pkg -eq "yaml") { $importName = "yaml" }
    try {
        $result = python -c "import $importName" 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host " OK" -ForegroundColor Green
        } else {
            Write-Host " MISSING" -ForegroundColor Red
            $errors++
        }
    } catch {
        Write-Host " MISSING" -ForegroundColor Red
        $errors++
    }
}

# --- Worker 专用包 ---
Write-Host ""
Write-Host "[检查] Worker 专用包: stable_whisper..." -NoNewline
try {
    $result = python -c "import stable_whisper" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host " OK" -ForegroundColor Green
    } else {
        Write-Host " MISSING (Worker 端需要)" -ForegroundColor Yellow
        $warnings++
    }
} catch {
    Write-Host " MISSING (Worker 端需要)" -ForegroundColor Yellow
    $warnings++
}

# --- 端口检查 ---
Write-Host ""
Write-Host "[检查] 端口 8787 (Coordinator)..." -NoNewline
$port8787 = Get-NetTCPConnection -LocalPort 8787 -ErrorAction SilentlyContinue
if ($port8787) {
    Write-Host " OCCUPIED (已被占用)" -ForegroundColor Yellow
    $warnings++
} else {
    Write-Host " FREE" -ForegroundColor Green
}

Write-Host "[检查] 端口 8788 (Worker)..." -NoNewline
$port8788 = Get-NetTCPConnection -LocalPort 8788 -ErrorAction SilentlyContinue
if ($port8788) {
    Write-Host " OCCUPIED (已被占用)" -ForegroundColor Yellow
    $warnings++
} else {
    Write-Host " FREE" -ForegroundColor Green
}

# --- 配置文件 ---
Write-Host ""
Write-Host "[检查] config.yaml..." -NoNewline
if (Test-Path "config.yaml") {
    Write-Host " OK (已存在)" -ForegroundColor Green
} else {
    Write-Host " MISSING (请从 config.example.yaml 复制)" -ForegroundColor Yellow
    $warnings++
}

# --- 结果汇总 ---
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
if ($errors -eq 0 -and $warnings -eq 0) {
    Write-Host "  全部检查通过!" -ForegroundColor Green
} elseif ($errors -eq 0) {
    Write-Host "  检查完成: $warnings 个警告" -ForegroundColor Yellow
} else {
    Write-Host "  检查完成: $errors 个错误, $warnings 个警告" -ForegroundColor Red
}
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
