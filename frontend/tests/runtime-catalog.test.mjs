import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import { catalogs } from './contract-fixtures.mjs';
const source = fs.readFileSync(new URL('../src/app/core/runtime-catalog.ts', import.meta.url),'utf8');
const compiled = ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const runtime = {};
vm.runInThisContext('(function(exports,require){'+compiled+'\n})')(runtime,()=>({environment:{apiUrl:'/api'}}));
test('el catálogo remoto agrega prioridades y actualiza parámetros antes del arranque', async () => {
  const previous=globalThis.fetch;
  const settings=runtime.simulationSettings;
  try {
    const modified=structuredClone(catalogs);
    modified.priorities.push({code:'urgent',label:'Urgente',rank:0});
    modified.parameters.low_fuel_threshold=15;
    modified.parameters.simulation.confirmedFuelPercent=80;
    globalThis.fetch=async () => ({ok:true,json:async()=>modified});
    await runtime.loadCatalogs();
    assert.equal(runtime.priorityLabel('urgent'),'Urgente');
    assert.equal(runtime.lowFuelThreshold,15);
    assert.equal(settings.confirmedFuelPercent,80);
    assert.equal(runtime.simulationSettings,settings);
  } finally {globalThis.fetch=previous;}
});
test('un catálogo no disponible detiene el arranque en vez de inventar valores', async () => {
  const previous=globalThis.fetch;
  try {
    globalThis.fetch=async () => ({ok:false});
    await assert.rejects(runtime.loadCatalogs(),/PostgreSQL/);
  } finally {globalThis.fetch=previous;}
});
