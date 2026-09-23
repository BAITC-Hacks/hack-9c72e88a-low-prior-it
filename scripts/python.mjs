import { existsSync } from 'node:fs';
import { spawn } from 'node:child_process';
const local = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
const command = existsSync(local) ? local : 'uv';
const args = existsSync(local) ? process.argv.slice(2) : ['run', 'python', ...process.argv.slice(2)];
const child = spawn(command, args, { stdio: 'inherit', shell: false });
child.on('error', error => { console.error(error.message); process.exit(1); });
child.on('exit', code => process.exit(code ?? 1));
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
