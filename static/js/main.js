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

        // Update tab button styles
        reportTab.classList.remove('text-blue-600', 'border-b-2', 'border-blue-600');
        symptomsTab.classList.remove('text-blue-600', 'border-b-2', 'border-blue-600');
        medicineTab.classList.remove('text-blue-600', 'border-b-2', 'border-blue-600');
        reportTab.classList.add('text-gray-500');
        symptomsTab.classList.add('text-gray-500');
        medicineTab.classList.add('text-gray-500');

        reportSection.classList.add('hidden');
        symptomsSection.classList.add('hidden');
        medicineSection.classList.add('hidden');

        if (tabName === 'report') {
            reportTab.classList.add('text-blue-600', 'border-b-2', 'border-blue-600');
            reportTab.classList.remove('text-gray-500');
            reportSection.classList.remove('hidden');
        } else if (tabName === 'symptoms') {
            symptomsTab.classList.add('text-blue-600', 'border-b-2', 'border-blue-600');
            symptomsTab.classList.remove('text-gray-500');
            symptomsSection.classList.remove('hidden');
        } else if (tabName === 'medicine') {
            medicineTab.classList.add('text-blue-600', 'border-b-2', 'border-blue-600');
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
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('border-blue-500');
    });

    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('border-blue-500');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('border-blue-500');
        const file = e.dataTransfer.files[0];
        handleFile(file);
    });

    dropZone.addEventListener('click', () => {
        fileInput.click();
    });

    fileInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        handleFile(file);
    });

    function handleFile(file) {
        if (!file) return;

        // Check file type
        const allowedTypes = ['image/jpeg', 'image/png', 'application/pdf'];
        if (!allowedTypes.includes(file.type)) {
            showError('Please upload a JPG, PNG, or PDF file');
            return;
        }

        const formData = new FormData();
        formData.append('file', file);

        showLoading();
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
                showError('Please paste your medical report text');
                return;
            }

            showLoading();
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

    analyzeButton.addEventListener('click', () => {
        const symptoms = symptomsInput.value.trim();
        if (!symptoms) {
            showError('Please describe your symptoms');
            return;
        }

        showLoading();
        console.log('Analyzing symptoms');

        fetch('/analyze-symptoms', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ symptoms: symptoms })
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
    });

    // Medicine analysis functionality
    const medicineName = document.getElementById('medicine-name');
    const dosageMorning = document.getElementById('dosage-morning');
    const dosageEvening = document.getElementById('dosage-evening');
    const dosageNight = document.getElementById('dosage-night');
    const patientAge = document.getElementById('patient-age');
    const patientGender = document.getElementById('patient-gender');
    const analyzeMedicineBtn = document.getElementById('analyze-medicine');

    analyzeMedicineBtn.addEventListener('click', () => {
        const medicine = medicineName.value.trim();
        const age = patientAge.value.trim();
        const gender = patientGender.value;

        // Validate inputs
        if (!medicine) {
            showError('Please enter a medicine name');
            return;
        }

        if (!age) {
            showError('Please enter patient age');
            return;
        }

        if (!gender) {
            showError('Please select patient gender');
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

        showLoading();
        console.log('Analyzing medicine:', { medicine, age, gender, dosage });

        fetch('/analyze-medicine', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                medicine: medicine,
                dosage: dosage,
                patient: {
                    age: parseInt(age),
                    gender: gender
                }
            })
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
    });

    // Prescription File Upload functionality (Option A in Medicine Info)
    const prescriptionDropZone = document.getElementById('prescription-drop-zone');
    const prescriptionFileInput = document.getElementById('prescription-file-input');

    if (prescriptionDropZone && prescriptionFileInput) {
        prescriptionDropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            prescriptionDropZone.classList.add('border-blue-500', 'bg-blue-100');
        });

        prescriptionDropZone.addEventListener('dragleave', () => {
            prescriptionDropZone.classList.remove('border-blue-500', 'bg-blue-100');
        });

        prescriptionDropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            prescriptionDropZone.classList.remove('border-blue-500', 'bg-blue-100');
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
        if (!allowedTypes.includes(file.type)) {
            showError('Please upload a JPG, PNG, or PDF prescription file');
            return;
        }

        const formData = new FormData();
        formData.append('file', file);

        const age = patientAge ? patientAge.value.trim() : '';
        const gender = patientGender ? patientGender.value : '';
        if (age) formData.append('age', age);
        if (gender) formData.append('gender', gender);

        showLoading('Analyzing Prescription Document with AI...');
        console.log('Uploading prescription file:', file.name);

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

    // PDF Report Download functionality
    const downloadPdfBtn = document.getElementById('download-pdf-btn');
    if (downloadPdfBtn) {
        downloadPdfBtn.addEventListener('click', () => {
            const currentAnalysis = tabResults[activeTab];
            if (!currentAnalysis || !currentAnalysis.english) {
                showError('No generated analysis results available to download.');
                return;
            }

            const resultElement = document.getElementById('result');
            const actionBar = resultElement.querySelector('.flex.space-x-2');

            // 1. Hide action buttons during capture
            if (actionBar) actionBar.style.display = 'none';

            // 2. Inject PDF Header at top of resultElement
            const headerBanner = document.createElement('div');
            headerBanner.id = 'pdf-inline-header';
            headerBanner.style.borderBottom = '2px solid #2563eb';
            headerBanner.style.paddingBottom = '12px';
            headerBanner.style.marginBottom = '20px';
            headerBanner.style.paddingTop = '10px';
            headerBanner.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <h1 style="color: #1d4ed8; font-size: 24px; font-weight: bold; margin: 0;">Medical Report Analyzer</h1>
                        <div style="color: #2563eb; font-size: 11px; font-weight: 700; text-transform: uppercase; margin-top: 2px;">
                            Official Clinical AI Summary & Health Guidance Report
                        </div>
                    </div>
                    <div style="text-align: right;">
                        <span style="background-color: #eff6ff; color: #1d4ed8; padding: 4px 10px; border-radius: 12px; font-size: 10px; font-weight: 700; border: 1px solid #bfdbfe;">
                            NVIDIA NIM / RapidOCR Active
                        </span>
                        <div style="color: #6b7280; font-size: 10px; margin-top: 4px;">
                            Generated Date: ${new Date().toLocaleDateString()} ${new Date().toLocaleTimeString()}
                        </div>
                    </div>
                </div>
            `;

            // 3. Inject PDF Footer at bottom of resultElement
            const footerBanner = document.createElement('div');
            footerBanner.id = 'pdf-inline-footer';
            footerBanner.style.borderTop = '2px solid #e5e7eb';
            footerBanner.style.paddingTop = '12px';
            footerBanner.style.marginTop = '25px';
            footerBanner.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: center; font-size: 10px; color: #4b5563; margin-bottom: 8px;">
                    <div><strong>Engine:</strong> Python 3.13 • Flask • Llama 3.1 8B • RapidOCR</div>
                    <div><strong>Module:</strong> ${activeTab.toUpperCase()} ANALYSIS</div>
                </div>
                <div style="font-size: 9.5px; color: #6b7280; text-align: center; line-height: 1.5; background: #f9fafb; padding: 8px; border-radius: 6px; border: 1px solid #f3f4f6;">
                    <strong>Medical Disclaimer:</strong> This document is an AI-assisted analytical clinical report intended strictly for educational and informational purposes. Always consult a certified physician for medical diagnosis.
                    <br>
                    <span style="color: #9ca3af;">© 2026 Medical Report Analyzer AI System • Agentic Architecture v2.0 • All Rights Reserved</span>
                </div>
            `;

            resultElement.insertBefore(headerBanner, resultElement.firstChild);
            resultElement.appendChild(footerBanner);

            const options = {
                margin:       [0.4, 0.4, 0.4, 0.4],
                filename:     `Medical_Report_Analysis_${Date.now()}.pdf`,
                image:        { type: 'jpeg', quality: 0.98 },
                html2canvas:  { scale: 2, useCORS: true, scrollX: 0, scrollY: 0 },
                jsPDF:        { unit: 'in', format: 'letter', orientation: 'portrait' }
            };

            html2pdf().set(options).from(resultElement).save().then(() => {
                if (document.getElementById('pdf-inline-header')) headerBanner.remove();
                if (document.getElementById('pdf-inline-footer')) footerBanner.remove();
                if (actionBar) actionBar.style.display = 'flex';
            }).catch(err => {
                console.error("PDF generation error:", err);
                if (document.getElementById('pdf-inline-header')) headerBanner.remove();
                if (document.getElementById('pdf-inline-footer')) footerBanner.remove();
                if (actionBar) actionBar.style.display = 'flex';
                showError('Failed to generate PDF. Please try again.');
            });
        });
    }

    // Translation handling
    const languageSelect = document.getElementById('language-select');
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
            <svg class="animate-spin -ml-1 mr-1.5 h-3.5 w-3.5 text-white inline" fill="none" viewBox="0 0 24 24">
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
                // Store the translation for current tab
                currentAnalysis.bangla = data.translation;
                
                // Update the Translated content container
                try {
                    banglaContent.innerHTML = marked.parse(data.translation);
                } catch (err) {
                    console.error('Error parsing markdown:', err);
                    banglaContent.textContent = data.translation;
                }

                // Show Translated view button with target language name
                banglaBtn.textContent = `${selectedLanguage}`;
                banglaBtn.classList.remove('hidden');
                
                // Trigger Translated view
                banglaBtn.click();
            } else {
                showError(data.error || 'Translation failed');
            }
        } catch (err) {
            console.error('Translation error:', err);
            showError('Failed to translate content');
        } finally {
            // Reset button state
            translateBtn.disabled = false;
            translateBtn.innerHTML = `
                <svg class="w-3.5 h-3.5 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129"></path></svg>
                Translate
            `;
        }
    });

    // Language switching
    englishBtn.addEventListener('click', () => {
        const currentAnalysis = tabResults[activeTab];
        if (!currentAnalysis) return;
        
        englishBtn.classList.add('bg-blue-500', 'text-white');
        englishBtn.classList.remove('bg-gray-200', 'text-gray-700');
        banglaBtn.classList.add('bg-gray-200', 'text-gray-700');
        banglaBtn.classList.remove('bg-blue-500', 'text-white');
        englishContent.classList.remove('hidden');
        banglaContent.classList.add('hidden');
    });

    banglaBtn.addEventListener('click', () => {
        const currentAnalysis = tabResults[activeTab];
        if (!currentAnalysis || !currentAnalysis.bangla) return;
        
        banglaBtn.classList.add('bg-blue-500', 'text-white');
        banglaBtn.classList.remove('bg-gray-200', 'text-gray-700');
        englishBtn.classList.add('bg-gray-200', 'text-gray-700');
        englishBtn.classList.remove('bg-blue-500', 'text-white');
        banglaContent.classList.remove('hidden');
        englishContent.classList.add('hidden');
    });

    function showLoading(msg) {
        loading.classList.remove('hidden');
        result.classList.add('hidden');
        error.classList.add('hidden');
        const loadingText = loading.querySelector('p');
        if (loadingText) {
            loadingText.textContent = msg || 'Analyzing with NVIDIA Nemotron AI...';
        }
    }

    function handleResponse(data) {
        loading.classList.add('hidden');
        console.log('Handling response for active tab:', activeTab, data);
        
        if (data.success && data.analysis) {
            tabResults[activeTab] = data.analysis;  // Store analysis specifically for active tab
            renderTabResult();
        } else {
            showError(data.error || 'An unexpected error occurred');
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
                    <span class="text-blue-700 font-bold text-lg flex items-center gap-2">
                        <svg class="w-5 h-5 inline-block text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 9 0 0118 0z"></path></svg>
                        Overall Summary
                    </span>
                </div>
                <div class="text-gray-800 text-sm font-medium leading-relaxed">$1</div>
            </div>`
        );

        // Highlight Possible Health Finding as a distinct observation card
        rawHtml = rawHtml.replace(
            /<h2>Possible Health Finding<\/h2>\s*([\s\S]*?)(?=<h2>|$)/gi,
            `<div class="possible-finding-card">
                <div class="flex items-center mb-2">
                    <span class="text-amber-800 font-bold text-lg flex items-center gap-2">
                        <svg class="w-5 h-5 inline-block text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                        Possible Health Finding
                    </span>
                </div>
                <div class="text-gray-800 text-sm font-medium leading-relaxed">$1</div>
            </div>`
        );

        // Highlight Possible Medication-Lab Safety Alert as a distinct high-visibility card
        rawHtml = rawHtml.replace(
            /<h2>Possible Medication[–\-]?Lab Safety Alert<\/h2>\s*([\s\S]*?)(?=<h2>|$)/gi,
            `<div class="safety-alert-card">
                <div class="flex items-center mb-2">
                    <span class="text-red-800 font-bold text-lg flex items-center gap-2">
                        <svg class="w-5 h-5 inline-block text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 9 0 0118 0z"></path></svg>
                        Possible Medication–Lab Safety Alert
                    </span>
                </div>
                <div class="text-gray-800 text-sm font-medium leading-relaxed">$1</div>
            </div>`
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
            translateBtn.classList.add('hidden');
        } else {
            translateBtn.classList.remove('hidden');
            banglaBtn.classList.add('hidden');
        }
        
        // Show English view by default
        englishContent.classList.remove('hidden');
        banglaContent.classList.add('hidden');
        
        // Update button states
        englishBtn.classList.add('bg-blue-500', 'text-white');
        englishBtn.classList.remove('bg-gray-200', 'text-gray-700');
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