document.addEventListener('DOMContentLoaded', () => {
  const fileDropZone = document.getElementById('fileDropZone');
  const fileInput = document.getElementById('fileInput');
  const sampleBtn = document.getElementById('sampleBtn');
  const resultsContainer = document.getElementById('resultsContainer');
  const emptyState = document.getElementById('emptyState');
  const scanProgress = document.getElementById('scanProgress');
  const exportJsonBtn = document.getElementById('exportJsonBtn');
  const exportPrintBtn = document.getElementById('exportPrintBtn');

  let currentAnalysisData = null;
  let elaSlider = null;
  let leafletMap = null;
  let mapMarker = null;
  let mapCircle = null;

  initTabs();
  initDragAndDrop();
  initActions();

  function initTabs() {
    const tabButtons = document.querySelectorAll('.nav-tab-btn');
    tabButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        tabButtons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');

        const targetId = btn.getAttribute('data-tab');
        const contents = document.querySelectorAll('.tab-content-panel');
        contents.forEach(panel => {
          if (panel.id === targetId) {
            panel.classList.remove('hidden');
          } else {
            panel.classList.add('hidden');
          }
        });

        if (targetId === 'tab-geospatial' && leafletMap) {
          setTimeout(() => {
            leafletMap.invalidateSize();
          }, 150);
        }
      });
    });
  }

  function initDragAndDrop() {
    if (!fileDropZone || !fileInput) return;

    ['dragenter', 'dragover'].forEach(eventName => {
      fileDropZone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        fileDropZone.classList.add('drop-zone-active');
      });
    });

    ['dragleave', 'drop'].forEach(eventName => {
      fileDropZone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        fileDropZone.classList.remove('drop-zone-active');
      });
    });

    fileDropZone.addEventListener('drop', (e) => {
      const dt = e.dataTransfer;
      if (dt.files && dt.files.length > 0) {
        handleFileUpload(dt.files[0]);
      }
    });

    fileDropZone.addEventListener('click', (e) => {
      if (e.target.closest('#sampleBtn')) return;
      fileInput.click();
    });

    fileInput.addEventListener('change', () => {
      if (fileInput.files && fileInput.files.length > 0) {
        handleFileUpload(fileInput.files[0]);
      }
    });
  }

  function initActions() {
    if (sampleBtn) {
      sampleBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        loadSampleAnalysis();
      });
    }

    if (exportJsonBtn) {
      exportJsonBtn.addEventListener('click', () => {
        if (!currentAnalysisData) return;
        const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(currentAnalysisData, null, 2));
        const dl = document.createElement('a');
        dl.setAttribute('href', dataStr);
        dl.setAttribute('download', `forensic_report_${currentAnalysisData.filename}.json`);
        dl.click();
      });
    }

    if (exportPrintBtn) {
      exportPrintBtn.addEventListener('click', () => {
        window.print();
      });
    }

    const elaViewModeRadios = document.querySelectorAll('input[name="elaViewMode"]');
    elaViewModeRadios.forEach(radio => {
      radio.addEventListener('change', (e) => {
        if (elaSlider) {
          elaSlider.setMode(e.target.value);
        }
      });
    });

    const reanalyzeElaBtn = document.getElementById('reanalyzeElaBtn');
    if (reanalyzeElaBtn) {
      reanalyzeElaBtn.addEventListener('click', () => {
        if (fileInput.files && fileInput.files.length > 0) {
          handleFileUpload(fileInput.files[0]);
        }
      });
    }

    const exifSearchInput = document.getElementById('exifSearchInput');
    if (exifSearchInput) {
      exifSearchInput.addEventListener('input', (e) => {
        filterExifRows(e.target.value.toLowerCase());
      });
    }
  }

  function setScanningState(isScanning, message) {
    if (scanProgress) {
      if (isScanning) {
        scanProgress.classList.remove('hidden');
        fileDropZone.classList.add('scanning');
        const textEl = document.getElementById('scanStatusText');
        if (textEl) textEl.textContent = message || 'Running Deep Forensic Pipeline...';
      } else {
        scanProgress.classList.add('hidden');
        fileDropZone.classList.remove('scanning');
      }
    }
  }

  async function handleFileUpload(file) {
    if (!file) return;

    const maxBytes = 25 * 1024 * 1024;
    if (file.size > maxBytes) {
      alert('Selected file exceeds the 25MB safety threshold.');
      return;
    }

    setScanningState(true, `Analyzing ${file.name} (Extracting DQT, ELA, Structural Hex)...`);

    const formData = new FormData();
    formData.append('file', file);

    const qInput = document.getElementById('elaQualityInput');
    const sInput = document.getElementById('elaScaleInput');
    if (qInput) formData.append('ela_quality', qInput.value);
    if (sInput) formData.append('ela_scale', sInput.value);

    try {
      const response = await fetch('/api/analyze', {
        method: 'POST',
        body: formData
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: 'Analysis failed on server.' }));
        throw new Error(err.detail || 'Analysis request returned error.');
      }

      const data = await response.json();
      currentAnalysisData = data;
      renderAnalysis(data);
    } catch (error) {
      alert(`Forensic Analysis Error: ${error.message}`);
    } finally {
      setScanningState(false);
    }
  }

  async function loadSampleAnalysis() {
    setScanningState(true, 'Synthesizing forensic specimen with embedded payload & DQT matrices...');
    try {
      const response = await fetch('/api/sample');
      if (!response.ok) throw new Error('Failed to retrieve specimen.');
      const data = await response.json();
      currentAnalysisData = data;
      renderAnalysis(data);
    } catch (error) {
      alert(`Sample Specimen Error: ${error.message}`);
    } finally {
      setScanningState(false);
    }
  }

  function renderAnalysis(data) {
    if (emptyState) emptyState.classList.add('hidden');
    if (resultsContainer) resultsContainer.classList.remove('hidden');

    renderThreatHUD(data);
    renderOverview(data);
    renderQuantization(data.quantization);
    renderEla(data.ela);
    renderPayload(data.payload);
    renderGeospatial(data.geospatial);
    renderHexStructure(data.hex_structure);
    renderMetadata(data.metadata);

    resultsContainer.scrollIntoView({ behavior: 'smooth' });
  }

  function renderThreatHUD(data) {
    const risk = data.risk_evaluation;
    const scoreEl = document.getElementById('hudRiskScore');
    const badgeEl = document.getElementById('hudThreatBadge');
    const verdictEl = document.getElementById('hudVerdictText');
    const filenameEl = document.getElementById('hudFileName');
    const formatEl = document.getElementById('hudFileFormat');
    const sizeEl = document.getElementById('hudFileSize');
    const latencyEl = document.getElementById('hudLatency');

    if (scoreEl) scoreEl.textContent = `${risk.score}/100`;
    if (verdictEl) verdictEl.textContent = risk.executive_verdict;
    if (filenameEl) filenameEl.textContent = data.filename;
    if (formatEl) formatEl.textContent = data.detected_format;
    if (sizeEl) sizeEl.textContent = data.file_size_formatted;
    if (latencyEl) latencyEl.textContent = `${data.processing_time_ms} ms`;

    if (badgeEl) {
      badgeEl.textContent = risk.threat_level;
      badgeEl.className = 'badge';
      if (risk.color_class === 'red') {
        badgeEl.classList.add('badge-crimson');
      } else if (risk.color_class === 'amber') {
        badgeEl.classList.add('badge-amber');
      } else {
        badgeEl.classList.add('badge-emerald');
      }
    }

    const md5El = document.getElementById('hudMd5');
    const sha1El = document.getElementById('hudSha1');
    const sha256El = document.getElementById('hudSha256');

    if (md5El) md5El.textContent = data.hashes.md5;
    if (sha1El) sha1El.textContent = data.hashes.sha1;
    if (sha256El) sha256El.textContent = data.hashes.sha256;
  }

  function renderOverview(data) {
    const risk = data.risk_evaluation;
    const meterEl = document.getElementById('overviewScoreBar');
    if (meterEl) {
      meterEl.style.width = `${risk.score}%`;
      if (risk.color_class === 'red') {
        meterEl.className = 'h-full bg-red-500 rounded-full transition-all duration-700';
      } else if (risk.color_class === 'amber') {
        meterEl.className = 'h-full bg-amber-500 rounded-full transition-all duration-700';
      } else {
        meterEl.className = 'h-full bg-emerald-500 rounded-full transition-all duration-700';
      }
    }

    const elaScoreEl = document.getElementById('summaryElaScore');
    const dqtFingerprintEl = document.getElementById('summaryDqtFingerprint');
    const payloadThreatEl = document.getElementById('summaryPayloadThreat');
    const geoModeEl = document.getElementById('summaryGeoMode');

    if (elaScoreEl) elaScoreEl.textContent = `${data.ela.tampering_likelihood_score}%`;
    
    if (dqtFingerprintEl) {
      if (data.quantization.is_jpeg && data.quantization.source_fingerprint) {
        dqtFingerprintEl.textContent = data.quantization.source_fingerprint.signature_name;
      } else {
        dqtFingerprintEl.textContent = 'Non-DCT Container / N/A';
      }
    }

    if (payloadThreatEl) {
      payloadThreatEl.textContent = data.payload.has_trailing_payload
        ? `${data.payload.threat_level} (${data.payload.payload_size_formatted})`
        : 'None (Clean Boundary)';
    }

    if (geoModeEl) {
      geoModeEl.textContent = data.geospatial.mode === 'EXIF_DIRECT'
        ? 'Direct Satellite Fix'
        : 'Smart Photometric Inference';
    }
  }

  function renderQuantization(quant) {
    const container = document.getElementById('tab-quantization');
    if (!container) return;

    if (!quant.is_jpeg || !quant.has_dqt) {
      document.getElementById('quantNonJpegMsg').classList.remove('hidden');
      document.getElementById('quantContentGrid').classList.add('hidden');
      document.getElementById('quantNonJpegDetail').textContent = quant.message || 'Target file is not a JPEG container.';
      return;
    }

    document.getElementById('quantNonJpegMsg').classList.add('hidden');
    document.getElementById('quantContentGrid').classList.remove('hidden');

    const qfEl = document.getElementById('quantEstQf');
    const confEl = document.getElementById('quantMatchConf');
    const fpNameEl = document.getElementById('quantFingerprintName');
    const fpCatEl = document.getElementById('quantFingerprintCategory');
    const fpDescEl = document.getElementById('quantFingerprintDesc');
    const dblProbEl = document.getElementById('quantDoubleCompProb');
    const bypassVerdictEl = document.getElementById('quantBypassVerdict');

    if (qfEl) qfEl.textContent = `QF ~ ${quant.estimated_quality_factor}`;
    if (confEl) confEl.textContent = `${quant.quality_match_confidence}% Match`;
    
    const fp = quant.source_fingerprint;
    if (fp) {
      if (fpNameEl) fpNameEl.textContent = fp.signature_name;
      if (fpCatEl) fpCatEl.textContent = fp.category;
      if (fpDescEl) fpDescEl.textContent = fp.description;
    }

    const dbl = quant.double_compression;
    if (dbl && dblProbEl) {
      dblProbEl.textContent = `${dbl.double_compression_probability}%`;
      dblProbEl.className = dbl.is_likely_double_compressed ? 'text-red-400 font-bold' : 'text-emerald-400 font-bold';
    }

    if (bypassVerdictEl && quant.exif_bypass_analysis) {
      bypassVerdictEl.textContent = quant.exif_bypass_analysis.verdict;
    }

    renderMatrixGrid('matrixGridLuminance', quant.matrices.luminance);
    renderMatrixGrid('matrixGridChrominance', quant.matrices.chrominance);
  }

  function renderMatrixGrid(elementId, matrix8x8) {
    const el = document.getElementById(elementId);
    if (!el || !matrix8x8) return;

    el.innerHTML = '';
    for (let r = 0; r < 8; r++) {
      for (let c = 0; c < 8; c++) {
        const val = matrix8x8[r][c];
        const cell = document.createElement('div');
        cell.className = 'matrix-cell';
        cell.textContent = val;

        if (val <= 4) {
          cell.classList.add('matrix-cell-low');
        } else if (val <= 16) {
          cell.classList.add('matrix-cell-mid');
        } else if (val <= 50) {
          cell.classList.add('matrix-cell-high');
        } else {
          cell.classList.add('matrix-cell-extreme');
        }

        cell.title = `Row ${r}, Col ${c}: Coeff = ${val}`;
        el.appendChild(cell);
      }
    }
  }

  function renderEla(ela) {
    if (!elaSlider) {
      elaSlider = new ElaComparisonSlider('elaComparisonContainer');
    }
    elaSlider.setImages(ela.images);

    const scoreEl = document.getElementById('elaScoreDisplay');
    const verdictEl = document.getElementById('elaVerdictDisplay');
    const meanEl = document.getElementById('elaMeanError');
    const maxEl = document.getElementById('elaMaxError');
    const stdEl = document.getElementById('elaStdError');
    const highRatioEl = document.getElementById('elaHighRatio');

    if (scoreEl) scoreEl.textContent = `${ela.tampering_likelihood_score}%`;
    if (verdictEl) verdictEl.textContent = ela.forensic_verdict;
    if (meanEl) meanEl.textContent = ela.mean_error;
    if (maxEl) maxEl.textContent = ela.max_error;
    if (stdEl) stdEl.textContent = ela.std_dev_error;
    if (highRatioEl) highRatioEl.textContent = `${ela.high_variance_pixel_ratio}%`;
  }

  function renderPayload(payload) {
    const statusBadge = document.getElementById('payloadStatusBadge');
    const threatLevelEl = document.getElementById('payloadThreatLevel');
    const sizeFormattedEl = document.getElementById('payloadSizeFormatted');
    const ratioEl = document.getElementById('payloadRatio');
    const eofOffsetEl = document.getElementById('payloadEofOffset');
    const entropyValEl = document.getElementById('payloadEntropyValue');
    const entropyAssessEl = document.getElementById('payloadEntropyAssess');
    const entropyBarEl = document.getElementById('payloadEntropyBar');
    const sigsListEl = document.getElementById('payloadSignaturesList');
    const stringsListEl = document.getElementById('payloadStringsList');

    if (statusBadge) {
      if (payload.has_trailing_payload) {
        statusBadge.textContent = 'PAYLOAD DETECTED';
        statusBadge.className = 'badge badge-crimson';
      } else {
        statusBadge.textContent = 'CLEAN EOF';
        statusBadge.className = 'badge badge-emerald';
      }
    }

    if (threatLevelEl) threatLevelEl.textContent = payload.threat_level;
    if (sizeFormattedEl) sizeFormattedEl.textContent = payload.payload_size_formatted;
    if (ratioEl) ratioEl.textContent = `${payload.payload_ratio_percentage}% of total file`;
    if (eofOffsetEl) eofOffsetEl.textContent = payload.expected_eof_offset;
    if (entropyValEl) entropyValEl.textContent = `${payload.shannon_entropy} / 8.0`;
    if (entropyAssessEl) entropyAssessEl.textContent = payload.entropy_assessment;

    if (entropyBarEl) {
      const pct = (payload.shannon_entropy / 8.0) * 100;
      entropyBarEl.style.width = `${pct}%`;
      if (payload.shannon_entropy > 7.2) {
        entropyBarEl.className = 'h-full bg-red-500 rounded-full transition-all';
      } else if (payload.shannon_entropy > 4.0) {
        entropyBarEl.className = 'h-full bg-amber-500 rounded-full transition-all';
      } else {
        entropyBarEl.className = 'h-full bg-cyan-500 rounded-full transition-all';
      }
    }

    if (sigsListEl) {
      if (payload.detected_signatures && payload.detected_signatures.length > 0) {
        sigsListEl.innerHTML = payload.detected_signatures.map(s => `
          <div class="flex items-center justify-between p-2 rounded bg-slate-900 border border-red-900/40 font-mono text-xs">
            <span class="text-red-400 font-bold">${s.signature_name}</span>
            <span class="text-slate-400">Offset +0x${s.offset_within_payload}</span>
            <span class="badge badge-crimson">${s.category}</span>
          </div>
        `).join('');
      } else {
        sigsListEl.innerHTML = '<div class="text-slate-500 text-xs italic">No known magic signatures identified in trailer.</div>';
      }
    }

    if (stringsListEl) {
      if (payload.extracted_strings && payload.extracted_strings.length > 0) {
        stringsListEl.innerHTML = payload.extracted_strings.map(str => `
          <div class="px-2 py-1 bg-slate-900/80 rounded border border-slate-800 font-mono text-xs text-amber-300 break-all select-all">
            ${HexViewer.escapeHtml(str)}
          </div>
        `).join('');
      } else {
        stringsListEl.innerHTML = '<div class="text-slate-500 text-xs italic">No printable ASCII strings identified.</div>';
      }
    }

    HexViewer.renderHexDump('payloadHexDump', payload.hex_preview);
  }

  function renderGeospatial(geo) {
    const modeBadge = document.getElementById('geoModeBadge');
    const sourceEl = document.getElementById('geoSourceType');
    const coordsEl = document.getElementById('geoCoordinates');
    const altitudeEl = document.getElementById('geoAltitude');
    const radiusEl = document.getElementById('geoRadius');
    const confEl = document.getElementById('geoConfidence');
    const notesEl = document.getElementById('geoNotes');

    const evEl = document.getElementById('geoEv100');
    const cctEl = document.getElementById('geoCct');
    const solarPhaseEl = document.getElementById('geoSolarPhase');
    const sunElevationEl = document.getElementById('geoSunElevation');
    const archetypeEl = document.getElementById('geoArchetype');
    const tzEl = document.getElementById('geoTimezone');

    if (modeBadge) {
      if (geo.mode === 'EXIF_DIRECT') {
        modeBadge.textContent = 'EXIF DIRECT FIX';
        modeBadge.className = 'badge badge-emerald';
      } else {
        modeBadge.textContent = 'INFERENCE FALLBACK';
        modeBadge.className = 'badge badge-amber';
      }
    }

    if (sourceEl) sourceEl.textContent = geo.source_type;
    if (coordsEl) coordsEl.textContent = geo.telemetry.coordinate_display;
    if (altitudeEl) altitudeEl.textContent = geo.telemetry.altitude_display || 'N/A';
    if (radiusEl) radiusEl.textContent = `± ${geo.uncertainty_radius_km} km`;
    if (confEl) confEl.textContent = `${geo.confidence_score}%`;
    if (notesEl) notesEl.textContent = geo.forensic_notes;

    const t = geo.telemetry;
    if (evEl) evEl.textContent = t.calculated_exposure_value_ev100 || 'N/A';
    if (cctEl) cctEl.textContent = t.estimated_color_temperature_kelvin || 'N/A';
    if (solarPhaseEl) solarPhaseEl.textContent = t.solar_phase || 'N/A';
    if (sunElevationEl) sunElevationEl.textContent = t.sun_elevation_estimate || 'N/A';
    if (archetypeEl) archetypeEl.textContent = t.environmental_archetype || 'N/A';
    if (tzEl) tzEl.textContent = t.timezone_offset_detected || 'N/A';

    updateMap(geo.latitude, geo.longitude, geo.uncertainty_radius_km, geo.mode === 'EXIF_DIRECT');
  }

  function updateMap(lat, lon, radiusKm, isDirect) {
    if (typeof L === 'undefined') return;

    if (!leafletMap) {
      leafletMap = L.map('map', {
        zoomControl: true,
        attributionControl: false
      }).setView([lat, lon], isDirect ? 13 : 4);

      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19
      }).addTo(leafletMap);
    } else {
      leafletMap.setView([lat, lon], isDirect ? 13 : 4);
      if (mapMarker) leafletMap.removeLayer(mapMarker);
      if (mapCircle) leafletMap.removeLayer(mapCircle);
    }

    const markerColor = isDirect ? '#10b981' : '#f59e0b';
    const circleColor = isDirect ? '#10b981' : '#06b6d4';

    mapMarker = L.circleMarker([lat, lon], {
      radius: 8,
      fillColor: markerColor,
      color: '#fff',
      weight: 2,
      opacity: 1,
      fillOpacity: 0.9
    }).addTo(leafletMap);

    const radiusMeters = (radiusKm || 1) * 1000;
    mapCircle = L.circle([lat, lon], {
      radius: radiusMeters,
      color: circleColor,
      weight: 1.5,
      fillColor: circleColor,
      fillOpacity: 0.12,
      dashArray: isDirect ? null : '6, 6'
    }).addTo(leafletMap);

    leafletMap.fitBounds(mapCircle.getBounds(), { padding: [30, 30], maxZoom: isDirect ? 14 : 6 });
  }

  function renderHexStructure(hex) {
    const scoreEl = document.getElementById('hexIntegrityScore');
    const segCountEl = document.getElementById('hexSegmentCount');
    const eofStatusEl = document.getElementById('hexEofStatus');
    const anomaliesListEl = document.getElementById('hexAnomaliesList');

    if (scoreEl) scoreEl.textContent = `${hex.structural_integrity_score}%`;
    if (segCountEl) segCountEl.textContent = hex.segment_count;
    if (eofStatusEl) {
      eofStatusEl.textContent = hex.has_eoi ? 'VALID TERMINATOR' : 'DAMAGED / MISSING EOF';
      eofStatusEl.className = hex.has_eoi ? 'badge badge-emerald' : 'badge badge-crimson';
    }

    if (anomaliesListEl) {
      if (hex.anomalies && hex.anomalies.length > 0) {
        anomaliesListEl.innerHTML = hex.anomalies.map(a => `
          <div class="p-2.5 rounded bg-red-950/30 border border-red-900/60 font-mono text-xs text-red-300 flex items-center gap-2">
            <span class="text-red-500 font-bold">▲</span>
            <span>${HexViewer.escapeHtml(a)}</span>
          </div>
        `).join('');
      } else {
        anomaliesListEl.innerHTML = `
          <div class="p-2.5 rounded bg-emerald-950/30 border border-emerald-900/60 font-mono text-xs text-emerald-300 flex items-center gap-2">
            <span class="text-emerald-500 font-bold">✓</span>
            <span>Zero structural container anomalies detected. Marker sequence complies with container specification.</span>
          </div>
        `;
      }
    }

    HexViewer.renderSegmentsTable('hexSegmentsTableContainer', hex.segments);
    HexViewer.renderHexDump('hexHeaderDump', hex.header_hex_dump);
    HexViewer.renderHexDump('hexTailDump', hex.tail_hex_dump);
  }

  function renderMetadata(meta) {
    const camMakeEl = document.getElementById('metaCamMake');
    const camModelEl = document.getElementById('metaCamModel');
    const camLensEl = document.getElementById('metaCamLens');
    const camSerialEl = document.getElementById('metaCamSerial');
    const dateOriginalEl = document.getElementById('metaDateOriginal');
    const dateModEl = document.getElementById('metaDateMod');
    const expParamsEl = document.getElementById('metaExpParams');
    const iccEl = document.getElementById('metaIccStatus');

    const cam = meta.camera || {};
    const temp = meta.temporal || {};
    const exp = meta.exposure || {};

    if (camMakeEl) camMakeEl.textContent = cam.make || 'N/A';
    if (camModelEl) camModelEl.textContent = cam.model || 'N/A';
    if (camLensEl) camLensEl.textContent = cam.lens_model || 'N/A';
    if (camSerialEl) camSerialEl.textContent = cam.serial_number || 'N/A';
    if (dateOriginalEl) dateOriginalEl.textContent = temp.date_time_original || 'N/A';
    if (dateModEl) dateModEl.textContent = temp.date_time_modified || 'N/A';

    if (expParamsEl) {
      const parts = [];
      if (exp.f_number) parts.push(`f/${exp.f_number}`);
      if (exp.exposure_time) parts.push(`${exp.exposure_time}s`);
      if (exp.iso) parts.push(`ISO ${exp.iso}`);
      if (exp.focal_length) parts.push(`${exp.focal_length}mm`);
      expParamsEl.textContent = parts.length > 0 ? parts.join(' | ') : 'N/A';
    }

    if (iccEl) {
      iccEl.textContent = meta.icc_profile_present ? 'EMBEDDED PROFILE' : 'NONE';
      iccEl.className = meta.icc_profile_present ? 'badge badge-cyan' : 'badge badge-slate';
    }

    const tableBody = document.getElementById('exifRawTableBody');
    if (!tableBody) return;

    const tags = meta.all_tags || {};
    const entries = Object.entries(tags);

    if (entries.length === 0) {
      tableBody.innerHTML = '<tr><td colspan="2" class="py-4 text-center text-slate-500 italic">No EXIF directory entries present in container.</td></tr>';
      return;
    }

    tableBody.innerHTML = entries.map(([key, val]) => `
      <tr class="exif-row hover:bg-slate-800/30 transition-colors">
        <td class="py-2 px-3 text-cyan-400 font-bold whitespace-nowrap">${HexViewer.escapeHtml(key)}</td>
        <td class="py-2 px-3 text-slate-300 break-all select-all">${HexViewer.escapeHtml(String(val))}</td>
      </tr>
    `).join('');
  }

  function filterExifRows(query) {
    const rows = document.querySelectorAll('.exif-row');
    rows.forEach(r => {
      const text = r.textContent.toLowerCase();
      if (!query || text.includes(query)) {
        r.style.display = '';
      } else {
        r.style.display = 'none';
      }
    });
  }
});
