import urllib.request, ssl, json

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

base = 'https://sih26017-infrastructure-intelligence-jedbh5zqn.vercel.app'

# Try health with full error detail
try:
    req = urllib.request.Request(base + '/api/v1/health')
    req.add_header('Accept', 'application/json')
    r = urllib.request.urlopen(req, timeout=15, context=ctx)
    body = r.read().decode()
    print('Response headers:', dict(r.headers))
    print('Body:', body[:300])
except urllib.error.HTTPError as e:
    print('HTTP Error:', e.code, e.reason)
    print('Response headers:', dict(e.headers))
    body = e.read().decode()
    print('Error body:', body[:500])
except Exception as e:
    print('Exception:', e)
