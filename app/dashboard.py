"""Read-only local monitoring dashboard for the signal engine."""

from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
import uvicorn

from app.config.settings import SUPPORTED_TIMEFRAMES, load_settings, normalize_symbol
from app.monitoring.runtime import RuntimeHealthSnapshotStore
from app.storage.database import Database
from app.storage.repositories import BacktestRepository, SignalRepository
from app.backtest.report import HistoricalPerformanceReport


def _open_connection(database_path: Path) -> sqlite3.Connection:
    database = Database(database_path)
    database.open()
    connection = database.connection
    if connection is None:  # pragma: no cover - defensive guard
        raise RuntimeError("Database could not be opened")
    return connection


def _dashboard_html() -> str:
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#f6f8ff"><title>Signalbot · Multi-Pair CSD Signal Engine</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Calistoga&family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;600&display=swap');
:root{color-scheme:light;--ink:#18233d;--muted:#60708b;--line:#e4e9f5;--panel:#fff;--canvas:#f6f8ff;--blue:#3159dc;--indigo:#5547bd;--blue-soft:#edf1ff;--good:#087a50;--good-bg:#e5f7ee;--warn:#985700;--warn-bg:#fff4d9;--danger:#ba3030;--danger-bg:#ffebeb;--radius:20px;--shadow:0 14px 36px rgba(42,64,131,.08)}
*{box-sizing:border-box}html{scroll-padding-top:90px}body{margin:0;color:var(--ink);background:radial-gradient(circle at 85% -10%,#e2e9ff 0,transparent 34rem),var(--canvas);font:15px/1.5 Inter,system-ui,sans-serif}.app{max-width:1520px;margin:auto;padding:18px 24px 44px}.topbar{position:sticky;top:12px;z-index:10;display:flex;align-items:center;gap:18px;padding:13px 16px;background:rgba(255,255,255,.88);border:1px solid rgba(228,233,245,.9);border-radius:18px;box-shadow:0 8px 30px rgba(44,64,123,.07);backdrop-filter:blur(16px)}.brand{display:flex;align-items:center;gap:10px;white-space:nowrap;font-weight:800;letter-spacing:-.04em;font-size:20px}.mark{display:grid;place-items:center;width:30px;height:30px;border-radius:10px;background:linear-gradient(135deg,var(--blue),var(--indigo));color:#fff}.nav{display:flex;gap:3px;flex:1;overflow:auto}.nav button,.text-button{appearance:none;border:0;background:transparent;color:var(--muted);font:600 13px Inter;padding:9px 10px;border-radius:9px;cursor:pointer;white-space:nowrap}.nav button:hover,.nav button[aria-current=true]{background:var(--blue-soft);color:var(--blue)}.safety{margin-left:auto;display:flex;align-items:center;gap:7px;color:#345;white-space:nowrap;font-size:12px;font-weight:700}.safety i{width:8px;height:8px;border-radius:50%;background:var(--good)}button:focus-visible,a:focus-visible{outline:3px solid #7894f8;outline-offset:3px}.page-head{display:flex;justify-content:space-between;align-items:end;gap:20px;padding:38px 4px 22px}.eyebrow{margin:0 0 6px;color:var(--blue);font-weight:800;font-size:11px;letter-spacing:.13em;text-transform:uppercase}.page-head h1{margin:0;font-family:Calistoga,Georgia,serif;font-size:clamp(29px,4vw,45px);font-weight:400;letter-spacing:-.035em;line-height:1.1}.subhead{max-width:680px;margin:8px 0 0;color:var(--muted)}.updated{font:500 12px 'JetBrains Mono',monospace;color:var(--muted);text-align:right}.notice{display:flex;gap:12px;align-items:flex-start;padding:13px 15px;margin:0 0 18px;border:1px solid #cbd7ff;background:#f0f4ff;border-radius:14px;color:#274071;font-size:13px}.notice strong{color:#1c3c9d}.grid{display:grid;gap:16px}.metrics{grid-template-columns:repeat(4,minmax(0,1fr))}.two{grid-template-columns:minmax(0,1.65fr) minmax(300px,1fr)}.card{min-width:0;padding:20px;background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow)}.card h2,.card h3{margin:0;letter-spacing:-.025em}.card h2{font-size:17px}.card h3{font-size:14px}.metric{position:relative;overflow:hidden}.metric:after{content:'';position:absolute;right:-18px;bottom:-21px;width:72px;height:72px;border:13px solid var(--blue-soft);border-radius:50%}.label{color:var(--muted);font-size:12px;font-weight:700}.value{margin-top:8px;font-size:24px;font-weight:800;letter-spacing:-.04em}.caption{margin:5px 0 0;color:var(--muted);font-size:12px}.badge{display:inline-flex;align-items:center;gap:6px;max-width:100%;padding:5px 8px;border-radius:999px;background:var(--blue-soft);color:#314eae;font:700 11px Inter;white-space:nowrap}.badge.good{background:var(--good-bg);color:var(--good)}.badge.warn{background:var(--warn-bg);color:var(--warn)}.badge.danger{background:var(--danger-bg);color:var(--danger)}.badge.muted{background:#eff2f7;color:#637089}.chart{height:282px;margin-top:12px;padding-top:8px}.chart svg{width:100%;height:100%;overflow:visible}.chart .gridline{stroke:#e7ebf5;stroke-width:1}.chart .area{fill:url(#area);opacity:.7}.chart .line{fill:none;stroke:#3159dc;stroke-width:3;stroke-linecap:round;stroke-linejoin:round}.chart-empty,.empty{display:grid;place-items:center;min-height:160px;text-align:center;color:var(--muted);font-size:13px}.signal-card{display:flex;flex-direction:column;gap:17px;background:linear-gradient(145deg,#fff,#f8faff)}.signal-score{display:flex;align-items:end;gap:9px}.signal-score strong{font-size:48px;line-height:.8;letter-spacing:-.08em}.signal-score span{padding-bottom:4px;color:var(--muted);font-weight:600}.progress{height:9px;overflow:hidden;background:#e9edfa;border-radius:99px}.progress span{display:block;height:100%;background:linear-gradient(90deg,#547be8,#6648bd);border-radius:inherit}.prices{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.price{padding:9px;border:1px solid var(--line);border-radius:12px}.price b{display:block;margin-top:3px;font:600 12px 'JetBrains Mono',monospace;overflow-wrap:anywhere}.pipeline{display:grid;grid-template-columns:repeat(6,minmax(105px,1fr));gap:8px;margin-top:14px}.step{position:relative;padding:12px;border:1px solid var(--line);border-radius:12px;background:#fcfdff}.step:not(:last-child):after{content:'›';position:absolute;right:-9px;top:12px;z-index:1;color:#9ba8c4;font-size:21px}.step b{display:block;font-size:12px}.step span{display:block;margin-top:5px;color:var(--muted);font-size:11px}.table-wrap{overflow:auto;margin-top:12px}table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:11px 8px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}th{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.07em}tbody tr:hover{background:#fafbff}.link-button{border:0;background:transparent;color:var(--blue);font:700 12px Inter;cursor:pointer;padding:0}.health-list{display:grid;gap:1px;margin-top:10px}.health-row{display:flex;justify-content:space-between;gap:12px;padding:11px 0;border-bottom:1px solid var(--line);font-size:13px}.health-row:last-child{border:0}.freshness{font:600 11px 'JetBrains Mono',monospace;color:var(--muted)}.detail-layout{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(280px,.75fr);gap:16px}.reason{display:grid;grid-template-columns:34px 1fr;gap:11px;padding:13px 0;border-bottom:1px solid var(--line)}.reason:last-child{border:0}.reason-num{display:grid;place-items:center;width:27px;height:27px;border-radius:9px;background:var(--blue-soft);color:var(--blue);font-weight:800;font-size:12px}.reason p{margin:2px 0 0;color:var(--muted);font-size:12px}.kpi-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:15px}.kpi{padding:12px;border-radius:13px;background:#f8faff}.kpi b{display:block;margin-top:2px;font-size:16px}.status-dot{display:inline-block;width:8px;height:8px;margin-right:6px;border-radius:50%;background:#a4afc4}.status-dot.ok{background:#18a46a}.status-dot.bad{background:#d35353}.symbol-grid{grid-template-columns:repeat(5,minmax(160px,1fr))}.symbol-card{padding:16px;cursor:pointer;transition:transform .18s,box-shadow .18s}.symbol-card:hover{transform:translateY(-2px);box-shadow:0 18px 38px rgba(42,64,131,.11)}.symbol-title{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;font-size:16px;font-weight:800}.signal-blank{color:var(--muted);font-size:12px}.wide{grid-column:1/-1}.warning-list{margin:10px 0 0;padding-left:18px;color:var(--muted);font-size:13px}.error{padding:18px;border:1px solid #f0bcbc;border-radius:14px;background:#fff4f4;color:#962d2d}.skeleton{height:116px;background:linear-gradient(90deg,#f1f4fb,#fbfcff,#f1f4fb);background-size:200% 100%;animation:loading 1.2s infinite;border-radius:var(--radius)}@keyframes loading{to{background-position:-200% 0}}@media(max-width:1050px){.metrics{grid-template-columns:repeat(2,1fr)}.symbol-grid{grid-template-columns:repeat(3,1fr)}.pipeline{grid-template-columns:repeat(3,1fr)}.step:after{display:none}}@media(max-width:720px){.app{padding:10px 12px 30px}.topbar{top:6px;flex-wrap:wrap;padding:11px}.nav{order:3;width:100%;flex-basis:100%}.safety{margin-left:auto}.page-head{display:block;padding-top:28px}.updated{text-align:left;margin-top:12px}.metrics,.two,.detail-layout{grid-template-columns:1fr}.symbol-grid{grid-template-columns:repeat(2,1fr)}.pipeline{grid-template-columns:repeat(2,1fr)}.card{padding:16px}.value{font-size:22px}}@media(max-width:400px){.symbol-grid{grid-template-columns:1fr}.safety{display:none}}@media(prefers-reduced-motion:reduce){*,*:before,*:after{scroll-behavior:auto!important;animation-duration:.01ms!important;transition-duration:.01ms!important}}
</style></head><body><div class="app"><header class="topbar"><div class="brand"><span class="mark" aria-hidden="true">S</span>signalbot</div><nav class="nav" aria-label="Primary navigation"><button data-view="dashboard">Overview</button><button data-view="signal">Signal detail</button><button data-view="monitor">Market monitor</button><button data-view="backtests">Backtests</button><button data-view="validation">Phase 9 validation</button><button data-view="health">System health</button></nav><div class="safety"><i aria-hidden="true"></i>Monitoring only · Observation mode</div></header><main id="app" aria-live="polite"><div class="page-head"><div><p class="eyebrow">Multi-Pair CSD Signal Engine · Read-only market intelligence</p><h1>Loading signalbot…</h1></div></div></main></div>
<script>
const el=document.querySelector('#app'),views=['dashboard','signal','monitor','backtests','validation','health'];
const state={status:null,signals:[],candles:{},backtests:[],phase9:null,selectedSignal:null,selectedRun:null,backtestDetail:null,error:null,loadedAt:null};
const esc=v=>String(v??'—').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const fmt=v=>v===null||v===undefined||v===''?'—':esc(v); const time=v=>v?new Date(v).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'}):'Not available';
const badge=(v)=>{const x=String(v||'NOT_AVAILABLE'),c=x.includes('STRONG')||x==='COMPLETE'||x==='BULLISH'?'good':x.includes('NO_')||x.includes('INCOMPLETE')||x==='NOT_AVAILABLE'?'muted':x.includes('WATCH')||x.includes('DIAGNOSTIC')?'warn':'';return `<span class="badge ${c}">${esc(x.replaceAll('_',' '))}</span>`};
const card=(title,body,klass='')=>`<section class="card ${klass}">${title?`<h2>${title}</h2>`:''}${body}</section>`;
const unavailable=(label='No persisted data yet')=>`<div class="empty"><div><strong>${esc(label)}</strong><br><span>This view only presents data supplied by the signal engine.</span></div></div>`;
async function api(path){const r=await fetch(path);if(!r.ok)throw new Error(`${r.status} ${r.statusText}`);return r.json()}
function head(title,description){return `<div class="page-head"><div><p class="eyebrow">Read-only market intelligence</p><h1>${title}</h1><p class="subhead">${description}</p></div><div class="updated">${state.loadedAt?`Updated ${time(state.loadedAt)}`:'Connecting to engine…'}<br>Auto-refreshes every 15 min</div></div><div class="notice"><strong>Observation mode</strong><span>Signalbot displays analysis and reference plans only. It has no order placement, wallet, withdrawal, or parameter-tuning controls.</span></div>`}
function metric(label,value,caption=''){return `<article class="card metric"><div class="label">${label}</div><div class="value">${value}</div>${caption?`<p class="caption">${caption}</p>`:''}</article>`}
function signalCard(s){if(!s)return card('ETHUSDT primary signal',unavailable('No persisted ETHUSDT signal'));
 const score=Number(s.confidence),width=Number.isFinite(score)?Math.max(0,Math.min(100,score*10)):0;
 return card('ETHUSDT primary signal',`<div class="signal-card"><div style="display:flex;justify-content:space-between;gap:10px;align-items:start"><div>${badge(s.classification)}<div class="caption" style="margin-top:8px">${fmt(s.direction)} · ${fmt(s.timeframe)} · ${time(s.created_at)}</div></div>${badge(s.direction)}</div><div class="signal-score"><strong>${fmt(s.confidence)}</strong><span>/ 10 backend score</span></div><div class="progress" aria-label="Score ${fmt(s.confidence)} out of 10"><span style="width:${width}%"></span></div><div class="prices"><div class="price"><span class="label">Reference entry</span><b>${fmt(s.reference_entry)}</b></div><div class="price"><span class="label">Stop loss</span><b>${fmt(s.stop_loss)}</b></div><div class="price"><span class="label">TP1 / TP2</span><b>${fmt(s.take_profit_1)} / ${fmt(s.take_profit_2)}</b></div><div class="price"><span class="label">TP3</span><b>${fmt(s.take_profit_3)}</b></div></div><button class="text-button" data-action="signal" style="align-self:start;padding-left:0;color:var(--blue)">Inspect reasoning →</button></div>`,'signal-card')}
function candleChart(candles){if(!candles?.length)return unavailable('No stored 15-minute candles');const values=candles.map(c=>Number(c.close)).filter(Number.isFinite);if(!values.length)return unavailable('Candle values unavailable');const min=Math.min(...values),max=Math.max(...values),span=max-min||1,pts=values.map((v,i)=>`${(i/(values.length-1||1))*100},${94-((v-min)/span)*82}`).join(' ');return `<div class="chart" role="img" aria-label="Close-price chart generated from ${values.length} stored closed candles"><svg viewBox="0 0 100 100" preserveAspectRatio="none"><defs><linearGradient id="area" x1="0" x2="0" y1="0" y2="1"><stop stop-color="#b9c8ff"/><stop offset="1" stop-color="#f7f9ff"/></linearGradient></defs><path class="gridline" d="M0 12H100M0 50H100M0 88H100"/><polygon class="area" points="0,100 ${pts} 100,100"/><polyline class="line" points="${pts}"/></svg></div><div style="display:flex;justify-content:space-between" class="caption"><span>${time(candles[0].open_time)}</span><span>Close ${fmt(candles.at(-1).close)}</span></div>`}
function pipeline(s){const steps=[['Structure','Not persisted'],['CSD / BOS',s?fmt(s.direction):'Not available'],['Breakout','Not persisted'],['Retest','Not persisted'],['Confirmation',s?fmt(s.classification):'Not available'],['Score',s?`${fmt(s.confidence)} / 10`:'Not available']];return `<div class="pipeline">${steps.map(([a,b])=>`<div class="step"><b>${a}</b><span>${b}</span></div>`).join('')}</div>`}
function dashboard(){const eth=state.signals.find(s=>s.symbol==='ETHUSDT')||state.signals[0],r=state.status?.runtime||{},ethCandles=state.candles.ETHUSDT||[];return head('A clear view of every signal.','Live engine health, persisted market context, and analysis-only reference plans—never execution.')+`<div class="grid metrics"><div>${metric('Engine status',r.running?'Running':'Not running',r.running?'Runtime snapshot received':'Awaiting runtime snapshot')}</div><div>${metric('WebSocket',r.websocket_connected?'Connected':'Disconnected','Binance market-data boundary')}</div><div>${metric('Enabled symbols',state.status?.enabled_symbols?.length??'—','Only configured symbols are queried')}</div><div>${metric('Latest persisted signals',state.signals.length,'Across enabled symbols')}</div></div><div class="grid two" style="margin-top:16px"><div class="card"><h2>ETHUSDT market context</h2><p class="caption">15-minute stored closing prices. Visualizes persisted candles only.</p>${candleChart(ethCandles)}</div>${signalCard(eth)}</div>${card('Analysis lifecycle',`<p class="caption">The backend persists the final signal fields, not each intermediate pipeline event.</p>${pipeline(eth)}`,'wide')}<div class="grid two" style="margin-top:16px">${card('Recent persisted signals',signalTable(state.signals.slice(0,6)))}${card('Data & system health',healthList(r))}</div>`}
function signalTable(signals){if(!signals.length)return unavailable('No persisted signals');return `<div class="table-wrap"><table><thead><tr><th>Signal</th><th>Classification</th><th>Score</th><th>Reference</th><th>Recorded</th><th></th></tr></thead><tbody>${signals.map(s=>`<tr><td><b>${esc(s.symbol)}</b><br><span class="caption">${fmt(s.direction)} · ${fmt(s.timeframe)}</span></td><td>${badge(s.classification)}</td><td>${fmt(s.confidence)}/10</td><td>${fmt(s.reference_entry)}</td><td>${time(s.created_at)}</td><td><button class="link-button" data-signal="${esc(s.signal_id)}">Details</button></td></tr>`).join('')}</tbody></table></div>`}
function healthList(r){const items=[['API / database',state.status?.database_connected?'Connected':'Unavailable',state.status?.database_connected],['Market data',r.websocket_connected?'Connected':'Disconnected',r.websocket_connected],['Engine',r.running?'Running':'Not running',r.running],['Last market message',time(r.last_message_time),!!r.last_message_time]];return `<div class="health-list">${items.map(([a,b,ok])=>`<div class="health-row"><span><i class="status-dot ${ok?'ok':'bad'}"></i>${a}</span><b>${b}</b></div>`).join('')}</div>`}
function signalDetail(){const s=state.selectedSignal||state.signals[0];if(!s)return head('Signal detail','A transparent, read-only explanation of each persisted analysis result.')+card('',unavailable('No signal selected or persisted'));
 const fields=[['Direction',s.direction],['Classification',s.classification],['Score',`${s.confidence} / 10`],['Signal time',time(s.created_at)],['Entry range',`${s.entry_low} — ${s.entry_high}`],['Reference entry',s.reference_entry],['Stop loss',s.stop_loss],['TP1 / TP2 / TP3',`${s.take_profit_1} / ${s.take_profit_2} / ${s.take_profit_3}`],['TP4',s.take_profit_4]];
 return head(`${s.symbol} signal reasoning`,'A transparent record of what the backend persisted. Missing fields are intentionally never inferred by the interface.')+`<div class="detail-layout">${card('Structure → score → risk',`<p class="caption">Recorded ${time(s.created_at)} · ID ${esc(s.signal_id)}</p><div id="evidence-detail" class="empty">Loading persisted analysis evidence…</div>`)}${card('Persisted reference plan',`<div class="prices">${fields.map(([a,b])=>`<div class="price"><span class="label">${a}</span><b>${fmt(b)}</b></div>`).join('')}</div><div style="margin-top:18px"><span class="label">Notification delivery</span><div id="notification-detail" class="caption">Loading delivery record…</div></div>`)}</div>`}
function monitor(){const desired=['ETHUSDT','BTCUSDT','SOLUSDT','BNBUSDT','XRPUSDT'],enabled=state.status?.enabled_symbols||[],runtime=state.status?.runtime||{};return head('Multi-symbol monitor','A read-only scan of the requested market set. Disabled symbols stay visible as configuration status, not simulated data.')+`<div class="grid symbol-grid">${desired.map(symbol=>{const s=state.signals.find(x=>x.symbol===symbol),fresh=(runtime.last_closed_candles||[]).filter(x=>x.symbol===symbol);return `<article class="card symbol-card" ${s?`data-signal="${esc(s.signal_id)}"`:''}><div class="symbol-title"><span>${symbol}</span>${enabled.includes(symbol)?badge('ENABLED'):badge('NOT_ENABLED')}</div>${s?`<div>${badge(s.classification)}</div><div class="value" style="font-size:20px">${fmt(s.confidence)}<span class="caption"> / 10</span></div><p class="caption">${fmt(s.direction)} · ${time(s.created_at)}</p><div class="price"><span class="label">Entry / SL</span><b>${fmt(s.reference_entry)} / ${fmt(s.stop_loss)}</b></div>`:`<p class="signal-blank">${enabled.includes(symbol)?'No persisted signal yet.':'Not enabled in the backend configuration.'}</p>`}<p class="freshness">15m / 1h / 4h: ${fresh.length?`${fresh.length} recorded freshness event(s)`:'No runtime freshness data'}</p></article>`}).join('')}</div>${card('Live data freshness',`<p class="caption">The runtime snapshot reports each closed candle it has received. It does not calculate additional health scores in the browser.</p>${healthList(runtime)}`,'wide')}`}
function metricValue(v){return v===null||v===undefined?'—':esc(v)}
function backtests(){const b=state.backtests,detail=state.backtestDetail;let body=b.length?`<div class="table-wrap"><table><thead><tr><th>Run</th><th>Market</th><th>Status</th><th>Created</th><th></th></tr></thead><tbody>${b.map(x=>`<tr><td>${esc(x.run_id)}</td><td>${esc(x.symbol)} · ${esc(x.timeframe)}</td><td>${badge(x.status)}</td><td>${time(x.created_at)}</td><td><button class="link-button" data-run="${esc(x.run_id)}">Inspect</button></td></tr>`).join('')}</tbody></table></div>`:unavailable('No historical backtest runs');let detailHtml=detail?backtestDetail(detail):unavailable('Select a persisted backtest run');return head('Historical backtests','Read-only reports from persisted runs. Report status and warnings are preserved so incomplete data is never mistaken for a result.')+`<div class="grid two">${card('Historical runs',body)}${card('Run summary',detailHtml)}</div>`}
function backtestDetail(d){const m=d.metrics||d,stats=[['Trades',d.trade_count??m.trade_count],['Net R',d.total_r??m.total_r],['Gross R',d.gross_r??m.gross_r],['Expectancy',d.expectancy_r??m.expectancy_r],['Profit factor',d.profit_factor??m.profit_factor],['Win rate',d.win_rate??m.win_rate],['Max drawdown',d.max_drawdown_r??m.max_drawdown_r],['Losing streak',m.max_losing_streak],['MFE / MAE',`${metricValue(m.average_mfe_r)} / ${metricValue(m.average_mae_r)}`],['Trade duration',m.average_bars_in_trade]];return `<div>${badge(d.status)}<p class="caption">${esc(d.backtest_policy||'Persisted backtest report')}</p><div class="kpi-grid">${stats.map(([a,b])=>`<div class="kpi"><span class="label">${a}</span><b>${metricValue(b)}</b></div>`).join('')}</div>${d.warnings?.length?`<ul class="warning-list">${d.warnings.map(esc).map(x=>`<li>${x}</li>`).join('')}</ul>`:''}<p class="caption">Random baseline: ${esc(d.baseline?.status||'Not reported')}</p>${d.trades?.length?`<div class="table-wrap"><table><thead><tr><th>Trade</th><th>Net R</th><th>MFE / MAE</th><th>Regime / session</th></tr></thead><tbody>${d.trades.map(t=>`<tr><td>${time(t.signal_time)}<br>${esc(t.direction)}</td><td>${metricValue(t.net_r)}</td><td>${metricValue(t.mfe_r)} / ${metricValue(t.mae_r)}</td><td>${metricValue(t.regime)} / ${metricValue(t.session)}</td></tr>`).join('')}</tbody></table></div>`:''}</div>`}
function validation(){const p=state.phase9;if(!p?.available){const cards=[metric('Execution status','Report unavailable','Run the existing Phase 9 script to write data/phase9_report.json.'),metric('Random baseline','Not available','No persisted report is present.'),metric('Walk-forward / OOS','Not available','No persisted report is present.'),metric('Sensitivity','Not available','No persisted report is present.')].join('');return head('Phase 9 validation','An observation-only space for persisted validation reports. No tuning or optimization controls are available.')+`<div class="grid metrics">${cards}</div>`+card('Validation diagnostics','<div class="notice" style="margin-top:14px"><strong>Awaiting backend report</strong><span>This view is read-only and never runs validation or chooses parameters. It will render the existing persisted report when one is available.</span></div>','wide')}const r=p.report||{},wf=r.walk_forward||{},sensitivity=r.sensitivity||{},symbols=r.symbols||{};const symbolRows=Object.entries(symbols).map(([name,value])=>'<tr><td>'+esc(name)+'</td><td>'+metricValue(value.trade_count)+'</td><td>'+metricValue(value.baseline?.percentile)+'</td><td>'+metricValue(value.metrics?.expectancy_r)+'</td></tr>').join('')||'<tr><td colspan="4">No symbol results persisted.</td></tr>';const points=(sensitivity.points||[]).map(x=>esc(x.parameter)+'='+esc(x.value)+' ('+esc(x.expectancy_r)+' R)').join(' · ')||'None';const cards=[metric('Execution status',badge(p.status),'Report status'),metric('Random baseline',Object.keys(symbols).length,'Symbols reported'),metric('Walk-forward / OOS',metricValue(wf.oos_trade_count),'Out-of-sample trades'),metric('Sensitivity',metricValue(sensitivity.plateau_width),'Plateau width; no value selected')].join('');const diagnostics='<p class="caption">Methodology: '+esc(r.methodology?.walk_forward||'Not recorded')+'</p><div class="table-wrap"><table><thead><tr><th>Symbol</th><th>Trades</th><th>Baseline</th><th>Expectancy</th></tr></thead><tbody>'+symbolRows+'</tbody></table></div><p class="caption">Sensitivity points: '+points+'</p>';return head('Phase 9 validation','Read-only results from the persisted frozen-strategy validation report.')+`<div class="grid metrics">${cards}</div>`+card('Validation diagnostics',diagnostics,'wide')}
function health(){const r=state.status?.runtime||{},candles=r.last_closed_candles||[];return head('System health','Runtime and freshness data published by the engine. Status colors supplement—never replace—the underlying text.')+`<div class="grid metrics"><div>${metric('API / database',state.status?.database_connected?'Connected':'Unavailable')}</div><div>${metric('Binance market data',r.websocket_connected?'Connected':'Disconnected')}</div><div>${metric('Engine',r.running?'Running':'Not running')}</div><div>${metric('Notifications','Delivery history only','Providers are not controlled here')}</div></div><div class="grid two" style="margin-top:16px">${card('Timeframe freshness',candles.length?`<div class="table-wrap"><table><thead><tr><th>Symbol</th><th>Timeframe</th><th>Last closed candle</th></tr></thead><tbody>${candles.map(c=>`<tr><td>${esc(c.symbol)}</td><td>${esc(c.timeframe)}</td><td>${time(c.close_time)}</td></tr>`).join('')}</tbody></table></div>`:unavailable('No closed-candle freshness recorded'))}${card('Runtime boundary',`<div class="health-list"><div class="health-row"><span>Last market message</span><b>${time(r.last_message_time)}</b></div><div class="health-row"><span>Configured enabled symbols</span><b>${state.status?.enabled_symbols?.map(esc).join(', ')||'None'}</b></div><div class="health-row"><span>Validation status</span><b>Not exposed by current API</b></div><div class="health-row"><span>Observation safety</span><b>Trading controls absent</b></div></div>`)}</div>`}
function render(){const view=location.hash.slice(1)||'dashboard';document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-current',String(b.dataset.view===view)));if(state.error){el.innerHTML=head('Connection needs attention','The dashboard could not obtain its read-only engine data.')+`<div class="error"><b>Unable to load backend data.</b><p>${esc(state.error)}</p><button class="text-button" data-action="retry" style="color:inherit;padding-left:0">Try again</button></div>`;return}const renderers={dashboard,signal:signalDetail,monitor,backtests,validation,health};el.innerHTML=(renderers[views.includes(view)?view:'dashboard'])();if(view==='signal'&&(state.selectedSignal||state.signals[0])){const signal=state.selectedSignal||state.signals[0];loadNotifications(signal);loadEvidence(signal)}}
async function loadNotifications(s){try{const d=await api(`/api/notifications?signal_id=${encodeURIComponent(s.signal_id)}`),node=document.querySelector('#notification-detail');if(node)node.innerHTML=d.notifications.length?d.notifications.map(n=>`${esc(n.provider)}: ${n.success?'delivered':'failed'} (${esc(n.attempts)} attempt${n.attempts===1?'':'s'})${n.error?` — ${esc(n.error)}`:''}`).join('<br>'):'No delivery attempts recorded.'}catch{const node=document.querySelector('#notification-detail');if(node)node.textContent='Delivery record unavailable.'}}
async function loadEvidence(s){try{const d=await api(`/api/signals/${encodeURIComponent(s.signal_id)}`),e=d.evidence,node=document.querySelector('#evidence-detail');if(!node)return;if(!e){node.innerHTML=unavailable('No evidence snapshot for this historical signal');return}const rows=[['Structure',`${e.structure?.swing_kind||'—'} @ ${e.structure?.swing_price||'—'} · ${time(e.structure?.swing_time)}`],['CSD / BOS',`${e.csd?.direction||'—'} · ${e.csd?.close_distance_percent||'—'}% close distance · ${time(e.csd?.time)}`],['Breakout',`${e.breakout?.status||'—'} · level ${e.breakout?.level||'—'} · quality ${e.breakout?.quality||'—'}`],['Retest',`${e.retest?.status||'—'} · quality ${e.retest?.quality||'—'} · ${time(e.retest?.time)}`],['Confirmation',`EMA ${e.confirmation?.ema?'✓':'—'} · RSI ${e.confirmation?.rsi?'✓':'—'} · MACD ${e.confirmation?.macd?'✓':'—'} · Volume ${e.confirmation?.volume?'✓':'—'} · 1H ${e.confirmation?.one_hour?'✓':'—'} · 4H ${e.confirmation?.four_hour?'✓':'—'}`],['Score components',Object.entries(e.score?.components||{}).map(([k,v])=>`${k}: ${v}`).join(' · ')||'—'],['Risk unit',e.risk?.risk_unit||'—']];node.className='';node.innerHTML=rows.map((x,i)=>`<div class="reason"><span class="reason-num">${i+1}</span><div><b>${esc(x[0])}</b><p>${esc(x[1])}</p></div></div>`).join('')}catch{const node=document.querySelector('#evidence-detail');if(node)node.innerHTML=unavailable('Analysis evidence unavailable.')}}
async function loadBacktest(runId){state.selectedRun=runId;state.backtestDetail=await api(`/api/backtests/${encodeURIComponent(runId)}`);render()}
async function load(){try{state.error=null;const status=await api('/api/status'),signals=(await api('/api/signals?limit=100')).signals||[];state.status=status;state.signals=signals;state.selectedSignal=state.selectedSignal?signals.find(s=>s.signal_id===state.selectedSignal.signal_id)||signals[0]:signals[0]||null;const symbols=status.enabled_symbols||[];const candleResults=await Promise.all(symbols.map(async symbol=>[symbol,(await api(`/api/candles?symbol=${encodeURIComponent(symbol)}&timeframe=15m&limit=80`)).candles||[]]));state.candles=Object.fromEntries(candleResults);const [backtests,phase9]=await Promise.all([api('/api/backtests'),api('/api/phase9')]);state.backtests=backtests.backtests||[];state.phase9=phase9;state.loadedAt=new Date().toISOString();render()}catch(e){state.error=e.message||'Unexpected connection error';render()}}
document.addEventListener('click',e=>{const v=e.target.closest('[data-view]');if(v){location.hash=v.dataset.view;return}const s=e.target.closest('[data-signal]');if(s){state.selectedSignal=state.signals.find(x=>x.signal_id===s.dataset.signal)||null;location.hash='signal';return}const r=e.target.closest('[data-run]');if(r){loadBacktest(r.dataset.run).catch(e=>{state.error=e.message;render()});return}if(e.target.closest('[data-action=signal]')){location.hash='signal';return}if(e.target.closest('[data-action=retry]'))load()});window.addEventListener('hashchange',render);load();setInterval(load,900000);
</script></body></html>"""


def create_dashboard_app(
    database_path: str | Path, enabled_symbols: tuple[str, ...], health_snapshot_path: str | Path | None = None,
    phase9_report_path: str | Path | None = None,
) -> FastAPI:
    """Create the read-only dashboard application over the engine SQLite data."""
    path = Path(database_path)
    symbols = tuple(normalize_symbol(symbol) for symbol in enabled_symbols)
    health_store = RuntimeHealthSnapshotStore(health_snapshot_path or path.with_suffix(".health.json"))
    validation_report_path = Path(phase9_report_path or path.with_name("phase9_report.json"))
    app = FastAPI(title="Multi-Pair CSD Signal Engine Dashboard", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return _dashboard_html()

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        connection = _open_connection(path)
        try:
            connection.execute("SELECT 1").fetchone()
        finally:
            connection.close()
        return {"database_connected": True, "enabled_symbols": list(symbols), "runtime": health_store.read()}

    @app.get("/api/candles")
    def candles(symbol: str, timeframe: str, limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
        try:
            canonical_symbol = normalize_symbol(symbol)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if canonical_symbol not in symbols:
            raise HTTPException(status_code=404, detail="Symbol is not enabled")
        canonical_timeframe = timeframe.strip().lower()
        if canonical_timeframe not in SUPPORTED_TIMEFRAMES:
            raise HTTPException(status_code=422, detail="Unsupported timeframe")
        connection = _open_connection(path)
        try:
            rows = connection.execute(
                "SELECT symbol,timeframe,open_time,close_time,open,high,low,close,volume,is_closed "
                "FROM candles WHERE symbol=? AND timeframe=? ORDER BY open_time DESC LIMIT ?",
                (canonical_symbol, canonical_timeframe, limit),
            ).fetchall()
        finally:
            connection.close()
        rows.reverse()
        fields = ("symbol", "timeframe", "open_time", "close_time", "open", "high", "low", "close", "volume", "is_closed")
        return {"candles": [dict(zip(fields, (*row[:-1], bool(row[-1]),))) for row in rows]}

    @app.get("/api/signals")
    def signals(symbol: str | None = None, limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
        if symbol is not None:
            try:
                canonical_symbol = normalize_symbol(symbol)
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            if canonical_symbol not in symbols:
                raise HTTPException(status_code=404, detail="Symbol is not enabled")
        else:
            canonical_symbol = None
        connection = _open_connection(path)
        try:
            if canonical_symbol is None:
                rows = connection.execute("SELECT signal_id,symbol,timeframe,direction,classification,confidence,entry_low,entry_high,reference_entry,stop_loss,take_profit_1,take_profit_2,take_profit_3,take_profit_4,created_at FROM signals ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            else:
                rows = connection.execute("SELECT signal_id,symbol,timeframe,direction,classification,confidence,entry_low,entry_high,reference_entry,stop_loss,take_profit_1,take_profit_2,take_profit_3,take_profit_4,created_at FROM signals WHERE symbol=? ORDER BY created_at DESC LIMIT ?", (canonical_symbol, limit)).fetchall()
        finally:
            connection.close()
        fields = ("signal_id", "symbol", "timeframe", "direction", "classification", "confidence", "entry_low", "entry_high", "reference_entry", "stop_loss", "take_profit_1", "take_profit_2", "take_profit_3", "take_profit_4", "created_at")
        return {"signals": [dict(zip(fields, row)) for row in rows]}

    @app.get("/api/signals/{signal_id}")
    def signal_detail(signal_id: str) -> dict[str, Any]:
        database = Database(path); database.open()
        try:
            repository = SignalRepository(database)
            record = repository.get(signal_id)
            if record is None:
                raise HTTPException(status_code=404, detail="Signal not found")
            return {"signal_id": record.signal_id, "symbol": record.symbol, "timeframe": record.timeframe,
                    "direction": str(record.direction), "classification": str(record.classification),
                    "confidence": str(record.confidence), "entry_low": str(record.entry_low), "entry_high": str(record.entry_high),
                    "reference_entry": str(record.reference_entry), "stop_loss": str(record.stop_loss),
                    "take_profit_1": str(record.take_profit_1), "take_profit_2": str(record.take_profit_2),
                    "take_profit_3": str(record.take_profit_3), "take_profit_4": str(record.take_profit_4) if record.take_profit_4 else None,
                    "created_at": record.created_at.isoformat(), "evidence": repository.get_evidence(signal_id)}
        finally:
            database.close()

    @app.get("/api/phase9")
    def phase9_report() -> dict[str, Any]:
        try:
            payload = __import__('json').loads(validation_report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {"available": False, "status": "REPORT_UNAVAILABLE", "report": None}
        if not isinstance(payload, dict):
            return {"available": False, "status": "INVALID_REPORT", "report": None}
        return {"available": True, "status": payload.get("status", "UNKNOWN"), "report": payload}

    @app.get("/api/notifications")
    def notifications(signal_id: str = Query(min_length=1)) -> dict[str, Any]:
        connection = _open_connection(path)
        try:
            rows = connection.execute(
                "SELECT provider,success,attempts,error FROM notifications WHERE signal_id=? ORDER BY id",
                (signal_id,),
            ).fetchall()
        finally:
            connection.close()
        fields = ("provider", "success", "attempts", "error")
        return {"notifications": [dict(zip(fields, (row[0], bool(row[1]), row[2], row[3]))) for row in rows]}

    @app.get("/api/backtests")
    def backtests() -> dict[str, Any]:
        connection = _open_connection(path)
        try:
            rows = connection.execute("SELECT run_id,symbol,timeframe,status,warnings,created_at FROM backtest_runs ORDER BY created_at DESC").fetchall()
        finally:
            connection.close()
        fields = ("run_id", "symbol", "timeframe", "status", "warnings", "created_at")
        return {"backtests": [dict(zip(fields, (row[0], row[1], row[2], row[3], __import__('json').loads(row[4]), row[5]))) for row in rows]}

    @app.get("/api/backtests/{run_id}")
    def backtest_detail(run_id: str) -> dict[str, Any]:
        database = Database(path); database.open()
        try:
            repository = BacktestRepository(database)
            if repository.get_run(run_id) is None:
                raise HTTPException(status_code=404, detail="Backtest not found")
            report = HistoricalPerformanceReport(repository).run(run_id)
            trades = repository.list_trades(run_id)
            report["trades"] = [{"trade_id": trade.trade_id, "signal_time": trade.signal_time.isoformat(),
                                 "direction": trade.direction, "entry_price": str(trade.entry_price) if trade.entry_price is not None else None,
                                 "stop_loss": str(trade.stop_loss) if trade.stop_loss is not None else None,
                                 "take_profit_1": str(trade.take_profit_1) if trade.take_profit_1 is not None else None,
                                 "take_profit_2": str(trade.take_profit_2) if trade.take_profit_2 is not None else None,
                                 "take_profit_3": str(trade.take_profit_3) if trade.take_profit_3 is not None else None,
                                 "score_total": str(trade.score_total), "score_classification": trade.score_classification,
                                 "exit_time": trade.exit_time.isoformat() if trade.exit_time else None,
                                 "exit_reason": trade.exit_reason, "gross_r": str(trade.gross_r) if trade.gross_r is not None else None,
                                 "costs_r": str(trade.costs_r) if trade.costs_r is not None else None,
                                 "net_r": str(trade.net_r) if trade.net_r is not None else None,
                                 "resolution_method": trade.resolution_method, "ambiguous_intrabar": trade.ambiguous_intrabar,
                                 "bars_in_trade": trade.bars_in_trade, "mfe_r": str(trade.mfe_r) if trade.mfe_r is not None else None,
                                 "mae_r": str(trade.mae_r) if trade.mae_r is not None else None,
                                 "symbol": trade.symbol, "regime": trade.regime, "session": trade.session} for trade in trades]
            return report
        finally:
            database.close()

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Multi-Pair CSD Signal Engine dashboard")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()
    settings = load_settings(args.config)
    uvicorn.run(create_dashboard_app(settings.database_path, settings.enabled_symbols), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
