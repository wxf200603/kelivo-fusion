/**
 * Runs the real super_admin.js against the bootstrap in
 * scripts/operit_host_bootstrap.js and a mock NativeInterface, to prove the
 * Tools proxy routes every call the way Android's OperitHostDispatcher expects.
 *
 *   node scripts/mock_tools_proxy_test.js
 */
const fs = require('fs');
const path = require('path');

const calls = [];

function json(value) {
    return value === null || value === undefined ? null : JSON.stringify(value);
}

/** Mirrors the branches in OperitHostDispatcher.kt. */
function hostDispatch(method, argsJson) {
    const args = argsJson ? JSON.parse(argsJson) : [];
    calls.push({ method, args });

    switch (method) {
        case 'Tools.System.terminal.create':
            return json({ sessionId: 'sess-1' });
        case 'Tools.System.terminal.exec':
            return json({
                output: `mock output for: ${args[1]}`,
                exitCode: 0,
                sessionId: args[0],
                timedOut: false,
            });
        case 'Tools.System.terminal.screen':
            return json({ sessionId: args[0], rows: 24, cols: 80, content: 'mock screen' });
        case 'Tools.System.terminal.input':
            return null;
        case 'Tools.System.shell':
            return json({ output: 'shell ok', exitCode: 0 });
        case 'Tools.Files.mkdir':
        case 'Tools.Files.write':
            return null;
        default:
            if (method.startsWith('console.')) return null;
            return json({ error: 'NotSupported', method });
    }
}

globalThis.NativeInterface = { __call: hostDispatch };

// The bootstrap ships inside OperitJsRuntime.kt; extract that exact string so
// this test can never drift from what the app actually runs.
const runtimeKt = path.join(
    __dirname,
    '..',
    'android',
    'app',
    'src',
    'main',
    'kotlin',
    'com',
    'psyche',
    'kelivo',
    'quickjs',
    'OperitJsRuntime.kt'
);
const kt = fs.readFileSync(runtimeKt, 'utf8');
const marker = 'HOST_BOOTSTRAP = """';
const start = kt.indexOf(marker);
if (start < 0) throw new Error('HOST_BOOTSTRAP not found in OperitJsRuntime.kt');
const bodyStart = start + marker.length;
const end = kt.indexOf('"""', bodyStart);
if (end < 0) throw new Error('unterminated HOST_BOOTSTRAP');

// Mimic Kotlin's trimIndent().
const rawLines = kt.slice(bodyStart, end).replace(/^\n/, '').split('\n');
const indents = rawLines
    .filter((line) => line.trim().length > 0)
    .map((line) => line.match(/^[ \t]*/)[0].length);
const strip = indents.length ? Math.min(...indents) : 0;
const bootstrap = rawLines
    .map((line) => line.slice(strip))
    .join('\n')
    .replace(/^\n+|\n+$/g, '');

const CLEAN_ON_EXIT = '/data/user/0/com.psyche.kelivo.fusion/app_flutter/environment/tmp/operit-cleanOnExit';
const script = bootstrap.replace(
    "'__KELIVO_CLEAN_ON_EXIT_DIR__'",
    JSON.stringify(CLEAN_ON_EXIT)
);
console.log(`bootstrap source:    OperitJsRuntime.kt (${bootstrap.split('\n').length} lines)`);
new Function(script)();

console.log('Tools defined:      ', typeof globalThis.Tools);
console.log('getChatId():        ', globalThis.getChatId());
console.log('cleanOnExit dir:    ', globalThis.OPERIT_CLEAN_ON_EXIT_DIR);

// --- the real package, loaded the same way callTool() loads it -------------
const pkgPath = path.join(__dirname, '..', 'assets', 'operit_packages', 'super_admin.js');
const source = fs.readFileSync(pkgPath, 'utf8');
const module_ = { exports: {} };
new Function('module', 'exports', `${source}\nreturn module.exports;`)(module_, module_.exports);
const pkg = module_.exports;

console.log('package exports:    ', Object.keys(pkg));

(async () => {
    const result = await pkg.terminal({ command: 'echo hello', timeoutMs: 5000 });

    console.log('\n--- host calls made, in order ---');
    for (const c of calls) {
        console.log(`  ${c.method} ${JSON.stringify(c.args).slice(0, 90)}`);
    }
    console.log('\n--- result returned to the model ---');
    console.log(JSON.stringify(result, null, 2).slice(0, 400));

    const methods = calls.map((c) => c.method);
    const needed = [
        'Tools.System.terminal.create',
        'Tools.System.terminal.exec',
    ];
    const missing = needed.filter((m) => !methods.includes(m));
    console.log('\nmissing expected calls:', missing.length ? missing : 'none');
    console.log(missing.length === 0 ? 'RESULT: PASS' : 'RESULT: FAIL');
})().catch((error) => {
    console.log('\nRESULT: FAIL —', error && error.message);
    console.log(error);
});