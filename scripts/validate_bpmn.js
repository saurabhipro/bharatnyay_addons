const BpmnModdle = require('bpmn-moddle').default || require('bpmn-moddle');
const fs = require('fs');

const path = process.argv[2];
const moddle = new BpmnModdle();
const xml = fs.readFileSync(path, 'utf8');

moddle.fromXML(xml).then((result) => {
  console.log('PARSE OK');
  if (result.warnings && result.warnings.length) {
    result.warnings.forEach((w) => console.log('WARN:', w.message));
  }
  const proc = result.rootElement.rootElements.find((e) => e.$type === 'bpmn:Process');
  const lanes = proc.laneSets?.[0]?.lanes || [];
  const laneRefs = new Set();
  lanes.forEach((lane) => {
    (lane.flowNodeRef || []).forEach((ref) => laneRefs.add(ref.id));
  });
  const topLevel = (proc.flowElements || []).filter((e) => e.$type !== 'bpmn:SequenceFlow');
  const missing = topLevel.filter((e) => !laneRefs.has(e.id));
  const dangling = [...laneRefs].filter(
    (id) => !topLevel.some((e) => e.id === id)
  );
  console.log('Top-level nodes:', topLevel.length);
  console.log('Not in any lane:', missing.map((e) => e.id).join(', ') || 'none');
  console.log('Dangling lane refs:', dangling.join(', ') || 'none');
}).catch((err) => {
  console.log('PARSE ERROR:', err.message);
  if (err.warnings) err.warnings.forEach((w) => console.log('WARN:', w.message));
  process.exit(1);
});
