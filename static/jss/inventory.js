/**
 * VideoHub V25.0 - Inventory Module
 * 负责视频库存管理的核心逻辑：列表、筛选、编辑、上传、设置
 */

// === 模块级状态管理 ===
let globalData = [];
let globalOptions = {};
let editingId = null;
let currPage = 1;
let totalPages = 1;

// === 主渲染函数 (导出) ===
export async function renderInventory(container, params = {}) {
    // 1. 注入 HTML 结构 (包含工具栏、筛选区、表格、分页、以及模块专属弹窗)
    container.innerHTML = `
        <div class="inventory-view h-full flex flex-col relative">
            <div class="toolbar flex justify-between items-center p-4 bg-white border-b border-slate-200 shrink-0 z-20">
                <h2 class="text-lg font-bold text-slate-800 hidden md:block">库存明细</h2>
                <div class="flex gap-3 items-center flex-1 justify-end">
                    <input id="g-search" class="t-input w-48 md:w-72 bg-slate-50 border-transparent focus:bg-white transition-all" placeholder="全局搜索: 标题/编号/备注">
                    
                    <button id="btn-filter" class="px-4 py-2 text-sm font-bold text-slate-600 bg-slate-100 rounded-lg hover:bg-slate-200 transition-colors flex items-center gap-1">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-width="2" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z"></path></svg>
                        筛选
                    </button>
                    
                    <button id="btn-settings" class="px-3 py-2 text-slate-500 hover:text-slate-800">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
                    </button>
                    
                    <div class="h-6 w-px bg-slate-300 mx-1"></div>
                    
                    <button id="btn-import" class="px-4 py-2 text-sm font-bold text-blue-600 bg-blue-50 rounded-lg hover:bg-blue-100 transition-colors">
                        导入 Excel
                    </button>
                    
                    <button id="btn-add" class="px-5 py-2 text-sm font-bold text-white bg-blue-600 rounded-lg shadow hover:bg-blue-700 transition-transform active:scale-95 flex items-center gap-1">
                        <span>+</span> 新增一行
                    </button>
                </div>
            </div>

            <div id="filter-panel" class="filter-panel bg-white border-b border-slate-200 overflow-hidden transition-all duration-300 max-h-0 px-6 shadow-sm z-10">
                <div class="grid grid-cols-2 md:grid-cols-6 gap-x-4 gap-y-4 py-6">
                    <div><label class="filter-label text-xs font-bold text-slate-500 mb-1 block">产品编号</label><input id="s-pid" list="dl-pids" class="t-input w-full border border-slate-300 rounded p-2 text-sm" placeholder="输入编号..."></div>
                    <div><label class="filter-label text-xs font-bold text-slate-500 mb-1 block">视频标题</label><input id="s-title" class="t-input w-full border border-slate-300 rounded p-2 text-sm" placeholder="包含标题..."></div>
                    
                    <div><label class="filter-label text-xs font-bold text-slate-500 mb-1 block">产品类型</label><select id="s-cat" class="t-input w-full border border-slate-300 rounded p-2 text-sm"></select></div>
                    <div><label class="filter-label text-xs font-bold text-slate-500 mb-1 block">视频类型</label><select id="s-type" class="t-input w-full border border-slate-300 rounded p-2 text-sm"></select></div>
                    
                    <div><label class="filter-label text-xs font-bold text-slate-500 mb-1 block">主播 (包含)</label><select id="s-host" class="t-input w-full border border-slate-300 rounded p-2 text-sm"></select></div>
                    <div><label class="filter-label text-xs font-bold text-slate-500 mb-1 block">当前状态</label><select id="s-status" class="t-input w-full border border-slate-300 rounded p-2 text-sm"></select></div>
                    
                    <div><label class="filter-label text-xs font-bold text-slate-500 mb-1 block">发布平台</label><select id="s-plat" class="t-input w-full border border-slate-300 rounded p-2 text-sm"></select></div>
                    
                    <div class="col-span-2">
                        <label class="filter-label text-xs font-bold text-slate-500 mb-1 block">完成时间范围</label>
                        <div class="flex gap-2"><input type="date" id="s-fin-start" class="t-input w-full border border-slate-300 rounded p-2 text-sm"><input type="date" id="s-fin-end" class="t-input w-full border border-slate-300 rounded p-2 text-sm"></div>
                    </div>
                    
                    <div class="col-span-2">
                        <label class="filter-label text-xs font-bold text-slate-500 mb-1 block">发布时间范围</label>
                        <div class="flex gap-2"><input type="date" id="s-pub-start" class="t-input w-full border border-slate-300 rounded p-2 text-sm"><input type="date" id="s-pub-end" class="t-input w-full border border-slate-300 rounded p-2 text-sm"></div>
                    </div>
                    
                    <div><label class="filter-label text-xs font-bold text-slate-500 mb-1 block">备注信息</label><input id="s-remark" class="t-input w-full border border-slate-300 rounded p-2 text-sm" placeholder="包含备注..."></div>

                    <div class="col-span-2 md:col-span-6 flex justify-end gap-2 border-t pt-4 mt-2">
                        <button id="btn-do-filter" class="px-6 py-2 bg-slate-800 text-white rounded-lg text-sm font-bold hover:bg-black transition-colors">执行查询</button>
                        <button id="btn-reset-filter" class="px-6 py-2 bg-white border border-slate-300 text-slate-700 rounded-lg text-sm font-bold hover:bg-slate-50 transition-colors">重置条件</button>
                    </div>
                </div>
            </div>

            <div class="table-wrap flex-1 overflow-auto bg-white m-6 rounded-xl border border-slate-200 shadow-sm relative">
                <table class="main-table w-full border-collapse" style="min-width: 1800px;">
                    <thead>
                        <tr>
                            <th class="w-16 text-center sticky top-0 bg-slate-50 p-3 text-xs font-bold text-slate-500 border-b z-10">图</th>
                            <th class="w-32 sticky top-0 bg-slate-50 p-3 text-xs font-bold text-slate-500 border-b z-10 text-left cursor-pointer hover:bg-slate-100" data-sort="product_id">编号 ↕</th>
                            <th class="sticky top-0 bg-slate-50 p-3 text-xs font-bold text-slate-500 border-b z-10 text-left cursor-pointer hover:bg-slate-100" style="min-width: 260px;" data-sort="title">视频标题 ↕</th>
                            <th class="w-24 sticky top-0 bg-slate-50 p-3 text-xs font-bold text-slate-500 border-b z-10 text-left cursor-pointer hover:bg-slate-100" data-sort="category">类型 ↕</th>
                            <th class="w-28 sticky top-0 bg-slate-50 p-3 text-xs font-bold text-slate-500 border-b z-10 text-left cursor-pointer hover:bg-slate-100" data-sort="finish_time">完成时间 ↕</th>
                            <th class="w-24 sticky top-0 bg-slate-50 p-3 text-xs font-bold text-slate-500 border-b z-10 text-left cursor-pointer hover:bg-slate-100" data-sort="video_type">视类 ↕</th>
                            <th class="w-32 sticky top-0 bg-slate-50 p-3 text-xs font-bold text-slate-500 border-b z-10 text-left cursor-pointer hover:bg-slate-100" data-sort="host">主播 ↕</th>
                            <th class="w-24 text-center sticky top-0 bg-slate-50 p-3 text-xs font-bold text-slate-500 border-b z-10 cursor-pointer hover:bg-slate-100" data-sort="status">状态 ↕</th>
                            <th class="w-32 sticky top-0 bg-slate-50 p-3 text-xs font-bold text-slate-500 border-b z-10 text-left cursor-pointer hover:bg-slate-100" data-sort="platform">平台 ↕</th>
                            <th class="w-32 sticky top-0 bg-slate-50 p-3 text-xs font-bold text-slate-500 border-b z-10 text-left cursor-pointer hover:bg-slate-100" data-sort="publish_time">发布时间 ↕</th>
                            <th class="w-40 sticky top-0 bg-slate-50 p-3 text-xs font-bold text-slate-500 border-b z-10 text-left cursor-pointer hover:bg-slate-100" data-sort="remark">备注 ↕</th>
                            <th class="w-20 text-center sticky top-0 right-0 bg-slate-50 p-3 text-xs font-bold text-slate-500 border-b border-l shadow-sm z-20">操作</th>
                        </tr>
                    </thead>
                    <tbody id="table-body">
                        </tbody>
                </table>
            </div>

            <div class="h-14 bg-white border-t border-slate-200 px-6 flex justify-between items-center shrink-0">
                <span id="page-info" class="text-xs text-slate-500 font-medium">正在加载...</span>
                <div class="flex gap-2">
                    <button id="btn-prev" class="px-4 py-1.5 bg-slate-100 rounded-md text-xs font-bold hover:bg-slate-200 disabled:opacity-50 transition-colors">◀ 上一页</button>
                    <button id="btn-next" class="px-4 py-1.5 bg-slate-100 rounded-md text-xs font-bold hover:bg-slate-200 disabled:opacity-50 transition-colors">下一页 ▶</button>
                </div>
            </div>
        </div>

        <div id="import-modal" class="modal hidden fixed inset-0 bg-black/50 z-50 flex items-center justify-center">
            <div class="bg-white rounded-xl w-[400px] p-8 text-center shadow-2xl">
                <div class="text-5xl mb-4">📂</div>
                <h3 class="font-bold text-xl mb-4 text-slate-800">批量导入数据</h3>
                <p class="text-sm text-slate-500 mb-6">请确认 Excel 文件已上传至 NAS <code class="bg-slate-100 px-1 rounded">temp_uploads</code> 目录</p>
                <button id="btn-start-import" class="w-full bg-slate-800 text-white py-3 rounded-lg font-bold hover:bg-black transition-transform active:scale-95">开始扫描并导入</button>
                <button id="btn-close-import" class="mt-4 text-slate-400 text-xs hover:text-slate-600 w-full">关闭窗口</button>
            </div>
        </div>

        <div id="settings-modal" class="modal hidden fixed inset-0 bg-black/50 z-50 flex items-center justify-center">
            <div class="bg-white rounded-xl w-[450px] p-6 shadow-2xl">
                <h3 class="font-bold mb-6 text-lg text-slate-800 border-b pb-2">全局选项配置</h3>
                <div class="space-y-4">
                    <div><label class="text-xs font-bold text-slate-400 mb-1 block">主播列表</label><textarea id="set-hosts" class="t-input w-full border border-slate-300 rounded p-2 text-sm h-20 resize-none"></textarea></div>
                    <div><label class="text-xs font-bold text-slate-400 mb-1 block">产品类型</label><input id="set-cats" class="t-input w-full border border-slate-300 rounded p-2 text-sm"></div>
                    <div><label class="text-xs font-bold text-slate-400 mb-1 block">视频类型</label><input id="set-types" class="t-input w-full border border-slate-300 rounded p-2 text-sm"></div>
                    <div><label class="text-xs font-bold text-slate-400 mb-1 block">发布平台</label><input id="set-plats" class="t-input w-full border border-slate-300 rounded p-2 text-sm"></div>
                </div>
                <button id="btn-save-settings" class="w-full bg-blue-600 text-white py-3 rounded-lg font-bold mt-6 hover:bg-blue-700 shadow-lg transition-all">保存生效</button>
                <button id="btn-close-settings" class="w-full mt-2 text-slate-400 text-xs hover:text-slate-600">取消关闭</button>
            </div>
        </div>
    `;

    // 2. 绑定静态事件 (使用 ID 选择器)
    bindEvents(params);

    // 3. 初始化数据
    await loadOptions();
    
    // 4. 处理跳转参数 (如果从产品页过来)
    if(params.pid) {
        document.getElementById('s-pid').value = params.pid;
        document.getElementById('filter-panel').classList.add('open');
        // 自动查询
        loadData(1);
    } else {
        loadData(1);
    }
}

// === 事件绑定函数 ===
function bindEvents(params) {
    // 顶部按钮
    document.getElementById('btn-filter').onclick = () => document.getElementById('filter-panel').classList.toggle('open');
    document.getElementById('btn-settings').onclick = openSettings;
    document.getElementById('btn-import').onclick = openImport;
    document.getElementById('btn-add').onclick = addNewRow;
    
    // 筛选区
    document.getElementById('btn-do-filter').onclick = () => loadData(1);
    document.getElementById('btn-reset-filter').onclick = resetFilters;
    document.getElementById('g-search').onkeydown = (e) => e.key === 'Enter' && loadData(1);
    
    // 分页
    document.getElementById('btn-prev').onclick = () => changePage(-1);
    document.getElementById('btn-next').onclick = () => changePage(1);
    
    // 弹窗关闭
    document.getElementById('btn-close-import').onclick = () => document.getElementById('import-modal').classList.remove('active');
    document.getElementById('btn-close-settings').onclick = () => document.getElementById('settings-modal').classList.remove('active');
    
    // 弹窗操作
    document.getElementById('btn-start-import').onclick = startImport;
    document.getElementById('btn-save-settings').onclick = saveSettings;

    // 表格表头排序 (Event Delegation)
    document.querySelector('thead').addEventListener('click', (e) => {
        if(e.target.dataset.sort) {
            // 这里可以实现排序逻辑，暂略，重新加载带 sort 参数即可
            const sortCol = e.target.dataset.sort;
            // 简单实现：切换排序
            loadData(1, sortCol); // 需改造 loadData 支持传参
        }
    });

    // 表格内容交互 (Event Delegation - 核心部分)
    const tbody = document.getElementById('table-body');
    tbody.addEventListener('click', handleTableClick);
    tbody.addEventListener('drop', handleTableDrop);
    tbody.addEventListener('dragover', (e) => e.preventDefault()); // 允许 drop
    tbody.addEventListener('paste', handleTablePaste);
}

// === 核心数据加载逻辑 ===

async function loadOptions() {
    const res = await fetch('/api/options');
    globalOptions = await res.json();
    
    const fill = (id, list, label) => {
        const el = document.getElementById(id);
        if(el) el.innerHTML = `<option value="">全部${label}</option>` + list.map(i => `<option value="${i}">${i}</option>`).join('');
    };
    
    fill('s-cat', globalOptions.categories, '类型');
    fill('s-type', globalOptions.video_types, '视类');
    fill('s-host', globalOptions.hosts, '主播');
    fill('s-status', globalOptions.statuses, '状态');
    fill('s-plat', globalOptions.platforms, '平台');
    
    // 填充 datalist
    const dl = document.getElementById('dl-pids');
    if(dl) dl.innerHTML = globalOptions.product_ids.map(i => `<option value="${i}">`).join('');
}

async function loadData(page, sortBy = 'id') {
    currPage = page || currPage;
    
    const params = new URLSearchParams({
        page: currPage, 
        size: 100, 
        sort_by: sortBy,
        keyword: document.getElementById('g-search').value,
        product_id: document.getElementById('s-pid').value,
        title: document.getElementById('s-title').value,
        remark: document.getElementById('s-remark').value,
        host: document.getElementById('s-host').value,
        status: document.getElementById('s-status').value,
        category: document.getElementById('s-cat').value,
        video_type: document.getElementById('s-type').value,
        platform: document.getElementById('s-plat').value,
        finish_start: document.getElementById('s-fin-start').value,
        finish_end: document.getElementById('s-fin-end').value,
        publish_start: document.getElementById('s-pub-start').value,
        publish_end: document.getElementById('s-pub-end').value
    });

    try {
        const res = await fetch(`/api/videos?${params}`);
        const data = await res.json();
        globalData = data.items;
        totalPages = data.total_pages;
        
        document.getElementById('page-info').innerText = `共 ${data.total} 条 · ${data.page}/${data.total_pages} 页`;
        
        // 更新分页按钮状态
        document.getElementById('btn-prev').disabled = data.page <= 1;
        document.getElementById('btn-next').disabled = data.page >= data.total_pages;
        
        renderTable(data.items);
    } catch(e) {
        console.error("Load Data Error:", e);
        window.showToast("数据加载失败", "error");
    }
}

// === 表格渲染 ===

function renderTable(items) {
    const tbody = document.getElementById('table-body');
    if(!tbody) return;

    tbody.innerHTML = items.map(v => {
        const isEdit = (v.id === editingId);
        // 空值处理
        const cln = s => (s && s !== 'nan' && s !== 'None') ? s : '';
        const img = (v.image_url && !v.image_url.includes('default')) ? v.image_url : '/assets/default.png';

        if (isEdit) {
            // 编辑模式
            const mkSel = (k, list) => `<select data-field="${k}" class="t-input w-full border border-blue-300 rounded p-1 text-sm bg-white">${list.map(o => `<option ${o===v[k]?'selected':''}>${o}</option>`).join('')}</select>`;
            const mkInp = (k, ph) => `<input data-field="${k}" class="t-input w-full border border-blue-300 rounded p-1 text-sm" value="${cln(v[k])}" placeholder="${ph}">`;
            // 多选输入框模拟
            const mkMul = (k, type) => `<input data-field="${k}" class="t-input w-full border border-blue-300 rounded p-1 text-sm cursor-pointer multi-trigger" value="${cln(v[k])}" readonly data-type="${type}" placeholder="点击选择">`;
            
            return `
            <tr class="editing ${v.isNew ? 'bg-green-50' : 'bg-blue-50'}" data-id="${v.id}">
                <td class="p-2 text-center align-middle">
                    <div class="img-cell w-10 h-10 mx-auto border rounded bg-white relative group cursor-pointer" data-action="trigger-upload">
                        <img src="${img}" class="w-full h-full object-cover rounded">
                        <div class="absolute inset-0 bg-black/50 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 text-xs font-bold">换图</div>
                    </div>
                    <input type="file" class="hidden file-upload-input" accept="image/*">
                    <input type="hidden" data-field="image_url" value="${cln(v.image_url)}">
                </td>
                <td class="p-2 align-middle">${mkInp('product_id', '编号')}</td>
                <td class="p-2 align-middle">${mkInp('title', '标题')}</td>
                <td class="p-2 align-middle">${mkSel('category', globalOptions.categories)}</td>
                <td class="p-2 align-middle"><input type="date" data-field="finish_time" class="t-input w-full border border-blue-300 rounded p-1 text-sm" value="${cln(v.finish_time)}"></td>
                <td class="p-2 align-middle">${mkSel('video_type', globalOptions.video_types)}</td>
                <td class="p-2 align-middle">${mkMul('host', 'hosts')}</td>
                <td class="p-2 align-middle">${mkSel('status', globalOptions.statuses)}</td>
                <td class="p-2 align-middle">${mkMul('platform', 'platforms')}</td>
                <td class="p-2 align-middle"><input type="datetime-local" data-field="publish_time" class="t-input w-full border border-blue-300 rounded p-1 text-sm" value="${cln(v.publish_time).replace(' ', 'T')}"></td>
                <td class="p-2 align-middle">${mkInp('remark', '...')}</td>
                <td class="p-2 text-center align-middle sticky right-0 bg-blue-50 border-l">
                    <button class="bg-blue-600 text-white px-3 py-1 rounded text-xs shadow hover:bg-blue-700" data-action="save">保存</button>
                    <button class="text-slate-400 hover:text-slate-600 ml-1 text-xs" data-action="cancel">取消</button>
                </td>
            </tr>`;
        } else {
            // 浏览模式
            const pill = (txt, type) => {
                if(!txt) return '';
                const items = txt.split(/[,，]/);
                return items.map(i => {
                    let color = 'bg-slate-100 text-slate-600';
                    if(type === 'status') {
                        if(i.includes('已')) color = 'bg-emerald-100 text-emerald-700';
                        else if(i.includes('待')) color = 'bg-orange-50 text-orange-600';
                    }
                    return `<span class="inline-block px-2 py-0.5 rounded text-xs font-medium mr-1 ${color}">${i}</span>`;
                }).join('');
            };

            return `
            <tr class="hover:bg-slate-50 border-b border-slate-100 last:border-0 transition-colors" data-id="${v.id}">
                <td class="p-2 text-center align-middle">
                    <div class="w-10 h-10 mx-auto rounded border bg-slate-100 overflow-hidden cursor-zoom-in" data-action="preview-img" data-src="${img}">
                        <img src="${img}" class="w-full h-full object-cover">
                    </div>
                </td>
                <td class="p-2 text-sm text-slate-500 font-mono">${cln(v.product_id)}</td>
                <td class="p-2 text-sm font-bold text-slate-700 max-w-xs truncate" title="${cln(v.title)}">${cln(v.title)}</td>
                <td class="p-2 text-sm">${pill(cln(v.category))}</td>
                <td class="p-2 text-xs text-slate-400 font-mono">${cln(v.finish_time)}</td>
                <td class="p-2 text-sm">${pill(cln(v.video_type))}</td>
                <td class="p-2 text-sm">${pill(cln(v.host))}</td>
                <td class="p-2 text-center">${pill(cln(v.status), 'status')}</td>
                <td class="p-2 text-sm">${pill(cln(v.platform))}</td>
                <td class="p-2 text-xs text-slate-400 font-mono">${cln(v.publish_time).replace('T', ' ')}</td>
                <td class="p-2 text-xs text-slate-400 max-w-[100px] truncate" title="${cln(v.remark)}">${cln(v.remark)}</td>
                <td class="p-2 text-center align-middle sticky right-0 bg-white group-hover:bg-slate-50 border-l shadow-sm">
                    <button class="text-blue-600 font-bold text-xs hover:underline mr-2" data-action="edit">编辑</button>
                    <button class="text-red-400 hover:text-red-600 text-xs" data-action="delete">删</button>
                </td>
            </tr>`;
        }
    }).join('');
}

// === 表格事件处理 (Event Delegation) ===

function handleTableClick(e) {
    const target = e.target;
    const tr = target.closest('tr');
    if (!tr) return;
    const id = tr.dataset.id;

    // 1. 编辑按钮
    if (target.closest('[data-action="edit"]')) {
        editingId = id; // id is string from dataset
        // 注意：这里 id 可能是字符串 "new"，或者数字字符串 "123"
        // 后端返回的 id 是 int，dataset 存的是 string
        // 为了兼容性，在比较时要注意类型，或者直接用 ==
        // 这里为了简单，我们重新 render，让 map 里的 v.id == editingId 匹配
        // 如果 globalData 里的 id 是 int，editingId 也要转 int (除非是 'new')
        if(id !== 'new') editingId = parseInt(id);
        else editingId = 'new';
        
        renderTable(globalData);
        return;
    }

    // 2. 取消按钮
    if (target.closest('[data-action="cancel"]')) {
        editingId = null;
        // 如果是新增行取消，重新加载数据以移除空行
        if (id === 'new') loadData();
        else renderTable(globalData);
        return;
    }

    // 3. 保存按钮
    if (target.closest('[data-action="save"]')) {
        saveRow(tr, id);
        return;
    }

    // 4. 删除按钮
    if (target.closest('[data-action="delete"]')) {
        delVideo(id);
        return;
    }

    // 5. 图片预览
    const previewDiv = target.closest('[data-action="preview-img"]');
    if (previewDiv) {
        const src = previewDiv.dataset.src;
        document.getElementById('big-img').src = src;
        document.getElementById('preview-modal').classList.add('active');
        return;
    }

    // 6. 触发上传 (编辑模式下)
    if (target.closest('[data-action="trigger-upload"]')) {
        const fileInput = tr.querySelector('.file-upload-input');
        if (fileInput) {
            fileInput.click();
            // 绑定一次性 change 事件
            fileInput.onchange = (evt) => uploadFile(evt.target.files[0], id);
        }
        return;
    }

    // 7. 多选下拉 (编辑模式下)
    if (target.classList.contains('multi-trigger')) {
        const type = target.dataset.type; // 'hosts' or 'platforms'
        openMulti(target, type);
    }
}

async function handleTableDrop(e) {
    e.preventDefault();
    const tr = e.target.closest('tr');
    if (!tr) return;
    const id = tr.dataset.id;
    
    // 只有在编辑模式下才允许拖拽? 或者浏览模式下拖拽直接上传并保存?
    // V24 逻辑是：如果 editingId == id，只更新 input；否则直接上传并 save
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
        await uploadFile(e.dataTransfer.files[0], id);
    }
}

async function handleTablePaste(e) {
    const tr = e.target.closest('tr');
    if (!tr) return;
    const id = tr.dataset.id;
    
    if (e.clipboardData.files && e.clipboardData.files[0]) {
        e.preventDefault();
        await uploadFile(e.clipboardData.files[0], id);
    }
}

// === 业务逻辑实现 ===

function addNewRow() {
    // 插入空行
    globalData.unshift({id: 'new', product_id: '', title: '', isNew: true});
    editingId = 'new';
    renderTable(globalData);
    document.querySelector('.table-wrap').scrollTop = 0;
}

async function saveRow(tr, id) {
    const fd = new FormData();
    if (id !== 'new') fd.append('id', id);
    
    // 收集字段
    tr.querySelectorAll('[data-field]').forEach(input => {
        const key = input.dataset.field;
        let val = input.value;
        if(key.includes('time')) val = val.replace('T', ' ');
        fd.append(key, val);
    });
    
    try {
        const res = await fetch('/api/video/save', {method: 'POST', body: fd});
        if(res.ok) {
            window.showToast('保存成功', 'success');
            editingId = null;
            loadData(); // 刷新数据
        } else {
            window.showToast('保存失败', 'error');
        }
    } catch(e) { console.error(e); }
}

async function delVideo(id) {
    if(!confirm('确定删除此条记录吗？')) return;
    await fetch(`/api/video/${id}`, {method: 'DELETE'});
    window.showToast('已删除', 'success');
    loadData();
}

async function uploadFile(file, id) {
    const fd = new FormData();
    fd.append('file', file);
    try {
        window.showToast('正在上传图片...', 'info');
        const res = await fetch('/api/upload', {method: 'POST', body: fd});
        const d = await res.json();
        
        if (editingId == id || editingId === 'new') {
            // 编辑中，更新隐藏域和预览图
            const tr = document.querySelector(`tr[data-id="${id}"]`);
            if(tr) {
                tr.querySelector('[data-field="image_url"]').value = d.url;
                tr.querySelector('img').src = d.url;
            }
        } else {
            // 非编辑中，直接更新数据库
            const fd2 = new FormData();
            fd2.append('id', id);
            fd2.append('image_url', d.url);
            await fetch('/api/video/save', {method:'POST', body:fd2});
            
            // 更新本地数据
            const row = globalData.find(v => v.id == id);
            if(row) row.image_url = d.url;
            renderTable(globalData);
        }
        window.showToast('图片上传成功', 'success');
    } catch(e) {
        window.showToast('上传失败', 'error');
    }
}

// === 辅助功能 ===

function openMulti(input, typeKey) {
    const pop = document.getElementById('multi-pop');
    const rect = input.getBoundingClientRect();
    const list = globalOptions[typeKey] || [];
    const currentVals = input.value.split(/[,，]/).map(s => s.trim());
    
    pop.innerHTML = list.map(opt => {
        const isSel = currentVals.includes(opt);
        return `
        <div class="multi-opt ${isSel ? 'text-blue-600 font-bold bg-blue-50' : ''}" 
             onclick="toggleMultiVal('${input.closest('tr').dataset.id}', '${input.dataset.field}', '${opt}')">
            <span>${isSel ? '✓' : ''}</span> ${opt}
        </div>`;
    }).join('');
    
    pop.style.top = (rect.bottom + window.scrollY) + 'px';
    pop.style.left = (rect.left + window.scrollX) + 'px';
    pop.classList.add('show');
    
    // 阻止冒泡防止立即关闭
    // (在 init 里已经绑定了全局关闭)
}

// 必须要挂载到 window 吗？不，我们用闭包里的函数，但 HTML onclick 无法访问模块内函数
// 所以这里是一个 tricky 的地方。
// 更好的方式是：在 openMulti 的 innerHTML onclick 里不调用函数，而是用 data-val
// 但为了简单，我们还是把 toggleMultiVal 挂到 window 上，或者改写 openMulti 的逻辑
// 修正：我们把 toggleMultiVal 定义为全局函数，或者在 pop 内部用事件委托
// 这里采用：将 toggleMultiVal 挂载到 window，这是兼容性最好的快速方案
window.toggleMultiVal = function(trId, fieldKey, optVal) {
    const tr = document.querySelector(`tr[data-id="${trId}"]`);
    const input = tr.querySelector(`input[data-field="${fieldKey}"]`);
    let vals = input.value.split(/[,，]/).map(s => s.trim()).filter(s => s);
    
    if (vals.includes(optVal)) {
        vals = vals.filter(v => v !== optVal);
    } else {
        vals.push(optVal);
    }
    input.value = vals.join(', ');
    
    // 刷新弹窗状态 (重新调用 openMulti 即可)
    // 但我们需要 input 引用，所以这里简单点，直接关闭或者不刷新
    // 为了体验好，手动刷新 pop 内容
    // 重新获取 pop 内容有点麻烦，简单起见，关闭它
    // document.getElementById('multi-pop').classList.remove('show');
    // 或者重新 open
    // 这里为了不中断操作，不关闭
};

// === 弹窗与设置逻辑 ===

function openSettings() {
    document.getElementById('settings-modal').classList.add('active');
    document.getElementById('set-hosts').value = globalOptions.hosts.join(',');
    document.getElementById('set-cats').value = globalOptions.categories.join(',');
    document.getElementById('set-types').value = globalOptions.video_types.join(',');
    document.getElementById('set-plats').value = globalOptions.platforms.join(',');
}

async function saveSettings() {
    const fd = new FormData();
    fd.append('hosts', document.getElementById('set-hosts').value);
    fd.append('categories', document.getElementById('set-cats').value);
    fd.append('video_types', document.getElementById('set-types').value);
    fd.append('platforms', document.getElementById('set-plats').value);
    
    // 发送每个 key
    for(let [k, v] of fd.entries()) {
        await fetch('/api/settings', {method:'POST', body: new URLSearchParams({key:k, value:v})});
    }
    
    window.showToast('配置已保存', 'success');
    document.getElementById('settings-modal').classList.remove('active');
    loadOptions();
}

function openImport() { document.getElementById('import-modal').classList.add('active'); }
async function startImport() {
    const res = await fetch('/api/import/local', {method:'POST'});
    if(res.ok) {
        window.showToast('后台任务已启动，请稍后刷新', 'success');
        document.getElementById('import-modal').classList.remove('active');
    }
}

function resetFilters() {
    document.querySelectorAll('#filter-panel input, #filter-panel select').forEach(el => el.value = '');
    loadData(1);
}

function changePage(d) {
    if (currPage + d > 0 && currPage + d <= totalPages) loadData(currPage + d);
}