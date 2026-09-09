from pathlib import Path
from html.parser import HTMLParser
import json
import re
import subprocess

root = Path(__file__).resolve().parent
markdown = (root/'study-srs-founder-analysis.md').read_text(encoding='utf-8')
assert [int(n) for n in re.findall(r'^\*\*(\d+)\.',markdown,re.M)] == list(range(1,18))
json.loads(re.search(r'```json\n(.*?)\n```',markdown,re.S)[1])

class Audit(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.links = []
        self.tables = 0
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if 'id' in attrs:
            assert attrs['id'] not in self.ids, attrs['id']
            self.ids.add(attrs['id'])
        if tag == 'a': self.links.append(attrs['href'])
        if tag == 'table': self.tables += 1

for file in ['study-srs-founder-analysis.html','study-srs-cost-calculator.html']:
    audit=Audit()
    content=(root/file).read_text(encoding='utf-8')
    audit.feed(content)
    for link in audit.links:
        if link.startswith('#'): assert link[1:] in audit.ids, link
        elif not link.startswith(('https://','http://')): assert (root/link).is_file(), link
    assert 'PLACEHOLDER' not in content
    print(file, 'valid anchors and local file links;', audit.tables, 'tables')

script=re.search(r'<script>(.*?)</script>',(root/'study-srs-cost-calculator.html').read_text(encoding='utf-8'),re.S)[1]
html_source=(root/'study-srs-cost-calculator.html').read_text(encoding='utf-8')
defaults=dict(re.findall(r'id="([^"]+)" type="number" value="([^"]+)"',html_source))
node_script='''const vm=require('vm'); const assert=require('assert');
const defaults=DEFAULTS;
const elements=Object.fromEntries(Object.entries(defaults).map(([id,value])=>[id,{value,addEventListener(){}}]));
elements.error={textContent:''};elements.results={innerHTML:''};
const sandbox={document:{getElementById:id=>elements[id]}};
vm.createContext(sandbox);vm.runInContext(SCRIPT,sandbox);
const v=Object.fromEntries(Object.entries(defaults).map(([k,v])=>[k,Number(v)]));
const result=sandbox.calculate(v);
const expected=[2.4,.44688,.12048,.0528];
result.forEach((r,i)=>assert(Math.abs(r.per50-expected[i])<1e-10));
assert(Math.abs(result[2].monthly-4.8192)<1e-10);
assert(Math.abs(result[2].contribution-17.1608)<1e-10);
assert(sandbox.calculate({...v,workload:3})[2].monthly>14.45);
assert(sandbox.calculate({...v,pages:0})[0].monthly===0);
assert(sandbox.calculate({...v,revenue:0})[0].margin===null);
elements.pages.value='-1';sandbox.render();assert(elements.error.textContent.length>0);
elements.pages.value='2000';sandbox.render();assert(elements.error.textContent==='');
assert(elements.results.innerHTML.includes('$4.819'));
console.log('Calculator: baseline, contribution, sensitivity, zero values, input validation and rendered output passed.');
'''.replace('DEFAULTS',json.dumps(defaults)).replace('SCRIPT',json.dumps(script))
result=subprocess.run(['node','-e',node_script],cwd=root,capture_output=True,text=True)
print(result.stdout)
assert result.returncode==0,result.stderr
print('All 17 topics present; JSON example valid.')
