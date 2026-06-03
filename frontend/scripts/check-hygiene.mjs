import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../src/', import.meta.url));
const blocked = [
  { pattern: /console\.log/g, label: 'console.log' },
  { pattern: /debugger/g, label: 'debugger' },
  { pattern: /TODO|FIXME/g, label: 'TODO/FIXME' },
  { pattern: /�|锛|绱|璁|鏂|鐭|妫|闃/g, label: 'mojibake' }
];
const extensions = new Set(['.ts', '.tsx', '.js', '.jsx', '.css']);
const failures = [];

function walk(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    const stat = statSync(path);
    if (stat.isDirectory()) {
      walk(path);
      continue;
    }
    if (!extensions.has(path.slice(path.lastIndexOf('.')))) continue;
    const text = readFileSync(path, 'utf8');
    for (const check of blocked) {
      const matches = text.match(check.pattern);
      if (matches) failures.push(`${path}: ${check.label}`);
    }
  }
}

walk(root);

if (failures.length > 0) {
  console.error(failures.join('\n'));
  process.exit(1);
}
