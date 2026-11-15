declare module 'node:fs' {
  export function readFileSync(path: string | URL, encoding: 'utf8' | 'utf-8'): string;
  export function readFileSync(path: string | URL, options: { encoding: 'utf8' | 'utf-8' }): string;
  export function readFileSync(path: string | URL, options?: { encoding?: 'utf8' | 'utf-8' } | null): string | Uint8Array;
  export function writeFileSync(path: string | URL, data: string | Uint8Array, encoding?: 'utf8' | 'utf-8'): void;
  export function existsSync(path: string | URL): boolean;
}

declare module 'node:url' {
  export function fileURLToPath(url: string | URL): string;
}

declare module 'node:module' {
  export function registerHooks(hooks: {
    resolve?: (...args: any[]) => any;
    load?: (...args: any[]) => any;
  }): void;
}

declare const process: {
  env: Record<string, string | undefined>;
  argv: string[];
  exitCode?: number;
  exit(code?: number): never;
  stdout: { write(chunk: string | Uint8Array): boolean };
  stderr: { write(chunk: string | Uint8Array): boolean };
};
