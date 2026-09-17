/*
 * Operit JS 包 → Kelivo Host API 契约验证器
 *
 * 目的：在没有 Flutter / Android SDK 的环境下，真实加载 Operit 的 super_admin.js，
 *      用 mock 宿主拦截它对 Tools.* 的全部调用，从而精确得到「dispatch 表必须提供什么」。
 *
 * 这不是纸上设计，是实际执行结果。
 */
const path = require('path');
const fs = require('fs');

const PKG = path.join(__dirname, '..', 'assets_operit_packages', 'super_admin.js');
const src = fs.readFileSync(PKG, 'utf8');

// ---------- 1. 验证 METADATA 解析（包加载器必需） ----------
function parseMetadata(source) {
  const m = source.match(/\/\*\s*METADATA\s*([\s\S]*?)\*\//);
  if (!m) throw new Error('METADATA not found');
  return JSON.parse(m[1]);
}
const meta = parseMetadata(src);
console.log('=== [1] METADATA 解析 ===');
console.log('  name        :', meta.name);
console.log('  enabledByDefault:', meta.enabledByDefault);
console.log('  category    :', meta.category);
console.log('  tools       :', meta.tools.map(t => t.name).join(', '));

// ---------- 2. 注入 mock 宿主 ----------
const calls = [];
global.OPERIT_CLEAN_ON_EXIT_DIR = '/tmp/operit_cleanOnExit'; // 宿主注入的全局
global.getChatId = () => 'chat-test-123';                    // 宿主注入的全局

let bigOutputMode = false;
global.Tools = {
  System: {
    terminal: {
      create: async (name) => {
        calls.push({ api: 'Tools.System.terminal.create', args: [name] });
        return { sessionId: 'sess-1' };
      },
      exec: async (sessionId, command, timeout) => {
        calls.push({ api: 'Tools.System.terminal.exec', args: [sessionId, command, timeout] });
        const out = bigOutputMode ? 'X'.repeat(20000) : `mock-output(${command})`;
        return { output: out, exitCode: 0, sessionId, timedOut: false };
      },
      screen: async (sessionId) => {
        calls.push({ api: 'Tools.System.terminal.screen', args: [sessionId] });
        return { sessionId, rows: 24, cols: 80, content: 'mock screen content' };
      },
      input: async (sessionId, opts) => {
        calls.push({ api: 'Tools.System.terminal.input', args: [sessionId, opts] });
        return { ok: true };
      },
    },
    shell: async (command) => {
      calls.push({ api: 'Tools.System.shell', args: [command] });
      return { output: 'uid=0(root)', exitCode: 0 };
    },
  },
  Files: {
    mkdir: async (p, recursive) => { calls.push({ api: 'Tools.Files.mkdir', args: [p, recursive] }); },
    write: async (p, content, append) => {
      calls.push({ api: 'Tools.Files.write', args: [p, `len=${content.length}`, append] });
      fs.writeFileSync('/tmp/_mock_' + path.basename(p), content);
    },
    exists: async (p) => true,
  },
};

// ---------- 3. 加载包（CommonJS exports） ----------
const pkg = require(PKG);
console.log('\n=== [2] 包导出符号 ===');
console.log(' ', Object.keys(pkg).join(', '));

(async () => {
  // ---------- 4. 逐个工具验证 ----------
  console.log('\n=== [3] 工具调用链验证 ===');

  const r1 = await pkg.terminal({ command: 'ls -la', timeoutMs: '5000' });
  console.log('\n[terminal] 返回结构:');
  console.log(' ', JSON.stringify(r1, null, 2).replace(/\n/g, '\n  '));

  const r2 = await pkg.terminal({ command: 'echo bg', background: 'true' });
  console.log('\n[terminal background] 返回:', JSON.stringify(r2));

  const r3 = await pkg.terminal_wait({ timeoutMs: '6000' });
  console.log('\n[terminal_wait] 返回:', JSON.stringify(r3));

  const r4 = await pkg.terminal_getscreen({});
  console.log('\n[terminal_getscreen] 返回:', JSON.stringify(r4));

  const r5 = await pkg.terminal_input({ input: 'pwd', control: 'enter' });
  console.log('\n[terminal_input] 返回:', JSON.stringify(r5));

  const r6 = await pkg.shell({ command: 'pm list packages' });
  console.log('\n[shell] 返回:', JSON.stringify(r6));

  // ---------- 5. 大输出持久化路径 ----------
  bigOutputMode = true;
  const r7 = await pkg.terminal({ command: 'cat bigfile', timeoutMs: '5000' });
  console.log('\n=== [4] 大输出持久化 (>12000 字符) ===');
  console.log(' ', JSON.stringify(r7, null, 2).replace(/\n/g, '\n  '));

  // ---------- 6. 汇总：dispatch 表契约 ----------
  console.log('\n=== [5] dispatch 表必须实现的方法（实测） ===');
  const uniq = [...new Set(calls.map(c => c.api))].sort();
  uniq.forEach(a => console.log('  ' + a));

  console.log('\n=== [6] 各方法的实际参数 ===');
  calls.forEach(c => console.log('  ' + c.api + '(' + c.args.map(a =>
    typeof a === 'object' ? JSON.stringify(a) : JSON.stringify(a)).join(', ') + ')'));
})();
