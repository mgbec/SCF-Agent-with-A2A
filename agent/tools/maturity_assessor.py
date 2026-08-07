"""
Maturity Assessment Tools

Provides SCR-CMM (Security, Compliance & Resilience Capability Maturity Model)
assessment capabilities across Levels 0-5.
"""

import json
import logging
from strands import tool

from tools.scf_lookup import _load_scf_data, _get_controls_index

logger = logging.getLogger(__name__)

CMM_LEVELS = {
    0: "Not Performed",
    1: "Performed Informally",
    2: "Planned & Tracked",
    3: "Well Defined",
    4: "Quantitatively Controlled",
    5: "Continuously Improving",
}

CMM_LEVEL_KEYS = {
    0: "SCR-CMM Level 0 Not Performed",
    1: "SCR-CMM Level 1 Performed Informally",
    2: "SCR-CMM Level 2 Planned & Tracked",
    3: "SCR-CMM Level 3 Well Defined",
    4: "SCR-CMM Level 4 Quantitatively Controlled",
    5: "SCR-CMM Level 5 Continuously Improving",
}


@tool
def get_maturity_criteria(control_id: str, target_level: int = 3) -> str:
    """
    Get the SCR-CMM maturity criteria for a specific control at a target level.

    Args:
        control_id: SCF control ID (e.g., 'GOV-01', 'IAC-15')
        target_level: Target maturity level 0-5 (default 3 = Well Defined)

    Returns:
        Detailed maturity criteria text for the control at the specified level,
        plus criteria for levels below to show progression path
    """
    control_id = control_id.upper().strip()
    target_level = max(0, min(5, target_level))

    index = _get_controls_index()
    control = index.get(control_id)
    if not control:
        return json.dumps({"error": f"Control '{control_id}' not found"})

    cmm_levels = control.get("cmm_levels", {})
    if not cmm_levels:
        return json.dumps({"error": f"No maturity criteria available for '{control_id}'"})

    # Build the maturity progression
    progression = {}
    for level in range(0, target_level + 1):
        key = CMM_LEVEL_KEYS.get(level, "")
        criteria = cmm_levels.get(key, "Not defined for this control")
        progression[f"Level {level} - {CMM_LEVELS[level]}"] = criteria

    return json.dumps({
        "scf_id": control_id,
        "control_name": control["scf_control_name"],
        "domain": control["scf_domain"],
        "target_level": target_level,
        "target_level_name": CMM_LEVELS[target_level],
        "maturity_progression": progression,
    }, indent=2)


@tool
def assess_maturity(
    domain: str,
    current_capabilities: str,
    target_level: int = 3,
) -> str:
    """
    Assess organizational maturity for an SCF domain and provide gap guidance.

    Args:
        domain: SCF domain identifier (e.g., 'GOV', 'IAC', 'NET', 'AAT')
        current_capabilities: Description of the organization's current capabilities,
                             processes, and controls for this domain
        target_level: Target SCR-CMM maturity level 0-5 (default 3)

    Returns:
        Assessment results with estimated current level, gaps to target, and
        remediation recommendations
    """
    domain = domain.upper().strip()
    target_level = max(0, min(5, target_level))
    data = _load_scf_data()

    # Get all controls for this domain
    domain_controls = [
        ctrl for ctrl in data["controls"]
        if ctrl["scf_id"].startswith(f"{domain}-")
    ]

    if not domain_controls:
        available = list(set(
            ctrl["scf_id"].split("-")[0] for ctrl in data["controls"]
        ))
        return json.dumps({
            "error": f"Domain '{domain}' not found",
            "available_domains": sorted(available),
        })

    # Get the domain info
    domain_info = next(
        (d for d in data["domains"] if d["identifier"] == domain), None
    )

    # Build assessment context
    key_controls = []
    for ctrl in domain_controls[:15]:  # Top controls by weight
        cmm = ctrl.get("cmm_levels", {})
        target_key = CMM_LEVEL_KEYS.get(target_level, "")
        key_controls.append({
            "scf_id": ctrl["scf_id"],
            "control_name": ctrl["scf_control_name"],
            "weight": ctrl["weight"],
            "target_criteria_preview": cmm.get(target_key, "")[:300],
        })

    return json.dumps({
        "domain": domain,
        "domain_name": domain_info["name"] if domain_info else domain,
        "domain_principles": domain_info["principles"] if domain_info else "",
        "total_controls_in_domain": len(domain_controls),
        "target_maturity_level": target_level,
        "target_level_name": CMM_LEVELS[target_level],
        "current_capabilities_provided": current_capabilities[:500],
        "key_controls_for_assessment": key_controls,
        "assessment_guidance": (
            f"To achieve Level {target_level} ({CMM_LEVELS[target_level]}), "
            f"the organization needs to demonstrate the criteria described in "
            f"each control's Level {target_level} definition. Review the "
            f"key_controls_for_assessment and compare against the provided "
            f"current_capabilities to identify specific gaps."
        ),
        "maturity_scale": CMM_LEVELS,
    }, indent=2)
