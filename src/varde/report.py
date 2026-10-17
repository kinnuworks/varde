"""Self-contained HTML report for a Varde run.

One file: inline CSS, vanilla JS and the run data as a JSON blob. The only
external request is the Inter web font, with system fonts as the fallback, so
the report works offline. All data is rendered with textContent and
createElement, never parsed as markup.
"""
from __future__ import annotations

import html
import json
import pathlib


def _embed(obj: object) -> str:
    text = json.dumps(obj, ensure_ascii=True, separators=(",", ":"), default=str)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def write_report(envelopes: list[dict], path: pathlib.Path, run_meta: dict) -> None:
    """Write the report for `envelopes` to `path` as a single HTML file."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    run_id = str((run_meta or {}).get("run_id") or "")
    data = _embed({"meta": run_meta or {}, "envelopes": [_pack(e) for e in envelopes or []]})
    doc = (_TEMPLATE.replace("__TITLE__", html.escape(f"Varde report · run {run_id}" if run_id else "Varde report"))
           .replace("__CSS__", _CSS).replace("__JS__", _JS).replace("__DATA__", data))
    path.write_text(doc, encoding="utf-8")


_SNAP_KEYS = ("source_url", "retrieved_at", "content_sha256", "snapshot_path", "source_class", "licence")


def _pack(env: dict) -> dict:
    """Store each snapshot's shared fields once; the page expands them on load."""
    snaps: list[list] = []
    index: dict[tuple, int] = {}
    packed = []
    for ev in env.get("evidence") or []:
        key = tuple(ev.get(k) for k in _SNAP_KEYS)
        if key not in index:
            index[key] = len(snaps)
            snaps.append(list(key))
        packed.append({**{k: v for k, v in ev.items() if k not in _SNAP_KEYS}, "_s": index[key]})
    return {**env, "evidence": packed, "_snaps": snaps}


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light">
<title>__TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap">
<style>__CSS__</style>
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="top">
  <div class="top-in">
    <a class="brand" href="#/" aria-label="Varde, all companies"><span class="mark" aria-hidden="true"></span><span>Varde</span></a>
    <nav class="nav" aria-label="Main">
      <a href="#/" data-nav="dir"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 4h14M3 10h14M3 16h9"/></svg><span>Companies</span></a>
      <a href="#/compare" data-nav="compare"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 3v14M10 3v14M16 3v14"/></svg><span>Compare</span></a>
      <a href="#/research" data-nav="research"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 4h12v9H9l-4 3v-3H4z"/></svg><span>Ask</span></a>
      <a href="#/refresh" data-nav="refresh"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M16 10a6 6 0 1 1-2-4.5M16 3v3h-3"/></svg><span>Changes</span></a>
    </nav>
    <div class="qs" role="search">
      <label class="sr" for="qs">Find a company</label>
      <input id="qs" type="search" placeholder="Find a company" autocomplete="off" aria-controls="qs-list" aria-expanded="false">
      <ul id="qs-list" class="qs-list" role="listbox" hidden></ul>
    </div>
  </div>
</header>
<main id="main" tabindex="-1"></main>
<footer class="foot" id="foot"></footer>
<div id="tray" class="tray" hidden></div>
<div id="scrim" class="scrim" hidden></div>
<aside id="drawer" class="drawer" role="dialog" aria-modal="true" aria-labelledby="dr-t" hidden>
  <div class="dr-h"><h2 id="dr-t">Source</h2><button class="icon" id="dr-x" type="button" aria-label="Close source panel">&#215;</button></div>
  <div class="dr-b" id="dr-b"></div>
</aside>
<div id="toast" class="toast" role="status" aria-live="polite"></div>
<script type="application/json" id="varde-data">__DATA__</script>
<script>__JS__</script>
</body>
</html>
"""

_CSS = r"""
:root{--ink:#1D1D1F;--ink2:#515154;--ink3:#6E6E73;--ink4:#C7C7CC;--bg:#F7F7F8;--surf:#FFFFFF;--surf2:#F2F2F4;--line:rgba(0,0,0,.07);--line2:rgba(0,0,0,.05);
--red:#C8102E;--redh:#A50D26;--wash:#FBEAEC;--amb:#8F5200;--ambbg:#FFF3DE;--ok:#1F7A3D;--okbg:#E8F5EC;
--sh:0 0 0 1px rgba(0,0,0,.07),0 1px 2px rgba(0,0,0,.04),0 8px 24px -12px rgba(0,0,0,.12);
--sans:Inter,system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
--mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
*{box-sizing:border-box}
[hidden]{display:none!important}
html{-webkit-text-size-adjust:100%;scroll-padding-top:72px}
body{margin:0;background:var(--bg);color:var(--ink);font:400 14px/1.5 var(--sans);-webkit-font-smoothing:antialiased;overflow-x:hidden;font-variant-numeric:tabular-nums}
a{color:inherit;text-underline-offset:2px;text-decoration-color:rgba(0,0,0,.25)}
a:hover{color:var(--ink);text-decoration-color:var(--red)}
h1,h2,h3{margin:0;font-weight:600;letter-spacing:-.025em;line-height:1.2}
h1{font-size:30px;letter-spacing:-.03em}h2{font-size:20px}h3{font-size:15px;letter-spacing:-.015em}
p{margin:0}
button{font:inherit;color:inherit;cursor:pointer}
:focus-visible{outline:2px solid var(--red);outline-offset:2px;border-radius:6px}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.skip{position:absolute;left:-999px;top:8px;background:var(--ink);color:#fff;padding:8px 12px;border-radius:8px;z-index:99}
.skip:focus{left:8px}
.mob{display:none}
.mono,.num{font-family:var(--mono);font-size:.92em;letter-spacing:0;font-variant-numeric:tabular-nums}
.num{white-space:nowrap}
.muted{color:var(--ink3)}.sec{color:var(--ink2)}.nowrap{white-space:nowrap}
.eyebrow{display:block;font-size:12px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--ink3);margin:0 0 6px}
.top{position:sticky;top:0;z-index:30;background:#fff;border-bottom:1px solid var(--line)}
.top-in{max-width:1180px;margin:0 auto;padding:0 24px;height:56px;display:flex;align-items:center;gap:24px}
.brand{display:flex;align-items:center;gap:8px;font-weight:600;font-size:16px;letter-spacing:-.02em;text-decoration:none}
.mark{width:14px;height:14px;background:var(--red);border-radius:3px;display:inline-block}
.nav{display:flex;gap:4px;align-self:stretch}
.nav a{display:flex;align-items:center;gap:6px;text-decoration:none;color:var(--ink3);font-weight:500;padding:0 10px;box-shadow:inset 0 -2px 0 transparent}
.nav a:hover{color:var(--ink)}
.nav a[aria-current=page]{color:var(--ink);box-shadow:inset 0 -2px 0 var(--red)}
.nav svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round;display:none}
.qs{margin-left:auto;position:relative;width:260px}
.qs input,.field{width:100%;height:36px;border:1px solid var(--line);border-radius:10px;padding:0 12px;font:inherit;background:var(--surf2);color:var(--ink)}
.qs input:focus,.field:focus{outline:2px solid var(--red);outline-offset:0;background:#fff}
.qs-list{position:absolute;right:0;top:44px;width:min(380px,calc(100vw - 32px));margin:0;padding:6px;list-style:none;background:#fff;border-radius:12px;box-shadow:var(--sh)}
.qs-list a{display:block;padding:8px 10px;border-radius:8px;text-decoration:none}
.qs-list a:hover,.qs-list a.on{background:var(--surf2)}
.qs-list small{display:block;color:var(--ink3)}
main{display:block;min-height:70vh;outline:none;padding-bottom:64px}
main:focus,main:focus-visible{outline:none}
.wrap{max-width:1180px;margin:0 auto;padding:0 24px}
.band{padding:40px 0 8px}
.band p.lead{color:var(--ink2);margin-top:8px;max-width:72ch}
.pad{padding-top:24px;padding-bottom:48px}
.card{background:var(--surf);border-radius:14px;box-shadow:var(--sh)}
.box{padding:24px}
.row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:36px;padding:0 14px;border-radius:10px;border:1px solid var(--line);background:#fff;font-weight:500;text-decoration:none;white-space:nowrap;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.btn:hover{background:var(--surf2);color:var(--ink)}
.btn.pri{background:var(--red);border-color:var(--red);color:#fff}
.btn.pri:hover{background:var(--redh);border-color:var(--redh);color:#fff}
.btn[aria-pressed=true]{background:var(--wash);border-color:var(--red);color:var(--red)}
.chip{display:inline-flex;align-items:center;gap:6px;min-height:32px;padding:0 12px;border-radius:999px;border:1px solid var(--line);background:#fff;font-size:13px;font-weight:500;color:var(--ink2)}
.chip:hover{background:var(--surf2);color:var(--ink)}
.chip[aria-pressed=true]{background:var(--wash);border-color:var(--red);color:var(--red)}
.chip .ct{font-family:var(--mono);font-size:11px;color:var(--ink3)}
.src{display:inline-flex;align-items:center;min-height:24px;padding:0 8px;border-radius:999px;border:1px solid var(--line);background:#fff;font-size:11.5px;font-weight:500;color:var(--ink3);white-space:nowrap}
.src:hover{color:var(--red);border-color:var(--red)}
.srcl{border:0;background:none;padding:4px 0;font-size:12px;font-weight:500;color:var(--ink3);text-decoration:underline;text-decoration-color:var(--ink4);text-underline-offset:3px}
.srcl:hover{color:var(--red);text-decoration-color:var(--red)}
.cites{white-space:nowrap}
.cite2{display:inline-flex;align-items:center;gap:3px;height:20px;padding:0 6px;margin:0 2px 0 4px;border:0;border-radius:6px;background:var(--wash);color:var(--red);font:600 11px/1 var(--mono);vertical-align:2px}
.cite2 svg{width:11px;height:11px;fill:none;stroke:currentColor;stroke-width:1.6}
.cite2:hover{background:var(--red);color:#fff}
.badge{display:inline-flex;align-items:center;height:22px;padding:0 8px;border-radius:999px;font-size:11.5px;font-weight:600;background:var(--surf2);color:var(--ink2)}
.badge.alert{background:var(--wash);color:var(--red)}
.badge.ok{background:var(--okbg);color:var(--ok)}
.badge.amb{background:var(--ambbg);color:var(--amb)}
.st{font-style:italic;color:var(--ink3)}
.st.ambiguous{font-style:normal;color:var(--amb);background:var(--ambbg);padding:1px 7px;border-radius:6px}
.reason{display:block;color:var(--ink3);font-size:12.5px;margin-top:2px}
.tools{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:24px}
.tools .field{max-width:520px;height:40px;font-size:14px;background:#fff;flex:1 1 280px}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
select.field,.tools select.field{width:auto;flex:0 0 auto;padding-right:28px;appearance:auto;height:40px;background:#fff}
.count{color:var(--ink3);margin:24px 0 8px;font-size:13px}
.tiles{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin-top:24px}
.tile{display:flex;flex-direction:column;align-items:flex-start;gap:4px;text-align:left;border:0;padding:16px;background:var(--surf);border-radius:14px;box-shadow:var(--sh)}
.tile b{font:600 28px/1.1 var(--sans);letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.tile span{font-size:12.5px;color:var(--ink3)}
.tile:hover{background:#FCFCFD}
.tile[aria-pressed=true]{box-shadow:0 0 0 2px var(--red),0 1px 2px rgba(0,0,0,.04)}
.tile[aria-pressed=true] span{color:var(--red)}
.list{list-style:none;margin:0;padding:0}
.co,.co-head{display:grid;grid-template-columns:minmax(0,1fr) 196px 84px 150px 132px 56px 36px;align-items:center;gap:16px;padding:12px 16px 12px 20px}
.co{border-top:1px solid var(--line2);position:relative}
.co:first-child{border-top:0}
.co:hover{background:#FBFBFC}
.list.card .co:first-child{border-radius:14px 14px 0 0}.list.card .co:last-child{border-radius:0 0 14px 14px}
.co-head{padding-top:0;padding-bottom:8px;font-size:11.5px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--ink3)}
.co-head .r,.co .r{text-align:right;justify-content:flex-end}
.co-a{min-width:0;text-decoration:none;display:block}
.co-a::after{content:"";position:absolute;inset:0}
.co-n{display:block;font-weight:600;font-size:15px;letter-spacing:-.01em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.co-a:hover .co-n{text-decoration:underline;text-decoration-color:var(--red);text-underline-offset:3px}
.co-m{display:block;color:var(--ink3);font-size:12.5px;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.co-figs{display:contents}
.co-f{min-width:0;font-size:13px;display:flex;align-items:center;gap:6px}
.co-f .num{font-size:12.5px}
.co-f.web{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:block;color:var(--ink2)}
.co-b{display:flex;gap:4px;flex-wrap:wrap;justify-content:flex-end}
.trend{color:var(--ink3);font-size:12px;width:10px;display:inline-block;text-align:center}
.areas{display:flex;gap:2px;align-items:center}
.areas i{width:9px;height:4px;border-radius:2px;background:rgba(0,0,0,.09)}
.areas i.on{background:var(--ink2)}
.ghost{position:relative;z-index:1;display:inline-flex;align-items:center;justify-content:center;gap:6px;width:32px;height:32px;border-radius:8px;border:1px solid transparent;background:none;color:var(--ink3)}
.ghost svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round}
.ghost:hover{background:var(--surf2);color:var(--ink)}
.ghost[aria-pressed=true]{background:var(--wash);color:var(--red)}
.ghost .gl{position:absolute;right:calc(100% + 6px);top:50%;transform:translateY(-50%);background:var(--ink);color:#fff;font-size:12px;font-weight:500;padding:3px 8px;border-radius:6px;white-space:nowrap;opacity:0;pointer-events:none;transition:opacity .12s}
.ghost:hover .gl,.ghost:focus-visible .gl{opacity:1}
.more{display:flex;justify-content:center;margin-top:16px}
.empty{padding:40px 24px;text-align:center;color:var(--ink3);font-style:italic}
.ph{display:flex;gap:24px;align-items:flex-start;justify-content:space-between;flex-wrap:wrap}
.ph-meta{display:flex;gap:8px 16px;flex-wrap:wrap;align-items:center;color:var(--ink2);margin-top:8px}
.crumb{font-size:13px;color:var(--ink3);text-decoration:none;display:inline-block;margin-bottom:12px}
.kpis{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px;margin-top:24px}
.kpi{padding:16px;display:flex;flex-direction:column;gap:2px;min-width:0}
.kpi .eyebrow{margin:0 0 4px;font-size:11px}
.kpi .kv1{font-size:17px;font-weight:600;letter-spacing:-.02em;line-height:1.25;overflow-wrap:anywhere}
.kpi .kv1 small{font-size:12px;font-weight:500;color:var(--ink3);margin-left:3px}
.kpi .kv1.st{font-size:14px;font-weight:400}
.kpi .ks{font-size:12px;color:var(--ink3)}
.kpi .kf{margin-top:auto;padding-top:8px;display:flex;align-items:flex-end;justify-content:space-between;gap:8px}
.spark{width:64px;height:24px;display:block}
.sum{font-size:15.5px;line-height:1.65;letter-spacing:-.006em;max-width:68ch;margin-top:12px}
.cap{font-size:12.5px;color:var(--ink3);margin-top:2px}
.unk{margin:16px 0 0;padding:12px 16px;background:var(--surf2);border-radius:10px;font-size:13px;color:var(--ink2)}
.unk ul{margin:4px 0 0;padding-left:18px}
.grid2{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(0,1fr);gap:16px;margin-top:16px}
.how h4{margin:20px 0 8px;font-size:12px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--ink3)}
.how h4:first-of-type{margin-top:12px}
.proof .quote{margin-top:8px}
.cnts{display:grid;grid-template-columns:1fr auto;gap:4px 12px;margin:0;font-size:13px}
.cnts dt{color:var(--ink2)}.cnts dd{margin:0;font-family:var(--mono);font-size:12.5px;text-align:right}
.check{list-style:none;margin:0;padding:0;display:grid;gap:6px;font-size:13px}
.check li{display:flex;align-items:center;gap:8px}
.check li span.v{margin-left:auto;color:var(--ink3);font-size:12px}
.check svg{width:14px;height:14px;flex:none;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.check .y svg{stroke:var(--red)}.check .n svg{stroke:var(--ink4)}.check .n{color:var(--ink3)}
.tabs{display:flex;gap:4px;overflow-x:auto;margin:40px 0 16px;border-bottom:1px solid var(--line);scrollbar-width:none}
.tabs::-webkit-scrollbar{display:none}
.tabs button{border:0;background:none;padding:10px 10px;font-weight:500;color:var(--ink3);white-space:nowrap;min-height:40px;box-shadow:inset 0 -2px 0 transparent;border-radius:0}
.tabs button:hover{color:var(--ink)}
.tabs button[aria-selected=true]{color:var(--ink);box-shadow:inset 0 -2px 0 var(--red)}
.facts{margin:0}
.fact{display:grid;grid-template-columns:208px minmax(0,1fr) auto;gap:16px;padding:12px 0;border-top:1px solid var(--line2);align-items:baseline}
.fact:first-child{border-top:0}
.fact dt{color:var(--ink3);font-size:13px}
.fact dd{margin:0;overflow-wrap:anywhere}
.fact.cont{border-top-color:transparent;padding-top:0}
.sub-h{margin:32px 0 8px;font-size:12px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--ink3)}
.sub-h:first-child{margin-top:0}
table.t{width:100%;border-collapse:collapse}
.t th,.t td{text-align:left;padding:10px 12px;border-top:1px solid var(--line2);vertical-align:top}
.t thead th{border-top:0;font-size:11.5px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--ink3);background:var(--surf2)}
.t thead th:first-child{border-radius:8px 0 0 8px}.t thead th:last-child{border-radius:0 8px 8px 0}
.t td.r,.t th.r{text-align:right}
.t .cell{display:inline-flex;gap:6px;align-items:center;flex-wrap:wrap;justify-content:flex-end}
.t-wrap{overflow-x:auto}
.tl2 .month{margin:28px 0 8px;font-size:12px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--ink3)}
.tl2 .month:first-child{margin-top:0}
.tl2 ol{list-style:none;margin:0;padding:0}
.ti{display:grid;grid-template-columns:92px minmax(0,1fr) auto;gap:16px;align-items:start}
.ti .d{padding-top:10px;font-size:12px;color:var(--ink2)}
.ti-b{position:relative;padding:8px 0 16px 20px;border-left:1px solid var(--line);min-width:0;overflow-wrap:anywhere}
.ti-b::before{content:"";position:absolute;left:-5px;top:14px;width:9px;height:9px;border-radius:50%;background:#fff;box-shadow:inset 0 0 0 2px var(--ink4)}
.tl2 .ti.first .ti-b::before{box-shadow:inset 0 0 0 2px var(--red)}
.ti .src{margin-top:8px}
.tag{display:inline-block;font-size:11px;font-weight:600;color:var(--ink2);background:var(--surf2);padding:2px 8px;border-radius:999px;margin-right:8px}
.chg{padding:16px 0;border-top:1px solid var(--line2)}
.chg:first-child{border-top:0}
.chg .row{margin-bottom:4px}
.diff{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;font-size:13px;margin-top:8px;color:var(--ink2)}
.ev{padding:12px 0;border-top:1px solid var(--line2)}
.ev:first-child{border-top:0}
.drawer{position:fixed;z-index:60;top:0;right:0;bottom:0;width:min(480px,100vw);background:#fff;box-shadow:-24px 0 64px rgba(0,0,0,.12),0 0 0 1px var(--line);display:flex;flex-direction:column}
.scrim{position:fixed;inset:0;z-index:55;background:rgba(15,15,20,.24)}
.dr-h{display:flex;align-items:center;justify-content:space-between;padding:16px 24px;border-bottom:1px solid var(--line)}
.dr-b{overflow-y:auto;padding:0 24px 32px;flex:1}
.icon{width:36px;height:36px;border-radius:10px;border:1px solid var(--line);background:#fff;font-size:20px;line-height:1}
.icon:hover{background:var(--surf2)}
.dc{padding:20px 0;border-bottom:1px solid var(--line)}
.dc:last-child{border-bottom:0}
.dc .v{font-size:16px;font-weight:600;letter-spacing:-.015em;margin:4px 0 8px;overflow-wrap:anywhere}
.kv{display:grid;grid-template-columns:120px minmax(0,1fr);gap:8px 12px;margin:12px 0 0;font-size:13px}
.kv dt{color:var(--ink3)}.kv dd{margin:0;overflow-wrap:anywhere}
.quote{font:12.5px/1.55 var(--mono);background:var(--surf2);border-radius:10px;padding:12px 14px;margin:12px 0 0;white-space:pre-wrap;overflow-wrap:anywhere;border-left:3px solid var(--red)}
.qlab{font-size:11.5px;font-weight:600;color:var(--ink3);margin-top:16px}
.copy{border:1px solid var(--line);background:#fff;border-radius:999px;font-size:11px;padding:1px 8px;margin-left:6px;color:var(--ink3)}
.copy:hover{background:var(--surf2);color:var(--ink)}
.tray{position:fixed;z-index:40;left:50%;bottom:24px;transform:translateX(-50%);display:flex;gap:8px;align-items:center;padding:8px 8px 8px 16px;background:#fff;border-radius:14px;box-shadow:var(--sh),0 16px 40px -16px rgba(0,0,0,.25);max-width:calc(100vw - 24px)}
.tray .tl-n{font-size:12.5px;color:var(--ink3);white-space:nowrap}
.tray .pill{display:inline-flex;align-items:center;gap:4px;max-width:170px;background:var(--surf2);border-radius:999px;padding:0 4px 0 10px;height:30px;font-size:12.5px}
.tray .pill span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tray .pill button{border:0;background:none;width:24px;height:24px;border-radius:999px;color:var(--ink3)}
.tray .pill button:hover{color:var(--red)}
.cmp th[scope=row]{color:var(--ink3);font-weight:500;font-size:13px;width:170px}
.cmp thead th{font-size:14px;color:var(--ink);font-weight:600;letter-spacing:-.015em;text-transform:none}
.cmp{table-layout:fixed}.cmp td{overflow-wrap:anywhere}
.cmp-wrap{overflow-x:auto;max-width:100%;-webkit-overflow-scrolling:touch}
.cmp thead td{width:170px}
.cmp th[scope=row],.cmp thead td{position:sticky;left:0;z-index:1;background:#fff;box-shadow:1px 0 0 var(--line2)}
.cmp thead td{background:var(--surf2)}
.cmp .cell{justify-content:flex-start}
.chl{margin:4px 0 0;padding-left:18px;font-size:13px;color:var(--ink2)}
.chl li{padding:1px 0}
.picker{position:relative;max-width:420px}
.picker ul{list-style:none;margin:6px 0 0;padding:0}
.picker li button{width:100%;text-align:left;border:0;background:none;padding:9px 10px;border-radius:8px;min-height:40px}
.picker li button:hover{background:var(--surf2)}
.ans{padding:16px 0;border-top:1px solid var(--line2)}
.ans:first-child{border-top:0}
.ans .q{font-weight:600;letter-spacing:-.015em}
.ans p{margin-top:8px;line-height:1.6}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.stat{padding:16px}
.stat b{display:block;font:600 15px/1.35 var(--mono);letter-spacing:-.01em;margin-top:2px;overflow-wrap:anywhere}
.stat span{font-size:12px;color:var(--ink3)}
.toast{position:fixed;z-index:70;left:50%;top:68px;transform:translateX(-50%);background:var(--ink);color:#fff;padding:8px 14px;border-radius:999px;font-size:13px;opacity:0;pointer-events:none;transition:opacity .2s}
.toast.on{opacity:1}
.foot{max-width:1180px;margin:0 auto;padding:24px 24px 40px;color:var(--ink3);font-size:12.5px;border-top:1px solid var(--line)}
@media (max-width:1100px){
 .co,.co-head{grid-template-columns:minmax(0,1fr) 180px 72px 120px 56px 36px}
 .co .web,.co-head .web{display:none}
 .kpis{grid-template-columns:repeat(3,minmax(0,1fr))}
}
@media (max-width:900px){.grid2{grid-template-columns:1fr}}
@media (max-width:759px){
 body{font-size:14px;padding-bottom:calc(68px + env(safe-area-inset-bottom))}
 h1{font-size:24px}
 .top-in{padding:0 16px;gap:12px;height:56px}.wrap{padding:0 16px}.foot{padding:24px 16px}
 .qs{width:auto;flex:1;max-width:none}
 .nav{position:fixed;left:0;right:0;bottom:0;z-index:35;background:#fff;border-top:1px solid var(--line);justify-content:space-around;padding:0 4px env(safe-area-inset-bottom)}
 .nav a{flex-direction:column;gap:2px;font-size:11px;padding:8px 4px;min-height:56px;min-width:64px;justify-content:center;box-shadow:inset 0 2px 0 transparent}
 .nav a[aria-current=page]{box-shadow:inset 0 2px 0 var(--red)}
 .nav svg{display:block;width:20px;height:20px}
 .band{padding:24px 0 4px}
 .tiles{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
 .tiles .tile:first-child{grid-column:1/-1}
 .tile{padding:12px 14px}.tile b{font-size:24px}
 .co-head{display:none}
 .mob{display:inline}
 .co{grid-template-columns:minmax(0,1fr) auto;gap:8px 12px;padding:14px 12px 14px 16px}
 .co-figs{display:flex;flex-wrap:wrap;gap:6px;grid-column:1/-1;grid-row:2}
 .co-f,.co .web{display:inline-flex!important;align-items:center;background:var(--surf2);border-radius:999px;padding:3px 10px;font-size:12px;max-width:100%}
 .co-f:empty{display:none!important}
 .co .areas{grid-column:1;grid-row:3}
 .co .ghost{grid-column:2;grid-row:1;width:auto;height:44px;padding:0 12px;border-color:var(--line)}
 .ghost .gl{position:static;transform:none;opacity:1;background:none;color:inherit;padding:0}
 .co-b{justify-content:flex-start}
 .kpis{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
 .kpi{padding:12px}
 .kpi .kv1{font-size:16px}
 .btn,.chip,.src,.tabs button,.copy,.srcl{min-height:44px}
 .copy{padding:0 12px}.src{padding:0 12px}
 .cite2{height:28px;padding:0 8px}
 .fact{grid-template-columns:minmax(0,1fr) auto;gap:4px 10px}
 .fact dt{grid-column:1/-1}
 .t-wrap{overflow:visible}
 table.t.stack-m,.t.stack-m tbody,.t.stack-m tr,.t.stack-m td,.t.stack-m th{display:block;width:100%}
 .t.stack-m thead{display:none}
 .t.stack-m tr{border:1px solid var(--line);border-radius:12px;padding:6px 12px;margin-bottom:8px}
 .t.stack-m td,.t.stack-m th{border-top:1px solid var(--line2);padding:8px 0;text-align:left}
 .t.stack-m tr>*:first-child{border-top:0}
 .t.stack-m td[data-label]::before{content:attr(data-label);display:block;font-size:11.5px;color:var(--ink3);margin-bottom:2px}
 .t.stack-m .cell{justify-content:flex-start}
 .cmp thead td,.cmp th[scope=row]{width:112px;min-width:112px;font-size:12.5px}
 .ti{grid-template-columns:minmax(0,1fr) auto;gap:0 8px}
 .ti .d{grid-column:1/-1;padding:0 0 0 20px;border-left:1px solid var(--line)}
 .drawer{top:auto;left:0;width:100%;max-height:86vh;border-radius:16px 16px 0 0;box-shadow:0 -16px 48px rgba(0,0,0,.16)}
 .dr-h{padding:14px 16px}.dr-b{padding:0 16px 28px}
 .icon{width:44px;height:44px}
 .kv{grid-template-columns:1fr}.kv dt{margin-top:6px}
 .tray{bottom:calc(68px + env(safe-area-inset-bottom));left:12px;right:12px;transform:none;justify-content:space-between}
 .tray .pill{display:none}
 .toast{top:64px}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important;scroll-behavior:auto!important}}
"""

_JS = r"""
'use strict';
const RAW=JSON.parse(document.getElementById('varde-data').textContent);
(function(){const K=["source_url","retrieved_at","content_sha256","snapshot_path","source_class","licence"];
for(const e of RAW.envelopes||[]){const S=e._snaps||[];for(const ev of e.evidence||[]){const row=S[ev._s];if(row){K.forEach((k,i)=>{if(row[i]!=null)ev[k]=row[i]})}delete ev._s}delete e._snaps}})();
const META=RAW.meta||{};
const SL={available:'Available',not_available:'Not available',blocked:'Blocked by source',not_applicable:'Not applicable',ambiguous:'Ambiguous: could not prove it is this company',failed:'Failed'};
const FIN_L={revenue:'Revenue',sales_revenue:'Sales revenue',operating_result:'Operating result',profit_before_tax:'Profit before tax',annual_result:'Annual result',salary_costs:'Salary costs',total_assets:'Total assets',equity:'Equity',total_debt:'Total debt',cash:'Cash'};
const FIN=Object.keys(FIN_L);
const AREAS=[['identity','Identity'],['financials','Financials'],['leadership','People & places'],['web_presence','Website & profiles'],['activity','Hiring & activity']];
const CLS={official_registry:'Official registry',company_owned:'Company website',official_api:'Official API',open_knowledge_base:'Open knowledge base'};
const TLL={job_ad:'Job ad',dated_news:'News',public_record:'Public record',registry_update:'Registry update',hiring_signal:'Careers page'};
const PEOPLE=['role','roles','workplace'],WEB=['official_website','website_title','website_description','social_profile','related_website'],ACT=['hiring_signal','job_ad','dated_news','public_record','registry_update'];
const MM={orgnr_on_page:'Organisation number printed on the site',registry_phone_and_name:'Phone number from the register and the company name appear on the site',registry_email_and_name:'Email address from the register and the company name appear on the site',registry_website_and_name:'Website declared in the register and the company name appears on it',name_and_registered_address:'Company name and registered address appear on the site',linked_from_verified_site:'Linked from the verified company website',orgnr_in_request:'Looked up by organisation number in the official register',employer_orgnr_in_ad:'Employer organisation number in the job ad',registeredAs_equals_orgnr:'The record is registered under this organisation number',P2333_equals_orgnr:'Wikidata lists this organisation number for the item',winner_identifier_equals_orgnr:'The winning supplier is identified by this organisation number',buyer_identifier_equals_orgnr:'The buyer is identified by this organisation number',company_board_linked_from_verified_site:'Board page linked from the verified company website',wikidata_item_with_matching_website:'Wikidata item lists the same verified website',verified_site:'Found on the verified company website',declared_in_register:'Declared in the official register',parent_orgnr_in_request:'Looked up by the parent organisation number in the official register',orgnr_in_feed_record:'Organisation number in the source record'};
function hum(k){return String(k||'').replace(/_/g,' ').replace(/([a-z])([A-Z])/g,'$1 $2').toLowerCase().replace(/^./,x=>x.toUpperCase())}
function mm(m){return MM[m]||hum(m)}
function acct(t){return {SELSKAP:'company accounts',KONSERN:'group accounts'}[t]||(t?String(t).toLowerCase()+' accounts':'')}
const REL={parent:'parent company',subsidiary:'subsidiary',sibling:'sister company',owner:'owner',owned:'owned company'};
const LBL={related_website:'Website declared in the register, run by another organisation',register_registrertIForetaksregisteret:'In the Register of Business Enterprises',register_registrertIMvaregisteret:'Registered for VAT',register_registrertIFrivillighetsregisteret:'In the Register of Non-Profit Organisations',register_registrertIStiftelsesregisteret:'In the Register of Foundations',status_konkurs:'Bankrupt',status_underAvvikling:'Being wound up',status_underTvangsavviklingEllerTvangsopplosning:'Under compulsory dissolution',in_group:'Part of a group',isin:'ISIN',lei:'Legal Entity Identifier',wikidata_item:'Wikidata item',accounts_audited:'Accounts audited',accounts_audit_opted_out:'Audit opted out'};
function lab(x){return x.field==='related_website'?LBL.related_website:(x.label||LBL[x.field]||hum(x.field))}
const d10=s=>String(s||'').slice(0,10);
function amtOf(f,a){if(typeof a==='string'&&a.trim()[0]==='{'){try{const o=JSON.parse(a);const k={operating_result:'driftsresultat',revenue:'sumDriftsinntekter'}[f];if(k&&o[k]!=null)return String(o[k]);for(const n in o)if(typeof o[n]==='number')return String(o[n])}catch(e){}}return a}
const MONO=new Set(['organisation_number','founded','registered_employees','share_capital','lei','isin','registered_date','registry_phone'].concat(FIN));
const TABS=[['overview','Overview'],['financials','Financials'],['people','Leadership & workplaces'],['web','Website & profiles'],['activity','Hiring & activity'],['changes','Changes'],['sources','Sources']];

/* dom helpers */
function h(t,a,...k){const e=document.createElement(t);if(a)for(const n in a){const v=a[n];if(v==null||v===false)continue;
 if(n==='class')e.className=v;else if(n.slice(0,2)==='on')e.addEventListener(n.slice(2),v);else e.setAttribute(n,v===true?'':String(v))}add(e,k);return e}
function add(e,k){for(const c of k){if(c==null||c===false||c==='')continue;if(Array.isArray(c))add(e,c);else e.appendChild(c instanceof Node?c:document.createTextNode(String(c)))}}
const $=s=>document.querySelector(s);
const SVGNS='http://www.w3.org/2000/svg';
function svgEl(t,a){const e=document.createElementNS(SVGNS,t);for(const k in a)e.setAttribute(k,a[k]);return e}
function svg(vb,parts,cls){const s=svgEl('svg',{viewBox:vb,'aria-hidden':'true'});if(cls)s.setAttribute('class',cls);for(const [t,a] of parts)s.appendChild(svgEl(t,a));return s}
const IC={doc:()=>svg('0 0 12 12',[['path',{d:'M3 1.5h4l2 2v7H3z M7 1.5v2h2'}]]),plus:()=>svg('0 0 16 16',[['path',{d:'M8 3.5v9M3.5 8h9'}]]),check:()=>svg('0 0 14 14',[['path',{d:'M3 7.5l2.5 2.5L11 4.5'}]]),dash:()=>svg('0 0 14 14',[['path',{d:'M4 7h6'}]])};
function rc(e,...k){e.replaceChildren();add(e,k);return e}
const isO=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
function safeUrl(u){u=String(u||'').trim();if(/^https?:\/\//i.test(u))return u;if(/^[a-z0-9.-]+\.[a-z]{2,}(\/\S*)?$/i.test(u))return 'https://'+u;return ''}
function safeRel(p){p=String(p||'');return p&&!/^[a-z][a-z0-9+.-]*:/i.test(p)&&!p.startsWith('//')?p:''}
function link(u,text){const s=safeUrl(u);return s?h('a',{href:s,target:'_blank',rel:'noopener noreferrer'},text||u):h('span',null,text||u||'')}
function toast(m){const t=$('#toast');t.textContent=m;t.classList.add('on');clearTimeout(toast.t);toast.t=setTimeout(()=>t.classList.remove('on'),1600)}
function copy(s){const done=()=>toast('Copied');try{navigator.clipboard.writeText(s).then(done,()=>fb())}catch(e){fb()}
 function fb(){const a=h('textarea',{class:'sr'});a.value=s;document.body.appendChild(a);a.select();try{document.execCommand('copy');done()}catch(e){toast('Copy failed')}a.remove()}}
function store(k,v){try{if(v===undefined)return JSON.parse(sessionStorage.getItem(k)||'null');sessionStorage.setItem(k,JSON.stringify(v))}catch(e){return null}}

/* formatting: display only, never arithmetic on figures */
function amt(a,cur){if(a==null||a==='')return '';let s=String(a).trim(),sg='';if(s[0]==='-'||s[0]==='+'){sg=s[0]==='-'?'-':'';s=s.slice(1)}
 const p=s.split('.');if(!/^\d+$/.test(p[0]))return String(a)+(cur?' '+cur:'');const i=p[0].replace(/\B(?=(\d{3})+(?!\d))/g,' ');
 const d=p[1]&&/[1-9]/.test(p[1])?'.'+p[1]:'';return sg+i+d+(cur?' '+cur:'')}
function org(n){n=String(n||'');return /^\d{9}$/.test(n)?n.slice(0,3)+' '+n.slice(3,6)+' '+n.slice(6):n}
function dt(s){s=String(s||'');const m=s.match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/);return m?m[1]+' '+m[2]+(/Z$|\+00:?00$/.test(s)?' UTC':''):s}
function per(p){p=String(p||'');const m=p.match(/^(\d{4}-\d{2}-\d{2})\/(\d{4}-\d{2}-\d{2})$/);if(!m)return p;
 return m[1].slice(5)==='01-01'&&m[2].slice(5)==='12-31'&&m[1].slice(0,4)===m[2].slice(0,4)?m[1].slice(0,4):m[1]+' to '+m[2]}
function title(s){return String(s||'').toLowerCase().replace(/(^|[\s-])(\p{L})/gu,(a,b,c)=>b+c.toUpperCase())}
function flat(v){if(v==null)return '';if(Array.isArray(v))return v.map(flat).filter(Boolean).join(v.some(isO)?' | ':', ');
 if(isO(v))return Object.keys(v).filter(k=>v[k]!=null&&v[k]!==''&&!/^(url|raw|role_code|rank|path)$/.test(k)).map(k=>hum(k)+': '+flat(v[k])).join('; ');
 if(typeof v==='boolean')return v?'Yes':'No';return String(v)}
function addr(v){if(!isO(v))return flat(v);const a=v.address||v.adresse;const L=[];if(a)L.push(Array.isArray(a)?a.join(', '):String(a));
 const t=[v.postcode||v.postnummer,v.city||v.poststed].filter(Boolean).join(' ');if(t)L.push(t);return L.length?L.join(', '):flat(v)}
function fv(c){const v=c.value,f=c.field;if(v==null)return '';
 if(FIN.includes(f))return isO(v)?amt(amtOf(f,v.amount),v.currency):flat(v);
 if(f==='share_capital'){if(!isO(v))return flat(v);const ex=[v.type,v.shares!=null&&amt(v.shares)+' shares',v.since&&'since '+d10(v.since)].filter(Boolean);return amt(v.amount,v.currency)+(ex.length?' ('+ex.join(', ')+')':'')}
 if(f==='accounts_audited'||f==='accounts_audit_opted_out')return isO(v)?(v.value?'Yes':'No')+(v.period?' ('+per(v.period)+(v.account_type?', '+acct(v.account_type):'')+')':''):flat(v);
 if(f==='former_names')return (Array.isArray(v)?v:[v]).map(n=>isO(n)?(n.name||'')+(n.from||n.to?' ('+[n.from&&'from '+d10(n.from),n.to&&'to '+d10(n.to)].filter(Boolean).join(' ')+')':''):String(n)).join('; ');
 switch(f){case 'organisation_number':return org(v);
  case 'legal_form':case 'institutional_sector':return isO(v)?[v.description,v.code&&'('+v.code+')'].filter(Boolean).join(' '):flat(v);
  case 'industry':return isO(v)?[v.code,v.description].filter(Boolean).join(' '):flat(v);
  case 'registered_address':return addr(v);
  case 'role':return isO(v)?[v.name,v.role].filter(Boolean).join(', '):flat(v);
  case 'workplace':return isO(v)?[v.name,addr(v.address)].filter(Boolean).join(', '):flat(v);
  case 'job_ad':return isO(v)?v.title||flat(v):flat(v);
  case 'dated_news':return c.title||(isO(v)?v.title:String(v).replace(/\s*\(\d{4}-\d{2}-\d{2}[^)]*\)\s*$/,''));
  case 'public_record':return isO(v)?v.title||v.type||flat(v):flat(v);
  case 'registry_update':return isO(v)?(v.type||'Update')+(Array.isArray(v.changes)&&v.changes.length?': '+v.changes.map(x=>x.field||hum(x.path)).join(', '):v.changed_fields?': '+flat(v.changed_fields):''):flat(v);
  case 'group_relation':return isO(v)?[v.name,v.organisation_number&&'('+org(v.organisation_number)+')'].filter(Boolean).join(' ')+[v.relation&&(REL[v.relation]||v.relation),v.ownership_basis,v.since&&'since '+d10(v.since)].filter(Boolean).map(x=>', '+x).join(''):flat(v);
  case 'role_in_other_entity':return isO(v)?(v.role||'Role')+' in '+[v.name,v.organisation_number&&'('+org(v.organisation_number)+')'].filter(Boolean).join(' ')+(v.share!=null?', share '+v.share:''):flat(v);
  case 'lei':return isO(v)?(v.lei||v.id||'')+(v.status||v.next_renewal?' ('+[v.status&&String(v.status).toLowerCase(),v.next_renewal&&'renewal due '+d10(v.next_renewal)].filter(Boolean).join(', ')+')':''):flat(v);
  case 'wikidata_item':return isO(v)?[v.label,v.qid&&'('+v.qid+')'].filter(Boolean).join(' '):flat(v);
  case 'isin':return isO(v)?v.isin||v.code||flat(v):flat(v);
  case 'related_website':return isO(v)?v.domain||v.website||v.url||flat(v):flat(v)}
 if(/^(status_|register_|in_group)/.test(f)&&typeof v==='boolean')return v?'Yes':'No';
 if(f.startsWith('status_')&&typeof v==='boolean')return v?'Yes':'No';return flat(v)}
function urlOf(c){const v=c.value;return c.url||(isO(v)&&v.url)||((c.field==='official_website'||c.field==='hiring_signal'||c.field==='social_profile')&&typeof v==='string'?v:'')}
function dateOf(c){const v=c.value;let d=(isO(v)&&(v.published||v.date))||c.published||'';if(!d&&typeof v==='string'){const m=v.match(/\((\d{4}-\d{2}-\d{2})/);if(m)d=m[1]}return d||c.as_of||''}
function perOf(c){return (isO(c.value)&&c.value.period)||c.reporting_period||''}

/* index */
const CO=[],BY={};
function av(c,f){return (c.by[f]||[]).filter(x=>x.availability==='available')}
function latest(c,f,period){const xs=av(c,f).filter(x=>isO(x.value)&&(!period||perOf(x)===period));
 xs.sort((a,b)=>(perOf(b).slice(-10)).localeCompare(perOf(a).slice(-10))||((a.value.account_type==='SELSKAP')?-1:1));return xs[0]||null}
function flags(c){const L=[];for(const x of c.e.claims||[])if(x.availability==='available'&&x.value===true&&/^status_(konkurs|underAvvikling|underTvang)/.test(x.field))L.push(x.field==='status_konkurs'?'Bankrupt':'Winding up');return [...new Set(L)]}
for(const e of RAW.envelopes||[]){const c={e,id:String(e.organisation_number||''),cl:{},ev:{},by:{}};
 for(const x of e.claims||[]){c.cl[x.id]=x;(c.by[x.field]||(c.by[x.field]=[])).push(x)}
 for(const v of e.evidence||[])c.ev[v.id]=v;
 const ln=av(c,'legal_name')[0];c.name=String(e.legal_name||(ln&&ln.value)||'Unnamed company');
 const ad=av(c,'registered_address')[0];let mu='';
 if(ad){const v=ad.value;if(isO(v))mu=v.municipality||v.kommune||v.city||v.poststed||'';else{const m=String(v).match(/\b\d{4}\s+([^,]+)$/);if(m)mu=m[1]}}
 if(!mu){const w=av(c,'workplace')[0];if(w&&isO(w.value))mu=w.value.municipality||''}
 c.muni=mu?title(isO(mu)?flat(mu):mu):'';
 const ind=(c.by.industry||[]).filter(x=>x.availability==='available').sort((a,b)=>((a.value||{}).rank||9)-((b.value||{}).rank||9))[0];
 c.ind=ind?(isO(ind.value)?ind.value.description||'':flat(ind.value)):'';c.indc=ind&&isO(ind.value)?ind.value.code||'':'';
 const lf=av(c,'legal_form')[0];c.form=lf?(isO(lf.value)?lf.value.code||lf.value.description:flat(lf.value)):'';
 c.areas=AREAS.map(([k])=>(e.claims||[]).some(x=>x.section===k&&x.availability==='available'));
 c.n=(e.claims||[]).filter(x=>x.availability==='available').length;
 const rv=latest(c,'revenue');c.rev=rv?parseFloat(rv.value.amount):null;
 c.badges=flags(c);
 c.f={web:av(c,'official_website').length>0,acc:FIN.some(f=>av(c,f).length),hire:av(c,'job_ad').length>0,news:av(c,'dated_news').length>0,chg:(e.changes||[]).length>0,bank:c.badges.length>0};
 c.s=[c.name,c.id,c.muni,c.ind,c.indc].join(' ').toLowerCase();CO.push(c);BY[c.id]=c}

/* shared bits */
function state(x){const s=x.availability||'failed';return h('span',null,h('span',{class:'st '+s},SL[s]||s),x.reason?h('span',{class:'reason'},x.reason):null)}
function srcBtn(c,ids,label){ids=(ids||[]).filter(id=>c.cl[id]&&(c.cl[id].evidence_ids||[]).length);if(!ids.length)return null;
 return h('button',{type:'button',class:'src','aria-label':'Show source for '+(label||'this value'),onclick:ev=>openDrawer(c,ids,null,ev.currentTarget)},'Source')}
function val(c,x){if(x.availability!=='available')return state(x);const v=x.value;
 if(x.field==='registry_update'&&isO(v)&&Array.isArray(v.changes)&&v.changes.length)return h('span',null,v.type||'Update',h('ul',{class:'chl'},v.changes.map(ch=>h('li',null,(ch.field||hum(ch.path))+': ',h('span',{class:'ink'},ch.new_value==null||ch.new_value===''?'removed':flat(ch.new_value))))));
 if(x.field==='former_names'&&Array.isArray(v)&&v.length>1)return h('ul',{class:'chl'},v.map(n=>h('li',null,fv({field:'former_names',value:[n]}))));
 const t=fv(x),u=urlOf(x),cls=MONO.has(x.field)?'mono':null;
 return u&&safeUrl(u)?link(u,t||u):h('span',{class:cls},t)}
function factRow(c,x,cont){return h('div',{class:'fact'+(cont?' cont':'')},h('dt',null,cont?h('span',{class:'sr'},lab(x)):lab(x)),h('dd',null,val(c,x),x.availability==='available'&&FIN.includes(x.field)&&perOf(x)?h('span',{class:'reason'},per(perOf(x))+(x.value.account_type?', '+acct(x.value.account_type):'')):null),h('div',null,srcBtn(c,[x.id],lab(x))))}
function facts(c,xs){if(!xs.length)return null;const dl=h('dl',{class:'facts'});let i=0;
 while(i<xs.length){let j=i;while(j<xs.length&&xs[j].field===xs[i].field)j++;const g=xs.slice(i,j).map((x,k)=>factRow(c,x,k>0));
  if(g.length>6){g.slice(5).forEach(r=>r.hidden=true);const b=h('div',{class:'fact cont'},h('dt',{class:'sr'},'More'),h('dd',null,h('button',{type:'button',class:'btn',onclick:()=>{g.forEach(r=>r.hidden=false);b.remove()}},'Show all '+g.length)));add(dl,[g,b])}else add(dl,g);i=j}return dl}
function areasEl(c){const on=AREAS.filter((a,i)=>c.areas[i]).map(a=>a[1]);
 return h('span',{class:'areas',role:'img','aria-label':'Areas found: '+(on.join(', ')||'none')},AREAS.map((a,i)=>h('i',{class:c.areas[i]?'on':null,title:a[1]+(c.areas[i]?': found':': not found')})))}
function badges(c){return c.badges.map(b=>h('span',{class:'badge alert'},b)).concat(c.e.state&&c.e.state!=='complete'?[h('span',{class:'badge'},'Run '+c.e.state)]:[])}
function tbl(heads,rows,cls){return h('div',{class:'t-wrap'},h('table',{class:'t stack-m '+(cls||'')},h('thead',null,h('tr',null,heads.map(x=>h('th',{scope:'col'},x)))),
 h('tbody',null,rows.map(r=>h('tr',null,r.map((cell,i)=>i===0&&r.rowHead?h('th',{scope:'row'},cell):h('td',{'data-label':heads[i]||null},cell)))))))}

function series(c,f){const m={};for(const x of av(c,f))if(isO(x.value)&&x.value.account_type!=='KONSERN')m[perOf(x).slice(-10)]=x;return Object.keys(m).sort().map(k=>m[k])}
function latestCo(c,f){const s=series(c,f);return s.length?s[s.length-1]:latest(c,f)}
function numOf(x){return parseFloat(amtOf(x.field,x.value.amount))}
function cmpGhost(c){const on=CMP.includes(c.id);const b=h('button',{type:'button',class:'ghost','data-cmp':c.id,'data-ghost':'1','aria-pressed':on,'aria-label':(on?'Remove ':'Add ')+c.name+(on?' from':' to')+' compare',onclick:()=>toggleCmp(c.id)});ghostFill(b,on);return b}
function ghostFill(b,on){rc(b,on?IC.check():IC.plus(),h('span',{class:'gl','aria-hidden':'true'},on?'In compare':'Compare'))}
function hireTxt(c){const j=av(c,'job_ad').length;return j?j+' open position'+(j===1?'':'s'):av(c,'hiring_signal').length?'Careers page only':'News or records found'}
/* compare selection */
let CMP=(store('varde-cmp')||[]).filter(id=>BY[id]).slice(0,3);
function setCmp(ids){CMP=ids.filter((x,i)=>BY[x]&&ids.indexOf(x)===i).slice(0,3);store('varde-cmp',CMP);
 document.querySelectorAll('[data-cmp]').forEach(b=>{const on=CMP.includes(b.dataset.cmp);b.setAttribute('aria-pressed',on);if(b.dataset.ghost){ghostFill(b,on);b.setAttribute('aria-label',(on?'Remove ':'Add ')+BY[b.dataset.cmp].name+(on?' from':' to')+' compare')}else b.textContent=on?'Added to compare':'Compare'});tray()}
function toggleCmp(id){if(CMP.includes(id))setCmp(CMP.filter(x=>x!==id));else if(CMP.length>=3)toast('You can compare up to 3 companies');else setCmp(CMP.concat(id))}
function cmpBtn(c){const on=CMP.includes(c.id);return h('button',{type:'button',class:'btn','data-cmp':c.id,'aria-pressed':on,'aria-label':(on?'Remove ':'Add ')+c.name+(on?' from':' to')+' compare',onclick:()=>toggleCmp(c.id)},on?'Added to compare':'Compare')}
function tray(){const t=$('#tray');const hide=!CMP.length||R.name==='compare';t.hidden=hide;if(hide)return;
 rc(t,h('span',{class:'tl-n'},CMP.length+' of 3 selected'),CMP.map(id=>h('span',{class:'pill'},h('span',null,BY[id].name),h('button',{type:'button','aria-label':'Remove '+BY[id].name+' from compare',onclick:()=>setCmp(CMP.filter(x=>x!==id))},'×'))),
 h('a',{class:'btn pri',href:'#/compare?ids='+CMP.join(',')},'Compare '+CMP.length))}

/* drawer */
let drOpener=null;
function evBlock(c,v){const sha=String(v.content_sha256||''),snap=safeRel(v.snapshot_path);
 return h('div',null,v.claim_span?[h('div',{class:'qlab'},v.span_exact===false?'Quoted text (normalised)':'Exact quote from the source'),h('pre',{class:'quote'},v.claim_span)]:h('div',{class:'qlab'},'No quote recorded for this source'),
 h('dl',{class:'kv'},h('dt',null,'Source'),h('dd',null,v.source_url?link(v.source_url):'Not recorded'),
  h('dt',null,'Source type'),h('dd',null,CLS[v.source_class]||v.source_class||'Unknown'),
  h('dt',null,'Retrieved'),h('dd',{class:'num'},dt(v.retrieved_at)),
  h('dt',null,'SHA-256'),h('dd',null,sha?[h('span',{class:'num',title:sha},sha.slice(0,16)+'…'),h('button',{type:'button',class:'copy','aria-label':'Copy full SHA-256 hash',onclick:()=>copy(sha)},'Copy')]:'Not recorded'),
  h('dt',null,'Snapshot'),h('dd',null,snap?h('a',{href:snap,target:'_blank',rel:'noopener'},h('span',{class:'mono'},snap)):'Not stored'),
  v.extraction_method?[h('dt',null,'Extraction'),h('dd',{class:'mono'},v.extraction_method)]:null,
  h('dt',null,'Licence'),h('dd',null,v.licence||'Not stated'),
  v.note?[h('dt',null,'Note'),h('dd',null,v.note)]:null))}
function openDrawer(c,ids,evIds,opener){drOpener=opener||document.activeElement;const b=$('#dr-b');rc(b);
 for(const id of ids||[]){const x=c.cl[id];if(!x)continue;
  b.appendChild(h('section',{class:'dc'},h('div',{class:'muted'},lab(x)),h('div',{class:'v'+(MONO.has(x.field)?' num':'')},x.availability==='available'?(fv(x)||'(empty)'):state(x)),
   h('dl',{class:'kv'},h('dt',null,'Company'),h('dd',null,c.name),
    x.match?[h('dt',null,'Match method'),h('dd',null,mm(x.match.method),x.match.detail?h('span',{class:'reason'},x.match.detail):null)]:null,
    perOf(x)?[h('dt',null,'Period'),h('dd',null,h('span',{class:'num'},perOf(x)),isO(x.value)&&x.value.account_type?', '+acct(x.value.account_type):'')]:null,
    x.as_of?[h('dt',null,'As of'),h('dd',{class:'num'},x.as_of)]:null,
    urlOf(x)?[h('dt',null,'Link'),h('dd',null,link(urlOf(x)))]:null),
   (x.evidence_ids||[]).map(e=>c.ev[e]?evBlock(c,c.ev[e]):h('p',{class:'st'},'Evidence '+e+' is missing from this record.'))))}
 for(const id of evIds||[]){const v=c.ev[id];if(!v)continue;const used=(c.e.claims||[]).filter(x=>(x.evidence_ids||[]).includes(id));
  b.appendChild(h('section',{class:'dc'},h('div',{class:'muted'},'Evidence '+id),h('div',{class:'v'},used.length?'Supports: '+[...new Set(used.map(x=>lab(x)))].join(', '):'Not cited by any fact'),evBlock(c,v)))}
 $('#dr-t').textContent=(ids&&ids.length>1)?ids.length+' cited facts':'Source';
 $('#scrim').hidden=false;$('#drawer').hidden=false;$('#dr-x').focus()}
function closeDrawer(){if($('#drawer').hidden)return;$('#drawer').hidden=true;$('#scrim').hidden=true;if(drOpener&&drOpener.focus)drOpener.focus()}
$('#dr-x').addEventListener('click',closeDrawer);$('#scrim').addEventListener('click',closeDrawer);
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeDrawer();
 if(e.key==='Tab'&&!$('#drawer').hidden){const f=[...$('#drawer').querySelectorAll('button,a[href]')];if(!f.length)return;const a=f[0],z=f[f.length-1];
  if(e.shiftKey&&document.activeElement===a){e.preventDefault();z.focus()}else if(!e.shiftKey&&document.activeElement===z){e.preventDefault();a.focus()}}
 if(e.key==='/'&&!/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)){e.preventDefault();$('#qs').focus()}});

/* search */
function match(q){q=q.trim().toLowerCase();if(!q)return CO;if(/^[\d\s]+$/.test(q))q=q.replace(/\s/g,'');const t=q.split(/\s+/);return CO.filter(c=>t.every(w=>c.s.includes(w)))}
(function(){const i=$('#qs'),l=$('#qs-list');let hits=[],on=0;
 function draw(){rc(l,hits.map((c,k)=>h('li',{role:'option','aria-selected':k===on},h('a',{href:'#/companies/'+c.id,class:k===on?'on':null,tabindex:'-1'},c.name,h('small',null,org(c.id)+(c.muni?' · '+c.muni:''))))));
  l.hidden=!hits.length;i.setAttribute('aria-expanded',!l.hidden)}
 i.addEventListener('input',()=>{hits=i.value.trim()?match(i.value).slice(0,7):[];on=0;draw()});
 i.addEventListener('keydown',e=>{if(e.key==='ArrowDown'&&hits.length){e.preventDefault();on=(on+1)%hits.length;draw()}else if(e.key==='ArrowUp'&&hits.length){e.preventDefault();on=(on+hits.length-1)%hits.length;draw()}
  else if(e.key==='Enter'){e.preventDefault();if(hits.length)location.hash='#/companies/'+hits[on].id;else if(i.value.trim()){DS.q=i.value;DS.shown=50;if(location.hash==='#/'||!location.hash)render();else location.hash='#/'}close()}else if(e.key==='Escape'){close()}});
 function close(){hits=[];draw();i.value=''}
 l.addEventListener('click',()=>setTimeout(close,0));i.addEventListener('blur',()=>setTimeout(()=>{if(!l.contains(document.activeElement)){hits=[];draw()}},150))})();

/* directory */
const DS={q:'',f:new Set(),sort:'data',shown:50};
const FL=[['web','Has website'],['acc','Has accounts'],['hire','Hiring'],['news','Has news'],['chg','Changed since last run'],['bank','Bankrupt or winding up']];
function dirList(){let xs=match(DS.q).filter(c=>[...DS.f].every(k=>c.f[k]));
 const s=DS.sort;xs=xs.slice().sort(s==='name'?(a,b)=>a.name.localeCompare(b.name,'nb'):s==='rev'?(a,b)=>(b.rev==null?-Infinity:b.rev)-(a.rev==null?-Infinity:a.rev)||a.name.localeCompare(b.name,'nb'):(a,b)=>b.n-a.n||a.name.localeCompare(b.name,'nb'));return xs}
function trendEl(c,f){const s=series(c,f);if(s.length<2)return null;const a=numOf(s[s.length-1]),b=numOf(s[s.length-2]);if(isNaN(a)||isNaN(b))return null;
 const k=a>b?['↑','up from previous year']:a<b?['↓','down from previous year']:['→','same as previous year'];return h('span',{class:'trend',role:'img','aria-label':k[1],title:k[1]},k[0])}
function card(c){const r=latestCo(c,'revenue'),emp=av(c,'registered_employees')[0],web=av(c,'official_website')[0];
 const bd=[c.f.hire&&'Hiring',c.f.news&&'News',c.f.chg&&'Changed'].filter(Boolean).map(t=>h('span',{class:'badge'},t)).concat(c.badges.map(b=>h('span',{class:'badge alert'},b)));
 return h('li',{class:'co'},h('a',{class:'co-a',href:'#/companies/'+c.id},h('span',{class:'co-n'},c.name),h('span',{class:'co-m'},h('span',{class:'num'},org(c.id)),[c.form,c.muni,c.ind].filter(Boolean).map(x=>' · '+x))),
  h('div',{class:'co-figs'},
   h('div',{class:'co-f r'},h('span',{class:'sr'},'Operating income, latest company accounts: '),r?[h('span',{class:'mob'},'Income '),h('span',{class:'num'},fv(r)),trendEl(c,'revenue')]:h('span',{class:'st'},'No accounts')),
   h('div',{class:'co-f r'},h('span',{class:'sr'},'Employees: '),emp?[h('span',{class:'num'},String(emp.value)),h('span',{class:'mob'},' employees')]:h('span',{class:'st nowrap'},h('span',{class:'mob'},'Employees: '),'Not registered')),
   h('div',{class:'co-f web'},h('span',{class:'sr'},'Website: '),web?fv(web):h('span',{class:'st'},'No website found')),
   h('div',{class:'co-f co-b'},bd)),
  areasEl(c),cmpGhost(c))}
function viewDir(){const res=h('div'),cnt=h('p',{class:'count','aria-live':'polite'});
 function draw(){const xs=dirList();cnt.textContent=xs.length===CO.length?CO.length+' companies':xs.length+' of '+CO.length+' companies match';
  if(!xs.length){rc(res,h('div',{class:'card empty'},CO.length?'No companies match. Clear a filter or search for an organisation number.':'This run contains no companies.'));return}
  const ul=h('ul',{class:'list card'},xs.slice(0,DS.shown).map(card));const more=xs.length>DS.shown?h('div',{class:'more'},h('button',{type:'button',class:'btn',onclick:()=>{const st=DS.shown;DS.shown+=50;xs.slice(st,DS.shown).forEach(c=>ul.appendChild(card(c)));if(xs.length<=DS.shown)more.remove();else more.firstChild.textContent=showTxt(xs);ul.children[st]&&ul.children[st].querySelector('a').focus()}},showTxt(xs))):null;
  rc(res,h('div',{class:'co-head','aria-hidden':'true'},h('span',null,'Company'),h('span',{class:'r'},'Operating income'),h('span',{class:'r'},'Employees'),h('span',{class:'web'},'Website'),h('span'),h('span',null,'Areas'),h('span')),...[ul,more].filter(Boolean))}
 const showTxt=xs=>'Show '+Math.min(50,xs.length-DS.shown)+' more ('+(xs.length-DS.shown)+' left)';
 const sync=()=>{tiles.querySelectorAll('[data-k]').forEach(b=>{const k=b.dataset.k;b.setAttribute('aria-pressed',k?DS.f.has(k):DS.f.size===0)});chips.querySelectorAll('[data-k]').forEach(b=>b.setAttribute('aria-pressed',DS.f.has(b.dataset.k)))};
 const flip=k=>{if(!k)DS.f.clear();else if(DS.f.has(k))DS.f.delete(k);else DS.f.add(k);DS.shown=50;sync();draw()};
 const tiles=h('div',{class:'tiles',role:'group','aria-label':'Coverage, select to filter'},[['','companies'],['web','with a website'],['acc','with filed accounts'],['hire','hiring'],['news','with dated news']].map(([k,t])=>{const n=k?CO.filter(c=>c.f[k]).length:CO.length;
  return h('button',{type:'button',class:'tile','data-k':k,'aria-pressed':k?DS.f.has(k):DS.f.size===0,'aria-label':k?n+' '+t+', filter':'All '+n+' companies, clear filters',onclick:()=>flip(k)},h('b',null,String(n)),h('span',null,t))}));
 let tm;const q=h('input',{class:'field',type:'search',placeholder:'Search by name, organisation number, municipality or industry','aria-label':'Search companies',value:DS.q,oninput:e=>{clearTimeout(tm);tm=setTimeout(()=>{DS.q=e.target.value;DS.shown=50;draw()},90)}});
 const sort=h('select',{class:'field','aria-label':'Sort companies',onchange:e=>{DS.sort=e.target.value;DS.shown=50;draw()}},[['data','Most data found'],['name','Name A to Z'],['rev','Operating income, highest first']].map(([v,t])=>h('option',{value:v,selected:DS.sort===v},t)));
 const chips=h('div',{class:'chips',role:'group','aria-label':'Filters'},FL.map(([k,t])=>h('button',{type:'button',class:'chip','data-k':k,'aria-pressed':DS.f.has(k),onclick:()=>flip(k)},t,h('span',{class:'ct'},CO.filter(c=>c.f[k]).length))));
 draw();return [h('section',{class:'band'},h('div',{class:'wrap'},h('span',{class:'eyebrow'},'Run '+(META.run_id||'')),h('h1',null,'Companies'),h('p',{class:'lead'},'Every value links to the page it came from, with the quote, the time it was read and a SHA-256 of the saved copy.'),
  tiles,h('div',{class:'tools'},q,sort),chips)),h('section',{class:'wrap pad',style:'padding-top:0'},cnt,res)]}

/* profile */
function srcChip(c,ids){ids=(ids||[]).filter(id=>c.cl[id]);if(!ids.length)return null;
 return h('button',{type:'button',class:'cite2','aria-label':ids.length+' source'+(ids.length===1?'':'s')+' for this sentence',onclick:ev=>openDrawer(c,ids,null,ev.currentTarget)},IC.doc(),String(ids.length))}
function missing(c,fields){const x=fields.flatMap(f=>c.by[f]||[]).find(y=>y.availability!=='available');
 return x?[h('div',{class:'kv1 st'},x.availability==='ambiguous'?'Ambiguous':SL[x.availability]||'Not found'),x.reason?h('div',{class:'ks'},x.reason):null]:h('div',{class:'kv1 st'},'Not found')}
function kpi(c,label,x,body,sub,extra,fields){return h('div',{class:'card kpi'},h('span',{class:'eyebrow'},label),x?[h('div',{class:'kv1'},body),sub?h('div',{class:'ks'},sub):null]:missing(c,fields),
 h('div',{class:'kf'},extra||h('span'),x&&(x.evidence_ids||[]).length?h('button',{type:'button',class:'srcl','aria-label':'Source for '+label,onclick:ev=>openDrawer(c,[x.id],null,ev.currentTarget)},'Source'):null))}
function money(c,f,label){const x=latestCo(c,f);return kpi(c,label,x,x?[h('span',{class:'nowrap'},amt(amtOf(f,x.value.amount))),h('small',null,x.value.currency||'')]:null,x?per(perOf(x))+', '+acct(x.value.account_type||'SELSKAP'):null,f==='revenue'&&x?spark(series(c,f)):null,[f,'annual_accounts'])}
function spark(xs){const v=xs.map(numOf).map(n=>isNaN(n)?0:Math.abs(n));if(v.length<2)return null;const m=Math.max(...v)||1,s=svg('0 0 '+(v.length*8)+' 24',[],'spark');
 s.setAttribute('preserveAspectRatio','none');s.style.width=Math.min(64,v.length*10)+'px';s.setAttribute('role','img');s.removeAttribute('aria-hidden');s.setAttribute('aria-label','Bars for '+v.length+' filed years, latest highlighted');
 v.forEach((n,i)=>{const hh=Math.max(2,n/m*22);s.appendChild(svgEl('rect',{x:i*8+1,y:24-hh,width:5,height:hh,rx:1,fill:i===v.length-1?'#C8102E':'#C7C7CC'}))});return s}
function hostOf(u){try{return new URL(u).hostname}catch(e){return u}}
function howEl(c){const e=c.e,w=c.by.official_website||[],wa=w.find(x=>x.availability==='available');let proof;
 if(wa){const ev=(wa.evidence_ids||[]).map(i=>c.ev[i]).find(Boolean)||{},q=String(ev.claim_span||'');
  proof=h('div',{class:'proof'},h('div',null,h('strong',null,fv(wa)),h('span',{class:'reason'},mm((wa.match||{}).method))),q?h('pre',{class:'quote'},q.length>140?q.slice(0,140)+'…':q):null,
   h('div',{class:'row',style:'margin-top:8px;justify-content:space-between'},ev.source_url?link(ev.source_url,hostOf(ev.source_url)):h('span'),h('button',{type:'button',class:'srcl','aria-label':'Full source for the website proof',onclick:x=>openDrawer(c,[wa.id],null,x.currentTarget)},'Full source')))}
 else{const na=w[0];proof=h('div',null,h('p',{class:'st'},'No website could be proven for this company'),na&&na.reason?h('span',{class:'reason'},na.reason):null)}
 const n={};for(const v of e.evidence||[])n[v.source_class]=(n[v.source_class]||0)+1;
 const rows=[['official_registry','Official registers'],['company_owned','Company website'],['official_api','Public APIs'],['open_knowledge_base','Open knowledge bases']].filter(([k],i)=>i<3||n[k]);
 const sec=e.sections||{},done=(e.run||{}).completed_at||META.completed_at;
 return h('div',{class:'card box how'},h('span',{class:'eyebrow'},'Proof'),h('h2',null,'How we know'),
  h('h4',null,'Website proven by'),proof,
  h('h4',null,'Evidence by source'),h('dl',{class:'cnts'},rows.map(([k,t])=>[h('dt',null,t),h('dd',null,String(n[k]||0))])),
  h('h4',null,'Areas checked'),h('ul',{class:'check'},AREAS.map(([k,t],i)=>{const s=(sec[k]||{}).state,on=c.areas[i];
   return h('li',{class:on?'y':'n'},on?IC.check():IC.dash(),h('span',null,t),h('span',{class:'v'},on?(k==='activity'?hireTxt(c):'Found'):k==='activity'&&av(c,'hiring_signal').length?'Careers page only':s==='ambiguous'?'Ambiguous':SL[s]||'Nothing found'))})),
  done?h('p',{class:'muted',style:'margin-top:16px;font-size:12.5px'},'Last checked ',h('span',{class:'num'},dt(done))):null)}
function viewProfile(id,tab){const c=BY[id];if(!c)return [h('section',{class:'wrap pad'},h('div',{class:'card empty'},'No company with organisation number '+id+' is in this run. ',h('a',{href:'#/'},'Back to all companies')))];
 store('varde-last',id);const e=c.e,sm=e.summary||{},ss=sm.sentences||[];
 const sum=h('div',{class:'card box'},h('span',{class:'eyebrow'},'Summary'),h('h2',null,'What the sources say'),h('p',{class:'cap'},'Written from the facts below. Each sentence links to its sources.'),
  ss.length?h('p',{class:'sum'},ss.map((s,i)=>{const t=String(s.text||''),k=t.lastIndexOf(' ');return [i?' ':'',k>0?t.slice(0,k+1):'',h('span',{class:'nowrap'},k>0?t.slice(k+1):t,srcChip(c,s.claim_ids))]})):h('p',{class:'sum st'},sm.text||'No summary was produced for this company.'),
  (sm.unknowns||[]).length?h('div',{class:'unk'},h('strong',null,'Unknown'),h('ul',null,sm.unknowns.map(u=>h('li',null,u)))):null);
 const tl=h('div',{class:'tabs',role:'tablist','aria-label':'Profile sections'}),panel=h('div',{role:'tabpanel',id:'panel',tabindex:'0'});
 function show(t,focus){tl.querySelectorAll('button').forEach(b=>{const on=b.dataset.t===t;b.setAttribute('aria-selected',on);b.tabIndex=on?0:-1;if(on&&focus)b.focus()});
  panel.setAttribute('aria-labelledby','tab-'+t);rc(panel);add(panel,[PANELS[t](c)]);try{history.replaceState(null,'','#/companies/'+id+(t==='overview'?'':'?tab='+t))}catch(x){}}
 TABS.forEach(([t,l])=>{let k=l;if(t==='changes')k+=' ('+(e.changes||[]).length+')';if(t==='sources')k+=' ('+(e.evidence||[]).length+')';
  tl.appendChild(h('button',{type:'button',role:'tab',id:'tab-'+t,'data-t':t,'aria-controls':'panel',onclick:()=>show(t),onkeydown:ev=>{const i=TABS.findIndex(x=>x[0]===t);
   if(ev.key==='ArrowRight'||ev.key==='ArrowLeft'){ev.preventDefault();show(TABS[(i+(ev.key==='ArrowRight'?1:TABS.length-1))%TABS.length][0],true)}}},k))});
 show(PANELS[tab]?tab:'overview');
 const lf=av(c,'legal_form')[0],emp=av(c,'registered_employees')[0],fd=av(c,'founded')[0],web=av(c,'official_website')[0];
 const kp=h('div',{class:'kpis'},money(c,'revenue','Operating income'),money(c,'annual_result','Annual result'),money(c,'equity','Equity'),
  kpi(c,'Employees',emp,emp?String(emp.value):null,emp?'In the register':null,null,['registered_employees']),
  kpi(c,'Founded',fd,fd?String(fd.value):null,null,null,['founded']),
  kpi(c,'Website',web,web?link(urlOf(web)||fv(web),fv(web)):null,web?'Proven to belong to this company':null,null,['official_website']));
 return [h('section',{class:'band'},h('div',{class:'wrap'},h('a',{class:'crumb',href:'#/'},'All companies'),h('div',{class:'ph'},h('div',{style:'min-width:0'},h('h1',null,c.name),
  h('div',{class:'ph-meta'},h('span',null,h('span',{class:'num'},org(c.id)),h('button',{type:'button',class:'copy','aria-label':'Copy organisation number',onclick:()=>copy(c.id)},'Copy')),lf?h('span',null,fv(lf)):null,c.muni?h('span',null,c.muni):null,
   c.badges.length?c.badges.map(b=>h('span',{class:'badge alert'},b)):h('span',{class:'badge ok'},'Active'),e.state&&e.state!=='complete'?h('span',{class:'badge'},'Run '+e.state):null)),
  h('div',{class:'row'},cmpBtn(c),h('a',{class:'btn',href:'#/research?id='+c.id},'Ask about this company'))),
  kp,h('div',{class:'grid2'},sum,howEl(c)))),h('section',{class:'wrap',style:'padding-bottom:48px'},tl,h('div',{class:'card box'},panel))]}
function rest(c,fields){return fields.flatMap(f=>c.by[f]||[])}
function nonAv(c,fields){return rest(c,fields).filter(x=>x.availability!=='available')}
const AUD=['accounts_audited','accounts_audit_opted_out'];
const OV=['organisation_number','legal_form','industry','registered_address','postal_address','registered_employees','founded','registered_date','share_capital','registered_activity','statutory_purpose','former_names','registry_website','registry_email','registry_phone','institutional_sector','latest_filed_accounts_year','lei','isin','wikidata_item'];
const GRP=['in_group','group_relation','role_in_other_entity'];
function known(){return new Set(['legal_name','annual_accounts','financials'].concat(FIN,AUD,PEOPLE,WEB,ACT,OV,GRP))}
const PANELS={
 overview(c){const K=known(),xs=rest(c,['legal_name'].concat(OV)),gr=rest(c,GRP);
  const others=(c.e.claims||[]).filter(x=>!K.has(x.field)).sort((a,b)=>a.field.localeCompare(b.field));
  return [h('h3',{class:'sub-h'},'Registered identity'),facts(c,xs)||h('p',{class:'st'},'No identity facts were found.'),gr.length?[h('h3',{class:'sub-h'},'Group and other roles'),facts(c,gr)]:null,others.length?[h('h3',{class:'sub-h'},'Status and other register facts'),facts(c,others)]:null]},
 financials(c){const xs=FIN.flatMap(f=>av(c,f)).filter(x=>isO(x.value));const cols=[];const seen={};
  for(const x of xs){const k=perOf(x)+'|'+(x.value.account_type||'');if(!seen[k]){seen[k]=1;cols.push({k,p:perOf(x),t:x.value.account_type||''})}}
  cols.sort((a,b)=>b.p.slice(-10).localeCompare(a.p.slice(-10))||(a.t==='SELSKAP'?-1:b.t==='SELSKAP'?1:a.t.localeCompare(b.t)));
  const na=nonAv(c,FIN.concat(['annual_accounts','financials']));
  if(!cols.length)return [h('p',{class:'st'},'No filed annual accounts were found for this company.'),facts(c,rest(c,AUD)),facts(c,na)];
  const heads=['Figure'].concat(cols.map(o=>per(o.p)+(o.t?', '+acct(o.t):'')));
  const rows=FIN.filter(f=>av(c,f).length).map(f=>{const r=[FIN_L[f]].concat(cols.map(o=>{const x=av(c,f).find(y=>isO(y.value)&&perOf(y)+'|'+(y.value.account_type||'')===o.k);
   return x?h('span',{class:'cell'},h('span',{class:'num'},fv(x)),srcBtn(c,[x.id],FIN_L[f]+' '+per(o.p))):h('span',{class:'st'},'Not in filing')}));r.rowHead=true;return r});
  const t=tbl(heads,rows,'fin');t.querySelectorAll('thead th').forEach((th,i)=>{if(i){th.className='r';th.title=cols[i-1].p}});t.querySelectorAll('tbody td').forEach(td=>td.className='r');
  return [h('p',{class:'muted',style:'margin-bottom:12px'},'Amounts exactly as filed. Each column is one reporting period, from the company accounts or the group accounts.'),t,AUD.some(f=>c.by[f])?[h('h3',{class:'sub-h'},'Audit'),facts(c,rest(c,AUD))]:null,na.length?[h('h3',{class:'sub-h'},'Missing figures'),facts(c,na)]:null]},
 people(c){const roles=av(c,'role'),wps=av(c,'workplace');
  const rr=roles.map(x=>{const v=isO(x.value)?x.value:{};const r=[v.role||x.label||'Role',v.name||flat(v),v.kind==='entity'?'Organisation':v.kind==='person'?'Person':(v.kind||''),srcBtn(c,[x.id],(v.role||'Role')+' '+(v.name||''))];r.rowHead=true;return r});
  const wr=wps.map(x=>{const v=isO(x.value)?x.value:{};const r=[v.name||'Workplace',addr(v.address)||'Not recorded',v.municipality?title(v.municipality):'Not recorded',v.employees!=null?h('span',{class:'num'},String(v.employees)):h('span',{class:'st'},'Not registered'),srcBtn(c,[x.id],'workplace '+(v.name||''))];r.rowHead=true;return r});
  return [h('h3',{class:'sub-h'},'Roles ('+roles.length+')'),rr.length?tbl(['Role','Name','Kind',''],rr):null,facts(c,nonAv(c,['role','roles']))||(rr.length?null:h('p',{class:'st'},'No roles were found.')),
   h('h3',{class:'sub-h'},'Workplaces ('+wps.length+')'),wr.length?tbl(['Name','Address','Municipality','Employees',''],wr):null,facts(c,nonAv(c,['workplace']))||(wr.length?null:h('p',{class:'st'},'No registered workplaces were found.'))]},
 web(c){const xs=rest(c,WEB);return xs.length?facts(c,xs):h('p',{class:'st'},'No website or profiles were found for this company.')},
 activity(c){const items=rest(c,ACT).filter(x=>x.availability==='available').map(x=>({x,d:String(dateOf(x)||'')})).sort((a,b)=>b.d.localeCompare(a.d));
  const MN=['January','February','March','April','May','June','July','August','September','October','November','December'],G=[],idx={};
  for(const it of items){const k=/^\d{4}-\d{2}/.test(it.d)?it.d.slice(0,7):'Undated';if(!(k in idx)){idx[k]=G.length;G.push([k,[]])}G[idx[k]][1].push(it)}
  let first=true;const tl=h('div',{class:'tl2'},G.map(([k,its])=>[h('h3',{class:'month'},k==='Undated'?'Undated':MN[+k.slice(5,7)-1]+' '+k.slice(0,4)),h('ol',null,its.map(({x,d})=>{const v=isO(x.value)?x.value:{};
   const extra=(x.field==='job_ad'?[v.locations&&flat(v.locations),v.expires&&'Expires '+d10(v.expires)]:x.field==='public_record'?[v.source,v.reference]:[]).filter(Boolean);const f=first;first=false;
   return h('li',{class:'ti'+(f?' first':'')},h('span',{class:'d num'},/^\d{4}-\d{2}-\d{2}/.test(d)?d.slice(0,10):'No date'),h('div',{class:'ti-b'},h('span',{class:'tag'},TLL[x.field]||lab(x)),val(c,x),extra.length?h('span',{class:'reason'},extra.join(' · ')):null),srcBtn(c,[x.id],lab(x)))}))]));
  const na=nonAv(c,ACT);return [items.length?tl:h('p',{class:'st'},'No jobs, news, public records or registry updates were found.'),na.length?[h('h3',{class:'sub-h'},'Not found'),facts(c,na)]:null]},
 changes(c){const ch=c.e.changes||[];if(!ch.length)return h('p',{class:'st'},'No changes since the previous run. Either this is the first run for this company or nothing changed.');return ch.map(x=>chgEl(x))},
 sources(c){const r=c.e.run||{},op=c.e.operations||{},ev=c.e.evidence||[];
  return [h('div',{class:'stats',style:'margin-bottom:18px'},[['Run',r.run_id],['Status',r.terminal_status||c.e.state],['Completed',dt(r.completed_at)],['Requests',op.requests],['Runtime',op.runtime_ms!=null?(op.runtime_ms/1000).toFixed(1)+' s':''],['Errors',(c.e.errors||[]).length]].map(([k,v])=>h('div',{class:'card stat'},h('span',null,k),h('b',null,v==null||v===''?'Not recorded':String(v))))),
   ev.length?ev.map(v=>h('div',{class:'ev row',style:'justify-content:space-between;flex-wrap:nowrap'},h('div',{style:'min-width:0'},h('div',{style:'overflow-wrap:anywhere'},v.source_url?link(v.source_url):'Source '+v.id),h('div',{class:'reason'},(CLS[v.source_class]||v.source_class||'')+' · retrieved '+dt(v.retrieved_at))),h('button',{type:'button',class:'src','aria-label':'Open evidence '+v.id,onclick:e=>openDrawer(c,[],[v.id],e.currentTarget)},'Details'))):h('p',{class:'st'},'No evidence was recorded.'),
   (c.e.errors||[]).length?[h('h3',{class:'sub-h'},'Errors during the run'),h('ul',null,c.e.errors.map(x=>h('li',{class:'sec'},isO(x)?[x.source||x.step||x.stage,x.reason||x.message||x.error].filter(Boolean).join(': ')||flat(x):String(x))))]:null]}};
function chgEl(x){const pv=x.previous&&'value' in x.previous?x.previous.value:x.previous,cv=x.current&&'value' in x.current?x.current.value:x.current;const f=v=>v==null?'Not present':fv({field:x.field||'',value:v});
 return h('div',{class:'chg'},h('div',{class:'row'},h('span',{class:'tag'},String(x.type||'change').replace(/_/g,' ')),x.material?h('span',{class:'badge amb'},'Material'):null,h('span',{class:'muted num'},dt(x.detected_at))),
  h('p',null,x.explanation||''),(x.previous||x.current)?h('div',{class:'diff'},h('span',{class:'muted'},'Before'),h('span',null,f(pv)),h('span',{class:'muted'},'Now'),h('span',null,f(cv))):null)}

/* compare */
function cellFor(c,f){const xs=c.by[f]||[];const x=xs.find(y=>y.availability==='available')||xs[0];if(!x)return h('span',{class:'st'},'Not found');
 return h('span',{class:'cell'},val(c,x),x.availability==='available'?srcBtn(c,[x.id],(x.label||f)+' for '+c.name):null)}
function finCell(c,f){const x=latest(c,f);if(!x){const na=(c.by[f]||[])[0];return na?state(na):h('span',{class:'st'},'Not found')}
 return h('span',{class:'cell'},h('span',null,h('span',{class:'num'},fv(x)),h('span',{class:'reason'},per(perOf(x))+(x.value.account_type?', '+acct(x.value.account_type):''))),srcBtn(c,[x.id],FIN_L[f]+' for '+c.name))}
function cnt(c,f){return h('span',{class:'num'},String(av(c,f).length))}
function picker(onPick,exclude){const ul=h('ul');const inp=h('input',{class:'field',type:'search',placeholder:'Search companies to add','aria-label':'Search companies to add',oninput:()=>{const v=inp.value.trim();
 rc(ul,v?match(v).filter(c=>!exclude.includes(c.id)).slice(0,6).map(c=>h('li',null,h('button',{type:'button',onclick:()=>onPick(c.id)},c.name,h('span',{class:'muted num'},' '+org(c.id))))):[])}});return h('div',{class:'picker'},inp,ul)}
function viewCompare(q){let ids=String(q.ids||'').split(',').map(s=>s.trim()).filter(id=>BY[id]);if(!q.ids&&CMP.length)ids=CMP.slice();ids=ids.slice(0,3);
 if(ids.join()!==CMP.join())setCmp(ids);const go=ids2=>{setCmp(ids2);location.hash='#/compare?ids='+CMP.join(',')};
 const head=h('section',{class:'band'},h('div',{class:'wrap'},h('h1',null,'Compare'),h('p',{class:'lead'},'Up to three companies side by side. Figures are the latest filed amounts, with their period and account type.'),ids.length<3?h('div',{style:'margin-top:16px'},picker(id=>go(ids.concat(id)),ids)):null));
 if(!ids.length)return [head,h('section',{class:'wrap pad'},h('div',{class:'card empty'},'No companies selected. Search above, or use the Compare button on a company.'))];
 const cs=ids.map(id=>BY[id]);const last=c=>{const ch=(c.e.changes||[]).slice().sort((a,b)=>String(b.detected_at).localeCompare(String(a.detected_at)))[0];return ch?h('span',null,ch.explanation||ch.type,h('span',{class:'reason num'},dt(ch.detected_at))):h('span',{class:'st'},'No changes')};
 const R2=[['Legal form',c=>cellFor(c,'legal_form')],['Municipality',c=>c.muni||h('span',{class:'st'},'Not found')],['Industry',c=>cellFor(c,'industry')],['Employees',c=>cellFor(c,'registered_employees')],['Founded',c=>cellFor(c,'founded')],
  ['Revenue',c=>finCell(c,'revenue')],['Annual result',c=>finCell(c,'annual_result')],['Equity',c=>finCell(c,'equity')],['Website',c=>cellFor(c,'official_website')],
  ['Roles',c=>cnt(c,'role')],['Workplaces',c=>cnt(c,'workplace')],['Job ads',c=>cnt(c,'job_ad')],['News items',c=>cnt(c,'dated_news')],['Latest change',last]];
 const heads=[''].concat(cs.map(c=>c.name));
 const t=h('div',{class:'cmp-wrap',tabindex:'0',role:'region','aria-label':'Comparison table, scrolls sideways'},h('table',{class:'t cmp',style:'min-width:'+(120+cs.length*170)+'px'},h('thead',null,h('tr',null,h('td'),cs.map(c=>h('th',{scope:'col'},h('a',{href:'#/companies/'+c.id},c.name),h('div',{class:'muted num',style:'font-weight:400'},org(c.id)),
  h('button',{type:'button',class:'copy',style:'margin:6px 0 0','aria-label':'Remove '+c.name+' from compare',onclick:()=>go(ids.filter(x=>x!==c.id))},'Remove'))))),
  h('tbody',null,R2.map(([l,fn])=>h('tr',null,h('th',{scope:'row'},l),cs.map(c=>h('td',{'data-label':c.name},fn(c))))))));
 return [head,h('section',{class:'wrap pad'},h('div',{class:'card box'},t))]}

/* ask */
const TOP=[['what',/\b(do|does|doing|business|activit|purpose|about|virksomhet|form[aå]l|bransje|industr|describe|make|sell)/],['fin',/revenue|financ|omsetning|turnover|profit|result|resultat|equity|egenkapital|account|regnskap|earn|money|income/],
 ['lead',/\bwho\b|\brun|lead|ceo|daglig|styre|board|chair|manag|director|role|people|owner/],['where',/where|locat|adress|address|office|kontor|municipal|kommune|workplace|based|city/],
 ['hire',/hir|job|stilling|recruit|vacan|career|ansett|position/],['news',/news|nyhet|press|article|media/],['web',/web|site|social|linkedin|online|domain|nettside|facebook|instagram/],['chg',/chang|endring|differ|since|previous|new\b/]];
const TF={what:['registered_activity','statutory_purpose','industry','website_description'],fin:['revenue','annual_result','equity'],lead:['role','roles'],where:['registered_address','workplace'],hire:['job_ad','hiring_signal'],news:['dated_news'],web:['official_website','social_profile'],chg:[]};
const TN={what:'activity',fin:'financial',lead:'leadership',where:'location',hire:'hiring',news:'news',web:'website',chg:'change'};
function answer(c,q){q=q.toLowerCase();const tops=TOP.filter(([k,r])=>r.test(q)).map(x=>x[0]).slice(0,2);const out=[];
 if(!tops.length)return [{t:'I can answer questions about what the company does, its financials, leadership, locations, hiring, news, website and changes. Try one of the suggested questions.'}];
 for(const k of tops){const S=[],A=f=>av(c,f);
  if(k==='what'){const a=A('registered_activity')[0]||A('statutory_purpose')[0],d=A('website_description')[0],i=A('industry').sort((x,y)=>((x.value||{}).rank||9)-((y.value||{}).rank||9))[0];
   if(d)S.push({t:'Its website describes the business as: "'+fv(d)+'"',ids:[d.id]});if(a)S.push({t:'Registered activity: "'+fv(a)+'"',ids:[a.id]});if(i)S.push({t:'Main industry code: '+fv(i)+'.',ids:[i.id]})}
  if(k==='fin')for(const f of ['revenue','annual_result','equity']){const x=latest(c,f);if(x)S.push({t:FIN_L[f]+' was '+fv(x)+' for '+per(perOf(x))+(x.value.account_type?' ('+acct(x.value.account_type)+').':'.'),ids:[x.id]})}
  if(k==='lead'){const R=A('role'),g=re=>R.filter(x=>isO(x.value)&&re.test(String(x.value.role||x.label||'')));const ceo=g(/daglig|ceo|chief exec/i),ch=g(/styrets leder|chair|styreleder/i);
   if(ceo.length)S.push({t:'Daglig leder (CEO): '+ceo.map(x=>x.value.name).join(', ')+'.',ids:ceo.map(x=>x.id)});if(ch.length)S.push({t:'Chair of the board: '+ch.map(x=>x.value.name).join(', ')+'.',ids:ch.map(x=>x.id)});
   if(R.length)S.push({t:R.length+' role'+(R.length===1?' is':'s are')+' registered in total. See Leadership & workplaces for the full list.',ids:[]})}
  if(k==='where'){const a=A('registered_address')[0],w=A('workplace');if(a)S.push({t:'Registered address: '+fv(a)+'.',ids:[a.id]});
   if(w.length){const m=[...new Set(w.map(x=>isO(x.value)&&x.value.municipality?title(x.value.municipality):'').filter(Boolean))];S.push({t:'It has '+w.length+' registered workplace'+(w.length===1?'':'s')+(m.length?' in '+m.slice(0,5).join(', ')+(m.length>5?' and more':''):'')+'.',ids:w.slice(0,6).map(x=>x.id)})}}
  if(k==='hire'){const j=A('job_ad'),s=A('hiring_signal')[0];if(j.length)S.push({t:j.length+' job ad'+(j.length===1?' was':'s were')+' found: '+j.slice(0,3).map(fv).join('; ')+(j.length>3?'; and more.':'.'),ids:j.slice(0,3).map(x=>x.id)});
   if(s)S.push({t:'Careers page: '+(urlOf(s)||fv(s))+'.',ids:[s.id]})}
  if(k==='news'){const ns=A('dated_news').map(x=>({x,d:dateOf(x)})).sort((a,b)=>String(b.d).localeCompare(String(a.d))).slice(0,2);for(const {x,d} of ns)S.push({t:'News'+(d?' ('+String(d).slice(0,10)+')':'')+': '+fv(x)+'.',ids:[x.id]})}
  if(k==='web'){const w=A('official_website')[0],s=A('social_profile');if(w)S.push({t:'Official website: '+fv(w)+'.',ids:[w.id]});if(s.length)S.push({t:'Social profiles: '+s.map(fv).join(', ')+'.',ids:s.map(x=>x.id)})}
  if(k==='chg'){const ch=c.e.changes||[];if(ch.length)S.push({t:ch.length+' change'+(ch.length===1?' was':'s were')+' detected since the previous run. Latest: '+String(ch[ch.length-1].explanation||ch[ch.length-1].type).replace(/\.$/,'')+'.',ids:[]});
   else S.push({t:'No changes were detected since the previous run, or this is the first run for this company.',ids:[]})}
  if(!S.length){const na=TF[k].flatMap(f=>(c.by[f]||[]).filter(x=>x.availability!=='available'))[0];
   S.push(na?{t:'Unknown: '+(lab(na))+'. '+(SL[na.availability]||na.availability)+(na.reason?', '+na.reason.replace(/\.$/,''):'')+'.',ids:[na.id]}:{t:'Unknown: no '+TN[k]+' facts were found for this company.',ids:[]})}
  out.push(...S.slice(0,tops.length>1?2:3))}return out.slice(0,3)}
const LOG=[];
function viewAsk(q){let id=q.id&&BY[q.id]?q.id:(BY[store('varde-last')]?store('varde-last'):(CO[0]||{}).id);const list=h('div');
 const sel=h('select',{class:'field','aria-label':'Company',style:'max-width:100%',onchange:e=>{id=e.target.value;store('varde-last',id)}},CO.slice().sort((a,b)=>a.name.localeCompare(b.name,'nb')).map(c=>h('option',{value:c.id,selected:c.id===id},c.name+' ('+c.id+')')));
 function draw(){rc(list,LOG.length?LOG.map(a=>{const c=BY[a.id],n={i:0,map:{}};return h('div',{class:'ans'},h('div',{class:'q'},a.q),h('div',{class:'muted',style:'font-size:12.5px'},c.name),a.r.map(s=>h('p',null,s.t,srcChip(c,s.ids))))}):h('p',{class:'st'},'Answers appear here.'))}
 function ask(text){text=String(text||'').trim();if(!text||!BY[id])return;LOG.unshift({q:text,id,r:answer(BY[id],text)});draw()}
 const inp=h('input',{class:'field',type:'text',placeholder:'For example: who runs it, or what was revenue','aria-label':'Your question',style:'flex:1 1 260px;height:44px'});
 const form=h('form',{class:'tools',onsubmit:e=>{e.preventDefault();ask(inp.value);inp.value=''}},inp,h('button',{type:'submit',class:'btn pri',style:'min-height:44px'},'Ask'));
 const sug=['What do they do?','What was revenue?','Who runs it?','Where are they located?','Are they hiring?','Any news?','Website and social profiles','What changed?'];
 draw();return [h('section',{class:'band'},h('div',{class:'wrap'},h('h1',null,'Ask'),h('p',{class:'lead'},'Answers only use facts shown on the company profile, each with a citation. Nothing is sent over the network. If the profile has no support for an answer, it says what is unknown.'),
  h('div',{style:'margin-top:16px'},h('label',{class:'muted',style:'display:block;font-size:12.5px;margin-bottom:4px'},'Company'),sel),form,
  h('div',{class:'chips',role:'group','aria-label':'Suggested questions'},sug.map(s=>h('button',{type:'button',class:'chip',onclick:()=>ask(s)},s))))),h('section',{class:'wrap pad'},h('div',{class:'card box'},list))]}

/* refresh */
function viewRefresh(){const m=META;const withCh=CO.filter(c=>(c.e.changes||[]).length);const by={};let mat=0;
 for(const c of withCh)for(const x of c.e.changes){by[x.type||'change']=(by[x.type||'change']||0)+1;if(x.material)mat++}
 const stats=[['Run',m.run_id],['Started',dt(m.started_at)],['Completed',dt(m.completed_at)],['Companies',m.companies!=null?m.companies:CO.length],['Requests',m.requests],['Third-party cost',m.cost_usd!=null?'USD '+m.cost_usd:'']];
 return [h('section',{class:'band'},h('div',{class:'wrap'},h('h1',null,'Changes'),h('p',{class:'lead'},'What this run found that differs from the previous run of the same companies.'),
  h('div',{class:'stats',style:'margin-top:18px'},stats.map(([k,v])=>h('div',{class:'card stat'},h('span',null,k),h('b',null,v==null||v===''?'Not recorded':String(v))))))),
  h('section',{class:'wrap pad'},!withCh.length?h('div',{class:'card empty'},'No changes detected. This is the first run, or nothing changed since the previous one.'):
   [h('p',{class:'count'},withCh.length+' compan'+(withCh.length===1?'y has':'ies have')+' changes, '+mat+' marked material.'),h('div',{class:'chips',style:'margin-bottom:16px'},Object.keys(by).sort((a,b)=>by[b]-by[a]).map(k=>h('span',{class:'chip'},k.replace(/_/g,' '),h('span',{class:'ct'},by[k])))),
    h('div',{class:'list'},withCh.map(c=>h('div',{class:'card box'},h('div',{class:'row',style:'justify-content:space-between'},h('a',{href:'#/companies/'+c.id+'?tab=changes',style:'font-weight:600;font-size:15px'},c.name),h('span',{class:'muted num'},org(c.id))),c.e.changes.map(chgEl))))])]}

/* router */
let R={name:'dir'};
function parse(){const raw=decodeURIComponent((location.hash||'#/').slice(1))||'/';const [p,qs]=raw.split('?');const q={};(qs||'').split('&').forEach(kv=>{if(!kv)return;const i=kv.indexOf('=');q[i<0?kv:kv.slice(0,i)]=i<0?'':kv.slice(i+1)});
 const seg=p.split('/').filter(Boolean);if(seg[0]==='companies'&&seg[1])return {name:'profile',id:seg[1],q};if(seg[0]==='compare')return {name:'compare',q};if(seg[0]==='research')return {name:'research',q};if(seg[0]==='refresh')return {name:'refresh',q};return {name:'dir',q}}
function render(){closeDrawer();R=parse();const main=$('#main');let v;
 if(R.name==='profile')v=viewProfile(R.id,R.q.tab);else if(R.name==='compare')v=viewCompare(R.q);else if(R.name==='research')v=viewAsk(R.q);else if(R.name==='refresh')v=viewRefresh();else v=viewDir();
 rc(main,...v);const nv={dir:'dir',profile:'dir',compare:'compare',research:'research',refresh:'refresh'}[R.name];
 document.querySelectorAll('[data-nav]').forEach(a=>{if(a.dataset.nav===nv)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')});
 document.querySelector('[data-nav=compare]').setAttribute('href','#/compare'+(CMP.length?'?ids='+CMP.join(','):''));
 document.title=(R.name==='profile'&&BY[R.id]?BY[R.id].name+' · ':'')+'Varde';tray();window.scrollTo(0,0)}
window.addEventListener('hashchange',()=>{render();$('#main').focus({preventScroll:true})});
$('#foot').textContent='Varde · every fact links to its source · run '+(META.run_id||'');
render();
"""
