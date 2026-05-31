/* ==========================================================================
   ukSponsorJobs - Premium Client Controller (State & API Core Engine)
   ========================================================================== */

// 1. Core State Definition
let state = {
    searchQuery: '',
    selectedDept: '',
    selectedLocation: '',
    currentPage: 1,
    totalPages: 1,
    abortController: null,
    debouncer: null
};

// Host Resolver (Auto routes to Render backend if running on production domain)
const getApiBase = () => {
    const host = window.location.hostname;
    if (host === 'localhost' || host === '127.0.0.1') {
        return 'http://localhost:8000';
    }
    if (host.includes('github.io')) {
        return 'https://uk-sponsor-radar-backend.onrender.com';
    }
    return '';
};

const API_BASE = getApiBase();

// 2. Application Entrypoint
window.addEventListener('DOMContentLoaded', () => {
    fetchFilterDropdowns();
    runSearch();
    updateLiveMetrics();
});

// 3. Dynamic Dropdown and Stats Aggregator
async function fetchFilterDropdowns() {
    try {
        const response = await fetch(`${API_BASE}/api/jobs/filters`);
        if (!response.ok) return;
        const data = await response.json();
        
        const deptSelect = document.getElementById('filter-dept');
        const citySelect = document.getElementById('filter-city');
        
        deptSelect.innerHTML = '<option value="">All Departments</option>';
        citySelect.innerHTML = '<option value="">Any Location (UK)</option>';
        
        data.departments.forEach(dept => {
            const opt = document.createElement('option');
            opt.value = dept;
            opt.textContent = dept;
            deptSelect.appendChild(opt);
        });
        
        data.locations.forEach(loc => {
            const opt = document.createElement('option');
            opt.value = loc;
            opt.textContent = loc;
            citySelect.appendChild(opt);
        });
    } catch (e) {
        console.error("Failed to load filter select elements", e);
    }
}

async function updateLiveMetrics() {
    try {
        const response = await fetch(`${API_BASE}/api/jobs?limit=1`);
        if (!response.ok) return;
        const data = await response.json();
        
        const jobCounter = document.getElementById('stat-live-jobs');
        if (jobCounter && data.meta) {
            jobCounter.textContent = data.meta.total.toLocaleString();
        }
    } catch (e) {
        console.error("Failed to pull live stats", e);
    }
}

// 4. Typing Debouncer & Controller
function handleSearchInput() {
    state.searchQuery = document.getElementById('search-input').value.trim();
    state.currentPage = 1;
    
    clearTimeout(state.debouncer);
    state.debouncer = setTimeout(() => {
        runSearch();
    }, 250);
}

// 5. Search Pipeline Executions
async function runSearch() {
    if (state.abortController) {
        state.abortController.abort();
    }
    state.abortController = new AbortController();
    const signal = state.abortController.signal;
    
    toggleLoadingState(true);
    
    state.selectedDept = document.getElementById('filter-dept').value;
    state.selectedLocation = document.getElementById('filter-city').value;
    
    try {
        const params = new URLSearchParams({
            q: state.searchQuery,
            dept: state.selectedDept,
            city: state.selectedLocation,
            page: state.currentPage,
            limit: 15
        });
        const endpoint = `${API_BASE}/api/jobs?${params.toString()}`;
        
        const response = await fetch(endpoint, { signal });
        if (!response.ok) throw new Error("API call failed");
        
        const data = await response.json();
        
        state.totalPages = data.meta.pages;
        renderResults(data);
        renderPagination();
    } catch (e) {
        if (e.name !== 'AbortError') {
            console.error("Search fetch failed", e);
            showErrorUI();
        }
    } finally {
        toggleLoadingState(false);
    }
}

// 6. Dynamic Grid and Table Rendering
function renderResults(data) {
    const counterText = document.getElementById('results-count');
    const grid = document.getElementById('jobs-grid-container');
    grid.innerHTML = '';
    
    counterText.textContent = `${data.meta.total.toLocaleString()} live visa-sponsorship roles found`;
    
    if (data.jobs.length === 0) {
        grid.innerHTML = `
            <div class="loading-indicator">
                <p class="loading-pulse-text">No live sponsorship vacancies found matching your criteria.</p>
                <p style="font-size: 13px; color: var(--text-muted);">Try clearing your filters or search terms.</p>
            </div>
        `;
        return;
    }
    
    data.jobs.forEach(job => {
        const card = document.createElement('div');
        card.className = 'job-card';
        card.onclick = () => openJobDrawer(job);
        
        const daysAgo = getDaysAgo(job.posted_date);
        const dateStr = daysAgo === 0 ? 'Today' : daysAgo === 1 ? '1 day ago' : `${daysAgo} days ago`;
        
        card.innerHTML = `
            <div class="job-card-header">
                <div>
                    <div class="job-company">${escapeHTML(job.company_name)}</div>
                    <h3 class="job-title">${escapeHTML(job.job_title)}</h3>
                </div>
            </div>
            <div class="job-badges">
                <span class="badge badge-dept">${escapeHTML(job.department)}</span>
                <span class="badge badge-loc">${escapeHTML(job.location)}</span>
                <span class="badge badge-source">${escapeHTML(job.source)}</span>
            </div>
            <div class="job-card-footer">
                <span class="job-date">${dateStr}</span>
                <span class="arrow-link">
                    <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2.5" fill="none" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>
                </span>
            </div>
        `;
        grid.appendChild(card);
    });
}

// 7. Pagination Widget Renderer
function renderPagination() {
    const wrapper = document.getElementById('pagination-controls');
    wrapper.innerHTML = '';
    
    if (state.totalPages <= 1) return;
    
    const prevBtn = document.createElement('button');
    prevBtn.className = 'pg-btn';
    prevBtn.disabled = state.currentPage === 1;
    prevBtn.onclick = () => changePage(state.currentPage - 1);
    prevBtn.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2.5" fill="none" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"></polyline></svg>';
    wrapper.appendChild(prevBtn);
    
    let startPage = Math.max(1, state.currentPage - 2);
    let endPage = Math.min(state.totalPages, startPage + 4);
    if (endPage - startPage < 4) {
        startPage = Math.max(1, endPage - 4);
    }
    
    for (let i = startPage; i <= endPage; i++) {
        const numBtn = document.createElement('button');
        numBtn.className = `pg-btn ${state.currentPage === i ? 'active' : ''}`;
        numBtn.textContent = i;
        numBtn.onclick = () => changePage(i);
        wrapper.appendChild(numBtn);
    }
    
    const nextBtn = document.createElement('button');
    nextBtn.className = 'pg-btn';
    nextBtn.disabled = state.currentPage === state.totalPages;
    nextBtn.onclick = () => changePage(state.currentPage + 1);
    nextBtn.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2.5" fill="none" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>';
    wrapper.appendChild(nextBtn);
}

function changePage(pageNumber) {
    state.currentPage = pageNumber;
    runSearch();
    window.scrollTo({ top: 300, behavior: 'smooth' });
}

// 8. Side-Drawer Control Logic
function openJobDrawer(job) {
    const box = document.getElementById('drawer-content-box');
    box.innerHTML = '';
    
    const applyUrl = job.job_url;
    
    box.innerHTML = `
        <div class="drawer-header">
            <span class="drawer-company">${escapeHTML(job.company_name)}</span>
            <h2 class="drawer-title">${escapeHTML(job.job_title)}</h2>
        </div>
        
        <div class="drawer-meta-grid">
            <div class="drawer-meta-item">
                <div class="meta-item-label">Job Category</div>
                <div class="meta-item-value">${escapeHTML(job.department)}</div>
            </div>
            <div class="drawer-meta-item">
                <div class="meta-item-label">Location</div>
                <div class="meta-item-value">${escapeHTML(job.location)}</div>
            </div>
            <div class="drawer-meta-item">
                <div class="meta-item-label">Source Sync</div>
                <div class="meta-item-value">${escapeHTML(job.source)}</div>
            </div>
            <div class="drawer-meta-item">
                <div class="meta-item-label">Visa route</div>
                <div class="meta-item-value">Skilled Worker</div>
            </div>
        </div>
        
        <div class="drawer-desc-block">
            <div class="drawer-desc-title">Visa Sponsorship Guarantee</div>
            <p class="drawer-desc-content">
                <strong>${escapeHTML(job.company_name)}</strong> is registered in the official UK Home Office worker sponsor records. 
                This vacancy is loaded directly from their Applicant Tracking System, ensuring the role is fresh, live, and actively recruiting.
            </p>
        </div>
        
        <div class="action-btn-container">
            <button class="btn-primary-glow" onclick="window.open('${applyUrl}', '_blank')">
                Apply on Company Site
                <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2.5" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
            </button>
            <button class="btn-secondary-border" onclick="generateSmartFallbackLinks('${escapeHTML(job.company_name)}')">
                Research Company on Google
            </button>
        </div>
    `;
    
    toggleDrawer(true);
}

function generateSmartFallbackLinks(companyName) {
    const googleCareersUrl = `https://www.google.com/search?q=${encodeURIComponent(companyName)}+careers+jobs+UK`;
    window.open(googleCareersUrl, '_blank');
}

// 9. UI Helpers and Formatting utils
function toggleDrawer(isOpen) {
    const drawer = document.getElementById('details-drawer');
    const overlay = document.getElementById('drawer-overlay');
    
    drawer.classList.toggle('active', isOpen);
    overlay.classList.toggle('active', isOpen);
}

function closeDrawer() {
    toggleDrawer(false);
}

function toggleLoadingState(isLoading) {
    const grid = document.getElementById('jobs-grid-container');
    
    if (isLoading) {
        grid.innerHTML = `
            <div class="loading-indicator">
                <div class="loading-spinner"></div>
                <div class="loading-pulse-text">Loading live jobs feed...</div>
            </div>
        `;
    }
}

function showErrorUI() {
    const grid = document.getElementById('jobs-grid-container');
    grid.innerHTML = `
        <div class="loading-indicator">
            <p style="color: #ef4444; font-weight: 600;">Failed to establish connection to sponsorship database.</p>
            <p style="font-size: 13px; color: var(--text-muted);">Please verify the backend server.py is running on port 8000.</p>
        </div>
    `;
}

function getDaysAgo(dateString) {
    if (!dateString) return 0;
    const diffTime = Math.abs(new Date() - new Date(dateString));
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24)) - 1;
    return isNaN(diffDays) ? 0 : diffDays;
}

function escapeHTML(str) {
    if (!str) return '';
    return str.replace(/[&<>'"]/g, 
        tag => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[tag] || tag)
    );
}
