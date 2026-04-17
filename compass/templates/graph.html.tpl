<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Architect's Compass — {PROJECT_NAME}</title>
  <script src="{VIS_NETWORK_CDN}"></script>
  <style>
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; height: 100%; background: #1e1e1e;
                 font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; }
    #graph { width: 100vw; height: 100vh; }
    #legend {
      position: fixed; top: 12px; left: 12px;
      background: rgba(0,0,0,0.75); color: #ccc;
      padding: 12px 16px; border-radius: 6px; font-size: 12px; line-height: 1.9;
      z-index: 10; max-width: 280px;
    }
    #legend strong { color: #fff; display: block; margin-bottom: 4px; }
    #legend .meta { color: #888; font-size: 11px; margin-top: 6px; border-top: 1px solid #333; padding-top: 6px; }
    .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%;
           margin-right: 6px; vertical-align: middle; }
    .swatch { display: inline-block; width: 20px; height: 3px; margin-right: 6px;
              vertical-align: middle; }
    #controls {
      position: fixed; top: 12px; right: 12px;
      background: rgba(0,0,0,0.75); color: #ccc;
      padding: 8px 12px; border-radius: 6px; font-size: 12px; z-index: 10;
      display: flex; gap: 6px;
    }
    #controls button {
      background: #333; color: #eee; border: 1px solid #555;
      padding: 4px 10px; border-radius: 3px; cursor: pointer; font-size: 11px;
      font-family: inherit;
    }
    #controls button:hover { background: #444; }
    #status {
      position: fixed; bottom: 12px; left: 12px;
      color: #666; font-size: 11px; z-index: 10;
    }
  </style>
</head>
<body>
<div id="legend">
  <strong>Architect's Compass — {PROJECT_NAME}</strong>
  <span class="dot" style="background:#4fc3f7"></span>Archivo interno<br>
  <span class="dot" style="background:#ffb300"></span>Hub (≥5 inbound)<br>
  <span class="dot" style="background:#fff3cd;border:1px solid #b7791f"></span>Huérfano<br>
  <span class="dot" style="background:#fde0dc;border:1px solid #c0392b"></span>En ciclo<br>
  <span class="dot" style="background:#4fc3f7;border:3px solid {ENTRY_POINT_BORDER_COLOR}"></span>Entry point<br>
  <div id="tier-legend" style="margin-top:6px; border-top:1px solid #333; padding-top:6px;">
    <strong style="font-size:11px; color:#aaa; display:block; margin-bottom:4px;">Externals por tier</strong>
  </div>
  <div class="meta">
    {GENERATED_AT}<br>
    nodes={NODE_COUNT} · edges={EDGE_COUNT} · cycles={CYCLE_COUNT}
  </div>
</div>
<div id="controls">
  <button onclick="fitGraph()">Fit</button>
  <button onclick="togglePhysics()">Toggle Physics</button>
  <button onclick="exportPng()">PNG</button>
</div>
<div id="graph"></div>
<div id="status"></div>
<script>
  // Datos inyectados por graph_emitter.build_graph_html()
  const EDGES_RAW = {EDGES_RAW_JSON};
  const EXTERNALS = new Set({EXTERNALS_JSON});
  const ORPHANS = new Set({ORPHANS_JSON});
  const CYCLES_NODES = new Set({CYCLES_NODES_JSON});
  const EDGE_COLORS = {EDGE_COLORS_JSON};
  // TIER-035 — tier semántico por external label + colores por tier.
  const EXTERNAL_TIERS = {EXTERNAL_TIERS_JSON};
  const TIER_COLORS = {TIER_COLORS_JSON};
  // GRAPH-036 — entry points (paths posix) + style.
  const ENTRY_POINTS = new Set({ENTRY_POINTS_JSON});
  const EP_BORDER_COLOR = "{ENTRY_POINT_BORDER_COLOR}";
  const EP_BORDER_WIDTH = {ENTRY_POINT_BORDER_WIDTH};
  const EP_SIZE_BOOST = {ENTRY_POINT_SIZE_BOOST};
  const EP_LABEL_PREFIX = "{ENTRY_POINT_LABEL_PREFIX}";

  // TIER-035 — darken helper (para borderColor por tier).
  function _darken(hex) {
    const h = (hex || "").replace("#", "");
    if (h.length !== 6) return "#333";
    const r = Math.max(0, parseInt(h.slice(0,2),16) - 48);
    const g = Math.max(0, parseInt(h.slice(2,4),16) - 48);
    const b = Math.max(0, parseInt(h.slice(4,6),16) - 48);
    return "#" + [r,g,b].map(v => v.toString(16).padStart(2,"0")).join("");
  }

  // TIER-035 — poblar leyenda de tiers dinámicamente con los tiers presentes.
  (function populateTierLegend() {
    const tierLegend = document.getElementById("tier-legend");
    if (!tierLegend) return;
    const presentTiers = new Set();
    EXTERNALS.forEach(name => {
      const t = EXTERNAL_TIERS[name] || "package";
      presentTiers.add(t);
    });
    const order = ["service", "wrapper", "package", "stdlib"];
    order.filter(t => presentTiers.has(t)).forEach(t => {
      const c = TIER_COLORS[t] || "#888";
      const row = document.createElement("div");
      row.innerHTML =
        '<span class="dot" style="background:' + c + ';border:1px solid ' + _darken(c) + '"></span>' +
        '<span style="text-transform:capitalize">' + t + '</span>';
      tierLegend.appendChild(row);
    });
  })();

  // contar inbound por nodo
  const inbound = {};
  EDGES_RAW.forEach(e => { inbound[e[1]] = (inbound[e[1]]||0) + 1; });

  // recolectar TODOS los node names (sources + targets + externals registrados
  // aunque no aparezcan en edges).
  const allNames = new Set();
  EDGES_RAW.forEach(e => { allNames.add(e[0]); allNames.add(e[1]); });
  EXTERNALS.forEach(n => allNames.add(n));
  ORPHANS.forEach(n => allNames.add(n));
  ENTRY_POINTS.forEach(n => allNames.add(n));

  // construir nodos únicos
  const nodeMap = {};
  let idSeq = 1;
  allNames.forEach(name => {
    if (nodeMap[name]) return;
    const isExternal = EXTERNALS.has(name);
    const isOrphan  = ORPHANS.has(name);
    const isCycle   = CYCLES_NODES.has(name);
    const isHub     = (inbound[name]||0) >= 5;
    const isEntry   = ENTRY_POINTS.has(name);
    let color = "#4fc3f7";
    let borderColor = "#2a7ca8";
    let borderWidth = 1;
    if (isExternal) {
      // TIER-035 — color por tier.
      const tier = EXTERNAL_TIERS[name] || "package";
      color = TIER_COLORS[tier] || "#ef5350";
      borderColor = _darken(color);
    }
    else if (isCycle)    { color = "#fde0dc"; borderColor = "#c0392b"; }
    else if (isOrphan)   { color = "#fff3cd"; borderColor = "#b7791f"; }
    else if (isHub)      { color = "#ffb300"; borderColor = "#a07700"; }
    // GRAPH-036 — entry point: override borde + engordar.
    if (isEntry && !isExternal) {
      borderColor = EP_BORDER_COLOR;
      borderWidth = EP_BORDER_WIDTH;
    }
    let baseLabel = name.length > 34 ? "…" + name.slice(-32) : name;
    if (isEntry && EP_LABEL_PREFIX) baseLabel = EP_LABEL_PREFIX + " " + baseLabel;
    const titleExtras = [];
    titleExtras.push("inbound: " + (inbound[name]||0));
    if (isExternal) titleExtras.push("tier: " + (EXTERNAL_TIERS[name] || "package"));
    if (isEntry) titleExtras.push("entry point");
    nodeMap[name] = {
      id: idSeq++,
      label: baseLabel,
      title: name + "\n" + titleExtras.join("\n"),
      color: { background: color, border: borderColor,
               highlight: { background: color, border: "#fff" } },
      font: { color: "#000", size: 11, face: "Arial" },
      shape: isExternal ? "ellipse" : "box",
      size: (isHub ? 22 : 14) + (isEntry ? EP_SIZE_BOOST : 0),
      borderWidth: borderWidth,
    };
  });

  const nodes = Object.values(nodeMap);
  const edges = EDGES_RAW.map(e => {
    const src = e[0], tgt = e[1], etype = e[2] || "use";
    const ecolor = EDGE_COLORS[etype] || "#666";
    return {
      from: nodeMap[src].id,
      to: nodeMap[tgt].id,
      arrows: "to",
      label: etype,
      font: { color: "#888", size: 9, align: "middle",
              background: "rgba(30,30,30,0.7)", strokeWidth: 0 },
      color: { color: ecolor, highlight: "#fff", opacity: 0.7 },
      width: 1,
      smooth: { type: "continuous" },
    };
  });

  const container = document.getElementById("graph");
  const data = { nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) };
  const options = {
    physics: {
      enabled: true,
      stabilization: { iterations: 200, updateInterval: 25 },
      barnesHut: { gravitationalConstant: -9000, springLength: 140,
                   springConstant: 0.04, damping: 0.3 },
    },
    interaction: { hover: true, tooltipDelay: 120, zoomView: true,
                   dragView: true, navigationButtons: false },
    edges: { smooth: { type: "continuous" } },
    nodes: { borderWidth: 1, font: { color: "#000000" } },
  };
  const network = new vis.Network(container, data, options);

  const status = document.getElementById("status");
  network.on("stabilizationProgress", p => {
    status.textContent = "Stabilizing… " + Math.round(100 * p.iterations / p.total) + "%";
  });
  network.on("stabilizationIterationsDone", () => {
    status.textContent = "Ready · scroll=zoom · drag=pan · click=highlight";
    setTimeout(() => { status.textContent = ""; }, 4000);
  });

  function fitGraph() { network.fit({ animation: { duration: 400 } }); }
  let physicsOn = true;
  function togglePhysics() {
    physicsOn = !physicsOn;
    network.setOptions({ physics: { enabled: physicsOn } });
  }
  function exportPng() {
    const canvas = container.getElementsByTagName("canvas")[0];
    if (!canvas) return;
    const a = document.createElement("a");
    a.href = canvas.toDataURL("image/png");
    a.download = "{PROJECT_NAME}-graph.png";
    a.click();
  }
</script>
</body>
</html>
