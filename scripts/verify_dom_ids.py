import re
import sys

with open('frontend/app.js', 'r', encoding='utf-8') as f:
    app_js = f.read()

required_ids = sorted(list(set(re.findall(r"getElementById\(['\"]([^'\"]+)['\"]\)", app_js))))

with open('frontend/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

missing = []
for req_id in required_ids:
    # Look for id="req_id" or id='req_id'
    pattern = rf'id=["\']{re.escape(req_id)}["\']'
    if not re.search(pattern, html):
        missing.append(req_id)

print(f"Total required IDs from app.js: {len(required_ids)}")
if missing:
    print(f"❌ Missing {len(missing)} IDs in index.html:")
    for m in missing:
        print(f"  - {m}")
    sys.exit(1)
else:
    print("✅ All required IDs are present in index.html!")
    sys.exit(0)
