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
    const selectedFileContainer = document.getElementById('selected-file-container');
    const selectedFileLabel = document.getElementById('selected-file-label');
    const clearSelectedFileBtn = document.getElementById('clear-selected-file');
    const analyzePrescriptionBtn = document.getElementById('analyze-prescription-btn');
    let stagedPrescriptionFile = null;

    function stagePrescriptionFile(file) {
        if (!file) return;
        const allowedTypes = ['image/jpeg', 'image/png', 'application/pdf'];
        const ext = file.name.split('.').pop().toLowerCase();
        if (!allowedTypes.includes(file.type) && !['jpg', 'jpeg', 'png', 'pdf'].includes(ext)) {
            showError('Please upload a valid JPG, PNG, or PDF prescription document');
            return;
        }
        stagedPrescriptionFile = file;
        if (selectedFileContainer && selectedFileLabel) {
            const sizeKb = (file.size / 1024).toFixed(1);
            selectedFileLabel.textContent = `${file.name} (${sizeKb} KB) — Ready to analyze`;
            selectedFileContainer.classList.remove('hidden');
        }
    }

    function clearStagedPrescriptionFile() {
        stagedPrescriptionFile = null;
        if (prescriptionFileInput) prescriptionFileInput.value = '';
        if (selectedFileContainer && selectedFileLabel) {
            selectedFileLabel.textContent = 'No file selected';
            selectedFileContainer.classList.add('hidden');
        }
    }

    if (clearSelectedFileBtn) {
        clearSelectedFileBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            clearStagedPrescriptionFile();
        });
    }

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
            stagePrescriptionFile(file);
        });

        prescriptionDropZone.addEventListener('click', (e) => {
            if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'BUTTON') {
                prescriptionFileInput.click();
            }
        });

        prescriptionFileInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            stagePrescriptionFile(file);
        });
    }

    if (analyzePrescriptionBtn) {
        analyzePrescriptionBtn.addEventListener('click', (e) => {
            e.preventDefault();
            if (!stagedPrescriptionFile) {
                showError('Please select or browse a prescription file first.');
                if (prescriptionFileInput) prescriptionFileInput.click();
                return;
            }
            handlePrescriptionFile(stagedPrescriptionFile);
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

        const labAnalyteEl = document.getElementById('lab-analyte');
        const labValueEl = document.getElementById('lab-value');
        const labUnitEl = document.getElementById('lab-unit');
        const labTimingEl = document.getElementById('lab-timing');
        if (labAnalyteEl && labAnalyteEl.value.trim()) {
            formData.append('current_lab_analyte', labAnalyteEl.value.trim());
            if (labValueEl && labValueEl.value.trim()) {
                formData.append('current_lab_value', labValueEl.value.trim());
            }
            if (labUnitEl && labUnitEl.value.trim()) {
                formData.append('current_lab_unit', labUnitEl.value.trim());
            }
            if (labTimingEl && labTimingEl.value) {
                formData.append('current_lab_timing', labTimingEl.value);
            }
        }

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

    // PDF Report Export: server-generated PDF, saved directly (no print dialog).
    const downloadPdfBtn = document.getElementById('download-pdf-btn');
    if (downloadPdfBtn) {
        downloadPdfBtn.addEventListener('click', async () => {
            const currentAnalysis = tabResults[activeTab];
            if (!currentAnalysis || !currentAnalysis.english) {
                showError('No generated analysis results available to download.');
                return;
            }

            const prefixes = { medicine: 'Prescription_Analysis', report: 'Lab_Report_Analysis', symptoms: 'Symptom_Analysis' };
            const now = new Date();
            const pad = n => String(n).padStart(2, '0');
            const dateStr = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
            const filename = `${prefixes[activeTab] || 'Analysis'}_${dateStr}.pdf`;

            const originalLabel = downloadPdfBtn.innerHTML;
            downloadPdfBtn.disabled = true;
            try {
                // Only the analysis markdown is sent: buttons, language
                // dropdowns and the chatbot are never part of the export.
                const response = await fetch('/export-pdf', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ markdown: currentAnalysis.english, kind: activeTab })
                });

                const contentType = (response.headers.get('Content-Type') || '').toLowerCase();
                if (!response.ok || !contentType.includes('application/pdf')) {
                    let message = 'Failed to generate PDF. Please try again.';
                    try {
                        const errBody = await response.json();
                        if (errBody && errBody.error) message = errBody.error;
                    } catch (_) { /* non-JSON error body: keep generic message */ }
                    showError(message);   // never save a failed response as a PDF
                    return;
                }

                const blob = await response.blob();
                const pdfBlob = new Blob([blob], { type: 'application/pdf' });
                const url = URL.createObjectURL(pdfBlob);
                const link = document.createElement('a');
                link.style.display = 'none';
                link.href = url;
                link.setAttribute('download', filename);
                link.download = filename; // explicit filename, ends in .pdf
                document.body.appendChild(link);
                link.click();
                setTimeout(() => {
                    if (link.parentNode) {
                        link.parentNode.removeChild(link);
                    }
                    URL.revokeObjectURL(url);
                }, 30000);
            } catch (err) {
                console.error('PDF download error:', err);
                showError('Failed to download PDF. Please check your connection and try again.');
            } finally {
                downloadPdfBtn.disabled = false;
                downloadPdfBtn.innerHTML = originalLabel;
            }
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
        if (typeof onAnalysisStarted === 'function') {
            onAnalysisStarted();
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
            if (typeof onAnalysisSucceeded === 'function') {
                onAnalysisSucceeded(data);
            }
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

        // Make Technical Details and Evidence section collapsible on screen
        rawHtml = rawHtml.replace(
            /(?:<hr>\s*)?<h2>(?:🔬\s*)?Technical Details and Evidence<\/h2>\s*([\s\S]*)$/i,
            `<details class="technical-details-card mt-8 border border-gray-200 rounded-xl p-4 bg-gray-50/70 shadow-sm" open>
                <summary class="cursor-pointer font-bold text-lg text-blue-900 flex items-center justify-between py-1 select-none">
                    <span class="flex items-center gap-2">
                        <svg class="w-5 h-5 text-blue-600 inline-block" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
                        🔬 Technical Details and Evidence
                    </span>
                    <span class="text-xs text-blue-600 font-medium hover:underline bg-blue-50 px-2.5 py-1 rounded-md border border-blue-200">
                        Click to collapse/expand
                    </span>
                </summary>
                <div class="mt-4 pt-4 border-t border-gray-200">
                    $1
                </div>
            </details>`
        );

        // === Status Badge Post-Processing ===
        // Convert emoji+status text in <td> cells into styled pill badges

        // Clinical status badges
        rawHtml = rawHtml.replace(/🟢\s*NORMAL/g,
            '<span class="status-badge status-normal">✓ Normal</span>');
        rawHtml = rawHtml.replace(/🔴\s*HIGH/g,
            '<span class="status-badge status-high">↑ High</span>');
        rawHtml = rawHtml.replace(/🔵\s*LOW/g,
            '<span class="status-badge status-low">↓ Low</span>');
        rawHtml = rawHtml.replace(/🟡\s*BORDERLINE/g,
            '<span class="status-badge status-borderline">~ Borderline</span>');
        rawHtml = rawHtml.replace(/⚠️\s*BORDERLINE/g,
            '<span class="status-badge status-borderline">⚠ Borderline</span>');
        rawHtml = rawHtml.replace(/🟠\s*CRITICAL/g,
            '<span class="status-badge status-critical">!! Critical</span>');
        rawHtml = rawHtml.replace(/❌\s*CRITICAL/g,
            '<span class="status-badge status-critical">!! Critical</span>');
        rawHtml = rawHtml.replace(/❓\s*UNKNOWN/g,
            '<span class="status-badge status-unknown">? Unknown</span>');

        // Validation status badges
        rawHtml = rawHtml.replace(/🟢\s*VALIDATED/g,
            '<span class="status-badge status-validated">✓ Validated</span>');
        rawHtml = rawHtml.replace(/🔴\s*INVALID/g,
            '<span class="status-badge status-invalid">✗ Invalid</span>');
        rawHtml = rawHtml.replace(/🟡\s*NEEDS REVIEW/g,
            '<span class="status-badge status-borderline">⚠ Review</span>');

        // Rule ID code chips — wrap REPORT_INLINE_* or any all-caps_underscored token in <td>
        rawHtml = rawHtml.replace(
            /(<td[^>]*>)\s*([A-Z][A-Z0-9_]{5,})\s*(<\/td>)/g,
            '$1<code class="rule-id-chip">$2</code>$3'
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

    // === Floating Action Button (FAB) RAG Chatbot Lifecycle & State ===
    const toggleChatBtn  = document.getElementById('toggle-chat-btn');
    const chatPopup      = document.getElementById('chat-popup');
    const chatCloseBtn   = document.getElementById('chat-close-btn');
    const chatFabIconOpen  = document.getElementById('chat-fab-icon-open');
    const chatFabIconClose = document.getElementById('chat-fab-icon-close');
    const chatFabBadge   = document.getElementById('chat-fab-badge');
    const chatInput      = document.getElementById('chat-input');
    const chatSendBtn    = document.getElementById('send-chat-btn');
    const chatMessages   = document.getElementById('chat-history');
    const chatSubtitle   = document.getElementById('chat-fab-subtitle');

    let clientAnalysisGeneration = 0;
    let activeAnalysisVersion = 0;
    let isAnalysisPending = false;

    function onAnalysisStarted() {
        clientAnalysisGeneration++;
        isAnalysisPending = true;
        activeAnalysisVersion = 0;
        if (chatInput) chatInput.disabled = true;
        if (chatSendBtn) chatSendBtn.disabled = true;
        if (chatMessages) {
            chatMessages.textContent = '';
            const pendingNotice = document.createElement('div');
            pendingNotice.className = 'bg-amber-50 border border-amber-200 text-amber-800 rounded-2xl px-4 py-2.5 max-w-[85%] text-xs shadow-sm font-medium';
            pendingNotice.textContent = 'A new analysis is processing. Prior context has been retired. Chat will be enabled once analysis completes.';
            chatMessages.appendChild(pendingNotice);
        }
    }

    function onAnalysisSucceeded(data) {
        isAnalysisPending = false;
        if (data && typeof data.analysis_version === 'number') {
            activeAnalysisVersion = data.analysis_version;
        }
        if (chatInput) chatInput.disabled = false;
        if (chatSendBtn) chatSendBtn.disabled = false;
        if (chatMessages) {
            chatMessages.textContent = '';
            const readyNotice = document.createElement('div');
            readyNotice.className = 'bg-blue-50 border border-blue-100 text-blue-800 rounded-2xl px-4 py-2.5 max-w-[85%] text-xs shadow-sm font-medium';
            readyNotice.textContent = 'Analysis loaded (v' + (activeAnalysisVersion || 1) + '). You can ask questions about the current report findings and recommendations above.';
            chatMessages.appendChild(readyNotice);
        }
    }

    function onAnalysisFailed(reason) {
        isAnalysisPending = false;
        activeAnalysisVersion = 0;
        if (chatInput) chatInput.disabled = true;
        if (chatSendBtn) chatSendBtn.disabled = true;
        if (chatMessages) {
            chatMessages.textContent = '';
            const failNotice = document.createElement('div');
            failNotice.className = 'bg-red-50 border border-red-200 text-red-800 rounded-2xl px-4 py-2.5 max-w-[85%] text-xs shadow-sm font-medium';
            failNotice.textContent = reason || 'No current analysis is available. The previous analysis was retired, and the new analysis failed or was invalid.';
            chatMessages.appendChild(failNotice);
        }
    }

    function resetChatPanel() {
        onAnalysisStarted();
    }

    // Context config for each tab
    const chatContextConfig = {
        report: {
            subtitle: 'Lab Report Grounded AI',
            placeholder: 'Ask about your lab results, diet, normal ranges...',
            typingMsg: 'Analyzing your lab report context...'
        },
        medicine: {
            subtitle: 'Prescription Pharmacist AI',
            placeholder: 'Ask about your medications, side effects, interactions...',
            typingMsg: 'Analyzing your prescription context...'
        },
        symptoms: {
            subtitle: 'Symptom Triage AI',
            placeholder: 'Ask about your symptoms, urgency, or next steps...',
            typingMsg: 'Analyzing your symptom context...'
        }
    };

    function updateChatContext() {
        const cfg = chatContextConfig[activeTab] || chatContextConfig.report;
        if (chatInput)    chatInput.placeholder = cfg.placeholder;
        if (chatSubtitle) chatSubtitle.textContent = cfg.subtitle;
    }

    function openChatPopup() {
        if (!chatPopup) return;
        chatPopup.classList.remove('hidden');
        if (chatFabIconOpen)  chatFabIconOpen.classList.add('hidden');
        if (chatFabIconClose) chatFabIconClose.classList.remove('hidden');
        if (chatFabBadge)     chatFabBadge.style.display = 'none';
        updateChatContext();
        setTimeout(() => { if (chatInput && !chatInput.disabled) chatInput.focus(); }, 120);
    }

    function closeChatPopup() {
        if (!chatPopup) return;
        chatPopup.classList.add('hidden');
        if (chatFabIconOpen)  chatFabIconOpen.classList.remove('hidden');
        if (chatFabIconClose) chatFabIconClose.classList.add('hidden');
    }

    if (toggleChatBtn) {
        toggleChatBtn.addEventListener('click', () => {
            const isOpen = !chatPopup.classList.contains('hidden');
            isOpen ? closeChatPopup() : openChatPopup();
        });
    }

    if (chatCloseBtn) {
        chatCloseBtn.addEventListener('click', closeChatPopup);
    }

    if (chatSendBtn && chatInput && chatMessages) {
        async function handleSendQuery() {
            const query = chatInput.value.trim();
            if (!query) return;

            if (isAnalysisPending) {
                const bubble = document.createElement('div');
                bubble.className = 'bg-amber-50 border border-amber-200 text-amber-800 rounded-2xl px-4 py-2.5 max-w-[85%] text-xs shadow-sm font-medium';
                bubble.textContent = 'Analysis is still in progress. Please wait until results are ready before asking questions.';
                chatMessages.appendChild(bubble);
                chatMessages.scrollTop = chatMessages.scrollHeight;
                return;
            }

            openChatPopup();

            const thisGen = clientAnalysisGeneration;
            const thisVer = activeAnalysisVersion;

            const userBubble = document.createElement('div');
            userBubble.className = 'ml-auto bg-blue-600 text-white rounded-2xl px-4 py-2.5 max-w-[85%] text-xs shadow-sm whitespace-pre-wrap';
            userBubble.textContent = query;
            chatMessages.appendChild(userBubble);
            chatInput.value = '';
            chatMessages.scrollTop = chatMessages.scrollHeight;

            const aiBubble = document.createElement('div');
            aiBubble.className = 'bg-white border border-gray-200 text-gray-800 rounded-2xl px-4 py-2.5 max-w-[85%] text-xs shadow-sm whitespace-pre-wrap';
            aiBubble.textContent = 'Analyzing current report context...';
            chatMessages.appendChild(aiBubble);
            chatMessages.scrollTop = chatMessages.scrollHeight;

            try {
                const res = await fetch('/api/patient-chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        query: query,
                        analysis_version: thisVer
                    })
                });
                const data = await res.json();

                // If user started a new analysis while this request was in flight, ignore stale reply
                if (thisGen !== clientAnalysisGeneration) {
                    aiBubble.remove();
                    return;
                }

                if (data.success && data.response) {
                    aiBubble.textContent = data.response;
                } else if (data.source === 'pending') {
                    aiBubble.textContent = 'Analysis is still in progress. Please wait for completion.';
                } else if (data.source === 'unavailable' || data.source === 'failed' || data.source === 'expired') {
                    aiBubble.textContent = data.error || 'No active analysis available. Please upload or analyze a new report.';
                } else {
                    aiBubble.textContent = data.error || "I could not retrieve an answer at this time. Please consult your physician.";
                }
            } catch (e) {
                if (thisGen !== clientAnalysisGeneration) {
                    aiBubble.remove();
                    return;
                }
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

    // Update chat context dynamically when user switches tabs (without falsely clearing or resetting context)
    [reportTab, symptomsTab, medicineTab].forEach(btn => {
        if (btn) btn.addEventListener('click', () => setTimeout(updateChatContext, 50));
    });

    // =========================================================================
    // Patient Records Dashboard Management
    // =========================================================================
    const openDashboardBtn = document.getElementById('open-dashboard-btn');
    const closeDashboardBtn = document.getElementById('close-dashboard-btn');
    const closeDashboardBtn2 = document.getElementById('close-dashboard-btn2');
    const dashboardModal = document.getElementById('patient-dashboard-modal');

    // Dashboard Sub-Tabs
    const dashTabMeds = document.getElementById('dash-tab-meds');
    const dashTabDiscontinued = document.getElementById('dash-tab-discontinued');
    const dashTabPrescriptions = document.getElementById('dash-tab-prescriptions');
    const dashTabLabs = document.getElementById('dash-tab-labs');
    const dashTabDdi = document.getElementById('dash-tab-ddi');

    const dashSecMeds = document.getElementById('dash-sec-meds');
    const dashSecDiscontinued = document.getElementById('dash-sec-discontinued');
    const dashSecPrescriptions = document.getElementById('dash-sec-prescriptions');
    const dashSecLabs = document.getElementById('dash-sec-labs');
    const dashSecDdi = document.getElementById('dash-sec-ddi');

    function switchDashTab(activeBtn, activeSec) {
        [dashTabMeds, dashTabDiscontinued, dashTabPrescriptions, dashTabLabs, dashTabDdi].forEach(btn => {
            if (btn) {
                btn.className = "py-3 text-gray-500 hover:text-blue-600 font-semibold";
            }
        });
        if (activeBtn) {
            activeBtn.className = "py-3 border-b-2 border-blue-600 text-blue-600 font-semibold";
        }
        [dashSecMeds, dashSecDiscontinued, dashSecPrescriptions, dashSecLabs, dashSecDdi].forEach(sec => {
            if (sec) sec.classList.add('hidden');
        });
        if (activeSec) {
            activeSec.classList.remove('hidden');
        }
    }

    if (dashTabMeds) dashTabMeds.addEventListener('click', () => switchDashTab(dashTabMeds, dashSecMeds));
    if (dashTabDiscontinued) dashTabDiscontinued.addEventListener('click', () => switchDashTab(dashTabDiscontinued, dashSecDiscontinued));
    if (dashTabPrescriptions) dashTabPrescriptions.addEventListener('click', () => switchDashTab(dashTabPrescriptions, dashSecPrescriptions));
    if (dashTabLabs) dashTabLabs.addEventListener('click', () => switchDashTab(dashTabLabs, dashSecLabs));
    if (dashTabDdi) dashTabDdi.addEventListener('click', () => switchDashTab(dashTabDdi, dashSecDdi));

    function loadPatientDashboard() {
        fetch('/api/patient/dashboard')
            .then(res => res.json())
            .then(data => {
                if (!data.success) {
                    console.warn("Failed to load dashboard data:", data.error);
                    return;
                }
                const dash = data.dashboard || {};
                const profile = dash.profile || {};
                
                // Populate profile
                const pNameEl = document.getElementById('dash-patient-name');
                if (pNameEl) pNameEl.textContent = profile.patient_name || 'Patient Records';
                const pEmailEl = document.getElementById('dash-email');
                if (pEmailEl) pEmailEl.textContent = profile.email || 'N/A';
                const pAgeEl = document.getElementById('dash-age');
                if (pAgeEl) pAgeEl.textContent = profile.age ? `${profile.age} yrs` : 'Not specified';
                const pGenEl = document.getElementById('dash-gender');
                if (pGenEl) pGenEl.textContent = profile.gender || 'Not specified';
                const pSlugEl = document.getElementById('dash-slug');
                if (pSlugEl) pSlugEl.textContent = `ID: ${profile.slug || '-'}`;

                // Populate Active Medications
                const activeBody = document.getElementById('dash-active-meds-body');
                if (activeBody) {
                    const activeMeds = dash.active_medications || [];
                    if (activeMeds.length === 0) {
                        activeBody.innerHTML = '<tr><td colspan="5" class="px-3 py-4 text-center text-gray-400">No active medications currently recorded.</td></tr>';
                    } else {
                        activeBody.innerHTML = activeMeds.map(m => `
                            <tr class="hover:bg-gray-50">
                                <td class="px-3 py-2.5 font-bold text-gray-900">${m.medicine_name || m.name}</td>
                                <td class="px-3 py-2.5 text-gray-600">${m.strength || m.dosage || '–'}</td>
                                <td class="px-3 py-2.5"><span class="px-2 py-0.5 bg-blue-50 text-blue-700 rounded font-medium text-[11px]">${m.med_class || 'Unclassified'}</span></td>
                                <td class="px-3 py-2.5 text-gray-500">${(m.added_at || '').substring(0, 10)}</td>
                                <td class="px-3 py-2.5 text-right">
                                    <button onclick="toggleMedStatus('${m.id || m.medicine_name}', 'discontinued')" class="px-2.5 py-1 text-[11px] font-semibold text-red-600 hover:text-red-800 bg-red-50 hover:bg-red-100 rounded border border-red-200 transition-colors">
                                        Discontinue
                                    </button>
                                </td>
                            </tr>
                        `).join('');
                    }
                }

                // Populate Discontinued Medications
                const disBody = document.getElementById('dash-discontinued-meds-body');
                if (disBody) {
                    const disMeds = dash.discontinued_medications || [];
                    if (disMeds.length === 0) {
                        disBody.innerHTML = '<tr><td colspan="5" class="px-3 py-4 text-center text-gray-400">No discontinued medications recorded.</td></tr>';
                    } else {
                        disBody.innerHTML = disMeds.map(m => `
                            <tr class="hover:bg-gray-50">
                                <td class="px-3 py-2.5 font-bold text-gray-700 line-through">${m.medicine_name || m.name}</td>
                                <td class="px-3 py-2.5 text-gray-500">${m.strength || m.dosage || '–'}</td>
                                <td class="px-3 py-2.5 text-gray-500 text-[11px]">${m.med_class || 'Unclassified'}</td>
                                <td class="px-3 py-2.5 text-gray-400"><span class="px-2 py-0.5 bg-gray-100 text-gray-600 rounded text-[11px]">Discontinued</span></td>
                                <td class="px-3 py-2.5 text-right">
                                    <button onclick="toggleMedStatus('${m.id || m.medicine_name}', 'active')" class="px-2.5 py-1 text-[11px] font-semibold text-green-700 hover:text-green-900 bg-green-50 hover:bg-green-100 rounded border border-green-200 transition-colors">
                                        Reactivate
                                    </button>
                                </td>
                            </tr>
                        `).join('');
                    }
                }

                // Populate Prescriptions
                const rxList = document.getElementById('dash-prescriptions-list');
                if (rxList) {
                    const rxs = dash.prescriptions || [];
                    if (rxs.length === 0) {
                        rxList.innerHTML = '<p class="text-xs text-gray-400 text-center py-4">No uploaded prescriptions found.</p>';
                    } else {
                        rxList.innerHTML = rxs.map(rx => `
                            <div class="p-3.5 bg-gray-50 rounded-xl border border-gray-200 text-xs space-y-1.5">
                                <div class="flex justify-between items-center">
                                    <span class="font-bold text-gray-900">Prescription #${rx.id || rx.visit_id} • ${(rx.timestamp || '').substring(0, 10)}</span>
                                    <span class="px-2 py-0.5 bg-green-100 text-green-800 rounded text-[10px] font-semibold">${rx.verification_status || 'VERIFIED'}</span>
                                </div>
                                <p class="text-gray-700"><strong>Summary:</strong> ${rx.medicine_name || 'Prescription items'}</p>
                                ${rx.medicines && rx.medicines.length ? `
                                    <div class="mt-1 pt-1 border-t border-gray-200 flex flex-wrap gap-1">
                                        ${rx.medicines.map(m => `<span class="px-2 py-0.5 bg-white border border-gray-200 rounded text-[11px] font-medium text-gray-800">${m.medicine_name} ${m.strength || ''}</span>`).join('')}
                                    </div>
                                ` : ''}
                            </div>
                        `).join('');
                    }
                }

                // Populate Labs
                const labsBody = document.getElementById('dash-labs-body');
                if (labsBody) {
                    const labs = dash.lab_results || [];
                    if (labs.length === 0) {
                        labsBody.innerHTML = '<tr><td colspan="5" class="px-3 py-4 text-center text-gray-400">No laboratory measurements recorded yet.</td></tr>';
                    } else {
                        labsBody.innerHTML = labs.map(l => {
                            const isAbn = ['HIGH', 'VERY_HIGH', 'LOW', 'POSITIVE'].includes((l.status || '').toUpperCase());
                            const badgeClass = isAbn ? 'bg-red-100 text-red-800' : 'bg-green-100 text-green-800';
                            return `
                                <tr class="hover:bg-gray-50">
                                    <td class="px-3 py-2 font-semibold text-gray-800">${l.parameter}</td>
                                    <td class="px-3 py-2 font-mono font-bold">${l.value}</td>
                                    <td class="px-3 py-2 text-gray-500">${l.unit || '–'}</td>
                                    <td class="px-3 py-2"><span class="px-2 py-0.5 rounded text-[10px] font-bold ${badgeClass}">${l.status}</span></td>
                                    <td class="px-3 py-2 text-gray-400">${(l.evaluated_at || '').substring(0, 10)}</td>
                                </tr>
                            `;
                        }).join('');
                    }
                }

                // Populate DDI History Table
                const ddiBody = document.getElementById('dash-ddi-body');
                if (ddiBody) {
                    const ddis = dash.ddi_history || [];
                    if (ddis.length === 0) {
                        ddiBody.innerHTML = '<tr><td colspan="5" class="px-3 py-4 text-center text-gray-400">No interaction records found.</td></tr>';
                    } else {
                        ddiBody.innerHTML = ddis.map(d => {
                            const sev = (d.severity || '').toUpperCase();
                            const sevClass = (sev === 'CRITICAL' || sev === 'MAJOR') ? 'bg-red-100 text-red-800' : (sev === 'MODERATE' ? 'bg-yellow-100 text-yellow-800' : 'bg-blue-100 text-blue-800');
                            return `
                                <tr class="hover:bg-gray-50">
                                    <td class="px-3 py-2.5 font-bold text-gray-900">${d.medicine_a}</td>
                                    <td class="px-3 py-2.5 font-bold text-gray-900">${d.medicine_b}</td>
                                    <td class="px-3 py-2.5 text-gray-600 font-mono text-[10px]">${d.source_a || 'NEW'} ↔ ${d.source_b || 'HIST'}</td>
                                    <td class="px-3 py-2.5"><span class="px-2 py-0.5 rounded text-[10px] font-bold ${sevClass}">${d.severity}</span></td>
                                    <td class="px-3 py-2.5 text-gray-600 text-[11px] max-w-xs">${d.interaction_description || '–'}</td>
                                </tr>
                            `;
                        }).join('');
                    }
                }
            })
            .catch(err => console.error("Error loading patient dashboard:", err));
    }

    window.toggleMedStatus = function(medId, newStatus) {
        fetch('/api/patient/toggle-medication', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ medication_id: medId, status: newStatus })
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                loadPatientDashboard();
            } else {
                alert('Could not update medication status: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(err => console.error('Error toggling medication:', err));
    };

    window.confirmPrescriptionMed = function(name, dosage, genericName, strength) {
        fetch('/api/patient/confirm-prescribed-medication', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ medicine_name: name, dosage: dosage, generic_name: genericName, strength: strength })
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                alert(`Medication '${name}' confirmed and saved to your active medications!`);
                loadPatientDashboard();
            } else {
                alert('Could not add medication: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(err => console.error('Error confirming medication:', err));
    };

    if (openDashboardBtn && dashboardModal) {
        openDashboardBtn.addEventListener('click', () => {
            dashboardModal.classList.remove('hidden');
            loadPatientDashboard();
        });
    }

    if (closeDashboardBtn && dashboardModal) {
        closeDashboardBtn.addEventListener('click', () => dashboardModal.classList.add('hidden'));
    }

    if (closeDashboardBtn2 && dashboardModal) {
        closeDashboardBtn2.addEventListener('click', () => dashboardModal.classList.add('hidden'));
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
        if (isAnalysisPending) {
            onAnalysisFailed('Analysis failed: ' + message);
        }
    }
});
