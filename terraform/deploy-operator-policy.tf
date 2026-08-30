################################################################################
# Deploy Operator Policy
#
# Least-privilege IAM policy for the human/CI principal that DEPLOYS the agent:
# building/pushing the container and rolling the runtime onto the new image via
# scripts/update-runtime.ps1 (get-agent-runtime + update-agent-runtime).
#
# This is a MANAGED POLICY only — it is not attached to anyone. Attach it to the
# IAM user or role that runs the deploy scripts:
#
#   aws iam attach-user-policy  --user-name <you>  --policy-arn <deploy_operator_policy_arn>
#   # or
#   aws iam attach-role-policy  --role-name <role> --policy-arn <deploy_operator_policy_arn>
#
# It is deliberately separate from the runtime's own execution role
# (aws_iam_role.agentcore_runtime) — that role is what the agent assumes at run
# time; this policy is what the operator needs to push the image and reconfigure
# the runtime.
################################################################################

resource "aws_iam_policy" "deploy_operator" {
  name        = "${local.name_prefix}-deploy-operator"
  description = "Permissions to build/push the agent image and roll the AgentCore runtime onto it"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Read + update the specific compliance-agent runtime. update-runtime.ps1
        # calls GetAgentRuntime (read config) then UpdateAgentRuntime (swap image).
        Sid    = "ManageComplianceAgentRuntime"
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:GetAgentRuntime",
          "bedrock-agentcore:UpdateAgentRuntime",
          "bedrock-agentcore:ListAgentRuntimes"
        ]
        Resource = [
          aws_bedrockagentcore_agent_runtime.compliance_agent.agent_runtime_arn,
          "${aws_bedrockagentcore_agent_runtime.compliance_agent.agent_runtime_arn}/*"
        ]
      },
      {
        # UpdateAgentRuntime passes the runtime's execution role back to the
        # service, so the operator needs PassRole for exactly that role.
        Sid      = "PassRuntimeExecutionRole"
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = aws_iam_role.agentcore_runtime.arn
        Condition = {
          StringEquals = {
            "iam:PassedToService" = "bedrock-agentcore.amazonaws.com"
          }
        }
      },
      {
        # Authenticate to ECR and push the freshly built image.
        Sid      = "EcrAuth"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "EcrPushPull"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:CompleteLayerUpload",
          "ecr:InitiateLayerUpload",
          "ecr:PutImage",
          "ecr:UploadLayerPart",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer"
        ]
        Resource = aws_ecr_repository.agent.arn
      },
      {
        # sts:GetCallerIdentity is used by build-and-push.ps1 to resolve the
        # account ID for the ECR registry login.
        Sid      = "StsIdentity"
        Effect   = "Allow"
        Action   = ["sts:GetCallerIdentity"]
        Resource = "*"
      }
    ]
  })

  tags = {
    Component = "deploy"
  }
}
