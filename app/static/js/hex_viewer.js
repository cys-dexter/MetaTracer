class HexViewer {
  static renderHexDump(targetElementId, dumpRows) {
    const el = document.getElementById(targetElementId);
    if (!el) return;

    if (!dumpRows || dumpRows.length === 0) {
      el.innerHTML = '<div class="text-slate-500 py-4 text-center font-mono text-xs">No hex data available for this section.</div>';
      return;
    }

    let html = '<table class="hex-table">';
    dumpRows.forEach(row => {
      html += `<tr>
        <td class="hex-offset">${row.offset}</td>
        <td class="hex-bytes">${row.hex}</td>
        <td class="hex-ascii">${this.escapeHtml(row.ascii)}</td>
      </tr>`;
    });
    html += '</table>';
    el.innerHTML = html;
  }

  static renderSegmentsTable(targetElementId, segments) {
    const el = document.getElementById(targetElementId);
    if (!el) return;

    if (!segments || segments.length === 0) {
      el.innerHTML = '<div class="text-slate-500 py-4 text-center font-mono text-xs">No structural segments parsed.</div>';
      return;
    }

    let html = `
      <div class="overflow-x-auto">
        <table class="w-full text-left text-xs font-mono">
          <thead class="text-slate-400 bg-slate-900/60 uppercase border-b border-slate-800">
            <tr>
              <th class="py-2.5 px-3">Offset</th>
              <th class="py-2.5 px-3">Marker / ID</th>
              <th class="py-2.5 px-3">Type</th>
              <th class="py-2.5 px-3">Length</th>
              <th class="py-2.5 px-3">Description</th>
              <th class="py-2.5 px-3">Status</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800/60 text-slate-300">
    `;

    segments.forEach(seg => {
      const isWarn = seg.anomalous;
      const statusBadge = isWarn
        ? '<span class="badge badge-crimson">ANOMALY</span>'
        : '<span class="badge badge-emerald">NORMAL</span>';
      
      html += `
        <tr class="hover:bg-slate-800/30 transition-colors">
          <td class="py-2 px-3 text-cyan-400">0x${seg.offset}</td>
          <td class="py-2 px-3 font-bold text-amber-400">${seg.marker}</td>
          <td class="py-2 px-3">${seg.name}</td>
          <td class="py-2 px-3">${seg.length} B</td>
          <td class="py-2 px-3 text-slate-400">${seg.description}</td>
          <td class="py-2 px-3">${statusBadge}</td>
        </tr>
      `;
    });

    html += `
          </tbody>
        </table>
      </div>
    `;

    el.innerHTML = html;
  }

  static escapeHtml(str) {
    if (!str) return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
}

window.HexViewer = HexViewer;
