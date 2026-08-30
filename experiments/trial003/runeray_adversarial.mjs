import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

function canon(value) {
  return JSON.stringify(value);
}

function record(results, id, condition, details = {}) {
  results.push({ id, pass: !!condition, ...details });
  return !!condition;
}

const root = process.argv[2];
const output = process.argv[3] ?? 'runeray_v07_adversarial.json';
if (!root) throw new Error('usage: node runeray_adversarial.mjs <runeray-root> [output]');

const { RuneRayEngine } = await import(pathToFileURL(path.join(root, 'src/core/RuneRayEngine.js')).href);
const results = [];

// Positive control: built-in state should survive fresh restore and identical continuation.
{
  const a = new RuneRayEngine(null, { headless: true, seed: 77 });
  a.camera.x = 2.25;
  a.controller.move.forward = true;
  a.advance(a.fixedStep / 2);
  const snap = a.serializeCoreState();
  const b = new RuneRayEngine(null, { headless: true, seed: 1 });
  b.restoreCoreState(snap);
  const immediateEqual = canon(a.serializeCoreState()) === canon(b.serializeCoreState());
  a.advance(a.fixedStep / 2);
  b.advance(b.fixedStep / 2);
  const continuedEqual = canon(a.serializeCoreState()) === canon(b.serializeCoreState());
  record(results, 'builtin_fresh_restore_continuation', immediateEqual && continuedEqual, { immediateEqual, continuedEqual });
}

// Adversary 1: entity Map insertion history is absent from the sorted snapshot but controls update order.
{
  const updateA = (_dt, _self, engine) => { engine.entities.get('b').state.v += 1; };
  const updateB = (_dt, _self, engine) => { engine.entities.get('a').state.v = engine.entities.get('b').state.v; };
  const left = new RuneRayEngine(null, { headless: true, seed: 5 });
  const right = new RuneRayEngine(null, { headless: true, seed: 5 });
  left.entities.add({ id: 'a', state: { v: 0 }, update: updateA });
  left.entities.add({ id: 'b', state: { v: 0 }, update: updateB });
  right.entities.add({ id: 'b', state: { v: 0 }, update: updateB });
  right.entities.add({ id: 'a', state: { v: 0 }, update: updateA });
  const beforeEqual = canon(left.serializeCoreState()) === canon(right.serializeCoreState());
  left.update(left.fixedStep);
  right.update(right.fixedStep);
  const afterEqual = canon(left.serializeCoreState()) === canon(right.serializeCoreState());
  record(results, 'entity_insertion_history_transition_equivalence', beforeEqual && afterEqual, {
    beforeEqual,
    afterEqual,
    left: left.entities.serialize(),
    right: right.entities.serialize(),
  });
}

// Adversary 2: addSystem permits hidden mutable state that is not represented by core snapshots.
{
  const makeSystem = phase => ({
    phase,
    update(_dt, engine) { engine.camera.x += this.phase; this.phase += 1; },
  });
  const left = new RuneRayEngine(null, { headless: true, seed: 6 });
  const right = new RuneRayEngine(null, { headless: true, seed: 6 });
  left.addSystem(makeSystem(0));
  right.addSystem(makeSystem(1));
  const beforeEqual = canon(left.serializeCoreState()) === canon(right.serializeCoreState());
  left.update(left.fixedStep);
  right.update(right.fixedStep);
  const afterEqual = canon(left.serializeCoreState()) === canon(right.serializeCoreState());
  record(results, 'custom_system_hidden_state_transition_equivalence', beforeEqual && afterEqual, {
    beforeEqual,
    afterEqual,
    leftCameraX: left.camera.x,
    rightCameraX: right.camera.x,
  });
}

// Adversary 3: restoring an older snapshot into a dirty engine leaves later entities resident.
{
  const source = new RuneRayEngine(null, { headless: true, seed: 7 });
  source.entities.add({ id: 'kept', state: { n: 1 } });
  const snap = source.serializeCoreState();
  const target = new RuneRayEngine(null, { headless: true, seed: 7 });
  target.entities.add({ id: 'kept', state: { n: 1 } });
  target.entities.add({ id: 'later', state: { n: 99 } });
  target.restoreCoreState(snap);
  const roundtripEqual = canon(snap) === canon(target.serializeCoreState());
  record(results, 'restore_removes_post_snapshot_entities', roundtripEqual, {
    roundtripEqual,
    restoredEntities: target.entities.serialize(),
  });
}

// Adversary 4: entity transition behavior is causal but omitted from snapshots.
{
  const source = new RuneRayEngine(null, { headless: true, seed: 8 });
  source.entities.add({
    id: 'clock',
    state: { n: 0 },
    update: (_dt, self) => { self.state.n += 1; },
  });
  const snap = source.serializeCoreState();
  const restored = new RuneRayEngine(null, { headless: true, seed: 8 });
  restored.restoreCoreState(snap);
  const beforeEqual = canon(source.serializeCoreState()) === canon(restored.serializeCoreState());
  source.update(source.fixedStep);
  restored.update(restored.fixedStep);
  const afterEqual = canon(source.serializeCoreState()) === canon(restored.serializeCoreState());
  record(results, 'fresh_restore_preserves_entity_transition_behavior', beforeEqual && afterEqual, {
    beforeEqual,
    afterEqual,
    sourceClock: source.entities.get('clock')?.state,
    restoredClock: restored.entities.get('clock')?.state,
  });
}

// Positive control: the explicit state-adapter mechanism can carry custom mutable system state
// when behavior/configuration is re-established outside the snapshot contract.
{
  const makeAdaptedSystem = phase => ({
    phase,
    update(_dt, engine) { engine.camera.x += this.phase; this.phase += 1; },
    serialize() { return { phase: this.phase }; },
    restore(data = {}) { this.phase = Number(data.phase ?? 0); },
  });
  const source = new RuneRayEngine(null, { headless: true, seed: 9 });
  const s1 = makeAdaptedSystem(3);
  source.addSystem(s1);
  source.registerStateAdapter('trial003-custom', s1);
  const snap = source.serializeCoreState();

  const restored = new RuneRayEngine(null, { headless: true, seed: 9 });
  const s2 = makeAdaptedSystem(0);
  restored.addSystem(s2);
  restored.registerStateAdapter('trial003-custom', s2);
  restored.restoreCoreState(snap);
  const beforeEqual = canon(source.serializeCoreState()) === canon(restored.serializeCoreState());
  source.update(source.fixedStep);
  restored.update(restored.fixedStep);
  const afterEqual = canon(source.serializeCoreState()) === canon(restored.serializeCoreState());
  record(results, 'explicit_state_adapter_preserves_custom_system_state', beforeEqual && afterEqual, {
    beforeEqual,
    afterEqual,
    sourcePhase: s1.phase,
    restoredPhase: s2.phase,
  });
}

const evidence = {
  subject: 'RuneRay v0.7.0',
  root,
  invariant: 'represented-equivalent state + same cause => represented-equivalent successor',
  results,
  failures: results.filter(r => !r.pass).map(r => r.id),
};
await fs.writeFile(output, JSON.stringify(evidence, null, 2) + '\n');
console.log(JSON.stringify(evidence, null, 2));

// The adversary is expected to expose failures in the frozen target. Do not make CI red merely
// because the subject is falsified; require the witness set itself to be present and positive controls to pass.
const requiredFailures = new Set([
  'entity_insertion_history_transition_equivalence',
  'custom_system_hidden_state_transition_equivalence',
  'restore_removes_post_snapshot_entities',
  'fresh_restore_preserves_entity_transition_behavior',
]);
const observedFailures = new Set(evidence.failures);
if (!results.find(r => r.id === 'builtin_fresh_restore_continuation')?.pass) throw new Error('positive control failed');
if (!results.find(r => r.id === 'explicit_state_adapter_preserves_custom_system_state')?.pass) throw new Error('state-adapter positive control failed');
for (const id of requiredFailures) if (!observedFailures.has(id)) throw new Error(`expected frozen-target witness not reproduced: ${id}`);
