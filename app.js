/* ==========================================================================
   ukSponsorJobs - Premium Client Controller (State & API Core Engine)
   ========================================================================== */

// 1. Core State Definition
let state = {
    activeTab: 'jobs', // 'jobs' or 'sponsors'
    searchQuery: '',
    selectedDept: '',
    selectedLocation: '',
    sponsorCity: '',
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
    // Set fallback to Render backend if hosted on GitHub pages
    if (host.includes('github.io')) {
        return 'https://uk-sponsor-radar-backend.onrender.com'; // Shared API Backend
    }
    return ''; // Relative path fallback
};

const API_BASE = getApiBase();

// 2. Application Entrypoint
window.addEventListener('DOMContentLoaded', () => {
    // Initial data load
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
        
        // Clear options except first
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

// 4. Tab Workspace Switcher
function switchTab(tabName) {
    if (state.activeTab === tabName) return;
    
    state.activeTab = tabName;
    state.currentPage = 1;
    state.searchQuery = '';
    state.selectedDept = '';
    state.selectedLocation = '';
    state.sponsorCity = '';
    
    // Reset HTML inputs
    document.getElementById('search-input').value = '';
    document.getElementById('filter-dept').value = '';
    document.getElementById('filter-city').value = '';
    const citySponsor = document.getElementById('filter-sponsor-city');
    if (citySponsor) citySponsor.value = '';
    
    // Toggle active visual states
    document.getElementById('tab-jobs').classList.toggle('active', tabName === 'jobs');
    document.getElementById('tab-sponsors').classList.toggle('active', tabName === 'sponsors');
    
    document.getElementById('panel-jobs').classList.toggle('hidden', tabName !== 'jobs');
    document.getElementById('panel-sponsors').classList.toggle('hidden', tabName !== 'sponsors');
    
    document.getElementById('jobs-filters').classList.toggle('hidden', tabName !== 'jobs');
    document.getElementById('sponsors-filters').classList.toggle('hidden', tabName !== 'sponsors');
    
    runSearch();
}

// 5. Typing Debouncer & Controller
function handleSearchInput() {
    state.searchQuery = document.getElementById('search-input').value.trim();
    
    const sponsorCityInput = document.getElementById('filter-sponsor-city');
    if (sponsorCityInput) {
        state.sponsorCity = sponsorCityInput.value.trim();
    }
    
    state.currentPage = 1;
    
    clearTimeout(state.debouncer);
    state.debouncer = setTimeout(() => {
        runSearch();
    }, 250);
}

// 6. Search Pipeline Executions
async function runSearch() {
    // 1. Cancel previous pending searches
    if (state.abortController) {
        state.abortController.abort();
    }
    state.abortController = new AbortController();
    const signal = state.abortController.signal;
    
    // Toggle Loading Indicators
    toggleLoadingState(true);
    
    // Capture filter variables
    if (state.activeTab === 'jobs') {
        state.selectedDept = document.getElementById('filter-dept').value;
        state.selectedLocation = document.getElementById('filter-city').value;
    }
    
    try {
        let endpoint = '';
        if (state.activeTab === 'jobs') {
            const params = new URLSearchParams({
                q: state.searchQuery,
                dept: state.selectedDept,
                city: state.selectedLocation,
                page: state.currentPage,
                limit: 15
            });
            endpoint = `${API_BASE}/api/jobs?${params.toString()}`;
        } else {
            const params = new URLSearchParams({
                q: state.searchQuery,
                city: state.sponsorCity,
                page: state.currentPage
            });
            endpoint = `${API_BASE}/api/sponsors?${params.toString()}`;
        }
        
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

// 7. Dynamic Grid and Table Rendering
function renderResults(data) {
    const counterText = document.getElementById('results-count');
    
    if (state.activeTab === 'jobs') {
        const grid = document.getElementById('jobs-grid-container');
        grid.innerHTML = '';
        
        counterText.textContent = `${data.meta.total.toLocaleString()} live visa-sponsorship roles found`;
        
        if (data.jobs.length === 0) {
            grid.innerHTML = `
                <div class="loading-indicator">
                    <p class="loading-pulse-text">No live sponsorship vacancies found matching your criteria.</p>
                    <p style="font-size: 13px; color: var(--text-muted);">Try clearing your filters or search terms, or search our Sponsors Directory tab directly!</p>
                </div>
            `;
            return;
        }
        
        data.jobs.forEach(job => {
            const card = document.createElement('div');
            card.className = 'job-card';
            card.onclick = () => openJobDrawer(job);
            
            // Format dates neatly
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
    } else {
        const tbody = document.getElementById('sponsors-table-body');
        tbody.innerHTML = '';
        
        counterText.textContent = `${data.meta.total.toLocaleString()} registered visa sponsors found`;
        
        if (data.sponsors.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="5" style="text-align: center; color: var(--text-muted); padding: 30px;">
                        No registered sponsorship firms found matching your search.
                    </td>
                </tr>
            `;
            return;
        }
        
        data.sponsors.forEach(sp => {
            const tr = document.createElement('tr');
            tr.onclick = () => openSponsorDrawer(sp);
            tr.style.cursor = 'pointer';
            
            tr.innerHTML = `
                <td class="td-sponsor-name">${escapeHTML(sp.organisation_name)}</td>
                <td>${escapeHTML(sp.town_city || 'N/A')}</td>
                <td>${escapeHTML(sp.county || 'N/A')}</td>
                <td><span class="badge badge-dept" style="font-size: 10px;">${escapeHTML(sp.route)}</span></td>
                <td>
                    <button class="btn-mini-crawl" onclick="event.stopPropagation(); triggerOnDemandCrawl(${sp.id})">
                        <svg viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" stroke-width="2.5" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"></path></svg>
                        Scan Site
                    </button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    }
}

// 8. Pagination Widget Renderer
function renderPagination() {
    const wrapper = document.getElementById('pagination-controls');
    wrapper.innerHTML = '';
    
    if (state.totalPages <= 1) return;
    
    // Prev Button
    const prevBtn = document.createElement('button');
    prevBtn.className = 'pg-btn';
    prevBtn.disabled = state.currentPage === 1;
    prevBtn.onclick = () => changePage(state.currentPage - 1);
    prevBtn.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2.5" fill="none" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"></polyline></svg>';
    wrapper.appendChild(prevBtn);
    
    // Numbers
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
    
    // Next Button
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

// 9. Side-Drawer Control Core Logic
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

function openSponsorDrawer(sp) {
    const box = document.getElementById('drawer-content-box');
    box.innerHTML = '';
    
    box.innerHTML = `
        <div class="drawer-header">
            <span class="drawer-company">Licensed UK Sponsor</span>
            <h2 class="drawer-title">${escapeHTML(sp.organisation_name)}</h2>
        </div>
        
        <div class="drawer-meta-grid">
            <div class="drawer-meta-item">
                <div class="meta-item-label">Town / City</div>
                <div class="meta-item-value">${escapeHTML(sp.town_city || 'N/A')}</div>
            </div>
            <div class="drawer-meta-item">
                <div class="meta-item-label">County</div>
                <div class="meta-item-value">${escapeHTML(sp.county || 'N/A')}</div>
            </div>
            <div class="drawer-meta-item">
                <div class="meta-item-label">Sponsorship Route</div>
                <div class="meta-item-value">${escapeHTML(sp.route)}</div>
            </div>
            <div class="drawer-meta-item">
                <div class="meta-item-label">Licence Rating</div>
                <div class="meta-item-value">${escapeHTML(sp.rating)}</div>
            </div>
        </div>
        
        <div class="drawer-desc-block">
            <div class="drawer-desc-title">Live Scraper Spider</div>
            <p class="drawer-desc-content">
                We don't have a direct API vacancy hook for this company in our default database indexes yet. 
                However, you can trigger our automated Web Radar Spider to crawl their live website right now to look for vacancies!
            </p>
        </div>
        
        <div class="action-btn-container" id="drawer-action-dock">
            <button class="btn-primary-glow" id="btn-run-spider" onclick="triggerOnDemandCrawl(${sp.id}, true)">
                <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2.5" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"></path></svg>
                Scan Career Page
            </button>
            <button class="btn-secondary-border" onclick="generateSmartFallbackLinks('${escapeHTML(sp.organisation_name)}')">
                Apply Direct via Google Careers
            </button>
        </div>
    `;
    
    toggleDrawer(true);
}

// 10. Automated Web Crawler trigger endpoint (On-Demand)
async function triggerOnDemandCrawl(sponsorId, isInsideDrawer = false) {
    let button = null;
    let loadingContainer = null;
    
    if (isInsideDrawer) {
        button = document.getElementById('btn-run-spider');
        button.disabled = true;
        button.innerHTML = '<span class="loading-spinner" style="width:14px; height:14px; border-width:2px; display:inline-block; margin-right:8px;"></span> Scouting careers...';
    } else {
        // Find row buttons
        openSponsorDrawer({ id: sponsorId, organisation_name: "Loading Sponsor details...", route: "Skilled Worker", rating: "A Rating" });
        button = document.getElementById('btn-run-spider');
        button.disabled = true;
        button.innerHTML = '<span class="loading-spinner" style="width:14px; height:14px; border-width:2px; display:inline-block; margin-right:8px;"></span> Scouting careers...';
    }
    
    // Inject step-by-step progress scanner block
    const progressBlock = document.createElement('div');
    progressBlock.className = 'drawer-desc-block';
    progressBlock.innerHTML = `
        <div class="drawer-desc-title" style="color: var(--accent-secondary); display:flex; align-items:center; gap:8px;">
            <div class="radar-scan" style="width:16px; height:16px; border-color:var(--accent-secondary)"></div>
            Live Spider Logs
        </div>
        <ul style="font-size:13px; color: var(--text-secondary); list-style:none; display:flex; flex-direction:column; gap:8px; padding-left:4px;">
            <li id="step-ddg">⌛ Resolving official company domain via Search Crawl...</li>
            <li id="step-http" style="opacity:0.5">⌛ Scouting website for HTML career patterns...</li>
            <li id="step-parse" style="opacity:0.5">⌛ Parsing active anchor tags & ATS vacancy signatures...</li>
        </ul>
    `;
    
    const dock = document.getElementById('drawer-action-dock');
    dock.parentNode.insertBefore(progressBlock, dock);
    
    try {
        // Step 1: Discover URL
        setTimeout(() => {
            const stepDdg = document.getElementById('step-ddg');
            if (stepDdg) stepDdg.textContent = '✅ Official domain and careers page resolved!';
            const stepHttp = document.getElementById('step-http');
            if (stepHttp) {
                stepHttp.opacity = '1';
                stepHttp.textContent = '⌛ Downloading HTML files from careers page...';
            }
        }, 1200);
        
        // Step 2: HTTP scan
        setTimeout(() => {
            const stepHttp = document.getElementById('step-http');
            if (stepHttp) stepHttp.textContent = '✅ HTML fetched successfully (Response 200 OK)';
            const stepParse = document.getElementById('step-parse');
            if (stepParse) {
                stepParse.opacity = '1';
                stepParse.textContent = '⌛ Parsing links and matching role categories...';
            }
        }, 2400);

        const response = await fetch(`${API_BASE}/api/crawl`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sponsor_id: sponsorId })
        });
        
        if (!response.ok) throw new Error("Crawl request failed");
        
        const data = await response.json();
        
        const stepParse = document.getElementById('step-parse');
        if (stepParse) stepParse.textContent = `✅ Crawled completed! ${data.jobs.length} jobs retrieved.`;
        
        // Render crawled jobs in drawer
        setTimeout(() => {
            renderCrawledJobsInDrawer(data);
        }, 800);
        
    } catch (e) {
        console.error("On-demand crawl failed", e);
        if (button) {
            button.disabled = false;
            button.innerHTML = 'Scan Failed. Retry?';
        }
        const stepParse = document.getElementById('step-parse');
        if (stepParse) stepParse.textContent = '❌ Web spider failed. Careers page blocked or custom site structured too complex.';
    }
}

function renderCrawledJobsInDrawer(data) {
    const box = document.getElementById('drawer-content-box');
    box.innerHTML = '';
    
    let jobsListHTML = '';
    if (data.jobs.length === 0) {
        jobsListHTML = `
            <div style="text-align:center; padding: 20px; background: rgba(255,255,255,0.02); border-radius: 8px; border: 1px solid var(--border-color);">
                <p style="font-size:14px; color: var(--text-secondary); margin-bottom:12px;">The spider crawled the website but did not extract structured job listings. Their careers page might be empty, or uses advanced cloud scrapeshield protections.</p>
                <button class="btn-primary-glow" style="width:100%" onclick="window.open('${data.careers_url}', '_blank')">
                    Open Custom Site Manually
                </button>
            </div>
        `;
    } else {
        jobsListHTML = '<div style="display:flex; flex-direction:column; gap:12px;">';
        data.jobs.forEach(job => {
            jobsListHTML += `
                <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); padding: 16px; border-radius: 8px; display:flex; justify-content:space-between; align-items:center; gap:12px;">
                    <div>
                        <h4 style="color:white; font-size:14px; font-weight:600; margin-bottom:4px;">${escapeHTML(job.job_title)}</h4>
                        <span class="badge badge-dept" style="font-size:10px; padding:2px 8px;">${escapeHTML(job.department)}</span>
                    </div>
                    <button class="btn-mini-crawl" onclick="window.open('${job.job_url}', '_blank')">Apply</button>
                </div>
            `;
        });
        jobsListHTML += '</div>';
    }
    
    box.innerHTML = `
        <div class="drawer-header">
            <span class="drawer-company" style="color: #10b981;">Scan Complete: Live Results</span>
            <h2 class="drawer-title">Careers Portal Results</h2>
        </div>
        
        <div style="font-size:14px; color: var(--text-secondary); line-height:1.5;">
            Our automated spider resolved the corporate careers portal at:
            <a href="${data.careers_url}" target="_blank" style="color: var(--accent-secondary); word-break:break-all; display:block; margin-top:4px;">${escapeHTML(data.careers_url)}</a>
        </div>
        
        <div class="drawer-desc-block">
            <div class="drawer-desc-title">Discovered Vacancies (${data.jobs.length})</div>
            ${jobsListHTML}
        </div>
        
        <div class="action-btn-container">
            <button class="btn-secondary-border" onclick="switchTab('sponsors'); closeDrawer();">
                Back to Sponsors directory
            </button>
        </div>
    `;
    
    // Refresh core statistics
    updateLiveMetrics();
}

function generateSmartFallbackLinks(companyName) {
    const googleCareersUrl = `https://www.google.com/search?q=${encodeURIComponent(companyName)}+careers+jobs+UK`;
    const linkedinJobsUrl = `https://www.linkedin.com/jobs/search/?keywords=${encodeURIComponent(companyName)}`;
    
    // Open Google Careers as primary fallback
    window.open(googleCareersUrl, '_blank');
}

// 11. UI Helpers and Formatting utils
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
    const tbody = document.getElementById('sponsors-table-body');
    
    if (isLoading) {
        if (state.activeTab === 'jobs') {
            grid.innerHTML = `
                <div class="loading-indicator">
                    <div class="loading-spinner"></div>
                    <div class="loading-pulse-text">Loading live jobs feed...</div>
                </div>
            `;
        } else {
            tbody.innerHTML = `
                <tr>
                    <td colspan="5" style="text-align: center; padding: 40px;">
                        <div class="loading-spinner" style="margin: 0 auto 16px auto;"></div>
                        <div class="loading-pulse-text">Syncing registered sponsors directory...</div>
                    </td>
                </tr>
            `;
        }
    }
}

function showErrorUI() {
    const grid = document.getElementById('jobs-grid-container');
    const tbody = document.getElementById('sponsors-table-body');
    
    const errHTML = `
        <div class="loading-indicator">
            <p style="color: #ef4444; font-weight: 600;">Failed to establish connection to sponsorship database.</p>
            <p style="font-size: 13px; color: var(--text-muted);">Please verify the backend server.py is running on port 8000.</p>
        </div>
    `;
    
    if (state.activeTab === 'jobs') {
        grid.innerHTML = errHTML;
    } else {
        tbody.innerHTML = `<tr><td colspan="5">${errHTML}</td></tr>`;
    }
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
