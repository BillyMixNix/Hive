// Offline syntax inspection only. Never eval/import/execute the supplied source.
const fs = require('node:fs');
const acorn = require('./vendor/acorn.cjs');
try {
  const {source, mode} = JSON.parse(fs.readFileSync(0, 'utf8'));
  const tree = acorn.parse(source, {
    ecmaVersion: 2022, sourceType: mode === 'module' ? 'module' : 'script',
    allowReturnOutsideFunction: mode === 'handler', locations: true
  });
  // Acorn offsets are UTF-16; Python offsets must be Unicode code points.
  const offset = n => Array.from(source.slice(0, n)).length;
  const symbols = [], globals = [], declarations = [], calls = [], bound = new Set();
  function names(pattern) {
    if (!pattern) return [];
    if (pattern.type === 'Identifier') return [pattern.name];
    if (pattern.type === 'RestElement') return names(pattern.argument);
    if (pattern.type === 'AssignmentPattern') return names(pattern.left);
    if (pattern.type === 'ArrayPattern') return pattern.elements.flatMap(names);
    if (pattern.type === 'ObjectPattern') return pattern.properties.flatMap(p => names(p.value || p.argument));
    return [];
  }
  for (const statement of tree.body) {
    const node = statement.declaration || statement;
    if (['FunctionDeclaration', 'ClassDeclaration'].includes(node.type) && node.id) {
      globals.push(node.id.name);
      symbols.push({name: node.id.name, start: offset(statement.start), end: offset(statement.end)});
    } else if (node.type === 'VariableDeclaration') {
      for (const decl of node.declarations) globals.push(...names(decl.id));
      const decl = node.declarations[0];
      if (node.declarations.length === 1 && decl.id.type === 'Identifier' &&
          ['ArrowFunctionExpression', 'FunctionExpression'].includes(decl.init?.type)) {
        symbols.push({name: decl.id.name, start: offset(statement.start), end: offset(statement.end)});
      }
    }
  }
  function walk(node) {
    if (!node || typeof node !== 'object') return;
    if (['FunctionDeclaration', 'ClassDeclaration'].includes(node.type) && node.id) {
      declarations.push(node.id.name); bound.add(node.id.name);
    }
    if (node.type === 'VariableDeclarator') for (const name of names(node.id)) bound.add(name);
    if (node.params) for (const p of node.params) for (const name of names(p)) bound.add(name);
    if (node.type === 'CallExpression' && node.callee.type === 'Identifier') calls.push(node.callee.name);
    for (const [key, value] of Object.entries(node)) {
      if (['loc', 'start', 'end'].includes(key)) continue;
      if (Array.isArray(value)) value.forEach(walk);
      else if (value && typeof value === 'object') walk(value);
    }
  }
  walk(tree);
  process.stdout.write(JSON.stringify({symbols, globals, declarations,
    calls: [...new Set(calls)].filter(name => !bound.has(name))}));
} catch (error) {
  process.stdout.write(JSON.stringify({error: String(error.message), line: error.loc?.line || null}));
  process.exitCode = 1;
}
