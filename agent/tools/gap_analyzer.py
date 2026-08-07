"""
Gap Analysis Tools

Performs compliance gap analysis by comparing organizational posture against
target framework requirements, using SCF as the normalization layer.
"""

import json
import logging
from strands import tool

from tools.scf_lookup import _load_scf_data, _get_controls_index

logger = logging.getLogger(__name__)


@tool
def gap_analysis(
    target_framework: str,
    implemented_controls: str,
    organization_size: str = "medium",
) -> str:
    """
    Perform a compliance gap analysis against a target framework.

    Args:
        target_framework: The compliance framework to assess against
                         (e.g., 'NIST 800-171 R3', 'HIPAA', 'PCI DSS', 'NIS2', 'ISO 27001')
        implemented_controls: Comma-separated list of SCF control IDs the organization
                            has implemented (e.g., 'GOV-01,GOV-02,IAC-01,IAC-15')
                            OR a text description of current security posture
        organization_size: Organization size for solution recommendations
                         ('micro_small', 'small', 'medium', 'large', 'enterprise')

    Returns:
        Gap analysis results showing required vs implemented controls,
        missing controls prioritized by weight, and remediation guidance
    """
    data = _load_scf_data()
    framework_lower = target_framework.lower()

    # Parse implemented controls
    if "," in implemented_controls:
        implemented_set = set(
            c.strip().upper() for c in implemented_controls.split(",")
        )
    else:
        # If it's a text description, treat as empty set (agent will interpret)
        implemented_set = set()

    # Find all controls that map to the target framework
    required_controls = []
    for ctrl in data["controls"]:
        mappings = ctrl.get("mappings", {})
        for key, value in mappings.items():
            if framework_lower in key.lower() and value:
                if key.startswith("Risk ") or key.startswith("Threat "):
                    continue
                required_controls.append({
                    "scf_id": ctrl["scf_id"],
                    "control_name": ctrl["scf_control_name"],
                    "description": ctrl["description"][:200],
                    "weight": int(ctrl.get("weight", "5")),
                    "framework_reference": value,
                    "pptdf": ctrl.get("pptdf_applicability", ""),
                    "cadence": ctrl.get("conformity_cadence", ""),
                })
                break

    # Sort by weight (highest priority first)
    required_controls.sort(key=lambda x: x["weight"], reverse=True)

    # Identify gaps
    required_ids = set(rc["scf_id"] for rc in required_controls)
    missing_ids = required_ids - implemented_set
    covered_ids = required_ids & implemented_set

    missing_controls = [
        rc for rc in required_controls if rc["scf_id"] in missing_ids
    ]

    # Get solutions for missing controls based on org size
    size_key_map = {
        "micro_small": "Possible Solutions & Considerations Micro-Small Business (<10 staff) BLS Firm Size Classes 1-2",
        "small": "Possible Solutions & Considerations Small Business (10-49 staff) BLS Firm Size Classes 3-4",
        "medium": "Possible Solutions & Considerations Medium Business (50-249 staff) BLS Firm Size Classes 5-6",
        "large": "Possible Solutions & Considerations Large Business (250-999 staff) BLS Firm Size Classes 7-8",
        "enterprise": "Possible Solutions & Considerations Enterprise (> 1,000 staff) BLS Firm Size Class 9",
    }
    size_key = size_key_map.get(organization_size, size_key_map["medium"])

    # Add remediation guidance for top gaps
    index = _get_controls_index()
    for mc in missing_controls[:10]:
        ctrl = index.get(mc["scf_id"])
        if ctrl:
            extra = ctrl.get("extra", {})
            mc["remediation_guidance"] = extra.get(size_key, "No specific guidance available")

    return json.dumps({
        "target_framework": target_framework,
        "organization_size": organization_size,
        "summary": {
            "total_required_controls": len(required_controls),
            "controls_implemented": len(covered_ids),
            "controls_missing": len(missing_ids),
            "compliance_percentage": round(
                len(covered_ids) / max(len(required_ids), 1) * 100, 1
            ),
        },
        "top_priority_gaps": missing_controls[:15],
        "implemented_controls": list(covered_ids)[:20],
    }, indent=2)


@tool
def compliance_scope(
    profile: str = "foundational",
    domain: str = "",
) -> str:
    """
    Get the set of SCF controls required for a given compliance profile.

    Args:
        profile: SCF profile to scope
                 ('foundational' = ESP Level 1, 'critical_infrastructure' = ESP Level 2,
                  'advanced_threats' = ESP Level 3, 'ai' = AI Model Deployment,
                  'mad' = Mergers Acquisitions & Divestitures)
        domain: Optional domain filter (e.g., 'GOV', 'IAC')

    Returns:
        List of in-scope controls for the profile with key metadata
    """
    data = _load_scf_data()
    domain_upper = domain.upper().strip() if domain else ""

    # Map profile to the extra field key
    profile_key_map = {
        "foundational": "SCF CORE ESP Level 1 Foundational",
        "critical_infrastructure": "SCF CORE ESP Level 2 Critical Infrastructure",
        "advanced_threats": "SCF CORE ESP Level 3 Advanced Threats",
        "ai": "SCF CORE AI Model Deployment",
        "mad": "SCF CORE Mergers, Acquisitions & Divestitures (MA&D)",
        "scrms": "SCF SCRMS",
    }

    profile_key = profile_key_map.get(profile.lower())
    if not profile_key:
        return json.dumps({
            "error": f"Unknown profile '{profile}'",
            "available_profiles": list(profile_key_map.keys()),
        })

    # Find controls that have this profile set
    in_scope = []
    for ctrl in data["controls"]:
        extra = ctrl.get("extra", {})
        if extra.get(profile_key):
            # Apply domain filter
            if domain_upper:
                ctrl_domain = ctrl["scf_id"].split("-")[0]
                if ctrl_domain != domain_upper:
                    continue

            in_scope.append({
                "scf_id": ctrl["scf_id"],
                "control_name": ctrl["scf_control_name"],
                "domain": ctrl["scf_domain"],
                "weight": ctrl["weight"],
                "pptdf": ctrl.get("pptdf_applicability", ""),
                "nist_csf_function": ctrl.get("nist_csf_function_grouping", ""),
            })

    # Sort by domain then weight
    in_scope.sort(key=lambda x: (x["domain"], -int(x.get("weight", "0"))))

    # Group by domain for summary
    domain_summary = {}
    for ctrl in in_scope:
        d = ctrl["scf_id"].split("-")[0]
        domain_summary[d] = domain_summary.get(d, 0) + 1

    return json.dumps({
        "profile": profile,
        "profile_key": profile_key,
        "domain_filter": domain_upper or "all",
        "total_in_scope_controls": len(in_scope),
        "controls_by_domain": domain_summary,
        "controls": in_scope[:50],  # Limit output size
    }, indent=2)
