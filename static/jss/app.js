import { renderDashboard } from './dashboard.js';
import { renderInventory } from './inventory.js';
import { renderProduct } from './product.js';

// 全局命名空间
window.router = {
    currentView: 'dashboard',
    
    // 初始化
    init: function() {
        console.log("App Initializing...");
        this.switch('dashboard');
        
        // 全局事件：点击空白关闭弹窗
        document.addEventListener('click', e => {
            if(!e.target.closest('.multi-pop') && !e.target.closest('.multi-trig')) 
                document.querySelectorAll('.multi-pop').forEach(el => el.classList.remove('show'));
        });
    },

    // 视图切换核心
    switch: async function(viewName, params = {}) {
        this.currentView = viewName;
        
        // 1. 更新侧边栏激活状态
        document.querySelectorAll('.nav-item').forEach(el => {
            el.classList.toggle('active', el.dataset.view === viewName);
        });

        // 2. 显示 Loading
        const container = document.getElementById('app-main');
        container.innerHTML = `
            <div class="flex h-full items-center justify-center text-slate-400">
                <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
            </div>`;

        // 3. 动态加载模块
        try {
            if (viewName === 'dashboard') {
                await renderDashboard(container);
            } else if (viewName === 'inventory') {
                await renderInventory(container, params);
            } else if (viewName === 'product') {
                await renderProduct(container);
            }
        } catch (error) {
            console.error("View Load Error:", error);
            container.innerHTML = `<div class="p-8 text-red-500">页面加载失败: ${error.message}</div>`;
        }
    }
};

// 工具：Toast 提示
window.showToast = function(msg, type='info') {
    const box = document.getElementById('toast-container');
    const el = document.createElement('div');
    el.className = 'toast';
    el.style.borderLeftColor = type === 'success' ? '#10b981' : '#3b82f6';
    el.innerHTML = `<span>${type==='success'?'✅':'ℹ️'}</span> ${msg}`;
    box.appendChild(el);
    setTimeout(() => el.remove(), 3000);
};

// 启动应用
window.router.init();