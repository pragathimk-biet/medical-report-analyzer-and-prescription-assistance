document.addEventListener('DOMContentLoaded', function() {
    // Tab switching functionality
    const reportTab = document.getElementById('report-tab');
    const symptomsTab = document.getElementById('symptoms-tab');
    const medicineTab = document.getElementById('medicine-tab');
    const reportSection = document.getElementById('report-section');
    const symptomsSection = document.getElementById('symptoms-section');
    const medicineSection = document.getElementById('medicine-section');
    const translateBtn = document.getElementById('translate-btn');
    
    // Per-tab analysis state tracking
    let activeTab = 'report';
    const tabResults = {
        report: null,
        symptoms: null,
        medicine: null
    };

    function switchTab(tabName) {
        activeTab = tabName;

        // Reset all tab styling
        [reportTab, symptomsTab, medicineTab].forEach(btn => {
            btn.classList.remove('active', 'text-blue-600', 'font-bold');
            btn.classList.add('text-gray-500', 'font-semibold');
        });

        reportSection.classList.add('hidden');
        symptomsSection.classList.add('hidden');
        medicineSection.classList.add('hidden');

        if (tabName === 'report') {
            reportTab.classList.add('active', 'text-blue-600', 'font-bold');
            reportTab.classList.remove('text-gray-500');
            reportSection.classList.remove('hidden');
        } else if (tabName === 'symptoms') {
            symptomsTab.classList.add('active', 'text-blue-600', 'font-bold');
            symptomsTab.classList.remove('text-gray-500');
            symptomsSection.classList.remove('hidden');
        } else if (tabName === 'medicine') {
            medicineTab.classList.add('active', 'text-blue-600', 'font-bold');
            medicineTab.classList.remove('text-gray-500');
            medicineSection.classList.remove('hidden');
        }

        // Hide loading and error on tab switch
        loading.classList.add('hidden');
        error.classList.add('hidden');

        // Render result for the selected active tab only
        renderTabResult();
    }

    reportTab.addEventListener('click', () => switchTab('report'));
    symptomsTab.addEventListener('click', () => switchTab('symptoms'));
    medicineTab.addEventListener('click', () => switchTab('medicine'));

    // File upload functionality
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const loading = document.getElementById('loading');
    const result = document.getElementById('result');
    const error = document.getElementById('error');
    const errorMessage = document.getElementById('error-message');
    const englishBtn = document.getElementById('english-btn');
    const banglaBtn = document.getElementById('bangla-btn');
    const englishContent = document.getElementById('english-content');
    const banglaContent = document.getElementById('bangla-content');

    // Drag and drop handlers
    if (dropZone) {
        ['dragenter', 'dragover'].forEach(eventName => {
            dropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropZone.classList.add('dragover');
            }, false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropZone.classList.remove('dragover');
            }, false);
        });

        dropZone.addEventListener('drop', (e) => {
            const dt = e.dataTransfer;
            const file = dt.files[0];
            handleFile(file);
        });

        dropZone.addEventListener('click', (e) => {
            if (e.target.tagName !== 'INPUT') {
                fileInput.click();
            }
        });
    }

    fileInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        handleFile(file);
    });

    function handleFile(file) {
        if (!file) return;

        // Check file type
        const allowedTypes = ['image/jpeg', 'image/png', 'application/pdf'];
        const ext = file.name.split('.').pop().toLowerCase();
        if (!allowedTypes.includes(file.type) && !['jpg', 'jpeg', 'png', 'pdf'].includes(ext)) {
            showError('Please upload a valid JPG, PNG, or PDF file.');
            return;
        }

        const formData = new FormData();
        formData.append('file', file);

        showLoading('Analyzing Medical Document with AI...');
        console.log('Uploading file:', file.name);

        fetch('/upload', {
            method: 'POST',
            body: formData
        })
        .then(response => {
            console.log('Response status:', response.status);
            return response.json();
        })
        .then(data => {
            console.log('Response data:', data);
            handleResponse(data);
        })
        .catch(err => {
            console.error('Error:', err);
            handleError(err);
        });
    }

    // Direct Report Text Analysis functionality
    const reportTextInput = document.getElementById('report-text-input');
    const analyzeReportTextBtn = document.getElementById('analyze-report-text-btn');

    if (analyzeReportTextBtn && reportTextInput) {
        analyzeReportTextBtn.addEventListener('click', () => {
            const text = reportTextInput.value.trim();
            if (!text) {
                showError('Please paste your medical report text first.');
                return;
            }

            showLoading('Analyzing Medical Report Text...');
            console.log('Analyzing report text directly');

            fetch('/analyze-report-text', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ report_text: text })
            })
            .then(response => response.json())
            .then(data => handleResponse(data))
            .catch(err => handleError(err));
        });
    }

    // Symptoms analysis functionality
    const symptomsInput = document.getElementById('symptoms-input');
    const analyzeButton = document.getElementById('analyze-symptoms');

    if (analyzeButton && symptomsInput) {
        analyzeButton.addEventListener('click', () => {
            const symptoms = symptomsInput.value.trim();
            if (!symptoms) {
                showError('Please describe your symptoms in detail');
                return;
            }

            showLoading('Evaluating Symptoms against Clinical Benchmarks...');
            console.log('Analyzing symptoms');

            fetch('/analyze-symptoms', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ symptoms: symptoms })
            })
            .then(response => response.json())
            .then(data => handleResponse(data))
            .catch(err => handleError(err));
        });
    }

    // Medicine analysis functionality
    const medicineName = document.getElementById('medicine-name');
    const dosageMorning = document.getElementById('dosage-morning');
    const dosageEvening = document.getElementById('dosage-evening');
    const dosageNight = document.getElementById('dosage-night');
    const patientAge = document.getElementById('patient-age');
    const patientGender = document.getElementById('patient-gender');
    const analyzeMedicineBtn = document.getElementById('analyze-medicine');

    if (analyzeMedicineBtn) {
        analyzeMedicineBtn.addEventListener('click', () => {
            const medicine = medicineName.value.trim();
            const age = patientAge.value.trim();
            const gender = patientGender.value;

            // Validate inputs
            if (!medicine) {
                showError('Please enter a medicine name');
                return;
            }

            const dosage = {
                morning: parseInt(dosageMorning.value) || 0,
                evening: parseInt(dosageEvening.value) || 0,
                night: parseInt(dosageNight.value) || 0
            };

            if (dosage.morning === 0 && dosage.evening === 0 && dosage.night === 0) {
                showError('Please enter at least one dosage value');
                return;
            }

            showLoading('Checking Medication Safety & Historical Contraindications...');

            fetch('/analyze-medicine', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    medicine: medicine,
                    dosage: dosage,
                    patient: {
                        age: age ? parseInt(age) : null,
                        gender: gender || null
                    }
                })
            })
            .then(response => response.json())
            .then(data => handleResponse(data))
            .catch(err => handleError(err));
        });
    }

    // Prescription File Upload functionality
    const prescriptionDropZone = document.getElementById('prescription-drop-zone');
    const prescriptionFileInput = document.getElementById('prescription-file-input');

    if (prescriptionDropZone && prescriptionFileInput) {
        ['dragenter', 'dragover'].forEach(eventName => {
            prescriptionDropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                prescriptionDropZone.classList.add('bg-blue-100');
            }, false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            prescriptionDropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                prescriptionDropZone.classList.remove('bg-blue-100');
            }, false);
        });

        prescriptionDropZone.addEventListener('drop', (e) => {
            const file = e.dataTransfer.files[0];
            handlePrescriptionFile(file);
        });

        prescriptionDropZone.addEventListener('click', (e) => {
            if (e.target.tagName !== 'INPUT') {
                prescriptionFileInput.click();
            }
        });

        prescriptionFileInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            handlePrescriptionFile(file);
        });
    }

    function handlePrescriptionFile(file) {
        if (!file) return;

        const allowedTypes = ['image/jpeg', 'image/png', 'application/pdf'];
        const ext = file.name.split('.').pop().toLowerCase();
        if (!allowedTypes.includes(file.type) && !['jpg', 'jpeg', 'png', 'pdf'].includes(ext)) {
            showError('Please upload a valid JPG, PNG, or PDF prescription document');
            return;
        }

        const formData = new FormData();
        formData.append('file', file);

        const age = patientAge ? patientAge.value.trim() : '';
        const gender = patientGender ? patientGender.value : '';
        if (age) formData.append('age', age);
        if (gender) formData.append('gender', gender);

        showLoading('Analyzing Prescription with Model 2 Handwriting Cross-Check...');

        fetch('/upload-prescription', {
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => handleResponse(data))
        .catch(err => {
            console.error('Prescription Upload Error:', err);
            handleError(err);
        });
    }

    // PDF Report Export functionality
    const downloadPdfBtn = document.getElementById('download-pdf-btn');
    if (downloadPdfBtn) {
        downloadPdfBtn.addEventListener('click', () => {
            const currentAnalysis = tabResults[activeTab];
            if (!currentAnalysis || !currentAnalysis.english) {
                showError('No generated analysis results available to download.');
                return;
            }

            const resultElement = document.getElementById('result');
            const actionBar = resultElement.querySelector('.flex.flex-wrap');
            const chatSection = document.getElementById('rag-chat-section');

            // Temporarily hide interactive UI elements during PDF render
            if (actionBar) actionBar.style.display = 'none';
            if (chatSection) chatSection.style.display = 'none';

            // Inject PDF Header banner
            const headerBanner = document.createElement('div');
            headerBanner.id = 'pdf-inline-header';
            headerBanner.style.borderBottom = '2px solid #2563eb';
            headerBanner.style.paddingBottom = '12px';
            headerBanner.style.marginBottom = '20px';
            headerBanner.style.paddingTop = '10px';
            headerBanner.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <h1 style="color: #1d4ed8; font-size: 22px; font-weight: 800; margin: 0;">Medical Report Analyzer</h1>
                        <div style="color: #2563eb; font-size: 10px; font-weight: 700; text-transform: uppercase; margin-top: 2px;">
                            Official Clinical AI Summary & Health Guidance Report
                        </div>
                    </div>
                    <div style="text-align: right;">
                        <span style="background-color: #eff6ff; color: #1d4ed8; padding: 4px 10px; border-radius: 12px; font-size: 10px; font-weight: 700; border: 1px solid #bfdbfe;">
                            NVIDIA NIM / RapidOCR Active
                        </span>
                        <div style="color: #6b7280; font-size: 9px; margin-top: 4px;">
                            Generated: ${new Date().toLocaleDateString()} ${new Date().toLocaleTimeString()}
                        </div>
                    </div>
                </div>
            `;

            // Inject PDF Footer banner
            const footerBanner = document.createElement('div');
            footerBanner.id = 'pdf-inline-footer';
            footerBanner.style.borderTop = '2px solid #e5e7eb';
            footerBanner.style.paddingTop = '12px';
            footerBanner.style.marginTop = '25px';
            footerBanner.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: center; font-size: 9px; color: #4b5563; margin-bottom: 6px;">
                    <div><strong>Engine:</strong> Python 3.12 • Flask • Llama 3.1 8B • RapidOCR</div>
                    <div><strong>Module:</strong> ${activeTab.toUpperCase()} ANALYSIS</div>
                </div>
                <div style="font-size: 8.5px; color: #6b7280; text-align: center; line-height: 1.4; background: #f9fafb; padding: 6px; border-radius: 6px; border: 1px solid #f3f4f6;">
                    <strong>Medical Disclaimer:</strong> This document is an AI-assisted clinical report intended strictly for educational and informational purposes. Always consult a certified physician for medical diagnosis.
                </div>
            `;

            resultElement.insertBefore(headerBanner, resultElement.firstChild);
            resultElement.appendChild(footerBanner);

            const options = {
                margin:       [0.3, 0.3, 0.3, 0.3],
                filename:     `Medical_Report_Analysis_${Date.now()}.pdf`,
                image:        { type: 'jpeg', quality: 0.98 },
                html2canvas:  { scale: 2, useCORS: true, scrollX: 0, scrollY: 0 },
                jsPDF:        { unit: 'in', format: 'letter', orientation: 'portrait' }
            };

            html2pdf().set(options).from(resultElement).save().then(() => {
                if (document.getElementById('pdf-inline-header')) headerBanner.remove();
                if (document.getElementById('pdf-inline-footer')) footerBanner.remove();
                if (actionBar) actionBar.style.display = 'flex';
                if (chatSection) chatSection.style.display = 'block';
            }).catch(err => {
                console.error("PDF generation error:", err);
                if (document.getElementById('pdf-inline-header')) headerBanner.remove();
                if (document.getElementById('pdf-inline-footer')) footerBanner.remove();
                if (actionBar) actionBar.style.display = 'flex';
                if (chatSection) chatSection.style.display = 'block';
                showError('Failed to generate PDF. Please try again.');
            });
        });
    }

    // Translation handling
    const languageSelect = document.getElementById('language-select');
    if (translateBtn) {
        translateBtn.addEventListener('click', async () => {
            const currentAnalysis = tabResults[activeTab];
            if (!currentAnalysis || !currentAnalysis.english) {
                showError('No content available to translate');
                return;
            }

            const selectedLanguage = languageSelect ? languageSelect.value : 'Kannada';

            // Show loading state
            translateBtn.disabled = true;
            translateBtn.innerHTML = `
                <svg class="animate-spin -ml-1 mr-1 h-3.5 w-3.5 text-white inline" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                Translating...
            `;
            
            try {
                const response = await fetch('/translate', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ 
                        text: currentAnalysis.english,
                        target_language: selectedLanguage
                    })
                });

                const data = await response.json();
                
                if (data.success && data.translation) {
                    currentAnalysis.bangla = data.translation;
                    
                    try {
                        banglaContent.innerHTML = formatPatientFriendlyHTML(data.translation);
                    } catch (err) {
                        console.error('Error parsing markdown:', err);
                        banglaContent.textContent = data.translation;
                    }

                    banglaBtn.textContent = `${selectedLanguage}`;
                    banglaBtn.classList.remove('hidden');
                    banglaBtn.click();
                } else {
                    showError(data.error || 'Translation failed');
                }
            } catch (err) {
                console.error('Translation error:', err);
                showError('Failed to translate content');
            } finally {
                translateBtn.disabled = false;
                translateBtn.innerHTML = `
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129"></path></svg>
                    Translate
                `;
            }
        });
    }

    // Language switching
    if (englishBtn) {
        englishBtn.addEventListener('click', () => {
            const currentAnalysis = tabResults[activeTab];
            if (!currentAnalysis) return;
            
            englishBtn.classList.add('bg-blue-600', 'text-white');
            englishBtn.classList.remove('bg-gray-200', 'text-gray-700');
            banglaBtn.classList.add('bg-gray-200', 'text-gray-700');
            banglaBtn.classList.remove('bg-blue-600', 'text-white');
            englishContent.classList.remove('hidden');
            banglaContent.classList.add('hidden');
        });
    }

    if (banglaBtn) {
        banglaBtn.addEventListener('click', () => {
            const currentAnalysis = tabResults[activeTab];
            if (!currentAnalysis || !currentAnalysis.bangla) return;
            
            banglaBtn.classList.add('bg-blue-600', 'text-white');
            banglaBtn.classList.remove('bg-gray-200', 'text-gray-700');
            englishBtn.classList.add('bg-gray-200', 'text-gray-700');
            englishBtn.classList.remove('bg-blue-600', 'text-white');
            banglaContent.classList.remove('hidden');
            englishContent.classList.add('hidden');
        });
    }

    function showLoading(msg) {
        loading.classList.remove('hidden');
        result.classList.add('hidden');
        error.classList.add('hidden');
        const loadingTitle = loading.querySelector('p');
        if (loadingTitle) {
            loadingTitle.textContent = msg || 'Analyzing Medical Data with AI...';
        }
    }

    // State tracking for active patient and report context
    let currentPatientName = 'default_patient';
    let currentReportMarkdown = '';

    function handleResponse(data) {
        loading.classList.add('hidden');
        console.log('Handling response for active tab:', activeTab, data);
        
        if (data.success && data.analysis) {
            tabResults[activeTab] = data.analysis;
            if (data.analysis.patient_name) {
                currentPatientName = data.analysis.patient_name;
            }
            if (data.analysis.english) {
                currentReportMarkdown = data.analysis.english;
            }
            renderTabResult();
        } else {
            showError(data.error || 'An unexpected error occurred while processing.');
        }
    }

    function formatPatientFriendlyHTML(markdownText) {
        if (!markdownText) return '';
        let rawHtml = marked.parse(markdownText);

        // Highlight Overall Summary as a distinct patient-friendly card
        rawHtml = rawHtml.replace(
            /<h2>Overall Summary<\/h2>\s*([\s\S]*?)(?=<h2>|$)/gi,
            `<div class="overall-summary-card">
                <div class="flex items-center mb-2">
                    <span class="text-blue-700 font-bold text-base sm:text-lg flex items-center gap-2">
                        <svg class="w-5 h-5 inline-block text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 9 0 0118 0z"></path></svg>
                        Overall Summary
                    </span>
                </div>
                <div class="text-gray-800 text-xs sm:text-sm font-medium leading-relaxed">$1</div>
            </div>`
        );

        // Highlight Possible Health Finding as a distinct observation card
        rawHtml = rawHtml.replace(
            /<h2>Possible Health Finding<\/h2>\s*([\s\S]*?)(?=<h2>|$)/gi,
            `<div class="possible-finding-card">
                <div class="flex items-center mb-2">
                    <span class="text-amber-800 font-bold text-base sm:text-lg flex items-center gap-2">
                        <svg class="w-5 h-5 inline-block text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                        Possible Health Finding
                    </span>
                </div>
                <div class="text-gray-800 text-xs sm:text-sm font-medium leading-relaxed">$1</div>
            </div>`
        );

        // Highlight Possible Medication-Lab Safety Alert as a distinct high-visibility card
        rawHtml = rawHtml.replace(
            /<h2>Possible Medication[–\-]?Lab Safety Alert<\/h2>\s*([\s\S]*?)(?=<h2>|$)/gi,
            `<div class="safety-alert-card">
                <div class="flex items-center mb-2">
                    <span class="text-red-800 font-bold text-base sm:text-lg flex items-center gap-2">
                        <svg class="w-5 h-5 inline-block text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 9 0 0118 0z"></path></svg>
                        Possible Medication–Lab Safety Alert
                    </span>
                </div>
                <div class="text-gray-800 text-xs sm:text-sm font-medium leading-relaxed">$1</div>
            </div>`
        );

        // Wrap markdown tables in responsive scroll wrapper
        rawHtml = rawHtml.replace(
            /<table([\s\S]*?)<\/table>/gi,
            '<div class="table-responsive-wrapper"><table$1</table></div>'
        );

        return rawHtml;
    }

    function renderTabResult() {
        const currentAnalysis = tabResults[activeTab];
        if (!currentAnalysis || !currentAnalysis.english) {
            result.classList.add('hidden');
            return;
        }

        result.classList.remove('hidden');
        
        // Show English content
        try {
            englishContent.innerHTML = formatPatientFriendlyHTML(currentAnalysis.english);
        } catch (err) {
            console.error('Error parsing markdown:', err);
            englishContent.textContent = currentAnalysis.english;
        }

        // Translation toggle setup
        if (currentAnalysis.bangla) {
            banglaContent.innerHTML = formatPatientFriendlyHTML(currentAnalysis.bangla);
            banglaBtn.classList.remove('hidden');
        } else {
            banglaBtn.classList.add('hidden');
        }
        
        // Show English view by default
        englishContent.classList.remove('hidden');
        banglaContent.classList.add('hidden');
        
        // Update button states
        englishBtn.classList.add('bg-blue-600', 'text-white');
        englishBtn.classList.remove('bg-gray-200', 'text-gray-700');
    }

    // Patient Follow-up RAG Chatbot Integration & Toggle
    const toggleChatBtn = document.getElementById('toggle-chat-btn');
    const chatCollapsibleBody = document.getElementById('chat-collapsible-body');
    const chatChevron = document.getElementById('chat-chevron');
    const chatToggleLabel = document.getElementById('chat-toggle-label');
    const chatInput = document.getElementById('patient-chat-input');
    const chatSendBtn = document.getElementById('patient-chat-send-btn');
    const chatMessages = document.getElementById('chat-messages');

    if (toggleChatBtn && chatCollapsibleBody) {
        toggleChatBtn.addEventListener('click', () => {
            const isHidden = chatCollapsibleBody.classList.contains('hidden');
            if (isHidden) {
                chatCollapsibleBody.classList.remove('hidden');
                if (chatChevron) chatChevron.classList.add('transform', 'rotate-180');
                if (chatToggleLabel) chatToggleLabel.textContent = 'Collapse Chat';
                setTimeout(() => {
                    if (chatInput) chatInput.focus();
                }, 100);
            } else {
                chatCollapsibleBody.classList.add('hidden');
                if (chatChevron) chatChevron.classList.remove('transform', 'rotate-180');
                if (chatToggleLabel) chatToggleLabel.textContent = 'Open Chat';
            }
        });
    }

    if (chatSendBtn && chatInput && chatMessages) {
        async function handleSendQuery() {
            const query = chatInput.value.trim();
            if (!query) return;

            // Ensure collapsible body is open if closed
            if (chatCollapsibleBody && chatCollapsibleBody.classList.contains('hidden')) {
                chatCollapsibleBody.classList.remove('hidden');
                if (chatChevron) chatChevron.classList.add('transform', 'rotate-180');
                if (chatToggleLabel) chatToggleLabel.textContent = 'Collapse Chat';
            }

            // Append user message
            const userBubble = document.createElement('div');
            userBubble.className = 'chat-message-bubble chat-user';
            userBubble.textContent = query;
            chatMessages.appendChild(userBubble);
            chatInput.value = '';
            chatMessages.scrollTop = chatMessages.scrollHeight;

            // Append typing indicator
            const aiBubble = document.createElement('div');
            aiBubble.className = 'chat-message-bubble chat-ai';
            aiBubble.innerHTML = '<span class="inline-flex items-center gap-1.5"><span class="w-2 h-2 bg-blue-600 rounded-full animate-ping"></span> Retrieving & analyzing patient report context...</span>';
            chatMessages.appendChild(aiBubble);
            chatMessages.scrollTop = chatMessages.scrollHeight;

            try {
                const activeAnalysis = tabResults[activeTab];
                const reportContextToSend = (activeAnalysis && activeAnalysis.english) ? activeAnalysis.english : currentReportMarkdown;
                const patientIdToSend = (activeAnalysis && activeAnalysis.patient_name) ? activeAnalysis.patient_name : currentPatientName;

                const res = await fetch('/api/patient-chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        query: query,
                        patient_id: patientIdToSend,
                        report_context: reportContextToSend
                    })
                });
                const data = await res.json();
                if (data.success && data.response) {
                    aiBubble.innerHTML = marked.parse(data.response);
                } else {
                    aiBubble.textContent = data.error || "I could not retrieve an answer at this time. Please consult your physician.";
                }
            } catch (e) {
                console.error("Chat error:", e);
                aiBubble.textContent = "Network error while connecting to Patient Assistant AI.";
            }
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }

        chatSendBtn.addEventListener('click', handleSendQuery);
        chatInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') handleSendQuery();
        });
    }



    function handleError(err) {
        console.error('Error details:', err);
        loading.classList.add('hidden');
        showError('An error occurred while processing your request. Please try again.');
    }

    function showError(message) {
        error.classList.remove('hidden');
        result.classList.add('hidden');
        errorMessage.textContent = message;
    }
});