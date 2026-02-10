/**
 * VideoHub V25.0 - Product SPU Module
 * 负责展示产品维度的库存统计卡片
 */

export async function renderProduct(container) {
    // 1. 注入 HTML 骨架
    container.innerHTML = `
        <div class="dash-container h-full flex flex-col">
            <div class="flex justify-between items-center mb-6 shrink-0">
                <h2 class="text-xl font-bold text-slate-800 flex items-center gap-2">
                    <span class="text-2xl">🏷️</span> 产品库存监控 (SPU)
                </h2>
                <div class="text-sm text-slate-500 bg-white px-3 py-1 rounded-full border border-slate-200 shadow-sm">
                    共监控 <span id="spu-count" class="font-bold text-blue-600 text-base">0</span> 个产品
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

    // 2. 加载数据
    try {
        const res = await fetch('/api/product_stats');
        if (!res.ok) throw new Error("API Error");
        const data = await res.json();
        
        // 更新计数
        document.getElementById('spu-count').innerText = data.length;
        
        // 渲染卡片
        renderCards(data);
        
    } catch (e) {
        console.error("Product Load Error:", e);
        container.innerHTML += `<div class="fixed bottom-4 right-4 bg-red-100 text-red-600 px-4 py-2 rounded shadow">加载失败: ${e.message}</div>`;
    }
}

// === 渲染核心逻辑 ===
function renderCards(data) {
    const grid = document.getElementById('product-grid');
    const loader = document.getElementById('product-loading');
    const empty = document.getElementById('product-empty');

    loader.classList.add('hidden');

    if (data.length === 0) {
        empty.classList.remove('hidden');
        return;
    }

    grid.classList.remove('hidden');
    
    grid.innerHTML = data.map(item => {
        // 计算完成率
        const pct = item.total > 0 ? Math.round(((item.total - item.pending) / item.total) * 100) : 0;
        
        // 智能状态着色逻辑
        let statusClass = 'normal'; // 默认蓝
        let statusColor = '#3b82f6';
        let statusText = '进行中';
        
        if (item.pending > 5) { 
            // 积压严重
            statusClass = 'danger'; 
            statusColor = '#ef4444'; 
            statusText = '积压';
        } else if (item.pending === 0 && item.total > 0) { 
            // 已全部发布
            statusClass = 'safe'; 
            statusColor = '#10b981';
            statusText = '完成';
        } else if (item.total < 3) { 
            // 总库存过低
            statusClass = 'warn'; 
            statusText = '缺货';
        }

        return `
        <div class="prod-card ${statusClass} group" onclick="jumpToInventory('${item.name}')">
            <div class="pc-header">
                <div class="pc-title" title="${item.name}">${item.name}</div>
                <div class="pc-badge transition-colors group-hover:bg-blue-50 group-hover:text-blue-600">SPU</div>
            </div>
            
            <div class="pc-body">
                <div class="pc-stat">
                    <div class="pc-num" style="color: ${statusColor}">${item.pending}</div>
                    <div class="pc-label">待发布库存</div>
                </div>
                <div class="text-right">
                    <div class="text-2xl font-bold text-slate-300 group-hover:text-slate-400 transition-colors">${pct}%</div>
                    <div class="text-xs text-slate-400 font-medium">${statusText}</div>
                </div>
            </div>
            
            <div class="pc-footer">
                <div class="pc-progress-bg">
                    <div class="pc-progress-fill" style="width: ${pct}%; background-color: ${statusColor}"></div>
                </div>
                <div class="pc-total">总库 ${item.total}</div>
            </div>
            
            <div class="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
                <svg class="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path></svg>
            </div>
        </div>`;
    }).join('');
}

// === 跳转联动函数 ===
// 将此函数挂载到 window，以便 HTML 字符串中的 onclick 可以调用
window.jumpToInventory = function(pid) {
    // 调用路由切换，并传递参数 pid
    window.router.switch('inventory', { pid: pid });
};