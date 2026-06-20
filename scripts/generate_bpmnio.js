#!/usr/bin/env node
/**
 * Generate bpmn.io-compatible BPMN with lane colors and expandable subprocesses.
 */
const fs = require('fs');

const outPath = process.argv[2];
if (!outPath) {
  console.error('Usage: node generate_bpmnio.js <output.bpmn>');
  process.exit(1);
}

const laneColors = {
  Lane_Central: { lane: '#E3F2FD', fill: '#BBDEFB', stroke: '#1565C0' },
  Lane_Area: { lane: '#E8F5E9', fill: '#C8E6C9', stroke: '#2E7D32' },
  Lane_State: { lane: '#FFF8E1', fill: '#FFECB3', stroke: '#F57F17' },
  Lane_Committees: { lane: '#F3E5F5', fill: '#E1BEE7', stroke: '#6A1B9A' },
  Lane_HQ: { lane: '#E0F2F1', fill: '#B2DFDB', stroke: '#00695C' },
  Lane_PAP: { lane: '#FFF3E0', fill: '#FFE0B2', stroke: '#E65100' },
  Lane_Tribunal: { lane: '#FFEBEE', fill: '#FFCDD2', stroke: '#C62828' },
};

const subprocessColor = { fill: '#E8EAF6', stroke: '#3949AB' };
const startColor = { fill: '#A5D6A7', stroke: '#1B5E20' };
const endColor = { fill: '#EF9A9A', stroke: '#B71C1C' };
const gatewayColor = { fill: '#FFF59D', stroke: '#F9A825' };

const lanes = [
  { id: 'Lane_Central', name: 'Ministry of Coal / Central Govt', nodes: ['Task_S4_Notification', 'Task_S7_Notification', 'Task_Handle_Objections', 'Task_S9_Declaration'] },
  { id: 'Lane_Area', name: 'Area L and R / Project Office', nodes: ['StartEvent_1', 'Task_Certificates_1ABC', 'Task_Exploration_2A', 'SubProcess_DroneSurvey', 'SubProcess_AssetSurvey', 'Task_Prepare_Comp_Proposal', 'SubProcess_Employment', 'SubProcess_HousePlot', 'SubProcess_CropComp', 'Task_Payment_Attempt', 'Task_Initiate_PTT_Deposit', 'Task_Deposit_PTT'] },
  { id: 'Lane_State', name: 'State Revenue / SDM / Collector', nodes: ['Task_State_Gazette'] },
  { id: 'Lane_Committees', name: 'Committees', nodes: ['Task_Joint_Committee_Survey', 'Task_ASC_Review', 'Task_DRRC_Meeting', 'Task_Standing_Committee'] },
  { id: 'Lane_HQ', name: 'SECL HQ', nodes: ['Task_HQ_Scrutiny_Comp', 'Task_HQ_Approval_Comp', 'Task_HQ_Scrutiny_Emp', 'Task_HQ_Approval_PTT'] },
  { id: 'Lane_PAP', name: 'PAP / Landowner', nodes: ['Task_Objection_Window', 'Gateway_Payment_Consent', 'Task_Receive_Compensation'] },
  { id: 'Lane_Tribunal', name: 'Part-Time Tribunal Bilaspur', nodes: ['Task_PTT_Hold_Funds', 'EndEvent_1'] },
];

const subprocesses = {
  SubProcess_DroneSurvey: {
    name: 'SOP 2 Drone Survey',
    steps: ['Procure VHR satellite imagery', 'Drone survey with GPS coordinates', 'Generate ortho-mosaic and 3D models'],
  },
  SubProcess_AssetSurvey: {
    name: 'SOP 3 Asset Survey',
    steps: ['Constitute joint committee', 'Socio-economic survey and Measurement Book', 'Videography and geotags', 'Calculate land and asset compensation', 'Verify B-1 P-II Statement V and VI'],
  },
  SubProcess_Employment: {
    name: 'SOP 5-8 Employment',
    steps: ['Prepare Descending Order List', 'Issue notice and Nomination Form', 'Receive and register nomination', 'Area Screening Committee verification', 'State authority verification', 'Area GM forwards to HQ'],
  },
  SubProcess_HousePlot: {
    name: 'SOP 7 House Plot / Cash R&R',
    steps: ['Family survey during asset survey', 'Determine PAF eligibility', 'Allot house plot or cash compensation', 'Physical verification and affidavit'],
  },
  SubProcess_CropComp: {
    name: 'SOP 9 Crop Compensation',
    steps: ['Area committee inspection', 'SDM demand note and calculation', 'Joint site inspection and photos', 'HQ and Standing Committee approval'],
  },
};

const flowOrder = [
  'StartEvent_1', 'Task_Certificates_1ABC', 'Task_S4_Notification', 'Task_State_Gazette', 'Task_Exploration_2A', 'Task_S7_Notification', 'Task_Objection_Window', 'Task_Handle_Objections', 'Task_S9_Declaration', 'SubProcess_DroneSurvey', 'SubProcess_AssetSurvey', 'Task_Joint_Committee_Survey', 'Task_Prepare_Comp_Proposal', 'Task_ASC_Review', 'Task_HQ_Scrutiny_Comp', 'Task_Standing_Committee', 'Task_HQ_Approval_Comp', 'Task_DRRC_Meeting', 'SubProcess_Employment', 'Task_HQ_Scrutiny_Emp', 'SubProcess_HousePlot', 'SubProcess_CropComp', 'Task_Payment_Attempt', 'Gateway_Payment_Consent',
];

const nodeToLane = {};
lanes.forEach((lane) => lane.nodes.forEach((n) => { nodeToLane[n] = lane.id; }));

const xMap = {};
flowOrder.forEach((id, i) => { xMap[id] = 220 + i * 170; });
xMap.Task_Receive_Compensation = xMap.Gateway_Payment_Consent + 170;
xMap.Task_Initiate_PTT_Deposit = xMap.Gateway_Payment_Consent + 170;
xMap.Task_HQ_Approval_PTT = xMap.Task_Initiate_PTT_Deposit + 170;
xMap.Task_Deposit_PTT = xMap.Task_HQ_Approval_PTT + 170;
xMap.Task_PTT_Hold_Funds = xMap.Task_Deposit_PTT + 170;
xMap.EndEvent_1 = Math.max(xMap.Task_Receive_Compensation, xMap.Task_PTT_Hold_Funds) + 170;

const laneH = 140;
const laneW = 5200;
const laneX = 160;

function shapeBounds(id) {
  const laneId = nodeToLane[id];
  const laneIndex = lanes.findIndex((l) => l.id === laneId);
  const ly = 80 + laneIndex * laneH;
  const x = xMap[id] || 220;
  if (id.startsWith('Start')) return { x, y: ly + 52, w: 36, h: 36 };
  if (id.startsWith('End')) return { x, y: ly + 52, w: 36, h: 36 };
  if (id.startsWith('Gateway')) return { x, y: ly + 45, w: 50, h: 50 };
  if (id.startsWith('SubProcess')) return { x, y: ly + 30, w: 130, h: 80 };
  return { x, y: ly + 35, w: 120, h: 70 };
}

function nodeColor(id) {
  if (id.startsWith('Start')) return startColor;
  if (id.startsWith('End')) return endColor;
  if (id.startsWith('Gateway')) return gatewayColor;
  if (id.startsWith('SubProcess')) return subprocessColor;
  const lane = nodeToLane[id];
  return laneColors[lane] || { fill: '#FFFFFF', stroke: '#333333' };
}

function buildSubProcessXml(spId, incoming, outgoing) {
  const sp = subprocesses[spId];
  const steps = sp.steps;
  const prefix = spId.replace('SubProcess_', '');
  let xml = `    <bpmn:subProcess id="${spId}" name="${sp.name}">\n`;
  xml += `      <bpmn:incoming>${incoming}</bpmn:incoming>\n`;
  xml += `      <bpmn:outgoing>${outgoing}</bpmn:outgoing>\n`;
  const startId = `Start_${prefix}`;
  const endId = `End_${prefix}`;
  xml += `      <bpmn:startEvent id="${startId}" name="Start"><bpmn:outgoing>${prefix}_F01</bpmn:outgoing></bpmn:startEvent>\n`;
  steps.forEach((step, i) => {
    const taskId = `Task_${prefix}_${i + 1}`;
    const inFlow = `${prefix}_F${String(i + 1).padStart(2, '0')}`;
    const outFlow = `${prefix}_F${String(i + 2).padStart(2, '0')}`;
    xml += `      <bpmn:task id="${taskId}" name="${step}"><bpmn:incoming>${inFlow}</bpmn:incoming><bpmn:outgoing>${outFlow}</bpmn:outgoing></bpmn:task>\n`;
  });
  const endInFlow = `${prefix}_F${String(steps.length + 1).padStart(2, '0')}`;
  xml += `      <bpmn:endEvent id="${endId}" name="Done"><bpmn:incoming>${endInFlow}</bpmn:incoming></bpmn:endEvent>\n`;
  xml += `      <bpmn:sequenceFlow id="${prefix}_F01" sourceRef="${startId}" targetRef="Task_${prefix}_1"/>\n`;
  for (let i = 1; i < steps.length; i += 1) {
    const fid = `${prefix}_F${String(i + 1).padStart(2, '0')}`;
    xml += `      <bpmn:sequenceFlow id="${fid}" sourceRef="Task_${prefix}_${i}" targetRef="Task_${prefix}_${i + 1}"/>\n`;
  }
  xml += `      <bpmn:sequenceFlow id="${endInFlow}" sourceRef="Task_${prefix}_${steps.length}" targetRef="${endId}"/>\n`;
  xml += `    </bpmn:subProcess>`;
  return xml;
}

function colorAttrs(c) {
  return ` bioc:stroke="${c.stroke}" bioc:fill="${c.fill}"`;
}

function buildSubProcessPlaneDi(spId) {
  const sp = subprocesses[spId];
  const prefix = spId.replace('SubProcess_', '');
  const steps = sp.steps;
  const planeId = `${spId}_plane`;
  const diagramId = `BPMNDiagram_${prefix}`;
  const stepW = 150;
  const taskH = 80;
  const baseX = 180;
  const baseY = 120;
  const gap = 180;

  const startId = `Start_${prefix}`;
  const endId = `End_${prefix}`;
  const startX = baseX;
  const endX = baseX + (steps.length + 1) * gap;

  let shapes = `
      <bpmndi:BPMNShape id="${startId}_di" bpmnElement="${startId}"${colorAttrs(startColor)}>
        <dc:Bounds x="${startX}" y="${baseY + 7}" width="36" height="36"/>
      </bpmndi:BPMNShape>`;

  steps.forEach((_, i) => {
    const taskId = `Task_${prefix}_${i + 1}`;
    const x = baseX + (i + 1) * gap;
    shapes += `
      <bpmndi:BPMNShape id="${taskId}_di" bpmnElement="${taskId}"${colorAttrs(subprocessColor)}>
        <dc:Bounds x="${x}" y="${baseY}" width="${stepW}" height="${taskH}"/>
      </bpmndi:BPMNShape>`;
  });

  shapes += `
      <bpmndi:BPMNShape id="${endId}_di" bpmnElement="${endId}"${colorAttrs(endColor)}>
        <dc:Bounds x="${endX}" y="${baseY + 7}" width="36" height="36"/>
      </bpmndi:BPMNShape>`;

  function spCenter(nodeId) {
    if (nodeId === startId) return { x: startX + 18, y: baseY + 25 };
    if (nodeId === endId) return { x: endX + 18, y: baseY + 25 };
    const idx = parseInt(nodeId.split('_').pop(), 10);
    const x = baseX + idx * gap;
    return { x: x + stepW / 2, y: baseY + taskH / 2 };
  }

  const nodeIds = [startId, ...steps.map((_, i) => `Task_${prefix}_${i + 1}`), endId];
  let edges = '';
  for (let i = 0; i < steps.length + 1; i += 1) {
    const fid = i === 0
      ? `${prefix}_F01`
      : `${prefix}_F${String(i + 1).padStart(2, '0')}`;
    const s = spCenter(nodeIds[i]);
    const t = spCenter(nodeIds[i + 1]);
    edges += `
      <bpmndi:BPMNEdge id="${fid}_di" bpmnElement="${fid}" bioc:stroke="#546E7A">
        <di:waypoint x="${s.x}" y="${s.y}"/>
        <di:waypoint x="${t.x}" y="${t.y}"/>
      </bpmndi:BPMNEdge>`;
  }

  return `
  <bpmndi:BPMNDiagram id="${diagramId}">
    <bpmndi:BPMNPlane id="${planeId}" bpmnElement="${spId}">${shapes}${edges}
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>`;
}


let laneShapes = '';
lanes.forEach((lane, idx) => {
  const y = 80 + idx * laneH;
  const c = laneColors[lane.id];
  laneShapes += `
      <bpmndi:BPMNShape id="${lane.id}_di" bpmnElement="${lane.id}" isHorizontal="true"${colorAttrs({ fill: c.lane, stroke: c.stroke })}>
        <dc:Bounds x="${laneX}" y="${y}" width="${laneW}" height="${laneH}"/>
      </bpmndi:BPMNShape>`;
});

let nodeShapes = '';
Object.keys(nodeToLane).forEach((nodeId) => {
  const b = shapeBounds(nodeId);
  const c = nodeColor(nodeId);
  let extra = colorAttrs(c);
  if (nodeId.startsWith('Gateway')) extra += ' isMarkerVisible="true"';
  if (nodeId.startsWith('SubProcess')) extra += ' isExpanded="false"';
  nodeShapes += `
      <bpmndi:BPMNShape id="${nodeId}_di" bpmnElement="${nodeId}"${extra}>
        <dc:Bounds x="${b.x}" y="${b.y}" width="${b.w}" height="${b.h}"/>
      </bpmndi:BPMNShape>`;
});

const flows = [
  ['Flow_01', 'StartEvent_1', 'Task_Certificates_1ABC'],
  ['Flow_02', 'Task_Certificates_1ABC', 'Task_S4_Notification'],
  ['Flow_03', 'Task_S4_Notification', 'Task_State_Gazette'],
  ['Flow_04', 'Task_State_Gazette', 'Task_Exploration_2A'],
  ['Flow_05', 'Task_Exploration_2A', 'Task_S7_Notification'],
  ['Flow_06', 'Task_S7_Notification', 'Task_Objection_Window'],
  ['Flow_07', 'Task_Objection_Window', 'Task_Handle_Objections'],
  ['Flow_08', 'Task_Handle_Objections', 'Task_S9_Declaration'],
  ['Flow_09', 'Task_S9_Declaration', 'SubProcess_DroneSurvey'],
  ['Flow_10', 'SubProcess_DroneSurvey', 'SubProcess_AssetSurvey'],
  ['Flow_11', 'SubProcess_AssetSurvey', 'Task_Joint_Committee_Survey'],
  ['Flow_12', 'Task_Joint_Committee_Survey', 'Task_Prepare_Comp_Proposal'],
  ['Flow_13', 'Task_Prepare_Comp_Proposal', 'Task_ASC_Review'],
  ['Flow_14', 'Task_ASC_Review', 'Task_HQ_Scrutiny_Comp'],
  ['Flow_15', 'Task_HQ_Scrutiny_Comp', 'Task_Standing_Committee'],
  ['Flow_16', 'Task_Standing_Committee', 'Task_HQ_Approval_Comp'],
  ['Flow_17', 'Task_HQ_Approval_Comp', 'Task_DRRC_Meeting'],
  ['Flow_18', 'Task_DRRC_Meeting', 'SubProcess_Employment'],
  ['Flow_19', 'SubProcess_Employment', 'Task_HQ_Scrutiny_Emp'],
  ['Flow_21', 'Task_HQ_Scrutiny_Emp', 'SubProcess_HousePlot'],
  ['Flow_22', 'SubProcess_HousePlot', 'SubProcess_CropComp'],
  ['Flow_23', 'SubProcess_CropComp', 'Task_Payment_Attempt'],
  ['Flow_24', 'Task_Payment_Attempt', 'Gateway_Payment_Consent'],
  ['Flow_25_Yes', 'Gateway_Payment_Consent', 'Task_Receive_Compensation'],
  ['Flow_25_No', 'Gateway_Payment_Consent', 'Task_Initiate_PTT_Deposit'],
  ['Flow_26', 'Task_Receive_Compensation', 'EndEvent_1'],
  ['Flow_27', 'Task_Initiate_PTT_Deposit', 'Task_HQ_Approval_PTT'],
  ['Flow_28', 'Task_HQ_Approval_PTT', 'Task_Deposit_PTT'],
  ['Flow_29', 'Task_Deposit_PTT', 'Task_PTT_Hold_Funds'],
  ['Flow_30', 'Task_PTT_Hold_Funds', 'EndEvent_1'],
];

function center(id) {
  const b = shapeBounds(id);
  return { x: b.x + b.w / 2, y: b.y + b.h / 2 };
}

let flowEdges = '';
flows.forEach(([fid, src, tgt]) => {
  const s = center(src);
  const t = center(tgt);
  flowEdges += `
      <bpmndi:BPMNEdge id="${fid}_di" bpmnElement="${fid}" bioc:stroke="#546E7A">
        <di:waypoint x="${s.x}" y="${s.y}"/>
        <di:waypoint x="${t.x}" y="${t.y}"/>
      </bpmndi:BPMNEdge>`;
});

const laneSetXml = lanes.map((lane) => `
      <bpmn:lane id="${lane.id}" name="${lane.name}">
${lane.nodes.map((n) => `        <bpmn:flowNodeRef>${n}</bpmn:flowNodeRef>`).join('\n')}
      </bpmn:lane>`).join('');

const subprocessXml = [
  buildSubProcessXml('SubProcess_DroneSurvey', 'Flow_09', 'Flow_10'),
  buildSubProcessXml('SubProcess_AssetSurvey', 'Flow_10', 'Flow_11'),
  buildSubProcessXml('SubProcess_Employment', 'Flow_18', 'Flow_19'),
  buildSubProcessXml('SubProcess_HousePlot', 'Flow_21', 'Flow_22'),
  buildSubProcessXml('SubProcess_CropComp', 'Flow_22', 'Flow_23'),
].join('\n');

const subprocessPlaneDi = Object.keys(subprocesses).map(buildSubProcessPlaneDi).join('');

const xml = `<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
  xmlns:di="http://www.omg.org/spec/DD/20100524/DI"
  xmlns:bioc="http://bpmn.io/schema/bpmn/biocolor/1.0"
  id="Definitions_LR_SOP"
  targetNamespace="http://bpmn.io/schema/bpmn"
  exporter="bpmn.io"
  exporterVersion="17.0.0">
  <bpmn:process id="LR_Master_Process" name="SECL L and R Master SOP" isExecutable="false">
    <bpmn:laneSet id="LaneSet_1">${laneSetXml}
    </bpmn:laneSet>
    <bpmn:startEvent id="StartEvent_1" name="Project identified"><bpmn:outgoing>Flow_01</bpmn:outgoing></bpmn:startEvent>
    <bpmn:task id="Task_Certificates_1ABC" name="Certificates 1A/1B/1C"><bpmn:incoming>Flow_01</bpmn:incoming><bpmn:outgoing>Flow_02</bpmn:outgoing></bpmn:task>
    <bpmn:task id="Task_S4_Notification" name="Sec 4(1) prospecting notification"><bpmn:incoming>Flow_02</bpmn:incoming><bpmn:outgoing>Flow_03</bpmn:outgoing></bpmn:task>
    <bpmn:task id="Task_State_Gazette" name="State Gazette republication"><bpmn:incoming>Flow_03</bpmn:incoming><bpmn:outgoing>Flow_04</bpmn:outgoing></bpmn:task>
    <bpmn:task id="Task_Exploration_2A" name="Prospecting Certificate 2A"><bpmn:incoming>Flow_04</bpmn:incoming><bpmn:outgoing>Flow_05</bpmn:outgoing></bpmn:task>
    <bpmn:task id="Task_S7_Notification" name="Sec 7(1) acquisition notification"><bpmn:incoming>Flow_05</bpmn:incoming><bpmn:outgoing>Flow_06</bpmn:outgoing></bpmn:task>
    <bpmn:task id="Task_Objection_Window" name="30-day objection window"><bpmn:incoming>Flow_06</bpmn:incoming><bpmn:outgoing>Flow_07</bpmn:outgoing></bpmn:task>
    <bpmn:task id="Task_Handle_Objections" name="Coal Controller inquiry"><bpmn:incoming>Flow_07</bpmn:incoming><bpmn:outgoing>Flow_08</bpmn:outgoing></bpmn:task>
    <bpmn:task id="Task_S9_Declaration" name="Sec 9(1) declaration"><bpmn:incoming>Flow_08</bpmn:incoming><bpmn:outgoing>Flow_09</bpmn:outgoing></bpmn:task>
${subprocessXml}
    <bpmn:task id="Task_Joint_Committee_Survey" name="Joint committee certifies MB"><bpmn:incoming>Flow_11</bpmn:incoming><bpmn:outgoing>Flow_12</bpmn:outgoing></bpmn:task>
    <bpmn:task id="Task_Prepare_Comp_Proposal" name="Compensation proposal"><bpmn:incoming>Flow_12</bpmn:incoming><bpmn:outgoing>Flow_13</bpmn:outgoing></bpmn:task>
    <bpmn:task id="Task_ASC_Review" name="ASC review"><bpmn:incoming>Flow_13</bpmn:incoming><bpmn:outgoing>Flow_14</bpmn:outgoing></bpmn:task>
    <bpmn:task id="Task_HQ_Scrutiny_Comp" name="HQ L and R scrutiny"><bpmn:incoming>Flow_14</bpmn:incoming><bpmn:outgoing>Flow_15</bpmn:outgoing></bpmn:task>
    <bpmn:task id="Task_Standing_Committee" name="Standing Committee"><bpmn:incoming>Flow_15</bpmn:incoming><bpmn:outgoing>Flow_16</bpmn:outgoing></bpmn:task>
    <bpmn:task id="Task_HQ_Approval_Comp" name="DTPP approval"><bpmn:incoming>Flow_16</bpmn:incoming><bpmn:outgoing>Flow_17</bpmn:outgoing></bpmn:task>
    <bpmn:task id="Task_DRRC_Meeting" name="SOP 4 DRRC meeting"><bpmn:incoming>Flow_17</bpmn:incoming><bpmn:outgoing>Flow_18</bpmn:outgoing></bpmn:task>
    <bpmn:task id="Task_HQ_Scrutiny_Emp" name="HQ employment approval"><bpmn:incoming>Flow_19</bpmn:incoming><bpmn:outgoing>Flow_21</bpmn:outgoing></bpmn:task>
    <bpmn:task id="Task_Payment_Attempt" name="Attempt compensation payment"><bpmn:incoming>Flow_23</bpmn:incoming><bpmn:outgoing>Flow_24</bpmn:outgoing></bpmn:task>
    <bpmn:exclusiveGateway id="Gateway_Payment_Consent" name="Consent?"><bpmn:incoming>Flow_24</bpmn:incoming><bpmn:outgoing>Flow_25_Yes</bpmn:outgoing><bpmn:outgoing>Flow_25_No</bpmn:outgoing></bpmn:exclusiveGateway>
    <bpmn:task id="Task_Receive_Compensation" name="PAP receives payment"><bpmn:incoming>Flow_25_Yes</bpmn:incoming><bpmn:outgoing>Flow_26</bpmn:outgoing></bpmn:task>
    <bpmn:task id="Task_Initiate_PTT_Deposit" name="Initiate PTT deposit"><bpmn:incoming>Flow_25_No</bpmn:incoming><bpmn:outgoing>Flow_27</bpmn:outgoing></bpmn:task>
    <bpmn:task id="Task_HQ_Approval_PTT" name="HQ PTT approval"><bpmn:incoming>Flow_27</bpmn:incoming><bpmn:outgoing>Flow_28</bpmn:outgoing></bpmn:task>
    <bpmn:task id="Task_Deposit_PTT" name="Deposit in PTT"><bpmn:incoming>Flow_28</bpmn:incoming><bpmn:outgoing>Flow_29</bpmn:outgoing></bpmn:task>
    <bpmn:task id="Task_PTT_Hold_Funds" name="PTT holds funds"><bpmn:incoming>Flow_29</bpmn:incoming><bpmn:outgoing>Flow_30</bpmn:outgoing></bpmn:task>
    <bpmn:endEvent id="EndEvent_1" name="Process closed"><bpmn:incoming>Flow_26</bpmn:incoming><bpmn:incoming>Flow_30</bpmn:incoming></bpmn:endEvent>
${flows.map(([id, s, t]) => `    <bpmn:sequenceFlow id="${id}" sourceRef="${s}" targetRef="${t}"/>`).join('\n')}
  </bpmn:process>
  <bpmndi:BPMNDiagram id="BPMNDiagram_1">
    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="LR_Master_Process">${laneShapes}${nodeShapes}${flowEdges}
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>${subprocessPlaneDi}
</bpmn:definitions>`;

fs.writeFileSync(outPath, xml);
console.log('Written:', outPath);
