document.addEventListener('DOMContentLoaded', function () {

    // ── State ──────────────────────────────────────────────────────────────
    let activeTab = 'report';
    const tabResults = { report: null, prescription: null, symptoms: null, medicine: null };
    let chatHistory = []; // RAG chatbot conversation history

    const ALLOWED_MIME = new Set([
        'image/jpeg', 'image/png', 'image/bmp', 'image/tiff', 'image/webp',
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/msword',
        'text/plain'
    ]);
    const ALLOWED_EXT = new Set(['jpg','jpeg','png','bmp','tiff','tif','webp','pdf','docx','doc','txt']);

    // ── Element References ─────────────────────────────────────────────────
    const loading         = document.getElementById('loading');
    const loadingTitle    = document.getElementById('loading-title');
    const loadingSub      = document.getElementById('loading-sub');
    const result          = document.getElementById('result');
    const error           = document.getElementById('error');
    const errorMessage    = document.getElementById('error-message');
    const englishBtn      = document.getElementById('english-btn');
    const banglaBtn       = document.getElementById('bangla-btn');
    const englishContent  = document.getElementById('english-content');
    const banglaContent   = document.getElementById('bangla-content');
    const translateBtn    = document.getElementById('translate-btn');
    const languageSelect  = document.getElementById('language-select');
    const downloadPdfBtn  = document.getElementById('download-pdf-btn');

    // ── Tab Switching ───────────────────────────────────────────────────────
    const tabs = {
        report:       { btn: document.getElementById('report-tab'),       section: document.getElementById('report-section') },
        prescription: { btn: document.getElementById('prescription-tab'), section: document.getElementById('prescription-section') },
        symptoms:     { btn: document.getElementById('symptoms-tab'),     section: document.getElementById('symptoms-section') },
        chatbot:      { btn: document.getElementById('chatbot-tab'),      section: document.getElementById('chatbot-section') },
        history:      { btn: document.getElementById('history-tab'),      section: document.getElementById('history-section') },
    };

    function switchTab(name) {
        activeTab = name;
        Object.entries(tabs).forEach(([key, tab]) => {
            if (!tab || !tab.btn || !tab.section) return;
            const isActive = key === name;
            tab.btn.classList.toggle('active', isActive);
            tab.section.classList.toggle('active', isActive);
            tab.section.classList.toggle('hidden', !isActive);
        });

        // Hide result/loading/error when switching away from result-producing tabs
        const resultTabs = ['report','prescription','symptoms'];
        if (!resultTabs.includes(name)) {
            loading.classList.add('hidden');
            error.classList.add('hidden');
            result.classList.add('hidden');
        } else {
            loading.classList.add('hidden');
            error.classList.add('hidden');
            renderTabResult();
        }

        // Auto-load history when switching to history tab
        if (name === 'history') {
            loadHistory();
        }
    }

    Object.entries(tabs).forEach(([name, tab]) => {
        if (tab && tab.btn) {
            tab.btn.addEventListener('click', () => switchTab(name));
        }
    });

    // ── File Validation ────────────────────────────────────────────────────
    function isFileAllowed(file) {
        const ext = file.name.split('.').pop().toLowerCase();
        if (ALLOWED_EXT.has(ext)) return true;
        if (ALLOWED_MIME.has(file.type)) return true;
        return false;
    }

    function formatFileSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / 1048576).toFixed(1) + ' MB';
    }

    // ── Generic Drop Zone Setup ────────────────────────────────────────────
    function setupDropZone(zoneId, inputId, fileNameId, analysisType) {
        const zone      = document.getElementById(zoneId);
        const input     = document.getElementById(inputId);
        const fileLabel = document.getElementById(fileNameId);
        if (!zone || !input) return;

        zone.addEventListener('dragover', (e) => {
            e.preventDefault();
            zone.classList.add('drag-over');
        });
        zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
        zone.addEventListener('drop', (e) => {
            e.preventDefault();
            zone.classList.remove('drag-over');
            const file = e.dataTransfer.files[0];
            if (file) handleFileUpload(file, fileLabel, analysisType);
        });
        zone.addEventListener('click', (e) => {
            if (!e.target.closest('label')) input.click();
        });
        input.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) handleFileUpload(file, fileLabel, analysisType);
            input.value = '';
        });
    }

    setupDropZone('drop-zone-report',        'file-input-report',        'file-name-report',        'report');
    setupDropZone('drop-zone-prescription',  'file-input-prescription',  'file-name-prescription',  'prescription');

    // ── File Upload Handler ────────────────────────────────────────────────
    function handleFileUpload(file, fileLabel, analysisType) {
        if (!isFileAllowed(file)) {
            showError(`Unsupported file type: "${file.name}". Please upload JPG, PNG, PDF, DOCX, BMP, TIFF, WEBP, or TXT.`);
            return;
        }
        if (file.size > 32 * 1024 * 1024) {
            showError(`File too large (${formatFileSize(file.size)}). Maximum allowed size is 32 MB.`);
            return;
        }

        if (fileLabel) {
            fileLabel.textContent = `📎 ${file.name} (${formatFileSize(file.size)})`;
            fileLabel.classList.remove('hidden');
        }

        const formData = new FormData();
        formData.append('file', file);
        formData.append('analysis_type', analysisType);

        // Include gender for report analysis
        if (analysisType === 'report') {
            const gender = document.getElementById('report-gender')?.value || 'unknown';
            formData.append('gender', gender);
        }

        // Include symptoms & medicine info for prescription analysis
        if (analysisType === 'prescription') {
            const symptoms = document.getElementById('prescription-symptoms-input')?.value?.trim() || '';
            formData.append('symptoms', symptoms);
            const rxAge = document.getElementById('rx-patient-age')?.value?.trim() || '';
            const rxGender = document.getElementById('rx-patient-gender')?.value || '';
            const rxMed = document.getElementById('rx-medicine-name')?.value?.trim() || '';
            const dM = parseInt(document.getElementById('rx-dosage-morning')?.value) || 0;
            const dE = parseInt(document.getElementById('rx-dosage-evening')?.value) || 0;
            const dN = parseInt(document.getElementById('rx-dosage-night')?.value) || 0;

            if (rxAge || rxGender || rxMed || (dM + dE + dN > 0)) {
                formData.append('patient_info', JSON.stringify({
                    age: rxAge ? parseInt(rxAge) : null,
                    gender: rxGender || 'unknown',
                    additional_medicine: rxMed,
                    dosage: { morning: dM, evening: dE, night: dN }
                }));
            }
        }

        const loadMsg = analysisType === 'prescription'
            ? 'Extracting prescription + DDI &amp; Symptom check...'
            : 'Extracting report + analyzing biomarkers...';
        const subMsg = analysisType === 'prescription'
            ? 'OCR → Medicine extraction → DDI check → Symptom correlation → AI analysis'
            : 'OCR → Biomarker extraction → Reference classification → AI analysis';

        setLoadingState(loadMsg, subMsg);

        fetch('/upload', { method: 'POST', body: formData })
            .then(r => r.json())
            .then(data => handleResponse(data))
            .catch(err => handleError(err));
    }

    // ── Report Text Analyze ────────────────────────────────────────────────
    document.getElementById('analyze-report-text-btn').addEventListener('click', () => {
        const text = document.getElementById('report-text-input').value.trim();
        if (!text) { showError('Please paste your medical report text first.'); return; }
        const gender = document.getElementById('report-gender')?.value || 'unknown';
        setLoadingState('Analyzing report text + extracting biomarkers...', 'Biomarker extraction → AI clinical analysis');
        fetch('/analyze-report-text', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ report_text: text, analysis_type: 'report', gender })
        })
        .then(r => r.json())
        .then(data => handleResponse(data))
        .catch(err => handleError(err));
    });

    // ── Prescription Text Analyze (Integrated with Dosage & Symptoms) ────
    document.getElementById('analyze-prescription-text-btn').addEventListener('click', () => {
        let text = document.getElementById('prescription-text-input')?.value?.trim() || '';
        const symptoms = document.getElementById('prescription-symptoms-input')?.value?.trim() || '';
        const rxAge = document.getElementById('rx-patient-age')?.value?.trim() || '';
        const rxGender = document.getElementById('rx-patient-gender')?.value || '';
        const rxMed = document.getElementById('rx-medicine-name')?.value?.trim() || '';
        const dM = parseInt(document.getElementById('rx-dosage-morning')?.value) || 0;
        const dE = parseInt(document.getElementById('rx-dosage-evening')?.value) || 0;
        const dN = parseInt(document.getElementById('rx-dosage-night')?.value) || 0;

        let manualMedClause = '';
        if (rxMed) {
            manualMedClause = `Tab. ${rxMed}`;
            if (dM > 0 || dE > 0 || dN > 0) {
                manualMedClause += ` ${dM}-${dE}-${dN}`;
            }
        }

        if (manualMedClause) {
            if (text) {
                text += `\n${manualMedClause}`;
            } else {
                text = manualMedClause;
            }
        }

        if (!text && !symptoms) {
            showError('Please paste prescription text or enter a medicine name or describe your symptoms.');
            return;
        }

        let patientInfo = null;
        if (rxAge || rxGender || (dM + dE + dN > 0)) {
            patientInfo = {
                age: rxAge ? parseInt(rxAge) : null,
                gender: rxGender || 'unknown',
                dosage: { morning: dM, evening: dE, night: dN }
            };
        }

        setLoadingState('Analyzing prescription + DDI, Medicine Info & Symptom check...', 'Medicine extraction → DDI verification → Symptom correlation → AI analysis');
        fetch('/analyze-report-text', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                report_text: text || `Reported Symptoms: ${symptoms}`,
                analysis_type: 'prescription',
                symptoms: symptoms,
                patient_info: patientInfo
            })
        })
        .then(r => r.json())
        .then(data => handleResponse(data))
        .catch(err => handleError(err));
    });

    // ── Symptoms Analyze ───────────────────────────────────────────────────
    document.getElementById('analyze-symptoms').addEventListener('click', () => {
        const symptoms = document.getElementById('symptoms-input').value.trim();
        if (!symptoms) { showError('Please describe your symptoms first.'); return; }
        setLoadingState('Analyzing symptoms...', 'AI is evaluating possible conditions');
        fetch('/analyze-symptoms', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symptoms })
        })
        .then(r => r.json())
        .then(data => handleResponse(data))
        .catch(err => handleError(err));
    });

    // ── Medicine Analyze ───────────────────────────────────────────────────
    document.getElementById('analyze-medicine').addEventListener('click', () => {
        const medicine = document.getElementById('medicine-name').value.trim();
        const age      = document.getElementById('patient-age').value.trim();
        const gender   = document.getElementById('patient-gender').value;

        if (!medicine) { showError('Please enter a medicine name.'); return; }
        if (!age || parseInt(age) <= 0) { showError('Please enter a valid patient age.'); return; }
        if (!gender) { showError('Please select patient gender.'); return; }

        const dosage = {
            morning: parseInt(document.getElementById('dosage-morning').value) || 0,
            evening: parseInt(document.getElementById('dosage-evening').value) || 0,
            night:   parseInt(document.getElementById('dosage-night').value)   || 0,
        };
        if (dosage.morning === 0 && dosage.evening === 0 && dosage.night === 0) {
            showError('Please enter at least one dosage value.');
            return;
        }

        setLoadingState('Analyzing medicine...', 'Looking up dosage, side effects & interactions');
        fetch('/analyze-medicine', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ medicine, dosage, patient: { age: parseInt(age), gender } })
        })
        .then(r => r.json())
        .then(data => handleResponse(data))
        .catch(err => handleError(err));
    });

    // ── Translation ────────────────────────────────────────────────────────
    translateBtn.addEventListener('click', async () => {
        const current = tabResults[activeTab];
        if (!current || !current.english) { showError('No content to translate.'); return; }

        const lang = languageSelect.value;
        translateBtn.disabled = true;
        translateBtn.innerHTML = `<svg class="spinner-sm" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" stroke-dasharray="40" stroke-dashoffset="10"/></svg> Translating…`;

        try {
            const res  = await fetch('/translate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: current.english, target_language: lang })
            });
            const data = await res.json();

            if (data.success && data.translation) {
                current.bangla = data.translation;
                banglaContent.innerHTML = safeMarkdown(data.translation);
                banglaBtn.textContent = lang;
                banglaBtn.classList.remove('hidden');
                banglaBtn.click();
            } else {
                showError(data.error || 'Translation failed.');
            }
        } catch (e) {
            showError('Translation request failed. Please try again.');
        } finally {
            translateBtn.disabled = false;
            translateBtn.innerHTML = `<svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129"/></svg> Translate`;
        }
    });

    // ── Language Toggles ───────────────────────────────────────────────────
    englishBtn.addEventListener('click', () => {
        englishBtn.classList.remove('btn-outline'); englishBtn.classList.add('btn-primary');
        banglaBtn.classList.remove('btn-primary');  banglaBtn.classList.add('btn-outline');
        englishContent.classList.remove('hidden');
        banglaContent.classList.add('hidden');
    });
    banglaBtn.addEventListener('click', () => {
        const cur = tabResults[activeTab];
        if (!cur || !cur.bangla) return;
        banglaBtn.classList.remove('btn-outline'); banglaBtn.classList.add('btn-primary');
        englishBtn.classList.remove('btn-primary'); englishBtn.classList.add('btn-outline');
        banglaContent.classList.remove('hidden');
        englishContent.classList.add('hidden');
    });

    // ── PDF Download ───────────────────────────────────────────────────────
    if (downloadPdfBtn) {
        downloadPdfBtn.addEventListener('click', () => {
            const cur = tabResults[activeTab];
            if (!cur || !cur.english) { showError('No analysis to download.'); return; }

            const resultEl  = document.getElementById('result');
            const actionBar = resultEl.querySelector('.result-actions');
            const followupEl = document.getElementById('followup-chat-container');
            if (actionBar) actionBar.style.display = 'none';
            if (followupEl) followupEl.style.display = 'none';

            const headerEl = document.createElement('div');
            headerEl.id = 'pdf-header';
            headerEl.style.cssText = 'border-bottom:2px solid #2563eb;padding-bottom:12px;margin-bottom:20px;';
            headerEl.innerHTML = `
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <div>
                        <h1 style="color:#1d4ed8;font-size:22px;font-weight:800;margin:0;">Medical Report Analyzer</h1>
                        <p style="color:#2563eb;font-size:11px;font-weight:700;text-transform:uppercase;margin-top:3px;">AI Clinical Summary — ${activeTab.toUpperCase()} ANALYSIS</p>
                    </div>
                    <div style="text-align:right;font-size:10px;color:#6b7280;">
                        <div style="background:#eff6ff;color:#1d4ed8;padding:3px 10px;border-radius:12px;border:1px solid #bfdbfe;font-weight:700;margin-bottom:4px;">NVIDIA NIM Active</div>
                        ${new Date().toLocaleString()}
                    </div>
                </div>`;

            const footerEl = document.createElement('div');
            footerEl.id = 'pdf-footer';
            footerEl.style.cssText = 'border-top:2px solid #e5e7eb;padding-top:12px;margin-top:25px;font-size:9.5px;color:#6b7280;text-align:center;';
            footerEl.innerHTML = `<strong>Disclaimer:</strong> AI-assisted for informational purposes only. Consult a certified physician for medical decisions.<br><span>© 2026 Medical Report Analyzer AI System • v3.0</span>`;

            resultEl.insertBefore(headerEl, resultEl.firstChild);
            resultEl.appendChild(footerEl);

            html2pdf().set({
                margin:      [0.4, 0.4, 0.4, 0.4],
                filename:    `Medical_Analysis_${activeTab}_${Date.now()}.pdf`,
                image:       { type: 'jpeg', quality: 0.98 },
                html2canvas: { scale: 2, useCORS: true },
                jsPDF:       { unit: 'in', format: 'letter', orientation: 'portrait' }
            }).from(resultEl).save().then(() => {
                document.getElementById('pdf-header')?.remove();
                document.getElementById('pdf-footer')?.remove();
                if (actionBar) actionBar.style.display = '';
                if (followupEl) followupEl.style.display = '';
            }).catch(() => {
                document.getElementById('pdf-header')?.remove();
                document.getElementById('pdf-footer')?.remove();
                if (actionBar) actionBar.style.display = '';
                if (followupEl) followupEl.style.display = '';
                showError('PDF generation failed. Please try again.');
            });
        });
    }

    // ── RAG CHATBOT ───────────────────────────────────────────────────────
    const chatbotInput  = document.getElementById('chatbot-input');
    const chatbotSend   = document.getElementById('chatbot-send');
    const chatbotMsgs   = document.getElementById('chatbot-messages');

    function appendChatMessage(role, content) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `chat-message ${role === 'user' ? 'user-message' : 'assistant-message'}`;
        const avatar = document.createElement('div');
        avatar.className = 'chat-avatar';
        avatar.textContent = role === 'user' ? '👤' : '🤖';
        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble';
        bubble.innerHTML = safeMarkdown(content);
        msgDiv.appendChild(avatar);
        msgDiv.appendChild(bubble);
        chatbotMsgs.appendChild(msgDiv);
        chatbotMsgs.scrollTop = chatbotMsgs.scrollHeight;
    }

    function sendChatMessage() {
        const q = chatbotInput.value.trim();
        if (!q) return;

        appendChatMessage('user', q);
        chatHistory.push({ role: 'user', content: q });
        chatbotInput.value = '';
        chatbotSend.disabled = true;
        chatbotSend.textContent = '…';

        // Add typing indicator
        const typingDiv = document.createElement('div');
        typingDiv.className = 'chat-message assistant-message';
        typingDiv.id = 'typing-indicator';
        typingDiv.innerHTML = `<div class="chat-avatar">🤖</div><div class="chat-bubble" style="color:#9ca3af;font-style:italic;">Thinking...</div>`;
        chatbotMsgs.appendChild(typingDiv);
        chatbotMsgs.scrollTop = chatbotMsgs.scrollHeight;

        fetch('/chatbot', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question: q, history: chatHistory.slice(-6) })
        })
        .then(r => r.json())
        .then(data => {
            document.getElementById('typing-indicator')?.remove();
            if (data.success && data.response) {
                appendChatMessage('assistant', data.response);
                chatHistory.push({ role: 'assistant', content: data.response });
            } else {
                appendChatMessage('assistant', data.error || 'Sorry, I could not process that. Please try again.');
            }
        })
        .catch(err => {
            document.getElementById('typing-indicator')?.remove();
            appendChatMessage('assistant', 'Network error. Please check your connection and try again.');
        })
        .finally(() => {
            chatbotSend.disabled = false;
            chatbotSend.innerHTML = `<svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/></svg> Send`;
        });
    }

    chatbotSend.addEventListener('click', sendChatMessage);
    chatbotInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendChatMessage();
        }
    });

    // Suggestion chips
    document.querySelectorAll('.suggestion-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            chatbotInput.value = chip.dataset.q;
            sendChatMessage();
        });
    });

    // ── CONTEXTUAL FOLLOW-UP RAG CHATBOT IN RESULT ───────────────────────
    const followupInput = document.getElementById('followup-input');
    const followupSend  = document.getElementById('followup-send');
    const followupMsgs  = document.getElementById('followup-messages');
    let followupHistory = [];

    function appendFollowupMessage(role, content) {
        if (!followupMsgs) return;
        const msgDiv = document.createElement('div');
        msgDiv.className = `chat-message ${role === 'user' ? 'user-message' : 'assistant-message'}`;
        const avatar = document.createElement('div');
        avatar.className = 'chat-avatar';
        avatar.textContent = role === 'user' ? '👤' : '🤖';
        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble';
        bubble.innerHTML = safeMarkdown(content);
        msgDiv.appendChild(avatar);
        msgDiv.appendChild(bubble);
        followupMsgs.appendChild(msgDiv);
        followupMsgs.scrollTop = followupMsgs.scrollHeight;
    }

    function sendFollowupMessage() {
        if (!followupInput) return;
        const q = followupInput.value.trim();
        if (!q) return;

        appendFollowupMessage('user', q);
        followupHistory.push({ role: 'user', content: q });
        followupInput.value = '';
        if (followupSend) {
            followupSend.disabled = true;
            followupSend.textContent = '…';
        }

        const curResult = tabResults[activeTab];
        const currentAnalysisText = curResult ? (curResult.english || '') : '';

        // Add typing indicator
        const typingDiv = document.createElement('div');
        typingDiv.className = 'chat-message assistant-message';
        typingDiv.id = 'followup-typing-indicator';
        typingDiv.innerHTML = `<div class="chat-avatar">🤖</div><div class="chat-bubble" style="color:#9ca3af;font-style:italic;">Analyzing result context & answering...</div>`;
        followupMsgs.appendChild(typingDiv);
        followupMsgs.scrollTop = followupMsgs.scrollHeight;

        fetch('/chatbot', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question: q,
                history: followupHistory.slice(-6),
                current_analysis: currentAnalysisText
            })
        })
        .then(r => r.json())
        .then(data => {
            document.getElementById('followup-typing-indicator')?.remove();
            if (data.success && data.response) {
                appendFollowupMessage('assistant', data.response);
                followupHistory.push({ role: 'assistant', content: data.response });
            } else {
                appendFollowupMessage('assistant', data.error || 'Sorry, I could not process that. Please try again.');
            }
        })
        .catch(err => {
            document.getElementById('followup-typing-indicator')?.remove();
            appendFollowupMessage('assistant', 'Network error. Please check your connection and try again.');
        })
        .finally(() => {
            if (followupSend) {
                followupSend.disabled = false;
                followupSend.innerHTML = `<svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/></svg> Ask AI`;
            }
        });
    }

    if (followupSend) followupSend.addEventListener('click', sendFollowupMessage);
    if (followupInput) {
        followupInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendFollowupMessage();
            }
        });
    }

    // Follow-up suggestion chips
    document.querySelectorAll('.followup-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            if (followupInput) {
                followupInput.value = chip.dataset.q;
                sendFollowupMessage();
            }
        });
    });

    // ── PATIENT PROFILE & HISTORY ─────────────────────────────────────────
    const saveProfileBtn = document.getElementById('save-profile-btn');
    const profileStatusMsg = document.getElementById('profile-status-msg');

    if (saveProfileBtn) {
        saveProfileBtn.addEventListener('click', saveProfile);
    }

    function loadProfile() {
        fetch('/profile')
            .then(r => r.json())
            .then(data => {
                if (data.success && data.profile) {
                    const p = data.profile;
                    const nameEl = document.getElementById('prof-name');
                    const ageEl = document.getElementById('prof-age');
                    const genderEl = document.getElementById('prof-gender');
                    const condEl = document.getElementById('prof-conditions');
                    const allergEl = document.getElementById('prof-allergies');
                    if (nameEl && p.name) nameEl.value = p.name;
                    if (ageEl && p.age) ageEl.value = p.age;
                    if (genderEl && p.gender) genderEl.value = p.gender;
                    if (condEl && p.known_conditions) condEl.value = p.known_conditions;
                    if (allergEl && p.allergies) allergEl.value = p.allergies;
                }
            })
            .catch(err => console.error('Error loading profile:', err));
    }

    function saveProfile() {
        const name = document.getElementById('prof-name')?.value?.trim() || 'Primary Patient';
        const age = document.getElementById('prof-age')?.value?.trim() || null;
        const gender = document.getElementById('prof-gender')?.value || 'unknown';
        const conditions = document.getElementById('prof-conditions')?.value?.trim() || '';
        const allergies = document.getElementById('prof-allergies')?.value?.trim() || '';

        if (saveProfileBtn) saveProfileBtn.disabled = true;

        fetch('/profile', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name,
                age: age ? parseInt(age) : null,
                gender,
                known_conditions: conditions,
                allergies
            })
        })
        .then(r => r.json())
        .then(data => {
            if (profileStatusMsg) {
                profileStatusMsg.textContent = '✅ Profile saved successfully!';
                profileStatusMsg.classList.remove('hidden');
                setTimeout(() => profileStatusMsg.classList.add('hidden'), 3500);
            }
        })
        .catch(err => {
            if (profileStatusMsg) {
                profileStatusMsg.textContent = '❌ Failed to save profile.';
                profileStatusMsg.classList.remove('hidden');
            }
        })
        .finally(() => {
            if (saveProfileBtn) saveProfileBtn.disabled = false;
        });
    }

    document.getElementById('refresh-history')?.addEventListener('click', loadHistory);

    function loadHistory() {
        loadProfile();
        fetch('/history')
            .then(r => r.json())
            .then(data => {
                if (!data.success) return;
                renderActiveMedicines(data.active_medicines || []);
                renderLabHistory(data.lab_history || []);
                renderAnalysisHistory(data.analyses || []);
            })
            .catch(err => console.error('History load error:', err));
    }

    function renderActiveMedicines(meds) {
        const container = document.getElementById('active-medicines-list');
        if (!container) return;
        if (!meds.length) {
            container.innerHTML = '<p class="history-empty">No active medicines recorded yet. Upload a prescription to track medicines.</p>';
            return;
        }
        container.innerHTML = meds.map(m => {
            const name = (m.canonical_name || '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
            const brand = m.brand_name ? ` (${m.brand_name})` : '';
            const dosage = m.dosage ? ` | ${m.dosage}` : '';
            const freq = m.frequency ? ` | ${m.frequency}` : '';
            const canName = m.canonical_name || '';
            return `<div class="history-item">
                <span class="history-badge badge-medicine">💊 Medicine</span>
                <span style="flex:1;"><strong>${name}</strong>${brand}${dosage}${freq}</span>
                <button class="btn-action-sm btn-action-discontinue" data-med="${canName}">Discontinue</button>
            </div>`;
        }).join('');

        container.querySelectorAll('.btn-action-discontinue').forEach(btn => {
            btn.addEventListener('click', () => {
                const medName = btn.dataset.med;
                if (!medName) return;
                fetch('/set-medicine-status', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ canonical_name: medName, confirmed: 0, discontinued: 1 })
                })
                .then(r => r.json())
                .then(() => loadHistory())
                .catch(err => console.error('Error discontinuing medicine:', err));
            });
        });
    }

    function renderLabHistory(labs) {
        const container = document.getElementById('lab-history-list');
        if (!container) return;
        if (!labs.length) {
            container.innerHTML = '<p class="history-empty">No lab results yet. Upload a medical report to track values.</p>';
            return;
        }
        container.innerHTML = labs.map(l => {
            const name = (l.test_name || '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
            const status = l.status || 'UNKNOWN';
            const badgeClass = status === 'NORMAL' ? 'badge-normal'
                : (status === 'HIGH' || status === 'DEFICIENT') ? 'badge-high'
                : status === 'LOW' ? 'badge-low'
                : 'badge-prediabetes';
            return `<div class="history-item">
                <span class="history-badge ${badgeClass}">${status}</span>
                <span><strong>${name}</strong>: ${l.value} ${l.unit || ''}</span>
                <span style="color:#6b7280;font-size:.75rem;">Ref: ${l.reference_range || ''}</span>
                ${l.test_date ? `<span style="color:#9ca3af;font-size:.72rem;">${l.test_date}</span>` : ''}
            </div>`;
        }).join('');
    }

    function renderAnalysisHistory(analyses) {
        const container = document.getElementById('analysis-history-list');
        if (!container) return;
        if (!analyses.length) {
            container.innerHTML = '<p class="history-empty">No analyses yet.</p>';
            return;
        }
        container.innerHTML = analyses.map(a => {
            const type = (a.analysis_type || '').toUpperCase();
            const file = a.filename || 'Text Input';
            const date = a.created_at ? new Date(a.created_at).toLocaleString() : '';
            return `<div class="history-item">
                <span class="history-badge badge-medicine">${type}</span>
                <span><strong>${file}</strong></span>
                <span style="color:#9ca3af;font-size:.72rem;">${date}</span>
            </div>`;
        }).join('');
    }

    // ── Helpers ────────────────────────────────────────────────────────────
    function safeMarkdown(text) {
        try { return marked.parse(text); }
        catch (e) { return `<pre>${text}</pre>`; }
    }

    function setLoadingState(title, sub) {
        loading.classList.remove('hidden');
        result.classList.add('hidden');
        error.classList.add('hidden');
        if (loadingTitle) loadingTitle.innerHTML = title;
        if (loadingSub)   loadingSub.textContent = sub;
    }

    function handleResponse(data) {
        loading.classList.add('hidden');
        if (data.success && data.analysis) {
            tabResults[activeTab] = data.analysis;
            renderTabResult();
        } else {
            showError(data.error || 'An unexpected error occurred. Please try again.');
        }
    }

    function handleError(err) {
        console.error('Request error:', err);
        loading.classList.add('hidden');
        showError('Could not reach the server. Please check your connection and try again.');
    }

    function showError(msg) {
        error.classList.remove('hidden');
        result.classList.add('hidden');
        loading.classList.add('hidden');
        errorMessage.textContent = msg;
    }

    function renderTabResult() {
        const cur = tabResults[activeTab];
        if (!cur || !cur.english) {
            result.classList.add('hidden');
            return;
        }
        result.classList.remove('hidden');
        englishContent.innerHTML = safeMarkdown(cur.english);

        if (cur.bangla) {
            banglaContent.innerHTML = safeMarkdown(cur.bangla);
            banglaBtn.classList.remove('hidden');
            translateBtn.classList.add('hidden');
        } else {
            translateBtn.classList.remove('hidden');
            banglaBtn.classList.add('hidden');
        }

        // Always show English by default
        englishContent.classList.remove('hidden');
        banglaContent.classList.add('hidden');
        englishBtn.classList.add('btn-primary'); englishBtn.classList.remove('btn-outline');
        banglaBtn.classList.remove('btn-primary'); banglaBtn.classList.add('btn-outline');
    }

    // Initial render
    switchTab('report');
});
