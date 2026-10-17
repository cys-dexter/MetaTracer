#!/usr/bin/env python3
import sys
from pathlib import Path

NEW_BLOCK = r"""  function resolveMapInfo(geo) {
    if (geo.map && typeof geo.map === 'object') return geo.map;
    const lat = Number(geo.latitude);
    const lon = Number(geo.longitude);
    const ok = geo.latitude != null && geo.longitude != null && Number.isFinite(lat) && Number.isFinite(lon);
    return {
      show: ok,
      latitude: ok ? lat : null,
      longitude: ok ? lon : null,
      radius_km: geo.uncertainty_radius_km || 0,
      zoom_hint: null
    };
  }

  function escapeText(value) {
    const str = String(value == null ? '' : value);
    if (typeof HexViewer !== 'undefined' && HexViewer.escapeHtml) return HexViewer.escapeHtml(str);
    return str.replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  }

  function renderGeospatial(geo) {
    if (!geo) return;

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

    const t = geo.telemetry || {};
    const mapInfo = resolveMapInfo(geo);
    const hasCoords = Boolean(mapInfo && mapInfo.show);
    const isDirect = geo.mode === 'EXIF_DIRECT';

    if (modeBadge) {
      if (isDirect) {
        modeBadge.textContent = 'EXIF DIRECT FIX';
        modeBadge.className = 'badge badge-emerald';
      } else {
        modeBadge.textContent = 'INFERENCE FALLBACK';
        modeBadge.className = 'badge badge-amber';
      }
    }

    if (sourceEl) sourceEl.textContent = geo.source_type || 'N/A';
    if (coordsEl) coordsEl.textContent = t.coordinate_display || 'Unavailable';
    if (altitudeEl) altitudeEl.textContent = t.altitude_display || 'N/A';
    if (radiusEl) radiusEl.textContent = hasCoords ? `± ${geo.uncertainty_radius_km} km` : 'N/A';
    if (confEl) {
      const rel = geo.reliability && geo.reliability !== 'NONE' ? ` (${geo.reliability})` : '';
      confEl.textContent = `${geo.confidence_score}%${rel}`;
    }
    if (notesEl) notesEl.textContent = geo.forensic_notes || '';

    if (evEl) evEl.textContent = t.calculated_exposure_value_ev100 || 'N/A';
    if (cctEl) cctEl.textContent = t.estimated_color_temperature_kelvin || 'N/A';
    if (solarPhaseEl) solarPhaseEl.textContent = t.solar_phase || 'N/A';
    if (sunElevationEl) sunElevationEl.textContent = t.sun_elevation_estimate || 'N/A';
    if (archetypeEl) archetypeEl.textContent = t.environmental_archetype || 'N/A';
    if (tzEl) tzEl.textContent = t.timezone_offset_detected || 'N/A';

    renderGeoExtras(geo);
    updateMap(mapInfo, isDirect, geo.reliability);
  }

  function renderGeoExtras(geo) {
    const anchor = document.getElementById('geoNotes');
    if (!anchor) return;

    let box = document.getElementById('geoExtras');
    if (!box) {
      box = document.createElement('div');
      box.id = 'geoExtras';
      box.className = 'mt-3 space-y-3 text-xs font-mono';
      anchor.insertAdjacentElement('afterend', box);
    }

    const parts = [];

    const rel = geo.reliability;
    if (rel && rel !== 'NONE') {
      const relClass = rel === 'HIGH' ? 'badge-emerald' : (rel === 'MEDIUM' ? 'badge-cyan' : 'badge-amber');
      parts.push(`
        <div class="flex items-center gap-2">
          <span class="text-slate-400">RELIABILITY</span>
          <span class="badge ${relClass}">${escapeText(rel)}</span>
        </div>
      `);
    }

    const alts = Array.isArray(geo.alternative_candidates) ? geo.alternative_candidates : [];
    if (alts.length > 0) {
      const rows = alts.map(a => `
        <div class="flex justify-between gap-3 p-2 rounded bg-slate-900 border border-slate-800">
          <span class="text-slate-300">${escapeText(a.region)}</span>
          <span class="text-slate-500">${escapeText(a.confidence_score)}% | +/- ${escapeText(a.uncertainty_radius_km)} km</span>
        </div>
      `).join('');
      parts.push(`<div><div class="text-slate-400 mb-1">ALTERNATIVE CANDIDATES</div><div class="space-y-1">${rows}</div></div>`);
    }

    const evidence = Array.isArray(geo.evidence) ? geo.evidence : [];
    if (evidence.length > 0) {
      const rows = evidence.map(e => {
        const flags = Array.isArray(e.flags) && e.flags.length > 0
          ? `<div class="text-amber-400/80 mt-0.5">${escapeText(e.flags.join(', ').replace(/_/g, ' '))}</div>`
          : '';
        return `
          <div class="p-2 rounded bg-slate-900 border border-slate-800">
            <div class="flex justify-between gap-3">
              <span class="text-cyan-400">${escapeText(e.source)}</span>
              <span class="text-slate-500">${Math.round((Number(e.adjusted_score) || 0) * 100)}%</span>
            </div>
            <div class="text-slate-300">${escapeText(e.label)}</div>
            ${flags}
          </div>
        `;
      }).join('');
      parts.push(`<div><div class="text-slate-400 mb-1">EVIDENCE TRAIL</div><div class="space-y-1">${rows}</div></div>`);
    }

    box.innerHTML = parts.join('');
  }

  function setMapVisibility(visible, message) {
    const mapEl = document.getElementById('map');
    if (!mapEl) return;

    let placeholder = document.getElementById('geoMapPlaceholder');
    if (!placeholder) {
      placeholder = document.createElement('div');
      placeholder.id = 'geoMapPlaceholder';
      placeholder.className = 'hidden rounded-xl border border-slate-700 bg-slate-900/60 p-6 text-center text-xs font-mono text-slate-400';
      mapEl.insertAdjacentElement('afterend', placeholder);
    }

    if (visible) {
      mapEl.style.display = '';
      placeholder.classList.add('hidden');
    } else {
      mapEl.style.display = 'none';
      placeholder.textContent = message || 'Map unavailable.';
      placeholder.classList.remove('hidden');
    }
  }

  function refitMap() {
    if (!leafletMap || !leafletMap._lastFit) return;
    const fit = leafletMap._lastFit;
    leafletMap.fitBounds(fit.bounds, { padding: [30, 30], maxZoom: fit.maxZoom });
  }

  function updateMap(info, isDirect, reliability) {
    if (typeof L === 'undefined') return;

    const lat = Number(info && info.latitude);
    const lon = Number(info && info.longitude);
    const valid = Boolean(info && info.show) && info.latitude != null && info.longitude != null
      && Number.isFinite(lat) && Number.isFinite(lon);

    if (!valid) {
      if (leafletMap) {
        if (mapMarker) leafletMap.removeLayer(mapMarker);
        if (mapCircle) leafletMap.removeLayer(mapCircle);
        leafletMap._lastFit = null;
      }
      mapMarker = null;
      mapCircle = null;
      setMapVisibility(false, 'No coordinates could be resolved: GPS is absent and no regional evidence was found.');
      return;
    }

    setMapVisibility(true);

    const radiusKm = Number(info.radius_km) > 0 ? Number(info.radius_km) : 1;
    const zoomHint = info.zoom_hint != null && Number.isFinite(Number(info.zoom_hint))
      ? Number(info.zoom_hint)
      : (isDirect ? 13 : 4);

    if (!leafletMap) {
      leafletMap = L.map('map', {
        zoomControl: true,
        attributionControl: false
      }).setView([lat, lon], zoomHint);

      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19
      }).addTo(leafletMap);
    } else {
      leafletMap.setView([lat, lon], zoomHint);
      if (mapMarker) leafletMap.removeLayer(mapMarker);
      if (mapCircle) leafletMap.removeLayer(mapCircle);
    }

    const weak = !isDirect && (reliability === 'SPECULATIVE' || reliability === 'LOW' || !reliability);
    const markerColor = isDirect ? '#10b981' : (weak ? '#f59e0b' : '#38bdf8');
    const circleColor = isDirect ? '#10b981' : (weak ? '#f59e0b' : '#06b6d4');

    mapMarker = L.circleMarker([lat, lon], {
      radius: 8,
      fillColor: markerColor,
      color: '#fff',
      weight: 2,
      opacity: 1,
      fillOpacity: 0.9
    }).addTo(leafletMap);

    mapCircle = L.circle([lat, lon], {
      radius: radiusKm * 1000,
      color: circleColor,
      weight: 1.5,
      fillColor: circleColor,
      fillOpacity: 0.12,
      dashArray: isDirect ? null : '6, 6'
    }).addTo(leafletMap);

    leafletMap._lastFit = {
      bounds: mapCircle.getBounds(),
      maxZoom: isDirect ? 14 : zoomHint
    };

    leafletMap.invalidateSize();
    refitMap();
    setTimeout(() => {
      if (leafletMap) {
        leafletMap.invalidateSize();
        refitMap();
      }
    }, 250);
  }

"""

TAB_OLD = "            leafletMap.invalidateSize();\n          }, 150);"
TAB_NEW = "            leafletMap.invalidateSize();\n            refitMap();\n          }, 150);"


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "app/static/js/app.js")
    if not path.exists():
        sys.exit(f"File not found: {path}")

    src = path.read_text(encoding="utf-8")
    if "function resolveMapInfo" in src:
        sys.exit("Already patched, nothing to do.")

    start = src.find("  function renderGeospatial(geo) {")
    end = src.find("  function renderHexStructure(hex) {")
    if start == -1 or end == -1 or end < start:
        sys.exit("Could not locate renderGeospatial / renderHexStructure; file left untouched.")

    backup = path.with_suffix(path.suffix + ".bak")
    backup.write_text(src, encoding="utf-8")

    out = src[:start] + NEW_BLOCK + src[end:]

    if out.count(TAB_OLD) == 1:
        out = out.replace(TAB_OLD, TAB_NEW, 1)
        tab_msg = "tab handler updated"
    else:
        tab_msg = "tab handler not found (skipped, map still works)"

    path.write_text(out, encoding="utf-8")
    print(f"Patched {path} (backup: {backup.name}); {tab_msg}.")


if __name__ == "__main__":
    main()
