export async function renderDashboard(container) {
    // 1. 注入 HTML 骨架
    container.innerHTML = `
        <div class="dash-container">
            <div class="kpi-grid">
                <div class="stat-card border-l-4 border-blue-500"><div class="stat-label">总库存</div><div class="stat-num" id="d-total">-</div></div>
                <div class="stat-card border-l-4 border-purple-500"><div class="stat-label text-purple-600">累计分发</div><div class="stat-num text-purple-700" id="d-dist">-</div></div>
                <div class="stat-card border-l-4 border-orange-500"><div class="stat-label text-orange-600">待发布</div><div class="stat-num text-orange-700" id="d-pending">-</div></div>
                <div class="stat-card"><div class="stat-label">今日 入库 / 发布</div><div class="flex items-baseline gap-2 mt-auto"><span class="text-3xl font-black text-slate-800" id="d-today-in">0</span><span class="text-slate-400">/</span><span class="text-3xl font-black text-green-600" id="d-today-out">0</span></div></div>
                <div class="stat-card"><div class="stat-label">本月 入库 / 发布</div><div class="flex items-baseline gap-2 mt-auto"><span class="text-3xl font-black text-slate-800" id="d-month-in">0</span><span class="text-slate-400">/</span><span class="text-3xl font-black text-green-600" id="d-month-out">0</span></div></div>
            </div>
            
            <div class="chart-grid">
                <div class="chart-box"><div class="chart-title">🏆 主播产出 Top 5</div><div id="chart-host" class="flex-1"></div></div>
                <div class="chart-box"><div class="chart-title">📊 类型占比</div><div id="chart-type" class="flex-1"></div></div>
                <div class="chart-box"><div class="chart-title">🕸️ 平台分发</div><div id="chart-plat" class="flex-1"></div></div>
            </div>
            
            <div class="trend-box">
                <div class="chart-title">
                    <span>📈 业务趋势</span>
                    <div class="flex gap-2">
                        <button class="text-xs px-2 py-1 rounded bg-slate-100 dim-btn" data-d="day">日</button>
                        <button class="text-xs px-2 py-1 rounded bg-slate-100 dim-btn" data-d="week">周</button>
                        <button class="text-xs px-2 py-1 rounded bg-slate-100 dim-btn" data-d="month">月</button>
                    </div>
                </div>
                <div id="chart-trend" class="flex-1 h-full"></div>
            </div>
            
            <div class="matrix-box">
                <div class="matrix-header">📱 账号分发矩阵</div>
                <table class="matrix-table">
                    <thead><tr><th style="width:30%">平台账号</th><th style="width:15%">今日🔥</th><th style="width:15%">本周</th><th style="width:15%">本月</th><th style="width:25%">年度</th></tr></thead>
                    <tbody id="matrix-body"></tbody>
                </table>
            </div>
        </div>`;

    // 2. 加载数据
    await loadData('day');

    // 3. 绑定维度切换事件
    container.querySelectorAll('.dim-btn').forEach(btn => {
        btn.onclick = () => loadData(btn.dataset.d);
    });

    async function loadData(dim) {
        const res = await fetch(`/api/dashboard?dim=${dim}`);
        const data = await res.json();
        
        // 填充文本
        document.getElementById('d-total').innerText = data.kpi.total;
        document.getElementById('d-dist').innerText = data.kpi.dist_total;
        document.getElementById('d-pending').innerText = data.kpi.pending;
        document.getElementById('d-today-in').innerText = data.kpi.today_in;
        document.getElementById('d-today-out').innerText = data.kpi.today_out;
        document.getElementById('d-month-in').innerText = data.kpi.month_in;
        document.getElementById('d-month-out').innerText = data.kpi.month_out;
        
        // 填充矩阵
        document.getElementById('matrix-body').innerHTML = data.matrix.map((r, i) => `
            <tr>
                <td class="font-bold flex items-center gap-2"><span class="w-5 h-5 rounded bg-slate-100 text-slate-500 text-xs flex items-center justify-center">${i+1}</span>${r.name}</td>
                <td class="${r.day>0?'val-today':''}">${r.day}</td><td>${r.week}</td><td>${r.month}</td><td class="font-mono font-bold">${r.year}</td>
            </tr>`).join('');

        // 渲染图表
        renderCharts(data);
    }

    function renderCharts(data) {
        const ct = echarts.init(document.getElementById('chart-trend'));
        ct.setOption({
            tooltip:{trigger:'axis'}, legend:{bottom:0}, grid:{top:20,left:40,right:20,bottom:30},
            xAxis:{type:'category',data:data.trend.dates}, yAxis:{type:'value'},
            series:[{name:'入库',type:'line',data:data.trend.in,smooth:true,areaStyle:{opacity:0.1}}, {name:'发布',type:'bar',data:data.trend.out,itemStyle:{color:'#10b981'}}]
        });

        const ch = echarts.init(document.getElementById('chart-host'));
        ch.setOption({
            tooltip:{trigger:'axis'}, grid:{top:10,left:60,right:20,bottom:20}, xAxis:{type:'value'}, 
            yAxis:{type:'category',data:data.hosts.map(i=>i.name).reverse()}, 
            series:[{type:'bar',data:data.hosts.map(i=>i.value).reverse(),itemStyle:{color:'#f59e0b',borderRadius:[0,4,4,0]}}]
        });

        const ctyp = echarts.init(document.getElementById('chart-type'));
        ctyp.setOption({ tooltip:{trigger:'item'}, series:[{type:'pie',radius:['40%','70%'],data:data.types}] });

        const cplat = echarts.init(document.getElementById('chart-plat'));
        cplat.setOption({
            tooltip:{}, radar:{indicator:data.plats.map(p=>({name:p.name, max:Math.max(...data.plats.map(v=>v.value),10)}))}, 
            series:[{type:'radar',data:[{value:data.plats.map(p=>p.value),name:'分发量'}]}]
        });
        
        window.onresize = () => { ct.resize(); ch.resize(); ctyp.resize(); cplat.resize(); };
    }
}