import urllib.request, ssl, json

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

base = 'https://sih26017-infrastructure-intelligence-2gaei2sra.vercel.app'
endpoints = [
    '/api/v1/health',
    '/api/v1/summary',
    '/api/v1/alerts?limit=3',
    '/api/v1/metadata',
    '/api/v1/data-quality',
    '/api/v1/auth/demo-token?role=VIEWER',
]

for ep in endpoints:
    try:
        method = 'POST' if 'demo-token' in ep else 'GET'
        req = urllib.request.Request(base + ep, method=method)
        req.add_header('Accept', 'application/json')
        r = urllib.request.urlopen(req, timeout=15, context=ctx)
        body = r.read().decode()
        ct = r.headers.get('Content-Type', '')
        is_json = body.strip().startswith('{') or body.strip().startswith('[')
        status = 'JSON OK' if is_json else 'HTML (PROTECTED)'
        print(f'[{status}] {r.getcode()} {ep}')
        if is_json:
            print('  Preview:', body[:120])
        else:
            print('  Redirect to:', body[200:280])
    except Exception as e:
        print(f'ERR {ep}: {e}')
