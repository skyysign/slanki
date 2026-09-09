from pathlib import Path
import csv
import html
import json
import re

ROOT = Path(__file__).resolve().parent
source = (ROOT / 'study-srs-founder-analysis.md').read_text(encoding='utf-8')
source_section = source.split('**Sources.**', 1)[1]
source_map = {}
for line in source_section.splitlines():
    match = re.match(r'(\d+)\. ', line)
    if match:
        for url in re.findall(r'\[[^]]+\]\((https?://[^)]+)\)', line):
            source_map[url] = int(match.group(1))

def inline(text, citations=True):
    held = []
    def hold(value):
        held.append(value)
        return f'ZZPLACEHOLDER{len(held)-1}ZZ'
    text = re.sub(r'`([^`]+)`', lambda m: hold('<code>'+html.escape(m[1])+'</code>'), text)
    def link(m):
        label, url = m[1], m[2]
        value = '<a href="'+html.escape(url, quote=True)+'">'+html.escape(label)+'</a>'
        if citations and url in source_map:
            n = source_map[url]
            value += f'<sup><a href="#source-{n}" aria-label="Source {n}">{n}</a></sup>'
        return hold(value)
    text = re.sub(r'\[([^]]+)\]\((https?://[^)]+)\)', link, text)
    text = html.escape(text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    for i, value in enumerate(held):
        text = text.replace(f'ZZPLACEHOLDER{i}ZZ', value)
    return text

lines = source.splitlines()
parts = []
toc = []
i = 0
in_sources = False
while i < len(lines):
    line = lines[i]
    if not line.strip():
        i += 1
        continue
    if line.startswith('# '):
        parts.append('<h1>'+inline(line[2:])+'</h1>')
        parts.append('TOCPLACEHOLDER')
        i += 1
        continue
    if line.startswith('```'):
        language = line[3:]
        i += 1
        block = []
        while i < len(lines) and not lines[i].startswith('```'):
            block.append(lines[i])
            i += 1
        parts.append('<pre><code>'+html.escape('\n'.join(block))+'</code></pre>')
        i += 1
        continue
    if line.startswith('|'):
        rows = []
        while i < len(lines) and lines[i].startswith('|'):
            rows.append([c.strip() for c in lines[i].strip('|').split('|')])
            i += 1
        assert len(rows) >= 2 and all(re.match(r'^:?-+:?$', c) for c in rows[1])
        count = len(rows[0])
        assert all(len(row) == count for row in rows), rows
        table = '<div class="table-wrap"><table><thead><tr>'
        table += ''.join('<th scope="col">'+inline(c)+'</th>' for c in rows[0])
        table += '</tr></thead><tbody>'
        for row in rows[2:]:
            table += '<tr>'+''.join('<td>'+inline(c)+'</td>' for c in row)+'</tr>'
        parts.append(table+'</tbody></table></div>')
        continue
    if re.match(r'^\d+\. ', line):
        items = []
        while i < len(lines) and re.match(r'^\d+\. ', lines[i]):
            number, content = lines[i].split('. ', 1)
            anchor = f' id="source-{number}"' if in_sources else ''
            items.append('<li'+anchor+'>'+inline(content, not in_sources)+'</li>')
            i += 1
        parts.append('<ol class="sources">'+''.join(items)+'</ol>' if in_sources else '<ol>'+''.join(items)+'</ol>')
        continue
    paragraph = [line]
    i += 1
    while i < len(lines) and lines[i].strip() and not lines[i].startswith(('|','```')) and not re.match(r'^\d+\. ', lines[i]):
        paragraph.append(lines[i])
        i += 1
    text = ' '.join(paragraph)
    match = re.match(r'^\*\*(\d+)\. (.+?)\.\*\*', text)
    anchor = ''
    if match:
        anchor = f' id="section-{match[1]}" class="section-start"'
        toc.append((match[1], match[2]))
    if text.startswith('**Sources.**'):
        in_sources = True
        anchor = ' id="sources" class="section-start"'
    parts.append('<p'+anchor+'>'+inline(text, not in_sources)+'</p>')

css = '''
:root {color-scheme:light} *{box-sizing:border-box} body{margin:0;background:#fff;color:#202020;font:16px/1.65 Georgia,serif}
main{max-width:1050px;margin:56px auto;padding:0 34px 70px}h1{font:600 36px/1.2 system-ui,sans-serif;letter-spacing:-.7px;margin:0 0 24px}
p{margin:0 0 18px}a{color:#263f55;text-decoration:underline;text-underline-offset:3px}sup{font:10px system-ui;margin-left:3px}
sup a{text-decoration:none}strong{font-weight:700}.section-start{margin-top:44px;padding-top:18px;border-top:1px solid #bbb;scroll-margin-top:24px}
details{font:14px/1.7 system-ui,sans-serif;margin:22px 0 28px;padding:12px 0;border-top:1px solid #ddd;border-bottom:1px solid #ddd}
summary{cursor:pointer}nav{columns:2;padding:10px 0}nav a{display:block;margin:3px 0}nav .download{margin-top:12px}
.table-wrap{overflow-x:auto;margin:22px 0 26px}table{width:100%;border-collapse:collapse;font:13px/1.55 system-ui,sans-serif}
th,td{text-align:left;vertical-align:top;padding:10px;border-bottom:1px solid #ddd}th{background:#eee;border-top:1px solid #888;border-bottom:1px solid #888;font-weight:650}
tbody tr:nth-child(even){background:#fafafa}li{margin-bottom:10px}ol{padding-left:25px}.sources{font:13px/1.65 system-ui,sans-serif}
code{font:12px/1.5 ui-monospace,Consolas,monospace;background:#f3f3f3;padding:2px 4px;overflow-wrap:anywhere}
pre{background:#f5f5f5;padding:20px;overflow:auto;line-height:1.5}pre code{background:none;padding:0}
@media(max-width:650px){main{padding:0 18px 40px;margin-top:30px}h1{font-size:29px}nav{columns:1}table{min-width:660px}body{font-size:16px}}
@media print{@page{size:A4;margin:16mm}main{max-width:none;margin:0;padding:0}body{font-size:10pt;line-height:1.5}h1{font-size:23pt}details{display:none}
.section-start{margin-top:24px;padding-top:10px}p{orphans:3;widows:3}table{font-size:8pt;line-height:1.4}th,td{padding:6px}tr{break-inside:avoid}thead{display:table-header-group}
.table-wrap{overflow:visible}pre{white-space:pre-wrap;break-inside:avoid}a{color:inherit}.sources{font-size:8pt}code{font-size:8pt}}
'''
nav = '<details><summary>Contents and companion files</summary><nav>'
nav += ''.join(f'<a href="#section-{n}">{n}. {html.escape(title)}</a>' for n,title in toc)
nav += '<a href="#sources">Sources</a><a class="download" href="study-srs-cost-calculator.html">Interactive cost calculator</a><a href="study-srs-founder-analysis.md">Editable Markdown</a></nav></details>'
body = '\n'.join(parts).replace('TOCPLACEHOLDER', nav)
assert len(toc) == 17
assert 'ZZPLACEHOLDER' not in body
document = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Lecture-to-SRS founder assessment</title><style>'+css+'</style><main>'+body+'</main></html>'
(ROOT/'study-srs-founder-analysis.html').write_text(document, encoding='utf-8')

rates = {'Luna': (0.2, 1.2), 'Terra': (2, 12), 'Astra': (10, 50)}
workloads = {
    'Naive flagship': [('Astra', 100000, 20000)],
    'Selective flagship': [('Luna', 40000, 12000), ('Astra', 15000, 4000)],
    'Selective mid-cost': [('Luna', 40000, 12000), ('Terra', 15000, 4000)],
    'All-cheap reference': [('Luna', 100000, 20000)],
}
with (ROOT/'study-srs-cost-model.csv').open('w', newline='', encoding='utf-8-sig') as f:
    writer=csv.writer(f)
    writer.writerow(['Scenario','Slides','Retry multiplier','Inference USD','Assumption','Rate source'])
    for name, stages in workloads.items():
        for slides in [50,100,2000]:
            value=sum((ti*rates[m][0]+to*rates[m][1])/1e6 for m,ti,to in stages)*1.2*slides/50
            writer.writerow([name,slides,1.2,round(value,6),'Modeled, not benchmarked; excludes infrastructure, support, payments and tax','https://developers.openai.com/api/docs/pricing'])

calculator = r'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Lecture processing cost calculator</title>
<style>CSSPLACEHOLDER
body{font-family:system-ui,sans-serif}main{max-width:1000px}.controls{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin:22px 0 30px}
label{display:flex;flex-direction:column;font-size:14px;gap:5px}input{padding:8px;border:1px solid #888;font:16px system-ui;width:100%}
.note{font-size:14px;color:#444}output{font-variant-numeric:tabular-nums}td input{font-size:14px;min-width:85px}#error{color:#8d1717}
@media(max-width:650px){.controls{grid-template-columns:1fr 1fr}}@media print{input{border:none;padding:0}}</style>
<main><h1>Lecture processing cost calculator</h1>
<p>Change the workload and pricing assumptions to compare four ingestion strategies. Rates were checked September 9, 2026. This is a cost scenario, not a quality benchmark.</p>
<p><a href="study-srs-founder-analysis.html">Read the founder assessment</a> · <a href="study-srs-cost-model.csv">Download baseline calculations</a></p>
<noscript><p>Enable JavaScript to use this calculator. The CSV contains all baseline results.</p></noscript>
<div class="controls">
<label>Monthly pages actually processed<input id="pages" type="number" value="2000" min="0" step="50"></label>
<label>Workload multiplier<input id="workload" type="number" value="1" min="0" step="0.1"></label>
<label>Retry / regeneration allowance (%)<input id="retry" type="number" value="20" min="0" step="5"></label>
<label>Monthly subscription revenue ($)<input id="revenue" type="number" value="24" min="0" step="1"></label>
<label>Allocated monthly infrastructure ($)<input id="infra" type="number" value="1" min="0" step="0.25"></label>
<label>Payment fee (%) — assumption<input id="fee" type="number" value="3" min="0" step="0.1"></label>
<label>Fixed monthly payment fee ($)<input id="fixed" type="number" value="0.30" min="0" step="0.05"></label>
<label>Monthly support minutes<input id="support" type="number" value="0" min="0" step="1"></label>
<label>Support cost per hour ($)<input id="hourly" type="number" value="40" min="0" step="5"></label>
</div>
<p id="error" role="alert"></p>
<div class="table-wrap"><table><thead><tr><th>Pipeline</th><th>50 pages</th><th>100 pages</th><th>Monthly inference</th><th>Monthly contribution</th><th>Contribution margin</th></tr></thead><tbody id="results" aria-live="polite"></tbody></table></div>
<p class="note">Contribution subtracts modeled inference, allocated infrastructure, payment fees, and entered support cost. It excludes taxes, refunds, free users, acquisition, other labor, and additional storage/egress not included in infrastructure. Monthly pages are actual consumption, not plan units. At the defaults, the selective mid-cost lane costs $4.8192 per heavy month.</p>
<details open><summary>Token budgets and rates</summary>
<p>Token totals cover all stages per 50-page lecture, including text, image-token equivalents, checking and billable reasoning. The workload multiplier scales every token budget. Change the stronger-lane budgets to test higher escalation or more expensive checking.</p>
<div class="controls">
<label>Naive / all-cheap input tokens<input id="naiveIn" type="number" value="100000" min="0" step="1000"></label>
<label>Naive / all-cheap output tokens<input id="naiveOut" type="number" value="20000" min="0" step="1000"></label>
<label>Selective cheap input tokens<input id="cheapIn" type="number" value="40000" min="0" step="1000"></label>
<label>Selective cheap output tokens<input id="cheapOut" type="number" value="12000" min="0" step="1000"></label>
<label>Selective stronger input tokens<input id="strongIn" type="number" value="15000" min="0" step="1000"></label>
<label>Selective stronger output tokens<input id="strongOut" type="number" value="4000" min="0" step="1000"></label>
</div>
<div class="table-wrap"><table><thead><tr><th>Model</th><th>Input $ / million</th><th>Output $ / million</th></tr></thead><tbody>
<tr><td>GPT-5.6 Luna</td><td><input aria-label="Luna input rate" id="lunaIn" type="number" value="0.20" min="0" step="0.05"></td><td><input aria-label="Luna output rate" id="lunaOut" type="number" value="1.20" min="0" step="0.1"></td></tr>
<tr><td>GPT-5.6 Terra</td><td><input aria-label="Terra input rate" id="terraIn" type="number" value="2" min="0" step="0.1"></td><td><input aria-label="Terra output rate" id="terraOut" type="number" value="12" min="0" step="0.5"></td></tr>
<tr><td>GPT-6 Astra</td><td><input aria-label="Astra input rate" id="astraIn" type="number" value="10" min="0" step="0.5"></td><td><input aria-label="Astra output rate" id="astraOut" type="number" value="50" min="0" step="1"></td></tr>
</tbody></table></div>
<p>Source: <a href="https://developers.openai.com/api/docs/pricing">OpenAI standard API pricing</a>. No caching, batch, or priority discount is assumed. Regional and long-context adjustments are excluded. The <a href="https://developers.openai.com/api/docs/guides/images-vision">vision guide</a> explains why image tokens vary by model and image configuration.</p>
</details>
<p><code>Cost per 50 pages = workload × (1 + retry% / 100) × sum((input tokens × input rate + output tokens × output rate) / 1,000,000)</code></p>
<p>There is no established quality equivalence between these pipelines. A cheaper result is useful only if it meets the quality and coverage requirements.</p>
</main><script>
const ids=['pages','workload','retry','revenue','infra','fee','fixed','support','hourly','naiveIn','naiveOut','cheapIn','cheapOut','strongIn','strongOut','lunaIn','lunaOut','terraIn','terraOut','astraIn','astraOut'];
function calculate(v){
 const stage=(input,output,model)=>(input*v[model+'In']+output*v[model+'Out'])/1e6;
 const multiplier=v.workload*(1+v.retry/100);
 const cheap=stage(v.cheapIn,v.cheapOut,'luna');
 const scenarios=[['Naive flagship',stage(v.naiveIn,v.naiveOut,'astra')],['Selective flagship',cheap+stage(v.strongIn,v.strongOut,'astra')],['Selective mid-cost',cheap+stage(v.strongIn,v.strongOut,'terra')],['All-cheap reference',stage(v.naiveIn,v.naiveOut,'luna')]];
 return scenarios.map(([name,base])=>{
  const per50=base*multiplier, monthly=per50*v.pages/50;
  const contribution=v.revenue-monthly-v.infra-v.revenue*v.fee/100-v.fixed-v.support*v.hourly/60;
  return {name,per50,per100:per50*2,monthly,contribution,margin:v.revenue>0?contribution/v.revenue:null};
 });
}
function render(){
 const v={};
 for(const id of ids){const input=document.getElementById(id);v[id]=Number(input.value);if(input.value===''||!Number.isFinite(v[id])||v[id]<0){document.getElementById('error').textContent='Enter a nonnegative number in every field.';return;}}
 document.getElementById('error').textContent='';
 const money=n=>n.toLocaleString('en-US',{style:'currency',currency:'USD',minimumFractionDigits:2,maximumFractionDigits:3});
 document.getElementById('results').innerHTML=calculate(v).map(row=>'<tr><td>'+row.name+'</td><td>'+money(row.per50)+'</td><td>'+money(row.per100)+'</td><td>'+money(row.monthly)+'</td><td>'+money(row.contribution)+'</td><td>'+(row.margin===null?'—':(row.margin*100).toFixed(1)+'%')+'</td></tr>').join('');
}
ids.forEach(id=>document.getElementById(id).addEventListener('input',render));render();
</script></html>'''.replace('CSSPLACEHOLDER',css)
(ROOT/'study-srs-cost-calculator.html').write_text(calculator,encoding='utf-8')

print(json.dumps({'sections':len(toc),'source_urls':len(source_map),'words':len(source.split()),'files':['study-srs-founder-analysis.html','study-srs-founder-analysis.md','study-srs-cost-calculator.html','study-srs-cost-model.csv']}, indent=2))
