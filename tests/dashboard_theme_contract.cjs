const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const read = file => fs.readFileSync(path.join(root, file), "utf8");

for (const file of ["dashboard/src/theme.ts", "dashboard/src/ThemeSwitch.tsx"]) assert(fs.existsSync(path.join(root, file)), `${file} must exist`);

const html = read("dashboard/index.html");
const bootstrap = html.indexOf("token-by-token-theme");
const moduleScript = html.indexOf('type="module"');
assert(bootstrap >= 0, "pre-paint theme bootstrap must exist");
assert(moduleScript > bootstrap, "theme bootstrap must run before the module script");
assert.match(html, /prefers-color-scheme/);
assert.match(html, /dataset\.theme/);

const theme = read("dashboard/src/theme.ts");
assert.match(theme, /export type Theme = "light" \| "dark"/);
assert.match(theme, /export function getInitialTheme/);
assert.match(theme, /export function applyTheme/);
assert.match(theme, /token-by-token-theme/);

const component = read("dashboard/src/ThemeSwitch.tsx");
assert.match(component, /aria-pressed/);
assert.match(component, />Light</);
assert.match(component, />Dark</);

const app = read("dashboard/src/App.tsx");
assert.match(app, /<ThemeSwitch/);

const css = read("dashboard/src/styles.css");
assert.match(css, /:root\[data-theme="light"\]/);
assert.match(css, /\.theme-switch/);

console.log("Theme contract passed.");
