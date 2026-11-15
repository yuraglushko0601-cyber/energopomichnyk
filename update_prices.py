"""Fetch permitted merchant JSON feeds, validate and publish offers atomically."""
import json, os, sys, urllib.request, urllib.parse, datetime, pathlib, tempfile
ROOT=pathlib.Path(__file__).resolve().parent
CONFIG=ROOT/'sources.json'
OUT=ROOT/'offers.json'
MAX_BYTES=5_000_000
REQUIRED=('brand','model','sku','shop','url','priceUah','availability')
STATES={'in_stock','out_of_stock','preorder','unknown'}

def valid(o, allow_hosts):
    if not isinstance(o,dict) or not all(k in o for k in REQUIRED): return False
    if not all(isinstance(o[k],str) and o[k].strip() for k in ('brand','model','sku','shop','url')):return False
    u=urllib.parse.urlsplit(o['url'])
    if u.scheme!='https' or not u.hostname or (allow_hosts and u.hostname not in allow_hosts):return False
    if o['availability'] not in STATES or type(o['priceUah']) not in (int,float) or not (0<o['priceUah']<=10_000_000):return False
    return True

def run():
    cfg=json.loads(CONFIG.read_text(encoding='utf-8'))
    sources=[s for s in cfg['sources'] if s.get('enabled')]
    if not sources: print('No enabled permitted feeds. Existing offers left untouched.');return 0
    offers=[];failures=[];now=datetime.datetime.now(datetime.timezone.utc).isoformat()
    for source in sources:
        url=source['feed_url'];host=urllib.parse.urlsplit(url).hostname
        if not url.startswith('https://') or not host or host not in source.get('allowed_feed_hosts',[]):
            failures.append(f"{source['name']}: feed URL not allowlisted");continue
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'EnergoPomichnyk/0.7 (+merchant-authorized-feed)'})
            with urllib.request.urlopen(req,timeout=15) as response:
                if response.status!=200:raise ValueError(f'HTTP {response.status}')
                raw=response.read(MAX_BYTES+1)
            if len(raw)>MAX_BYTES:raise ValueError('Feed too large')
            payload=json.loads(raw)
            entries=payload.get('offers') if isinstance(payload,dict) else payload
            if not isinstance(entries,list) or len(entries)>10000:raise ValueError('Invalid offers array')
            hosts=set(source.get('allowed_product_hosts',[]))
            for entry in entries:
                if valid(entry,hosts):
                    o={k:entry[k] for k in REQUIRED};o['checkedAt']=now;o['sourceId']=source['id'];offers.append(o)
            print(f"{source['name']}: {len(entries)} received")
        except Exception as exc:failures.append(f"{source['name']}: {exc}")
    if failures:print('\n'.join(failures),file=sys.stderr)
    # Never replace an existing file with empty or incomplete data on upstream errors.
    if failures or not offers:print('No publication; previous verified snapshot preserved.');return 1
    unique={(o['brand'],o['model'],o['sku'],o['shop']):o for o in offers}
    data={'schemaVersion':1,'generatedAt':now,'offers':list(unique.values())}
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=ROOT,delete=False) as f:
        json.dump(data,f,ensure_ascii=False,indent=2);temp=f.name
    os.replace(temp,OUT)
    print(f'Published {len(unique)} offers to {OUT}')
    return 0
if __name__=='__main__':sys.exit(run())
