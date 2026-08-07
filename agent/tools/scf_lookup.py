"""
SCF Control Lookup Tools

Provides direct access to SCF 2026.2 controls by ID, domain, and search.
Uses the SCF JSON loaded into S3 / Bedrock Knowledge Base.
"""

import json
import logging
import os
from functools import lru_cache
from typing import Optional

import boto3
from strands import tool

logger = logging.getLogger(__name__)

# Cache the SCF data in memory after first load
_scf_data: Optional[dict] = None


def _load_scf_data() -> dict:
    """Load SCF JSON from S3 bucket."""
    global _scf_data
    if _scf_data is not None:
        return _scf_data

    bucket = os.environ.get("SCF_DATA_BUCKET")
    if not bucket:
        raise RuntimeError("SCF_DATA_BUCKET environment variable not set")

    s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))

    try:
        response = s3.get_object(Bucket=bucket, Key="scf-full-2026.2.json")
        _scf_data = json.loads(response["Body"].read().decode("utf-8"))
        logger.info(f"Loaded SCF data: {_scf_data['metadata']['control_count']} controls, "
                    f"{_scf_data['metadata']['domain_count']} domains")
        return _scf_data
    except Exception as e:
        logger.error(f"Failed to load SCF data from S3: {e}")
        raise


def _get_controls_index() -> dict:
    """Build an index of controls by scf_id for fast lookup."""
    data = _load_scf_data()
    return {ctrl["scf_id"]: ctrl for ctrl in data["controls"]}


@tool
def scf_control_lookup(control_id: str) -> str:
    """
    Look up a specific SCF control by its ID.

    Args:
        control_id: The SCF control identifier (e.g., 'GOV-01', 'IAC-15.10', 'AAT-01.5')

    Returns:
        Complete control details including description, maturity criteria, mappings, and guidance
    """
    control_id = control_id.upper().strip()
    index = _get_controls_index()

    control = index.get(control_id)
    if not control:
        # Try partial match
        matches = [k for k in index.keys() if control_id in k]
        if matches:
            return json.dumps({
                "error": f"Control '{control_id}' not found. Did you mean: {matches[:5]}?"
            }, indent=2)
        return json.dumps({"error": f"Control '{control_id}' not found in SCF 2026.2"})

    # Format the response with key fields
    result = {
        "scf_id": control["scf_id"],
        "domain": control["scf_domain"],
        "control_name": control["scf_control_name"],
        "description": control["description"],
        "control_question": control["control_question"],
        "conformity_cadence": control["conformity_cadence"],
        "weight": control["weight"],
        "pptdf_applicability": control["pptdf_applicability"],
        "nist_csf_function": control["nist_csf_function_grouping"],
        "maturity_levels": control.get("cmm_levels", {}),
        "key_mappings": _extract_key_mappings(control.get("mappings", {})),
        "risk_threats": control.get("mappings", {}).get("Risk Threat Summary", ""),
        "solutions": _extract_solutions(control.get("extra", {})),
    }

    return json.dumps(result, indent=2)


def _extract_key_mappings(mappings: dict) -> dict:
    """Extract the most commonly referenced framework mappings."""
    key_frameworks = [
        "NIST 800-53 R5", "NIST CSF 2.0", "NIST 800-171 R3",
        "ISO 27001 2022", "ISO 27002 2022",
        "PCI DSS 4.0.1", "US HIPAA Security Rule / NIST SP 800-66 R2",
        "EMEA EU NIS2 2022", "EMEA EU DORA 2023", "EMEA EU AI Act",
    ]
    return {k: v for k, v in mappings.items() if k in key_frameworks and v}


def _extract_solutions(extra: dict) -> dict:
    """Extract possible solutions by org size."""
    solutions = {}
    for key, value in extra.items():
        if "Possible Solutions" in key:
            # Simplify the key
            if "Micro-Small" in key:
                solutions["micro_small"] = value
            elif "Small Business" in key:
                solutions["small"] = value
            elif "Medium" in key:
                solutions["medium"] = value
            elif "Large" in key:
                solutions["large"] = value
            elif "Enterprise" in key:
                solutions["enterprise"] = value
    return solutions


@tool
def scf_domain_list() -> str:
    """
    List all 34 SCF domains with their identifiers, principles, and control counts.

    Returns:
        Complete list of SCF 2026.2 domains
    """
    data = _load_scf_data()
    domains = []
    for d in data["domains"]:
        domains.append({
            "number": d["number"],
            "identifier": d["identifier"],
            "name": d["name"],
            "principles": d["principles"],
            "control_count": d["control_count"],
        })
    return json.dumps({"total_domains": len(domains), "domains": domains}, indent=2)


@tool
def scf_search(query: str, domain: str = "", limit: int = 10) -> str:
    """
    Search SCF controls by keyword in name, description, or control question.

    Args:
        query: Search term(s) to find in control names, descriptions, and questions
        domain: Optional domain identifier to filter results (e.g., 'GOV', 'IAC', 'NET')
        limit: Maximum number of results to return (default 10)

    Returns:
        List of matching controls with key details
    """
    data = _load_scf_data()
    query_lower = query.lower()
    domain_upper = domain.upper().strip() if domain else ""

    results = []
    for ctrl in data["controls"]:
        # Apply domain filter
        if domain_upper:
            ctrl_domain = ctrl["scf_id"].split("-")[0]
            if ctrl_domain != domain_upper:
                continue

        # Search in key fields
        searchable = " ".join([
            ctrl.get("scf_control_name", ""),
            ctrl.get("description", ""),
            ctrl.get("control_question", ""),
        ]).lower()

        if query_lower in searchable:
            results.append({
                "scf_id": ctrl["scf_id"],
                "control_name": ctrl["scf_control_name"],
                "description": ctrl["description"][:200],
                "domain": ctrl["scf_domain"],
                "weight": ctrl["weight"],
            })

        if len(results) >= limit:
            break

    return json.dumps({
        "query": query,
        "domain_filter": domain_upper or "all",
        "result_count": len(results),
        "results": results,
    }, indent=2)
