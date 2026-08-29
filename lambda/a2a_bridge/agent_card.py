"""
A2A Agent Card builder.

Produces a spec-compliant Agent2Agent (A2A) AgentCard describing the SCF
Compliance Assessment Agent. One card is built per auth "prefix" so that each
route advertises only the identity provider that guards it:

    prefix="cognito"  -> OAuth2 (Amazon Cognito): client_credentials + authorization_code
    prefix="entra"    -> OpenID Connect (Microsoft Entra ID)
    prefix=None       -> generic card listing both schemes (served at /.well-known/agent-card.json)

Values come from environment variables set by Terraform (see terraform/a2a.tf).
"""

import os

PROTOCOL_VERSION = "0.3.0"

AGENT_NAME = os.environ.get("AGENT_NAME", "SCF Compliance Assessment Agent")
AGENT_VERSION = os.environ.get("AGENT_VERSION", "2026.2")
AGENT_DESCRIPTION = os.environ.get(
    "AGENT_DESCRIPTION",
    "AI-driven Secure Controls Framework (SCF) 2026.2 compliance assessment: "
    "control lookup, framework mapping, gap analysis, maturity assessment, "
    "evidence checklists, and questionnaire answers.",
)

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
COGNITO_TOKEN_URL = os.environ.get("COGNITO_TOKEN_URL", "")
COGNITO_AUTHORIZE_URL = os.environ.get("COGNITO_AUTHORIZE_URL", "")
COGNITO_SCOPE = os.environ.get("COGNITO_SCOPE", "")
ENTRA_TENANT_ID = os.environ.get("ENTRA_TENANT_ID", "")

SKILLS = [
    {
        "id": "gap-analysis",
        "name": "Gap analysis",
        "description": "Identify missing SCF controls against any target framework "
        "(HIPAA, NIST 800-53, ISO 27001, PCI DSS, EU NIS2, DORA, ...) and "
        "recommend compensating controls.",
        "tags": ["compliance", "gap-analysis", "frameworks"],
        "examples": [
            "Perform a HIPAA gap analysis for a 175-employee healthcare SaaS with controls GOV-01, IAC-15, NET-01 implemented.",
            "What controls are required for the SCF ESP Level 1 Foundational profile?",
        ],
    },
    {
        "id": "control-lookup",
        "name": "SCF control lookup",
        "description": "Return full untruncated data for an SCF control: SCR-CMM "
        "maturity criteria (Levels 0-5), framework mappings, and evidence requirements.",
        "tags": ["scf", "controls", "maturity", "evidence"],
        "examples": [
            "Look up SCF control IAC-15 and show the full maturity criteria for Levels 2 and 3.",
            "For the IAC domain, generate a SOC 2 Type II evidence request checklist.",
        ],
    },
    {
        "id": "framework-mapping",
        "name": "Framework mapping",
        "description": "Map between SCF controls and 252+ laws, regulations, and frameworks.",
        "tags": ["mapping", "frameworks", "regulations"],
        "examples": [
            "What SCF controls map to EU NIS2 requirements? Show the top 15 with article references.",
            "Map our existing HIPAA controls to EU NIS2 and flag what transfers directly.",
        ],
    },
    {
        "id": "questionnaire-answers",
        "name": "Questionnaire answers",
        "description": "Find and reuse approved historical questionnaire / security "
        "assessment responses, or draft a new answer from SCF controls.",
        "tags": ["questionnaire", "sig", "vendor-assessment", "soc2"],
        "examples": [
            "How do we answer the SIG question about data encryption at rest?",
            "What did we put for incident response in our last SOC 2 assessment?",
        ],
    },
]


def _cognito_security_scheme():
    scopes = {COGNITO_SCOPE: "Invoke the SCF Compliance Assessment Agent"} if COGNITO_SCOPE else {}
    flows = {}
    if COGNITO_TOKEN_URL:
        flows["clientCredentials"] = {"tokenUrl": COGNITO_TOKEN_URL, "scopes": scopes}
    if COGNITO_AUTHORIZE_URL and COGNITO_TOKEN_URL:
        flows["authorizationCode"] = {
            "authorizationUrl": COGNITO_AUTHORIZE_URL,
            "tokenUrl": COGNITO_TOKEN_URL,
            "scopes": {**scopes, "openid": "OpenID Connect", "email": "User email"},
        }
    return {
        "type": "oauth2",
        "description": "Amazon Cognito. Machine-to-machine callers use the "
        "client_credentials flow; interactive users use the authorization_code "
        "(hosted UI) flow. Send the access token as 'Authorization: Bearer <token>'.",
        "flows": flows,
    }


def _entra_security_scheme():
    tid = ENTRA_TENANT_ID or "common"
    return {
        "type": "openIdConnect",
        "description": "Microsoft Entra ID. Acquire a token for this API's app "
        "registration (client_credentials or on-behalf-of) and send it as "
        "'Authorization: Bearer <token>'.",
        "openIdConnectUrl": f"https://login.microsoftonline.com/{tid}/v2.0/.well-known/openid-configuration",
    }


def build_card(prefix: str | None) -> dict:
    """Return an A2A AgentCard dict for the given auth prefix ("cognito", "entra", or None)."""
    effective_prefix = prefix or "cognito"
    rpc_url = f"{PUBLIC_BASE_URL}/{effective_prefix}/rpc" if PUBLIC_BASE_URL else f"/{effective_prefix}/rpc"

    card = {
        "protocolVersion": PROTOCOL_VERSION,
        "name": AGENT_NAME,
        "description": AGENT_DESCRIPTION,
        "url": rpc_url,
        "preferredTransport": "JSONRPC",
        "version": AGENT_VERSION,
        "provider": {
            "organization": "SCF Compliance Agent",
            "url": "https://securecontrolsframework.com",
        },
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
            "stateTransitionHistory": True,
        },
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["text/plain"],
        "skills": SKILLS,
        "supportsAuthenticatedExtendedCard": False,
    }

    if prefix == "cognito":
        card["securitySchemes"] = {"cognito": _cognito_security_scheme()}
        card["security"] = [{"cognito": [COGNITO_SCOPE] if COGNITO_SCOPE else []}]
    elif prefix == "entra":
        card["securitySchemes"] = {"entra": _entra_security_scheme()}
        card["security"] = [{"entra": []}]
    else:
        card["securitySchemes"] = {
            "cognito": _cognito_security_scheme(),
            "entra": _entra_security_scheme(),
        }
        # Either scheme is sufficient (alternatives, not both required).
        card["security"] = [
            {"cognito": [COGNITO_SCOPE] if COGNITO_SCOPE else []},
            {"entra": []},
        ]
        if PUBLIC_BASE_URL:
            card["additionalInterfaces"] = [
                {"transport": "JSONRPC", "url": f"{PUBLIC_BASE_URL}/cognito/rpc"},
                {"transport": "JSONRPC", "url": f"{PUBLIC_BASE_URL}/entra/rpc"},
            ]

    return card
