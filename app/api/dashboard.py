from __future__ import annotations


DASHBOARD_HTML = r"""<!doctype html>
<html lang="id">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>IDX Data Dashboard</title>
  <style>
    :root{color-scheme:light;--ink:#17212b;--muted:#64748b;--line:#dce3e8;--soft:#f5f7f8;--navy:#102a43;--teal:#087f73;--teal-dark:#06675e;--blue:#1d4ed8;--danger:#b42318;--success:#18794e;--shadow:0 10px 30px rgba(15,42,67,.08)}
    *{box-sizing:border-box}[hidden]{display:none!important}body{margin:0;background:#f6f8fa;color:var(--ink);font:14px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}button,input{font:inherit}
    .shell{min-height:100vh}.topbar{height:64px;background:var(--navy);color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 max(24px,calc((100vw - 1240px)/2));box-shadow:0 2px 12px rgba(15,42,67,.2)}
    .brand{display:flex;align-items:center;gap:12px;font-weight:800;letter-spacing:.01em}.mark{display:grid;place-items:center;width:34px;height:34px;border-radius:9px;background:#fff;color:var(--teal);font-size:18px}.connection{display:flex;align-items:center;gap:8px;color:#d8e7ef;font-size:13px}.dot{width:8px;height:8px;border-radius:50%;background:#34d399;box-shadow:0 0 0 4px rgba(52,211,153,.15)}
    main{width:min(1240px,calc(100% - 32px));margin:28px auto 48px}.intro{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin-bottom:20px}.intro h1{font-size:27px;line-height:1.2;margin:0 0 5px}.intro p{margin:0;color:var(--muted)}
    .cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:20px}.stat{background:#fff;border:1px solid var(--line);border-radius:12px;padding:18px;box-shadow:var(--shadow)}.stat-label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;font-weight:700}.stat-value{font-size:25px;font-weight:800;margin-top:5px;white-space:nowrap}.stat-note{font-size:12px;color:var(--muted);margin-top:3px}
    .grid{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(300px,.75fr);gap:18px}.panel{background:#fff;border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);overflow:hidden}.panel-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:18px 20px;border-bottom:1px solid var(--line)}.panel-head h2{font-size:16px;margin:0}.panel-head p{font-size:12px;color:var(--muted);margin:2px 0 0}.panel-body{padding:20px}
    .filters{display:grid;grid-template-columns:1.3fr 1fr 1fr auto;gap:10px;align-items:end}.field{display:grid;gap:6px}.field label{font-size:12px;font-weight:700;color:#475569}.field input{width:100%;height:40px;border:1px solid #cbd5e1;border-radius:8px;padding:0 11px;background:#fff;color:var(--ink);outline:none}.field input:focus{border-color:var(--teal);box-shadow:0 0 0 3px rgba(8,127,115,.12)}
    .btn{height:40px;border:0;border-radius:8px;padding:0 15px;font-weight:750;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:7px;white-space:nowrap}.btn:disabled,.btn.disabled{opacity:.5;cursor:not-allowed;pointer-events:none}.btn-primary{background:var(--teal);color:#fff}.btn-primary:hover{background:var(--teal-dark)}.btn-secondary{background:#e8eef9;color:#183b76}.btn-quiet{background:#eef2f4;color:#334155}.btn-danger{background:#fff1f0;color:var(--danger);border:1px solid #fecaca}.export-actions{display:flex;gap:8px;flex-wrap:wrap}.export-actions a{text-decoration:none}
    .table-wrap{margin-top:18px;border:1px solid var(--line);border-radius:10px;overflow:auto;max-height:480px}table{width:100%;border-collapse:collapse;min-width:740px}th{position:sticky;top:0;z-index:1;background:#e9f5f3;color:#174a45;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.045em;padding:11px 9px;border-bottom:1px solid #b8dcd7}td{padding:10px 9px;border-bottom:1px solid #edf0f2;white-space:nowrap;font-variant-numeric:tabular-nums}tbody tr:hover{background:#f8fbfb}.number{text-align:right}.empty{padding:44px 20px;text-align:center;color:var(--muted)}
    .actions-stack{display:grid;gap:12px}.action-card{border:1px solid var(--line);border-radius:10px;padding:14px}.action-card h3{font-size:14px;margin:0 0 4px}.action-card p{font-size:12px;color:var(--muted);margin:0 0 12px}.action-row{display:flex;gap:8px}.action-row .field{flex:1}.action-row .btn{margin-top:23px}.backfill-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.backfill-grid .wide{grid-column:1/-1}
    .job{margin-top:16px;border-top:1px solid var(--line);padding-top:16px}.badge{display:inline-flex;border-radius:99px;padding:4px 9px;font-size:11px;font-weight:800}.RUNNING{background:#fff7d6;color:#8a5b00}.SUCCESS{background:#dcfce7;color:var(--success)}.FAILED{background:#fee2e2;color:var(--danger)}pre{max-height:170px;overflow:auto;background:#111827;color:#d1fae5;border-radius:8px;padding:12px;font:11px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace;white-space:pre-wrap;word-break:break-word}.runs{margin-top:18px}.run-line{display:grid;grid-template-columns:1fr auto;gap:10px;padding:10px 0;border-bottom:1px solid #edf0f2}.run-title{font-weight:700;font-size:13px}.run-meta{font-size:11px;color:var(--muted)}
    .notice{display:none;margin:0 0 16px;padding:11px 14px;border-radius:9px;border:1px solid}.notice.show{display:block}.notice.info{background:#eff6ff;border-color:#bfdbfe;color:#1e40af}.notice.error{background:#fff1f0;border-color:#fecaca;color:#991b1b}.notice.success{background:#ecfdf5;border-color:#bbf7d0;color:#166534}
    @media(max-width:950px){.cards{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}.filters{grid-template-columns:1fr 1fr}.filters .field:first-child{grid-column:1/-1}.filters .btn{width:100%}}
    @media(max-width:560px){main{width:min(100% - 20px,1240px);margin-top:18px}.topbar{padding:0 14px}.connection span:last-child{display:none}.intro{align-items:flex-start;flex-direction:column}.cards{grid-template-columns:1fr 1fr;gap:9px}.stat{padding:14px}.stat-value{font-size:20px}.filters{grid-template-columns:1fr}.filters .field:first-child{grid-column:auto}.export-actions{width:100%}.export-actions .btn{flex:1}.panel-head{align-items:flex-start;flex-direction:column}.panel-head>.btn{width:100%}.backfill-grid{grid-template-columns:1fr}.backfill-grid .wide{grid-column:auto}}
  </style>
</head>
<body>
<div class="shell">
  <header class="topbar"><div class="brand"><div class="mark">ID</div><span>IDX Data</span></div><div class="connection"><span class="dot"></span><span id="connectionText">Menghubungkan database</span></div></header>
  <main>
    <section class="intro"><div><h1>Market Data Dashboard</h1><p>Scraping, verifikasi, tampilkan, dan ekspor data OHLCV tanpa command line.</p></div><button class="btn btn-quiet" id="refreshAll">Muat ulang</button></section>
    <div class="notice" id="notice"></div>
    <section class="cards">
      <article class="stat"><div class="stat-label">Total candle</div><div class="stat-value" id="totalRows">—</div><div class="stat-note">Baris OHLCV tervalidasi</div></article>
      <article class="stat"><div class="stat-label">Simbol tersimpan</div><div class="stat-value" id="totalSymbols">—</div><div class="stat-note">Kode saham unik</div></article>
      <article class="stat"><div class="stat-label">Data terbaru</div><div class="stat-value" id="latestDate">—</div><div class="stat-note" id="dateRange">Rentang data</div></article>
      <article class="stat"><div class="stat-label">Proses terakhir</div><div class="stat-value" id="lastStatus">—</div><div class="stat-note" id="lastJob">Belum ada proses</div></article>
    </section>

    <section class="grid">
      <article class="panel">
        <div class="panel-head"><div><h2>Data OHLCV</h2><p>Harga ditampilkan dalam Rupiah.</p></div><div class="export-actions"><button class="btn btn-quiet" id="resetView">Reset tampilan</button><a class="btn btn-secondary" id="csvLink" href="#">CSV</a><a class="btn btn-primary" id="xlsxLink" href="#">Excel</a></div></div>
        <div class="panel-body">
          <form class="filters" id="dataForm">
            <div class="field"><label for="symbols">Simbol saham</label><input id="symbols" value="BBCA, BBRI, TLKM" placeholder="Contoh: BBCA, BBRI"></div>
            <div class="field"><label for="fromDate">Dari tanggal</label><input id="fromDate" type="date"></div>
            <div class="field"><label for="toDate">Sampai tanggal</label><input id="toDate" type="date"></div>
            <button class="btn btn-primary" type="submit">Tampilkan</button>
          </form>
          <div class="table-wrap"><table><thead><tr><th>Simbol</th><th>Tanggal</th><th class="number">Open</th><th class="number">High</th><th class="number">Low</th><th class="number">Close</th><th class="number">Perubahan</th><th class="number">Volume</th></tr></thead><tbody id="dataBody"><tr><td class="empty" colspan="8">Memuat data…</td></tr></tbody></table></div>
        </div>
      </article>

      <aside>
        <article class="panel">
          <div class="panel-head"><div><h2>Scraping dan verifikasi</h2><p>Satu proses berjalan pada satu waktu.</p></div><button class="btn btn-danger" id="resetJob">Reset scraping</button></div>
          <div class="panel-body">
            <div class="actions-stack">
              <div class="action-card"><h3>Perbarui daftar saham</h3><p>Scraping daftar IDX lalu verifikasi kode dan nama emiten.</p><button class="btn btn-secondary job-button" data-job="sync">Ambil dan verifikasi saham</button></div>
              <div class="action-card"><h3>Ambil data terbaru</h3><p>Scraping data pasar terbaru yang belum tersimpan.</p><div class="action-row"><div class="field"><label for="dailyEnd">Sampai tanggal</label><input type="date" id="dailyEnd"></div><button class="btn btn-primary job-button" data-job="daily">Ambil terbaru</button></div></div>
              <div class="action-card"><h3>Ambil data historis</h3><p>Scraping dan verifikasi histori untuk saham serta rentang tertentu.</p><form id="backfillForm" class="backfill-grid"><div class="field wide"><label for="backfillSymbols">Kode saham</label><input id="backfillSymbols" value="BBCA, BBRI, TLKM"></div><div class="field"><label for="backfillStart">Mulai</label><input id="backfillStart" type="date" required></div><div class="field"><label for="backfillEnd">Selesai</label><input id="backfillEnd" type="date" required></div><button class="btn btn-primary wide" type="submit">Mulai scraping historis</button></form></div>
            </div>
            <div class="job" id="jobPanel"><div id="jobSummary" class="run-meta">Belum ada proses scraping pada sesi ini.</div><pre id="jobOutput" hidden></pre></div>
            <div class="runs"><h3>Riwayat ETL</h3><div id="runList"><div class="run-meta">Memuat riwayat…</div></div></div>
          </div>
        </article>
      </aside>
    </section>
  </main>
</div>
<script>
  const byId = id => document.getElementById(id);
  const rupiah = new Intl.NumberFormat('id-ID',{style:'currency',currency:'IDR',maximumFractionDigits:0});
  const integer = new Intl.NumberFormat('id-ID');
  const percent = new Intl.NumberFormat('id-ID',{style:'percent',minimumFractionDigits:2,maximumFractionDigits:2});
  const viewResetKey = 'idx-data:view-reset:v1';
  const scrapingResetKey = 'idx-data:scraping-reset:v1';
  let jobTimer;

  function isoDate(value){return value.toISOString().slice(0,10)}
  function isReset(key){try{return localStorage.getItem(key)==='1'}catch{return false}}
  function rememberReset(key){try{localStorage.setItem(key,'1')}catch{}}
  function forgetReset(key){try{localStorage.removeItem(key)}catch{}}
  function setDefaults(){const now=new Date();const before=new Date(now);before.setDate(now.getDate()-7);if(isReset(viewResetKey)){byId('symbols').value='';byId('fromDate').value='';byId('toDate').value=''}else{byId('symbols').value='BBCA, BBRI, TLKM';byId('toDate').value=isoDate(now);byId('fromDate').value=isoDate(before)}if(isReset(scrapingResetKey)){byId('dailyEnd').value='';byId('backfillSymbols').value='';byId('backfillStart').value='';byId('backfillEnd').value=''}else{byId('dailyEnd').value=isoDate(now);byId('backfillSymbols').value='BBCA, BBRI, TLKM';byId('backfillEnd').value=isoDate(now);byId('backfillStart').value=isoDate(before)}}
  function showNotice(message,type='info'){const node=byId('notice');node.className=`notice show ${type}`;node.textContent=message;clearTimeout(node._timer);node._timer=setTimeout(()=>node.className='notice',5000)}
  async function api(url,options={}){const response=await fetch(url,options);let payload;try{payload=await response.json()}catch{payload={detail:await response.text()}}if(!response.ok)throw new Error(payload.detail||`HTTP ${response.status}`);return payload}
  function query(){const params=new URLSearchParams();const symbols=byId('symbols').value.trim();if(symbols)params.set('symbols',symbols);if(byId('fromDate').value)params.set('from',byId('fromDate').value);if(byId('toDate').value)params.set('to',byId('toDate').value);return params}
  function setExportsEnabled(enabled){for(const id of ['csvLink','xlsxLink']){const link=byId(id);link.classList.toggle('disabled',!enabled);link.setAttribute('aria-disabled',String(!enabled));if(!enabled)link.href='#'}}
  function updateExportLinks(){const params=query();byId('csvLink').href=`/export/ohlcv.csv?${params}`;byId('xlsxLink').href=`/export/ohlcv.xlsx?${params}`;setExportsEnabled(true)}
  async function loadOverview(){try{const data=await api('/ui/api/overview');byId('totalRows').textContent=integer.format(data.total_rows);byId('totalSymbols').textContent=integer.format(data.total_symbols);byId('latestDate').textContent=data.latest_date||'—';byId('dateRange').textContent=data.earliest_date?`${data.earliest_date} — ${data.latest_date}`:'Belum ada data';byId('lastStatus').textContent=data.last_run?.status||'—';byId('lastJob').textContent=data.last_run?.job_name||'Belum ada proses';byId('connectionText').textContent='Database terhubung'}catch(error){byId('connectionText').textContent='Database bermasalah';showNotice(error.message,'error')}}
  async function loadData(){const body=byId('dataBody');if(isReset(viewResetKey)){body.innerHTML='<tr><td class="empty" colspan="8">Tampilan direset. Isi filter lalu klik Tampilkan.</td></tr>';setExportsEnabled(false);return}body.innerHTML='<tr><td class="empty" colspan="8">Memuat data…</td></tr>';updateExportLinks();try{const rows=await api(`/ui/api/ohlcv?${query()}&limit=2000`);if(!rows.length){body.innerHTML='<tr><td class="empty" colspan="8">Tidak ada data pada filter ini.</td></tr>';return}body.innerHTML=rows.map(row=>{const change=Number(row.open)?(Number(row.close)-Number(row.open))/Number(row.open):0;return `<tr><td><strong>${row.symbol}</strong></td><td>${row.trade_date}</td><td class="number">${rupiah.format(row.open)}</td><td class="number">${rupiah.format(row.high)}</td><td class="number">${rupiah.format(row.low)}</td><td class="number">${rupiah.format(row.close)}</td><td class="number" style="color:${change<0?'#b42318':'#18794e'}">${percent.format(change)}</td><td class="number">${integer.format(row.volume)}</td></tr>`}).join('')}catch(error){body.innerHTML=`<tr><td class="empty" colspan="8">${error.message}</td></tr>`}}
  async function loadRuns(){try{const runs=await api('/ui/api/etl-runs?limit=6');byId('runList').innerHTML=runs.length?runs.map(run=>`<div class="run-line"><div><div class="run-title">${run.job_name}</div><div class="run-meta">Loaded ${integer.format(run.rows_loaded)} • Rejected ${integer.format(run.rows_rejected)}</div></div><span class="badge ${run.status}">${run.status}</span></div>`).join(''):'<div class="run-meta">Belum ada riwayat.</div>'}catch(error){byId('runList').innerHTML=`<div class="run-meta">${error.message}</div>`}}
  function setJobButtons(disabled){document.querySelectorAll('.job-button,#backfillForm button').forEach(button=>button.disabled=disabled)}
  function renderJob(job){const output=byId('jobOutput');const reset=byId('resetJob');if(!job){setJobButtons(false);byId('jobSummary').textContent='Belum ada proses scraping pada sesi ini.';output.hidden=true;output.textContent='';reset.disabled=false;return}const running=job.status==='RUNNING';setJobButtons(running);reset.disabled=running;byId('jobSummary').innerHTML=`<span class="badge ${job.status}">${job.status}</span> <strong>${job.name}</strong><div class="run-meta">${job.command}</div>`;output.hidden=!job.output;output.textContent=job.output||'';if(running){clearTimeout(jobTimer);jobTimer=setTimeout(pollJob,2500)}else{loadOverview();loadRuns();loadData()}}
  async function pollJob(){try{renderJob(await api('/ui/api/jobs/current'))}catch(error){showNotice(error.message,'error')}}
  async function runJob(url,payload){try{const job=await api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:payload?JSON.stringify(payload):undefined});forgetReset(scrapingResetKey);showNotice(`${job.name} dimulai.`,'success');renderJob(job)}catch(error){showNotice(error.message,'error')}}
  async function resetJob(){try{await api('/ui/api/jobs/reset',{method:'POST'});clearTimeout(jobTimer);rememberReset(scrapingResetKey);byId('dailyEnd').value='';byId('backfillSymbols').value='';byId('backfillStart').value='';byId('backfillEnd').value='';renderJob(null);showNotice('Formulir dan status scraping sudah direset. Data tersimpan tidak dihapus.','success')}catch(error){showNotice(error.message,'error')}}
  function resetView(){rememberReset(viewResetKey);byId('symbols').value='';byId('fromDate').value='';byId('toDate').value='';byId('dataBody').innerHTML='<tr><td class="empty" colspan="8">Tampilan direset. Isi filter lalu klik Tampilkan.</td></tr>';setExportsEnabled(false);showNotice('Filter dan tabel data sudah dikosongkan.','success')}
  byId('dataForm').addEventListener('submit',event=>{event.preventDefault();forgetReset(viewResetKey);loadData()});
  byId('resetView').addEventListener('click',resetView);
  byId('refreshAll').addEventListener('click',()=>{loadOverview();loadRuns();loadData();pollJob()});
  byId('resetJob').addEventListener('click',resetJob);
  document.querySelector('[data-job="sync"]').addEventListener('click',()=>runJob('/ui/api/jobs/sync-symbols'));
  document.querySelector('[data-job="daily"]').addEventListener('click',()=>runJob('/ui/api/jobs/daily',{end:byId('dailyEnd').value||null}));
  byId('backfillForm').addEventListener('submit',event=>{event.preventDefault();runJob('/ui/api/jobs/backfill',{symbols:byId('backfillSymbols').value,start:byId('backfillStart').value,end:byId('backfillEnd').value})});
  setDefaults();loadOverview();loadRuns();loadData();pollJob();
</script>
</body></html>"""
