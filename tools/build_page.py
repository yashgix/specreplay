"""Render docs/index.html from the committed results. Every number on the page comes from results/ and study/."""

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = 'https://github.com/yashgix/specdrift'

STYLE = """
:root{color-scheme:light dark;--bg:#fff;--band:#f3f6fb;--ink:#14202e;--muted:#566476;--line:#dce3ec;--accent:#1d4ed8;
--warn:#b45309;--code:#eef2f8;--sans:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;--mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace}
@media(prefers-color-scheme:dark){:root{--bg:#0e1621;--band:#152131;--ink:#e6edf6;--muted:#9fb0c5;--line:#263548;--accent:#7aa2ff;--warn:#f0a85a;--code:#1a2738}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.65 var(--sans)}
.wrap{max-width:780px;margin:0 auto;padding:0 16px}
header{background:var(--band);padding:3rem 0 2rem}
h1{font:600 2.4rem/1.1 var(--mono);margin:0 0 .75rem}h2{font-size:1.5rem;margin:0 0 .8rem}
section{padding:2.2rem 0;border-top:1px solid var(--line)}p,ul{margin:.6rem 0}ul{padding-left:1.2rem}
a{color:var(--accent)}code{font:.88em var(--mono);background:var(--code);padding:.08em .35em;border-radius:4px;overflow-wrap:anywhere}
pre{background:var(--code);padding:.9rem 1rem;border-radius:8px;overflow-x:auto;font:.85rem/1.5 var(--mono)}pre code{background:none;padding:0}
.lede{font-size:1.2rem;color:var(--muted)}.muted{color:var(--muted)}.small{font-size:.85rem}
.tiles{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.75rem;margin:1rem 0}
.tile{border:1px solid var(--line);border-radius:10px;padding:.8rem}.tile b{display:block;font:600 1.6rem var(--mono)}
.tile span{font-size:.85rem;color:var(--muted)}
.table-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px;margin:1rem 0}
table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{text-align:left;padding:.5rem .7rem;border-bottom:1px solid var(--line);vertical-align:top}
td code{white-space:nowrap}th{background:var(--band);color:var(--muted);font-weight:500}tr:last-child td{border-bottom:0}td.r,th.r{text-align:right}
.flow{display:flex;align-items:stretch;gap:.4rem;margin:1rem 0}.step{flex:1;min-width:0;border:1px solid var(--line);background:var(--band);border-radius:10px;padding:.6rem .7rem;font-size:.85rem}.step b{display:block;font-family:var(--mono);margin-bottom:.2rem}.step span{color:var(--muted)}.arr{align-self:center;color:var(--muted)}.arr::before{content:"\\2192"}
svg{display:block;width:100%;height:auto}svg text{fill:var(--ink);font:12px var(--mono)}svg .m{fill:var(--muted)}
svg .box{fill:var(--band);stroke:var(--line)}svg .bar{fill:var(--accent)}svg .ln{stroke:var(--muted);fill:none}
@media(max-width:620px){.flow{flex-direction:column}.arr::before{content:"\\2193"}.tiles{grid-template-columns:repeat(2,minmax(0,1fr))}h1{font-size:1.9rem}}
"""

FLOW = [
    ('Inputs', '13 pinned commits, the OpenAPI spec, one fixture call per tool'),
    ('Real handlers', 'fetch replaced by a fake API built from the spec, one change at a time: null, omit, enum, 204'),
    ('Findings', 'crash, error result, output schema, request, bound'),
    ('Score', '25-case ledger and the hold-out'),
]
DIAGRAM = (
    '<div class="flow" role="img" aria-label="Data flow">'
    + '<span class="arr" aria-hidden="true"></span>'.join(
        f'<div class="step"><b>{title}</b><span>{text}</span></div>' for title, text in FLOW
    )
    + '</div>'
)


def load(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8'))


def esc(value):
    return html.escape(str(value))


def tile(value, label):
    return f'<div class="tile"><b>{esc(value)}</b><span>{esc(label)}</span></div>'


def table(head, rows, right=()):
    cells = ''.join(f'<th class="{"r" if i in right else ""}">{esc(h)}</th>' for i, h in enumerate(head))
    body = ''.join(
        '<tr>' + ''.join(f'<td class="{"r" if i in right else ""}">{c}</td>' for i, c in enumerate(row)) + '</tr>'
        for row in rows
    )
    return f'<div class="table-wrap"><table><thead><tr>{cells}</tr></thead><tbody>{body}</tbody></table></div>'


def chart(commits, values):
    width, left, top, row = 760, 70, 10, 24
    peak = max(values)
    out = [
        f'<svg viewBox="0 0 {width} {top + row * len(values) + 10}" role="img" aria-label="Documented findings per commit">'
    ]
    for i, (commit, value) in enumerate(zip(commits, values, strict=True)):
        y = top + i * row
        size = (width - left - 50) * value / peak
        out.append(
            f'<text x="0" y="{y + 14}">{esc(commit)}</text><rect class="bar" x="{left}" y="{y + 2}" width="{size:.1f}" height="16" rx="3"/>'
        )
        out.append(f'<text x="{left + size + 6:.1f}" y="{y + 14}">{value}</text>')
    return ''.join(out) + '</svg>'


def page():
    m, wide, hold = load('results/metrics.json'), load('results/wide.json'), load('results/holdout.json')
    triage = load('study/triage.json')
    commits = [row['commit'] for row in load('results/reports.json')]
    causes = triage['root_causes']
    tiles = ''.join(
        [
            tile(f'{m["known_caught"]}/{m["known_cases"]}', 'ledger cases caught (in-sample)'),
            tile(f'{m["known_caught_documented"]}/{m["known_cases_documented"]}', 'caught where the spec documents it'),
            tile(f'{hold["caught"]}/{hold["cases"]}', 'hold-out cases caught'),
            tile(f'{m["runs_total"]:,}', 'tool calls replayed'),
        ]
    )
    cause_rows = [
        [esc(c['title']), esc(c['kind'].replace('_', ' ')), '<br>'.join(f'<code>{esc(s)}</code>' for s in c['sites'])]
        for c in causes
    ]
    hold_rows = [[esc(s['id']), esc(s['first_run_prediction']), esc(s['result'])] for s in hold['scored']]
    wrapper = next(f for f in wide['added_findings'] if f['outcome'] == 'wrapped_over_limit')['detail']
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SpecDrift</title>
<meta name="description" content="A contract-drift scanner for AgentPhone's open-source MCP server, checked against its OpenAPI spec.">
<style>{STYLE}</style></head><body>
<header><div class="wrap"><h1>SpecDrift</h1>
<p class="lede">Replays the real tool handlers of <code>agentphone-mcp</code> against a fake API built from its OpenAPI spec, to find places where the tools and the documented API disagree.</p>
<p><a href="{REPO}">GitHub</a></p></div></header>
<main class="wrap">
<section><h2>The problem</h2>
<p>The project's history shows a run of contract-drift bugs between its MCP tools and the documented API: an empty 204 body failing output validation, documented <code>null</code> values rejected, a crash on a documented list shape, bounds dropped and later restored. The project's own check compares endpoint and field names. SpecDrift asks a different question: from the published spec alone, how many of those bugs would an automatic behavioural check have caught, and what does it flag today?</p></section>
<section><h2>Approach</h2>{DIAGRAM}
<p>Each pinned commit's real <code>tools.ts</code>, <code>api.ts</code> and <code>output-schemas.ts</code> run with the zod version they pin. <code>fetch</code> is replaced by an in-process API that answers from the spec. Each tool is called once with a valid fixture, then again with one thing changed in the response: a nullable field set to <code>null</code>, an optional field left out, another enum value, an empty array, a 204. Requests are checked against the spec, and each argument that reaches a constrained request field is probed with a value just past the documented limit. Nothing touches the network or the live API.</p></section>
<section><h2>Results</h2><div class="tiles">{tiles}</div>
<p>The ledger has {m['known_cases']} cases, {m['known_cases_documented']} of them about contracts the spec documents. The rules were written knowing these cases, so the {m['known_caught']}/{m['known_cases']} figure shows the rules reproduce the history. It is not a rate for unseen drift.</p>
<h3>Documented findings per commit, oldest first</h3>{chart(commits, m['documented_findings_per_commit'])}
<h3>What it flags at v0.10.0</h3>
<p>{m['latest_findings_documented']} documented findings come down to {len(causes)} root causes, one of which is already known. None is shown to break a user. The maintainers report in #88 that the API answers 422 to out-of-range values, so a missing client-side bound likely means a late 422. Nothing was run against the live API.</p>
{table(['Root cause', 'Kind', 'Code sites'], cause_rows)}
<p>The language case is open upstream as issue #120 with fix PR #121 and is not counted as a finding of this work.</p>
<h3>Hold-out</h3>
<p>Three cases outside the ledger, with the rules frozen first (git tag <code>rules-frozen</code>) and predictions written before the first run. One caught, two missed with their bugs shown to be exercised. Three cases is too few for a rate. It shows which classes are covered.</p>
{table(['Case', 'Predicted', 'Result'], hold_rows)}
<h3>Prompt wrapper</h3>
<p>In hosted mode the tool wraps <code>system_prompt</code> in identity text. Wide mode measured this on the real handler: <code>{esc(wrapper)}</code>. A plain ASCII prompt over that threshold would go out over the documented 20000. This is measured offline. Live behaviour is unverified.</p></section>
<section><h2>What v2 changed</h2><ul>
<li>Findings are reported as root causes, not as counts of "new bugs" or "confirmed".</li>
<li>Recall is labelled in-sample, and a small frozen hold-out was added.</li>
<li>Wide mode probes arguments the fixtures leave out and measures the prompt wrapper.</li>
<li>Review fixes after the freeze did not move the 25-case results.</li></ul>
<p class="small muted">Full list: <a href="{REPO}/blob/main/docs/V2-CHANGES.md">docs/V2-CHANGES.md</a>.</p></section>
<section><h2>Limits</h2><ul>
<li>{m['spec_operations_unconstrained']} of {m['spec_operations']} operations document an unconstrained response, so nothing can be judged there.</li>
<li>The handlers run against a stubbed <code>fetch</code> and an emulation of the SDK's three checks, not the SDK.</li>
<li>Single-fault mutations only. Combined faults are out of scope.</li>
<li>The spec is treated as correct. A spec error shows up as a tool bug.</li>
<li>The spec is a live document. The copy used for the committed results is not retrievable, and a later fetch differs in one description. The experiment still reproduces the results byte for byte.</li></ul></section>
<section><h2>Reproduce</h2>
<pre><code>git clone {REPO} &amp;&amp; cd specdrift
export ARCTURUS_NODE=/path/to/node22
python tools/fetch_data.py --accept-spec-drift
make test experiment</code></pre>
<p class="small muted">The page is generated from <code>results/</code> and <code>study/</code> by <code>python tools/build_page.py</code>. Built with Arcturus (Claude Code builders, Codex review). Reviewed and verified by hand.</p></section>
</main></body></html>
"""


if __name__ == '__main__':
    (ROOT / 'docs').mkdir(exist_ok=True)
    (ROOT / 'docs' / 'index.html').write_text(page(), encoding='utf-8')
