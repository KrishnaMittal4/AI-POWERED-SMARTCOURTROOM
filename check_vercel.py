import urllib.request
import re

url = 'https://ai-smartcourtroom-nzld.vercel.app/'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
with urllib.request.urlopen(req) as resp:
    html = resp.read().decode('utf-8')
    print('Vercel HTML length:', len(html))
    scripts = re.findall(r'src="([^"]+index[^"]+\.js)"', html)
    print('Script files:', scripts)
    if scripts:
        js_url = url.rstrip('/') + scripts[0]
        print('Fetching JS bundle:', js_url)
        req_js = urllib.request.Request(js_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req_js) as js_resp:
            js_code = js_resp.read().decode('utf-8')
            print('JS bundle size:', len(js_code))
            print('Contains "Upload Case PDF"?', 'Upload Case PDF' in js_code)
            print('Contains "research-only judgment corpus"?', 'research-only judgment corpus' in js_code)
