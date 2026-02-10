/**
 * VideoHub V30.0 - Product SPU Module (Pure Text Version)
 * 负责展示产品维度的库存统计卡片 - 无图片，纯数据，高性能
 */

export async function renderProduct(container) {
    // 1. 注入 HTML 骨架
    container.innerHTML = `
        <div class="dash-container h-full flex flex-col">
            <div class="flex justify-between items-center mb-6 shrink-0 sticky top-0 bg-[#f8fafc] z-10 py-2">
                <h2 class="text-xl font-bold text-slate-800 flex items-center gap-2">
                    <span class="text-2xl">🏷️</span> 产品库存监控 (SPU)
                </h2>
                <div class="relative">
                    <input id="prod-search" class="t-input w-64 pl-8 rounded-full border-slate-300 focus:border-blue-500 shadow-sm" placeholder="搜索产品型号...">
                    <svg class="w-4 h-4 absolute left-2.5 top-2.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
                </div>
            </div>

            <div id="product-loading" class="flex-1 flex justify-center items-center text-slate-400">
                <div class="flex flex-col items-center gap-2">
                    <svg class="animate-spin h-8 w-8 text-blue-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                    <span class="text-xs">正在统计库存...</span>
                </div>
            </div>

            <div id="product-grid" class="card-grid hidden">
                </div>
            
            <div id="product-empty" class="hidden flex-1 flex flex-col justify-center items-center text-slate-400">
                <div class="text-4xl mb-2">📦</div>
                <p>暂无产品数据，请先在“视频库存”中添加数据</p>
            </div>
        </div>
    `;

    // 绑定搜索事件
    document.getElementById('prod-search').addEventListener('input', (e) => {
        Product.search(e.target.value);
    });

    // 2. 加载数据
    try {
        const res = await fetch('/api/product_stats');
        if (!res.ok) throw new Error("API Error");
        const data = await res.json();
        
        // 渲染卡片
        Product.allData = data; // 缓存数据供搜索使用
        Product.render(data);
        
    } catch (e) {
        console.error("Product Load Error:", e);
        container.innerHTML += `<div class="fixed bottom-4 right-4 bg-red-100 text-red-600 px-4 py-2 rounded shadow">加载失败: ${e.message}</div>`;
    }
}

// === 产品逻辑封装 ===
const Product = {
    allData: [],
    
    search: function(keyword) {
        if(!keyword) { 
            this.render(this.allData); 
            return; 
        }
        const lowerKey = keyword.toLowerCase();
        const filtered = this.allData.filter(item => 
            item.name && String(item.name).toLowerCase().includes(lowerKey)
        );
        this.render(filtered);
    },

    render: function(data) {
        const grid = document.getElementById('product-grid');
        const loader = document.getElementById('product-loading');
        const empty = document.getElementById('product-empty');

        if(loader) loader.classList.add('hidden');

        if (!data || data.length === 0) {
            if(empty) empty.classList.remove('hidden');
            if(grid) grid.innerHTML = '';
            return;
        }

        if(empty) empty.classList.add('hidden');
        if(grid) grid.classList.remove('hidden');
        
        grid.innerHTML = data.map(item => {
            const pct = item.total > 0 ? Math.round(((item.total - item.pending) / item.total) * 100) : 0;
            
            // 状态逻辑
            let statusClass = 'normal'; 
            let color = '#3b82f6';
            let statusText = '进行中';
            
            if (item.pending > 5) { 
                statusClass = 'danger'; color = '#ef4444'; statusText = '积压';
            } else if (item.pending === 0 && item.total > 0) { 
                statusClass = 'safe'; color = '#10b981'; statusText = '完成';
            } else if (item.total < 3) { 
                statusClass = 'warn'; statusText = '缺货';
            }

            // 纯文字卡片模板
            return `
            <div class="prod-card ${statusClass} group" onclick="jumpToInventory('${item.name}')">
                <div class="pc-header">
                    <div class="pc-title" title="${item.name}">${item.name}</div>
                    <div class="pc-badge transition-colors group-hover:bg-blue-50 group-hover:text-blue-600">SPU</div>
                </div>
                
                <div class="pc-body">
                    <div class="pc-stat">
                        <div class="pc-num" style="color: ${color}">${item.pending}</div>
                        <div class="pc-label">待发布</div>
                    </div>
                    <div class="text-right">
                        <div class="text-2xl font-bold text-slate-300 group-hover:text-slate-400 transition-colors">${pct}%</div>
                        <div class="text-xs text-slate-400 font-medium">${statusText}</div>
                    </div>
                </div>
                
                <div class="pc-footer">
                    <div class="pc-progress-bg">
                        <div class="pc-progress-fill" style="width: ${pct}%; background-color: ${color}"></div>
                    </div>
                    <div class="pc-total">总库 ${item.total}</div>
                </div>
                
                <div class="absolute top-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity">
                    <svg class="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path></svg>
                </div>
            </div>`;
        }).join('');
    }
};

// 挂载跳转函数供 HTML 调用
window.jumpToInventory = function(pid) {
    if(window.router) {
        window.router.switch('inventory', { pid: pid });
    }
};