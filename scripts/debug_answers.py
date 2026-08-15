"""Quick debug: test the answers search logic locally."""
import boto3

dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
table = dynamodb.Table("scf-agent-approved-answers")

# Scan all items
response = table.scan(Limit=100)
items = response["Items"]
print(f"Total items scanned: {len(items)}")
print()

# Test search
query = "risk assessment"
keywords = [w.lower() for w in query.split() if len(w) > 3]
print(f"Keywords: {keywords}")
print()

matches = []
for item in items:
    q_text = (item.get("question_text", "") or "").lower()
    a_text = (item.get("answer_text", "") or "").lower()
    tags = (item.get("tags", "") or "").lower()
    searchable = f"{q_text} {a_text} {tags}"

    score = sum(1 for kw in keywords if kw in searchable)
    threshold = max(1, len(keywords) // 3)
    
    if score > 0:
        print(f"  Score {score}/{len(keywords)} (threshold={threshold}): {item.get('question_text', '')[:60]}")
    
    if score >= threshold:
        matches.append(item)

print(f"\nMatches found: {len(matches)}")
for m in matches[:3]:
    print(f"  - {m.get('question_text', '')[:80]}")
