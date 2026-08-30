# Build and push the SCF Compliance Agent frontend container to ECR.
# Run from the frontend/ directory.
#
# Bootstrap (first time): the ECR repo must exist before this runs and before
# the App Runner service is created:
#   cd ..\terraform
#   terraform apply -target=aws_ecr_repository.frontend
#   cd ..\frontend
#   .\build-and-push.ps1
#   cd ..\terraform
#   terraform apply
#
# After that, App Runner auto-deploys on every push to :latest.

param(
    [string]$Region = "us-east-1",
    [string]$Tag = "latest"
)

$ErrorActionPreference = "Stop"

Push-Location ..\terraform
$ECR_URL = terraform output -raw frontend_ecr_repository_url
$ACCOUNT_ID = (aws sts get-caller-identity --query Account --output text)
Pop-Location

Write-Host "ECR Repository: $ECR_URL"
Write-Host "Account ID: $ACCOUNT_ID"
Write-Host "Region: $Region"

Write-Host "`nAuthenticating Docker with ECR..."
aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$Region.amazonaws.com"

# App Runner runs linux/amd64.
Write-Host "`nBuilding container image (linux/amd64)..."
docker build --platform linux/amd64 -t "${ECR_URL}:${Tag}" .

Write-Host "`nPushing to ECR..."
docker push "${ECR_URL}:${Tag}"

Write-Host "`nDone! Image pushed to: ${ECR_URL}:${Tag}"
Write-Host "If the App Runner service already exists, it will auto-deploy this image."
