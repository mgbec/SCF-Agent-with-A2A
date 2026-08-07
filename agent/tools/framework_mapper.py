"""
Framework Mapping Tools

Maps between SCF controls and 252+ external laws, regulations, and frameworks.
Supports bidirectional mapping (SCF→framework and framework→SCF).
"""

import json
import logging
import os
from typing import Optional

import boto3
from strands import tool

logger = logging.getLogger(__name__)

# Import shared data loader
from tools.scf_lookup import _load_scf_data, _get_controls_index


# Key frameworks organized by category
FRAMEWORK_CATEGORIES = {
    "US Federal": [
        "NIST 800-53 R5", "NIST CSF 2.0", "NIST 800-171 R3",
        "NIST 800-171A R3", "NIST 800-82 R3", "US FedRAMP R5 (moderate)",
        "US FedRAMP R5 (high)", "US CJIS Security Policy 6.0",
        "US DFARS Cybersecurity 252.204-7012", "US FAR 52.204-21",
    ],
    "US Industry": [
        "AICPA TSC 2017:2022 (used for SOC 2)", "PCI DSS 4.0.1",
        "US HIPAA Security Rule / NIST SP 800-66 R2",
        "US HIPAA Administrative Simplification 2013",
        "US GLBA CFR 314 2023", "US SOX", "US NERC CIP 2024",
    ],
    "US State": [
        "US - CA CCPA 2025", "US - NY DFS 23 NYCRR500 2023 Amd 2",
        "US - TX DIR Control Standards 2.2",
    ],
    "EU/EMEA": [
        "EMEA EU NIS2 2022", "EMEA EU NIS2 Annex 2024",
        "EMEA EU DORA 2023", "EMEA EU AI Act",
        "EMEA EU EBA GL/2019/04", "EMEA EU PSD2 2015",
        "EMEA Saudi Arabia ECC-1 2018",
        "EMEA Germany C5 2020", "EMEA Spain Royal Decree 311 2022",
    ],
    "ISO Standards": [
        "ISO 27001 2022", "ISO 27002 2022", "ISO  27017 2015",
        "ISO  27018 2025", "ISO 27701  2025", "ISO 31000 2018",
        "ISO 42001 2023",
    ],
    "APAC": [
        "APAC Australia ISM March 2026", "APAC Australia Prudential Standard CPS234 2019",
        "APAC Singapore MAS TRM 2021", "APAC Japan ISMAP",
        "APAC Malaysia RMiT 2025", "APAC New Zealand NZISM 3.9",
        "APAC India SEBI CSCRF 2024",
    ],
    "Other Frameworks": [
        "CSA CCM 4.1.0", "COBIT 2019", "TISAX ISA 6.0.3",
        "IEC 62443-2-1 2024", "US C2M2 2.1", "SPARTA",
    ],
}


@tool
def list_frameworks(category: str = "") -> str:
    """
    List available compliance frameworks that SCF maps to.

    Args:
        category: Optional category filter (e.g., 'US Federal', 'EU/EMEA', 'ISO Standards', 'APAC')
                  Leave empty to see all categories.

    Returns:
        List of supported frameworks organized by category
    """
    if category:
        matching = {k: v for k, v in FRAMEWORK_CATEGORIES.items()
                    if category.lower() in k.lower()}
        if not matching:
            return json.dumps({
                "error": f"Category '{category}' not found",
                "available_categories": list(FRAMEWORK_CATEGORIES.keys()),
            })
        return json.dumps(matching, indent=2)

    return json.dumps({
        "total_frameworks": "252+",
        "categories": {k: len(v) for k, v in FRAMEWORK_CATEGORIES.items()},
        "frameworks_by_category": FRAMEWORK_CATEGORIES,
    }, indent=2)


@tool
def map_to_framework(framework_name: str, domain: str = "", limit: int = 20) -> str:
    """
    Find all SCF controls that map to a specific compliance framework.

    Args:
        framework_name: Name or partial name of the target framework (e.g., 'HIPAA', 'NIS2', 'PCI DSS')
        domain: Optional SCF domain filter (e.g., 'IAC', 'NET')
        limit: Maximum results to return (default 20)

    Returns:
        List of SCF controls with their mappings to the requested framework
    """
    data = _load_scf_data()
    framework_lower = framework_name.lower()
    domain_upper = domain.upper().strip() if domain else ""

    results = []
    framework_key_found = None

    for ctrl in data["controls"]:
        # Apply domain filter
        if domain_upper:
            ctrl_domain = ctrl["scf_id"].split("-")[0]
            if ctrl_domain != domain_upper:
                continue

        mappings = ctrl.get("mappings", {})

        # Find matching framework key (case-insensitive partial match)
        for key, value in mappings.items():
            if framework_lower in key.lower() and value:
                # Skip risk/threat entries
                if key.startswith("Risk ") or key.startswith("Threat "):
                    continue

                if not framework_key_found:
                    framework_key_found = key

                results.append({
                    "scf_id": ctrl["scf_id"],
                    "control_name": ctrl["scf_control_name"],
                    "framework": key,
                    "framework_references": value,
                    "weight": ctrl["weight"],
                })
                break

        if len(results) >= limit:
            break

    return json.dumps({
        "framework_query": framework_name,
        "framework_matched": framework_key_found or "none",
        "domain_filter": domain_upper or "all",
        "result_count": len(results),
        "mappings": results,
    }, indent=2)


@tool
def get_control_mappings(control_id: str) -> str:
    """
    Get all framework mappings for a specific SCF control.

    Args:
        control_id: SCF control ID (e.g., 'GOV-01', 'IAC-15')

    Returns:
        Complete list of all framework references for the given control
    """
    control_id = control_id.upper().strip()
    index = _get_controls_index()

    control = index.get(control_id)
    if not control:
        return json.dumps({"error": f"Control '{control_id}' not found"})

    mappings = control.get("mappings", {})

    # Separate into categories
    framework_mappings = {}
    risk_mappings = {}
    threat_mappings = {}

    for key, value in mappings.items():
        if not value:
            continue
        if key.startswith("Risk "):
            risk_mappings[key] = value
        elif key.startswith("Threat ") or key == "Control Threat Summary":
            threat_mappings[key] = value
        elif key == "Risk Threat Summary":
            risk_mappings[key] = value
        else:
            framework_mappings[key] = value

    return json.dumps({
        "scf_id": control_id,
        "control_name": control["scf_control_name"],
        "total_framework_mappings": len(framework_mappings),
        "framework_mappings": framework_mappings,
        "risk_summary": mappings.get("Risk Threat Summary", ""),
        "threat_summary": mappings.get("Control Threat Summary", ""),
    }, indent=2)
