/**
 * Module-resolution hooks for the scanner: `zod` from SPECDRIFT_ZOD, the
 * @wakeshift/sdk stub, and a `.ts` parent's `./x.js` import of its `./x.ts` file.
 */
import { existsSync } from 'node:fs';
import { registerHooks } from 'node:module';
import { fileURLToPath } from 'node:url';

type ResolveContext = { parentURL?: string };
type ResolveResult = { url: string; shortCircuit?: boolean };
type NextResolve = (specifier: string, context: ResolveContext) => ResolveResult;
type Resolve = (specifier: string, context: ResolveContext, nextResolve: NextResolve) => ResolveResult;

/** The web/ directory, from the CLI path Node puts in argv[1] (no import.meta in detected ESM). */
const WEB = (() => {
  const entry = process.argv[1] ?? '';
  const dir = entry.slice(0, entry.lastIndexOf('/') + 1);
  return new URL(`file://${dir.startsWith('/') ? '' : '/'}${dir}`);
})();

const ROOT = new URL('../', WEB);
const STUB = new URL('wakeshift_stub.ts', WEB).href;

function toUrl(pathOrUrl: string): string {
  return pathOrUrl.startsWith('file:') ? pathOrUrl : new URL(pathOrUrl, ROOT).href;
}

const resolve: Resolve = (specifier, context, nextResolve) => {
  if (specifier === 'zod') {
    const entry = process.env.SPECDRIFT_ZOD;
    if (entry !== undefined && entry !== '') return { url: toUrl(entry), shortCircuit: true };
  }
  if (specifier === '@wakeshift/sdk') return { url: STUB, shortCircuit: true };
  const parent = context.parentURL;
  if (parent !== undefined && parent.endsWith('.ts') && specifier.startsWith('.') && specifier.endsWith('.js')) {
    const candidate = new URL(`${specifier.slice(0, -3)}.ts`, parent);
    if (existsSync(fileURLToPath(candidate))) return { url: candidate.href, shortCircuit: true };
  }
  return nextResolve(specifier, context);
};

registerHooks({ resolve });
