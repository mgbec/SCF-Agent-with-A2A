# Update the AgentCore runtime to pick up a freshly pushed ECR image.
#
# The runtime's container_uri is pinned to a mutable tag (":latest"), so
# `terraform apply` does NOT detect a new image push. This script forces the
# runtime to re-pull by calling the bedrock-agentcore-control update API.
#
# Strategy: read the CURRENT runtime config (get-agent-runtime), swap ONLY the
# container image URI, and send the full config back (update-agent-runtime).
# Reading-then-writing means the update always matches whatever Terraform
# provisioned (role, network mode, protocol, env vars) - we don't reconstruct
# it by hand and risk drift.
#
# All identifiers are read from Terraform outputs / the AWS CLI at runtime.
# Nothing (account IDs, ARNs, ECR URLs) is hardcoded.
#
# Usage (from the agent/ directory, after build-and-push.ps1):
#   .\update-runtime.ps1
#   .\update-runtime.ps1 -Region us-west-2 -Tag latest
#   .\update-runtime.ps1 -ImageUri 123456789012.dkr.ecr.us-east-1.amazonaws.com/repo@sha256:...
#   .\update-runtime.ps1 -DryRun          # print the assembled payload; do NOT update
#
# Tip: run once with -DryRun to eyeball the payload (especially the field names
# read back from get-agent-runtime) before performing the real update.

param(
    [string]$Region = "us-east-1",
    [string]$Tag    = "latest",
    # Optional explicit image URI (tag or digest). If omitted, uses "<ecr_url>:<Tag>".
    [string]$ImageUri = "",
    [string]$TerraformDir = "..\terraform",
    # Print the assembled update payload and exit without calling update-agent-runtime.
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$env:AWS_PAGER = ""   # disable the CLI pager so output is captured cleanly

# Invoke the AWS CLI robustly. PowerShell with $ErrorActionPreference="Stop"
# turns ANY native-command stderr write into a terminating NativeCommandError,
# but the AWS CLI writes to stderr even on success. So we redirect stdout/stderr
# to separate temp files and decide success from the EXIT CODE only.
# Returns: @{ ExitCode = <int>; StdOut = <string>; StdErr = <string> }
function Invoke-Aws([string[]]$AwsArgs) {
    $outFile = [System.IO.Path]::GetTempFileName()
    $errFile = [System.IO.Path]::GetTempFileName()
    try {
        $p = Start-Process -FilePath "aws" -ArgumentList $AwsArgs -NoNewWindow -Wait -PassThru `
            -RedirectStandardOutput $outFile -RedirectStandardError $errFile
        return @{
            ExitCode = $p.ExitCode
            StdOut   = (Get-Content $outFile -Raw)
            StdErr   = (Get-Content $errFile -Raw)
        }
    }
    finally {
        Remove-Item $outFile, $errFile -ErrorAction SilentlyContinue
    }
}

# Write text as UTF-8 WITHOUT a byte order mark. Windows PowerShell 5.x's
# `Set-Content -Encoding UTF8` prepends a BOM (EF BB BF), which the AWS CLI's
# file:// reader rejects ("Expected: '=', received: '<BOM>'"). This writes clean
# UTF-8 on both PowerShell 5.x and 7+.
function Write-JsonNoBom([string]$Path, [string]$Content) {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

function Get-TfOutput([string]$Key) {
    Push-Location $TerraformDir
    try {
        $val = terraform output -raw $Key 2>$null
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($val)) {
            throw "Could not read terraform output '$Key'. Run 'terraform apply' first."
        }
        return $val.Trim()
    }
    finally {
        Pop-Location
    }
}

# --- Resolve identifiers from Terraform -----------------------------------
Write-Host "Reading identifiers from Terraform outputs..."
$runtimeId = Get-TfOutput "agent_runtime_id"

if ([string]::IsNullOrWhiteSpace($ImageUri)) {
    $ecrUrl   = Get-TfOutput "ecr_repository_url"
    $ImageUri = "${ecrUrl}:${Tag}"
}

Write-Host "Runtime ID : $runtimeId"
Write-Host "Region     : $Region"
Write-Host "New image  : $ImageUri"

# --- Read the current runtime configuration -------------------------------
Write-Host "`nFetching current runtime configuration..."
$get = Invoke-Aws @(
    "bedrock-agentcore-control", "get-agent-runtime",
    "--agent-runtime-id", $runtimeId,
    "--region", $Region
)

if ($get.ExitCode -ne 0) {
    Write-Error "get-agent-runtime failed (exit $($get.ExitCode)):`n$($get.StdErr)"
    exit 1
}

$current = $get.StdOut | ConvertFrom-Json

# --- Build the update payload from the current config ---------------------
# Required by update-agent-runtime: agent-runtime-id, agent-runtime-artifact,
# role-arn, network-configuration. We carry protocol-configuration and
# environment variables through too, so nothing provisioned by Terraform is lost.

$roleArn = $current.roleArn
if ([string]::IsNullOrWhiteSpace($roleArn)) { throw "Current runtime has no roleArn - aborting." }

# Show the image currently deployed (helps confirm the swap is doing something).
$currentImage = $current.agentRuntimeArtifact.containerConfiguration.containerUri
if ([string]::IsNullOrWhiteSpace($currentImage)) { $currentImage = "(none / unknown)" }
Write-Host "Current image : $currentImage"

# Swap only the image URI inside the artifact block.
$artifact = @{
    containerConfiguration = @{
        containerUri = $ImageUri
    }
}

$networkConfig = $current.networkConfiguration
if ($null -eq $networkConfig) {
    # Fall back to the project default if the API omitted it.
    $networkConfig = @{ networkMode = "PUBLIC" }
}

# --- Write JSON args to temp files (PowerShell mangles inline JSON) --------
$artifactFile = [System.IO.Path]::GetTempFileName()
$networkFile  = [System.IO.Path]::GetTempFileName()
$protocolFile = $null
$envFile      = $null

$cliArgs = @(
    "bedrock-agentcore-control", "update-agent-runtime",
    "--agent-runtime-id", $runtimeId,
    "--role-arn", $roleArn,
    "--agent-runtime-artifact", "file://$artifactFile",
    "--network-configuration", "file://$networkFile",
    "--region", $Region
)

try {
    Write-JsonNoBom $artifactFile ($artifact     | ConvertTo-Json -Depth 10)
    Write-JsonNoBom $networkFile  ($networkConfig | ConvertTo-Json -Depth 10)

    # Preserve protocol configuration if the current runtime has one.
    if ($null -ne $current.protocolConfiguration) {
        $protocolFile = [System.IO.Path]::GetTempFileName()
        Write-JsonNoBom $protocolFile ($current.protocolConfiguration | ConvertTo-Json -Depth 10)
        $cliArgs += @("--protocol-configuration", "file://$protocolFile")
    }

    # Preserve environment variables if present.
    if ($null -ne $current.environmentVariables) {
        $envFile = [System.IO.Path]::GetTempFileName()
        Write-JsonNoBom $envFile ($current.environmentVariables | ConvertTo-Json -Depth 10)
        $cliArgs += @("--environment-variables", "file://$envFile")
    }

    if ($DryRun) {
        Write-Host "`n=== DRY RUN - no update performed ===" -ForegroundColor Yellow
        Write-Host "Image swap : $currentImage  ->  $ImageUri"
        Write-Host "`n--agent-runtime-artifact:"
        Write-Host (Get-Content $artifactFile -Raw)
        Write-Host "--network-configuration:"
        Write-Host (Get-Content $networkFile -Raw)
        if ($protocolFile) {
            Write-Host "--protocol-configuration:"
            Write-Host (Get-Content $protocolFile -Raw)
        } else {
            Write-Host "--protocol-configuration: (not present on current runtime; omitted)"
        }
        if ($envFile) {
            Write-Host "--environment-variables:"
            Write-Host (Get-Content $envFile -Raw)
        } else {
            Write-Host "--environment-variables: (not present on current runtime; omitted)"
        }
        Write-Host "`nCommand that WOULD run (JSON args via temp files):"
        Write-Host ("  aws " + ($cliArgs -join " "))
        Write-Host "`nRe-run without -DryRun to apply." -ForegroundColor Yellow
        return
    }

    Write-Host "`nUpdating runtime to the new image..."
    $upd = Invoke-Aws $cliArgs

    if ($upd.ExitCode -ne 0) {
        Write-Error "update-agent-runtime failed (exit $($upd.ExitCode)):`n$($upd.StdErr)"
        exit 1
    }

    if ($upd.StdOut) { Write-Host $upd.StdOut }
    Write-Host "`nUpdate accepted. New sessions will use: $ImageUri"
    Write-Host "Existing idle sessions roll over per idle_runtime_session_timeout (300s)."
    Write-Host "`nVerify with:"
    Write-Host "  cd scripts; python test_agent.py"
}
finally {
    foreach ($f in @($artifactFile, $networkFile, $protocolFile, $envFile)) {
        if ($f -and (Test-Path $f)) { Remove-Item $f -ErrorAction SilentlyContinue }
    }
}

