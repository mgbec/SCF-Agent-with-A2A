# Build and push the SCF Compliance Agent container to ECR
# Run from the agent/ directory after terraform apply

param(
    [string]$Region = "us-east-1",
    [string]$Tag = "latest"
)

$ErrorActionPreference = "Stop"

# Get Terraform outputs
Push-Location ..\terraform
$ECR_URL = terraform output -raw ecr_repository_url
$ACCOUNT_ID = (aws sts get-caller-identity --query Account --output text)
Pop-Location

Write-Host "ECR Repository: $ECR_URL"
Write-Host "Account ID: $ACCOUNT_ID"
Write-Host "Region: $Region"

# Authenticate Docker with ECR
Write-Host "`nAuthenticating Docker with ECR..."
aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$Region.amazonaws.com"

# Build the container (ARM64 for AgentCore/Graviton)
Write-Host "`nBuilding container image..."
docker build --platform linux/arm64 -t "${ECR_URL}:${Tag}" .

# Push to ECR
Write-Host "`nPushing to ECR..."
docker push "${ECR_URL}:${Tag}"

Write-Host "`nDone! Image pushed to: ${ECR_URL}:${Tag}"
Write-Host "You may need to update the AgentCore runtime to pick up the new image."
