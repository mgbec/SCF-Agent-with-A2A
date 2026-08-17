"""
Retrieval Accuracy Evaluation

Tests that the agent's data retrieval tools return correct results.
Runs automatically — no manual review needed for pass/fail.

Usage:
    python eval_retrieval.py
    python eval_retrieval.py --verbose

Tests:
1. DynamoDB control lookup - exact match against source JSON
2. DynamoDB domain query - returns all controls in a domain
3. Approved answers keyword search - finds expected answers
4. End-to-end agent accuracy - agent response contains expected control IDs
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime

import boto3


REGION = "us-east-1"
CONTROLS_TABLE = "scf-agent-scf-controls"
ANSWERS_TABLE = "scf-agent-approved-answers"
SCF_JSON_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "SCF-2026-2", "JSON", "scf-full-2026.2.json"
)


def get_agent_arn():
    tf_dir = os.path.join(os.path.dirname(__file__), "..", "terraform")
    result = subprocess.run(
        ["terraform", "output", "-raw", "agent_runtime_arn"],
        cwd=tf_dir, capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


class EvalResults:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def ok(self, test_name):
        self.passed += 1
        print(f"  ✓ {test_name}")

    def fail(self, test_name, reason):
        self.failed += 1
        self.errors.append((test_name, reason))
        print(f"  ✗ {test_name}: {reason}")

    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*60}")
        print(f"EVALUATION RESULTS: {self.passed}/{total} passed")
        if self.errors:
            print(f"\nFailures:")
            for name, reason in self.errors:
                print(f"  ✗ {name}: {reason}")
        print(f"{'='*60}")
        return self.failed == 0


def test_dynamo_control_lookup(results, verbose=False):
    """Test that DynamoDB returns correct control data."""
    print("\n[1] DynamoDB Control Lookup Accuracy")

    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    table = dynamodb.Table(CONTROLS_TABLE)

    # Load source truth
    with open(SCF_JSON_PATH, "r", encoding="utf-8") as f:
        source = json.load(f)

    test_controls = ["GOV-01", "IAC-15", "CRY-05", "IRO-01", "AAT-01", "QTS-01"]

    for scf_id in test_controls:
        response = table.get_item(Key={"scf_id": scf_id})
        item = response.get("Item")

        if not item:
            results.fail(f"Lookup {scf_id}", "Not found in DynamoDB")
            continue

        # Find in source
        source_ctrl = next((c for c in source["controls"] if c["scf_id"] == scf_id), None)
        if not source_ctrl:
            results.fail(f"Lookup {scf_id}", "Not found in source JSON")
            continue

        # Verify key fields match
        if item.get("scf_control_name") != source_ctrl["scf_control_name"]:
            results.fail(f"Lookup {scf_id}", f"Name mismatch: {item.get('scf_control_name')} vs {source_ctrl['scf_control_name']}")
        elif item.get("description") != source_ctrl["description"]:
            results.fail(f"Lookup {scf_id}", "Description mismatch")
        elif item.get("weight") != source_ctrl["weight"]:
            results.fail(f"Lookup {scf_id}", f"Weight mismatch: {item.get('weight')} vs {source_ctrl['weight']}")
        else:
            results.ok(f"Lookup {scf_id} — name, description, weight all correct")


def test_dynamo_domain_query(results, verbose=False):
    """Test that domain queries return the right number of controls."""
    print("\n[2] DynamoDB Domain Query Accuracy")

    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    table = dynamodb.Table(CONTROLS_TABLE)

    # Load source truth for domain counts
    with open(SCF_JSON_PATH, "r", encoding="utf-8") as f:
        source = json.load(f)

    domain_counts = {d["identifier"]: d["control_count"] for d in source["domains"]}

    test_domains = ["GOV", "IAC", "CRY", "QTS"]

    for domain_id in test_domains:
        response = table.query(
            IndexName="domain-index",
            KeyConditionExpression=boto3.dynamodb.conditions.Key("domain_id").eq(domain_id),
            Select="COUNT",
        )
        actual_count = response.get("Count", 0)
        expected_count = domain_counts.get(domain_id, 0)

        if actual_count == expected_count:
            results.ok(f"Domain {domain_id}: {actual_count} controls (matches source)")
        else:
            results.fail(f"Domain {domain_id}", f"Got {actual_count}, expected {expected_count}")


def test_answers_keyword_search(results, verbose=False):
    """Test that the approved answers search finds expected results."""
    print("\n[3] Approved Answers Keyword Search")

    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    table = dynamodb.Table(ANSWERS_TABLE)

    test_queries = [
        {"query": "risk assessment", "should_match": "risk assessment"},
        {"query": "encryption at rest", "should_match": "encrypt"},
        {"query": "incident response", "should_match": "incident"},
        {"query": "access control authentication", "should_match": "access"},
        {"query": "vendor third party", "should_match": "vendor"},
    ]

    response = table.scan(Limit=100)
    all_items = response.get("Items", [])

    if not all_items:
        results.fail("Answers DB", "Table is empty — no answers to search")
        return

    for test in test_queries:
        query = test["query"]
        keywords = [w.lower() for w in query.split() if len(w) > 3]

        matches = []
        for item in all_items:
            q_text = (item.get("question_text", "") or "").lower()
            a_text = (item.get("answer_text", "") or "").lower()
            searchable = f"{q_text} {a_text}"

            score = sum(1 for kw in keywords if kw in searchable)
            if score >= max(1, len(keywords) // 3):
                matches.append(item)

        if matches:
            # Verify the match contains expected content
            found_expected = any(
                test["should_match"] in (m.get("question_text", "") or "").lower() or
                test["should_match"] in (m.get("answer_text", "") or "").lower()
                for m in matches
            )
            if found_expected:
                results.ok(f"Search '{query}' → {len(matches)} results, contains '{test['should_match']}'")
            else:
                results.fail(f"Search '{query}'", f"Got {len(matches)} results but none contain '{test['should_match']}'")
        else:
            results.fail(f"Search '{query}'", "No matches found")


def test_agent_end_to_end(results, verbose=False):
    """Test that the agent returns responses grounded in actual data."""
    print("\n[4] End-to-End Agent Accuracy")

    arn = get_agent_arn()
    if not arn:
        results.fail("Agent E2E", "Could not get agent ARN from terraform")
        return

    test_cases = [
        {
            "prompt": "Look up SCF control GOV-01. Just give me the control name and weight.",
            "must_contain": ["Security, Compliance & Resilience Program", "10"],
            "must_not_contain": ["I don't have", "no data"],
        },
        {
            "prompt": "What is the conformity cadence for IAC-15?",
            "must_contain": ["Account Management"],
            "must_not_contain": ["unable to find", "no information"],
        },
    ]

    for tc in test_cases:
        payload_b64 = base64.b64encode(
            json.dumps({"prompt": tc["prompt"], "session_id": "eval"}).encode()
        ).decode()

        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            result = subprocess.run(
                ["aws", "bedrock-agentcore", "invoke-agent-runtime",
                 "--agent-runtime-arn", arn,
                 "--payload", payload_b64,
                 "--region", REGION, tmp_path],
                capture_output=True, text=True, timeout=120,
            )

            if result.returncode != 0:
                results.fail(f"Agent: {tc['prompt'][:40]}", f"CLI error: {result.stderr[:100]}")
                continue

            if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                with open(tmp_path, "r", encoding="utf-8") as f:
                    content = f.read()
                try:
                    data = json.loads(content)
                    response_text = data.get("response", content)
                except json.JSONDecodeError:
                    response_text = content
            else:
                results.fail(f"Agent: {tc['prompt'][:40]}", "No response file")
                continue

            # Check must_contain
            missing = [term for term in tc["must_contain"] if term.lower() not in response_text.lower()]
            # Check must_not_contain
            found_bad = [term for term in tc["must_not_contain"] if term.lower() in response_text.lower()]

            if missing:
                results.fail(f"Agent: {tc['prompt'][:40]}", f"Missing expected terms: {missing}")
            elif found_bad:
                results.fail(f"Agent: {tc['prompt'][:40]}", f"Contains unwanted terms: {found_bad}")
            else:
                results.ok(f"Agent: {tc['prompt'][:40]}... — response contains expected data")

            if verbose:
                print(f"    Response preview: {response_text[:200]}")

        except subprocess.TimeoutExpired:
            results.fail(f"Agent: {tc['prompt'][:40]}", "Timeout (120s)")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(description="Evaluate retrieval accuracy")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--skip-agent", action="store_true", help="Skip slow agent E2E tests")
    args = parser.parse_args()

    print("=" * 60)
    print("SCF Compliance Agent - Retrieval Accuracy Evaluation")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    results = EvalResults()

    test_dynamo_control_lookup(results, args.verbose)
    test_dynamo_domain_query(results, args.verbose)
    test_answers_keyword_search(results, args.verbose)

    if not args.skip_agent:
        test_agent_end_to_end(results, args.verbose)
    else:
        print("\n[4] Agent E2E — SKIPPED")

    passed = results.summary()
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
